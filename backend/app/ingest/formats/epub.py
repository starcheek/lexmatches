"""EPUB 2/3: zip + lxml spine walk (no ebooklib). Tolerates truncated archives / corrupt central directory
(local-header scan), missing container.xml or OPF, missing manifest items and broken XHTML. Chapters come from the
EPUB3 nav or the EPUB2 NCX: the first block of every TOC target starts a new reading unit."""
from __future__ import annotations

import io
import posixpath
import urllib.parse
import zipfile
import zlib

from lxml import etree

from app.ingest import drm
from app.ingest.encoding import decode
from app.ingest.formats.html import html_to_blocks, noteref_targets, parse_html
from app.ingest.ir import Document, IngestError

NS = {"opf": "http://www.idpf.org/2007/opf", "dc": "http://purl.org/dc/elements/1.1/",
      "c": "urn:oasis:names:tc:opendocument:xmlns:container", "ncx": "http://www.daisy.org/z3986/2005/ncx/"}
XMLP = etree.XMLParser(recover=True, resolve_entities=False, no_network=True, huge_tree=True)


class ZipReader:
    """zipfile with a fallback that scans local file headers (truncated / EOCD-damaged archives)."""

    def __init__(self, data: bytes, warnings: list):
        self.entries: dict[str, bytes] = {}
        self.z = None
        try:
            self.z = zipfile.ZipFile(io.BytesIO(data))
            self.names = self.z.namelist()
        except Exception:
            warnings.append("damaged archive: recovered by scanning local file headers")
            self._scan(data, warnings)
            self.names = list(self.entries)

    def _scan(self, data: bytes, warnings: list) -> None:
        pos = 0
        while True:
            i = data.find(b"PK\x03\x04", pos)
            if i < 0 or i + 30 > len(data):
                break
            flags = int.from_bytes(data[i + 6:i + 8], "little")
            method = int.from_bytes(data[i + 8:i + 10], "little")
            csize = int.from_bytes(data[i + 18:i + 22], "little")
            nlen = int.from_bytes(data[i + 26:i + 28], "little")
            xlen = int.from_bytes(data[i + 28:i + 30], "little")
            name = data[i + 30:i + 30 + nlen].decode("utf-8", "replace")
            start = i + 30 + nlen + xlen
            sized = csize and not (flags & 8)
            try:
                if method == 0:
                    self.entries[name] = data[start:start + csize] if sized else data[start:data.find(b"PK", start)]
                elif method == 8:
                    d = zlib.decompressobj(-15)
                    self.entries[name] = d.decompress(data[start:start + csize] if sized else data[start:])
                    if not d.eof:
                        warnings.append(f"truncated entry recovered partially: {name}")
            except zlib.error:
                warnings.append(f"unrecoverable entry: {name}")
            pos = start + csize if sized else start + 1

    def read(self, name: str) -> bytes | None:
        candidates = [name] + [n for n in self.names if n.lower() == name.lower() or urllib.parse.unquote(n) == name]
        for n in candidates:
            try:
                if self.z is not None:
                    return self.z.read(n)
                if n in self.entries:
                    return self.entries[n]
            except KeyError:
                continue
            except Exception:  # CRC error / truncated member inside a readable central directory
                return None
        return None


def _xml(data: bytes | None):
    return etree.fromstring(data, XMLP) if data else None


def _toc(zr: ZipReader, opf_dir: str, nav_href: str | None, ncx_href: str | None) -> list[tuple[str, str, str]]:
    """[(zip path, fragment, title)] from the EPUB3 nav, else the NCX."""
    toc = []
    if nav_href:
        root = parse_html(zr.read(posixpath.join(opf_dir, nav_href)) or b"<html/>")
        navs = [n for n in root.iter("nav")
                if "toc" in (n.get("{http://www.idpf.org/2007/ops}type") or n.get("epub:type") or "toc")]
        base = posixpath.join(opf_dir, posixpath.dirname(nav_href))
        for a in (navs[0].iter("a") if navs else ()):
            path, _, frag = urllib.parse.unquote(a.get("href") or "").partition("#")
            toc.append((posixpath.normpath(posixpath.join(base, path)) if path else "", frag,
                        " ".join(a.text_content().split())))
    if not toc and ncx_href:
        root = _xml(zr.read(posixpath.join(opf_dir, ncx_href)))
        base = posixpath.join(opf_dir, posixpath.dirname(ncx_href))
        for np_ in (root.iter("{%s}navPoint" % NS["ncx"]) if root is not None else ()):
            label = np_.findtext("ncx:navLabel/ncx:text", default="", namespaces=NS).strip()
            c = np_.find("ncx:content", NS)
            path, _, frag = urllib.parse.unquote(c.get("src") if c is not None else "").partition("#")
            toc.append((posixpath.normpath(posixpath.join(base, path)), frag, label))
    return toc


