"""Text-to-speech: provider selection, per-user cache, bounded synthesis pool.

Flow for one segment:  plan() (pure: voice, normalised units, cache key)
                    -> cached()  (S3 lookup, cheap, runs in the request threadpool)
                    -> submit()  (CPU-bound synthesis in a small pool, identical requests share one job)

Cache objects are per user and per book (product requirement: no shared generated artifacts):
    tts/<user_id>/<book_id | "misc">/<sha256>.mp3   audio
    tts/<user_id>/<book_id | "misc">/<sha256>.json  {duration, words, voice, provider, content_type}
Deleting a book deletes its prefix; a bucket lifecycle rule expires everything under tts/
after TTS_CACHE_DAYS (covers account removal and leftovers).
"""
import hashlib
import json
import logging
import re
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass

from app import storage
from app.config import settings
from app.languages import to_iso
from app.tts.piper import VoiceNotReady
from app.tts.text import speakable, spoken_units

log = logging.getLogger(__name__)

FORMAT_VERSION = "2"  # bump when audio encoding / timing semantics change
MAX_QUEUE = 32
SCOPE_RE = re.compile(r"^(misc|[0-9a-f-]{36})$")
NAME_RE = re.compile(r"^[0-9a-f]{64}\.mp3$")

__all__ = ["VoiceNotReady", "Unsupported", "Busy", "Clip", "plan", "cached", "submit", "voice_status",
           "delete_audio", "object_key", "start_background"]


class Unsupported(ValueError):
    """No server voice for this language (client falls back to the browser's speech)."""


class Busy(Exception):
    """Synthesis queue is full."""


@dataclass
class Clip:
    scope: str
    name: str
    content_type: str
    duration: float
    words: list  # per display token of the segment text: [start, end] seconds or None (silent token)
    voice: str
    provider: str
    cached: bool = False

    def public(self) -> dict:
        return {"audio_url": f"/api/tts/audio/{self.scope}/{self.name}", **asdict(self)}


@dataclass
class Plan:
    provider: object
    voice: str
    lang: str
    units: list[str]
    user_id: str
    scope: str
    name: str

    @property
    def key(self) -> str:
        return object_key(self.user_id, self.scope, self.name)


# ---- providers ------------------------------------------------------------------------------
_providers: dict = {}


def get_provider(name: str | None = None):
    name = (name or settings.tts_provider or "piper").lower()
    if name == "elevenlabs" and not settings.elevenlabs_api_key:
        name = "piper"
    if name == "grok":
        name = "xai"
    if name == "xai" and not settings.xai_api_key:
        name = "piper"
    if name not in _providers:
        if name == "xai":
            from app.tts.xai import XaiProvider

            _providers[name] = XaiProvider(settings.xai_api_key, settings.xai_voice)
        elif name == "elevenlabs":
            from app.tts.elevenlabs import ElevenLabsProvider

            _providers[name] = ElevenLabsProvider(settings.elevenlabs_api_key)
        else:
            from app.tts.piper import PiperProvider

            name = "piper"
            _providers.setdefault(name, PiperProvider(settings.piper_voices_dir, settings.piper_voices))
    return _providers[name]


def set_provider(name: str, provider) -> None:
    """Test hook."""
    if provider is None:
        _providers.pop(name, None)
    else:
        _providers[name] = provider


# ---- planning / cache -------------------------------------------------------------------------
def object_key(user_id, scope: str, name: str) -> str:
    return f"tts/{user_id}/{scope}/{name}"


def plan(text: str, language: str | None, *, user_id, scope: str = "misc", voice: str | None = None,
         provider: str | None = None) -> Plan:
    prov = get_provider(provider)
    lang = to_iso(language)
    try:
        voice_id = prov.voice_for(lang, voice)
    except ValueError as e:
        raise Unsupported(str(e)) from None
    units = spoken_units(text, lang)
    if not any(speakable(u) for u in units):
        raise ValueError("Nothing to read aloud in this text")
    variant = f"{settings.piper_length_scale}" if prov.name == "piper" else ""
    digest = hashlib.sha256(
        "\x00".join([FORMAT_VERSION, prov.name, voice_id, variant, lang, "\x1f".join(units)]).encode()
    ).hexdigest()
    return Plan(prov, voice_id, lang, units, str(user_id), scope, f"{digest}.mp3")


def cached(p: Plan) -> Clip | None:
    meta = storage.get(p.key + ".json")  # written after the audio, so its presence implies the audio
    if meta is None:
        return None
    return Clip(**json.loads(meta), scope=p.scope, name=p.name, cached=True)


