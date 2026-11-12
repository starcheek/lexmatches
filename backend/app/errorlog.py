"""Server-side problem log (table server_errors): failed API responses, unhandled exceptions, crashed jobs.

Logging must never break or slow the request it describes: every write is best-effort."""
import json
import logging
import time
import traceback
from uuid import UUID

import jwt
from fastapi import Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse, Response

from app import db
from app.config import settings

log = logging.getLogger("app.errors")

SKIP = ("/api/health", "/api/track")
MAX_BODY = 4000


def record(method: str, path: str, *, status: int | None = None, duration_ms: int | None = None,
           user_id: str | None = None, session_id: str | None = None, ip: str | None = None,
           detail: str | None = None, tb: str | None = None) -> None:
    try:
        db.execute(
            "INSERT INTO server_errors (method, path, status, duration_ms, user_id, session_id, ip, detail, traceback)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (method, path[:500], status, duration_ms, user_id, session_id, ip,
             detail[:MAX_BODY] if detail else None, tb[-12000:] if tb else None),
        )
    except Exception:
        log.exception("could not write server_errors row")


def record_job_failure(key: str, exc: BaseException) -> None:
    record("JOB", key, detail=f"{type(exc).__name__}: {exc}",
           tb="".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))


def _uuid(value: str | None) -> str | None:
    try:
        return str(UUID(value)) if value else None
    except ValueError:
        return None


def _user_id(request: Request) -> str | None:
    """Who made the request, from the token alone (no database lookup; an admin token is not a user)."""
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return None
    try:
        payload = jwt.decode(header[7:], settings.jwt_secret, algorithms=["HS256"], options={"verify_iat": False})
    except jwt.PyJWTError:
        return None
    return _uuid(payload.get("sub"))


def _detail(body: bytes) -> str:
    """FastAPI errors are {"detail": ...}; keep the message, fall back to the raw body."""
    text = body[:MAX_BODY].decode("utf-8", "replace")
    try:
        detail = json.loads(text).get("detail")
        return detail if isinstance(detail, str) else json.dumps(detail, ensure_ascii=False)
    except Exception:
        return text


async def middleware(request: Request, call_next):
    from app.routers.analytics import client_ip

    path = request.url.path
    if path in SKIP:
        return await call_next(request)
    started = time.monotonic()
    who = dict(user_id=_user_id(request), session_id=_uuid(request.headers.get("x-session")), ip=client_ip(request))
    try:
        response = await call_next(request)
    except Exception as exc:
        log.exception("unhandled error: %s %s", request.method, path)
        await run_in_threadpool(
            record, request.method, path, status=500, duration_ms=int((time.monotonic() - started) * 1000),
            detail=f"{type(exc).__name__}: {exc}", tb=traceback.format_exc(), **who)
        return JSONResponse({"detail": "Something went wrong on the server. It has been logged."}, status_code=500)
    if response.status_code < 400:
        return response
    # Error bodies are small: read the message the user got, then send the same response on.
    body = b"".join([chunk async for chunk in response.body_iterator])
    await run_in_threadpool(
        record, request.method, path, status=response.status_code,
        duration_ms=int((time.monotonic() - started) * 1000), detail=_detail(body), **who)
    headers = {k: v for k, v in response.headers.items() if k.lower() != "content-length"}
    return Response(content=body, status_code=response.status_code, headers=headers, media_type=response.media_type)
