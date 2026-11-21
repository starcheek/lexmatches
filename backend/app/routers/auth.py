import logging
import re

import httpx
import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from app import auth, db, seed
from app.config import settings
from app.routers.analytics import client_ip

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])
TURNSTILE_VERIFY = "https://challenges.cloudflare.com/turnstile/v0/siteverify"

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class Credentials(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        v = v.strip()
        if not EMAIL_RE.match(v) or len(v) > 255:
            raise ValueError("Invalid email address")
        return v


class Signup(Credentials):
    captcha: str | None = Field(default=None, max_length=4096)  # Cloudflare Turnstile response token


def _user_out(user: dict) -> dict:
    return {"id": str(user["id"]), "email": user["email"], "created_at": user["created_at"].isoformat()}


def _captcha_ok(token: str | None, ip: str | None) -> bool:
    """Cloudflare Turnstile server-side check. Always true while TURNSTILE_SECRET_KEY is not set."""
    if not settings.turnstile_secret_key:
        return True
    if not token:
        return False
    try:
        r = httpx.post(TURNSTILE_VERIFY, timeout=10, data={
            "secret": settings.turnstile_secret_key, "response": token, **({"remoteip": ip} if ip else {})})
        return bool(r.json().get("success"))
    except Exception:
        log.exception("turnstile verification failed")
        return False


@router.get("/config")
def auth_config():
    """What the sign-in page needs before the user acts: whether sign-up is open and the captcha site key."""
    from app.routers.admin import signup_open

    return {"signup_open": signup_open(), "turnstile_site_key": settings.turnstile_site_key or None}


@router.post("/signup")
def signup(body: Signup, request: Request):
    from app.routers.admin import signup_open  # admin imports Credentials from this module

    if not signup_open():
        raise HTTPException(403, "Sign-up is closed. Ask the owner for a test account.")
    if not 8 <= len(body.password) <= 72:
        raise HTTPException(400, "Password must be 8-72 characters")
    if not _captcha_ok(body.captcha, client_ip(request)):
        raise HTTPException(400, "Captcha check failed. Please try again.")
    try:
        user = db.fetch_one(
            "INSERT INTO users (email, password_hash) VALUES (%s, %s) RETURNING id, email, created_at",
            (body.email, auth.hash_password(body.password)),
        )
    except psycopg.errors.UniqueViolation:
        raise HTTPException(409, "User already registered")
    seed.add_sample_books(user["id"])
    return {"token": auth.create_token(user["id"]), "user": _user_out(user)}


@router.post("/login")
def login(body: Credentials):
    user = db.fetch_one(
        "SELECT id, email, created_at, password_hash, token_version FROM users WHERE lower(email) = lower(%s)",
        (body.email,),
    )
    if not auth.verify_or_waste(user["password_hash"] if user else None, body.password):
        raise HTTPException(401, "Invalid login credentials")
    return {"token": auth.create_token(user["id"], user["token_version"]), "user": _user_out(user)}


@router.get("/me")
def me(user: dict = Depends(auth.current_user)):
    return _user_out(user)
