// Touch devices: a floating translations on/off button where the reader's thumb already is.
// Every vertical scroll gesture is a sample of where the thumb rests (which half of the screen, how
// high); the button sits at the running average of those samples, on that side, and moves there
// smoothly. Learned per browser (localStorage), so a left-handed reader gets it on the left.
import { useEffect, useRef, useState } from "react";
import { Languages } from "lucide-react";
import { cn } from "@/lib/utils";

const ZONE_KEY = "lexmatches:thumb-zone:v1";
const SIZE = 52; // px, comfortably above the 44 px minimum touch target
const MIN_MOVE = 12; // px before a touch counts as a scroll (and its direction is decided)

interface Zone {
  /** Running average of the scrolling thumb, as fractions of the viewport. */
  x: number;
  y: number;
  /** Scroll gestures seen (the first few move the button more). */
  n: number;
  side: "left" | "right";
}
// Before any scrolling: right-handed, a little below the middle (where a thumb rests holding a phone).
const DEFAULT_ZONE: Zone = { x: 0.8, y: 0.6, n: 0, side: "right" };

function loadZone(): Zone {
  try {
    const z = JSON.parse(localStorage.getItem(ZONE_KEY) ?? "null");
    if (z && Number.isFinite(z.x) && Number.isFinite(z.y) && (z.side === "left" || z.side === "right")) return z;
  } catch {
    /* default */
  }
  return DEFAULT_ZONE;
}

/** Where the thumb scrolls, learned from the reader's vertical scroll gestures while `enabled`. */
function useThumbZone(enabled: boolean): Zone {
  const [zone, setZone] = useState<Zone>(loadZone);
  // The exact running average; the state (what is drawn) only follows it when the button would visibly move.
  const live = useRef(zone);

  useEffect(() => {
    if (!enabled) return;
    let gesture: { x0: number; y0: number; sx: number; sy: number; count: number; vertical: boolean | null } | null = null;

    const onStart = (e: TouchEvent) => {
      const t = e.touches[0];
      const target = e.target as Element | null;
      // one finger, and not on a control (the button itself, the dock, dialogs)
      gesture = e.touches.length === 1 && !target?.closest("button, a, input, textarea, [role=dialog], [data-testid=reader-dock]")
        ? { x0: t.clientX, y0: t.clientY, sx: t.clientX, sy: t.clientY, count: 1, vertical: null }
        : null;
    };
    const onMove = (e: TouchEvent) => {
      if (!gesture || e.touches.length !== 1) return void (gesture = null);
      const t = e.touches[0];
      const dx = t.clientX - gesture.x0;
      const dy = t.clientY - gesture.y0;
      if (gesture.vertical === null && Math.hypot(dx, dy) >= MIN_MOVE) gesture.vertical = Math.abs(dy) > Math.abs(dx);
      gesture.sx += t.clientX;
      gesture.sy += t.clientY;
      gesture.count++;
    };
    const onEnd = () => {
      const g = gesture;
      gesture = null;
      if (!g?.vertical || g.count < 3) return;
      const w = window.innerWidth;
      const h = window.visualViewport?.height ?? window.innerHeight;
      const fx = g.sx / g.count / w;
      const fy = g.sy / g.count / h;
      const prev = live.current;
      const a = Math.max(0.2, 1 / (prev.n + 1)); // the first gesture replaces the default outright
      const x = prev.x + (fx - prev.x) * a;
      const y = prev.y + (fy - prev.y) * a;
      // a little hysteresis, so thumbs near the middle do not make the button jump sides
      const side = x > 0.55 ? "right" : x < 0.45 ? "left" : prev.side;
      const next: Zone = { x, y, n: prev.n + 1, side };
      live.current = next;
      try {
        localStorage.setItem(ZONE_KEY, JSON.stringify(next));
      } catch {
        /* this visit only */
      }
      setZone((shown) => (side !== shown.side || Math.abs(y - shown.y) > 0.015 ? next : shown));
    };

    window.addEventListener("touchstart", onStart, { passive: true });
    window.addEventListener("touchmove", onMove, { passive: true });
    window.addEventListener("touchend", onEnd, { passive: true });
    window.addEventListener("touchcancel", onEnd, { passive: true });
    return () => {
      window.removeEventListener("touchstart", onStart);
      window.removeEventListener("touchmove", onMove);
      window.removeEventListener("touchend", onEnd);
      window.removeEventListener("touchcancel", onEnd);
    };
  }, [enabled]);

  return zone;
}

/** The floating button. `top`/`bottom` = room kept free for the reader's header and dock (px). */
export function ThumbToggle({
  pressed,
  onToggle,
  label,
  top,
  bottom,
}: {
  pressed: boolean;
  onToggle: () => void;
  label: string;
  top: number;
  bottom: number;
}) {
  const zone = useThumbZone(true);
  return (
    <button
      type="button"
      aria-pressed={pressed}
      aria-label={label}
      data-testid="thumb-toggle"
      data-side={zone.side}
      onClick={() => {
        navigator.vibrate?.(8);
        onToggle();
      }}
      className={cn(
        "fixed z-40 flex items-center justify-center rounded-full border shadow-lg backdrop-blur",
        "transition-[top,left,right,background-color,color] duration-300 ease-out motion-reduce:transition-none",
        "touch-manipulation select-none [-webkit-tap-highlight-color:transparent] active:scale-95 [&_svg]:h-6 [&_svg]:w-6",
        pressed ? "border-accent bg-accent text-accent-foreground" : "border-border bg-background/90 text-foreground",
        zone.side === "right" ? "right-3" : "left-3",
      )}
      style={{
        width: SIZE,
        height: SIZE,
        top: `clamp(${top}px, calc(${(zone.y * 100).toFixed(2)}dvh - ${SIZE / 2}px), calc(100dvh - ${bottom + SIZE}px))`,
      }}
    >
      <Languages aria-hidden />
    </button>
  );
}
