import { useEffect, useRef, useState } from 'react';
import { Loader2 } from 'lucide-react';
import * as pdfjsLib from 'pdfjs-dist';

// Set up the worker using the installed package
// @ts-ignore - Vite will handle this
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';
pdfjsLib.GlobalWorkerOptions.workerSrc = workerUrl;

interface PdfViewerProps {
  pdfUrl: string;
  pageNumber: number;
}

const PdfViewer = ({ pdfUrl, pageNumber }: PdfViewerProps) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let isMounted = true;

    const loadPage = async () => {
      if (!canvasRef.current) return;
      
      try {
        setLoading(true);
        setError(null);

        console.log('Loading PDF from URL:', pdfUrl);
        
        const loadingTask = pdfjsLib.getDocument({
          url: pdfUrl,
          withCredentials: false
        });
        const pdf = await loadingTask.promise;
        
        if (!isMounted) return;

        console.log('PDF loaded, rendering page:', pageNumber);
        
        const page = await pdf.getPage(pageNumber);
        const viewport = page.getViewport({ scale: 1.5 });

        const canvas = canvasRef.current;
        const context = canvas.getContext('2d');
        
        if (!context) {
          setError('Canvas context not available');
          return;
        }

        canvas.height = viewport.height;
        canvas.width = viewport.width;

        await page.render({
          canvasContext: context,
          viewport: viewport
        } as any).promise;
        
        console.log('Page rendered successfully');
        
        if (isMounted) {
          setLoading(false);
        }
      } catch (err) {
        console.error('Error loading PDF page:', err);
        if (isMounted) {
          setError(`Failed to load PDF page: ${err instanceof Error ? err.message : 'Unknown error'}`);
          setLoading(false);
        }
      }
    };

    loadPage();

    return () => {
      isMounted = false;
    };
  }, [pdfUrl, pageNumber]);

  return (
    <div className="relative flex items-center justify-center bg-muted/30 rounded-lg p-4 min-h-[600px]">
      {loading && (
        <div className="absolute inset-0 flex items-center justify-center">
          <Loader2 className="h-8 w-8 animate-spin text-accent" />
        </div>
      )}
      {error && (
        <div className="absolute inset-0 flex items-center justify-center">
          <p className="text-destructive">{error}</p>
        </div>
      )}
      <canvas ref={canvasRef} className={`max-w-full h-auto ${loading ? 'opacity-0' : 'opacity-100'} transition-opacity`} />
    </div>
  );
};

export default PdfViewer;