// Renders one page of the original PDF. Lazy-loaded (pdf.js is ~400 kB): see Read.tsx.
import { useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";
import * as pdfjsLib from "pdfjs-dist";
import type { PDFDocumentProxy } from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";

pdfjsLib.GlobalWorkerOptions.workerSrc = workerUrl;

interface PdfViewerProps {
  pdfUrl: string;
  /** 1-based PDF page (the reading unit's source_page_start, not necessarily its page_number). */
  pageNumber: number;
}

const PdfViewer = ({ pdfUrl, pageNumber }: PdfViewerProps) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [doc, setDoc] = useState<PDFDocumentProxy | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Load the document once per URL.
  useEffect(() => {
    let cancelled = false;
    const task = pdfjsLib.getDocument({ url: pdfUrl });
    task.promise.then(
      (d) => !cancelled && setDoc(d),
      (e) => !cancelled && setError(`Could not open the PDF: ${e instanceof Error ? e.message : e}`),
    );
    return () => {
      cancelled = true;
      void task.destroy();
    };
  }, [pdfUrl]);

  useEffect(() => {
    if (!doc || !canvasRef.current) return;
    let cancelled = false;
    let render: { cancel: () => void } | null = null;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        if (pageNumber < 1 || pageNumber > doc.numPages) throw new Error(`the PDF has ${doc.numPages} pages`);
        const page = await doc.getPage(pageNumber);
        if (cancelled || !canvasRef.current) return;
        const viewport = page.getViewport({ scale: Math.min(2, window.devicePixelRatio || 1) * 1.25 });
        const canvas = canvasRef.current;
        canvas.width = viewport.width;
        canvas.height = viewport.height;
        const task = page.render({ canvas, viewport });
        render = task;
        await task.promise;
        if (!cancelled) setLoading(false);
      } catch (e) {
        if (!cancelled && !(e instanceof Error && e.name === "RenderingCancelledException")) {
          setError(`Could not show PDF page ${pageNumber}: ${e instanceof Error ? e.message : e}`);
          setLoading(false);
        }
      }
    })();
    return () => {
      cancelled = true;
      render?.cancel();
    };
  }, [doc, pageNumber]);

  return (
    <div className="relative flex min-h-[60vh] items-start justify-center rounded-lg bg-muted/30 p-2 sm:p-4">
      {loading && !error && (
        <div className="absolute inset-0 flex items-center justify-center">
          <Loader2 className="h-8 w-8 animate-spin text-accent" aria-label="Loading PDF page" />
        </div>
      )}
      {error && <p className="m-auto p-6 text-center text-sm text-destructive">{error}</p>}
      <canvas
        ref={canvasRef}
        className={`h-auto max-w-full rounded shadow-soft transition-opacity ${loading || error ? "opacity-0" : "opacity-100"}`}
        aria-label={`PDF page ${pageNumber}`}
      />
    </div>
  );
};

export default PdfViewer;
