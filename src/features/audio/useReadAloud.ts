import { useEffect, useMemo, useRef, useSyncExternalStore } from "react";
import { ReadAloudController } from "./controller";
import type { ReadAloud, ReadAloudOptions } from "./types";

/**
 * Read-aloud player for an ordered list of segments.
 *
 *   const player = useReadAloud({ segments, bookId, onQueueEnd: () => { goNext(); return true; } });
 *   player.playFrom(segment.id);           // start here, continue to the end (then onQueueEnd)
 *   player.wordFor(segment.id);            // word index being spoken in that segment, or null
 *   <ReadAloudBar player={player} />       // compact controls + keyboard shortcuts
 *
 * Pass a memoised `segments` array; ids must be stable across re-renders and unique across pages.
 */
export function useReadAloud(options: ReadAloudOptions): ReadAloud {
  const ref = useRef<ReadAloudController | null>(null);
  if (!ref.current) ref.current = new ReadAloudController();
  const c = ref.current;
  c.bookId = options.bookId;
  c.serverEnabled = options.serverEnabled ?? true;
  c.onQueueEnd = options.onQueueEnd;
  c.startAt = options.startAt;

  useEffect(() => () => c.dispose(), [c]);
  useEffect(() => c.setSegments(options.segments), [c, options.segments]);

  const lang = options.segments[0]?.lang;
  useEffect(() => {
    if (lang) c.prepare(lang);
  }, [c, lang, options.serverEnabled]);

  const snapshot = useSyncExternalStore(c.subscribe, c.getSnapshot);
  return useMemo(
    () => ({
      ...snapshot,
      playFrom: c.playFrom,
      toggle: c.toggle,
      pause: c.pause,
      resume: c.resume,
      stop: c.stop,
      next: c.next,
      prev: c.prev,
      replay: c.replay,
      setRate: c.setRate,
      wordFor: (id: string) => (snapshot.activeId === id ? snapshot.activeWord : null),
    }),
    [snapshot, c],
  );
}

/** Map a word index of `groups.join(" ")` to the index of the group containing it (e.g. word pairs). */
export function wordToGroup(groups: string[]): number[] {
  return groups.flatMap((g, i) => Array<number>(g.split(/\s+/).filter(Boolean).length).fill(i));
}
