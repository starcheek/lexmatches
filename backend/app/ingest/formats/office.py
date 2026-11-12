"""DOCX (mammoth -> HTML walker), ODT (direct content.xml walk), RTF (striprtf -> plain-text reflow)."""
from __future__ import annotations

import io
import re
import zipfile

from lxml import etree

from app.ingest.formats.html import html_to_blocks, noteref_targets, parse_html
from app.ingest.ir import Block, Document, IngestError

XMLP = etree.XMLParser(recover=True, resolve_entities=False, no_network=True, huge_tree=True)
WS = re.compile(r"\s+")
DOCX_STYLES = """p[style-name='Title'] => h1:fresh
p[style-name='Subtitle'] => h2:fresh
p[style-name='Quote'] => blockquote > p:fresh
p[style-name='Intense Quote'] => blockquote > p:fresh
p[style-name='Block Text'] => blockquote > p:fresh"""


def _core_props(z: zipfile.ZipFile, doc: Document, path: str) -> None:
    try:
        root = etree.fromstring(z.read(path), XMLP)
    except Exception:
        return
    for el in root.iter():
        name = etree.QName(el).localname if isinstance(el.tag, str) else ""
        value = (el.text or "").strip()
        if not value:
            continue
        if name == "title":
            doc.title = value
        elif name in ("creator", "initial-creator") and not doc.author:
            doc.author = value
        elif name == "language":
            doc.language = value


def parse_docx(data: bytes) -> Document:
    import mammoth
    try:
        result = mammoth.convert_to_html(io.BytesIO(data), style_map=DOCX_STYLES)
    except Exception as e:
        raise IngestError(f"This DOCX file could not be read ({type(e).__name__}).") from e
    root = parse_html("<html><body>" + result.value + "</body></html>")
    for li in root.iter("li"):  # mammoth notes: <li id="footnote-1">… <a href="#footnote-ref-1">↑</a>
        if (li.get("id") or "").startswith(("footnote-", "endnote-")):
            li.set("class", "footnote")
            for a in list(li.iter("a")):
                if (a.get("href") or "").startswith(("#footnote-ref", "#endnote-ref")):
                    a.drop_tree()
    doc = Document([], "docx", "mammoth -> lxml html walker")
    doc.blocks, _, refs = html_to_blocks(root, noteref_targets(root))
    doc.audit.add("L0", "noteref_markers_dropped", refs)
    _core_props(zipfile.ZipFile(io.BytesIO(data)), doc, "docProps/core.xml")
    return doc


def parse_odt(data: bytes) -> Document:
    T = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
    TB = "urn:oasis:names:tc:opendocument:xmlns:table:1.0"
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        root = etree.fromstring(z.read("content.xml"), XMLP)
    except Exception as e:
        raise IngestError("This ODT file could not be read.") from e
    doc = Document([], "odt", "lxml content.xml walker")
    _core_props(z, doc, "meta.xml")
    notes: list[str] = []

    def text_of(el) -> str:
        buf = []

        def rec(e):
            if e.text:
                buf.append(e.text)
            for c in e:
                if c.tag == f"{{{T}}}note":
                    body = c.find(f"{{{T}}}note-body")
                    if body is not None:
                        notes.append(" ".join(WS.sub(" ", "".join(p.itertext())).strip() for p in body))
                elif c.tag == f"{{{T}}}s":
                    buf.append(" ")
                elif c.tag == f"{{{T}}}tab":
                    buf.append(" ")
                elif c.tag == f"{{{T}}}line-break":
                    buf.append("\n")
                else:
                    rec(c)
                if c.tail:
                    buf.append(c.tail)
        rec(el)
        return re.sub(r"[ \t]+", " ", "".join(buf)).strip()

    def walk(el, depth=0):
        for c in el:
            if c.tag == f"{{{T}}}h":
                t = text_of(c)
                if t:
                    doc.blocks.append(Block("heading", t, level=int(c.get(f"{{{T}}}outline-level", "1"))))
            elif c.tag == f"{{{T}}}p":
                t = text_of(c)
                if t:
                    btype = "verse" if "\n" in t else ("list_item" if depth else "paragraph")
                    doc.blocks.append(Block(btype, t, level=depth or None))
            elif c.tag == f"{{{T}}}list":
                walk(c, depth + 1)
            elif c.tag == f"{{{TB}}}table":
                rows = [" | ".join(WS.sub(" ", "".join(cell.itertext())).strip() for cell in r)
                        for r in c.iter(f"{{{TB}}}table-row")]
                doc.blocks.append(Block("table", "\n".join(rows)))
            else:
                walk(c, depth)

    office_text = next(root.iter("{urn:oasis:names:tc:opendocument:xmlns:office:1.0}text"), None)
    if office_text is None:
        raise IngestError("This ODT file has no text body.")
    walk(office_text)
    doc.blocks += [Block("footnote", t) for t in notes if t]
    return doc


def parse_rtf(data: bytes, declared: str | None) -> Document:
    from striprtf.striprtf import rtf_to_text

    from app.ingest.formats.text import parse_text
    m = re.search(rb"\\ansicpg(\d+)", data[:2000])
    codepage = f"cp{m.group(1).decode()}" if m else "cp1252"
    try:
        text = rtf_to_text(data.decode("latin-1"), encoding=codepage, errors="ignore")
    except LookupError:
        text = rtf_to_text(data.decode("latin-1"), errors="ignore")
    doc = parse_text(text, declared, source_format="rtf")
    doc.extractor = "striprtf -> text reflow"
    return doc
