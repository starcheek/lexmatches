"""PDF L1 + L2 on visual lines (ported from the PDF lab, geometry from formats.pdf).

  L1  span characters (levels.clean_text) + letter-spaced emphasis (Sperrsatz) + line-final soft hyphens
  L2  running headers / footers / page numbers (repetition + page zone + gap)   ablation: leaks 389 -> 4
      rotated margin text (e.g. arXiv side banner)
      vertical (tategaki) pages rotated into a horizontal reading frame, ruby readings removed
      drop caps merged into their first line
      reading order: column gutters + XY-cut bands                             ablation: CER 0.006 -> 0.001
      footnote regions (bottom, smaller font, marker) + footnote calls          ablation: CER 0.003 -> 0.001
Lines are never deleted: they get a non-body `role`; only body lines become text.
"""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict

from app.ingest.formats.pdf import Line, Page, Span
from app.ingest.ir import Audit
from app.ingest.levels import SOFT_MARK, clean_text

PAGENUM_RES = [
    re.compile(r"^[\W_]{0,4}\d{1,4}[\W_]{0,4}$"),
    re.compile(r"^[\W_]{0,3}[ivxlcdm]{1,7}[\W_]{0,3}$", re.I),
    re.compile(r"^(page|seite|página|pagina|p\.|lpp\.|стр\.|с\.)\s*\d+(\s*(of|/|из|von|de|no)\s*\d+)?\.?$", re.I),
    re.compile(r"^\d+\s*/\s*\d+$"),
]
FN_MARK = re.compile(r"^\s*(\(?\d{1,3}[\).]?|\[\d{1,3}\]|[*†‡§¶]+|[⁰¹²³⁴⁵⁶⁷⁸⁹]{1,3})\s*[^\d\s].{2,}")
SUPERSCRIPT_DIGITS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")
CJK = re.compile(r"[぀-ヿ㐀-鿿豈-﫿　-〿＀-￯]")
SINGLE_LETTER_WORDS = {"ru": set("вкосуияаВКОСУИЯА"), "pt": set("aeoAEO"), "fr": set("àaAyY"), "en": set("aAI"),
                       "lv": set("uUaA")}


def body_font_size(pages: list[Page]) -> float:
    c: Counter = Counter()
    for p in pages:
        for ln in p.lines:
            for s in ln.spans:
                c[round(s.size * 2) / 2] += len(s.text.strip())
    return c.most_common(1)[0][0] if c else 10.0


# ------------------------------------------------------------------------------------------------ L1
def _letterspacing(s: str, lang: str) -> str:
    """'g e s p e r r t' -> 'gesperrt' (>= 4 single letters in a row that are not real one-letter words)."""
    singles = SINGLE_LETTER_WORDS.get(lang, set())

    def fix(m):
        toks = m.group(1).split(" ")
        return m.group(0) if sum(1 for t in toks if t in singles) > 1 else "".join(toks)
    return re.sub(r"(?<![\w])((?:\w ){3,}\w)(?![\w])(?: (?=[,.;:!?]))?", fix, s)


def normalize_chars(pages: list[Page], lang: str, audit: Audit) -> None:
    # Automatic hyphenation shows up as U+00AD or U+2010 at line ends (PDFium reports U+2010 where PyMuPDF gave
    # U+00AD). When a document never uses U+2010 inside a line, a line-final U+2010 is a typesetter hyphen.
    texts = [ln.text.rstrip() for pg in pages for ln in pg.lines]
    auto_2010 = not any("‐" in t[:-1] for t in texts) and any(t.endswith("‐") for t in texts)
    for pg in pages:
        for ln in pg.lines:
            last = next((s for s in reversed(ln.spans) if s.text.strip()), None)
            if last is not None and (last.text.rstrip().endswith("­") or
                                     (auto_2010 and last.text.rstrip().endswith("‐"))):
                last.text = last.text.rstrip()[:-1] + SOFT_MARK  # joined without hyphen in L3
                audit.add("L1", "line_final_soft_hyphen")
            for s in ln.spans:
                s.text = clean_text(s.text, lang, audit)
                if lang not in ("ja", "zh"):
                    t = _letterspacing(s.text, lang)
                    if t != s.text:
                        audit.add("L1", "letterspacing", example=s.text)
                        s.text = t
        pg.lines = [ln for ln in pg.lines if ln.text.strip()]


# ------------------------------------------------------------------------------------------------ L2
def _hf_key(t: str) -> str:
    return re.sub(r"[\s\W_]+", " ", re.sub(r"\d+", "#", t.strip().lower())).strip()


