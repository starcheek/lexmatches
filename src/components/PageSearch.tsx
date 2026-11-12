import { useEffect, useState } from "react";
import { Loader2, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Tip } from "@/components/Tip";
import { api, type SearchResult } from "@/lib/api";
import { cn } from "@/lib/utils";

interface PageSearchProps {
  bookId: string;
  onPageSelect: (pageNumber: number) => void;
  currentPage: number;
}

/** Search the book's text (server-side); pick a result to jump to its page. */
const PageSearch = ({ bookId, onPageSelect, currentPage }: PageSearchProps) => {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const q = query.trim();
    if (q.length < 2) {
      setResults([]);
      setError(null);
      return;
    }
    let cancelled = false;
    const timer = setTimeout(async () => {
      setSearching(true);
      try {
        const found = await api.search(bookId, q);
        if (!cancelled) {
          setResults(found);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Search failed");
      } finally {
        if (!cancelled) setSearching(false);
      }
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [query, bookId]);

  const pick = (pageNumber: number) => {
    onPageSelect(pageNumber);
    setOpen(false);
    setQuery("");
  };

  const highlight = (text: string) => {
    const q = query.trim();
    if (!q) return text;
    const escaped = q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    return text.split(new RegExp(`(${escaped})`, "gi")).map((part, i) =>
      part.toLowerCase() === q.toLowerCase() ? (
        <mark key={i} className="rounded-sm bg-accent/20 px-0.5 text-foreground">
          {part}
        </mark>
      ) : (
        part
      ),
    );
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <Tip label="Search in book">
        <PopoverTrigger asChild>
          <Button variant="ghost" size="icon" className="shrink-0" aria-label="Search in book">
            <Search />
          </Button>
        </PopoverTrigger>
      </Tip>
      <PopoverContent align="end" className="w-[min(24rem,calc(100vw-1rem))] p-3">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            type="search"
            placeholder="Search in this book…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="pl-9"
            aria-label="Search text"
            autoFocus
          />
          {searching && <Loader2 className="absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 animate-spin text-muted-foreground" />}
        </div>
        <div className="mt-3 max-h-[min(24rem,60vh)] overflow-y-auto" role="list" aria-label="Search results">
          {error ? (
            <p className="py-6 text-center text-sm text-destructive">{error}</p>
          ) : results.length > 0 ? (
            <div className="space-y-1.5">
              {results.map((r) => (
                <button
                  key={r.pageNumber}
                  role="listitem"
                  onClick={() => pick(r.pageNumber)}
                  className={cn(
                    "w-full rounded-md border p-2.5 text-left transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    r.pageNumber === currentPage ? "border-accent/40 bg-accent/5" : "border-border",
                  )}
                >
                  <div className="mb-1 flex items-center justify-between text-xs">
                    <span className="font-semibold text-primary">Page {r.pageNumber}</span>
                    <span className="text-muted-foreground">
                      {r.matchCount} match{r.matchCount !== 1 ? "es" : ""}
                    </span>
                  </div>
                  <p className="line-clamp-2 font-serif text-sm text-foreground/80">{highlight(r.snippet)}</p>
                </button>
              ))}
            </div>
          ) : (
            <p className="py-6 text-center text-sm text-muted-foreground">
              {query.trim().length >= 2 ? (searching ? "Searching…" : `No matches for “${query.trim()}”`) : "Type at least 2 letters"}
            </p>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
};

export default PageSearch;
