"""Shared intermediate representation (IR) of every ingested document, plus typed errors.

    {"meta": {"title", "author", "language", "source_format", "extractor", "warnings": [{code, message, pages?}],
              "route_to_ocr", "ocr_pages"},
     "blocks": [{"id", "type", "level", "role", "text", "sentences": [[start, end]], "source_page",
                 "source_page_end", "confidence", "removed": null | reason, "notes": []}]}

`type`: heading | paragraph | list_item | blockquote | verse | footnote | caption | table | separator.
`role`: body | toc | boilerplate | front_matter | back_matter. Only body blocks that are not `removed` are read,
translated and spoken (`Block.readable`); everything else is kept so the UI can show and restore it.
`sentences` are character offsets into `text` (verse and tables: one span per line).
"""
from __future__ import annotations

from dataclasses import dataclass, field

BLOCK_TYPES = ("heading", "paragraph", "list_item", "blockquote", "verse", "footnote", "caption", "table", "separator")
ROLES = ("body", "toc", "boilerplate", "front_matter", "back_matter")


class IngestError(Exception):
    """User-facing ingestion failure; `code` is stable for clients, the message is shown to the user."""
    code = "ingest_failed"
    status = 400


class UnsupportedFormat(IngestError):
    code = "unsupported_format"
    status = 415


class DRMProtected(IngestError):
    code = "drm_protected"
    status = 422

    def __init__(self, scheme: str, detail: str):
        self.scheme = scheme
        super().__init__(f"This book is protected by DRM ({scheme}). Only DRM-free files can be imported: "
                         f"please use a DRM-free edition (e.g. Project Gutenberg, Standard Ebooks, or a shop that "
                         f"sells DRM-free books). [{detail}]")


class NoText(IngestError):
    code = "no_text"
    status = 422


class FetchFailed(IngestError):
    code = "fetch_failed"
    status = 422


class URLBlocked(FetchFailed):
    code = "url_blocked"
    status = 400


@dataclass(eq=False)
class Block:
    type: str
    text: str
    level: int | None = None
    role: str = "body"
    removed: str | None = None
    source_page: int | None = None
    source_page_end: int | None = None
    confidence: float = 1.0
    notes: list = field(default_factory=list)
    sentences: list = field(default_factory=list)
    id: str = ""
    chapter: str | None = None  # working only: TOC title when this block starts a navigation chapter

    @property
    def readable(self) -> bool:
        return self.role == "body" and self.removed is None and self.type != "separator" and bool(self.text.strip())

    def remove(self, reason: str, role: str | None = None) -> None:
        if role:
            self.role = role
        if self.removed is None:
            self.removed = reason

    def to_json(self) -> dict:
        return {"id": self.id, "type": self.type, "level": self.level, "role": self.role, "text": self.text,
                "sentences": self.sentences, "source_page": self.source_page,
                "source_page_end": self.source_page_end if self.source_page_end != self.source_page else None,
                "confidence": round(self.confidence, 2), "removed": self.removed, "notes": self.notes}


class Audit:
    """What every level changed: {level: {rule: count}} plus a few examples per rule (for support/debugging)."""

    def __init__(self, examples: int = 3):
        self.counts: dict[str, dict[str, int]] = {}
        self.examples: dict[str, list[str]] = {}
        self._cap = examples

    def add(self, level: str, rule: str, n: int = 1, example: str | None = None) -> None:
        if n <= 0:
            return
        d = self.counts.setdefault(level, {})
        d[rule] = d.get(rule, 0) + n
        if example:
            ex = self.examples.setdefault(f"{level}.{rule}", [])
            if len(ex) < self._cap:
                ex.append(example[:120])

    def to_json(self) -> dict:
        return {"counts": self.counts, "examples": self.examples}


@dataclass
class Document:
    blocks: list[Block]
    source_format: str
    extractor: str
    title: str | None = None
    author: str | None = None
    language: str | None = None          # ISO 639-1 used for segmentation
    language_detected: str | None = None
    language_score: float = 0.0
    warnings: list = field(default_factory=list)
    route_to_ocr: bool = False
    ocr_pages: list = field(default_factory=list)
    page_count: int | None = None
    audit: Audit = field(default_factory=Audit)

    def warn(self, code: str, message: str, **extra) -> None:
        if not any(w["code"] == code and w["message"] == message for w in self.warnings):
            self.warnings.append({"code": code, "message": message, **extra})

    def renumber(self) -> None:
        for i, b in enumerate(self.blocks):
            b.id = f"b{i + 1}"

    def meta(self) -> dict:
        return {"title": self.title, "author": self.author, "language": self.language,
                "language_detected": self.language_detected, "language_score": round(self.language_score, 3),
                "source_format": self.source_format, "extractor": self.extractor, "warnings": self.warnings,
                "route_to_ocr": self.route_to_ocr, "ocr_pages": self.ocr_pages, "page_count": self.page_count}

    def to_json(self) -> dict:
        return {"meta": self.meta(), "blocks": [b.to_json() for b in self.blocks], "audit": self.audit.to_json()}