def remove_headers_footers(pages: list[Page], body: float, audit: Audit, zone: float = 0.12) -> None:
    cands = []
    for pg in pages:
        ls = sorted((ln for ln in pg.lines if ln.role == "body"), key=lambda ln: ln.y0)
        if len(ls) < 2:
            continue
        H = pg.height
        top = [ln for ln in ls if ln.y1 <= H * zone + 0.5 * body or (ln is ls[0] and ln.y1 <= H * 0.16)][:8]
        bot = [ln for ln in ls if ln.y0 >= H * (1 - zone) - 0.5 * body][-8:]
        for ln in top:
            below = [x.y0 for x in ls if x.y0 > ln.y1 - 1 and x not in top]
            cands.append((pg, ln, "top", (min(below) - ln.y1) if below else 99))
        for ln in bot:
            above = [x.y1 for x in ls if x.y1 < ln.y0 + 1 and x not in bot]
            cands.append((pg, ln, "bottom", (ln.y0 - max(above)) if above else 99))
    keys: Counter = Counter()
    seen = set()
    for pg, ln, where, _ in cands:
        k = (where, _hf_key(ln.text))
        if (pg.number, k) not in seen:
            seen.add((pg.number, k))
            keys[k] += 1
    min_rep = 2 if len(pages) <= 8 else 3
    for pg, ln, where, gap in cands:
        if ln.role != "body":
            continue
        t = ln.text.strip()
        k = (where, _hf_key(t))
        is_num = any(r.match(t) for r in PAGENUM_RES) and len(t) <= 22
        separated = gap >= 0.9 * body or ln.size < 0.92 * body
        if is_num and (separated or keys[k] >= min_rep):
            ln.role = "pagenum"
        elif keys[k] >= min_rep and ln.size <= 1.08 * body and separated and len(t) < 160:
            ln.role = "header" if where == "top" else "footer"
        else:
            continue
        audit.add("L2", f"remove_{ln.role}", example=t)


def remove_margin_text(pg: Page, audit: Audit) -> None:
    if pg.vertical:
        return
    for ln in pg.lines:
        if ln.role == "body" and ln.vertical:
            ln.role = "margin"
            audit.add("L2", "remove_rotated_margin_text", example=ln.text.strip())


CAPTION_RE = re.compile(r"^\s*(figure|fig\.|table|tableau|abbildung|abb\.|tabelle|рис\.|рисунок|таблица|attēls|"
                        r"tabula|figura|tabela|図|表)\s*\d+(\.\d+)?\s*[.:|]", re.I)


def remove_figure_text(pg: Page, body: float, audit: Audit) -> None:
    """Labels drawn over figure images are not running text (boxes densely covered by text are left alone).
    Vector-drawn figures are not detected: clustering vector paths swallowed body text on the real PDFs."""
    for box in pg.figures:
        area = max(1.0, (box[2] - box[0]) * (box[3] - box[1]))
        inside = [ln for ln in pg.lines if ln.role == "body" and box[0] <= (ln.x0 + ln.x1) / 2 <= box[2]
                  and box[1] <= (ln.y0 + ln.y1) / 2 <= box[3]]
        if not inside or sum((ln.x1 - ln.x0) * (ln.y1 - ln.y0) for ln in inside) / area > 0.3:
            continue
        for ln in inside:
            if ln.size <= 1.05 * body and not CAPTION_RE.match(ln.text):
                ln.role = "figure_text"
                audit.add("L2", "remove_text_inside_figure", example=ln.text.strip())


def rotate_to_reading_frame(pg: Page) -> None:
    """Vertical-rl page: columns right -> left, glyphs top -> bottom. Map (x, y) -> (y, W - x) so every later
    step (paragraphs, indents, short-line detection) works as for horizontal text."""
    W = pg.width
    for ln in pg.lines:
        x0, y0, x1, y1 = ln.bbox
        ln.bbox = (y0, W - x1, y1, W - x0)


def remove_ruby(pg: Page, body: float, audit: Audit) -> None:
    for ln in pg.lines:
        if ln.role == "body" and ln.size <= 0.7 * body and CJK.search(ln.text) and len(ln.text.strip()) <= 12:
            ln.role = "ruby"
            audit.add("L2", "remove_ruby")


