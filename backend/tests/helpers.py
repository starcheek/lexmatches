import time


def make_pdf(pages: list[str], size: float = 12, image_only: tuple[int, ...] = ()) -> bytes:
    """A4 PDF with one Helvetica text line per input line (pypdfium2); a line starting with "# " is a 16 pt bold
    heading. Pages listed in `image_only` (0-based) get a full-page image and no text, like a scan."""
    import ctypes
    import io

    import pypdfium2 as pdfium
    import pypdfium2.raw as R

    pdf = pdfium.PdfDocument.new()
    for n, text in enumerate(pages):
        page = pdf.new_page(595, 842)
        if n in image_only:
            img = R.FPDFPageObj_NewImageObj(pdf.raw)
            bitmap = pdfium.PdfBitmap.new_native(200, 280, R.FPDFBitmap_BGR)
            bitmap.fill_rect((240, 240, 240, 255), 0, 0, 200, 280)
            R.FPDFImageObj_SetBitmap(None, 0, img, bitmap.raw)
            R.FPDFImageObj_SetMatrix(img, 595, 0, 0, 842, 0, 0)
            R.FPDFPage_InsertObject(page.raw, img)
        y = 842 - 60
        for line in (text or "").split("\n"):
            heading = line.startswith("# ")
            if line:
                font, fsize = (b"Helvetica-Bold", 16) if heading else (b"Helvetica", size)
                obj = R.FPDFPageObj_NewTextObj(pdf.raw, font, fsize)
                buf = ctypes.create_string_buffer((line[2:] if heading else line).encode("utf-16-le") + b"\0\0")
                R.FPDFText_SetText(obj, ctypes.cast(buf, ctypes.POINTER(ctypes.c_ushort)))
                R.FPDFPageObj_Transform(obj, 1, 0, 0, 1, 50, y)
                R.FPDFPage_InsertObject(page.raw, obj)
            y -= (24 if heading else size * 1.4)
        R.FPDFPage_GenerateContent(page.raw)
    out = io.BytesIO()
    pdf.save(out)
    return out.getvalue()


def wait_for(fn, timeout: float = 20.0, interval: float = 0.1):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = fn()
        if value:
            return value
        time.sleep(interval)
    raise AssertionError("condition not met in time")
