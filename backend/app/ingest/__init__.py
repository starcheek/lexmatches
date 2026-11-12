"""Ingestion: any supported book/file format, pasted text or URL -> structured, cleaned IR -> reading units.

Entry points: `ingest_file`, `ingest_text`, `ingest_url`, `apply_overrides` (pipeline.py) and `build_units`
(units.py). Errors are `IngestError` subclasses with a stable `code` and a user-facing message (ir.py).
See docs/ARCHITECTURE.md#ingestion.
"""
from app.ingest.ir import Block, Document, DRMProtected, FetchFailed, IngestError, NoText, UnsupportedFormat, URLBlocked
from app.ingest.pipeline import MAX_TEXT_CHARS, apply_overrides, ingest_file, ingest_text, ingest_url
from app.ingest.units import Unit, build_units

__all__ = ["Block", "Document", "IngestError", "UnsupportedFormat", "DRMProtected", "NoText", "FetchFailed",
           "URLBlocked", "ingest_file", "ingest_text", "ingest_url", "apply_overrides", "build_units", "Unit",
           "MAX_TEXT_CHARS"]
