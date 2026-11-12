"""Reading units ("pages" of the reader) built from structure, not from PDF pages.

  * a new unit starts at every level-1/2 heading and at every navigation chapter (EPUB TOC target)
  * otherwise blocks are packed to ~TARGET characters, a unit closes before it would exceed MAX
  * a paragraph is never split unless it is longer than SPLIT; then only at sentence boundaries
  * verse stanzas and tables are never split; a heading never ends a unit
  * blocks that are not read (removed / non-body) stay in the unit where they occur, so the UI can restore them
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.ingest.ir import Block, Document

TARGET = 1600
MAX = 1800
SPLIT = 3000


@dataclass
class Unit:
    blocks: list[Block] = field(default_factory=list)
    title: str | None = None

    @property
    def chars(self) -> int:
        return sum(len(b.text) for b in self.blocks if b.readable)

    @property
    def text(self) -> str:
        """Body text (search, legacy clients): readable blocks separated by blank lines."""
        return "\n\n".join(b.text for b in self.blocks if b.readable)

    @property
    def source_pages(self) -> tuple[int | None, int | None]:
        pages = [p for b in self.blocks if b.readable for p in (b.source_page, b.source_page_end) if p]
        return (min(pages), max(pages)) if pages else (None, None)


def _split(b: Block) -> list[Block]:
    """Cut a very long paragraph at sentence boundaries into pieces of at most ~TARGET characters."""
    if len(b.text) <= SPLIT or b.type in ("verse", "table", "heading") or len(b.sentences) < 2:
        return [b]
    pieces, start, cur = [], 0, []
    for s, e in b.sentences:
        if cur and e - start > TARGET:
            pieces.append((start, cur[-1][1], cur))
            start, cur = s, []
        cur.append((s, e))
    pieces.append((start, cur[-1][1], cur))
    out = []
    for k, (a, z, sents) in enumerate(pieces):
        part = Block(b.type, b.text[a:z], level=b.level, role=b.role, removed=b.removed, source_page=b.source_page,
                     source_page_end=b.source_page_end, confidence=b.confidence, notes=list(b.notes),
                     sentences=[[s - a, e - a] for s, e in sents], id=b.id if k == 0 else f"{b.id}.{k + 1}",
                     chapter=b.chapter if k == 0 else None)
        out.append(part)
    return out


def unit_sentences(blocks: list[dict] | None, text: str = "") -> list[tuple[int, str, str]]:
    """Translation / TTS input of one stored unit: [(paragraph index, sentence, block id)] over the readable
    blocks (one paragraph per block; verse and table lines and headings are sentences of their own).
    Units stored before structured ingestion (blocks NULL) are segmented from their plain text."""
    if blocks is None:
        from app.ingest.pipeline import text_to_blocks
        blocks = text_to_blocks(text)
    out, para = [], -1
    for b in blocks:
        if b.get("role", "body") != "body" or b.get("removed") or b.get("type") == "separator" or not b.get("sentences"):
            continue
        para += 1
        out.extend((para, b["text"][s:e], b["id"]) for s, e in b["sentences"])
    return out


def build_units(doc: Document) -> list[Unit]:
    units: list[Unit] = []
    cur = Unit()
    title: str | None = None

    def only_headings(u: Unit) -> bool:
        return all(b.type == "heading" or not b.readable for b in u.blocks)

    def close():
        nonlocal cur
        if cur.blocks:
            units.append(cur)
        cur = Unit(title=title)

    for big in doc.blocks:
        for b in _split(big):
            if not b.readable:
                cur.blocks.append(b)
                continue
            chapter_start = b.chapter is not None or (b.type == "heading" and (b.level or 9) <= 2)
            if chapter_start:
                title = (b.chapter or b.text)[:200]
                if cur.chars and not only_headings(cur):
                    close()
                cur.title = cur.title if cur.chars and only_headings(cur) else title
            elif cur.chars and cur.chars + len(b.text) > MAX and cur.chars >= TARGET // 2:
                trailing = []  # a heading never ends a unit: carry trailing headings over
                while cur.blocks and cur.blocks[-1].type == "heading" and cur.blocks[-1].readable:
                    trailing.insert(0, cur.blocks.pop())
                if cur.chars:
                    close()
                cur.blocks = trailing + cur.blocks
            if cur.title is None:
                cur.title = title
            cur.blocks.append(b)
    if cur.blocks:
        if units and not cur.chars:
            units[-1].blocks.extend(cur.blocks)  # trailing removed blocks (licence, colophon) join the last unit
        else:
            units.append(cur)
    return units
