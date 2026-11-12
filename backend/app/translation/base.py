"""Translator seam.

A Translator turns one chunk (consecutive sentences of a page, plus read-only context and the
book glossary) into, per sentence, a natural translation `t` and learner chunks `u`:

    translate(Chunk(["Le chat dort."], [0], "fr", "en"))
    -> ChunkResult([{"t": "The cat is sleeping.", "u": [["Le chat", "the cat"], ["dort.", "sleeps."]]}], {})

Implementations only talk to the model. Alignment repair, the single retry, glossary merging
and persistence live in `pipeline.py` so every implementation gets the same guarantees.
"""
from dataclasses import dataclass, field
from typing import Protocol


class TranslatorError(Exception):
    """Failure of one model call (bad output, API error)."""


class RateLimited(TranslatorError):
    def __init__(self, message: str = "Rate limit exceeded", retry_after: float = 0.0):
        super().__init__(message)
        self.retry_after = retry_after


@dataclass
class Chunk:
    sentences: list[str]
    paragraphs: list[int]          # paragraph number of each sentence (blank line between paragraphs)
    source_locale: str
    target_locale: str
    glossary: dict[str, str] = field(default_factory=dict)
    context: str = ""              # preceding source text, read-only
    context_translation: str = ""  # its translation, when already known


@dataclass
class ChunkResult:
    sentences: list[dict]          # [{"t": str, "u": [[source_chunk, gloss], ...]}], one per input sentence
    glossary: dict[str, str]       # new terms the model reports: source -> rendering


class Translator(Protocol):
    name: str

    def translate(self, chunk: Chunk) -> ChunkResult:
        ...
