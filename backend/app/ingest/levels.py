"""Format-independent levels. Each records what it changed in `doc.audit` under its level name.

  L1  clean_text         character normalisation (NFC, ligatures, soft hyphens, odd spaces, control/zero-width,
                         TeX quotes and dashes, French no-break spaces, guarded mojibake repair)
  L2  flag_boilerplate   Project Gutenberg header/licence, ebook metadata header, tables of contents -> role +
                         `removed` reason (kept in the IR, never deleted); reference markers in text sources
  L3  infer_structure    verse runs and chapter headings in formats without markup (TXT, DOCX, FB2 from Calibre)
  L4  assess             document language (character-weighted vote over paragraphs), quality warnings
"""
from __future__ import annotations

import html as html_lib
import re
import unicodedata
from collections import Counter

from app.ingest import langid
from app.ingest.ir import Audit, Block, Document

# ------------------------------------------------------------------------------------------------ L1
LIGATURES = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st"}
_LIG = re.compile("[" + "".join(LIGATURES) + "]")
_ZERO_WIDTH = re.compile("[​‎‏⁠﻿]")
_CONTROL = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f]")
_ODD_SPACE = re.compile("[  -   　]")
_PUA = re.compile("[-]")
_MOJIBAKE = re.compile("Ã[\x80-\xbf©¨ª«®¯°±²³´µ¶·¸¹º»¼½¾¿]|â€[™œ\x9d“”˜¦¢]|Ð[°±²³´µ¶·¸¹º»¼½¾¿]|Ñ[\x80-\x8f]|"
                       "ã\x81|Å[¡¾]|Ä[\x81\x8d]")
_ENTITY = re.compile(r"&(#\d+|#x[0-9a-f]+|[a-z]{2,8});", re.I)
SOFT_MARK = "‐⁣"  # line-final soft hyphen (PDF): joined without a hyphen by the PDF L3


def clean_text(t: str, lang: str | None, audit: Audit, keep_newlines: bool = False, entities: bool = False) -> str:
    if not t:
        return t
    t0 = t
    if _MOJIBAKE.search(t):
        import ftfy
        fixed = ftfy.fix_encoding(t)
        if fixed != t:
            audit.add("L1", "mojibake_repaired", example=t[:60])
            t = fixed
    if entities and "&" in t and _ENTITY.search(t):
        t = html_lib.unescape(t)
        audit.add("L1", "html_entities")
    t2 = unicodedata.normalize("NFC", t)
    if t2 != t:
        audit.add("L1", "nfc")
        t = t2
    if _LIG.search(t):
        audit.add("L1", "ligature", len(_LIG.findall(t)))
        t = _LIG.sub(lambda m: LIGATURES[m.group(0)], t)
    if "­" in t:
        audit.add("L1", "soft_hyphen", t.count("­"))
        t = t.replace("­", "")
    if lang == "fr":  # French typography: no-break space before ; : ! ? » and after «
        t = re.sub("[   ](?=[;:!?»])", " ", t)
        t = re.sub("(?<=«)[   ]", " ", t)
        t2 = re.sub("[ -  　]|[  ](?![;:!?»])(?<!«.)", " ", t)
    else:
        t2 = _ODD_SPACE.sub(" ", t) if lang != "ja" else re.sub("[  -   ]", " ", t)
    if t2 != t:
        audit.add("L1", "odd_space")
        t = t2
    t2 = _CONTROL.sub("", _ZERO_WIDTH.sub("", t).replace("\t", " "))  # keeps \n
    if t2 != t:
        audit.add("L1", "control_or_zero_width")
        t = t2
    if _PUA.search(t):
        audit.add("L1", "private_use_chars", len(_PUA.findall(t)))
    if lang != "ja":
        if "``" in t or "''" in t:
            open_q, close_q = ("„", "“") if lang == "de" else ("“", "”")
            t = t.replace("``", open_q).replace("''", close_q)
            audit.add("L1", "tex_quotes")
        if lang == "de" and ",," in t:
            t = t.replace(",,", "„")
            audit.add("L1", "de_low_quote")
        if "--" in t:
            t2 = re.sub(r"(?<!-)---?(?!-)", "—", t)
            if t2 != t:
                audit.add("L1", "double_hyphen_dash")
                t = t2
    if t != t0 and not keep_newlines:
        t = re.sub(r"[ ]{2,}", " ", t)
    return t


# ------------------------------------------------------------------------------------------------ L2
_PG_START = re.compile(r"\*\*\*\s*START OF (THE|THIS) PROJECT GUTENBERG", re.I)
_PG_END = re.compile(r"\*\*\*\s*END OF (THE|THIS) PROJECT GUTENBERG", re.I)
_PG_PRODUCER = re.compile(r"project gutenberg|gutenberg\.org|^produced by|transcriber['’]s note|e-?text prepared by", re.I)
_EBOOK_META = re.compile(r"\b(Title|Author|Release [Dd]ate|Language|Credits|Most recently updated|Illustrator|"
                         r"Translator|Produced by|Original publication):")
