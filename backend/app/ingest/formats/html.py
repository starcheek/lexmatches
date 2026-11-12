"""(X)HTML DOM -> blocks. Used for EPUB spine documents, HTML files, DOCX (via mammoth), Markdown (via markdown-it),
pasted rich HTML and fetched web pages.

Book-like HTML keeps every block. Web pages (URL, clipboard, chrome-heavy HTML files) are reduced to the article:
trafilatura picks the main content, blocks whose word shingles are not in it are flagged `web_chrome`, then
text rules flag what follows the article end (References / See also / Comments ...), citations and photo credits.
"""
from __future__ import annotations

import re

from lxml import etree
from lxml import html as LH

from app.ingest.ir import Block, Document

EPUB_NS = "http://www.idpf.org/2007/ops"
BLOCKS = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "pre", "table", "figure", "figcaption", "dt",
          "dd", "hr", "div", "section", "article", "aside", "header", "footer", "main", "nav", "ul", "ol", "dl", "body",
          "center", "address", "details", "summary", "tr", "tbody", "thead", "caption", "hgroup", "td", "th"}
SKIP = {"script", "style", "noscript", "template", "svg", "math", "head", "title", "button", "form", "input", "select",
        "textarea", "iframe", "object", "video", "audio", "map", "link", "meta", "rt", "rp", "img"}
VERSE_RX = re.compile(r"\b(verse|poem|poetry|stanza|lg|vers|poesie|poème|line-group|z3998:poem|z3998:verse|"
                      r"z3998:song|z3998:hymn|linegroup)\b", re.I)
NOTE_RX = re.compile(r"(^|\s|:)(footnotes?|endnotes?|rearnotes?|doc-footnote|doc-endnotes?|fn|ftn\d*|notes?-?body)($|\s)",
                     re.I)
NOTE_ID_RX = re.compile(r"^(fn|ftn|footnote|endnote|note|nt)[-_:]?\d+$", re.I)
NOTEREF_TXT = re.compile(r"^\s*[\[\(]?\s*(\d{1,4}|[a-z]|[ivxlc]{1,6}|\*{1,3}|†|‡)\s*[\]\)]?\s*$", re.I)
PAGENUM_RX = re.compile(r"\b(pagenum|page-?number|pagebreak|pageno|pb)\b", re.I)
HIDDEN_RX = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden", re.I)
WS = re.compile(r"[ \t\r\n\f​]+")
# epub:type / class -> (role, removed reason)
ROLE_TYPES = [("titlepage", "front_matter", "title_page"), ("halftitlepage", "front_matter", "title_page"),
              ("imprint", "front_matter", "imprint"), ("copyright-page", "front_matter", "copyright"),
              ("colophon", "back_matter", "colophon"), ("pg-boilerplate", "boilerplate", "gutenberg_licence"),
              ("toc", "toc", "toc"), ("loi", "toc", "toc"), ("lot", "toc", "toc"), ("landmarks", "toc", "toc"),
              ("page-list", "toc", "toc")]


def _tag(el) -> str:
    return el.tag.split("}")[-1].lower() if isinstance(el.tag, str) else ""


def _types(el) -> str:
    return " ".join(filter(None, [el.get("class"), el.get(f"{{{EPUB_NS}}}type"), el.get("epub:type"), el.get("role")]))


def _tc(el) -> str:
    return "".join(el.itertext()) if isinstance(el.tag, str) else ""


def _by_class(root, *names: str) -> list:
    """Elements carrying any of the classes (XPath: lxml's cssselect() needs the extra `cssselect` package)."""
    return root.xpath("//*[" + " or ".join(
        f"contains(concat(' ', normalize-space(@class), ' '), ' {n} ')" for n in names) + "]")


def parse_html(text: str | bytes):
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    text = re.sub(r"^\s*<\?xml[^>]*\?>", "", text)  # lxml.html refuses str input with an encoding declaration
    try:
        return LH.document_fromstring(text)
    except Exception:
        return LH.fromstring("<html><body>" + text + "</body></html>")


def noteref_targets(root) -> set[str]:
    ids = set()
    for a in root.iter("a", "{http://www.w3.org/1999/xhtml}a"):
        href = a.get("href") or ""
        if "#" in href and ("noteref" in _types(a) or NOTEREF_TXT.match(_tc(a))):
            ids.add(href.split("#")[-1])
    return ids


