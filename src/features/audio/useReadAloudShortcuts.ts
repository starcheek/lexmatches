import { useEffect } from "react";
import type { ReadAloud } from "./types";

// Typing, or keyboard use of an open menu / dialog / listbox (Space selects there): not a shortcut.
const isTyping = (t: EventTarget | null) =>
  t instanceof HTMLElement &&
  (t.isContentEditable ||
    ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName) ||
    t.closest('[role="dialog"],[role="alertdialog"],[role="menu"],[role="listbox"]') !== null);

/** Space = play/pause, R = say the current sentence again, [ / ] = previous / next sentence (or line). */
export function useReadAloudShortcuts(player: ReadAloud, enabled = true) {
  useEffect(() => {
    if (!enabled) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey || isTyping(e.target)) return;
      const active = player.activeId !== null;
      if (e.code === "Space") player.toggle();
      else if ((e.key === "r" || e.key === "R") && active) player.replay();
      else if (e.key === "[" && active) player.prev();
      else if (e.key === "]" && active) player.next();
      else return;
      e.preventDefault(); // also keeps a focused button from re-firing on Space
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [player, enabled]);
}
