"""PDF L0 on pypdfium2 (Apache-2.0/BSD): per-character geometry -> visual lines of styled spans.

The upper PDF levels (pdf_layout L2, pdf_structure L3) only consume the Page/Line/Span objects below.
Font size = FPDFText_GetFontSize x sqrt(|det(char matrix)|), which equals PyMuPDF's span size on the lab corpus.
Lines are PDFium's own lines (generated CR/LF), split at wide horizontal gaps (columns sharing a baseline)
and re-merged when they share a baseline (superscript calls, list markers in separate text objects).
"""
from __future__ import annotations

import ctypes
import math
import re
from dataclasses import dataclass, field

import pypdfium2 as pdfium
import pypdfium2.raw as R

from app.ingest.ir import IngestError

PUA = re.compile("[-]")
CONTROL = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f]")


@dataclass(eq=False)
class Span:
    text: str
    font: str
    size: float
    bold: bool
    italic: bool
    sup: bool
    bbox: tuple


@dataclass(eq=False)
class Line:
    spans: list[Span]
    bbox: tuple                      # x0, y0, x1, y1, top-left origin (after L2: the page's reading frame)
    page: int                        # 1-based
    vertical: bool = False
    role: str = "body"               # body | header | footer | pagenum | margin | footnote | dropcap | ruby
    col: int = 0                     # flow segment index after reading-order analysis
    flow_break: bool = False         # first line of a flow segment (column / page start)
    notes: list = field(default_factory=list)

    @property
    def text(self) -> str:
        return "".join(s.text for s in self.spans)

    @property
    def size(self) -> float:
        acc: dict[float, int] = {}
        for s in self.spans:
            if not s.sup:
                acc[round(s.size, 1)] = acc.get(round(s.size, 1), 0) + len(s.text.strip())
        return max(acc, key=acc.get) if acc else (self.spans[0].size if self.spans else 0.0)

    @property
    def bold(self) -> bool:
        chars = [s for s in self.spans if s.text.strip()]
        return bool(chars) and all(s.bold for s in chars)

    @property
    def italic(self) -> bool:
        chars = [s for s in self.spans if s.text.strip()]
        return bool(chars) and all(s.italic for s in chars)

    x0 = property(lambda self: self.bbox[0])
    y0 = property(lambda self: self.bbox[1])
    x1 = property(lambda self: self.bbox[2])
    y1 = property(lambda self: self.bbox[3])


@dataclass(eq=False)
class Page:
    number: int
    width: float
    height: float
    lines: list[Line]
    image_area: float = 0.0          # fraction of the page covered by images
    chars: int = 0
    invisible: float = 0.0           # fraction of characters in render mode 3 (OCR text layer over a scan)
    bad_chars: float = 0.0           # control / private-use / U+FFFD share of the raw text
    columns: int = 1
    vertical: bool = False
    figures: list = field(default_factory=list)  # boxes of figure-sized images


class _Font:
    __slots__ = ("name", "size", "bold", "italic", "rotated", "invisible")


def _font(tp, i, obj, matrix, buf, flags) -> _Font:
    f = _Font()
    R.FPDFText_GetFontInfo(tp, i, buf, len(buf), ctypes.byref(flags))
    f.name = buf.value.decode("utf-8", "replace").split("+")[-1]
    R.FPDFText_GetMatrix(tp, i, ctypes.byref(matrix))
    f.size = R.FPDFText_GetFontSize(tp, i) * math.sqrt(abs(matrix.a * matrix.d - matrix.b * matrix.c))
    low = f.name.lower()
    f.bold = R.FPDFText_GetFontWeight(tp, i) >= 600 or any(k in low for k in ("bold", "black", "heavy", "semibold"))
    f.italic = bool(flags.value & 64) or "italic" in low or "oblique" in low
    f.rotated = abs(matrix.b) > 0.1 * abs(matrix.a or 1) or abs(matrix.c) > 0.1 * abs(matrix.d or 1)
    f.invisible = obj is not None and R.FPDFTextObj_GetTextRenderMode(obj) == 3
    return f