class Walker:
    def __init__(self, note_ids: set[str] | None = None):
        self.blocks: list[Block] = []
        self.anchors: dict[str, int] = {}   # element id -> index of the first block at or after it
        self.note_ids = note_ids or set()
        self.noterefs = 0

    # -- inline text
    def _inline(self, el, buf: list[str]) -> None:
        tag = _tag(el)
        if tag in SKIP or HIDDEN_RX.search(el.get("style", "")):
            return
        if tag == "br":
            buf.append("\n")
            return
        if PAGENUM_RX.search(_types(el)) and not _tc(el).strip().isalpha():
            return
        if tag in ("a", "sup"):
            txt = _tc(el)
            href = el.get("href") or ""
            is_ref = "noteref" in _types(el) or (tag == "a" and "#" in href and NOTEREF_TXT.match(txt)) or \
                (tag == "sup" and NOTEREF_TXT.match(txt) and el.find(".//a") is not None)
            if is_ref:
                self.noterefs += 1
                return
        if el.text:
            buf.append(el.text)
        for ch in el:
            if isinstance(ch.tag, str):
                self._inline(ch, buf)
            if ch.tail:
                buf.append(ch.tail)

    def emit(self, el, btype: str, ctx: dict, level: int | None = None) -> None:
        buf: list[str] = []
        if el.text:
            buf.append(el.text)
        for ch in el:
            if isinstance(ch.tag, str):
                self._inline(ch, buf)
            if ch.tail:
                buf.append(ch.tail)
        raw = "".join(buf)
        if btype in ("verse", "table"):
            text = "\n".join(WS.sub(" ", x).strip() for x in raw.split("\n"))
            text = re.sub(r"\n{2,}", "\n", text).strip()
        else:
            text = WS.sub(" ", raw.replace("\n", " ")).strip()
        if not text:
            return
        b = Block(btype, text, level=level)
        if ctx.get("role"):
            b.remove(ctx["reason"], ctx["role"])
        if ctx.get("code"):
            b.remove("code")
        self.blocks.append(b)

    # -- block structure
    def walk(self, el, ctx: dict | None = None) -> None:
        ctx = dict(ctx or {})
        tag = _tag(el)
        if not tag or tag in SKIP or HIDDEN_RX.search(el.get("style", "")) or el.get("hidden") is not None:
            return
        if el.get("id"):
            self.anchors.setdefault(el.get("id"), len(self.blocks))
        types = _types(el)
        if PAGENUM_RX.search(types) and not any(_tag(c) in BLOCKS for c in el):
            return
        for key, role, reason in ROLE_TYPES:
            if re.search(r"(^|\s|:)" + re.escape(key) + r"($|\s)", types) and not ctx.get("role"):
                ctx.update(role=role, reason=reason)
        if el.get("id") in ("pg-header", "pg-footer") and not ctx.get("role"):
            ctx.update(role="boilerplate", reason="gutenberg_licence")
        if tag == "nav" and not ctx.get("role"):
            ctx.update(role="toc", reason="toc")
        if VERSE_RX.search(types):
            ctx["verse"] = True
        if tag in ("aside", "section", "div", "li", "p", "dd", "ol") and (
                NOTE_RX.search(types) or NOTE_ID_RX.match(el.get("id") or "") or (el.get("id") in self.note_ids)):
            ctx["note"] = True
        if tag == "hr":
            self.blocks.append(Block("separator", ""))
            return
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.emit(el, "footnote" if ctx.get("note") else "heading", ctx, level=int(tag[1]))
            return
        if tag == "table":
            rows = [[WS.sub(" ", _tc(c)).strip() for c in tr if _tag(c) in ("td", "th")]
                    for tr in el.iter("tr", "{http://www.w3.org/1999/xhtml}tr")]
            if any(len(c) > 200 for r in rows for c in r):  # layout table (drama, poems): walk its cells
                for cell in el.iter("td", "th", "{http://www.w3.org/1999/xhtml}td"):
                    self.walk_container(cell, ctx)
                return
            text = "\n".join(" | ".join(r) for r in rows if any(r))
            if text:
                b = Block("table", text)
                if ctx.get("role"):
                    b.remove(ctx["reason"], ctx["role"])
                self.blocks.append(b)
            return
        if tag in ("figcaption", "caption"):
            self.emit(el, "caption", ctx)
            return
        if tag == "pre":
            self.emit(el, "paragraph", dict(ctx, code=True))
            return
        if tag in ("ul", "ol", "dl"):
            ctx["list_depth"] = ctx.get("list_depth", 0) + 1
        if tag == "blockquote":
            ctx["quote"] = True
        if any(_tag(c) in BLOCKS for c in el) or tag in ("body", "html"):
            self.walk_container(el, ctx)
            return
        if self.note_ids and not ctx.get("note"):
            # the note target is the block itself or an anchor at its very start (<p><a id="fn1">[1]</a> ...)
            first = next((c for c in el if isinstance(c.tag, str)), None)
            if first is not None and not (el.text or "").strip() and first.get("id") in self.note_ids \
                    and _tag(first) != "sup":
                ctx["note"] = True
        self.emit(el, self.leaf_type(tag, el, ctx), ctx, level=ctx.get("list_depth") if tag == "li" else None)

    def walk_container(self, el, ctx: dict) -> None:
        """Mixed content: loose inline runs between block children become paragraphs."""
        run: list = []

        def flush():
            if run and "".join(x if isinstance(x, str) else _tc(x) for x in run).strip():
                p = etree.Element("p")
                p.text = ""
                for x in run:
                    if isinstance(x, str):
                        if len(p):
                            p[-1].tail = (p[-1].tail or "") + x
                        else:
                            p.text += x
                    else:
                        p.append(x)
                self.emit(p, self.leaf_type("p", p, ctx), ctx)
            run.clear()
        if el.text and el.text.strip():
            run.append(el.text)
        for ch in list(el):
            if not isinstance(ch.tag, str):
                if ch.tail and ch.tail.strip():
                    run.append(ch.tail)
                continue
            if _tag(ch) in BLOCKS or _tag(ch) in ("h1", "h2", "h3", "h4", "h5", "h6"):
                flush()
                self.walk(ch, ctx)
                if ch.tail and ch.tail.strip():
                    run.append(ch.tail)
            else:
                import copy
                c2 = copy.deepcopy(ch)
                tail, c2.tail = c2.tail, None
                run.append(c2)
                if tail:
                    run.append(tail)
        flush()

    @staticmethod
    def leaf_type(tag: str, el, ctx: dict) -> str:
        if ctx.get("note"):
            return "footnote"
        if ctx.get("verse") or VERSE_RX.search(_types(el)):
            return "verse"
        brs = sum(1 for _ in el.iter("br", "{http://www.w3.org/1999/xhtml}br"))
        if brs >= 2:
            lines = [x for x in re.split(r"<br\s*/?>", etree.tostring(el, encoding="unicode")) if x.strip()]
            if lines and sum(len(re.sub("<[^>]+>", "", x).strip()) for x in lines) / len(lines) < 70:
                return "verse"
        if tag in ("li", "dt", "dd"):
            return "list_item"
        if ctx.get("quote"):
            return "blockquote"
        return "paragraph"


