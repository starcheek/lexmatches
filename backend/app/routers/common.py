"""Ownership checks (replace the former RLS policies) and row serializers."""
from uuid import UUID

from fastapi import HTTPException

from app import db
from app.translation.pipeline import page_progress

BOOK_FIELDS = (
    "id, user_id, title, original_locale, target_locale, source, status, error, total_pages,"
    " last_read_page, created_at, updated_at, source_format, author, detected_language, warnings"
)
PAGE_FIELDS = (
    "id, book_id, page_number, original_text, blocks, translated_data, images, status, error,"
    " created_at, updated_at, source_page_start, source_page_end, chapter_title"
)


def owned_book(book_id: UUID, user: dict) -> dict:
    book = db.fetch_one(f"SELECT {BOOK_FIELDS} FROM books WHERE id = %s AND user_id = %s", (book_id, user["id"]))
    if book is None:
        raise HTTPException(404, "Book not found")
    return book


def owned_page(page_id: UUID, user: dict) -> dict:
    page = db.fetch_one(
        f"SELECT {', '.join('p.' + f.strip() for f in PAGE_FIELDS.split(','))}"
        " FROM pages p JOIN books b ON b.id = p.book_id WHERE p.id = %s AND b.user_id = %s",
        (page_id, user["id"]),
    )
    if page is None:
        raise HTTPException(404, "Page not found")
    return page


def book_out(book: dict) -> dict:
    out = {k: v for k, v in book.items() if k != "user_id"}
    for k in ("id",):
        out[k] = str(out[k])
    for k in ("created_at", "updated_at"):
        out[k] = out[k].isoformat()
    return out


def page_out(page: dict) -> dict:
    out = dict(page)
    out["id"] = str(out["id"])
    out["book_id"] = str(out["book_id"])
    for k in ("created_at", "updated_at"):
        out[k] = out[k].isoformat()
    out["progress"] = page_progress(page)
    return out
