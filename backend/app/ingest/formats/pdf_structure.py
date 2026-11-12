"""PDF L3: body lines -> blocks (ported from the PDF lab).

  paragraphs   vertical gap, first-line indent, short previous line (justified), font change, bullets,
               ideographic indent; continuation across column and page breaks   ablation: para-F1 0.13 -> 0.96
  dehyphenation  document vocabulary + per-language keep lists                   ablation: WER 0.029 -> 0.001
  verse        runs of short flush-left lines that end although the next word would have fitted
  headings     size rank, bold/centred/upper-case short lines, chapter patterns; captions, list items, quotes
  footnotes    placed right after the block that cites them
"""
from __future__ import annotations

import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from app.ingest.formats.pdf import Line, Page
from app.ingest.ir import Audit, Block

TERMINAL = re.compile(r"[.!?…:;»\"”’)\]。！？」』]\s*$")
SENT_END = re.compile(r"[.!?…»\"”。！？」』]\s*$")
BULLET = re.compile(r"^\s*([•◦▪▫●○■□►▸‣⁃∙·]|\(?\d{1,2}[.)]|\(?[a-z][.)]|\([ivx]{1,4}\))\s+\S")
BULLET_SYM = re.compile(r"^\s*[•◦▪▫●○■□►▸‣⁃∙·]\s*")
CAPTION = re.compile(r"^\s*(figure|fig\.|table|tableau|abbildung|abb\.|tabelle|рис\.|рисунок|таблица|attēls|tabula|"
                     r"figura|tabela|quadro|図|表)\s*\d+(\.\d+)?\s*[.:|]", re.I)
CHAPTER = re.compile(r"^\s*((chapter|chapitre|kapitel|глава|capítulo|capitulo|nodaļa|part|partie|livre|book|canto|"
                     r"teil|buch|часть|daļa|dziedājums)\b.{0,60}|[IVXLC]{1,6}\.?|\d{1,3}\.?|"
                     r"第[一二三四五六七八九十百〇\d]+[章節回部])\s*$", re.I)
KEEP_HYPHEN_SUFFIX = {
    "fr": {"il", "ils", "elle", "elles", "on", "je", "tu", "nous", "vous", "moi", "toi", "lui", "leur", "leurs", "y",
           "en", "là", "ci", "même", "mêmes", "t", "le", "la", "les", "ce"},
    "pt": {"se", "lhe", "lhes", "o", "a", "os", "as", "me", "te", "nos", "vos", "lo", "la", "los", "las", "no", "na",
           "nas", "mos", "ei", "ás", "á", "emos", "ia", "iam"},
    "ru": {"то", "либо", "нибудь", "ка", "таки", "де", "с"},
}
KEEP_HYPHEN_PREFIX = {
    "fr": {"quatre", "vingt", "dix", "peut", "c'est", "vis", "au", "après", "avant", "arrière", "grand", "grands",
           "grande", "sous", "contre", "porte", "chef", "demi", "mi", "semi", "ex", "non", "anti", "sur", "beau",
           "belle", "petit", "petite"},
    "en": {"self", "ex", "non", "well", "half", "all", "great", "co", "re", "pre", "anti", "semi", "mid", "quasi",
           "cross", "post", "vice"},
    "ru": {"по", "кое", "во", "из", "северо", "юго", "темно", "светло", "ярко", "бледно"},
    "pt": {"guarda", "porta", "beija", "bem", "mal", "ex", "vice", "pré", "pós", "pró", "recém", "além", "aquém",
           "sem", "sota", "soto"},
}
WORD_END = re.compile(r"([\w'’]+)[-‐]⁣?$")
WORD_START = re.compile(r"^([\w'’]+)")
HYPHEN_END = re.compile(r"\w[-‐]⁣?$")
CJK = re.compile(r"[぀-ヿ㐀-鿿豈-﫿＀-￯]")
FN_MARKER = re.compile(r"^\s*(\(?\s?\d{1,3}\s?[\).]?|\[\d{1,3}\]|[*†‡§¶]+|[⁰¹²³⁴⁵⁶⁷⁸⁹]{1,3})\s*")
SUPERSCRIPT_DIGITS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")


@dataclass(eq=False)
class _Para:
    kind: str
    lines: list[Line] = field(default_factory=list)
    type: str = "paragraph"
    level: int | None = None
    text: str = ""


def build_vocab(pages: list[Page]) -> Counter:
    v: Counter = Counter()
    for p in pages:
        for ln in p.lines:
            if ln.role == "body":
                toks = ln.text.split()
                for t in toks[:-1] if toks and toks[-1].endswith(("-", "‐")) else toks:
                    t = t.strip(".,;:!?«»\"“”„()[]—–'’…").lower()
                    if t:
                        v[t] += 1
    return v


