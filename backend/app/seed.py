"""Sample books every new account starts with (backend/seed/).

Only public-domain source text is seeded. Each account gets its own copy, added like an upload, so the
translations and audio made from it stay per user and the owner can delete it like any other book.
"""
import logging
from pathlib import Path

from app.config import settings
from app.ingest import IngestError
from app.ingest.pipeline import precheck
from app.services.processing import create_uploaded_book

log = logging.getLogger(__name__)
SEED_DIR = Path(__file__).resolve().parent.parent / "seed"
# (title, file in backend/seed, language of the text, language it is read in)
BOOKS = [
    ("French Short Stories", "french-short-stories.html", "french", "english"),
]


def add_sample_books(user_id) -> None:
    """Never fails: a missing or broken sample must not block account creation."""
    if not settings.seed_books:
        return
    for title, name, original, target in BOOKS:
        try:
            data = (SEED_DIR / name).read_bytes()
            create_uploaded_book(user_id, title, original, target, data, precheck(data))
        except (OSError, IngestError):
            log.exception("sample book %s was not added for user %s", name, user_id)