def html_to_blocks(root, note_ids: set[str] | None = None) -> tuple[list[Block], dict[str, int], int]:
    w = Walker(note_ids)
    body = root.find(".//body")
    if body is None:
        body = root.find(".//{http://www.w3.org/1999/xhtml}body")
    w.walk(body if body is not None else root)
    return w.blocks, w.anchors, w.noterefs


# ------------------------------------------------------------------------------------------------ documents
def _title(root) -> str | None:
    t = root.find(".//title")
    t = WS.sub(" ", t.text_content()).strip() if t is not None else ""
    og = root.xpath("string(//meta[@property='og:title']/@content)")
    h1 = root.find(".//h1")
    cand = og or (WS.sub(" ", h1.text_content()).strip() if h1 is not None else "") or t
    cand = re.split(r"\s+[—|–-]\s+(Wikipedia|Wikipédia|Википедия|Wikisource|Викитека|Vikipēdija)\b", cand)[0]
    return cand.strip()[:300] or None


def _book_like(root, text: str) -> bool:
    if re.search(r"project gutenberg", text[:20000], re.I):
        return True
    body = root.find(".//body")
    if body is None:
        return False
    total = len(WS.sub(" ", body.text_content()))
    links = sum(len(a.text_content()) for a in body.iter("a"))
    ptext = sum(len(p.text_content()) for p in body.iter("p"))
    navs = len(list(body.iter("nav"))) + len(body.xpath(".//header | .//footer | .//*[@role='navigation']"))
    return total > 0 and links / total < 0.08 and ptext / total > 0.6 and navs == 0


