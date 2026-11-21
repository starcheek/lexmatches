"""Owner tools behind the ADMIN_TOKEN bearer token (the /admin page): accounts and the sign-up switch, every
account's books (and sharing them), the server log."""
import logging
import secrets
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from app import auth, db, seed, serverlog, storage
from app.config import settings
from app.routers.analytics import admin
from app.routers.auth import Credentials

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(admin)])


def signup_open() -> bool:
    row = db.fetch_one("SELECT value FROM app_settings WHERE key = 'signup_open'")
    return True if row is None else bool(row["value"])


class NewUser(BaseModel):
    email: str
    password: str | None = None  # empty = generate one


class Password(BaseModel):
    password: str | None = None


class AppSettings(BaseModel):
    signup_open: bool


# Generated passwords are easy to read out and type on a phone: "maple-river-482" (128 x 128 x 900 ≈ 15 million).
_WORDS = """
apple amber anchor arrow autumn badge basil beach berry birch blue bloom breeze brick brook butter cabin camel
candle canyon cedar cherry cider cloud clover cocoa comet coral cotton crane daisy delta desert dolphin dove
dream eagle ember falcon fern field flame forest fox garden ginger glade grape harbor hazel honey island ivory
jade jasmine kettle kiwi lagoon lake lantern lemon lily lotus maple meadow melon mint moon morning moss nectar
night oak ocean olive orange orchid otter panda paper peach pearl pebble pepper pine planet plum pony quartz
rabbit rain raven reef river robin rose ruby saffron sage sand shell silver sky snow sparrow spring spruce star
stone storm sugar summer sun swan tiger tulip valley velvet violet walnut wave willow window winter wolf zebra
""".split()


def _password(given: str | None) -> str:
    """The owner's own choice (6+ characters: the owner picks it and passes it on), or an easy generated one."""
    password = (given or "").strip() or (
        f"{secrets.choice(_WORDS)}-{secrets.choice(_WORDS)}-{secrets.randbelow(900) + 100}")
    if not 6 <= len(password) <= 72:
        raise HTTPException(400, "Password must be 6-72 characters")
    return password


@router.get("/users")
def users():
    """Every account with what it has used: books, translated pages (the API cost), sessions, last visit."""
    return db.fetch_all(
        "SELECT u.id, u.email, u.created_at,"
        "  (SELECT count(*) FROM books b WHERE b.user_id = u.id) AS books,"
        "  (SELECT count(*) FROM pages p JOIN books b ON b.id = p.book_id"
        "    WHERE b.user_id = u.id AND p.translated_data IS NOT NULL) AS translated_pages,"
        "  (SELECT count(*) FROM analytics_sessions s WHERE s.user_id = u.id) AS sessions,"
        "  (SELECT max(s.last_seen_at) FROM analytics_sessions s WHERE s.user_id = u.id) AS last_seen,"
        "  (SELECT host(s.ip) FROM analytics_sessions s WHERE s.user_id = u.id ORDER BY s.last_seen_at DESC LIMIT 1) AS last_ip"
        " FROM users u ORDER BY u.created_at DESC"
    )


@router.post("/users", status_code=201)
def create_user(body: NewUser):
    """Create an account for a tester. The password is returned once, to pass on; only its hash is stored."""
    try:
        email = Credentials(email=body.email, password="-").email  # same rule as public sign-up
    except ValueError:
        raise HTTPException(422, "Invalid email address")
    password = _password(body.password)
    try:
        user = db.fetch_one(
            "INSERT INTO users (email, password_hash) VALUES (%s, %s) RETURNING id, email",
            (email, auth.hash_password(password)),
        )
    except psycopg.errors.UniqueViolation:
        raise HTTPException(409, "User already registered")
    seed.add_sample_books(user["id"])
    return {"id": str(user["id"]), "email": user["email"], "password": password}


@router.post("/users/{user_id}/password")
def reset_password(user_id: UUID, body: Password):
    password = _password(body.password)
    # token_version + 1: sessions signed in with the old password end
    if not db.execute("UPDATE users SET password_hash = %s, token_version = token_version + 1 WHERE id = %s",
                      (auth.hash_password(password), user_id)):
        raise HTTPException(404, "User not found")
    return {"password": password}


@router.delete("/users/{user_id}", status_code=204)
def delete_user(user_id: UUID):
    """Remove the account with its books, pages and progress (database cascade) and its stored files and audio."""
    if not db.execute("DELETE FROM users WHERE id = %s", (user_id,)):
        raise HTTPException(404, "User not found")
    try:
        s3 = storage.client()
        for prefix in (f"{user_id}/", f"tts/{user_id}/"):
            for page in s3.get_paginator("list_objects_v2").paginate(Bucket=settings.s3_bucket, Prefix=prefix):
                for obj in page.get("Contents", []):
                    s3.delete_object(Bucket=settings.s3_bucket, Key=obj["Key"])
    except Exception:
        pass  # the account is gone; orphaned files are unreachable (keys are per user)
    return Response(status_code=204)


