import { useState, useEffect } from "react";
import { Search, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { supabase } from "@/integrations/supabase/client";

interface SearchResult {
  pageNumber: number;
  snippet: string;
  matchCount: number;
}

interface PageSearchProps {
  bookId: string;
  onPageSelect: (pageNumber: number) => void;
  currentPage: number;
}

const PageSearch = ({ bookId, onPageSelect, currentPage }: PageSearchProps) => {
  const [isOpen, setIsOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [isSearching, setIsSearching] = useState(false);

  useEffect(() => {
    if (query.trim().length < 2) {
      setResults([]);
      return;
    }

    const searchTimer = setTimeout(() => {
      performSearch();
    }, 300);

    return () => clearTimeout(searchTimer);
  }, [query, bookId]);

  const performSearch = async () => {
    if (!query.trim()) return;

    setIsSearching(true);
    try {
      const { data: pages, error } = await supabase
        .from("pages")
        .select("page_number, original_text, translated_data")
        .eq("book_id", bookId)
        .order("page_number");

      if (error) throw error;

      const searchResults: SearchResult[] = [];
      const lowerQuery = query.toLowerCase();

      pages?.forEach((page) => {
        const text = page.original_text.toLowerCase();
        
        // Check if query exists in text
        if (text.includes(lowerQuery)) {
          // Count matches
          const matches = text.split(lowerQuery).length - 1;
          
          // Extract snippet around first match
          const matchIndex = text.indexOf(lowerQuery);
          const snippetStart = Math.max(0, matchIndex - 50);
          const snippetEnd = Math.min(text.length, matchIndex + query.length + 50);
          
          let snippet = page.original_text.substring(snippetStart, snippetEnd);
          if (snippetStart > 0) snippet = "..." + snippet;
          if (snippetEnd < text.length) snippet = snippet + "...";

          searchResults.push({
            pageNumber: page.page_number,
            snippet,
            matchCount: matches,
          });
        }
      });

      setResults(searchResults);
    } catch (error) {
      console.error("Search error:", error);
    } finally {
      setIsSearching(false);
    }
  };

  const handleResultClick = (pageNumber: number) => {
    onPageSelect(pageNumber);
    setIsOpen(false);
    setQuery("");
  };

  const highlightQuery = (text: string) => {
    if (!query.trim()) return text;
    
    const parts = text.split(new RegExp(`(${query})`, 'gi'));
    return parts.map((part, i) => 
      part.toLowerCase() === query.toLowerCase() 
        ? <mark key={i} className="bg-accent text-accent-foreground font-semibold">{part}</mark>
        : part
    );
  };

  return (
    <div className="relative">
      <Button
        variant="outline"
        size="sm"
        onClick={() => setIsOpen(!isOpen)}
        className="gap-2"
      >
        <Search className="h-4 w-4" />
        Search Pages
      </Button>

      {isOpen && (
        <Card className="absolute top-12 right-0 w-96 p-4 shadow-lg z-50 border-border">
          <div className="flex items-center gap-2 mb-4">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input
                type="text"
                placeholder="Search in book..."
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                className="pl-9"
                autoFocus
              />
            </div>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setIsOpen(false);
                setQuery("");
              }}
            >
              <X className="h-4 w-4" />
            </Button>
          </div>

          {isSearching ? (
            <div className="text-center py-8 text-muted-foreground text-sm">
              Searching...
            </div>
          ) : results.length > 0 ? (
            <ScrollArea className="h-[400px] pr-4">
              <div className="space-y-2">
                {results.map((result) => (
                  <button
                    key={result.pageNumber}
                    onClick={() => handleResultClick(result.pageNumber)}
                    className={`w-full text-left p-3 rounded-lg border transition-colors hover:bg-accent/50 ${
                      result.pageNumber === currentPage
                        ? "bg-accent border-accent-foreground/20"
                        : "border-border bg-card"
                    }`}
                  >
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-sm font-semibold text-primary">
                        Page {result.pageNumber}
                      </span>
                      <span className="text-xs text-muted-foreground">
                        {result.matchCount} match{result.matchCount !== 1 ? "es" : ""}
                      </span>
                    </div>
                    <p className="text-sm text-foreground/80 line-clamp-2">
                      {highlightQuery(result.snippet)}
                    </p>
                  </button>
                ))}
              </div>
            </ScrollArea>
          ) : query.trim().length >= 2 ? (
            <div className="text-center py-8 text-muted-foreground text-sm">
              No results found for "{query}"
            </div>
          ) : (
            <div className="text-center py-8 text-muted-foreground text-sm">
              Enter at least 2 characters to search
            </div>
          )}
        </Card>
      )}
    </div>
  );
};

export default PageSearch;
