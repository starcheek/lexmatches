"""Owner tools behind the ADMIN_TOKEN bearer token (the /admin page): test accounts and the sign-up switch."""
import secrets
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from app import auth, db, storage
from app.config import settings
from app.routers.analytics import admin
from app.routers.auth import Credentials

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


def _password(given: str | None) -> str:
    password = given or secrets.token_urlsafe(9)
    if not 8 <= len(password) <= 72:
        raise HTTPException(400, "Password must be 8-72 characters")
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
    return {"id": str(user["id"]), "email": user["email"], "password": password}


@router.post("/users/{user_id}/password")
def reset_password(user_id: UUID, body: Password):
    password = _password(body.password)
    if not db.execute("UPDATE users SET password_hash = %s WHERE id = %s", (auth.hash_password(password), user_id)):
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
