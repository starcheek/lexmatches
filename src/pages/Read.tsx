import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { supabase } from "@/integrations/supabase/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";
import { ArrowLeft, Loader2, FileText, FileImage, WifiOff, Download, FileDown } from "lucide-react";
import { toast } from "sonner";
import { Progress } from "@/components/ui/progress";
import ReadingView from "@/components/ReadingView";
import PageSearch from "@/components/PageSearch";
import PdfViewer from "@/components/PdfViewer";
import { SubscriptionBanner } from "@/components/SubscriptionBanner";
import { useSubscription } from "@/contexts/SubscriptionContext";
import { useServiceWorker } from "@/hooks/useServiceWorker";

interface WordPair {
  original: string;
  translation: string;
}

interface TranslationData {
  lines: WordPair[][];
  fullTranslation: string;
}

interface PageImage {
  data: string;
  position?: number;
}

interface Page {
  id: string;
  page_number: number;
  original_text: string;
  translated_data: TranslationData | null;
  images: PageImage[];
  status: string;
}

interface Book {
  id: string;
  title: string;
  total_pages: number;
  status: string;
  last_read_page: number;
  original_locale: string;
}

interface TranslationProgress {
  done: number;
  total: number;
  rateLimited?: boolean;
}

const Read = () => {
  const { bookId } = useParams();
  const navigate = useNavigate();
  
  const { cachePages, isOnline } = useServiceWorker();
  const [book, setBook] = useState<Book | null>(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [pages, setPages] = useState<Record<number, Page>>({});
  const [loading, setLoading] = useState(true);
  const [viewMode, setViewMode] = useState<'text' | 'pdf'>('text');
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [autoTranslate, setAutoTranslate] = useState(false);
  const [lastTranslatedPage, setLastTranslatedPage] = useState<number | null>(null);
  const [showSubscriptionError, setShowSubscriptionError] = useState(false);
  const [prefetchCount, setPrefetchCount] = useState(5);
  const [isPrefetching, setIsPrefetching] = useState(false);
  const [prefetchProgress, setPrefetchProgress] = useState({ current: 0, total: 0 });
  const [isExporting, setIsExporting] = useState(false);
  const [translatedPagesCount, setTranslatedPagesCount] = useState({ translated: 0, total: 0 });
  const [translatingPageIds, setTranslatingPageIds] = useState<Set<string>>(new Set());
  const [translationProgress, setTranslationProgress] = useState<Record<string, TranslationProgress>>({});

  const loadPagesWindowRef = useRef<(() => void) | null>(null);
  const activeTranslationIdsRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    if (!bookId) {
      navigate("/dashboard");
      return;
    }

    loadBook();

    // Subscribe to realtime updates for pages
    const channel = supabase
      .channel('pages-changes')
      .on(
        'postgres_changes',
        {
          event: '*',
          schema: 'public',
          table: 'pages',
          filter: `book_id=eq.${bookId}`
        },
        (payload) => {
          console.log('Page change received:', payload);
          const incoming = payload.new as any;
          // Realtime can drop the row (e.g. payload too large for a fully
          // translated page). Never overwrite good state with a broken row —
          // refetch instead, otherwise the translation appears to vanish.
          if (incoming && typeof incoming.page_number === 'number' && incoming.id) {
            // Robust check: if data is missing but it should be there, refetch
            if ((incoming.status === 'completed' || incoming.status === 'processing') && !incoming.translated_data) {
              console.log('Large payload truncated, refetching page...');
              loadPagesWindowRef.current?.();
              return;
            }

            setPages(prev => {
              const existing = prev[incoming.page_number];
              const merged = { ...(existing || {}), ...incoming } as Page;
              // Keep already-loaded translation if the event omitted it
              if (!incoming.translated_data && existing?.translated_data) {
                merged.translated_data = existing.translated_data;
              }
              return { ...prev, [incoming.page_number]: merged };
            });
          } else {
            loadPagesWindowRef.current?.();
          }
        }
      )
      .subscribe();

    return () => {
      // Stop translations when leaving the page
      setAutoTranslate(false);
      
      // Clear failed page statuses
      const clearFailedPages = async () => {
        if (!bookId) return;
        
        try {
          const { data: failedPages } = await supabase
            .from('pages')
            .select('id')
            .eq('book_id', bookId)
            .eq('status', 'failed');
          
          if (failedPages && failedPages.length > 0) {
            await supabase
              .from('pages')
              .update({ status: 'pending' })
              .eq('book_id', bookId)
              .eq('status', 'failed');
            
            console.log(`Cleared ${failedPages.length} failed pages`);
          }
        } catch (error) {
          console.error('Error clearing failed pages:', error);
        }
      };
      
      clearFailedPages();
      supabase.removeChannel(channel);
    };
  }, [bookId, navigate]);

  useEffect(() => {
    if (book) {
      // Check if user skipped pages (only if auto-translate is active)
      if (autoTranslate && lastTranslatedPage !== null && currentPage !== lastTranslatedPage + 1 && currentPage !== lastTranslatedPage) {
        console.log('Page skipped, disabling auto-translate');
        setAutoTranslate(false);
        toast.info("Auto-translation paused. Click 'Start Translation' to continue.");
      }
      
      loadPagesWindowRef.current = loadPagesWindow;
      loadPagesWindow();
      saveLastReadPage();
    }
  }, [currentPage, book]);

  const saveLastReadPage = async () => {
    if (!bookId || !book) return;
    
    try {
      await supabase
        .from("books")
        .update({ last_read_page: currentPage })
        .eq("id", bookId);
    } catch (error) {
      console.error('Error saving last read page:', error);
    }
  };

  const loadBook = async () => {
    try {
      const { data, error } = await supabase
        .from("books")
        .select("*")
        .eq("id", bookId)
        .single();

      if (error) throw error;
      
      setBook(data);
      
      // Restore last read page
      if (data.last_read_page && data.last_read_page > 0 && data.last_read_page <= data.total_pages) {
        setCurrentPage(data.last_read_page);
      }
      
      // Get translated pages count
      await loadTranslatedPagesCount(data.total_pages);
      
      // Get PDF URL from storage
      const { data: { user } } = await supabase.auth.getUser();
      if (user) {
        const { data: urlData } = await supabase.storage
          .from('books')
          .createSignedUrl(`${user.id}/${bookId}.pdf`, 3600);
        
        if (urlData?.signedUrl) {
          // signedUrl is already a full URL, use it directly
          setPdfUrl(urlData.signedUrl);
          console.log('PDF URL:', urlData.signedUrl);
        }
      }
      
      setLoading(false);
    } catch (error: any) {
      console.error(error);
      toast.error("Failed to load book");
      navigate("/dashboard");
    }
  };

  const loadTranslatedPagesCount = async (totalPages: number) => {
    if (!bookId) return;
    
    const { count, error } = await supabase
      .from("pages")
      .select("*", { count: 'exact', head: true })
      .eq("book_id", bookId)
      .eq("status", "completed");
    
    if (!error) {
      setTranslatedPagesCount({ translated: count || 0, total: totalPages });
    }
  };

  const loadPagesWindow = async () => {
    if (!book) return;

    // Smart pre-loading: current + next 2 + previous 1
    const pageNumbers = [
      currentPage - 1,
      currentPage,
      currentPage + 1,
      currentPage + 2
    ].filter(n => n > 0 && n <= book.total_pages);

    const { data: pagesData, error } = await supabase
      .from("pages")
      .select("*")
      .eq("book_id", bookId)
      .in("page_number", pageNumbers);

    if (error) {
      console.error(error);
      return;
    }

    const pagesMap: Record<number, Page> = {};
    pagesData?.forEach(page => {
      pagesMap[page.page_number] = {
        ...page,
        translated_data: page.translated_data as unknown as TranslationData | null,
        images: (page.images as unknown as PageImage[]) || []
      };
    });
    
    setPages(prev => ({ ...prev, ...pagesMap }));
    
    // Cache pages for offline reading
    if (pagesData && pagesData.length > 0) {
      cachePages(pagesData);
    }

    // Only auto-translate if enabled and it's not already being translated
    if (autoTranslate) {
      const currentPageData = pagesData?.find(p => p.page_number === currentPage);
      if (currentPageData && (currentPageData.status === 'pending' || currentPageData.status === 'processing') && !activeTranslationIdsRef.current.has(currentPageData.id)) {
        void translatePage(currentPageData.id, currentPage);
      }
    }
  };

  const startTranslation = async () => {
    setAutoTranslate(true);
    setShowSubscriptionError(false);
    const page = pages[currentPage];
    if (page && (page.status === 'pending' || page.status === 'processing')) {
      await translatePage(page.id, currentPage);
    }
  };

  const invokeTranslation = async (pageId: string) => {
    let lastDone = -1;
    let stalled = 0;
    for (let attempt = 0; attempt < 60; attempt++) {
      const { data, error } = await supabase.functions.invoke('translate-page', { body: { pageId } });
      if (error) return { data, error };

      const done = typeof data?.done === 'number'
        ? data.done
        : Array.isArray(data?.data?.lines) ? data.data.lines.length : lastDone;
      const total = typeof data?.total === 'number' ? data.total : done;
      setTranslationProgress(prev => ({
        ...prev,
        [pageId]: { done: Math.max(0, done), total: Math.max(0, total), rateLimited: Boolean(data?.rateLimited) }
      }));
      loadPagesWindowRef.current?.();

      if (!data?.partial) return { data, error: null };
      if (done >= 0 && done === lastDone && !data?.rateLimited) {
        stalled++;
        if (stalled >= 2) return { data, error: new Error('Translation stopped making progress. Please resume.') };
      } else {
        stalled = 0;
      }
      lastDone = done;

      const wait = data?.rateLimited
        ? Math.min(Math.max(Number(data?.retryAfterMs) || 5000, 1000), 30000)
        : 150;
      await new Promise(resolve => setTimeout(resolve, wait));
    }

    return { data: null, error: new Error('Translation is taking too long. Please resume.') };
  };

  const translatePage = async (pageId: string, pageNumber: number) => {
    if (activeTranslationIdsRef.current.has(pageId)) return;
    activeTranslationIdsRef.current.add(pageId);
    
    try {
      setTranslatingPageIds(prev => new Set(prev).add(pageId));
      setLastTranslatedPage(pageNumber);
      const { error } = await invokeTranslation(pageId);

      // Always resync from the database: realtime events can be missed or
      // dropped, which previously left the page stuck showing "paused".
      await loadPagesWindow();
      if (book) await loadTranslatedPagesCount(book.total_pages);

      if (error) {
        console.error('Translation error:', error);

        if (error.message.includes('Rate limit')) {
          toast.error("Rate limit reached. Please wait a moment.");
          setAutoTranslate(false);
        } else if (error.message.includes('credits')) {
          toast.error("AI credits exhausted. Please add credits to continue.");
          setAutoTranslate(false);
        } else {
          toast.error(error.message || "Translation could not continue.");
        }
      }
    } catch (error: any) {
      console.error('Error triggering translation:', error);
      setAutoTranslate(false);
    } finally {
      activeTranslationIdsRef.current.delete(pageId);
      setTranslatingPageIds(prev => {
        const next = new Set(prev);
        next.delete(pageId);
        return next;
      });
      setTranslationProgress(prev => {
        const next = { ...prev };
        delete next[pageId];
        return next;
      });
    }
  };


  const handlePrevPage = () => {
    if (currentPage > 1) {
      setCurrentPage(currentPage - 1);
    }
  };

  const handleNextPage = () => {
    if (book && currentPage < book.total_pages) {
      setCurrentPage(currentPage + 1);
    }
  };

  const handlePrefetch = async () => {
    if (!book || !bookId || isPrefetching) return;

    setIsPrefetching(true);
    setPrefetchProgress({ current: 0, total: prefetchCount });

    try {
      const pageNumbers = Array.from(
        { length: prefetchCount },
        (_, i) => currentPage + i
      ).filter(n => n <= book.total_pages);

      // Get pages that need translation
      const { data: pagesData, error } = await supabase
        .from("pages")
        .select("*")
        .eq("book_id", bookId)
        .in("page_number", pageNumbers);

      if (error) throw error;

      // Never queue a page a translation loop is already working on
      const pagesToTranslate = (pagesData || []).filter(
        p => (p.status === 'pending' || p.status === 'processing') && !activeTranslationIdsRef.current.has(p.id)
      );
      const totalToProcess = pagesToTranslate.length;

      setPrefetchProgress({ current: 0, total: totalToProcess });

      if (totalToProcess === 0) {
        toast.info("All selected pages are already translated!");
        if (pagesData && pagesData.length > 0) {
          cachePages(pagesData);
        }
        setIsPrefetching(false);
        return;
      }

      toast.info(`Translating ${totalToProcess} pages...`);

      let completed = 0;
      let stop = false;
      const queue = [...pagesToTranslate];
      const PARALLEL_PAGES = 2;

      const worker = async () => {
        while (!stop) {
          const pageToTranslate = queue.shift();
          if (!pageToTranslate) return;
          if (activeTranslationIdsRef.current.has(pageToTranslate.id)) continue;
          activeTranslationIdsRef.current.add(pageToTranslate.id);

          try {
            let rateLimitRetries = 0;
            while (!stop) {
              const { error: translateError } = await invokeTranslation(pageToTranslate.id);
              if (!translateError) break;

              console.error('Translation error:', translateError);
              const message = translateError.message || '';
              if (message.includes('Daily translation limit')) {
                toast.error("Daily translation limit reached. Try again tomorrow.");
                stop = true;
                break;
              }
              if ((message.includes('Rate limit') || message.includes('429')) && rateLimitRetries < 3) {
                rateLimitRetries++;
                await new Promise(resolve => setTimeout(resolve, 5000 * rateLimitRetries));
                continue;
              }
              // Give up on this page, keep going with the rest
              break;
            }
          } catch (e) {
            console.error('Error translating page:', e);
          } finally {
            activeTranslationIdsRef.current.delete(pageToTranslate.id);
            completed++;
            setPrefetchProgress({ current: completed, total: totalToProcess });
          }
        }
      };

      await Promise.all(
        Array.from({ length: Math.min(PARALLEL_PAGES, queue.length) }, () => worker())
      );

      // Reload all pages and cache them
      const { data: translatedPages } = await supabase
        .from("pages")
        .select("*")
        .eq("book_id", bookId)
        .in("page_number", pageNumbers)
        .eq("status", "completed");

      await loadPagesWindow();
      if (translatedPages && translatedPages.length > 0) {
        cachePages(translatedPages);
        toast.success(`Translated and cached ${translatedPages.length} pages!`);
        await loadTranslatedPagesCount(book.total_pages);
      }
    } catch (error) {
      console.error('Prefetch error:', error);
      toast.error("Failed to translate pages");
    } finally {
      setIsPrefetching(false);
      setPrefetchProgress({ current: 0, total: 0 });
    }
  };


  const handleExport = async () => {
    if (!book || !bookId) return;
    
    setIsExporting(true);
    try {
      const pageNumbers = Array.from(
        { length: prefetchCount },
        (_, i) => currentPage + i
      ).filter(n => n <= book.total_pages);

      const { data, error } = await supabase.functions.invoke('export-book', {
        body: { bookId, pageNumbers, format: 'html' }
      });

      if (error) throw error;

      // Create and download the HTML file
      const blob = new Blob([data], { type: 'text/html' });
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${book.title}-pages-${pageNumbers[0]}-${pageNumbers[pageNumbers.length - 1]}.html`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);
      
      toast.success("Export downloaded! Open in browser and print to PDF if needed.");
    } catch (error) {
      console.error('Export error:', error);
      toast.error("Failed to export pages. Make sure pages are translated first.");
    } finally {
      setIsExporting(false);
    }
  };

  if (loading || !book) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="text-center">
          <Loader2 className="h-12 w-12 text-accent mx-auto mb-4 animate-spin" />
          <p className="text-muted-foreground">Loading book...</p>
        </div>
      </div>
    );
  }

  const currentPageData = pages[currentPage];

  return (
    <div className="min-h-screen bg-background flex flex-col">
      {/* Navigation Header */}
      <header className="border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60 sticky top-0 z-50">
        <div className="container max-w-none flex items-center justify-between h-16 px-4 lg:px-6 xl:px-8">
          <div className="flex items-center gap-4">
            <Button variant="ghost" size="sm" onClick={() => navigate("/dashboard")}>
              <ArrowLeft className="h-4 w-4 mr-2" />
              Back
            </Button>
            <div className="flex flex-col">
              <h1 className="text-sm font-semibold truncate max-w-[200px] sm:max-w-md">
                {book.title}
              </h1>
              <div className="flex items-center gap-2">
                <Progress 
                  value={(translatedPagesCount.translated / translatedPagesCount.total) * 100} 
                  className="h-1.5 w-24" 
                />
                <span className="text-[10px] text-muted-foreground">
                  {translatedPagesCount.translated}/{translatedPagesCount.total} pages translated
                </span>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <div id="reader-desktop-controls" className="hidden lg:flex items-center gap-2" />
            {!isOnline && (
              <div className="flex items-center text-yellow-600 bg-yellow-50 px-2 py-1 rounded text-xs mr-2">
                <WifiOff className="h-3 w-3 mr-1" />
                Offline
              </div>
            )}
            
            <PageSearch 
              bookId={book.id}
              onPageSelect={setCurrentPage} 
              currentPage={currentPage}
            />

            <Button
              variant={viewMode === 'text' ? 'default' : 'outline'}
              size="sm"
              onClick={() => setViewMode('text')}
              title="Text view (translated)"
            >
              <FileText className="h-4 w-4" />
            </Button>
            
            <Button
              variant={viewMode === 'pdf' ? 'default' : 'outline'}
              size="sm"
              onClick={() => setViewMode('pdf')}
              disabled={!pdfUrl}
              title="Original PDF view"
            >
              <FileImage className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </header>

      <main className="flex-1 overflow-auto">
        <div className="container max-w-5xl py-6 lg:max-w-none lg:px-6 xl:px-8">
          {showSubscriptionError && (
            <div className="mb-6">
              <SubscriptionBanner />
            </div>
          )}

          {/* Translation Controls */}
          {viewMode === 'text' && (
            <div className="mb-6 flex flex-wrap items-center gap-4 bg-accent/5 p-4 rounded-lg border border-accent/10">
              <div className="flex items-center gap-4 flex-1 min-w-[200px]">
                <Button
                  onClick={startTranslation}
                  disabled={autoTranslate || (currentPageData?.status === 'completed' && translatedPagesCount.translated === translatedPagesCount.total)}
                  variant={autoTranslate ? "outline" : "default"}
                  className="w-full sm:w-auto"
                >
                  {autoTranslate ? (
                    <>
                      <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                      Auto-translating...
                    </>
                  ) : (
                    "Start Auto-Translation"
                  )}
                </Button>
                
                {autoTranslate && (
                  <Button variant="ghost" size="sm" onClick={() => setAutoTranslate(false)}>
                    Pause
                  </Button>
                )}
              </div>

              <div className="flex items-center gap-2 border-l pl-4">
                <Input
                  type="number"
                  min="1"
                  max={book.total_pages}
                  value={prefetchCount}
                  onChange={(e) => setPrefetchCount(parseInt(e.target.value) || 1)}
                  className="w-20 h-9"
                  title="Number of pages to pre-translate/export"
                />
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handlePrefetch}
                  disabled={isPrefetching}
                >
                  {isPrefetching ? (
                    <>
                      <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                      {prefetchProgress.current}/{prefetchProgress.total}
                    </>
                  ) : (
                    <>
                      <Download className="h-4 w-4 mr-2" />
                      Pre-translate
                    </>
                  )}
                </Button>
                
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleExport}
                  disabled={isExporting}
                >
                  {isExporting ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <>
                      <FileDown className="h-4 w-4 mr-2" />
                      Export
                    </>
                  )}
                </Button>
              </div>
            </div>
          )}

          {viewMode === 'text' ? (
            <ReadingView
              pageNumber={currentPage}
              originalText={currentPageData?.original_text || ""}
              translationData={currentPageData?.translated_data}
              images={currentPageData?.images}
              onNextPage={handleNextPage}
              onPrevPage={handlePrevPage}
              totalPages={book.total_pages}
              bookId={book.id}
              originalLocale={book.original_locale}
              isProcessing={currentPageData?.status === 'processing'}
              isActuallyTranslating={translatingPageIds.has(currentPageData?.id || "")}
              translationProgress={currentPageData ? translationProgress[currentPageData.id] : undefined}
              isPending={currentPageData?.status === 'pending'}
              isFailed={currentPageData?.status === 'failed'}
              onStartTranslation={startTranslation}
              onRetryTranslation={() => translatePage(currentPageData!.id, currentPage)}
              showSubscriptionError={showSubscriptionError}
            />
          ) : (
            <div className="h-[calc(100vh-12rem)]">
              {pdfUrl && (
                <PdfViewer
                  pdfUrl={pdfUrl}
                  pageNumber={currentPage}
                />
              )}
            </div>
          )}
        </div>
      </main>
    </div>
  );
};

export default Read;
