"""Reading sessions (translation-toggle tracking) and the progress page data."""
import re
from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from uuid import UUID

from app import auth, db
from app.routers.common import owned_book

router = APIRouter(prefix="/api", tags=["progress"])

WORD_RE = re.compile(r"(?:[^\W_]|['’-])+")


def count_words(text: str | None) -> int:
    return len(WORD_RE.findall(text or ""))


class SessionUpsert(BaseModel):
    book_id: UUID
    page_number: int = Field(ge=1)
    translation_toggle_clicks: int = Field(ge=0)
    session_date: date | None = None


@router.post("/reading-sessions")
def upsert_session(body: SessionUpsert, user: dict = Depends(auth.current_user)):
    owned_book(body.book_id, user)
    db.execute(
        "INSERT INTO reading_sessions (user_id, book_id, page_number, session_date, translation_toggle_clicks)"
        " VALUES (%s, %s, %s, %s, %s)"
        " ON CONFLICT (user_id, book_id, page_number, session_date)"
        " DO UPDATE SET translation_toggle_clicks = EXCLUDED.translation_toggle_clicks",
        (user["id"], body.book_id, body.page_number, body.session_date or date.today(), body.translation_toggle_clicks),
    )
    return {"ok": True}


@router.get("/progress")
def progress(user: dict = Depends(auth.current_user)):
    books = db.fetch_all(
        "SELECT id, title, total_pages FROM books WHERE user_id = %s ORDER BY created_at DESC", (user["id"],)
    )
    sessions = db.fetch_all(
        "SELECT s.book_id, s.page_number, s.translation_toggle_clicks, p.original_text"
        " FROM reading_sessions s LEFT JOIN pages p ON p.book_id = s.book_id AND p.page_number = s.page_number"
        " WHERE s.user_id = %s ORDER BY s.page_number",
        (user["id"],),
    )
    return {
        "books": [{"id": str(b["id"]), "title": b["title"], "total_pages": b["total_pages"]} for b in books],
        "sessions": [
            {
                "book_id": str(s["book_id"]),
                "page_number": s["page_number"],
                "translation_toggle_clicks": s["translation_toggle_clicks"],
                "words": count_words(s["original_text"]),
            }
            for s in sessions
        ],
    }