@router.get("/books")
def books():
    """Every book with its owner and how much of it is translated (`translated`: the page numbers)."""
    return db.fetch_all(
        "SELECT b.id, b.user_id, u.email, b.title, b.author, b.original_locale, b.target_locale, b.status, b.error,"
        "  b.source_format, b.total_pages, b.last_read_page, b.created_at,"
        "  COALESCE(t.translated, '{}') AS translated, COALESCE(t.partial, 0) AS partial_pages"
        " FROM books b JOIN users u ON u.id = b.user_id"
        " LEFT JOIN LATERAL ("
        "   SELECT array_agg(p.page_number ORDER BY p.page_number)"
        "            FILTER (WHERE p.status = 'completed' AND p.translated_data IS NOT NULL) AS translated,"
        "          count(*) FILTER (WHERE p.status <> 'completed' AND p.translated_data IS NOT NULL) AS partial"
        "   FROM pages p WHERE p.book_id = b.id) t ON true"
        " ORDER BY b.created_at DESC"
    )


class Share(BaseModel):
    user_ids: list[UUID]


_BOOK_COPY = ("title, original_locale, target_locale, source, status, error, total_pages, glossary, source_format,"
              " author, detected_language, warnings, ingest")
_PAGE_COPY = ("page_number, original_text, blocks, translated_data, images, error, source_page_start,"
              " source_page_end, chapter_title")


@router.post("/books/{book_id}/share", status_code=201)
def share_book(book_id: UUID, body: Share):
    """Give other accounts their own copy of a book, with every translation made so far (nothing is translated
    or paid for again). Copies are independent: later translations and reading progress stay with each account."""
    book = db.fetch_one("SELECT id, user_id, status, source_format FROM books WHERE id = %s", (book_id,))
    if book is None:
        raise HTTPException(404, "Book not found")
    if book["status"] != "completed":
        raise HTTPException(409, "This book is not ready (still being processed, or it failed)")
    targets = list(dict.fromkeys(body.user_ids))
    if not targets:
        raise HTTPException(400, "Choose at least one account")
    found = db.fetch_all("SELECT id FROM users WHERE id = ANY(%s)", (targets,))
    if len(found) != len(targets):
        raise HTTPException(404, "User not found")
    copies = []
    for user_id in targets:
        with db.connection() as conn:
            new_id = conn.execute(
                f"INSERT INTO books (user_id, {_BOOK_COPY}) SELECT %s, {_BOOK_COPY} FROM books WHERE id = %s RETURNING id",
                (user_id, book_id),
            ).fetchone()["id"]
            # a page caught mid-translation has no job in the copy: it continues from what is stored when opened
            conn.execute(
                f"INSERT INTO pages (book_id, status, {_PAGE_COPY})"
                f" SELECT %s, CASE WHEN status = 'processing' THEN 'pending' ELSE status END, {_PAGE_COPY}"
                " FROM pages WHERE book_id = %s",
                (new_id, book_id),
            )
        try:  # the uploaded original (the PDF view needs it); pasted and imported texts have none
            source = storage.book_file_key(book["user_id"], book_id, book["source_format"])
            if storage.exists(source):
                storage.client().copy_object(
                    Bucket=settings.s3_bucket, Key=storage.book_file_key(user_id, new_id, book["source_format"]),
                    CopySource={"Bucket": settings.s3_bucket, "Key": source})
        except Exception:
            log.exception("could not copy the source file of book %s for user %s", book_id, user_id)
        copies.append({"user_id": str(user_id), "book_id": str(new_id)})
    return {"copies": copies}


@router.get("/logs")
def logs(limit: int = 500, level: str = "INFO", q: str | None = None, after: int = 0):
    """The server's newest log lines (kept in memory since the last restart), oldest first."""
    return {"started": serverlog.STARTED.isoformat(), "kept": serverlog.MAX_RECORDS,
            "lines": serverlog.read(limit, level, q, after)}


@router.get("/settings")
def get_settings():
    return {"signup_open": signup_open()}


@router.put("/settings")
def put_settings(body: AppSettings):
    db.execute(
        "INSERT INTO app_settings (key, value) VALUES ('signup_open', %s)"
        " ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()",
        (db.json(body.signup_open),),
    )
    return {"signup_open": body.signup_open}