def merge_drop_caps(pg: Page, body: float, audit: Audit) -> None:
    for dc in [ln for ln in pg.lines if ln.role == "body"]:
        t = dc.text.strip()
        if not (1 <= len(t) <= 3 and any(c.isalpha() for c in t) and dc.size >= 1.8 * body):
            continue
        cands = [ln for ln in pg.lines if ln is not dc and ln.role == "body" and ln.x0 >= dc.x0 - 2
                 and ln.x0 - dc.x1 < 4 * body and ln.x1 > dc.x1 and dc.y0 - 0.8 * body <= ln.y0 <= dc.y1
                 and ln.size < 1.5 * body]
        if not cands:
            continue
        tgt = min(cands, key=lambda ln: ln.y0)
        first = tgt.spans[0]
        tgt.spans.insert(0, Span(t, first.font, first.size, first.bold, first.italic, False, dc.bbox))
        tgt.notes.append("dropcap")
        for ln in cands:  # lines wrapped around the initial are not indented
            ln.bbox = (min(ln.x0, dc.x0), ln.y0, ln.x1, ln.y1)
            if ln is not tgt:
                ln.notes.append("dropcap_adjacent")
        dc.role = "dropcap"
        audit.add("L2", "merge_drop_cap", example=t + tgt.text[:40])


def _find_gutter(lines: list[Line], x0: float, x1: float):
    W = x1 - x0
    if W <= 0:
        return None
    narrow = [ln for ln in lines if (ln.x1 - ln.x0) < 0.55 * W]
    if len(narrow) < 6:
        return None
    cov = [0] * (int(W) + 2)
    for ln in narrow:
        for i in range(max(0, int(ln.x0 - x0)), max(0, int(math.ceil(ln.x1 - x0)))):
            if i < len(cov):
                cov[i] += 1
    lo, hi = int(0.2 * W), int(0.8 * W)
    tol = max(2, int(0.05 * len(narrow)))  # a few stray lines may cross the gutter (they become spanning)
    best, run_start = None, None
    for i in range(lo, hi + 1):
        if cov[i] <= tol:
            if run_start is None:
                run_start = i
        elif run_start is not None:
            if best is None or (i - run_start) > (best[1] - best[0]):
                best = (run_start, i)
            run_start = None
    if run_start is not None and (best is None or (hi + 1 - run_start) > (best[1] - best[0])):
        best = (run_start, hi + 1)
    if not best or (best[1] - best[0]) < max(5, 0.015 * W):
        return None
    g0, g1 = best[0] + x0, best[1] + x0
    left = [ln for ln in narrow if ln.x1 <= g0 + 1]
    right = [ln for ln in narrow if ln.x0 >= g1 - 1]
    if len(left) < 3 or len(right) < 3:
        return None
    lw, rw = sum(ln.x1 - ln.x0 for ln in left), sum(ln.x1 - ln.x0 for ln in right)
    if min(lw, rw) < 0.15 * max(lw, rw):  # both sides must carry text mass (not a ragged verse block)
        return None
    return g0, g1


