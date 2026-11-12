// The reader: original text as paragraphs of sentences, optional interlinear glosses under word chunks,
// natural sentence translations on demand, read-aloud with sentence + word highlight.
//
// Help model: the learner reads the original and looks up only what they do not know.
//   - click / tap a word or phrase -> its gloss under it (again to hide)
//   - ↑ / ↓                        -> move the current line (a dot in the left margin), scrolling line by line
//   - ← / → (same thing), G, "Glosses" -> all glosses of the page on / off
//   - L, "Line"                    -> line mode: only the current line shows its glosses; they follow ↑ / ↓
//   - "Translation" (T)            -> natural translation after every paragraph (side by side on wide screens)
//   - Enter                        -> natural translation of the current line's sentence
// The gloss row is always reserved, so nothing moves when a gloss appears. Every lookup (not hiding)
// counts as one "translation toggle click" for the Progress page (reading_sessions) and in the dock.
// Pages are turned with the buttons. While read-aloud is active, tapping a sentence jumps playback there.
import { Fragment, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { AArrowDown, AArrowUp, ChevronLeft, ChevronRight, Languages, Play, Rows3, WholeWord } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Tip } from "@/components/Tip";
import { api, isLoggedIn, type TranslationData } from "@/lib/api";
import { isShortcutEvent } from "@/lib/keys";
import { buildReaderModel, type ReaderSentence } from "@/lib/readingModel";
import { cn } from "@/lib/utils";
import { ReadAloudBar, useReadAloud, wordToGroup, type AudioSegment } from "@/features/audio";

const PREFS_KEY = "lexmatches:reader:v2"; // v2: glosses are off by default (the reader looks words up)
interface Prefs {
  glosses: boolean;
  translations: boolean;
  /** Line mode: the glosses of the current line only (the line followed with ↑ / ↓). */
  line: boolean;
  /** Index into TEXT_SCALES. */
  size: number;
}
const TEXT_SCALES = [0.85, 1, 1.15, 1.3, 1.5];
const DEFAULT_PREFS: Prefs = { glosses: false, translations: false, line: false, size: 1 };
function loadPrefs(): Prefs {
  try {
    return { ...DEFAULT_PREFS, ...JSON.parse(localStorage.getItem(PREFS_KEY) ?? "{}") };
  } catch {
    return DEFAULT_PREFS;
  }
}

/** The tokens on the same visual line as `el` (a line is measured, not stored). */
const lineOf = (all: HTMLElement[], el: HTMLElement) => {
  const top = el.getBoundingClientRect().top;
  return all.filter((t) => Math.abs(t.getBoundingClientRect().top - top) < 6);
};

const HEADER_PX = 72; // sticky header height + margin
const DOCK_PX = 88;
const CJK = /[\u3040-\u30ff\u3400-\u9fff]/;

interface ReadingViewProps {
  pageNumber: number;
  totalPages: number;
  originalText: string;
  translationData?: TranslationData | null;
  bookId: string;
  originalLocale?: string;
  onNextPage: () => void;
  onPrevPage: () => void;
  /** Status / action banner shown above the text (translate button, progress, errors). */
  banner?: ReactNode;
  /** Landing-page demo: controls inline instead of docked, no shortcuts, nothing recorded. */
  demo?: boolean;
}

