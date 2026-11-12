// Read-aloud engine (framework-free; `useReadAloud` wraps it for React).
//
// Segments are sentences. Consecutive sentences of a paragraph are synthesized together as one part
// (see buildParts): the voice reads connected prose with natural sentence-to-sentence prosody, and
// there is no clip change (= audible gap) between sentences. One part = one request = one clip.
// Inside a part the word timings say which sentence is being read, and prev / next / replay /
// "play from this sentence" seek within the clip.
// Server engine: POST /api/tts -> {audio_url, words: [[start, end] | null, ...]}, audio fetched as a
// blob into one reused <audio> element (iOS only lets a gesture-unlocked element play later). The
// next two parts are prefetched while one plays, so playback continues without a request gap.
// The active word comes from exact server timings, polled per animation frame. Speed = playbackRate
// (browsers preserve pitch).
// Browser engine (Web Speech API): logged-out demo, or no server voice for the language (HTTP 404).
import { api, ApiError, type TtsClip } from "@/lib/api";
import { bcp47, browserSpeechSupported, isoOf, LANGUAGE_NAMES, pickVoice, tokenOffsets } from "./browserSpeech";
import type { AudioSegment, ReadAloudSnapshot } from "./types";

export const RATES = [0.7, 0.85, 1, 1.2];
const RATE_KEY = "lexmatches:tts-rate";
const SPEAKABLE = /[\p{L}\p{N}]/u;
const SENTENCE_END = /[.!?…][»”"')\]]*$/;
// A part takes whole sentences until it has this many characters (~15-20 s of speech, ready in a
// couple of seconds); it never crosses a paragraph (`group`) or a language change.
const PART_CHARS = 280;
const LONG_SEGMENT = 600; // one segment longer than this is cut at a sentence end, then at a comma
const MAX_CLIPS = 40;

/** The words of one segment (or of a piece of a very long one) inside a part. */
export interface Span {
  seg: AudioSegment;
  /** Index of the span's first word within the part's words. */
  start: number;
  /** Index of the span's first word within the segment's words. */
  wordOffset: number;
  count: number;
}

export interface Part {
  lang: string;
  text: string;
  spans: Span[];
}

/** Group segments into parts (server limit is 2000 characters per request). Segments with nothing to say are left out. */
export function buildParts(segments: AudioSegment[]): Part[] {
  const parts: Part[] = [];
  let words: string[] = [], spans: Span[] = [], length = 0, lang = "", group: AudioSegment["group"];
  const flush = () => {
    if (words.length) parts.push({ lang, text: words.join(" "), spans });
    words = [];
    spans = [];
    length = 0;
  };
  for (const seg of segments) {
    const tokens = seg.text.split(/\s+/).filter(Boolean);
    if (!SPEAKABLE.test(seg.text)) continue;
    if (words.length && (seg.lang !== lang || seg.group !== group || length >= PART_CHARS)) flush();
    lang = seg.lang;
    group = seg.group;
    let span: Span = { seg, start: words.length, wordOffset: 0, count: 0 };
    tokens.forEach((token, i) => {
      words.push(token);
      span.count++;
      length += token.length + 1;
      const cut =
        i < tokens.length - 1 &&
        ((length >= LONG_SEGMENT && SENTENCE_END.test(token)) || (length >= 2 * LONG_SEGMENT && /[,;:]$/.test(token)) || length >= 1500);
      if (cut) {
        spans.push(span);
        flush();
        span = { seg, start: 0, wordOffset: i + 1, count: 0 };
      }
    });
    spans.push(span);
  }
  flush();
  return parts;
}

/** The span that word `k` of the part belongs to. */
const spanOfWord = (part: Part, k: number) => {
  let s = 0;
  while (s + 1 < part.spans.length && part.spans[s + 1].start <= k) s++;
  return s;
};

interface LoadedClip {
  url: string;
  words: TtsClip["words"];
}

const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

function storedRate(): number {
  try {
    const r = Number(localStorage.getItem(RATE_KEY));
    return RATES.includes(r) ? r : 1;
  } catch {
    return 1;
  }
}

// 10 ms of silence, played synchronously inside the first user gesture to unlock the element on iOS.
function silentWav(): string {
  const n = 220, buf = new DataView(new ArrayBuffer(44 + n * 2));
  const str = (o: number, s: string) => [...s].forEach((ch, i) => buf.setUint8(o + i, ch.charCodeAt(0)));
  str(0, "RIFF"); buf.setUint32(4, 36 + n * 2, true); str(8, "WAVEfmt "); buf.setUint32(16, 16, true);
  buf.setUint16(20, 1, true); buf.setUint16(22, 1, true); buf.setUint32(24, 22050, true);
  buf.setUint32(28, 44100, true); buf.setUint16(32, 2, true); buf.setUint16(34, 16, true);
  str(36, "data"); buf.setUint32(40, n * 2, true);
  return URL.createObjectURL(new Blob([buf], { type: "audio/wav" }));
}

export class ReadAloudController {
  bookId?: string;
  serverEnabled = true;
  onQueueEnd?: () => boolean | void;
  startAt?: () => string | null | undefined;

  private snapshot: ReadAloudSnapshot = {
    status: "idle", engine: "server", activeId: null, activeWord: null,
    rate: storedRate(), voiceProgress: null, note: null, error: null,
  };
  private listeners = new Set<() => void>();
  private segmentIds = "";
  private parts: Part[] = [];
  private index = -1; // into parts
  private span = 0; // into parts[index].spans: the sentence being read
  private playing: Part | null = null; // the part the loaded clip / utterance was made from
  private wordBase = 0; // browser engine: index of the utterance's first word within the part
  private run = 0; // bumps on every part start/stop: stale async continuations bail out
  private session = 0; // bumps on stop: cancels background waits/prefetch retries
  private audio: HTMLAudioElement | null = null;
  private unlocked = false;
  private current: LoadedClip | null = null;
  private clips = new Map<string, Promise<LoadedClip>>();
  private raf = 0;
  private continueOnNewSegments = false;
  private noServerVoice = new Set<string>(); // ISO codes answered with 404 / "unavailable"

  // ---- store --------------------------------------------------------------------------------
  subscribe = (fn: () => void) => {
    this.listeners.add(fn);
    return () => void this.listeners.delete(fn);
  };
  getSnapshot = () => this.snapshot;

  private set(patch: Partial<ReadAloudSnapshot>) {
    const keys = Object.keys(patch) as (keyof ReadAloudSnapshot)[];
    if (keys.every((k) => this.snapshot[k] === patch[k])) return;
    this.snapshot = { ...this.snapshot, ...patch };
    this.listeners.forEach((fn) => fn());
  }

  // ---- inputs -------------------------------------------------------------------------------
  setSegments(segments: AudioSegment[]) {
    const wasPlaying = this.index >= 0;
    const ids = segments.map((s) => s.id).join("\n");
    const changed = ids !== this.segmentIds;
    this.segmentIds = ids;
    this.parts = buildParts(segments);
    if (changed && this.continueOnNewSegments && this.parts.length) {
      this.continueOnNewSegments = false;
      this.playAt(0, 0);
      return;
    }
    if (!wasPlaying) return;
    // Same page re-rendered (e.g. translation arrived): keep playing; new text is used from the next part.
    const at = this.locate(this.snapshot.activeId);
    if (at) [this.index, this.span] = at;
    else this.stop();
  }

  /** [part, span] of the first piece of segment `id`. */
  private locate(id: string | null | undefined): [number, number] | null {
    for (let i = 0; i < this.parts.length; i++) {
      const s = this.parts[i].spans.findIndex((sp) => sp.seg.id === id);
      if (s >= 0) return [i, s];
    }
    return null;
  }

  /** Prewarm: the server starts downloading/loading the voice; learns early if there is none. */
  prepare(lang: string) {
    if (!this.serverEnabled) return;
    api.ttsPrepare(lang).then((s) => {
      if (s.state === "unavailable") this.noServerVoice.add(isoOf(lang));
    }).catch(() => undefined);
  }

  // ---- controls -----------------------------------------------------------------------------
  playFrom = (id?: string) => {
    this.unlock();
    if (!id && this.index >= 0) return this.playAt(this.index, this.span);
    const at = this.locate(id ?? this.startAt?.()) ?? (id ? null : this.parts.length ? [0, 0] : null);
    if (at) this.playAt(at[0], at[1]);
  };

  toggle = () => {
    const { status } = this.snapshot;
    if (status === "playing") this.pause();
    else if (status === "paused") this.resume();
    else if (status === "loading" || status === "preparing") this.stop();
    else this.playFrom();
  };

  pause = () => {
    if (this.snapshot.status !== "playing") return;
    if (this.snapshot.engine === "browser") window.speechSynthesis.pause();
    else this.audio?.pause();
    cancelAnimationFrame(this.raf);
    this.set({ status: "paused" });
  };

  resume = () => {
    if (this.snapshot.status !== "paused") return;
    this.set({ status: "playing" });
    if (this.snapshot.engine === "browser") window.speechSynthesis.resume();
    else this.audio?.play().then(this.tick, (e) => this.fail(e));
  };

  stop = () => {
    this.run++;
    this.session++;
    this.continueOnNewSegments = false;
    this.halt();
    this.index = -1;
    this.set({ status: "idle", activeId: null, activeWord: null, voiceProgress: null, error: null });
  };

  // next / prev / replay act on sentences (spans).
  next = () => {
    if (this.index < 0) return;
    if (this.span + 1 < this.parts[this.index].spans.length) this.playAt(this.index, this.span + 1);
    else this.playAt(this.index + 1, 0);
  };

  prev = () => {
    if (this.index < 0) return;
    if (this.span > 0) this.playAt(this.index, this.span - 1);
    else if (this.index > 0) this.playAt(this.index - 1, this.parts[this.index - 1].spans.length - 1);
    else this.playAt(0, 0);
  };

  replay = () => {
    if (this.index >= 0) this.playAt(this.index, this.span);
  };

  setRate = (rate: number) => {
    try {
      localStorage.setItem(RATE_KEY, String(rate));
    } catch {
      /* ignore */
    }
    if (this.audio) this.audio.defaultPlaybackRate = this.audio.playbackRate = rate;
    this.set({ rate }); // browser engine: applies from the next part
  };

  dispose() {
    this.stop();
    this.audio?.remove();
    this.audio = null;
    this.unlocked = false;
    this.clips.forEach((p) => p.then((c) => URL.revokeObjectURL(c.url), () => undefined));
    this.clips.clear();
  }

  // ---- playback -----------------------------------------------------------------------------
  private halt() {
    cancelAnimationFrame(this.raf);
    if (this.audio) {
      this.audio.onended = null;
      this.audio.pause();
    }
    if (browserSpeechSupported()) window.speechSynthesis.cancel();
    this.current = null;
    this.playing = null;
  }

  /** Start time of span `s` in the loaded clip (its first timed word). */
  private spanTime(clip: LoadedClip, part: Part, s: number): number {
    if (s === 0) return 0;
    const { start, count } = part.spans[s];
    for (let k = start; k < clip.words.length; k++) {
      const w = clip.words[k];
      if (w) return k < start + count ? w[0] : Math.max(0, w[0] - 0.05);
    }
    return 0;
  }

  /** Read part `i` from its span `s` (sentence) on, then continue with the following parts. */
  private async playAt(i: number, s: number) {
    if (i < 0 || i >= this.parts.length) return this.finish();
    const part = this.parts[i];
    const first = part.spans[s];
    // The sentence is in the clip that is already loaded: seek, no reload and no gap.
    if (this.current && this.audio && this.playing?.text === part.text && this.snapshot.engine === "server") {
      this.index = i;
      this.span = s;
      this.audio.currentTime = this.spanTime(this.current, part, s);
      this.set({ activeId: first.seg.id, activeWord: null });
      return;
    }
    const run = ++this.run;
    this.halt();
    this.index = i;
    this.span = s;
    const engine = this.serverEnabled && !this.noServerVoice.has(isoOf(part.lang)) ? "server" : "browser";
    this.set({
      activeId: first.seg.id, activeWord: null, engine, error: null, voiceProgress: null,
      status: this.snapshot.status === "playing" ? "playing" : "loading",
      note: engine === "browser" ? this.browserNote(part.lang) : null,
    });
    if (engine === "browser") return this.speak(part, s, run);
    try {
      const clip = await this.load(part);
      if (run !== this.run) return;
      this.current = clip;
      this.playing = part;
      const audio = this.element();
      audio.src = clip.url;
      audio.defaultPlaybackRate = audio.playbackRate = this.snapshot.rate;
      audio.onended = () => run === this.run && this.playAt(this.index + 1, 0);
      const from = this.spanTime(clip, part, s);
      if (from > 0) {
        await new Promise<void>((resolve) => {
          if (audio.readyState >= 1) resolve();
          else audio.addEventListener("loadedmetadata", () => resolve(), { once: true });
        });
        if (run !== this.run) return;
        audio.currentTime = from;
      }
      // Paused while this part was loading (e.g. Space right after jumping): stay paused; resume() plays it.
      if (this.snapshot.status === "paused") return;
      await audio.play();
      if (run !== this.run) return;
      this.set({ status: "playing", voiceProgress: null });
      this.tick();
      for (const n of [i + 1, i + 2]) if (n < this.parts.length) this.load(this.parts[n]).catch(() => undefined);
    } catch (e) {
      if (run !== this.run) return;
      if (e instanceof ApiError && e.status === 404) {
        this.noServerVoice.add(isoOf(part.lang));
        return this.playAt(i, s); // retried with the browser engine
      }
      this.fail(e);
    }
  }

  /** Word `k` of the playing part is being spoken: publish its sentence and word. */
  private at(part: Part, k: number | null) {
    if (k === null) return this.set({ activeWord: null });
    const s = spanOfWord(part, k);
    if (part === this.parts[this.index] || part.text === this.parts[this.index]?.text) this.span = s;
    this.set({ activeId: part.spans[s].seg.id, activeWord: part.spans[s].wordOffset + k - part.spans[s].start });
  }

  private finish() {
    this.halt();
    this.run++;
    this.index = -1;
    this.continueOnNewSegments = true;
    const continues = this.onQueueEnd?.() === true;
    this.continueOnNewSegments = continues;
    this.set({ status: continues ? "loading" : "idle", activeId: null, activeWord: null });
  }

  private tick = () => {
    const clip = this.current, audio = this.audio, part = this.playing;
    if (!clip || !audio || !part || this.snapshot.status !== "playing") return;
    const t = audio.currentTime + 0.03; // ~ one frame of render latency
    let word: number | null = null;
    for (let k = 0; k < clip.words.length; k++) {
      const w = clip.words[k];
      if (!w) continue;
      if (w[0] > t) break;
      word = k; // stays on the last started word through pauses
    }
    this.at(part, word);
    this.raf = requestAnimationFrame(this.tick);
  };

  private fail(e: unknown) {
    this.halt();
    const message = e instanceof Error ? e.message : String(e);
    const blocked = e instanceof DOMException && e.name === "NotAllowedError";
    this.set({ status: "error", activeWord: null, voiceProgress: null, error: blocked ? "Tap play to start audio" : message });
  }

  // ---- server clips -------------------------------------------------------------------------
  private load(part: Part): Promise<LoadedClip> {
    const key = `${part.lang}\n${part.text}`;
    let p = this.clips.get(key);
    if (!p) {
      p = this.fetchClip(part);
      this.clips.set(key, p);
      p.catch(() => this.clips.delete(key));
      if (this.clips.size > MAX_CLIPS) {
        const [oldKey, old] = this.clips.entries().next().value as [string, Promise<LoadedClip>];
        this.clips.delete(oldKey);
        old.then((c) => c !== this.current && URL.revokeObjectURL(c.url), () => undefined);
      }
    }
    return p;
  }

  private async fetchClip(part: Part): Promise<LoadedClip> {
    const session = this.session;
    for (let networkRetries = 2; ; ) {
      try {
        const meta = await api.ttsClip(part.text, part.lang, this.bookId);
        const blob = await api.ttsAudio(meta.audio_url);
        return { url: URL.createObjectURL(blob), words: meta.words };
      } catch (e) {
        const network = e instanceof TypeError && networkRetries-- > 0; // fetch() failed (connection dropped)
        const retryable = network || (e instanceof ApiError && (e.status === 503 || e.status === 429));
        if (!retryable || session !== this.session) throw e;
        if (e instanceof ApiError && e.status === 503 && /voice/i.test(e.message)) await this.waitForVoice(part, session);
        else await wait(network ? 800 : 2500);
      }
    }
  }

  /** Voice still downloading on the server: show progress while polling /tts/prepare. */
  private async waitForVoice(part: Part, session: number) {
    for (;;) {
      const status = await api.ttsPrepare(part.lang).catch(() => null);
      if (session !== this.session) throw new Error("cancelled");
      if (status?.state === "error") throw new Error(status.error || "Voice download failed");
      if (status && status.state !== "downloading" && status.state !== "missing") return;
      if (this.parts[this.index] === part) this.set({ status: "preparing", voiceProgress: status?.progress ?? 0 });
      await wait(1500);
    }
  }

  private element(): HTMLAudioElement {
    if (!this.audio) {
      const a = document.createElement("audio");
      a.preload = "auto";
      a.hidden = true;
      a.setAttribute("data-testid", "read-aloud-audio");
      a.preservesPitch = true;
      document.body.appendChild(a);
      this.audio = a;
    }
    return this.audio;
  }

  private unlock() {
    if (this.unlocked || !this.serverEnabled) return;
    this.unlocked = true;
    const a = this.element();
    a.src = silentWav();
    a.play().catch(() => undefined);
  }

  // ---- browser speech -----------------------------------------------------------------------
  private browserNote(lang: string): string {
    const name = LANGUAGE_NAMES[isoOf(lang)] ?? lang;
    if (!browserSpeechSupported()) return "Speech is not supported in this browser";
    const reason = this.serverEnabled ? `no server voice for ${name}` : "sign in for natural voices";
    return pickVoice(lang) ? `Browser voice (${reason})` : `No ${name} voice in this browser`;
  }

  private speak(part: Part, s: number, run: number) {
    if (!browserSpeechSupported()) return this.fail(new Error("Speech is not supported in this browser"));
    // The browser cannot seek inside an utterance: speak the part from the chosen sentence on.
    this.wordBase = part.spans[s].start;
    const text = part.text.split(" ").slice(this.wordBase).join(" ");
    const u = new SpeechSynthesisUtterance(text);
    const voice = pickVoice(part.lang);
    if (voice) u.voice = voice;
    u.lang = voice?.lang ?? bcp47(part.lang);
    u.rate = 0.9 * this.snapshot.rate;
    const offsets = tokenOffsets(text);
    u.onstart = () => run === this.run && this.set({ status: "playing" });
    u.onboundary = (e) => {
      if (run !== this.run || e.name !== "word") return;
      let w = 0;
      while (w + 1 < offsets.length && offsets[w + 1] <= e.charIndex) w++;
      this.at(part, this.wordBase + w);
    };
    u.onend = () => run === this.run && this.playAt(this.index + 1, 0);
    u.onerror = (e) => {
      if (run === this.run && e.error !== "canceled" && e.error !== "interrupted") this.fail(new Error(`Speech failed (${e.error})`));
    };
    window.speechSynthesis.speak(u);
  }
}
