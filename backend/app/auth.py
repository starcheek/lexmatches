"""Email + password auth: argon2 hashes, HS256 JWT bearer tokens."""
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app import db
from app.config import settings

_hasher = PasswordHasher()
_bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


# Verified when the account does not exist, so a failed login takes as long either way (no account probing).
_DUMMY_HASH = _hasher.hash("no-such-account-placeholder")


def verify_or_waste(password_hash: str | None, password: str) -> bool:
    if password_hash is None:
        verify_password(_DUMMY_HASH, password)
        return False
    return verify_password(password_hash, password)


def create_token(user_id: str, version: int = 0) -> str:
    """`ver` is users.token_version: bumping it (password reset) invalidates every token issued before."""
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user_id), "ver": int(version), "iat": now,
               "exp": now + timedelta(hours=settings.jwt_ttl_hours)}
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def current_user(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> dict:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required")
    try:
        # iat is not verified: a token issued "in the future" only means the server clock was stepped
        # back (seen under Docker Desktop / WSL), and rejecting it logs the user out mid-session.
        payload = jwt.decode(creds.credentials, settings.jwt_secret, algorithms=["HS256"],
                             options={"verify_iat": False})
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired session")
    user = db.fetch_one("SELECT id, email, full_name, created_at, token_version FROM users WHERE id = %s",
                        (payload.get("sub"),))
    # tokens from before token_version existed carry no "ver": they count as version 0
    if user is None or payload.get("ver", 0) != user.pop("token_version"):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired session")
    return user
