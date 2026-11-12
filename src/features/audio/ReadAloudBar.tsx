import { Loader2, Pause, Play, RotateCcw, SkipBack, SkipForward, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { RATES } from "./controller";
import type { ReadAloud } from "./types";
import { useReadAloudShortcuts } from "./useReadAloudShortcuts";

/** Compact read-aloud controls. Placement is up to the caller (`className`). `shortcuts={false}` leaves Space etc. alone. */
export function ReadAloudBar({ player, className, shortcuts = true }: { player: ReadAloud; className?: string; shortcuts?: boolean }) {
  useReadAloudShortcuts(player, shortcuts);
  const { status, activeId, rate, voiceProgress, note, error } = player;
  const active = activeId !== null;
  const busy = status === "loading" || status === "preparing";
  const label =
    status === "error" ? error
    : status === "preparing" ? `Preparing voice… ${Math.round((voiceProgress ?? 0) * 100)}%`
    : note;
  const nextRate = RATES[(RATES.indexOf(rate) + 1) % RATES.length];
  // Keep focus where it was: Space must not re-activate the last clicked control.
  const noFocus = (e: React.MouseEvent) => e.preventDefault();

  return (
    <div
      role="toolbar"
      aria-label="Read aloud"
      data-testid="read-aloud-bar"
      data-active={activeId ?? undefined}
      data-status={status}
      className={cn("relative flex w-fit items-center gap-0.5 rounded-full border border-border bg-background/95 p-1 shadow-lg backdrop-blur", className)}
    >
      <Button variant="ghost" size="icon" className="h-8 w-8 rounded-full" onMouseDown={noFocus} onClick={player.prev} disabled={!active} title="Back ( [ )">
        <SkipBack className="h-4 w-4" />
      </Button>
      <Button
        size="icon"
        className="h-9 w-9 rounded-full"
        onMouseDown={noFocus}
        onClick={player.toggle}
        title={status === "playing" ? "Pause (Space)" : busy ? "Cancel" : "Read aloud (Space)"}
        aria-label={status === "playing" ? "Pause" : "Read aloud"}
      >
        {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : status === "playing" ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
      </Button>
      <Button variant="ghost" size="icon" className="h-8 w-8 rounded-full" onMouseDown={noFocus} onClick={player.next} disabled={!active} title="Forward ( ] )">
        <SkipForward className="h-4 w-4" />
      </Button>
      <Button variant="ghost" size="icon" className="h-8 w-8 rounded-full" onMouseDown={noFocus} onClick={player.replay} disabled={!active} title="Say again (R)">
        <RotateCcw className="h-4 w-4" />
      </Button>
      <Button
        variant="ghost"
        size="sm"
        className="h-8 rounded-full px-2 text-xs tabular-nums"
        onMouseDown={noFocus}
        onClick={() => player.setRate(nextRate)}
        title={`Speed: ${rate}× (click for ${nextRate}×)`}
        data-testid="read-aloud-rate"
      >
        {rate}×
      </Button>
      <Button variant="ghost" size="icon" className="h-8 w-8 rounded-full" onMouseDown={noFocus} onClick={player.stop} disabled={!active && !busy} title="Stop">
        <X className="h-4 w-4" />
      </Button>
      {/* Caption above the bar, so the buttons never move under the pointer when it appears. */}
      {label && (
        <span
          role="status"
          className={cn(
            "absolute bottom-full left-1/2 mb-1.5 max-w-[90vw] -translate-x-1/2 truncate whitespace-nowrap rounded-full border border-border bg-background/95 px-2.5 py-0.5 text-xs shadow-sm",
            status === "error" ? "text-destructive" : "text-muted-foreground",
          )}
        >
          {label}
        </span>
      )}
    </div>
  );
}