const ReadingView = ({
  pageNumber,
  totalPages,
  originalText,
  translationData,
  bookId,
  originalLocale,
  onNextPage,
  onPrevPage,
  banner,
  demo = false,
}: ReadingViewProps) => {
  const model = useMemo(() => buildReaderModel(originalText, translationData), [originalText, translationData]);
  const cjk = useMemo(() => CJK.test(originalText.slice(0, 400)), [originalText]);
  const [prefs, setPrefs] = useState<Prefs>(loadPrefs);
  const [revealed, setRevealed] = useState<Set<number>>(new Set());
  const [clickCount, setClickCount] = useState(0);
  const glossesOn = prefs.glosses && model.hasGlosses;
  const translationsOn = prefs.translations && model.hasTranslations;

  const updatePrefs = useCallback((patch: Partial<Prefs>) => {
    setPrefs((prev) => {
      const next = { ...prev, ...patch };
      try {
        localStorage.setItem(PREFS_KEY, JSON.stringify(next));
      } catch {
        /* ignore */
      }
      return next;
    });
  }, []);
  const countHelp = useCallback(() => setClickCount((c) => c + 1), []);

  // A display change (glosses, translations, text size) changes line heights: keep the line the
  // reader is looking at (the first words below the header) where it is instead of letting the text jump.
  const anchorRef = useRef<{ el: HTMLElement; top: number } | null>(null);
  const holdPosition = useCallback(() => {
    const el = Array.from(document.querySelectorAll<HTMLElement>(".reading-text .chunk, .reading-text .word")).find(
      (e) => e.getBoundingClientRect().bottom > HEADER_PX,
    );
    anchorRef.current = el ? { el, top: el.getBoundingClientRect().top } : null;
  }, []);
  const sizeIndex = Math.min(TEXT_SCALES.length - 1, Math.max(0, Math.round(Number(prefs.size)) || 0));
  useLayoutEffect(() => {
    const anchor = anchorRef.current;
    anchorRef.current = null;
    if (anchor?.el.isConnected) window.scrollBy(0, anchor.el.getBoundingClientRect().top - anchor.top);
  }, [glossesOn, translationsOn, sizeIndex]);

  // Only asking for help counts as a lookup, not hiding it again.
  const toggleGlosses = useCallback(() => {
    holdPosition();
    updatePrefs({ glosses: !prefs.glosses });
    if (!prefs.glosses) countHelp();
  }, [prefs.glosses, updatePrefs, countHelp, holdPosition]);
  const toggleTranslations = useCallback(() => {
    holdPosition();
    updatePrefs({ translations: !prefs.translations });
    if (!prefs.translations) countHelp();
  }, [prefs.translations, updatePrefs, countHelp, holdPosition]);

  // ---- Lookups: the reader reads the original and reveals the gloss of a word / phrase they do not
  // know (click or tap), or of the whole page (← / →, G). ↑ / ↓ move the current line. Tokens are
  // the [data-tok] elements (chunks, or words on an untranslated page); a line is a row of tokens as
  // laid out on screen, so it is measured, not stored.
  const articleRef = useRef<HTMLElement>(null);
  const [shown, setShown] = useState<Set<string>>(new Set()); // chunk keys "<sentence>:<chunk>"
  const [cursor, setCursor] = useState<string | null>(null); // a token of the current line
  const tokens = useCallback(() => Array.from(articleRef.current?.querySelectorAll<HTMLElement>("[data-tok]") ?? []), []);
  /** The cursor's token, or (first use) the first token fully below the header. */
  const currentToken = useCallback(
    (all: HTMLElement[]) =>
      (cursor && all.find((t) => t.dataset.tok === cursor)) || all.find((t) => t.getBoundingClientRect().top >= HEADER_PX) || all[0],
    [cursor],
  );
  const toggleChunk = useCallback(
    (key: string) => {
      setCursor(key);
      if (!shown.has(key)) countHelp();
      setShown((prev) => {
        const next = new Set(prev);
        if (!next.delete(key)) next.add(key);
        return next;
      });
    },
    [shown, countHelp],
  );
  const moveLine = useCallback(
    (dir: 1 | -1) => {
      const all = tokens();
      const cur = currentToken(all);
      if (!cur) return;
      if (!cursor) return setCursor(cur.dataset.tok!); // first press: mark the line the reader is at
      const line = lineOf(all, cur);
      const next = all[all.indexOf(dir > 0 ? line[line.length - 1] : line[0]) + dir];
      if (!next) return;
      setCursor(next.dataset.tok!);
      // Scroll by exactly one line once the current line leaves the comfortable part of the window.
      const from = cur.getBoundingClientRect().top;
      const to = next.getBoundingClientRect().top;
      if (dir > 0 ? to > window.innerHeight * 0.5 : to < HEADER_PX + window.innerHeight * 0.2) {
        const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        window.scrollBy({ top: to - from, behavior: reduced ? "auto" : "smooth" });
      }
    },
    [tokens, currentToken, cursor],
  );
  // The current line is marked by a small dot in the left margin that slides between lines (CSS
  // transition). Its position is measured, so it is re-done whenever the layout can change.
  const [dotTop, setDotTop] = useState<number | null>(null);
  // Line mode: the tokens of the current line; their glosses are shown, nothing else is.
  const lineOn = prefs.line && model.hasGlosses && !glossesOn;
  const [lineKeys, setLineKeys] = useState<Set<string>>(new Set());
  // ← / → in line mode: the line's glosses off (read unaided, keep moving) and on again when needed.
  const [lineHelp, setLineHelp] = useState(true);
  const toggleLineHelp = useCallback(() => {
    if (!lineHelp) countHelp();
    setLineHelp(!lineHelp);
  }, [lineHelp, countHelp]);
  const toggleLine = useCallback(() => {
    updatePrefs({ line: !prefs.line });
    setLineHelp(true);
    if (prefs.line) return;
    countHelp(); // turning the help on is one lookup; following the text line by line is not counted again
    if (!cursor) {
      const first = currentToken(tokens());
      if (first) setCursor(first.dataset.tok!);
    }
  }, [prefs.line, updatePrefs, countHelp, cursor, currentToken, tokens]);
  const [viewport, setViewport] = useState(0);
  useEffect(() => {
    const onResize = () => setViewport(window.innerWidth);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  useLayoutEffect(() => {
    const article = articleRef.current;
    const cur = cursor ? tokens().find((t) => t.dataset.tok === cursor) : undefined;
    if (!article || !cur) {
      setLineKeys((prev) => (prev.size ? new Set() : prev));
      return setDotTop(null);
    }
    const words = (cur.querySelector(".chunk-src") ?? cur).getBoundingClientRect(); // the source words, not the gloss
    setDotTop(words.top + words.height / 2 - article.getBoundingClientRect().top);
    // A line is a row of tokens as laid out; showing a gloss never moves a word, so the row is stable.
    const keys = lineOn && lineHelp ? lineOf(tokens(), cur).map((t) => t.dataset.tok!) : [];
    setLineKeys((prev) => (prev.size === keys.length && keys.every((k) => prev.has(k)) ? prev : new Set(keys)));
  }, [cursor, model, sizeIndex, translationsOn, viewport, tokens, lineOn, lineHelp]);
  const resize = useCallback(
    (step: number) => {
      const next = Math.min(TEXT_SCALES.length - 1, Math.max(0, sizeIndex + step));
      if (next === sizeIndex) return;
      holdPosition();
      updatePrefs({ size: next });
    },
    [sizeIndex, updatePrefs, holdPosition],
  );

  // ---- Read aloud (src/features/audio): one segment per sentence, id "<page>:<sentence index>" ----
  const segmentId = useCallback((i: number) => `${pageNumber}:${i}`, [pageNumber]);
  // `group` = paragraph: its sentences are spoken together as connected prose (one clip, no gaps).
  const ttsSegments = useMemo<AudioSegment[]>(
    () =>
      model.paragraphs.flatMap((p) =>
        p.sentences
          .filter((s) => s.source?.trim())
          .map((s) => ({ id: segmentId(s.index), text: s.source!, lang: originalLocale ?? "en", group: p.key })),
      ),
    [model.paragraphs, segmentId, originalLocale],
  );
  const wordToChunk = useMemo(
    () => model.sentences.map((s) => (s.chunks ? wordToGroup(s.chunks.map((c) => c.original)) : null)),
    [model.sentences],
  );
  const reader = useReadAloud({
    segments: ttsSegments,
    bookId: demo ? undefined : bookId,
    serverEnabled: !demo && isLoggedIn(),
    onQueueEnd: () => {
      if (demo || pageNumber >= totalPages) return false;
      onNextPage(); // keep reading on the next page
      return true;
    },
    // Play starts at the first sentence visible below the header.
    startAt: () => {
      const el = Array.from(document.querySelectorAll<HTMLElement>("[data-sentence]")).find(
        (e) => e.getBoundingClientRect().bottom > HEADER_PX,
      );
      return el ? segmentId(Number(el.dataset.sentence)) : undefined;
    },
  });
  const audioActive = reader.status !== "idle" && reader.status !== "error";

  // Keep the sentence being read on screen (between the header and the dock).
  useEffect(() => {
    if (!reader.activeId || demo) return;
    const el = document.querySelector<HTMLElement>(`[data-segment="${reader.activeId}"]`);
    if (!el) return;
    const r = el.getBoundingClientRect();
    if (r.top < HEADER_PX || r.bottom > window.innerHeight - DOCK_PX) el.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [reader.activeId, demo]);

  /** Enter: the natural translation of the current line's sentence. */
  const activateSentence = (s: ReaderSentence) => {
    if (!s.chunks && !s.translation) return;
    setRevealed((prev) => {
      const next = new Set(prev);
      if (next.has(s.index)) next.delete(s.index);
      else {
        next.add(s.index);
        countHelp();
      }
      return next;
    });
  };

  // ---- Help-click tracking -> reading_sessions (flushed on page change, tab hide and unmount) ----
  const pendingRef = useRef<{ page: number; clicks: number } | null>(null);
  const flushClicks = useCallback(async () => {
    const pending = pendingRef.current;
    if (!pending || pending.clicks === 0) return;
    pendingRef.current = null;
    if (demo || !isLoggedIn()) return;
    try {
      await api.saveReadingSession({
        book_id: bookId,
        page_number: pending.page,
        session_date: new Date().toISOString().split("T")[0],
        translation_toggle_clicks: pending.clicks,
      });
    } catch (error) {
      console.error("Error saving reading session:", error);
      pendingRef.current = pending; // retried on the next flush
    }
  }, [bookId, demo]);

  useEffect(() => {
    if (clickCount === 0) return;
    pendingRef.current = { page: pageNumber, clicks: clickCount };
    const t = setTimeout(() => void flushClicks(), 800);
    return () => clearTimeout(t);
  }, [clickCount, pageNumber, flushClicks]);

  useEffect(() => {
    const onHide = () => void flushClicks();
    document.addEventListener("visibilitychange", onHide);
    window.addEventListener("pagehide", onHide);
    return () => {
      document.removeEventListener("visibilitychange", onHide);
      window.removeEventListener("pagehide", onHide);
      void flushClicks();
    };
  }, [flushClicks]);

  useEffect(() => {
    void flushClicks();
    setClickCount(0);
    setRevealed(new Set());
    setShown(new Set());
    setCursor(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset per page only
  }, [pageNumber]);

  // ---- Shortcuts: ↑/↓ line, ←/→ or G all glosses, T translations, -/+ text size
  // (Space / R / [ / ] are the player's). Pages are turned with the buttons. In the landing-page demo
  // only the arrows work, and only while the pointer or the focus is on the demo. ----
  const demoActive = useRef(false);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!isShortcutEvent(e) || e.shiftKey) return;
      if (demo && !demoActive.current) return;
      // e.code as well: the letter keys must work on non-Latin keyboard layouts too.
      const key = e.key.toLowerCase();
      if (e.key === "ArrowDown") moveLine(1);
      else if (e.key === "ArrowUp") moveLine(-1);
      else if ((e.key === "ArrowLeft" || e.key === "ArrowRight") && model.hasGlosses) (lineOn ? toggleLineHelp : toggleGlosses)();
      else if (e.key === "Enter" && cursor) {
        // the natural translation of the sentence the current line starts in
        const sentence = model.sentences[parseInt(cursor, 10)];
        if (sentence) activateSentence(sentence);
      } else if (demo) return;
      else if ((key === "g" || e.code === "KeyG") && model.hasGlosses) toggleGlosses();
      else if ((key === "l" || e.code === "KeyL") && model.hasGlosses) toggleLine();
      else if ((key === "t" || e.code === "KeyT") && model.hasTranslations) toggleTranslations();
      else if (e.key === "+" || e.key === "=") resize(1);
      else if (e.key === "-") resize(-1);
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- activateSentence only uses state setters
  }, [demo, model, cursor, lineOn, toggleGlosses, toggleLine, toggleLineHelp, toggleTranslations, resize, moveLine]);

  // ---- Bookmark: remember the top visible sentence of this book; restore it once ----
  const bookmarkKey = `lexmatches:bookmark:${bookId}`;
  const restoredRef = useRef(false);
  useEffect(() => {
    if (demo) return;
    let t: ReturnType<typeof setTimeout> | undefined;
    const save = () => {
      const top = Array.from(document.querySelectorAll<HTMLElement>("[data-sentence]")).find(
        (e) => e.getBoundingClientRect().bottom > HEADER_PX,
      );
      try {
        localStorage.setItem(bookmarkKey, JSON.stringify({ page: pageNumber, sentence: Number(top?.dataset.sentence ?? 0) }));
      } catch {
        /* ignore */
      }
    };
    const onScroll = () => {
      clearTimeout(t);
      t = setTimeout(save, 300);
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      window.removeEventListener("scroll", onScroll);
      clearTimeout(t);
    };
  }, [bookmarkKey, pageNumber, demo]);

  useEffect(() => {
    if (demo || restoredRef.current || model.total === 0) return;
    restoredRef.current = true;
    let saved: { page?: number; sentence?: number } | null = null;
    try {
      saved = JSON.parse(localStorage.getItem(bookmarkKey) ?? "null");
    } catch {
      saved = null;
    }
    if (saved?.page !== pageNumber || !saved.sentence) return;
    const el = document.querySelector<HTMLElement>(`[data-sentence="${saved.sentence}"]`);
    if (el) window.scrollTo({ top: Math.max(0, el.getBoundingClientRect().top + window.scrollY - HEADER_PX - 16) });
  }, [model.total, bookmarkKey, pageNumber, demo]);

  // ---- Render ----
  const activeIndex =
    audioActive && reader.activeId?.startsWith(`${pageNumber}:`) ? Number(reader.activeId.split(":")[1]) : null;
  const activeWord = activeIndex === null ? null : reader.wordFor(segmentId(activeIndex));

  const toggles = (
    <div className="flex items-center gap-1" role="group" aria-label="Reading help">
      {!demo && (
        <>
          <Tip label="Smaller text (−)" side="top">
            <Button variant="ghost" size="icon" className="h-9 w-9 rounded-full text-muted-foreground" aria-label="Smaller text"
              disabled={sizeIndex === 0} onClick={() => resize(-1)} onMouseDown={(e) => e.preventDefault()}>
              <AArrowDown />
            </Button>
          </Tip>
          <Tip label="Larger text (+)" side="top">
            <Button variant="ghost" size="icon" className="h-9 w-9 rounded-full text-muted-foreground" aria-label="Larger text"
              disabled={sizeIndex === TEXT_SCALES.length - 1} onClick={() => resize(1)} onMouseDown={(e) => e.preventDefault()}>
              <AArrowUp />
            </Button>
          </Tip>
        </>
      )}
      {model.hasGlosses && (
        <HelpToggle pressed={glossesOn} onClick={toggleGlosses} label="Glosses" tip={demo ? "Show all glosses" : "Show all glosses (G)"} icon={<WholeWord />} />
      )}
      {model.hasGlosses && !demo && (
        <HelpToggle pressed={lineOn} onClick={toggleLine} label="Line" tip="Glosses for the line you are on only; move with ↑ ↓, hide or show with ← → (L)" icon={<Rows3 />} />
      )}
      {model.hasTranslations && (
        <HelpToggle pressed={translationsOn}onClick={toggleTranslations} label="Translation" tip={demo ? "Sentence translations" : "Sentence translations (T)"} icon={<Languages />} />
      )}
      {model.hasGlosses && (
        <Tip label="Times you asked for a translation on this page" side="top">
          <span className="ml-1 whitespace-nowrap rounded-full bg-muted px-2.5 py-1 text-xs tabular-nums text-muted-foreground" data-testid="lookup-count">
            {clickCount} {clickCount === 1 ? "lookup" : "lookups"}
          </span>
        </Tip>
      )}
    </div>
  );
  const player = ttsSegments.length > 0 && (
    <ReadAloudBar player={reader} shortcuts={!demo} className="border-0 bg-transparent p-0 shadow-none backdrop-blur-none" />
  );

  return (
    <div
      className={cn(!demo && "pb-28")}
      style={{ "--reader-scale": demo ? 1 : TEXT_SCALES[sizeIndex] } as CSSProperties}
      onPointerEnter={() => (demoActive.current = true)}
      onPointerLeave={() => (demoActive.current = false)}
      onPointerDown={() => (demoActive.current = true)}
    >
      <div className={cn("reader-column mx-auto w-full px-4 sm:px-6")} data-translations={translationsOn || undefined}>
        {demo ? (
          <div className="mb-6 flex flex-wrap items-center justify-between gap-2 rounded-full border bg-background/80 px-2 py-1 shadow-sm">
            {toggles}
            {player}
          </div>
        ) : totalPages > 1 ? (
          <PageNav pageNumber={pageNumber} totalPages={totalPages} onPrev={onPrevPage} onNext={onNextPage} />
        ) : (
          <div className="h-6" />
        )}

        {banner}

        <article
          ref={articleRef}
          className="reading-text"
          lang={originalLocale}
          data-glosses={glossesOn || undefined}
          data-translations={translationsOn || undefined}
          aria-label={`Page ${pageNumber} text`}
        >
          {dotTop !== null && <span className="line-dot" data-testid="line-dot" style={{ top: dotTop }} aria-hidden />}
          {model.paragraphs.map((p) => {
            const paragraphTranslation = translationsOn
              ? p.sentences.map((s) => s.translation).filter(Boolean).join(" ")
              : "";
            return (
              <div key={p.key} className="para">
                <p className="para-src">
                  {p.sentences.map((s) => {
                    const isActive = activeIndex === s.index;
                    const isRevealed = revealed.has(s.index);
                    const glossed = Boolean(s.chunks) && (glossesOn || isRevealed);
                    const activeGroup = isActive && activeWord !== null ? (s.chunks ? wordToChunk[s.index]?.[activeWord] ?? null : activeWord) : null;
                    return (
                      <Fragment key={s.index}>
                        {s.source === null ? (
                          <span className="sentence-placeholder" aria-label="Translating…" />
                        ) : (
                          <span
                            className="sentence"
                            data-sentence={s.index}
                            data-segment={segmentId(s.index)}
                            data-active={isActive || undefined}
                            data-revealed={isRevealed || undefined}
                            data-helpable={audioActive || undefined}
                            onClick={() => {
                              // While listening, a tap jumps playback to this sentence.
                              if (audioActive && s.source && !window.getSelection()?.toString()) reader.playFrom(segmentId(s.index));
                            }}
                          >
                            <SentenceText s={s} glossed={glossed} shown={shown} line={lineKeys} onChunk={audioActive ? undefined : toggleChunk} activeGroup={activeGroup} cjk={cjk} />
                          </span>
                        )}
                        {isRevealed && (
                          <span className="sentence-help" data-testid="sentence-help">
                            {s.translation && <span className="sentence-help-text">{s.translation}</span>}
                            {s.source && (
                              <button
                                type="button"
                                className="sentence-help-listen"
                                onClick={() => reader.playFrom(segmentId(s.index))}
                              >
                                <Play className="h-3 w-3" aria-hidden /> Listen from here
                              </button>
                            )}
                          </span>
                        )}
                        {!cjk && " "}
                      </Fragment>
                    );
                  })}
                </p>
                {paragraphTranslation && <p className="para-translation">{paragraphTranslation}</p>}
              </div>
            );
          })}
        </article>

        {!demo && totalPages > 1 && (
          <div className="mt-10 flex items-center justify-between gap-3 border-t pt-6">
            <Button variant="outline" onClick={onPrevPage} disabled={pageNumber <= 1}>
              <ChevronLeft /> Previous
            </Button>
            <span className="text-sm text-muted-foreground">
              {pageNumber} / {totalPages}
            </span>
            <Button onClick={onNextPage} disabled={pageNumber >= totalPages}>
              Next page <ChevronRight />
            </Button>
          </div>
        )}
      </div>

      {!demo && (toggles || player) && (
        <div
          className="fixed inset-x-0 bottom-0 z-40 border-t bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/80"
          data-testid="reader-dock"
        >
          <div className="mx-auto flex max-w-4xl items-center justify-between gap-2 px-3 pt-2 pb-[max(0.5rem,env(safe-area-inset-bottom))] sm:px-6">
            {toggles || <span />}
            {player}
          </div>
        </div>
      )}
    </div>
  );
};

/** Rough text width in em of the reading font size (CJK glyphs are full width). */
const emWidth = (text: string, latin: number) =>
  Array.from(text).reduce((w, ch) => w + (CJK.test(ch) ? 1 : latin), 0);
const GLOSS_SLACK_EM = 0.6;
/** A gloss that is at most a little wider than its chunk stays on one line (the column grows by up
 *  to the slack). A longer one wraps under the chunk instead of pushing the next words away; the
 *  column is then at least wide enough for the gloss to fit on two lines. */
function glossLayout(original: string, gloss: string): { oneLine: boolean; minWidth?: string } {
  const g = 0.66 * emWidth(gloss, 0.52);
  if (g <= emWidth(original, 0.45) + GLOSS_SLACK_EM) return { oneLine: true };
  return { oneLine: false, minWidth: `${(g * 0.7).toFixed(2)}em` };
}

function SentenceText({
  s, glossed, shown, line, onChunk, activeGroup, cjk,
}: {
  /** Chunks of the current line while line mode is on. */
  line: Set<string>;
  s: ReaderSentence;
  /** All glosses of the sentence are shown (Glosses on, or the sentence is opened). */
  glossed: boolean;
  /** Chunks whose gloss the reader looked up ("<sentence>:<chunk>"). */
  shown: Set<string>;
  /** Click / tap on a chunk; undefined while a click means something else (read-aloud). */
  onChunk?: (key: string) => void;
  activeGroup: number | null;
  cjk: boolean;
}) {
  if (s.chunks) {
    return (
      <>
        {s.chunks.map((c, k) => {
          // The gloss is always in the DOM (hidden by CSS when off) so that the source text is in the
          // same place whether a gloss is shown or not.
          const layout = c.translation ? glossLayout(c.original, c.translation) : null;
          const key = `${s.index}:${k}`;
          const visible = glossed || shown.has(key) || line.has(key);
          return (
            <Fragment key={k}>
              {k > 0 && !cjk && " "}
              <span
                className="chunk"
                data-tok={key}
                data-glossed={visible || undefined}
                data-tts-active={k === activeGroup || undefined}
                style={layout?.minWidth ? { minWidth: layout.minWidth } : undefined}
                onClick={
                  onChunk && layout
                    ? (e) => {
                        if (window.getSelection()?.toString()) return; // selecting text, not tapping
                        e.stopPropagation();
                        onChunk(key);
                      }
                    : undefined
                }
              >
                <span className="chunk-src">{c.original}</span>
                {layout && (
                  <span className="chunk-gloss" data-oneline={layout.oneLine || undefined} aria-hidden={!visible || undefined}>
                    {c.translation}
                  </span>
                )}
              </span>
            </Fragment>
          );
        })}
      </>
    );
  }
  // Not translated yet: words as spans so the spoken word can be highlighted.
  let word = -1;
  return (
    <>
      {s.source!.split(/(\s+)/).map((tok, k) => {
        if (!tok) return null;
        if (/^\s+$/.test(tok)) return " ";
        word++;
        return (
          <span key={k} className="word" data-tok={`${s.index}:w${word}`} data-tts-active={word === activeGroup || undefined}>
            {tok}
          </span>
        );
      })}
    </>
  );
}

function HelpToggle({ pressed, onClick, label, tip, icon }: { pressed: boolean; onClick: () => void; label: string; tip: string; icon: ReactNode }) {
  return (
    <Tip label={tip} side="top">
      <Button
        variant="ghost"
        size="sm"
        aria-pressed={pressed}
        aria-label={label}
        onClick={onClick}
        onMouseDown={(e) => e.preventDefault() /* keep Space for play/pause */}
        className={cn(
          "h-9 rounded-full px-3 text-muted-foreground",
          pressed && "bg-accent/15 text-accent hover:bg-accent/20 hover:text-accent",
        )}
      >
        {icon}
        <span className="hidden sm:inline">{label}</span>
      </Button>
    </Tip>
  );
}

function PageNav({ pageNumber, totalPages, onPrev, onNext }: { pageNumber: number; totalPages: number; onPrev: () => void; onNext: () => void }) {
  return (
    <nav className="flex items-center justify-center gap-1 py-3 text-sm text-muted-foreground" aria-label="Pages">
      <Tip label="Previous page">
        <Button variant="ghost" size="icon" className="h-8 w-8" onClick={onPrev} disabled={pageNumber <= 1} aria-label="Previous page">
          <ChevronLeft />
        </Button>
      </Tip>
      <span className="min-w-[7rem] text-center tabular-nums" data-testid="page-indicator">
        Page {pageNumber} of {totalPages}
      </span>
      <Tip label="Next page">
        <Button variant="ghost" size="icon" className="h-8 w-8" onClick={onNext} disabled={pageNumber >= totalPages} aria-label="Next page">
          <ChevronRight />
        </Button>
      </Tip>
    </nav>
  );
}

export default ReadingView;