def dehyphenate(prev: str, nxt: str, lang: str, vocab: Counter) -> tuple[str, str]:
    """Join `prev` (ending in a hyphen) with `nxt`; returns (text, decision)."""
    prev = prev.rstrip()
    nxt = nxt.lstrip()
    if prev.endswith("‐⁣"):
        return prev[:-2] + nxt, "soft"
    m1, m2 = WORD_END.search(prev), WORD_START.match(nxt)
    if not (m1 and m2):
        return prev + nxt, "keep_nonword"
    a, b = m1.group(1), m2.group(1)
    if any(ch.isdigit() for ch in a + b):
        return prev + nxt, "keep_digit"
    joined, hyph = (a + b).lower(), (a + "-" + b).lower()
    cj, ch = vocab.get(joined, 0), vocab.get(hyph, 0)
    if cj > ch:
        return prev[:-1] + nxt, "join_vocab"
    if ch > cj:
        return prev + nxt, "keep_vocab"
    if b[:1].isupper():
        return prev + nxt, "keep_upper"
    if b.lower() in KEEP_HYPHEN_SUFFIX.get(lang, ()) or a.lower() in KEEP_HYPHEN_PREFIX.get(lang, ()):
        return prev + nxt, "keep_lang_rule"
    return prev[:-1] + nxt, "join_default"


def _seg_stats(lines: list[Line]):
    xs = Counter(round(ln.x0) for ln in lines)
    cands = [x for x, c in xs.items() if c >= max(2, 0.2 * len(lines))]
    left = min(cands) if cands else (xs.most_common(1)[0][0] if xs else 0)
    right = sorted(ln.x1 for ln in lines)[int(0.9 * (len(lines) - 1))] if lines else 0
    full = sum(1 for ln in lines if ln.x1 >= right - 0.02 * max(1, right - left))
    return left, right, len(lines) >= 4 and full / len(lines) > 0.45


def _centered(ln: Line, left: float, right: float) -> bool:
    w = max(1.0, right - left)
    return abs((ln.x0 + ln.x1) / 2 - (left + right) / 2) < 0.05 * w and (ln.x1 - ln.x0) < 0.9 * w \
        and (ln.x0 - left) > 0.04 * w


def _hard_break(a: Line, b: Line, right: float) -> bool:
    """`a` ended although the first word of `b` would still have fitted (= not a wrap)."""
    t = a.text.strip()
    cw = (a.x1 - a.x0) / max(1, len(t))
    w = b.text.split()
    return a.x1 + ((len(w[0]) if w else 1) + 1) * cw < right - 0.5 * cw


def _is_verse_run(lines: list[Line], right: float) -> bool:
    if len(lines) < 4:
        return False
    hard = sum(1 for a, b in zip(lines, lines[1:]) if _hard_break(a, b, right))
    ends = sum(1 for ln in lines if SENT_END.search(ln.text))
    hy = sum(1 for ln in lines if re.search(r"\w[-‐]$", ln.text.rstrip()))
    return hard / (len(lines) - 1) >= 0.75 and ends / len(lines) < 0.6 and hy == 0


def _verse_lines(pages, seg_lines, stats, body, lead, audit) -> set:
    multi = {p.number: p.columns > 1 for p in pages}
    x1s = sorted(ln.x1 for p in pages if p.columns <= 1 for ln in p.lines
                 if ln.role == "body" and abs(ln.size - body) < 0.6)
    if not x1s:
        return set()
    doc_right = x1s[int(0.95 * (len(x1s) - 1))]
    lefts = sorted(ln.x0 for p in pages for ln in p.lines if ln.role == "body")
    dleft = lefts[int(0.1 * (len(lefts) - 1))]
    # prose has line ends clustered near the right edge; in verse-dominated documents use the page margins
    if sum(1 for x in x1s if x > doc_right - 0.1 * (doc_right - dleft)) / len(x1s) < 0.4:
        widest = max(ln.x1 for p in pages for ln in p.lines if ln.role == "body")
        doc_right = max(widest, min(p.width for p in pages) - dleft)
    verse = set()
    for k, ls in seg_lines.items():
        left, right, _ = stats[k]
        ref_right = right if multi.get(k[0]) else max(right, doc_right)
        run: list[Line] = []
        for ln in ls + [None]:
            flush_left = ln is not None and ln.size <= 1.1 * body and abs(ln.x0 - left) < 0.6 * body
            if flush_left and len(ln.text.strip()) > 3 and (not run or ln.y1 - run[-1].y1 <= 1.3 * lead):
                run.append(ln)
                continue
            if _is_verse_run(run, ref_right):
                verse.update(id(x) for x in run)
            run = [ln] if flush_left else []
    if verse:
        audit.add("L3", "verse_lines", len(verse))
    return verse


