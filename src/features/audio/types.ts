/** One unit of read-aloud and highlighting: a sentence. `id` must be unique across pages. */
export interface AudioSegment {
  id: string;
  text: string;
  /** Book locale as stored ("french") or an ISO code ("fr"). */
  lang: string;
  /** Paragraph key: consecutive segments of one group are spoken together as connected prose. */
  group?: string | number;
}

export type ReadAloudStatus = "idle" | "preparing" | "loading" | "playing" | "paused" | "error";

export interface ReadAloudSnapshot {
  status: ReadAloudStatus;
  /** "server" = Piper/ElevenLabs audio with exact word timings; "browser" = Web Speech API. */
  engine: "server" | "browser";
  activeId: string | null;
  /** Index of the spoken word in the active segment's `text.split(/\s+/)` (null between words / idle). */
  activeWord: number | null;
  rate: number;
  /** 0..1 while the server downloads the voice (status "preparing"). */
  voiceProgress: number | null;
  /** Short user-facing note, e.g. why the browser voice is used. */
  note: string | null;
  error: string | null;
}

export interface ReadAloudOptions {
  segments: AudioSegment[];
  /** Cache scope on the server; the book's cached audio is deleted with the book. */
  bookId?: string;
  /** false = browser speech only (logged-out demo). Default true. */
  serverEnabled?: boolean;
  /**
   * Called after the last segment finished. Return true if you moved on (e.g. to the next page):
   * playback then continues from the first segment of the next `segments` list you pass in.
   */
  onQueueEnd?: () => boolean | void;
  /** Where play() starts when nothing is active, e.g. the first line visible on screen. Default: first segment. */
  startAt?: () => string | null | undefined;
}

export interface ReadAloud extends ReadAloudSnapshot {
  /** Start reading at segment `id` (default: the active or first segment) and continue to the end. */
  playFrom(id?: string): void;
  toggle(): void;
  pause(): void;
  resume(): void;
  stop(): void;
  /** next / prev / replay act on sentences (segments). */
  next(): void;
  prev(): void;
  /** Restart the current sentence (learners: "say that again"). */
  replay(): void;
  setRate(rate: number): void;
  /** Active word index for a segment, or null if that segment is not being read. */
  wordFor(id: string): number | null;
}