TOC_HEAD = re.compile(r"^\s*(contents|table of contents|table des matières|inhalt|inhaltsverzeichnis|содержание|"
                      r"оглавление|índice|indice|sumário|saturs|目次)\s*\.?$", re.I)
_LEADER = re.compile(r"(?:\.\s?){3,}\s*\d+|…{2,}\s*\d+")
_REF_MARK = re.compile(r"\[(\d{1,3}[a-z]?|[a-z]|note \d+|citation needed|réf\. nécessaire|источник не указан[^\]]*|"
                       r"nicht belegt|carece de fontes|nepieciešama atsauce|要出典[^\]]*|[ivx]+)\]", re.I)
_EDIT_MARK = re.compile(r"\s*\[\s*(edit|modifier|modifier \| modifier le code|править|править \| править код|"
                        r"bearbeiten|bearbeiten \| quelltext bearbeiten|editar|editar \| editar código-fonte|labot|"
                        r"labot \| labot pirmkodu|編集|edit source|edit \| edit source)\s*\]", re.I)


def _key(t: str) -> str:
    return re.sub(r"\W+", " ", t.lower()).strip()


def flag_boilerplate(doc: Document, strip_reference_marks: bool = False) -> None:
    B, audit = doc.blocks, doc.audit
    start = next((i for i, b in enumerate(B) if _PG_START.search(b.text)), None)
    end = next((i for i, b in enumerate(B) if _PG_END.search(b.text)), None)
    if start is not None and start < 0.3 * len(B):
        for b in B[:start + 1]:
            b.remove("gutenberg_header", "boilerplate")
        audit.add("L2", "gutenberg_header", start + 1)
    if end is not None and end > 0.5 * len(B):
        for b in B[end:]:
            b.remove("gutenberg_licence", "boilerplate")
        audit.add("L2", "gutenberg_licence", len(B) - end)
    lo = (start + 1) if start is not None else 0
    for b in B[lo:lo + 8]:
        if b.role == "body" and _PG_PRODUCER.search(b.text) and len(b.text) < 600:
            b.remove("ebook_producer_note", "boilerplate")
            audit.add("L2", "ebook_producer_note", example=b.text)
    for b in B:
        if b.role == "body" and len(b.text) > 150 and "Project Gutenberg" in b.text \
                and re.search(r"licen[cs]e|eBook|trademark", b.text, re.I):
            b.remove("gutenberg_licence", "boilerplate")
            audit.add("L2", "gutenberg_paragraph", example=b.text)
    for b in B[:15]:
        if b.role == "body" and len(_EBOOK_META.findall(b.text)) >= 2:
            b.remove("ebook_metadata", "boilerplate")
            audit.add("L2", "ebook_metadata", example=b.text)
    _flag_toc(doc)
    if strip_reference_marks:
        for b in B:
            if b.type != "footnote":
                t = _EDIT_MARK.sub("", _REF_MARK.sub("", b.text))
                if t != b.text:
                    audit.add("L2", "reference_marks_stripped", example=b.text[:60])
                    b.text = re.sub(r"\s+([,.;:!?)])", r"\1", t) if doc.language != "fr" else t


def _flag_toc(doc: Document) -> None:
    """TOC = heading 'Contents' + the short entries / table after it; a table whose rows repeat the chapter
    headings; blocks dominated by dot leaders; or a run of >= 5 short blocks that repeat later chapter headings
    (EPUB/HTML tables of contents without a heading)."""
    B = doc.blocks
    heads = Counter(_key(b.text) for b in B if b.type == "heading")
    in_toc, run = False, []

    def mark(b, rule):
        if b.removed is None:
            b.remove("toc", "toc")
            doc.audit.add("L2", rule, example=b.text[:60])

    for i, b in enumerate(B + [Block("paragraph", "x" * 500)]):
        t = b.text.strip()
        leaders = len(_LEADER.findall(t))
        # rows of a <table> / <br>-separated lines (EPUB, HTML): a TOC when half of them repeat chapter headings
        lines = [k for k in map(_key, t.split("\n")) if len(k) >= 6] if b.type in ("table", "verse") else []
        if TOC_HEAD.match(t):
            in_toc = True
            mark(b, "toc_heading")
        elif len(lines) >= 3 and sum(1 for x in lines if any(len(h) >= 6 and (x.startswith(h) or h.startswith(x))
                                                             for h in heads)) >= 0.5 * len(lines):
            mark(b, "toc_table")
        elif leaders and len(_LEADER.sub("", t)) <= 80 * leaders:  # entries joined into one block in PDFs
            mark(b, "toc_leaders")
        elif in_toc and (len(t) < 120 or b.type == "table") and (b.type != "heading" or re.search(r"\d+\s*$", t)):
            mark(b, "toc_entry")  # short entries, or the table, right after a "Contents" heading
        else:
            in_toc = False
        if len(t) < 90 and b.type in ("list_item", "paragraph") and heads.get(_key(t), 0) >= 1:
            run.append(b)
        elif b.type != "separator":
            if len(run) >= 5:
                for x in run:
                    mark(x, "toc_run")
            run = []


