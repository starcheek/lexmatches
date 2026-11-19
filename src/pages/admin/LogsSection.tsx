// Admin: the server's own log output (newest lines, kept in memory by the API since its last restart),
// and the failed requests stored in the database.
import { useCallback, useEffect, useRef, useState } from "react";
import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { call, when, type ServerRequest } from "./shared";

interface Line {
  id: number;
  ts: string;
  level: string;
  logger: string;
  message: string;
}
interface Logs {
  started: string;
  kept: number;
  lines: Line[];
}

const LEVELS = ["INFO", "WARNING", "ERROR"] as const;
const POLL_MS = 5000;
const tone: Record<string, string> = { WARNING: "text-amber-600 dark:text-amber-400", ERROR: "text-destructive", CRITICAL: "text-destructive" };
const clock = (iso: string) => new Date(iso).toLocaleTimeString(undefined, { hour12: false }) + " " + new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });

const LogsSection = ({ token, failed }: { token: string; failed: ServerRequest[] }) => {
  const [level, setLevel] = useState<(typeof LEVELS)[number]>("INFO");
  const [query, setQuery] = useState("");
  const [live, setLive] = useState(true);
  const [logs, setLogs] = useState<Logs | null>(null);
  const [error, setError] = useState<string | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const stick = useRef(true); // follow the newest line unless the owner scrolled up to read

  const load = useCallback(async () => {
    try {
      const params = new URLSearchParams({ level, limit: "1000" });
      if (query.trim()) params.set("q", query.trim());
      setLogs(await call<Logs>(token, "GET", `/logs?${params}`));
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [token, level, query]);

  useEffect(() => {
    const first = setTimeout(() => void load(), 250); // also debounces typing in the filter
    const timer = live ? setInterval(() => void load(), POLL_MS) : undefined;
    return () => {
      clearTimeout(first);
      clearInterval(timer);
    };
  }, [load, live]);

  useEffect(() => {
    if (stick.current && box.current) box.current.scrollTop = box.current.scrollHeight;
  }, [logs]);

  return (
    <div className="space-y-6">
      <Card data-testid="admin-logs">
        <CardHeader>
          <CardTitle className="text-lg">Server log</CardTitle>
          <CardDescription>
            {logs
              ? `The newest ${logs.kept} lines since the server started (${when(logs.started)}). Older lines: docker compose logs api.`
              : "Loading…"}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex rounded-md border p-0.5" role="group" aria-label="Lowest level shown">
              {LEVELS.map((l) => (
                <button
                  key={l}
                  type="button"
                  aria-pressed={level === l}
                  onClick={() => setLevel(l)}
                  className={cn("rounded px-2.5 py-1 text-xs font-medium", level === l ? "bg-muted text-foreground" : "text-muted-foreground hover:text-foreground")}
                >
                  {l === "INFO" ? "All" : l === "WARNING" ? "Warnings" : "Errors"}
                </button>
              ))}
            </div>
            <Input className="min-w-48 flex-1" placeholder="Filter text" value={query} onChange={(e) => setQuery(e.target.value)} />
            <label className="flex items-center gap-2 text-sm text-muted-foreground">
              <input type="checkbox" className="h-4 w-4" checked={live} onChange={(e) => setLive(e.target.checked)} />
              Live
            </label>
            <Button variant="ghost" size="sm" onClick={() => void load()}>
              <RefreshCw /> Refresh
            </Button>
          </div>
          {error && <p className="text-sm text-destructive" role="alert">{error}</p>}
          <div
            ref={box}
            onScroll={(e) => {
              const el = e.currentTarget;
              stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
            }}
            className="h-[60vh] overflow-auto rounded-md border bg-muted/30 p-3 font-mono text-xs leading-relaxed"
            tabIndex={0}
            aria-label="Server log lines"
          >
            {logs && logs.lines.length === 0 && <p className="text-muted-foreground">No lines match.</p>}
            {logs?.lines.map((l) => (
              <div key={l.id} className={cn("whitespace-pre-wrap break-words", tone[l.level])}>
                <span className="text-muted-foreground">{clock(l.ts)}</span> <span className="font-semibold">{l.level}</span>{" "}
                <span className="text-muted-foreground">{l.logger}:</span> {l.message}
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Failed requests ({failed.length})</CardTitle>
          <CardDescription>Stored in the database, so they survive restarts: rejected requests, crashes and failed jobs of the last days.</CardDescription>
        </CardHeader>
        <CardContent className="text-sm">
          {failed.length === 0 ? (
            <p className="text-muted-foreground">Nothing recorded.</p>
          ) : (
            <ul className="space-y-1">
              {failed.map((s, i) => (
                <li key={i} className="border-t pt-1">
                  {when(s.ts)} · {s.email ?? "signed out"} · {s.ip ?? "–"} ·{" "}
                  <span className="font-medium">
                    {s.status ?? ""} {s.method} {s.path}
                  </span>
                  {s.duration_ms !== null && ` · ${s.duration_ms} ms`}
                  {s.detail && <div className="break-words text-muted-foreground">{s.detail}</div>}
                  {s.traceback && (
                    <details>
                      <summary className="cursor-pointer text-muted-foreground">Traceback</summary>
                      <pre className="overflow-x-auto whitespace-pre-wrap text-xs">{s.traceback}</pre>
                    </details>
                  )}
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
};

export default LogsSection;
