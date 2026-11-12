"""Orchestration: bytes / pasted text / URL -> Document (IR with sentences).

    L0  sniff (content, never the extension) -> DRM check -> format parser (formats/*)
    L1  characters        PDF: on spans inside formats.pdf_layout; others: levels.clean_text on blocks
    L2  layout/boilerplate PDF: headers, columns, footnotes (pdf_layout); all: levels.flag_boilerplate
    L3  structure         PDF: pdf_structure; markup formats: from the markup; text: formats.text; all: levels.infer_structure
    L4  quality           language vote + warnings (levels.assess); PDF: OCR gate (ocr.gate / ocr.ocr_pages)
    L6  sentences         sentences.segment_block
Reading units are built from the result by units.build_units.
"""
from __future__ import annotations

import re
import time

from app.ingest import drm, langid, levels, ocr, sniff
from app.ingest.formats import epub, fb2, html, office, text as textfmt
from app.ingest.ir import Block, Document, IngestError, NoText, UnsupportedFormat
from app.ingest.sentences import segment_block

MAX_FILE_BYTES = 100 * 1024 * 1024
MAX_TEXT_CHARS = 1_000_000  # pasted text (~600 book pages)
_MATH_FONT = re.compile(r"^(CM(MI|SY|EX)|MSAM|MSBM|LMMath|STIX.*Math|Cambria ?Math|.*Math$|Symbol)", re.I)


def _raw_lang(text: str) -> str | None:
    lang, score = langid.detect(text[:20000])
    return lang if score > 0.5 else None


# ------------------------------------------------------------------------------------------------ PDF
def _pdf(data: bytes, declared: str | None) -> Document:
    from app.ingest.formats import pdf, pdf_layout, pdf_structure
    t0 = time.perf_counter()
    pages, info = pdf.extract(data)
    sample = " ".join(ln.text for p in pages[:30] for ln in p.lines)
    lang = declared or _raw_lang(sample) or "en"
    doc = Document([], "pdf", "pypdfium2 + lexmatches pdf L1-L3", author=info["author"] or None,
                   page_count=len(pages))
    doc.audit.add("L0", "pages", len(pages))
    _pdf_warnings(doc, pages)
    layout = pdf_layout.run(pages, lang, doc.audit)
    doc.blocks = pdf_structure.run(pages, lang, doc.audit, layout)
    if layout["vertical"]:
        doc.warn("vertical_text", "Vertical (tategaki) layout detected and re-ordered right-to-left.")
    if layout["multi_column_pages"]:
        doc.warn("multi_column", "Multi-column pages were re-ordered column by column.",
                 pages=layout["multi_column_pages"][:100])
    doc.ocr_pages = ocr.gate(pages, lang)
    if doc.ocr_pages:
        _splice_ocr(doc, data, lang)
    doc.title = info["title"] or None
    doc.audit.add("L0", "seconds_x100", int(100 * (time.perf_counter() - t0)))
    return doc


def _pdf_warnings(doc: Document, pages) -> None:
    math_pages, table_pages = [], []
    for p in pages:
        spans = [s for ln in p.lines for s in ln.spans]
        chars = sum(len(s.text) for s in spans) or 1
        if sum(len(s.text) for s in spans if _MATH_FONT.match(s.font)) / chars > 0.03:
            math_pages.append(p.number)
        rows: dict[int, int] = {}
        for ln in p.lines:
            rows[round(ln.y0 / 2)] = rows.get(round(ln.y0 / 2), 0) + 1
        if sum(1 for n in rows.values() if n >= 3) >= 3:
            table_pages.append(p.number)
    if math_pages:
        doc.warn("math", "Mathematical formulas are not reconstructed and may read garbled.", pages=math_pages[:100])
    if table_pages:
        doc.warn("tables", "Tables are read as plain text lines.", pages=table_pages[:100])
    if any(p.invisible > 0.5 and p.image_area > 0.8 for p in pages):
        doc.warn("ocr_text_layer", "Some pages are scans with an OCR text layer; their text may contain "
                                   "recognition errors.")