def parse(data: bytes) -> Document:
    warnings: list[str] = []
    zr = ZipReader(data, warnings)
    drm.check_epub({n.lower(): n for n in zr.names}, lambda n: zr.read(n))
    doc = Document([], "epub", "zip + lxml spine walk")
    opf_path = None
    cont = _xml(zr.read("META-INF/container.xml"))
    rf = cont.find(".//c:rootfile", NS) if cont is not None else None
    if rf is not None:
        opf_path = rf.get("full-path")
    if not opf_path or zr.read(opf_path) is None:
        cands = [n for n in zr.names if n.lower().endswith(".opf")]
        opf_path = cands[0] if cands else None
        if opf_path:
            warnings.append("container.xml missing or invalid; OPF found by search")
    opf = _xml(zr.read(opf_path)) if opf_path else None
    spine, toc, opf_dir = [], [], ""
    if opf is not None:
        opf_dir = posixpath.dirname(opf_path)
        md = opf.find(".//{*}metadata")
        if md is not None:
            doc.title = (md.findtext("dc:title", namespaces=NS) or "").strip() or None
            doc.author = ", ".join(c.text.strip() for c in md.findall("dc:creator", NS) if c.text) or None
            doc.language = (md.findtext("dc:language", namespaces=NS) or "").strip() or None
        manifest, nav_href, ncx_href = {}, None, None
        for it in opf.iterfind(".//opf:manifest/opf:item", NS):
            href = urllib.parse.unquote(it.get("href") or "")
            manifest[it.get("id")] = (href, it.get("media-type") or "")
            if "nav" in (it.get("properties") or "").split():
                nav_href = href
            if it.get("media-type") == "application/x-dtbncx+xml":
                ncx_href = href
        sp = opf.find(".//opf:spine", NS)
        for ir in (sp.iterfind("opf:itemref", NS) if sp is not None else ()):
            m = manifest.get(ir.get("idref"))
            if m:
                spine.append((posixpath.normpath(posixpath.join(opf_dir, m[0])), ir.get("linear", "yes") != "no"))
            else:
                warnings.append(f"spine item {ir.get('idref')} missing from manifest")
        if not spine:
            spine = [(posixpath.normpath(posixpath.join(opf_dir, h)), True) for h, mt in manifest.values() if "html" in mt]
        toc = _toc(zr, opf_dir, nav_href, ncx_href)
    if not spine:
        warnings.append("no usable OPF: reading every (X)HTML file in archive order")
        spine = [(n, True) for n in zr.names if n.lower().endswith((".xhtml", ".html", ".htm"))]
    docs = []
    for href, linear in spine:
        raw = zr.read(href)
        if raw is None:
            warnings.append(f"missing spine document: {href}")
            continue
        try:
            docs.append((href, linear, parse_html(decode(raw)[0])))
        except Exception:
            warnings.append(f"unparseable spine document: {href}")
    if not docs:
        raise IngestError("This EPUB contains no readable content documents.")
    note_ids = set().union(*(noteref_targets(d) for _, _, d in docs))
    chapters: dict[str, list[tuple[str, str]]] = {}
    for path, frag, title in toc:
        chapters.setdefault(path, []).append((frag, title))
    refs = 0
    for href, linear, d in docs:
        blocks, anchors, n = html_to_blocks(d, note_ids)
        refs += n
        for frag, title in chapters.get(href, []):
            i = anchors.get(frag, 0) if frag else 0
            if i < len(blocks) and blocks[i].chapter is None:
                blocks[i].chapter = title or blocks[i].text[:120]
        if not linear:
            for b in blocks:
                if b.role == "body" and b.type != "footnote":
                    b.notes.append("nonlinear")
        doc.blocks.extend(blocks)
    doc.audit.add("L0", "spine_documents", len(docs))
    doc.audit.add("L0", "noteref_markers_dropped", refs)
    for w in warnings:
        doc.warn("damaged_file" if "font obfuscation" not in w else "info", w)
    if len(warnings) > 5:
        doc.warnings = doc.warnings[:5] + [{"code": "damaged_file", "message": f"... {len(warnings) - 5} more"}]
    return doc
