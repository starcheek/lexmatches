import re

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from app import auth, db, seed

router = APIRouter(prefix="/api/auth", tags=["auth"])

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


def _user_out(user: dict) -> dict:
    return {"id": str(user["id"]), "email": user["email"], "created_at": user["created_at"].isoformat()}


@router.post("/signup")
def signup(body: Credentials):
    from app.routers.admin import signup_open  # admin imports Credentials from this module

    if not signup_open():
        raise HTTPException(403, "Sign-up is closed. Ask the owner for a test account.")
    if not 8 <= len(body.password) <= 72:
        raise HTTPException(400, "Password must be 8-72 characters")
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
        "SELECT id, email, created_at, password_hash FROM users WHERE lower(email) = lower(%s)", (body.email,)
    )
    if user is None or not auth.verify_password(user["password_hash"], body.password):
        raise HTTPException(401, "Invalid login credentials")
    return {"token": auth.create_token(user["id"]), "user": _user_out(user)}


@router.get("/me")
def me(user: dict = Depends(auth.current_user)):
    return _user_out(user)
