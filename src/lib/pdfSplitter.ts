import { PDFDocument } from 'pdf-lib';

const MAX_PAGES_PER_PART = 150;

export interface PdfPart {
  blob: Blob;
  startPage: number;
  endPage: number;
  partNumber: number;
  totalParts: number;
}

/**
 * Splits a PDF into parts of MAX_PAGES_PER_PART pages each
 */
export async function splitPdf(file: File): Promise<PdfPart[]> {
  const arrayBuffer = await file.arrayBuffer();
  const pdfDoc = await PDFDocument.load(arrayBuffer);
  const totalPages = pdfDoc.getPageCount();
  
  // If PDF is within limit, return as single part
  if (totalPages <= MAX_PAGES_PER_PART) {
    return [{
      blob: new Blob([arrayBuffer], { type: 'application/pdf' }),
      startPage: 1,
      endPage: totalPages,
      partNumber: 1,
      totalParts: 1
    }];
  }
  
  const parts: PdfPart[] = [];
  const totalParts = Math.ceil(totalPages / MAX_PAGES_PER_PART);
  
  for (let i = 0; i < totalParts; i++) {
    const startPage = i * MAX_PAGES_PER_PART;
    const endPage = Math.min((i + 1) * MAX_PAGES_PER_PART, totalPages);
    
    // Create a new PDF with just this range of pages
    const newPdf = await PDFDocument.create();
    const pageIndices = Array.from(
      { length: endPage - startPage },
      (_, idx) => startPage + idx
    );
    
    const copiedPages = await newPdf.copyPages(pdfDoc, pageIndices);
    copiedPages.forEach(page => newPdf.addPage(page));
    
    const pdfBytes = await newPdf.save();
    const blob = new Blob([new Uint8Array(pdfBytes)], { type: 'application/pdf' });
    
    parts.push({
      blob,
      startPage: startPage + 1, // 1-indexed for display
      endPage,
      partNumber: i + 1,
      totalParts
    });
  }
  
  return parts;
}

/**
 * Get page count from a PDF file without fully loading it
 */
export async function getPdfPageCount(file: File): Promise<number> {
  const arrayBuffer = await file.arrayBuffer();
  const pdfDoc = await PDFDocument.load(arrayBuffer);
  return pdfDoc.getPageCount();
}

export const MAX_PAGES = MAX_PAGES_PER_PART;