def _splice_ocr(doc: Document, data: bytes, lang: str) -> None:
    pages = doc.ocr_pages
    doc.route_to_ocr = len(pages) > 0.2 * (doc.page_count or 1)
    try:
        replacement = ocr.ocr_pages(data, pages, lang)
    except ocr.OcrUnavailable:
        for b in doc.blocks:
            if b.source_page in pages:
                b.remove("needs_ocr")
        doc.warn("scanned_pages", "Scanned pages are not supported yet: pages " + _ranges(pages) + ".", pages=pages)
        doc.audit.add("L4", "pages_need_ocr", len(pages))
        return
    keep = [b for b in doc.blocks if b.source_page not in replacement]
    for page, blocks in sorted(replacement.items()):
        idx = next((i for i, b in enumerate(keep) if (b.source_page or 0) > page), len(keep))
        keep[idx:idx] = blocks
    doc.blocks = keep
    doc.audit.add("L4", "pages_ocred", len(replacement))


def _ranges(nums: list[int]) -> str:
    out, start, prev = [], None, None
    for n in sorted(nums) + [None]:
        if start is not None and n == prev + 1:
            prev = n
            continue
        if start is not None:
            out.append(f"{start}–{prev}" if prev > start else str(start))
        start = prev = n
    return ", ".join(out)


# ------------------------------------------------------------------------------------------------ others
def _finish(doc: Document, declared: str | None, text_source: bool = False) -> Document:
    """Shared L1 (non-PDF), L2, L3 inference, L4, L6. Mutates and returns doc."""
    if doc.source_format != "pdf":
        lang = declared or langid.norm_lang(doc.language) or \
            _raw_lang(" ".join(b.text for b in doc.blocks[:400])) or "en"
        for b in doc.blocks:
            b.text = levels.clean_text(b.text, lang, doc.audit, keep_newlines=b.type in ("verse", "table"),
                                       entities=text_source).strip()
        doc.blocks = [b for b in doc.blocks if b.text or b.type == "separator"]
        if doc.source_format not in ("epub", "html", "url", "paste_html"):
            levels.infer_structure(doc)
    levels.flag_boilerplate(doc, strip_reference_marks=text_source or doc.source_format in ("paste_html", "url"))
    levels.assess(doc, declared)
    if not doc.title:
        first = next((b for b in doc.blocks if b.readable and b.type == "heading" and len(b.text) < 120), None)
        doc.title = first.text if first else None
    for b in doc.blocks:
        b.sentences = segment_block(b.text, b.type, doc.language) if b.type != "separator" else []
    doc.blocks = [b for b in doc.blocks if b.type != "separator" or b.removed]
    doc.renumber()
    if not any(b.readable for b in doc.blocks):
        if doc.ocr_pages:
            raise NoText("This PDF is scanned (no usable text layer). Scanned books are not supported yet.")
        raise NoText("No readable text was found in this document.")
    return doc


_UNSUPPORTED = {
    "mobi": "MOBI/AZW3 (Kindle) files are not supported. Please convert the book to EPUB (e.g. with Calibre) or "
            "download the EPUB edition.",
    "ole_doc": "Legacy Word .doc files are not supported; please save as .docx, .odt or PDF.",
    "unknown_zip": "Unsupported or unrecognised file format. Supported: PDF, EPUB, FB2, DOCX, ODT, RTF, Markdown, "
                   "HTML and plain text.",
}


def _check(data: bytes, epub_drm: bool = True) -> str:
    """Sniff + DRM / unsupported / binary checks without parsing; returns the raw sniffed kind."""
    if len(data) > MAX_FILE_BYTES:
        raise IngestError(f"File too large (max {MAX_FILE_BYTES // 1024 // 1024} MB).")
    kind = sniff.sniff(data)
    drm.check(kind, data)
    if kind == "epub" and epub_drm:
        zr = epub.ZipReader(data, [])
        drm.check_epub({n.lower(): n for n in zr.names}, zr.read)
    if kind in _UNSUPPORTED:
        raise UnsupportedFormat(_UNSUPPORTED[kind])
    if kind == "text" and b"\x00" in data[:4096] and not data.startswith((b"\xff\xfe", b"\xfe\xff")):
        raise UnsupportedFormat(_UNSUPPORTED["unknown_zip"])  # binary (image, archive, ...)
    return kind


def precheck(data: bytes) -> str:
    """Fast upload check: the source format (pdf, epub, fb2, docx, odt, rtf, html, txt) or a typed IngestError."""
    kind = _check(data)
    return {"fb2zip": "fb2", "txtzip": "txt", "text": "txt"}.get(kind, kind)


