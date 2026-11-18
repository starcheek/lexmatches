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
    # Only what is usually followed by a capital or a digit: an abbreviation followed by lowercase never matters, and
    # ones that often end a sentence (pl/cs "r." year, "w."/"st." century, uk "р.", "тис.", Greek "π.Χ.") are left out.
    "es": "sr sra srta sres sras srs dr dra lic ing arq prof profa gral ud uds vd vds dña sto sta pág págs p pp s núm "
          "art cap vol fig ej av avda aprox tel dpto",
    "it": "sig sigg sig.ra sig.na dott dott.ssa prof prof.ssa ing avv arch geom rag on sen mons gen dr p pag pagg pp n "
          "nr num art cap vol fig es cfr ca v vs sec tel",
    "ca": "sr sra srta dr dra prof pàg p pp núm art cap vol fig ex av pl c aprox tel",
    "nl": "dhr mevr mw mej dr prof ir ing drs mr jhr st bijv bv vgl zgn resp ca blz pag nr afb hfd hfdst tel",
    "pl": "dr prof mgr inż doc hab np m.in tzn tj tzw ok ul al pl nr str s tel im św ks pt ds p por zob godz "
          "ang łac niem",
    "uk": "проф акад доц напр див пор вул просп пл ім м с",
    "cs": "dr prof mgr ing doc phdr mudr judr rndr bc csc tj tzn např resp tzv mj str s č sv ul nám p pí sl odst",
    "sv": "dr prof doc fil t.ex dvs bl.a s.k ca resp kl nr s sid jfr fr.o.m t.o.m d.v.s p.g.a enl ang kap tel obs",
    "no": "dr prof bl.a dvs d.v.s f.eks mht pga ca kl nr s jf evt hhv iht ifm vedr ang kap tel",
    "da": "hr frk dr prof bl.a dvs d.v.s f.eks mht pga ca kl nr s jf evt hhv iht ang vedr inkl ekskl kap afsn tel",
    "fi": "tri prof dos esim ns mm ks vrt n klo nro s v huom puh",
    "ro": "dl dna dra dr prof conf lect ing gen str bd nr pag p ex art cap vol sec aprox tel",
    "hu": "dr id ifj özv pl ill kb vö ún ld ti u krt tel jan febr márc ápr máj jún júl aug szept okt nov dec",
    "tr": "dr prof doç yrd av op alb sn bkz örn s sf no çev haz cad sok mah",
    "el": "κ δρ καθ δηλ βλ σελ αρ οδ τηλ αγ",
}
FINAL_OK = {  # abbreviations that may also end a sentence; a dotted one ("o.s.v") is matched as a whole
    "en": "etc", "fr": "etc", "pt": "etc", "es": "etc", "it": "ecc etc", "ca": "etc",
    "ro": "etc ș.a ş.a ș.a.m.d ş.a.m.d", "de": "usw", "lv": "utt c", "ru": "п д", "uk": "т.д т.п ін",
    "nl": "enz e.d e.a", "pl": "itd itp cdn", "cs": "atd apod aj", "sv": "osv o.s.v m.m m.fl etc",
    "no": "osv o.l m.m mv etc", "da": "osv o.l m.m mv etc", "fi": "jne yms tms ym tjsp", "hu": "stb",
    "tr": "vs vb vd", "el": "κλπ κ.λπ κ.λ.π κ.ά",
}
ORDINAL_DOT = {"de", "lv", "cs", "pl", "da", "no", "fi", "hu", "tr"}  # 1. Januar, 28. října, II. Rákóczi
REVERSED_GUILL = {"de", "da", "cs", "hu"}  # »quote« rather than «quote»
_ABBR = {k: set(v.split()) for k, v in ABBR.items()}
_FINAL = {k: set(FINAL_OK.get(k, "").split()) for k in ABBR}
CLOSE_Q = "»«”“‘\"'’›‹)」』）"  # « closes German »quotes«, “ closes Czech/German „quotes“
UPPER_START = re.compile(r"[\"'«»„“‘‚‹›(\[—–―\-]*\s*[A-ZÀ-ÖØ-ÞĀ-ŽȘȚΆΈ-ΏΑ-ΫЀ-ЯҐ0-9¿¡]")
_BOUNDARY = re.compile(r"([.!?…]+)([" + re.escape(CLOSE_Q) + r"]*)(\s+)")
_BOUNDARY_EL = re.compile(r"([.!?…;\u037e]+)([" + re.escape(CLOSE_Q) + r"]*)(\s+)")  # Greek ? is ;
_INITIALS = re.compile(r"(?:[^\W\d_]\.)+[^\W\d_]")  # U.S, i.e, т.е, π.χ
_KANA = re.compile(r"[぀-ヿ]")
MAX_SENTENCE = 600


def _lexseg(text: str, lang: str) -> list[tuple[int, int]]:
    key = lang if lang in _ABBR else "en"
    abbr, final = _ABBR[key], _FINAL[key]
    bounds: list[int] = []
    for m in (_BOUNDARY_EL if lang == "el" else _BOUNDARY).finditer(text):
        nxt = text[m.end():m.end() + 40]
        if not nxt or not UPPER_START.match(nxt):
            continue
        word_m = re.search(r"([\w.\-]+)$", text[:m.start()])
        w = word_m.group(1).lower() if word_m else ""
        punct = m.group(1)
        seg_start = bounds[-1] if bounds else 0
        opened = text.count("«", seg_start, m.start()) - text.count("»", seg_start, m.start())
        if lang not in REVERSED_GUILL and opened > 0 and not m.group(2) and "»" in nxt:
            continue  # inside a short quotation: «Как? Как?» — ...
        if punct == "." and not m.group(2):
            last = w.split(".")[-1] if w else ""
            if len(w) == 1 and w.isalpha() and word_m.group(1).isupper():
                continue  # initial: A. P. Chekhov
            if w not in final:
                if _INITIALS.fullmatch(w):
                    continue  # U.S, i.e, т.е
                if (w in abbr or last in abbr) and last not in final:
                    continue
                if lang in ORDINAL_DOT and word_m and re.fullmatch(r"\d{1,2}|[IVXLC]+", word_m.group(1)):
                    continue  # ordinal: 1. Januar, 18. novembrī, IV. Béla
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
