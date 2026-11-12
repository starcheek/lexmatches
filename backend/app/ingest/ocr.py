"""PDF L4 quality gate (which pages have no usable text layer) and the OCR hook.

`ocr_pages` is the single entry point for the OCR follow-up: it receives the original PDF bytes, the 1-based page
numbers the gate rejected and the document language, and returns {page_number: [Block, ...]} with
`source_page` set. The pipeline splices those blocks in place of the rejected pages' blocks (by `source_page`)
before sentence segmentation and reading units, so OCR output flows through the same L6/units/translation path.
Until an OCR engine exists it raises OcrUnavailable and the book gets the warning "scanned pages not supported yet".
"""
from __future__ import annotations

import re
from collections import Counter

from app.ingest.ir import Block

SCRIPT = {"ru": "cyr", "uk": "cyr", "ja": "cjk", "zh": "cjk", "ko": "cjk"}
VOWELS = {"lat": set("aeiouyàâäéèêëîïôöùûüÿæœáíóúãõāēīūåøąęė"), "cyr": set("аеёиоуыэюяіїє")}


class OcrUnavailable(Exception):
    pass


def ocr_pages(pdf_bytes: bytes, page_numbers: list[int], language: str) -> dict[int, list[Block]]:
    """OCR the given pages. Contract: return {page: blocks} (blocks with source_page=page, any IR type, no
    sentences - the pipeline segments them). Raise OcrUnavailable when no engine is configured."""
    raise OcrUnavailable("OCR is not available yet")


def _script(c: str) -> str:
    o = ord(c)
    if 0x0400 <= o <= 0x04FF:
        return "cyr"
    if 0x3040 <= o <= 0x30FF or 0x3400 <= o <= 0x9FFF or 0xF900 <= o <= 0xFAFF or 0xAC00 <= o <= 0xD7AF:
        return "cjk"
    if c.isalpha() and o < 0x0250 or 0x1E00 <= o <= 0x1EFF:
        return "lat"
    return "other"


def text_garbage(text: str, lang: str) -> float:
    """0..1, high = the text layer is unusable (broken ToUnicode maps, wrong script, no vowels, symbol soup)."""
    t = text.strip()
    if not t:
        return 1.0
    letters = [c for c in t if c.isalpha()]
    nl = max(1, len(letters))
    exp = SCRIPT.get(lang, "lat")
    scr = Counter(_script(c) for c in letters)
    script_frac = (scr.get(exp, 0) + (scr.get("lat", 0) if exp != "lat" else 0)) / nl
    letter_ratio = len(letters) / max(1, sum(1 for c in t if not c.isspace()))
    bad = sum(1 for c in t if c == "�" or 0xE000 <= ord(c) <= 0xF8FF or (ord(c) < 32 and c not in "\n\t")) / len(t)
    score = 0.0
    if exp in VOWELS and len(letters) > 50:
        v = sum(1 for c in letters if c.lower() in VOWELS[exp]) / nl
        if v < 0.22 or v > 0.68:
            score += 0.4
    toks = re.findall(r"\S+", t)
    if toks and exp != "cjk":
        weird = sum(1 for w in toks if re.search(r"[a-zа-я][A-ZА-Я]", w)
                    or re.search(r"[^\w\s.,;:!?'’\"“”«»()\-—–…%/]{2,}", w)) / len(toks)
        score += min(0.5, weird * 2)
    score += min(1.0, bad * 10)
    if script_frac < 0.6 and len(letters) > 30:
        score += 0.5
    if letter_ratio < 0.5 and len(t) > 100:
        score += 0.4
    return min(1.0, score)


def gate(pages, lang: str) -> list[int]:
    """Pages to route to OCR: garbage text layer, or (almost) no text on a page that is mostly image."""
    out = []
    for p in pages:
        text = "\n".join(ln.text for ln in p.lines if ln.role in ("body", "footnote", "header", "footer", "pagenum"))
        if not text.strip() and p.image_area < 0.3:
            continue  # blank page
        g = min(1.0, text_garbage(text, lang) + min(1.0, p.bad_chars * 10))
        if g >= 0.5 or (p.chars < 30 and p.image_area > 0.3):
            out.append(p.number)
    return out