def _split_y(lines: list[Line]) -> list[list[Line]]:
    """Horizontal slabs at full-width whitespace gaps (XY-cut, horizontal step)."""
    ls = sorted(lines, key=lambda ln: ln.y0)
    hs = sorted(ln.y1 - ln.y0 for ln in ls)
    thr = max(4.0, 0.6 * hs[len(hs) // 2])
    slabs, cur, bottom = [], [ls[0]], ls[0].y1
    for ln in ls[1:]:
        if ln.y0 - bottom > thr:
            slabs.append(cur)
            cur = []
        cur.append(ln)
        bottom = max(bottom, ln.y1)
    slabs.append(cur)
    return slabs


def _by_y(lines):
    return sorted(lines, key=lambda ln: (round(ln.y0, 0), ln.x0))


def _order(lines: list[Line], depth: int = 0) -> list[list[Line]]:
    if not lines:
        return []
    x0, x1 = min(ln.x0 for ln in lines), max(ln.x1 for ln in lines)
    g = _find_gutter(lines, x0, x1) if depth < 3 else None
    if not g and depth < 3 and len(lines) >= 8:
        slabs = _split_y(lines)
        if len(slabs) > 1:
            regions = []  # [lines, gutter]
            for s in slabs:
                gs = _find_gutter(s, min(ln.x0 for ln in s), max(ln.x1 for ln in s)) if len(s) >= 6 else None
                prev_g = regions[-1][1] if regions else None
                fits = prev_g and all(ln.x1 <= prev_g[0] + 1 or ln.x0 >= prev_g[1] - 1 for ln in s)
                if prev_g and (gs and abs(gs[0] - prev_g[0]) < 10 or not gs and fits):
                    regions[-1][0] += s
                elif regions and not prev_g and not gs:
                    regions[-1][0] += s
                else:
                    regions.append([list(s), gs])
            if len(regions) > 1 or regions[0][1]:
                out = []
                for rl, rg in regions:
                    out += _order(rl, depth + 1) if rg else [_by_y(rl)]
                return out
    if not g:
        return [_by_y(lines)]
    g0, g1 = g
    span_ids = {id(ln) for ln in lines if ln.x0 < g0 - 1 and ln.x1 > g1 + 1}
    spanning = sorted([ln for ln in lines if id(ln) in span_ids], key=lambda ln: ln.y0)
    bands = defaultdict(list)
    for ln in lines:
        if id(ln) not in span_ids:
            bands[sum(1 for s in spanning if s.y0 <= ln.y0)].append(ln)
    segments = []
    for k in range(len(spanning) + 1):
        if k > 0:
            segments.append([spanning[k - 1]])
        band = bands.get(k, [])
        mid = (g0 + g1) / 2
        segments += _order([ln for ln in band if (ln.x0 + ln.x1) / 2 < mid], depth + 1)
        segments += _order([ln for ln in band if (ln.x0 + ln.x1) / 2 >= mid], depth + 1)
    merged = []  # consecutive single spanning lines form one segment
    for s in segments:
        if merged and len(s) == 1 and id(s[0]) in span_ids and all(id(ln) in span_ids for ln in merged[-1]):
            merged[-1].append(s[0])
        else:
            merged.append(s)
    return merged


def reading_order(pg: Page, audit: Audit) -> None:
    segs = _order([ln for ln in pg.lines if ln.role == "body"])
    if len(segs) > 1 and sum(1 for s in segs if len(s) > 2) > 1:
        pg.columns = 2
        audit.add("L2", "multi_column_page")
    ordered = []
    for ci, s in enumerate(segs):
        for j, ln in enumerate(s):
            ln.col, ln.flow_break = ci, j == 0
            ordered.append(ln)
    pg.lines = ordered + [ln for ln in pg.lines if ln.role != "body"]


def detect_footnotes(pg: Page, body: float, audit: Audit, ratio: float = 0.9) -> None:
    segs = defaultdict(list)
    for ln in pg.lines:
        if ln.role == "body":
            segs[ln.col].append(ln)
    for ls in segs.values():
        ls = sorted(ls, key=lambda ln: ln.y0)
        if len(ls) < 2:
            continue
        region = []
        for ln in reversed(ls):
            if ln.size > ratio * body:
                break
            region.append(ln)
        region.reverse()
        if not region or len(region) == len(ls):
            continue
        start = next((i for i, ln in enumerate(region)
                      if FN_MARK.match(ln.text) or (ln.spans and ln.spans[0].sup)), None)
        if start is None:
            continue
        above_i = len(ls) - len(region) + start - 1
        if above_i >= 0 and region[start].y0 - ls[above_i].y1 < 0.2 * body:
            continue
        for ln in region[start:]:
            ln.role = "footnote"
            if FN_MARK.match(ln.text) or (ln.spans and ln.spans[0].sup):
                ln.notes.append("fn_start")
        audit.add("L2", "footnote_lines", len(region) - start, example=region[start].text.strip())
    for ln in pg.lines:  # footnote calls in body lines: raised small digits / symbols
        if ln.role != "body":
            continue
        keep = []
        for i, s in enumerate(ln.spans):
            st = s.text.strip()
            sup_digits = re.fullmatch(r"[⁰¹²³⁴⁵⁶⁷⁸⁹]{1,3}", st or "")
            if i > 0 and st and ((s.sup and re.fullmatch(r"\d{1,3}|[*†‡]+", st)) or sup_digits):
                ln.notes.append("fnref:" + st.translate(SUPERSCRIPT_DIGITS))
                audit.add("L2", "footnote_call_removed")
                if s.text.endswith(" "):
                    keep.append(Span(" ", s.font, s.size, s.bold, s.italic, False, s.bbox))
                continue
            keep.append(s)
        ln.spans = keep


def run(pages: list[Page], lang: str, audit: Audit) -> dict:
    normalize_chars(pages, lang, audit)
    for pg in pages:
        lines = pg.lines
        pg.vertical = len(lines) > 5 and sum(ln.vertical for ln in lines) > 0.5 * len(lines)
    body = body_font_size(pages)
    remove_headers_footers(pages, body, audit)
    for pg in pages:
        remove_margin_text(pg, audit)
        remove_figure_text(pg, body, audit)
        if pg.vertical:
            rotate_to_reading_frame(pg)
    vertical_doc = sum(p.vertical for p in pages) > 0.5 * len(pages)
    for pg in pages:
        if lang in ("ja", "zh") or pg.vertical:
            remove_ruby(pg, body, audit)
        merge_drop_caps(pg, body, audit)
        reading_order(pg, audit)
        detect_footnotes(pg, body, audit)
    return {"body_size": body, "vertical": vertical_doc,
            "multi_column_pages": [p.number for p in pages if p.columns > 1]}
