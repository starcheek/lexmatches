import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTheme } from "next-themes";
import {
  AlertTriangle, ArrowLeft, BookOpen, FileDown, FileImage, FileText, Keyboard, Languages, Loader2, MoreVertical, RotateCcw, Sparkles,
} from "lucide-react";
import { toast } from "sonner";
import { api, ApiError, isLoggedIn, type Page } from "@/lib/api";
import { languageLabel } from "@/lib/languages";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import {
  DropdownMenu, DropdownMenuCheckboxItem, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import ReadingView from "@/components/ReadingView";
import PageSearch from "@/components/PageSearch";
import { SubscriptionBanner } from "@/components/SubscriptionBanner";
import { Tip } from "@/components/Tip";

const PdfViewer = lazy(() => import("@/components/PdfViewer"));

const BATCH_PAGES = 10;
const INTRO_KEY = "lexmatches:reader-intro:v1"; // set once the reader's help has been seen
const autoKey = (bookId: string) => `lexmatches:auto-translate:${bookId}`;
const readAuto = (bookId: string) => {
  try {
    return localStorage.getItem(autoKey(bookId)) === "1";
  } catch {
    return false;
  }
};

const Read = () => {
  const { bookId = "" } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { resolvedTheme, setTheme } = useTheme();

  const [currentPage, setCurrentPage] = useState(1);
  const [viewMode, setViewMode] = useState<"text" | "pdf">("text");
  const [autoTranslate, setAutoTranslateState] = useState(() => readAuto(bookId));
  const [starting, setStarting] = useState<Set<string>>(new Set()); // POST in flight
  const [showSubscriptionError, setShowSubscriptionError] = useState(false);
  // The help opens by itself the first time this browser opens any book, and from "Shortcuts" after that.
  const [shortcutsOpen, setShortcutsOpen] = useState(() => {
    try {
      return localStorage.getItem(INTRO_KEY) !== "1";
    } catch {
      return false;
    }
  });
  const closeHelp = (open: boolean) => {
    setShortcutsOpen(open);
    if (open) return;
    try {
      localStorage.setItem(INTRO_KEY, "1");
    } catch {
      /* shown again next time */
    }
  };
  const [tourRequest, setTourRequest] = useState(0); // bumped to start the reader's guided tour
  const [exporting, setExporting] = useState(false);
  const initialised = useRef(false);

  useEffect(() => {
    if (!isLoggedIn()) navigate("/auth");
  }, [navigate]);

  const setAutoTranslate = (on: boolean) => {
    setAutoTranslateState(on);
    try {
      localStorage.setItem(autoKey(bookId), on ? "1" : "0");
    } catch {
      /* ignore */
    }
  };

  // ---- Book (polled while the PDF is still being split into pages) ----
  const bookQuery = useQuery({
    queryKey: ["book", bookId],
    queryFn: () => api.getBook(bookId),
    enabled: Boolean(bookId),
    retry: (count, error) => !(error instanceof ApiError && error.status === 404) && count < 2,
    refetchInterval: (q) => (q.state.data?.status === "pending" || q.state.data?.status === "processing" ? 2000 : false),
  });
  const book = bookQuery.data;
  const ready = Boolean(book && book.total_pages > 0);

  const shownPage = useRef(1); // last page we scrolled to / saved
  useEffect(() => {
    if (!book || initialised.current || book.total_pages === 0) return;
    initialised.current = true;
    const start = book.last_read_page > 0 && book.last_read_page <= book.total_pages ? book.last_read_page : 1;
    shownPage.current = start;
    setCurrentPage(start);
  }, [book]);

  // ---- Page window: previous, current, next two (polled while one is translating) ----
  const windowNumbers = useMemo(
    () => (book ? [currentPage - 1, currentPage, currentPage + 1, currentPage + 2].filter((n) => n > 0 && n <= book.total_pages) : []),
    [book, currentPage],
  );
  const pagesQuery = useQuery({
    queryKey: ["pages", bookId, windowNumbers.join(",")],
    queryFn: () => api.getPages(bookId, { numbers: windowNumbers }),
    enabled: ready && windowNumbers.length > 0,
    placeholderData: (prev) => prev,
    refetchInterval: (q) => (q.state.data?.some((p) => p.status === "processing") ? 1500 : false),
  });
  const pages = useMemo(() => {
    const byNumber: Record<number, Page> = {};
    pagesQuery.data?.forEach((p) => (byNumber[p.page_number] = p));
    return byNumber;
  }, [pagesQuery.data]);
  const page = pages[currentPage];

  const statsQuery = useQuery({
    queryKey: ["stats", bookId],
    queryFn: () => api.getStats(bookId),
    enabled: ready,
  });
  // Refresh the "n of N translated" count when a page in the window changes status.
  const windowStatuses = pagesQuery.data?.map((p) => p.status).join(",");
  useEffect(() => {
    if (windowStatuses) void queryClient.invalidateQueries({ queryKey: ["stats", bookId] });
  }, [windowStatuses, bookId, queryClient]);

  // ---- Translation: POST starts a background job; the window query polls its progress ----
  const startTranslation = useCallback(
    async (target: Page) => {
      if (starting.has(target.id)) return;
      setStarting((s) => new Set(s).add(target.id));
      setShowSubscriptionError(false);
      try {
        await api.translatePage(target.id);
      } catch (error) {
        if (error instanceof ApiError && error.status === 402) setShowSubscriptionError(true);
        toast.error(error instanceof Error ? error.message : "Could not start the translation");
        setAutoTranslate(false);
      } finally {
        await queryClient.invalidateQueries({ queryKey: ["pages", bookId] });
        setStarting((s) => {
          const next = new Set(s);
          next.delete(target.id);
          return next;
        });
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps -- setAutoTranslate is stable in effect
    [starting, queryClient, bookId],
  );

  const translateCurrent = () => {
    if (!page) return;
    setAutoTranslate(true); // keep going as the reader turns pages
    void startTranslation(page);
  };

  // Auto mode: translate the current page, and the next one once the current page is done.
  useEffect(() => {
    if (!autoTranslate || !page || viewMode !== "text") return;
    if (page.status === "pending") void startTranslation(page);
    else if (page.status === "completed") {
      const next = pages[currentPage + 1];
      if (next?.status === "pending") void startTranslation(next);
    }
  }, [autoTranslate, page, pages, currentPage, startTranslation, viewMode]);

  const translateBatch = async () => {
    if (!book) return;
    const numbers = Array.from({ length: BATCH_PAGES }, (_, i) => currentPage + i).filter((n) => n <= book.total_pages);
    try {
      const batch = await api.getPages(bookId, { numbers });
      const todo = batch.filter((p) => p.status === "pending" || p.status === "failed");
      if (!todo.length) return void toast.info("These pages are already translated");
      await Promise.all(todo.map((p) => api.translatePage(p.id)));
      toast.success(`Translating ${todo.length} page${todo.length > 1 ? "s" : ""} in the background`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not start the translation");
    }
    void queryClient.invalidateQueries({ queryKey: ["pages", bookId] });
  };

  const exportPages = async () => {
    if (!book) return;
    setExporting(true);
    try {
      const done = (await api.getPages(bookId, { status: "completed" })).map((p) => p.page_number);
      if (!done.length) return void toast.info("Translate a page first, then export it");
      const html = await api.exportHtml(bookId, done);
      const url = URL.createObjectURL(new Blob([html], { type: "text/html" }));
      const a = Object.assign(document.createElement("a"), { href: url, download: `${book.title}.html` });
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      toast.success(`Exported ${done.length} translated page${done.length > 1 ? "s" : ""}`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Export failed");
    } finally {
      setExporting(false);
    }
  };

  // ---- Navigation ----
  const goToPage = useCallback(
    (n: number) => {
      if (!book || n < 1 || n > book.total_pages) return;
      setCurrentPage(n);
    },
    [book],
  );
  const handlePrev = useCallback(() => goToPage(currentPage - 1), [goToPage, currentPage]);
  const handleNext = useCallback(() => goToPage(currentPage + 1), [goToPage, currentPage]);

  // Page turned: start at the top, remember the page (debounced).
  useEffect(() => {
    if (!initialised.current || shownPage.current === currentPage) return;
    shownPage.current = currentPage;
    window.scrollTo({ top: 0 });
    const t = setTimeout(() => api.updateBook(bookId, { last_read_page: currentPage }).catch(() => undefined), 500);
    return () => clearTimeout(t);
  }, [currentPage, bookId]);

  // PDF on demand (fetched with the auth header, shown through an object URL)
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  useEffect(() => {
    if (viewMode !== "pdf" || pdfUrl || !book || book.source !== "pdf") return;
    let cancelled = false;
    api
      .getPdfBlob(book.id)
      .then((blob) => !cancelled && setPdfUrl(URL.createObjectURL(blob)))
      .catch(() => toast.error("Could not load the PDF"));
    return () => {
      cancelled = true;
    };
  }, [viewMode, pdfUrl, book]);
  useEffect(() => () => void (pdfUrl && URL.revokeObjectURL(pdfUrl)), [pdfUrl]);

  // ---- Render ----
  if (bookQuery.isError) {
    return (
      <CenteredState icon={<AlertTriangle className="h-10 w-10 text-destructive" />} title="This book could not be opened">
        <p className="text-muted-foreground">{bookQuery.error instanceof Error ? bookQuery.error.message : "Unknown error"}</p>
        <Button className="mt-6" onClick={() => navigate("/dashboard")}>Back to library</Button>
      </CenteredState>
    );
  }
  if (!book) {
    return (
      <CenteredState icon={<Loader2 className="h-10 w-10 animate-spin text-accent" />} title="Opening book…" />
    );
  }
  if (book.status === "failed" && book.total_pages === 0) {
    return (
      <CenteredState icon={<AlertTriangle className="h-10 w-10 text-destructive" />} title="We couldn't read this book">
        <p className="text-muted-foreground">{book.error || "Extracting the text failed."}</p>
        <Button className="mt-6" onClick={() => navigate("/dashboard")}>Back to library</Button>
      </CenteredState>
    );
  }
  if (!ready) {
    return (
      <CenteredState icon={<Loader2 className="h-10 w-10 animate-spin text-accent" />} title={`Preparing “${book.title}”`}>
        <p className="text-muted-foreground">Extracting the pages. This usually takes a few seconds; the book opens by itself.</p>
        <Button variant="ghost" className="mt-6" onClick={() => navigate("/dashboard")}>Back to library</Button>
      </CenteredState>
    );
  }

  const stats = statsQuery.data;
  const isStarting = page ? starting.has(page.id) : false;
  const pdfPage = page?.source_page_start ?? page?.page_number ?? currentPage;
  const batchSize = Math.min(BATCH_PAGES, book.total_pages - currentPage + 1);

  return (
    <div className="min-h-screen bg-background">
      <header className="sticky top-0 z-50 border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/80">
        <div className="mx-auto flex h-14 max-w-6xl items-center gap-2 px-2 sm:px-4">
          <Tip label="Back to library">
            <Button variant="ghost" size="icon" className="shrink-0" onClick={() => navigate("/dashboard")} aria-label="Back to library">
              <ArrowLeft />
            </Button>
          </Tip>
          <div className="min-w-0">
            <h1 className="truncate text-sm font-semibold leading-tight">{book.title}</h1>
            <p className="truncate text-xs text-muted-foreground" data-testid="book-meta">
              {languageLabel(book.original_locale)} → {languageLabel(book.target_locale)}
              {stats && ` · ${stats.translated} of ${stats.total} pages translated`}
            </p>
          </div>
          <Tip label="How to read here: keys and controls">
            <Button variant="ghost" size="sm" className="shrink-0 text-muted-foreground" onClick={() => setShortcutsOpen(true)} aria-label="Keyboard shortcuts">
              <Keyboard /> <span className="hidden sm:inline">Shortcuts</span>
            </Button>
          </Tip>
          {/* The tour is about the arrow keys, so it is offered where there is a keyboard-sized screen. */}
          {viewMode === "text" && (
            <Button
              variant="outline"
              size="sm"
              className="hidden shrink-0 rounded-full border-accent/50 text-accent hover:bg-accent/10 hover:text-accent md:inline-flex"
              onClick={() => setTourRequest((n) => n + 1)}
              data-testid="tour-button"
            >
              <Sparkles /> Show me how to use it
            </Button>
          )}
          <div className="flex-1" />
          <PageSearch bookId={book.id} onPageSelect={goToPage} currentPage={currentPage} />
          <DropdownMenu>
            <Tip label="More">
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="icon" className="shrink-0" aria-label="More actions">
                  <MoreVertical />
                </Button>
              </DropdownMenuTrigger>
            </Tip>
            <DropdownMenuContent align="end" className="w-64">
              {book.source === "pdf" && (
                <DropdownMenuItem onSelect={() => setViewMode(viewMode === "text" ? "pdf" : "text")}>
                  {viewMode === "text" ? <FileImage /> : <FileText />}
                  {viewMode === "text" ? "Show original PDF page" : "Back to text"}
                </DropdownMenuItem>
              )}
              <DropdownMenuLabel className="text-xs font-normal text-muted-foreground">Translation</DropdownMenuLabel>
              <DropdownMenuCheckboxItem checked={autoTranslate} onCheckedChange={(on) => setAutoTranslate(Boolean(on))}>
                Translate pages as I read
              </DropdownMenuCheckboxItem>
              {batchSize > 1 && (
                <DropdownMenuItem onSelect={() => void translateBatch()}>
                  <Languages /> Translate the next {batchSize} pages
                </DropdownMenuItem>
              )}
              <DropdownMenuItem onSelect={() => void exportPages()} disabled={exporting}>
                <FileDown /> Export translated pages
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuCheckboxItem
                checked={resolvedTheme === "dark"}
                onCheckedChange={(on) => setTheme(on ? "dark" : "light")}
              >
                Dark mode
              </DropdownMenuCheckboxItem>
              <DropdownMenuItem onSelect={() => setShortcutsOpen(true)}>
                <Keyboard /> Keyboard shortcuts
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </header>

      <main className="pt-2">
        {showSubscriptionError && (
          <div className="mx-auto mb-4 max-w-[42rem] px-4">
            <SubscriptionBanner />
          </div>
        )}

        {viewMode === "pdf" ? (
          <div className="mx-auto max-w-4xl px-4 pb-10">
            <div className="flex items-center justify-between py-3">
              <Button variant="ghost" size="sm" onClick={() => setViewMode("text")}>
                <FileText /> Back to text
              </Button>
              <span className="text-sm text-muted-foreground">
                Page {currentPage} of {book.total_pages}
                {pdfPage !== currentPage && ` · PDF page ${pdfPage}`}
              </span>
            </div>
            {pdfUrl ? (
              <Suspense fallback={<Loader2 className="mx-auto mt-20 h-8 w-8 animate-spin text-accent" />}>
                <PdfViewer pdfUrl={pdfUrl} pageNumber={pdfPage} />
              </Suspense>
            ) : (
              <Loader2 className="mx-auto mt-20 h-8 w-8 animate-spin text-accent" />
            )}
          </div>
        ) : (
          <ReadingView
            pageNumber={currentPage}
            totalPages={book.total_pages}
            originalText={page?.original_text ?? ""}
            translationData={page?.translated_data}
            bookId={book.id}
            originalLocale={book.original_locale}
            onNextPage={handleNext}
            onPrevPage={handlePrev}
            tourRequest={tourRequest}
            banner={
              <PageBanner
                page={page}
                loading={pagesQuery.isPending}
                starting={isStarting}
                autoTranslate={autoTranslate}
                onTranslate={translateCurrent}
                onShowPdf={book.source === "pdf" ? () => setViewMode("pdf") : undefined}
              />
            }
          />
        )}
      </main>

      <Dialog open={shortcutsOpen} onOpenChange={closeHelp}>
        <DialogContent className="max-h-[90vh] max-w-md overflow-y-auto" data-testid="reader-help">
          <DialogHeader>
            <DialogTitle>How to read here</DialogTitle>
            <DialogDescription>
              Read the original. Ask for help only where you need it; every time you do is counted as a lookup.
            </DialogDescription>
          </DialogHeader>
          <ul className="space-y-1.5 text-sm">
            <li><span className="font-medium">Click a word or phrase</span> to see its translation under it.</li>
            <li><span className="font-medium">↑ and ↓</span> move line by line; a golden dot marks your line.</li>
            <li><span className="font-medium">Line</span> shows the translations of your current line only, and follows you as you move.</li>
            <li><span className="font-medium">← or →</span> shows the translations of the whole page; in Line, it hides or shows those of your line.</li>
            <li><span className="font-medium">Play</span> reads the text aloud and highlights each word.</li>
          </ul>
          <h3 className="text-sm font-semibold">Keyboard shortcuts</h3>
          <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
            {[
              ["↑ / ↓", "Previous / next line"],
              ["L", "Translations of the current line only, on / off"],
              ["← / →", "All glosses of the page on / off; in Line: the current line's"],
              ["G", "All glosses of the page on / off"],
              ["T", "Sentence translations on / off"],
              ["− / +", "Smaller / larger text"],
              ["Enter", "Translation of the current line's sentence"],
              ["Space", "Read aloud / pause"],
              ["[ / ]", "Previous / next sentence"],
              ["R", "Say the sentence again"],
            ].map(([k, v]) => (
              <div key={k} className="contents">
                <dt><kbd className="rounded border bg-muted px-1.5 py-0.5 font-mono text-xs">{k}</kbd></dt>
                <dd className="text-muted-foreground">{v}</dd>
              </div>
            ))}
          </dl>
          <p className="text-xs text-muted-foreground">Shortcuts work while reading, not while typing in a field. You can reopen this from “Shortcuts” in the top bar.</p>
          {viewMode === "text" && (
            <Button
              variant="outline"
              className="hidden md:inline-flex"
              onClick={() => {
                closeHelp(false);
                setTourRequest((n) => n + 1);
              }}
            >
              <Sparkles /> Show me how to use it
            </Button>
          )}
          <Button onClick={() => closeHelp(false)}>Got it</Button>
        </DialogContent>
      </Dialog>
    </div>
  );
};

function PageBanner({
  page, loading, starting, autoTranslate, onTranslate, onShowPdf,
}: {
  page?: Page;
  loading: boolean;
  starting: boolean;
  autoTranslate: boolean;
  onTranslate: () => void;
  onShowPdf?: () => void;
}) {
  const box = "mb-6 rounded-lg border px-4 py-3 text-sm font-sans";
  if (!page) {
    return loading ? (
      <div className="mb-6 space-y-3" aria-label="Loading page">
        {[92, 100, 96, 70].map((w, i) => (
          <div key={i} className="h-4 animate-pulse rounded bg-muted" style={{ width: `${w}%` }} />
        ))}
      </div>
    ) : null;
  }
  if (!page.original_text.trim()) {
    return (
      <div className={`${box} bg-muted/40`} role="status">
        <p className="text-muted-foreground">This page has no text{onShowPdf ? " (it may be an image or a blank page)." : "."}</p>
        {onShowPdf && (
          <Button variant="outline" size="sm" className="mt-2" onClick={onShowPdf}>
            <FileImage /> Show the PDF page
          </Button>
        )}
      </div>
    );
  }
  if (page.status === "processing" || starting) {
    const { done, total } = page.progress;
    return (
      <div className={`${box} border-accent/20 bg-accent/5`} role="status" data-testid="translation-progress">
        <div className="flex items-center gap-2">
          <Loader2 className="h-4 w-4 shrink-0 animate-spin text-accent" />
          <span>
            {done > 0 && total > 0 ? `Translating… ${done} of ${total} sentences ready` : "Translating… the first sentences appear in about 15 seconds"}
          </span>
        </div>
        <Progress value={total ? (done / total) * 100 : 3} className="mt-2 h-1" />
      </div>
    );
  }
  if (page.status === "failed") {
    return (
      <div className={`${box} border-destructive/30 bg-destructive/5`} role="alert">
        <p className="font-medium text-destructive">Translation failed</p>
        {page.error && <p className="mt-0.5 text-muted-foreground">{page.error}</p>}
        <Button variant="outline" size="sm" className="mt-2" onClick={onTranslate}>
          <RotateCcw /> Try again
        </Button>
      </div>
    );
  }
  if (page.status === "pending" && !autoTranslate) {
    return (
      <div className={`${box} flex flex-wrap items-center justify-between gap-3 bg-muted/40`} role="status">
        <div>
          <p className="font-medium">This page isn't translated yet</p>
          <p className="text-muted-foreground">You can read and listen now. Translation takes about 15 seconds.</p>
        </div>
        <Button size="sm" onClick={onTranslate}>
          <Languages /> Translate page
        </Button>
      </div>
    );
  }
  return null;
}

function CenteredState({ icon, title, children }: { icon: React.ReactNode; title: string; children?: React.ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-6">
      <div className="max-w-md text-center">
        <div className="mb-4 flex justify-center">{icon ?? <BookOpen className="h-10 w-10 text-accent" />}</div>
        <h1 className="mb-2 font-serif text-2xl font-semibold text-primary">{title}</h1>
        {children}
      </div>
    </div>
  );
}

export default Read;