def _segment(pages, verse, stats, body, lead, cjk, audit):
    paras: list[_Para] = []
    fnotes: dict[int, list[list[Line]]] = defaultdict(list)
    cur: _Para | None = None
    for p in pages:
        for ln in p.lines:
            if ln.role == "footnote":
                if "fn_start" in ln.notes or not fnotes[p.number]:
                    fnotes[p.number].append([ln])
                else:
                    fnotes[p.number][-1].append(ln)
                continue
            if ln.role != "body":
                continue
            kind = "verse" if id(ln) in verse else "prose"
            left, right, just = stats.get((p.number, ln.col), (ln.x0, ln.x1, False))
            t = ln.text
            new = cur is None or kind != cur.kind
            if not new:
                pv = cur.lines[-1]
                pv_hyph = pv.text.rstrip().endswith(("-", "‐", "⁣"))
                if not ln.flow_break and pv.page == ln.page:
                    gap = ln.y1 - pv.y1
                    if gap > 1.45 * lead or gap < -0.5 * body:
                        new = True
                    elif abs(ln.size - pv.size) > 0.18 * max(ln.size, pv.size) or (ln.bold != pv.bold and len(t) < 90):
                        new = True
                    elif kind == "prose" and _centered(pv, left, right) and _centered(ln, left, right) \
                            and ln.italic == pv.italic and not SENT_END.search(pv.text):
                        new = False  # multi-line centred title
                    elif kind == "prose" and ln.size >= 1.12 * body and abs(ln.size - pv.size) < 0.3:
                        new = False  # multi-line display heading
                    elif kind == "prose":
                        ind = ln.x0 - left
                        if t.startswith("　"):
                            new = True
                        elif ind > 0.6 * body and (pv.x0 - left) < ind - 0.4 * body and not pv_hyph \
                                and not BULLET.match(cur.lines[0].text):  # hanging indent of a list item
                            new = True
                        elif BULLET_SYM.match(t) or (BULLET.match(t) and SENT_END.search(pv.text)):
                            new = True
                        elif (just or cjk) and (right - pv.x1) > 1.5 * body and not pv_hyph \
                                and "dropcap" not in pv.notes and "dropcap_adjacent" not in pv.notes:
                            new = True
                        elif not just and SENT_END.search(pv.text) and (right - pv.x1) > 0.25 * (right - left) \
                                and t[:1].isupper():
                            new = True
                        elif CAPTION.match(t):
                            new = True
                else:  # flow break (new column / page): continue unless there is evidence of a new paragraph
                    _, pright, pjust = stats.get((pv.page, pv.col), (pv.x0, pv.x1, False))
                    p_full = (pright - pv.x1) < 1.5 * body
                    indent = (ln.x0 - left) > 0.6 * body or t.startswith("　")
                    if kind == "verse" or indent or BULLET.match(t) or CAPTION.match(t) \
                            or abs(ln.size - pv.size) > 0.18 * max(ln.size, pv.size):
                        new = True
                    elif pv_hyph or (p_full and (pjust or cjk)) or \
                            (not SENT_END.search(pv.text) and (t[:1].islower() or cjk)):
                        audit.add("L3", "continue_across_" + ("page" if pv.page != ln.page else "column"))
                    else:
                        new = True
            if new:
                cur = _Para(kind)
                paras.append(cur)
            cur.lines.append(ln)
    return paras, fnotes


def _assemble(paras, lang, vocab, cjk, closed_dash, audit) -> None:
    for b in paras:
        if b.kind == "verse":
            b.type = "verse"
            b.text = "\n".join(ln.text.strip() for ln in b.lines)
            continue
        txt = ""
        for ln in b.lines:
            t = ln.text.strip().lstrip("　 ")
            if not txt:
                txt = t
            elif HYPHEN_END.search(txt) and re.match(r"\w", t):
                txt, decision = dehyphenate(txt, t, lang, vocab)
                audit.add("L3", "dehyphen_" + decision)
            elif txt.endswith(("—", "–")) and closed_dash:
                txt += t
            elif cjk and (CJK.search(txt[-1:]) or CJK.search(t[:1])):
                txt += t
            else:
                txt += " " + t
        if any(n.startswith("fnref:") for ln in b.lines for n in ln.notes):
            txt = re.sub(r"\s*\(\s*\)", "", txt)  # "( )" left where a call like "(¹)" was removed
        b.text = txt.replace("⁣", "")


