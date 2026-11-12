"""FictionBook 2 (.fb2 / .fb2.zip): sections -> headings, poems -> verse stanzas, epigraphs/cites -> blockquotes,
notes bodies -> footnotes. The XML declaration's encoding (often windows-1251) is honoured by lxml."""
from __future__ import annotations

import io
import re
import zipfile

from lxml import etree

from app.ingest.ir import Block, Document, IngestError

XMLP = etree.XMLParser(recover=True, resolve_entities=False, no_network=True, huge_tree=True)
WS = re.compile(r"\s+")


def _local(el) -> str:
    return etree.QName(el).localname if isinstance(el.tag, str) else ""


def _text(el) -> str:
    parts = []

    def rec(e):
        if e.text:
            parts.append(e.text)
        for c in e:
            is_noteref = _local(c) == "a" and (c.get("type") == "note" or
                                               (c.get("{http://www.w3.org/1999/xlink}href") or "").startswith("#"))
            if not is_noteref:
                rec(c)
            if c.tail:
                parts.append(c.tail)
    rec(el)
    return WS.sub(" ", "".join(parts)).strip()


def parse(data: bytes, zipped: bool = False) -> Document:
    if zipped:
        z = zipfile.ZipFile(io.BytesIO(data))
        data = z.read(next(n for n in z.namelist() if n.lower().endswith(".fb2")))
    root = etree.fromstring(data, XMLP)
    if root is None:
        raise IngestError("This FB2 file is not readable XML.")
    doc = Document([], "fb2", "lxml fb2 mapper")
    info = next((e for e in root.iter() if _local(e) == "title-info"), None)
    for e in (info if info is not None else ()):
        if _local(e) == "book-title":
            doc.title = _text(e)
        elif _local(e) == "lang":
            doc.language = (e.text or "").strip()
        elif _local(e) == "author" and not doc.author:
            doc.author = " ".join(_text(c) for c in e if _local(c) in ("first-name", "middle-name", "last-name")) or None
    blocks = doc.blocks

    def section(el, depth: int, notes: bool):
        for c in el:
            name = _local(c)
            if name == "title":
                t = " ".join(_text(p) for p in c if _local(p) == "p")
                if t:
                    blocks.append(Block("footnote" if notes else "heading", t, level=None if notes else min(6, depth)))
            elif name in ("p", "subtitle", "text-author"):
                t = _text(c)
                if t:
                    btype = "footnote" if notes else ("heading" if name == "subtitle" else "paragraph")
                    blocks.append(Block(btype, t, level=min(6, depth + 1) if btype == "heading" else None))
            elif name == "poem":
                for st in c:
                    if _local(st) == "stanza":
                        lines = [_text(v) for v in st if _local(v) == "v"]
                        if any(lines):
                            blocks.append(Block("verse", "\n".join(x for x in lines if x)))
                    elif _local(st) == "title":
                        t = " ".join(_text(p) for p in st if _local(p) == "p")
                        if t:
                            blocks.append(Block("heading", t, level=min(6, depth + 1)))
            elif name in ("epigraph", "cite"):
                for p in c.iter():
                    if _local(p) in ("p", "text-author") and _text(p):
                        blocks.append(Block("blockquote", _text(p)))
            elif name == "empty-line":
                blocks.append(Block("separator", ""))
            elif name == "table":
                rows = [" | ".join(_text(td) for td in tr) for tr in c if _local(tr) == "tr"]
                blocks.append(Block("table", "\n".join(rows)))
            elif name == "section":
                section(c, depth + 1, notes)

    for body in [e for e in root if _local(e) == "body"]:
        section(body, 1, notes=body.get("name") in ("notes", "comments"))
    for b in blocks:
        if b.type == "heading" and (b.level or 9) <= 2:
            b.chapter = b.text
    return doc