def _aozora(root, doc: Document) -> None:
    """Aozora Bunko XHTML: <div class="main_text"> with one paragraph per <br> line, ruby, metadata blocks."""
    mt = _by_class(root, "main_text")[0]
    a, t = _by_class(root, "author"), _by_class(root, "title")
    doc.author = a[0].text_content().strip() if a else None
    doc.title = t[0].text_content().strip() if t else doc.title
    doc.language = "ja"
    for part in re.split(r"<br\s*/?>", LH.tostring(mt, encoding="unicode")):
        frag = LH.fromstring("<p>" + part + "</p>")
        blocks, _, _ = html_to_blocks(frag)
        for b in blocks:
            b.text = b.text.strip("　 ")
            if b.text:
                doc.blocks.append(b)
    for el in _by_class(root, "bibliographical_information", "notation_notes", "after_text"):
        blocks, _, _ = html_to_blocks(LH.fromstring(LH.tostring(el)))
        for b in blocks:
            b.remove("aozora_colophon", "back_matter")
            doc.blocks.append(b)


def _shingles(text: str, cjk: bool) -> set[str]:
    if cjk:
        t = re.sub(r"\s+", "", text)
        return {t[i:i + 4] for i in range(max(1, len(t) - 3))}
    toks = re.findall(r"\w+", text.lower())
    if len(toks) < 3:
        return {" ".join(toks)} if toks else set()
    return {" ".join(toks[i:i + 3]) for i in range(len(toks) - 2)}


def _web_cleanup(doc: Document, raw_html: str) -> None:
    import trafilatura

    from app.ingest.formats.text import CITATION, CREDIT, END_HEADINGS, NAV_VOCAB, TERMINAL
    try:
        main = trafilatura.extract(raw_html, include_comments=False, include_tables=False, favor_recall=True) or ""
    except Exception:  # noqa: BLE001 - extraction is a vote; without it only the text rules apply
        main = ""
    audit = doc.audit
    if len(main) >= 200:
        cjk = bool(re.search(r"[぀-ヿ一-鿿]", main[:2000]))
        main_sh, main_norm = _shingles(main, cjk), WS.sub(" ", main).lower()
        for b in doc.blocks:
            if b.removed:
                continue
            sh = _shingles(b.text, cjk)
            if not (len(sh & main_sh) / max(1, len(sh)) >= 0.5 or
                    (len(b.text) < 60 and WS.sub(" ", b.text).lower().strip() in main_norm)):
                b.remove("web_chrome", "boilerplate")
                audit.add("L2", "web_chrome", example=b.text[:60])
    ended = False
    kept = [b for b in doc.blocks if b.readable]
    for i, b in enumerate(kept):
        t = b.text.strip()
        if not ended and b.type in ("heading", "paragraph") and len(t) < 60 and END_HEADINGS.match(t) and i > 2:
            ended = True
        if ended:
            b.remove("after_article_end", "back_matter")
        elif b.type in ("paragraph", "list_item", "caption") and len(t) < 400 and CITATION.search(t) \
                and re.search(r"\d{4}", t):
            b.remove("citation", "back_matter")
        elif b.type == "caption" or (len(t) < 160 and CREDIT.search(t) and not TERMINAL.search(t)):
            b.remove("caption_credit", "boilerplate")
        elif b.type == "table":
            b.remove("table", "boilerplate")
        elif WS.sub(" ", t.lower()) in NAV_VOCAB:
            b.remove("navigation", "boilerplate")
        else:
            continue
        audit.add("L2", b.removed, example=t[:60])


def parse_document(text: str, url: str | None = None, mode: str | None = None, source_format: str = "html") -> Document:
    """mode: "web" (article extraction), "book" (keep everything) or None (decide from the page)."""
    root = parse_html(text)
    doc = Document([], source_format, "lxml html walker", title=_title(root))
    lang = root.get("lang") or root.xpath("string(//html/@lang)") or \
        root.xpath("string(//meta[@http-equiv='content-language']/@content)")
    doc.language = lang or None
    if _by_class(root, "main_text"):
        _aozora(root, doc)
        doc.extractor = "aozora xhtml walker"
        return doc
    blocks, _, refs = html_to_blocks(root, noteref_targets(root))
    doc.blocks = blocks
    doc.audit.add("L0", "noteref_markers_dropped", refs)
    if (mode or ("book" if _book_like(root, text) else "web")) == "web":
        doc.extractor = "lxml html walker + trafilatura main-content vote + text rules"
        _web_cleanup(doc, text)
    return doc
