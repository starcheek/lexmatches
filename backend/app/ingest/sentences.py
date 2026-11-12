"""L6 sentence segmentation (rule-based, per-language abbreviations; no dependency).

Chosen over the PDF lab's segmenter and the old translation regex on both labs' hand-segmented sets (held-out
exact match: this one 27/29 on the PDF lab's set, the PDF lab's 21/28 on this one, the regex 37/57 overall).
Offsets index the block text, which is never changed. Verse and tables: one span per line. Headings: one span.
Sentences longer than MAX_SENTENCE are cut at the clause boundary nearest the middle (translation chunking).
"""
import re

ABBR = {
    "fr": "m mm mme mmes mlle mlles dr pr st ste me mgr cf p pp t chap vol éd etc env av apr j.-c ex fig art n° no h min",
    "en": "mr mrs ms dr prof st jr sr vs etc fig no vol pp p ch jan feb mar apr jun jul aug sep sept oct nov dec mt rev "
          "gen col capt lt sgt inc ltd co e.g i.e a.m p.m cf al",
    "de": "dr prof hr fr nr bzw ca usw vgl z b d h u a s o sog ggf evtl inkl jh jahrhundert st str hauptstr tel okt nov "
          "dez jan feb mär apr aug sept bd hg abb",
    "ru": "г гг в вв т е д п см ср стр им ул др проф акад тыс млн млрд руб коп т.е т.д т.п напр гл",
    "pt": "sr sra srs sras dr dra prof profa p ex pág pp etc av cap séc nº n vol fig",
    "lv": "apm tūkst milj nr sk skat u c utt piem prof dr g gs lpp att plkst t i proti",
}
FINAL_OK = {"etc", "usw", "utt", "п", "д", "c"}  # abbreviations that may also end a sentence
CLOSE_Q = "»«”\"'’›‹)」』）"  # « closes German »quotes«
UPPER_START = re.compile(r"[\"'«»„“‘‹›(\[—–―\-]*\s*[A-ZÀ-ÖØ-ÞĀ-ŽА-ЯЁ0-9¿¡]")
_BOUNDARY = re.compile(r"([.!?…]+|\.\.\.)([" + re.escape(CLOSE_Q) + r"]*)(\s+)")
_KANA = re.compile(r"[぀-ヿ]")
MAX_SENTENCE = 600


def _lexseg(text: str, lang: str) -> list[tuple[int, int]]:
    abbr = set(ABBR.get(lang, ABBR["en"]).split())
    bounds: list[int] = []
    for m in _BOUNDARY.finditer(text):
        nxt = text[m.end():m.end() + 40]
        if not nxt or not UPPER_START.match(nxt):
            continue
        word_m = re.search(r"([\w.\-]+)$", text[:m.start()])
        w = word_m.group(1).lower() if word_m else ""
        punct = m.group(1)
        seg_start = bounds[-1] if bounds else 0
        opened = text.count("«", seg_start, m.start()) - text.count("»", seg_start, m.start())
        if lang != "de" and opened > 0 and not m.group(2) and "»" in nxt:
            continue  # inside a short quotation: «Как? Как?» — ...
        if punct == "." and not m.group(2):
            last = w.split(".")[-1] if w else ""
            if len(w) == 1 and w.isalpha() and word_m.group(1).isupper():
                continue  # initial: A. P. Chekhov
            if re.fullmatch(r"([a-zа-я]\.)+[a-zа-я]", w, re.I):
                continue  # U.S, i.e, т.е
            if (w in abbr or last in abbr) and w not in FINAL_OK and last not in FINAL_OK:
                continue
            if lang in ("de", "lv") and re.fullmatch(r"\d{1,2}|[ivxlc]+", w, re.I):
                continue  # ordinal: 1. Januar, 18. novembrī
        bounds.append(m.end(2))
    return _spans(text, bounds)


def _ja(text: str) -> list[tuple[int, int]]:
    bounds, start = [], 0
    for m in re.finditer(r"[。！？!?]+[」』）)]*", text):
        if text.count("「", start, m.end()) > text.count("」", start, m.end()):
            continue  # inside a quotation
        if text[m.end() - 1] in "」』" and re.match(r"[とって]", text[m.end():m.end() + 1]):
            continue  # 「…。」と言った
        bounds.append(m.end())
        start = m.end()
    return _spans(text, bounds)


def _spans(text: str, bounds: list[int]) -> list[tuple[int, int]]:
    out, start = [], 0
    for b in bounds + [len(text)]:
        seg = text[start:b]
        if seg.strip():
            s = start + len(seg) - len(seg.lstrip())
            out.append((s, start + len(seg.rstrip())))
        start = b
    return out


def _split_long(text: str, a: int, b: int) -> list[tuple[int, int]]:
    if b - a <= MAX_SENTENCE:
        return [(a, b)]
    mid = (a + b) // 2
    for sep in ("; ", ": ", ", ", "、", " "):
        cuts = [a + m.end() for m in re.finditer(re.escape(sep), text[a:b]) if a + m.end() < b]
        if cuts:
            cut = min(cuts, key=lambda c: abs(c - mid))
            left = (a, cut - (len(sep) - len(sep.rstrip())))
            return _split_long(text, *left) + _split_long(text, cut, b)
    return [(a, b)]


def segment(text: str, lang: str | None) -> list[tuple[int, int]]:
    if not text.strip():
        return []
    spans = _ja(text) if lang in ("ja", "zh") or _KANA.search(text[:200]) else _lexseg(text, lang or "en")
    return [s for a, b in spans for s in _split_long(text, a, b)]


def segment_block(text: str, btype: str, lang: str | None) -> list[list[int]]:
    if btype == "separator" or not text.strip():
        return []
    if btype in ("verse", "table"):
        out, pos = [], 0
        for line in text.split("\n"):
            if line.strip():
                s = pos + len(line) - len(line.lstrip())
                out.append([s, pos + len(line.rstrip())])
            pos += len(line) + 1
        return out
    if btype == "heading":
        s = len(text) - len(text.lstrip())
        return [[s, len(text.rstrip())]]
    return [list(x) for x in segment(text, lang)]