def _build_line(chars: list, page_no: int) -> Line | None:
    """chars: [(ch, x0, y0, x1, y1, baseline, font)] -> Line with superscript-aware spans."""
    real = [c for c in chars if c[0].strip()]
    if not real:
        return None
    vertical = any(c[6].rotated for c in real) or (
        len(real) >= 2 and (real[-1][2] - real[0][2]) > 1.5 * abs(real[-1][1] - real[0][1])
        and (real[-1][2] - real[0][2]) > real[0][6].size)
    sizes: dict[float, int] = {}
    for c in real:
        sizes[round(c[6].size, 1)] = sizes.get(round(c[6].size, 1), 0) + 1
    size = max(sizes, key=sizes.get)
    base = sorted(c[5] for c in real if abs(c[6].size - size) < 0.6)
    baseline = base[len(base) // 2] if base else real[0][5]
    spans: list[Span] = []
    cur, key = [], None
    for c in chars:
        f = c[6]
        sup = (not vertical and c[0].strip() != "" and f.size < 0.85 * size and c[5] < baseline - 0.2 * size)
        k = (f.name, round(f.size * 2) / 2, f.bold, f.italic, sup)
        if c[0] == " " and cur:
            k = key  # spaces never start a new span
        if cur and k != key:
            spans.append(_span(cur, key))
            cur = []
        cur.append(c)
        key = k
    if cur:
        spans.append(_span(cur, key))
    bbox = (min(c[1] for c in real), min(c[2] for c in real), max(c[3] for c in real), max(c[4] for c in real))
    return Line(spans, bbox, page_no, vertical)


def _span(chars, key) -> Span:
    real = [c for c in chars if c[0].strip()] or chars
    return Span("".join(c[0] for c in chars), key[0], key[1], key[2], key[3], key[4],
                (min(c[1] for c in real), min(c[2] for c in real), max(c[3] for c in real), max(c[4] for c in real)))


def _joinable(prev: Line, ln: Line) -> bool:
    if prev.y1 <= ln.y0 or ln.y1 <= prev.y0 or ln.x0 < prev.x1 - 1:
        return False
    h = min(prev.y1 - prev.y0, ln.y1 - ln.y0) or 1
    overlap = min(prev.y1, ln.y1) - max(prev.y0, ln.y0)
    size = max(prev.size, ln.size, 1)
    ratio = max(prev.size, ln.size) / max(0.1, min(prev.size, ln.size))
    return ratio < 1.6 and overlap > 0.45 * h and -1 <= ln.x0 - prev.x1 < 1.2 * size


def _merge_same_baseline(lines: list[Line]) -> list[Line]:
    """Join fragments of one visual line, whatever their order in the content stream (separately drawn dashes,
    superscript footnote calls, list markers)."""
    out: list[Line] = []
    for ln in sorted((x for x in lines if not x.vertical), key=lambda x: x.x0):
        prev = next((p for p in reversed(out) if _joinable(p, ln)), None)
        if prev is None:
            out.append(ln)
            continue
        size = max(prev.size, ln.size, 1)
        spans = list(prev.spans)
        if ln.x0 - prev.x1 > 0.15 * size and not prev.text.endswith(" ") and not ln.text.startswith(" "):
            s = spans[-1]
            spans.append(Span(" ", s.font, s.size, s.bold, s.italic, False, (prev.x1, prev.y0, ln.x0, prev.y1)))
        small_raised = ln.size < 0.85 * prev.size and ln.y1 < prev.y1 - 0.15 * prev.size
        for s in ln.spans:  # a separately drawn raised small run is a superscript (footnote call)
            spans.append(Span(s.text, s.font, s.size, s.bold, s.italic, s.sup or small_raised, s.bbox))
        out[out.index(prev)] = Line(spans, (min(prev.x0, ln.x0), min(prev.y0, ln.y0), max(prev.x1, ln.x1),
                                            max(prev.y1, ln.y1)), prev.page, False)
    # small fragments drawn inside another line's extent (superscript calls PDFium left a gap for): insert by x
    for frag in [x for x in out if len(x.text.strip()) <= 4]:
        host = next((h for h in out if h is not frag and h.x0 - 1 <= frag.x0 and frag.x1 <= h.x1 + 1
                     and min(h.y1, frag.y1) - max(h.y0, frag.y0) > 0.45 * (frag.y1 - frag.y0)
                     and len(h.text.strip()) > len(frag.text.strip())), None)
        if host is None:
            continue
        raised = frag.size < 0.85 * host.size and frag.y1 < host.y1 - 0.15 * host.size
        add = [Span(s.text, s.font, s.size, s.bold, s.italic, s.sup or raised, s.bbox) for s in frag.spans]
        host.spans = sorted(host.spans + add, key=lambda s: s.bbox[0])
        out.remove(frag)
    out.sort(key=lambda x: (round(x.y0), x.x0))
    return out + [x for x in lines if x.vertical]


def _page(pdf_page, number: int) -> Page:
    W, H = pdf_page.get_size()
    tp = pdf_page.get_textpage()
    n = tp.count_chars()
    rect, ox, oy = R.FS_RECTF(), ctypes.c_double(), ctypes.c_double()
    matrix, buf, flags = R.FS_MATRIX(), ctypes.create_string_buffer(256), ctypes.c_int()
    fonts: dict[int, _Font] = {}
    font = None
    lines, cur = [], []
    raw, invisible = [], 0

    def flush():
        if cur:
            ln = _build_line(cur, number)
            if ln is not None:
                lines.append(ln)
            cur.clear()

    high = 0
    for i in range(n):
        u = R.FPDFText_GetUnicode(tp, i)
        if u in (10, 13):
            flush()
            continue
        if 0xD800 <= u <= 0xDBFF:  # non-BMP characters (math alphanumerics) come as surrogate pairs
            high = u
            continue
        if 0xDC00 <= u <= 0xDFFF:
            u, high = (0x10000 + ((high - 0xD800) << 10) + (u - 0xDC00)) if high else 0xFFFD, 0
        try:
            ch = "-" if u == 2 else chr(u)  # PDFium reports a line-final ASCII hyphen as U+0002
        except ValueError:
            ch = "�"
        obj = R.FPDFText_GetTextObject(tp, i)
        addr = ctypes.cast(obj, ctypes.c_void_p).value if obj else None
        if addr is not None:
            font = fonts.get(addr)
            if font is None:
                font = fonts[addr] = _font(tp, i, obj, matrix, buf, flags)
        elif font is None:
            font = _font(tp, i, None, matrix, buf, flags)
        R.FPDFText_GetLooseCharBox(tp, i, ctypes.byref(rect))
        R.FPDFText_GetCharOrigin(tp, i, ctypes.byref(ox), ctypes.byref(oy))
        x0, x1, y0, y1 = rect.left, rect.right, H - rect.top, H - rect.bottom
        raw.append(ch)
        invisible += font.invisible
        if cur and ch.strip():
            last = next((c for c in reversed(cur) if c[0].strip()), None)
            if last is not None and not font.rotated and not last[6].rotated:
                size = max(font.size, last[6].size, 1)
                horizontal_gap = x0 - last[3]
                same_column = abs(x0 - last[1]) < 0.6 * size and y0 > last[2]  # vertical writing: next glyph below
                if not same_column and (horizontal_gap > 3 * size or x1 < last[1] - size):
                    flush()  # a wide gap on one baseline (column / table cell) or a jump back = new line
        cur.append((ch, x0, y0, x1, y1, H - oy.value, font))
    flush()
    tp.close()
    text = "".join(raw)
    page = Page(number, W, H, _merge_same_baseline(lines), chars=len(text.strip()),
                invisible=invisible / max(1, len(raw)),
                bad_chars=(len(CONTROL.findall(text)) + len(PUA.findall(text)) + text.count("�")) / max(1, len(text)))
    area = 0.0
    for obj in pdf_page.get_objects(filter=[R.FPDF_PAGEOBJ_IMAGE], max_depth=3):
        try:
            left, bottom, right, top = obj.get_bounds()
        except pdfium.PdfiumError:
            continue
        box = (max(left, 0), H - min(top, H), min(right, W), H - max(bottom, 0))  # top-left origin
        a = max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])
        area += a
        if 0.02 * W * H < a < 0.8 * W * H:  # a figure, not a page-sized scan or background
            page.figures.append(box)
    page.image_area = min(1.0, area / max(1.0, W * H))
    return page


def extract(data: bytes) -> tuple[list[Page], dict]:
    try:
        doc = pdfium.PdfDocument(data)
    except pdfium.PdfiumError as e:
        if "password" in str(e).lower():
            raise IngestError("This PDF is password-protected. Please upload an unprotected copy.") from e
        raise IngestError(f"The PDF could not be opened ({e}).") from e
    try:
        pages = []
        for i in range(len(doc)):
            p = doc[i]
            try:
                pages.append(_page(p, i + 1))
            finally:
                p.close()
        meta = doc.get_metadata_dict(skip_empty=True)
        return pages, {"title": meta.get("Title", "").strip(), "author": meta.get("Author", "").strip()}
    finally:
        doc.close()
