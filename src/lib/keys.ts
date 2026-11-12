/** Keys typed into a field or used inside a menu/dialog/listbox are not page shortcuts. */
export const isTypingTarget = (t: EventTarget | null) =>
  t instanceof HTMLElement &&
  (t.isContentEditable ||
    ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName) ||
    t.closest('[role="dialog"],[role="alertdialog"],[role="menu"],[role="listbox"]') !== null);

/** A plain key press (no modifier, not typing, not already handled) that a page shortcut may use. */
export const isShortcutEvent = (e: KeyboardEvent) =>
  !e.defaultPrevented && !e.ctrlKey && !e.metaKey && !e.altKey && !isTypingTarget(e.target);