# ------------------------------------------------------------------------------------------------ L3 (reflow)
HEADING_RX = re.compile(
    r"^\s*((chapitre|chapter|kapitel|capítulo|capitulo|глава|часть|livre|book|teil|parte|nodaļa|daļa|acte?|scène|"
    r"scene|akt|szene|действие|явление)\s+([ivxlcdm]+|\d+|premier|première|first|[a-zа-я]+)\b.{0,60}|"
    r"[IVXLCDM]{1,7}\.?|\d{1,3}\.?|第[一二三四五六七八九十百〇0-9]+[章話回節部])\s*$", re.I)
LEVEL1 = re.compile(r"^\s*(livre|book|tome|volume|part|partie|teil|часть|том|parte|daļa|第.+部)\b", re.I)
TERMINAL = re.compile(r"[.!?…»”\"')\]:;。！？」』]\s*$")


def infer_structure(doc: Document) -> None:
    out, run = [], []

    def is_line(b: Block) -> bool:
        return (b.type == "paragraph" and b.readable and 0 < len(b.text) < 60 and "\n" not in b.text
                and not HEADING_RX.match(b.text) and not re.match(r"^[—–\-«\"]", b.text))

    def flush():
        if (len(run) >= 3 and sum(1 for b in run if not TERMINAL.search(b.text)) >= 0.5 * len(run)
                and sum(1 for b in run if b.text[:1].isupper()) >= 0.7 * len(run)):
            v = Block("verse", "\n".join(b.text for b in run), confidence=0.75, notes=["verse_inferred"],
                      source_page=run[0].source_page, chapter=run[0].chapter)
            out.append(v)
            doc.audit.add("L3", "verse_inferred", len(run), example=v.text[:60])
        else:
            out.extend(run)
        run.clear()

    for b in doc.blocks:
        if is_line(b):
            run.append(b)
        elif b.type == "separator" and run:
            continue  # Calibre FB2 / DOCX put empty lines between verse lines
        else:
            flush()
            out.append(b)
    flush()
    doc.blocks = out
    for b in doc.blocks:
        if b.type == "paragraph" and b.readable and len(b.text) < 80 and HEADING_RX.match(b.text):
            b.type, b.level, b.confidence = "heading", 1 if LEVEL1.match(b.text) else 2, 0.7
            doc.audit.add("L3", "heading_inferred", example=b.text)


# ------------------------------------------------------------------------------------------------ L4
def vote_language(blocks: list[Block]) -> tuple[str | None, float]:
    """Character-weighted vote over paragraph-like blocks (robust to quotations in another language)."""
    paras = [b for b in blocks if b.readable and b.type in ("paragraph", "blockquote", "verse", "list_item")
             and len(b.text) >= 40]
    votes: Counter = Counter()
    for b in paras[::max(1, len(paras) // 300)]:
        lang, score = langid.detect(b.text)
        if lang:
            votes[lang] += len(b.text) * score
    if votes:
        lang = votes.most_common(1)[0][0]
        return lang, votes[lang] / sum(votes.values())
    return langid.detect(" ".join(b.text for b in blocks if b.readable)[:20000])


def assess(doc: Document, declared: str | None) -> None:
    """Final language (declared by the user wins; metadata otherwise; detection when neither), warnings."""
    det, score = vote_language(doc.blocks)
    doc.language_detected, doc.language_score = det, score
    meta = langid.norm_lang(doc.language)
    chosen = declared or (meta if meta and not (det and det != meta and score > 0.8) else det) or meta or "en"
    if det and det != chosen and score > 0.8:
        doc.warn("language_mismatch", f"The text looks like '{det}' (confidence {score:.2f}), not '{chosen}'.")
    doc.language = chosen
    kept = [b for b in doc.blocks if b.readable]
    chars = sum(len(b.text) for b in kept)
    if chars < 200:
        doc.warn("little_text", "Very little text was extracted.")
    total = sum(len(b.text) for b in doc.blocks) or 1
    removed = sum(len(b.text) for b in doc.blocks if not b.readable)
    if removed / total > 0.6 and doc.source_format in ("paste", "paste_html", "url"):
        doc.warn("mostly_removed", f"{int(100 * removed / total)}% of the text was classified as page furniture; "
                                   "review the removed blocks.")
    paras = [b for b in kept if b.type == "paragraph"]
    if len(paras) > 5 and doc.source_format in ("paste", "paste_html", "url"):
        short = sum(1 for b in kept if len(b.text.split()) < 5 and b.type != "heading") / len(kept)
        term = sum(1 for b in paras if TERMINAL.search(b.text)) / len(paras)
        if short > 0.45 or term < 0.35:
            doc.warn("not_prose", "This looks like navigation or lists rather than continuous prose; check the "
                                  "preview before translating.")