def _classify(paras, stats, body, audit) -> None:
    def top(b):
        return round(max(ln.size for ln in b.lines) * 2) / 2
    head_sizes = sorted({top(b) for b in paras if max(ln.size for ln in b.lines) >= 1.15 * body and len(b.text) < 200},
                        reverse=True)
    for b in paras:
        if b.type == "verse":
            continue
        t = b.text.strip()
        sz, nwords = top(b), len(t.split())
        short = len(t) < 160 and len(b.lines) <= 3
        if CAPTION.match(t) and len(t) < 400:
            b.type = "caption"
        elif short and sz in head_sizes:
            b.type, b.level = "heading", head_sizes.index(sz) + 1
        elif short and CHAPTER.match(t) and len(b.lines) == 1:
            b.type, b.level = "heading", len(head_sizes) + 1
        elif short and all(ln.bold for ln in b.lines) and nwords <= 15 and not t.endswith((".", ",", ";")):
            b.type, b.level = "heading", len(head_sizes) + 1
        elif short and t.isupper() and nwords <= 12 and len(t) > 3 and not SENT_END.search(t):
            b.type, b.level = "heading", len(head_sizes) + 2
        elif len(t) < 260 and len(b.lines) <= 4 and not t.endswith((".", ",", ";", ":")) \
                and all(_centered(ln, *stats.get((ln.page, ln.col), (0, 0, False))[:2]) for ln in b.lines) \
                and (t.isupper() or all(ln.italic for ln in b.lines) or len(b.lines) > 1):
            b.type, b.level = "heading", len(head_sizes) + 2
        elif BULLET.match(t) and (BULLET_SYM.match(t) or len(b.lines) <= 6):
            b.type = "list_item"
            b.text = BULLET_SYM.sub("", t)
        else:
            left, right, _ = stats.get((b.lines[0].page, b.lines[0].col), (0, 0, False))
            if len(b.lines) >= 2 and all(ln.x0 > left + 1.5 * body and ln.x1 < right - 1.5 * body for ln in b.lines):
                b.type = "blockquote"
        if b.type == "heading":
            audit.add("L3", "heading", example=t)


def _footnote_blocks(fnotes, lang, vocab) -> dict[int, list[tuple[str, Block]]]:
    out = {}
    for pno, groups in fnotes.items():
        fbs = []
        for g in groups:
            t = ""
            for ln in g:
                s = ln.text.strip()
                t = s if not t else (dehyphenate(t, s, lang, vocab)[0] if HYPHEN_END.search(t) else t + " " + s)
            m = FN_MARKER.match(t)
            marker = m.group(1).strip("().[] ").translate(SUPERSCRIPT_DIGITS) if m else ""
            fbs.append((marker, Block("footnote", (t[m.end():] if m else t).replace("⁣", ""), source_page=pno,
                                      notes=[f"marker:{marker}"] if marker else [])))
        out[pno] = fbs
    return out


def run(pages: list[Page], lang: str, audit: Audit, layout: dict) -> list[Block]:
    body = layout["body_size"]
    vocab = build_vocab(pages)
    cjk = lang in ("ja", "zh")
    all_text = [ln.text for p in pages for ln in p.lines]
    closed_dash = sum(len(re.findall(r"\w—\w", t)) for t in all_text) > sum(len(re.findall(r"\s—\s", t)) for t in all_text)
    seg_lines = defaultdict(list)
    for p in pages:
        for ln in p.lines:
            if ln.role == "body":
                seg_lines[(p.number, ln.col)].append(ln)
    stats = {k: _seg_stats(ls) for k, ls in seg_lines.items()}
    deltas = [b.y1 - a.y1 for ls in seg_lines.values() for a, b in zip(ls, ls[1:])
              if 0 < b.y1 - a.y1 < 3 * body and abs(a.size - body) < 0.6 and abs(b.size - body) < 0.6]
    lead = statistics.median(deltas) if deltas else 1.25 * body
    verse = set() if cjk else _verse_lines(pages, seg_lines, stats, body, lead, audit)
    paras, fnotes = _segment(pages, verse, stats, body, lead, cjk, audit)
    _assemble(paras, lang, vocab, cjk, closed_dash, audit)
    _classify(paras, stats, body, audit)
    notes_by_page = _footnote_blocks(fnotes, lang, vocab)
    out: list[Block] = []
    placed = set()
    for b in paras:
        if not b.text.strip():
            continue
        blk = Block(b.type, b.text, level=b.level, source_page=b.lines[0].page, source_page_end=b.lines[-1].page)
        out.append(blk)
        refs = {n.split(":", 1)[1] for ln in b.lines for n in ln.notes if n.startswith("fnref:")}
        for pg in range(blk.source_page, blk.source_page_end + 1):
            for marker, fb in notes_by_page.get(pg, []):
                if id(fb) not in placed and marker in refs:
                    out.append(fb)
                    placed.add(id(fb))
    for pno, fbs in notes_by_page.items():  # unanchored notes: after the last block of their page
        for _, fb in fbs:
            if id(fb) not in placed:
                idx = max((i for i, b in enumerate(out) if b.type != "footnote" and (b.source_page or 0) <= pno),
                          default=len(out) - 1)
                out.insert(idx + 1, fb)
                placed.add(id(fb))
                audit.add("L3", "footnote_unanchored")
    return out