def ingest_file(data: bytes, declared_language: str | None = None, url: str | None = None) -> Document:
    """Any supported file (format sniffed from the bytes). Raises IngestError subclasses with user messages."""
    kind = _check(data, epub_drm=False)  # formats.epub checks DRM with its damage-tolerant reader
    declared = langid.norm_lang(declared_language)
    if kind == "pdf":
        return _finish(_pdf(data, declared), declared)
    if kind == "epub":
        doc = epub.parse(data)
    elif kind in ("fb2", "fb2zip"):
        doc = fb2.parse(data, zipped=kind == "fb2zip")
    elif kind == "docx":
        doc = office.parse_docx(data)
    elif kind == "odt":
        doc = office.parse_odt(data)
    elif kind == "rtf":
        doc = office.parse_rtf(data, declared)
    elif kind in ("html", "text", "txtzip"):
        return _text_like(data, kind, declared, url)
    else:
        raise UnsupportedFormat(_UNSUPPORTED.get(kind, _UNSUPPORTED["unknown_zip"]))
    return _finish(doc, declared, text_source=kind == "rtf")


def _text_like(data: bytes, kind: str, declared: str | None, url: str | None) -> Document:
    from app.ingest.encoding import decode
    if kind == "txtzip":
        data = textfmt.unzip_text(data)
    text, rep = decode(data)
    if kind == "html" or sniff.looks_like_html(text):
        doc = html.parse_document(text, url=url, mode="web" if url else None,
                                  source_format="url" if url else "html")
        return _finish(doc, declared)
    doc = textfmt.parse_text(text, declared, source_format="txt")
    if rep["method"] == "decode+langid":
        doc.warn("encoding_guessed", f"Text encoding guessed as {rep['encoding']}.")
    doc.audit.add("L0", "encoding_" + rep["method"].split(" ")[0])
    return _finish(doc, declared, text_source=True)


def ingest_text(text: str, declared_language: str | None = None, html_text: str | None = None) -> Document:
    """Pasted content: rich clipboard HTML when available, else plain text (web-page copy, PDF-viewer copy,
    prose); Markdown and Aozora notation are recognised."""
    declared = langid.norm_lang(declared_language)
    if html_text and html_text.strip():
        if len(html_text) > 5 * MAX_TEXT_CHARS:
            raise IngestError("Pasted content is too large.")
        doc = html.parse_document(html_text, mode="web", source_format="paste_html")
        return _finish(doc, declared)
    if len(text) > MAX_TEXT_CHARS:
        raise IngestError(f"Pasted text is too long (max {MAX_TEXT_CHARS:,} characters).")
    if sniff.looks_like_html(text):
        return _finish(html.parse_document(text, mode="web", source_format="paste_html"), declared)
    doc = textfmt.parse_text(text, declared, source_format="paste")
    return _finish(doc, declared, text_source=True)


def ingest_url(url: str, declared_language: str | None = None) -> Document:
    from app.ingest.fetch import fetch
    data, final_url = fetch(url)
    return ingest_file(data, declared_language, url=final_url)


def text_to_blocks(text: str, language: str | None = None) -> list[dict]:
    """Blocks with sentences for plain text that has no stored structure (pages from before structured
    ingestion, ad-hoc text): paragraphs re-flowed like a TXT file, nothing removed."""
    if not (text or "").strip():
        return []
    lang = langid.norm_lang(language) or _raw_lang(text) or "en"
    doc = textfmt.parse_text(text, lang, source_format="txt")
    for b in doc.blocks:
        b.sentences = segment_block(b.text, b.type, lang)
    doc.renumber()
    return [b.to_json() for b in doc.blocks if b.type != "separator"]


def apply_overrides(doc: Document, restore=(), remove=(), language: str | None = None) -> Document:
    """User decisions from the preview: restore / remove block ids, segmentation language."""
    restore, remove = set(restore or ()), set(remove or ())
    for b in doc.blocks:
        if b.id in restore:
            b.removed, b.role = None, "body"
        if b.id in remove:
            b.remove("user")
    lang = langid.norm_lang(language)
    if lang and lang != doc.language:
        doc.language = lang
        for b in doc.blocks:
            b.sentences = segment_block(b.text, b.type, lang)
    if not any(b.readable for b in doc.blocks):
        raise NoText("Nothing left to read: all blocks are removed.")
    return doc


__all__ = ["ingest_file", "ingest_text", "ingest_url", "apply_overrides", "Block", "Document"]
