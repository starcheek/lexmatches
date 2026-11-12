"""TTS endpoints.

POST /api/tts            {text, language?, book_id?, voice?, provider?} -> clip metadata (JSON)
GET  /api/tts/audio/...  the clip's audio (immutable, per user)
POST /api/tts/prepare    {language} -> voice status; starts downloading/loading the voice
"""
import asyncio
import threading
import time
from collections import defaultdict, deque
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from app import auth, storage, tts
from app.config import settings
from app.routers.common import owned_book

router = APIRouter(prefix="/api/tts", tags=["tts"])


class TTSRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    language: str | None = Field(default=None, max_length=32)
    book_id: UUID | None = None  # cache scope: deleted with the book
    voice: str | None = Field(default=None, max_length=100)
    provider: str | None = Field(default=None, max_length=20)


class PrepareRequest(BaseModel):
    language: str | None = Field(default=None, max_length=32)
    provider: str | None = Field(default=None, max_length=20)


class _RateLimiter:
    """Sliding one-minute window per user (in-process; single api instance)."""

    def __init__(self):
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, user_id: str) -> None:
        now, limit = time.monotonic(), settings.tts_rate_per_min
        with self._lock:
            hits = self._hits[user_id]
            while hits and now - hits[0] > 60:
                hits.popleft()
            if len(hits) >= limit:
                retry = max(1, int(60 - (now - hits[0])) + 1)
                raise HTTPException(429, "Too many speech requests, slow down", headers={"Retry-After": str(retry)})
            hits.append(now)


limiter = _RateLimiter()


def _unavailable(detail: str, retry_after: int) -> JSONResponse:
    return JSONResponse({"detail": detail}, status_code=503, headers={"Retry-After": str(retry_after)})


@router.post("")
async def text_to_speech(body: TTSRequest, user: dict = Depends(auth.current_user)):
    """Synthesize (or fetch from cache) one segment. Returns metadata; fetch `audio_url` for the audio.

    `words[i]` = [start, end] seconds of the i-th whitespace-separated token of `text` (null = silent).
    404 = no server voice for the language (use the browser's speech), 400 = nothing speakable,
    422 = invalid request (e.g. text > 2000 chars: split it), 503 = voice still downloading or
    queue full (honour Retry-After), 429 = per-user rate limit.
    """
    limiter.check(str(user["id"]))
    scope = "misc"
    if body.book_id:
        await run_in_threadpool(owned_book, body.book_id, user)
        scope = str(body.book_id)
    try:
        plan = tts.plan(body.text.strip(), body.language, user_id=user["id"], scope=scope,
                        voice=body.voice, provider=body.provider)
    except tts.Unsupported as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))

    clip = await run_in_threadpool(tts.cached, plan)
    if clip is None:
        try:
            clip = await asyncio.wrap_future(tts.submit(plan))
        except tts.VoiceNotReady:
            return _unavailable("Preparing voice", 3)
        except tts.Busy:
            return _unavailable("Speech synthesis is busy", 2)
        except Exception as e:
            raise HTTPException(502, f"TTS failed: {e}")
    return clip.public()


@router.get("/audio/{scope}/{name}")
def audio(scope: str, name: str, request: Request, user: dict = Depends(auth.current_user)):
    if not tts.SCOPE_RE.match(scope) or not tts.NAME_RE.match(name):
        raise HTTPException(404, "Not found")
    etag = f'"{name.split(".")[0][:32]}"'
    headers = {"Cache-Control": "private, max-age=31536000, immutable", "ETag": etag}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    data = storage.get(tts.object_key(user["id"], scope, name))
    if data is None:
        raise HTTPException(404, "Not found")
    return Response(data, media_type="audio/mpeg", headers=headers)


@router.post("/prepare")
def prepare(body: PrepareRequest, user: dict = Depends(auth.current_user)):
    """{language, provider, voice, state: ready|loading|downloading|missing|error|unavailable, progress?}"""
    return tts.voice_status(body.language, body.provider)
