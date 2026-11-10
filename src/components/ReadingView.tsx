import { useState, useRef, useEffect, useCallback } from "react";
import { createPortal } from "react-dom";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Eye, EyeOff, ChevronLeft, ChevronRight, Loader2, Volume2, Square, ScanEye, Keyboard } from "lucide-react";
import { supabase } from "@/integrations/supabase/client";
import { toast } from "sonner";
import { useEyeTracking } from "@/hooks/useEyeTracking";

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

interface ReadingViewProps {
  pageNumber: number;
  originalText: string;
  translationData?: TranslationData;
  images?: PageImage[];
  onNextPage: () => void;
  onPrevPage: () => void;
  totalPages: number;
  bookId: string;
  originalLocale?: string;
  isProcessing?: boolean;
  isPending?: boolean;
  isFailed?: boolean;
  isActuallyTranslating?: boolean;
  translationProgress?: { done: number; total: number; rateLimited?: boolean };
  onStartTranslation?: () => void;
  onRetryTranslation?: () => void;
  showSubscriptionError?: boolean;
}

const ReadingView = ({
  pageNumber,
  originalText,
  translationData,
  images = [],
  onNextPage,
  onPrevPage,
  totalPages,
  bookId,
  originalLocale,
  isProcessing = false,
  isPending = false,
  isActuallyTranslating = false,
  translationProgress,
  isFailed = false,
  onStartTranslation,
  onRetryTranslation,
  showSubscriptionError = false,
}: ReadingViewProps) => {
  const [showTranslations, setShowTranslations] = useState(true);
  // Defensive: a truncated/partial realtime payload can arrive without `lines`
  const safeLines: WordPair[][] = Array.isArray(translationData?.lines) ? translationData.lines : [];
  const hasRenderableLines = safeLines.some(line => Array.isArray(line) && line.length > 0);
  const [clickCount, setClickCount] = useState(0);
  const linesContainerRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  
  // Keyboard controls tooltip
  const [showControlsTip, setShowControlsTip] = useState(false);
  const [tipDismissed, setTipDismissed] = useState(false);
  const [desktopControlsHost, setDesktopControlsHost] = useState<HTMLElement | null>(null);

  // Scroll progress: percentage of lines left to complete the page
  const [scrollProgress, setScrollProgress] = useState(100);

  useEffect(() => {
    setDesktopControlsHost(document.getElementById("reader-desktop-controls"));
  }, []);

  // On desktop, keep every source line on one row and use the available width.
  useEffect(() => {
    if (!hasRenderableLines) return;

    const fitLines = () => {
      if (!window.matchMedia("(min-width: 1024px)").matches) return;

      const lineElements = linesContainerRef.current?.querySelectorAll<HTMLElement>(".translated-line");
      lineElements?.forEach((lineElement) => {
        const pairs = lineElement.querySelector<HTMLElement>(".translated-line-pairs");
        if (!pairs) return;

        lineElement.style.removeProperty("--fitted-line-size");
        const availableWidth = pairs.clientWidth;
        const naturalWidth = pairs.scrollWidth;
        if (availableWidth <= 0 || naturalWidth <= 0) return;

        const fittedSize = Math.min(24, 18 * (availableWidth / naturalWidth));
        lineElement.style.setProperty("--fitted-line-size", `${fittedSize}px`);
      });
    };

    const frame = window.requestAnimationFrame(fitLines);
    const observer = new ResizeObserver(fitLines);
    if (linesContainerRef.current) observer.observe(linesContainerRef.current);
    document.fonts?.ready.then(fitLines).catch(() => undefined);

    return () => {
      window.cancelAnimationFrame(frame);
      observer.disconnect();
    };
  }, [hasRenderableLines, pageNumber, safeLines]);

  // TTS state (Web Speech API)
  const [playingLineIndex, setPlayingLineIndex] = useState<number | null>(null);
  const [currentWordIndex, setCurrentWordIndex] = useState<number | null>(null);
  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>([]);
  const utteranceRef = useRef<SpeechSynthesisUtterance | null>(null);

  // Eye tracking
  const eyeTracking = useEyeTracking(containerRef);
  const [calibrationPoints, setCalibrationPoints] = useState<{x: number, y: number, id: number}[]>([]);

  // Handle calibration clicks
  const handleCalibrationClick = (e: React.MouseEvent) => {
    if (!eyeTracking.isCalibrating) return;
    const newPoint = { x: e.clientX, y: e.clientY, id: Date.now() };
    setCalibrationPoints(prev => [...prev, newPoint]);
    // Remove point after animation
    setTimeout(() => {
      setCalibrationPoints(prev => prev.filter(p => p.id !== newPoint.id));
    }, 1000);
  };

  // Clear calibration points when calibration ends
  useEffect(() => {
    if (!eyeTracking.isCalibrating) {
      setCalibrationPoints([]);
    }
  }, [eyeTracking.isCalibrating]);

  // Load available voices
  useEffect(() => {
    const loadVoices = () => {
      const availableVoices = window.speechSynthesis.getVoices();
      if (availableVoices.length > 0) {
        setVoices(availableVoices);
      }
    };

    loadVoices();
    // Chrome loads voices asynchronously
    window.speechSynthesis.onvoiceschanged = loadVoices;

    return () => {
      window.speechSynthesis.onvoiceschanged = null;
    };
  }, []);

  // Find the best voice for the language
  const getBestVoice = (locale?: string): SpeechSynthesisVoice | null => {
    if (voices.length === 0) return null;

    // Map full language names to ISO codes
    const localeMap: Record<string, string> = {
      english: "en",
      french: "fr",
      portuguese: "pt",
      russian: "ru",
      japanese: "ja",
      latvian: "lv",
    };

    const normalizedLocale = locale?.toLowerCase() || "";
    // Check if it's a full name or already a code
    const langCode = localeMap[normalizedLocale] || normalizedLocale.substring(0, 2);
    
    console.log(`Looking for voice for locale: "${locale}" -> langCode: "${langCode}"`);
    console.log(`Available voices:`, voices.map(v => `${v.name} (${v.lang})`));
    
    // Filter voices that match the language (e.g., "fr-FR", "fr-CA" for French)
    const matchingVoices = voices.filter(v => 
      v.lang.toLowerCase().startsWith(langCode + "-") || v.lang.toLowerCase() === langCode
    );

    console.log(`Matching voices for ${langCode}:`, matchingVoices.map(v => v.name));

    if (matchingVoices.length === 0) return null;

    // Prefer premium/natural voices (often have "Premium", "Enhanced", "Natural" in name)
    const premiumVoice = matchingVoices.find(v => 
      /premium|enhanced|natural|neural/i.test(v.name)
    );
    if (premiumVoice) return premiumVoice;

    // Prefer local voices over remote (usually better quality)
    const localVoice = matchingVoices.find(v => v.localService);
    if (localVoice) return localVoice;

    // Return first matching voice
    return matchingVoices[0];
  };

  // Track translation toggle clicks and save to database (robust on mobile:
  // flushes pending clicks on page change, tab hide/backgrounding and unmount)
  const pendingRef = useRef<{ page: number; clicks: number } | null>(null);

  const flushClicks = useCallback(async () => {
    const pending = pendingRef.current;
    if (!pending || pending.clicks === 0) return;
    pendingRef.current = null;

    const { data: { user } } = await supabase.auth.getUser();
    if (!user) return;

    const today = new Date().toISOString().split('T')[0];

    const { error } = await supabase
      .from('reading_sessions')
      .upsert({
        user_id: user.id,
        book_id: bookId,
        page_number: pending.page,
        session_date: today,
        translation_toggle_clicks: pending.clicks,
      }, {
        onConflict: 'user_id,book_id,page_number,session_date'
      });

    if (error) {
      console.error('Error saving click data:', error);
      pendingRef.current = pending; // keep for a later retry
    }
  }, [bookId]);

  useEffect(() => {
    if (clickCount === 0) return;
    pendingRef.current = { page: pageNumber, clicks: clickCount };
    const timeoutId = setTimeout(() => { void flushClicks(); }, 800);
    return () => clearTimeout(timeoutId);
  }, [clickCount, pageNumber, flushClicks]);

  // Flush when the app is backgrounded / closed (common on mobile)
  useEffect(() => {
    const onHide = () => { void flushClicks(); };
    document.addEventListener('visibilitychange', onHide);
    window.addEventListener('pagehide', onHide);
    return () => {
      document.removeEventListener('visibilitychange', onHide);
      window.removeEventListener('pagehide', onHide);
      void flushClicks();
    };
  }, [flushClicks]);

  // Reset states when page changes (flush the previous page's clicks first)
  useEffect(() => {
    void flushClicks();
    setClickCount(0);
    stopAudio();
  }, [pageNumber]);


  // Keyboard controls for reading (WASD + arrow keys)
  useEffect(() => {
    // Smooth, line-based scrolling engine
    let targetY = window.scrollY;
    let rafId: number | null = null;
    let holdTimer: ReturnType<typeof setTimeout> | null = null;
    let holdInterval: ReturnType<typeof setInterval> | null = null;
    let heldDirection = 0;

    const getLineHeight = () => {
      const lineEls = document.querySelectorAll('[data-line-index]');
      if (lineEls.length >= 2) {
        const a = (lineEls[0] as HTMLElement).getBoundingClientRect();
        const b = (lineEls[1] as HTMLElement).getBoundingClientRect();
        const step = b.top - a.top;
        if (step > 8) return step;
      }
      if (lineEls.length === 1) {
        const h = (lineEls[0] as HTMLElement).getBoundingClientRect().height;
        if (h > 8) return h;
      }
      const lh = parseFloat(getComputedStyle(document.body).lineHeight);
      return Number.isFinite(lh) && lh > 8 ? lh : 44;
    };


    const animate = () => {
      const current = window.scrollY;
      const delta = targetY - current;
      if (Math.abs(delta) < 0.5) {
        window.scrollTo({ top: targetY });
        rafId = null;
        return;
      }
      // ease-out: move a fraction of remaining distance each frame
      window.scrollTo({ top: current + delta * 0.22 });
      rafId = requestAnimationFrame(animate);
    };

    const scrollLines = (direction: number, lines = 1) => {
      const maxY = Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
      const base = rafId === null ? window.scrollY : targetY;
      targetY = Math.min(maxY, Math.max(0, base + direction * getLineHeight() * lines));
      if (rafId === null) rafId = requestAnimationFrame(animate);
    };

    const clearHold = () => {
      if (holdTimer) { clearTimeout(holdTimer); holdTimer = null; }
      if (holdInterval) { clearInterval(holdInterval); holdInterval = null; }
      heldDirection = 0;
    };

    const startHold = (direction: number) => {
      if (heldDirection === direction) return;
      clearHold();
      heldDirection = direction;
      scrollLines(direction);
      holdTimer = setTimeout(() => {
        holdInterval = setInterval(() => scrollLines(direction), 90);
      }, 220);
    };

    const handleKeyDown = (e: KeyboardEvent) => {
      const key = e.key;
      const code = e.code;

      // Vertical scroll: W/S and ArrowUp/ArrowDown
      if (key === 'w' || key === 'W' || key === 'ArrowUp' || key === 's' || key === 'S' || key === 'ArrowDown') {
        e.preventDefault();
        if (e.repeat) return; // our own hold engine handles repeats
        const direction = (key === 'w' || key === 'W' || key === 'ArrowUp') ? -1 : 1;
        startHold(direction);
        return;
      }

      // Translation toggle: A/D and ArrowLeft/ArrowRight (both act as simple toggles)
      if (
        key === 'a' || key === 'A' || key === 'ArrowLeft' ||
        key === 'd' || key === 'D' || key === 'ArrowRight'
      ) {
        e.preventDefault();
        if (e.repeat) return;
        setShowTranslations(prev => !prev);
        setClickCount(prev => prev + 1);
        return;
      }

      // Legacy numpad 3 (code: Numpad3) or regular 3 when numlock is off
      if (code === 'Numpad3' || (key === '3' && e.location === 3)) {
        e.preventDefault();
        setShowTranslations(prev => !prev);
        setClickCount(prev => prev + 1);
      }
    };

    const handleKeyUp = (e: KeyboardEvent) => {
      const key = e.key;
      if (key === 'w' || key === 'W' || key === 'ArrowUp' || key === 's' || key === 'S' || key === 'ArrowDown') {
        clearHold();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    window.addEventListener('keyup', handleKeyUp);
    window.addEventListener('blur', clearHold);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
      window.removeEventListener('keyup', handleKeyUp);
      window.removeEventListener('blur', clearHold);
      clearHold();
      if (rafId !== null) cancelAnimationFrame(rafId);
    };
  }, []);

  // ---- Bookmark: remember the top-most visible line and restore it on return ----
  const bookmarkKey = `lexmatches:bookmark:${bookId}`;
  const restoredRef = useRef(false);

  // Save the top visible line (upper bound) while scrolling, and track progress
  useEffect(() => {
    const totalLines = translationData?.lines?.length || 0;
    const save = () => {
      const lineEls = Array.from(document.querySelectorAll('[data-line-index]')) as HTMLElement[];
      if (lineEls.length === 0) return;
      const threshold = 120; // header offset
      let topLine = 0;
      for (const el of lineEls) {
        if (el.getBoundingClientRect().top <= threshold) {
          topLine = Number(el.dataset.lineIndex ?? 0);
        } else break;
      }
      try {
        localStorage.setItem(bookmarkKey, JSON.stringify({ page: pageNumber, line: topLine }));
      } catch { /* ignore */ }

      // Update "lines left" percentage under the toggle button
      if (totalLines > 0) {
        const linesLeft = Math.max(0, totalLines - topLine - 1);
        setScrollProgress(Math.round((linesLeft / totalLines) * 100));
      }
    };

    let t: ReturnType<typeof setTimeout> | null = null;
    const onScroll = () => {
      if (t) clearTimeout(t);
      t = setTimeout(save, 250);
    };
    window.addEventListener('scroll', onScroll, { passive: true });
    // Initial calculation once lines are rendered
    const initialTimeout = setTimeout(save, 500);
    return () => {
      window.removeEventListener('scroll', onScroll);
      if (t) clearTimeout(t);
      clearTimeout(initialTimeout);
    };
  }, [bookmarkKey, pageNumber, translationData]);

  // Restore bookmark once, when the bookmarked page's lines are rendered
  useEffect(() => {
    if (restoredRef.current) return;
    if (!hasRenderableLines) return;

    let saved: { page?: number; line?: number } | null = null;
    try {
      const raw = localStorage.getItem(bookmarkKey);
      saved = raw ? JSON.parse(raw) : null;
    } catch { saved = null; }

    if (!saved || saved.page !== pageNumber || !saved.line || saved.line < 1) {
      restoredRef.current = true;
      return;
    }

    const lineIndex = saved.line;
    const timeout = setTimeout(() => {
      const el = document.querySelector(`[data-line-index="${lineIndex}"]`) as HTMLElement | null;
      if (!el) return;
      restoredRef.current = true;
      const top = el.getBoundingClientRect().top + window.scrollY - 100;
      window.scrollTo({ top: Math.max(0, top), behavior: 'smooth' });
      toast.info(`Jumped back to where you left off (line ${lineIndex + 1})`);
    }, 350);

    return () => clearTimeout(timeout);
  }, [translationData, bookmarkKey, pageNumber]);


  // Cleanup on unmount
  useEffect(() => {
    return () => {
      stopAudio();
    };
  }, []);

  const handleToggleTranslations = () => {
    setShowTranslations(!showTranslations);
    setClickCount(prev => prev + 1);
  };

  const stopAudio = () => {
    window.speechSynthesis.cancel();
    utteranceRef.current = null;
    setPlayingLineIndex(null);
    setCurrentWordIndex(null);
  };

  const playLine = (lineIndex: number) => {
    // If already playing this line, stop it
    if (playingLineIndex === lineIndex) {
      stopAudio();
      return;
    }

    // Stop any current playback
    stopAudio();

    const line = safeLines[lineIndex];
    if (!Array.isArray(line) || line.length === 0) return;

    const lineText = line.map(pair => pair.original).join(" ");

    if (!lineText.trim()) return;

    // Check if Web Speech API is supported
    if (!window.speechSynthesis) {
      toast.error("Text-to-speech is not supported in your browser");
      return;
    }

    const utterance = new SpeechSynthesisUtterance(lineText);
    
    // Set the best available voice for this language
    const bestVoice = getBestVoice(originalLocale);
    if (bestVoice) {
      utterance.voice = bestVoice;
      utterance.lang = bestVoice.lang;
      console.log(`Using voice: ${bestVoice.name} (${bestVoice.lang})`);
    } else {
      // Fallback to just setting language
      const langCode = originalLocale?.toLowerCase()?.substring(0, 2) || "en";
      utterance.lang = langCode === "fr" ? "fr-FR" : langCode === "pt" ? "pt-BR" : langCode === "ru" ? "ru-RU" : langCode === "ja" ? "ja-JP" : "en-US";
    }
    
    utterance.rate = 0.9; // Slightly slower for language learning
    utteranceRef.current = utterance;

    // Word boundary event for highlighting
    let wordIndex = 0;
    utterance.onboundary = (event) => {
      if (event.name === "word") {
        setCurrentWordIndex(wordIndex);
        wordIndex++;
      }
    };

    utterance.onstart = () => {
      setPlayingLineIndex(lineIndex);
      setCurrentWordIndex(0);
    };

    utterance.onend = () => {
      stopAudio();
    };

    utterance.onerror = (event) => {
      if (event.error !== "canceled") {
        console.error("Speech error:", event.error);
        toast.error("Failed to play audio");
      }
      stopAudio();
    };

    window.speechSynthesis.speak(utterance);
  };

  return (
    <div ref={containerRef} className="min-h-screen bg-gradient-to-br from-background via-reading-bg to-background">
      {desktopControlsHost && translationData && !isProcessing && !isPending && !isFailed && createPortal(
        <>
          <div className="flex items-center gap-1.5">
            <Button
              variant={showTranslations ? "default" : "outline"}
              onClick={handleToggleTranslations}
              size="sm"
              title={showTranslations ? "Hide translations" : "Show translations"}
            >
              {showTranslations ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              <span className="hidden xl:inline ml-2">{showTranslations ? "Hide" : "Show"}</span>
            </Button>
            <span className="min-w-12 text-xs text-muted-foreground">{scrollProgress}% left</span>
          </div>
          <div
            className="relative"
            onMouseEnter={() => setShowControlsTip(true)}
            onMouseLeave={() => setShowControlsTip(false)}
          >
            <Button
              type="button"
              variant="ghost"
              size="icon"
              onClick={() => setShowControlsTip(prev => !prev)}
              aria-label="Keyboard controls"
              title="Keyboard controls"
              className="h-9 w-9"
            >
              <Keyboard className="h-4 w-4" />
            </Button>
            {showControlsTip && !tipDismissed && (
              <div className="absolute right-0 top-full mt-2 w-52 p-3 rounded-lg bg-popover text-popover-foreground shadow-lg border border-border text-xs space-y-2 z-30">
                <div className="font-medium text-foreground">Reading shortcuts</div>
                <div className="flex justify-between"><span className="text-muted-foreground">W / S / ↑ / ↓</span><span>Scroll</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">A / D / ← / →</span><span>Toggle</span></div>
                <Button type="button" variant="ghost" size="sm" onClick={() => setTipDismissed(true)} className="h-auto w-full justify-start px-0 py-1 text-xs text-muted-foreground">
                  Dismiss
                </Button>
              </div>
            )}
          </div>
        </>,
        desktopControlsHost
      )}
      {/* Eye tracking calibration overlay */}
      {eyeTracking.isCalibrating && (
        <div 
          className="fixed inset-0 bg-background/90 z-50 cursor-crosshair"
          onClick={handleCalibrationClick}
        >
          {/* Calibration points animation */}
          {calibrationPoints.map(point => (
            <div
              key={point.id}
              className="absolute pointer-events-none"
              style={{ left: point.x, top: point.y, transform: 'translate(-50%, -50%)' }}
            >
              <div className="w-8 h-8 rounded-full bg-primary animate-ping" />
              <div className="absolute inset-0 w-8 h-8 rounded-full bg-primary/50" />
            </div>
          ))}
          
          <div className="absolute inset-0 flex flex-col items-center justify-center p-8 pointer-events-none">
            <div className="max-w-md text-center space-y-4 pointer-events-auto">
              <ScanEye className="h-16 w-16 mx-auto text-primary animate-pulse" />
              <h2 className="text-2xl font-bold">Calibrating Eye Tracking</h2>
              <p className="text-muted-foreground">
                Click different parts of the screen while looking at the cursor.
                Click at least 9 points for best results.
              </p>
              <p className="text-sm text-muted-foreground">
                Points clicked: {calibrationPoints.length > 0 ? `${calibrationPoints.length}+` : '0'}
              </p>
              <div className="flex gap-2 justify-center">
                <Button onClick={() => eyeTracking.endCalibration()} variant="default">
                  Done Calibrating
                </Button>
                <Button onClick={() => eyeTracking.stopTracking()} variant="outline">
                  Cancel
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Eye tracking controls - floating button */}
      <div className="fixed bottom-20 right-4 z-40 flex flex-col gap-2">
        {eyeTracking.isActive && !eyeTracking.isCalibrating && (
          <div className="bg-primary/10 text-primary text-xs px-3 py-1 rounded-full">
            Eye tracking active
          </div>
        )}
        <Button
          size="icon"
          variant={eyeTracking.isActive ? "default" : "outline"}
          onClick={() => eyeTracking.isActive ? eyeTracking.stopTracking() : eyeTracking.startTracking()}
          disabled={eyeTracking.isLoading}
          className="rounded-full shadow-lg h-12 w-12"
          title={eyeTracking.isActive ? "Stop eye tracking" : "Start eye tracking for auto-scroll"}
        >
          {eyeTracking.isLoading ? (
            <Loader2 className="h-5 w-5 animate-spin" />
          ) : (
            <ScanEye className="h-5 w-5" />
          )}
        </Button>
      </div>

      {eyeTracking.error && (
        <div className="fixed bottom-36 right-4 z-40 bg-destructive text-destructive-foreground text-sm px-3 py-2 rounded-lg max-w-xs">
          {eyeTracking.error}
        </div>
      )}

      <div className="flex gap-4 lg:gap-6 max-w-7xl lg:max-w-none mx-auto my-8 px-4 lg:px-0">
        {/* Main content card */}
        <Card className="flex-1 min-w-0 p-4 lg:p-8 shadow-soft">
        <div className="mb-6 flex items-center gap-2 sm:gap-4">
          <Button variant="outline" size="sm" onClick={onPrevPage} disabled={pageNumber === 1}>
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <span className="text-sm font-medium">
            Page {pageNumber} of {totalPages}
          </span>
          <Button variant="outline" size="sm" onClick={onNextPage} disabled={pageNumber === totalPages}>
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>

        {/* Status banners */}
        {isProcessing && (
          <div className="mb-6">
            <Card className="p-4 bg-accent/10 border-accent/20">
              <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-3">
                  {isActuallyTranslating && <Loader2 className="h-5 w-5 text-accent animate-spin" />}
                  <div>
                    <p className="text-sm text-muted-foreground">
                      {isActuallyTranslating
                        ? translationProgress?.rateLimited
                          ? "Translation is cooling down briefly, then continuing…"
                          : "Translating this page…"
                        : "Translation was interrupted"}
                    </p>
                    {isActuallyTranslating && translationProgress && translationProgress.total > 0 && (
                      <p className="mt-1 text-xs text-muted-foreground">
                        {translationProgress.done} of {translationProgress.total} lines ready
                      </p>
                    )}
                  </div>
                </div>
                {!isActuallyTranslating && (
                  <Button variant="default" size="sm" onClick={onStartTranslation}>Resume</Button>
                )}
              </div>
              {isActuallyTranslating && translationProgress && translationProgress.total > 0 && (
                <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-muted">
                  <div
                    className="h-full bg-accent transition-all duration-500"
                    style={{ width: `${Math.min(100, (translationProgress.done / translationProgress.total) * 100)}%` }}
                  />
                </div>
              )}
            </Card>
          </div>
        )}
        
        {isPending && !showSubscriptionError && (
          <div className="mb-6">
            <Card className="p-4 bg-accent/10 border-accent/20">
              <div className="flex items-center justify-between">
                <p className="text-sm text-muted-foreground">Ready to translate this page</p>
                <Button variant="default" size="sm" onClick={onStartTranslation}>
                  Start Translation
                </Button>
              </div>
            </Card>
          </div>
        )}
        
        {isFailed && !showSubscriptionError && (
          <div className="mb-6">
            <Card className="p-4 bg-destructive/10 border-destructive/20">
              <div className="flex items-center justify-between">
                <p className="text-sm text-destructive">Translation failed</p>
                <Button variant="outline" size="sm" onClick={onRetryTranslation}>
                  Retry
                </Button>
              </div>
            </Card>
          </div>
        )}

        {hasRenderableLines ? (
          <>
            <div ref={linesContainerRef} className="reading-content space-y-4">
              {safeLines.map((line, lineIndex) => !Array.isArray(line) || line.length === 0 ? null : (
                <div key={lineIndex} data-line-index={lineIndex} className="translated-line leading-loose flex items-start gap-2">

                  {/* Speaker button for each line */}
                  <button
                    onClick={() => playLine(lineIndex)}
                    className="flex-shrink-0 mt-1 p-1.5 rounded-full hover:bg-accent/20 transition-colors"
                    title={playingLineIndex === lineIndex ? "Stop" : "Listen to this line"}
                  >
                    {playingLineIndex === lineIndex ? (
                      <Square className="h-4 w-4 text-primary fill-primary" />
                    ) : (
                      <Volume2 className="h-4 w-4 text-muted-foreground hover:text-foreground" />
                    )}
                  </button>
                  
                  {/* Word pairs */}
                  <div className="translated-line-pairs flex-1 min-w-0">
                    {line.map((pair, pairIndex) => (
                      <span 
                        key={pairIndex} 
                        className={`translated-word-pair inline-flex flex-col mr-3 mb-2 align-top transition-all duration-200 ${
                          playingLineIndex === lineIndex && currentWordIndex === pairIndex
                            ? 'bg-accent/30 rounded px-1 -mx-1'
                            : ''
                        }`}
                      >
                        <span className="translated-original text-lg font-serif text-foreground whitespace-nowrap">
                          {pair.original}
                        </span>
                        <span 
                          className={`translated-translation translation-text text-sm whitespace-nowrap transition-opacity duration-300 ${
                            showTranslations ? 'opacity-100' : 'opacity-0'
                          }`}
                          style={{ visibility: showTranslations ? 'visible' : 'hidden' }}
                        >
                          {pair.translation}
                        </span>
                      </span>
                    ))}
                  </div>
                </div>
              ))}
            </div>

            {/* Mobile toggle button */}
            {!isProcessing && !isPending && !isFailed && (
              <div className="lg:hidden mt-6 sticky bottom-4">
                <Button
                  variant={showTranslations ? "default" : "outline"}
                  onClick={handleToggleTranslations}
                  size="sm"
                  className="w-full shadow-lg"
                >
                  {showTranslations ? (
                    <>
                      <EyeOff className="h-4 w-4 mr-2" />
                      Hide Translations
                    </>
                  ) : (
                    <>
                      <Eye className="h-4 w-4 mr-2" />
                      Show Translations
                    </>
                  )}
                </Button>
              </div>
            )}
          </>
        ) : (
          <>
            <div className="reading-content space-y-4">
              <p className="text-lg font-serif text-foreground leading-relaxed whitespace-pre-wrap">
                {originalText}
              </p>
            </div>
          </>
        )}
        </Card>

        {/* Right sidebar with images */}
        {images.length > 0 && (
          <Card className="hidden lg:block w-80 p-4 shadow-soft h-fit sticky top-24">
            <h3 className="text-sm font-semibold text-muted-foreground mb-4">Page Images</h3>
            <ScrollArea className="h-[600px] pr-4">
              <div className="space-y-4">
                {images.map((image, idx) => (
                  <div key={idx} className="border border-border rounded-lg overflow-hidden">
                    <img 
                      src={image.data} 
                      alt={`Page image ${idx + 1}`} 
                      className="w-full h-auto"
                    />
                  </div>
                ))}
              </div>
            </ScrollArea>
          </Card>
        )}
      </div>
    </div>
  );
};

export default ReadingView;