def _render(p: Plan) -> Clip:
    spoken = [u for u in p.units if u]
    audio, duration, times = p.provider.synthesize(spoken, p.voice)
    it = iter(times)
    words = [None if not u else (list(t) if (t := next(it)) else None) for u in p.units]
    meta = {"content_type": p.provider.content_type, "duration": duration, "words": words,
            "voice": p.voice, "provider": p.provider.name}
    storage.put(p.key, audio, p.provider.content_type)
    storage.put(p.key + ".json", json.dumps(meta).encode(), "application/json")
    return Clip(**meta, scope=p.scope, name=p.name)


# ---- bounded synthesis pool with request coalescing ------------------------------------------------
_pool: ThreadPoolExecutor | None = None
_inflight: dict[str, Future] = {}
_inflight_lock = threading.Lock()


def submit(p: Plan) -> Future:
    """Queue synthesis; concurrent identical requests (prefetch + click) share one job."""
    global _pool
    with _inflight_lock:
        if p.key in _inflight:
            return _inflight[p.key]
        if len(_inflight) >= MAX_QUEUE:
            raise Busy()
        if _pool is None:
            _pool = ThreadPoolExecutor(max_workers=max(1, settings.tts_workers), thread_name_prefix="tts")
        fut = _pool.submit(_render, p)
        _inflight[p.key] = fut

    def _done(_f, key=p.key):
        with _inflight_lock:
            _inflight.pop(key, None)

    fut.add_done_callback(_done)
    return fut


# ---- voices ---------------------------------------------------------------------------------------
def voice_status(language: str | None, provider: str | None = None) -> dict:
    """Status of the voice for a language; starts downloading/loading it in the background."""
    prov = get_provider(provider)
    lang = to_iso(language)
    try:
        voice = prov.voice_for(lang, None)
    except ValueError:
        return {"language": lang, "provider": prov.name, "voice": None, "state": "unavailable"}
    return {"language": lang, "provider": prov.name, "voice": voice, **prov.prepare(voice)}


# ---- deletion / housekeeping -------------------------------------------------------------------------
def _delete_prefix(prefix: str) -> int:
    s3, deleted = storage.client(), 0
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=settings.s3_bucket, Prefix=prefix):
        keys = [{"Key": o["Key"]} for o in page.get("Contents", [])]
        if keys:
            s3.delete_objects(Bucket=settings.s3_bucket, Delete={"Objects": keys, "Quiet": True})
            deleted += len(keys)
    return deleted


def delete_audio(user_id, scope: str | None = None) -> int:
    """Delete a user's cached audio for one book (scope) or all of it (account removal)."""
    return _delete_prefix(f"tts/{user_id}/" + (f"{scope}/" if scope else ""))


def _housekeeping() -> None:
    s3 = storage.client()
    try:
        s3.put_bucket_lifecycle_configuration(
            Bucket=settings.s3_bucket,
            LifecycleConfiguration={"Rules": [{
                "ID": "tts-cache-expiry", "Status": "Enabled", "Filter": {"Prefix": "tts/"},
                "Expiration": {"Days": max(1, settings.tts_cache_days)},
            }]},
        )
    except Exception as e:
        log.warning("could not set TTS cache lifecycle rule: %s", e)
    try:  # pre-per-user cache layout (tts/<sha>.wav, shared by all users): remove
        legacy = s3.list_objects_v2(Bucket=settings.s3_bucket, Prefix="tts/", Delimiter="/").get("Contents", [])
        if legacy:
            s3.delete_objects(Bucket=settings.s3_bucket, Delete={"Objects": [{"Key": o["Key"]} for o in legacy]})
            log.info("deleted %d legacy shared TTS cache objects", len(legacy))
    except Exception as e:
        log.warning("legacy TTS cache cleanup failed: %s", e)

    prov = get_provider()
    pre = settings.piper_preload.lower()
    if prov.name != "piper" or pre in ("", "none"):
        return
    langs = list(prov.voices) if pre == "all" else [x.strip() for x in pre.split(",") if x.strip()]
    for lang in langs:  # sequential, files only (models load on first use / prepare)
        try:
            voice = prov.voice_for(lang, None)
            prov.prepare(voice, load=False)
            prov.wait(voice)
        except Exception as e:
            log.warning("preloading voice for %s failed: %s", lang, e)


def start_background() -> None:
    threading.Thread(target=_housekeeping, name="tts-housekeeping", daemon=True).start()
