"""Optional ElevenLabs provider (enabled only when ELEVENLABS_API_KEY is set).

Uses the `/with-timestamps` endpoint, whose character alignment gives word timings.
Not exercised against the live API in tests (no key); the response parsing is unit-tested.
"""
import base64

import httpx

VOICE_MAP = {
    "en": "9BWtsMINqrJLrRacOk9x",  # Aria
    "fr": "JBFqnCBsd6RMkjVDRZzb",  # George (multilingual)
    "pt": "Xb7hH8MSUJpSbSDYk0k2",  # Alice
    "ru": "JBFqnCBsd6RMkjVDRZzb",
    "ja": "SAz9YHcvj6GT2YYXdXww",  # River
    "lv": "XB0fDUnXU5powFXDhCwa",  # Charlotte
}


def unit_times_from_alignment(units: list[str], alignment: dict) -> tuple[list[tuple[float, float] | None], float]:
    starts = alignment.get("character_start_times_seconds") or []
    ends = alignment.get("character_end_times_seconds") or []
    times, pos = [], 0
    for unit in units:  # the request text is " ".join(units): unit u spans [pos, pos+len)
        a, b = pos, min(pos + len(unit), len(starts)) - 1
        times.append((round(starts[a], 3), round(ends[b], 3)) if 0 <= a <= b < len(ends) else None)
        pos += len(unit) + 1
    return times, round(ends[-1], 3) if ends else 0.0


class ElevenLabsProvider:
    name = "elevenlabs"
    content_type = "audio/mpeg"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def voice_for(self, lang: str, voice: str | None) -> str:
        return voice or VOICE_MAP.get(lang, VOICE_MAP["en"])

    def status(self, voice: str) -> dict:
        return {"state": "ready"}

    def prepare(self, voice: str, load: bool = True) -> dict:
        return self.status(voice)

    def synthesize(self, units: list[str], voice: str) -> tuple[bytes, float, list[tuple[float, float] | None]]:
        resp = httpx.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice}/with-timestamps",
            params={"output_format": "mp3_44100_64"},
            headers={"xi-api-key": self.api_key},
            json={
                "text": " ".join(units),
                "model_id": "eleven_turbo_v2_5",
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
            },
            timeout=60,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"ElevenLabs API error: {resp.status_code}")
        body = resp.json()
        times, duration = unit_times_from_alignment(units, body.get("alignment") or {})
        return base64.b64decode(body["audio_base64"]), duration, times
