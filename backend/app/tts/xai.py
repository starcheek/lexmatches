"""Optional xAI (Grok) text-to-speech provider, enabled with TTS_PROVIDER=xai and XAI_API_KEY.

POST https://api.x.ai/v1/tts with `with_timestamps` returns base64 MP3 plus per-character timings, from which
the word timings for highlighting are derived. Billed per input character; the per-user cache in
app/tts/__init__.py means a page is paid for once per user.
"""
import base64
import time

import httpx

API_URL = "https://api.x.ai/v1/tts"
# xAI language codes (BCP-47). Every voice speaks every language; unlisted ones go as "auto".
LANG_CODES = {
    "en": "en", "fr": "fr", "de": "de", "ru": "ru", "it": "it", "ja": "ja", "ko": "ko", "zh": "zh", "tr": "tr",
    "vi": "vi", "hi": "hi", "id": "id", "bn": "bn", "es": "es-ES", "pt": "pt-PT", "ar": "ar-SA",
}
# "[pause]" and "<whisper>" are speech tags to the API: book text must not trigger them. One character for
# one character, so the timings still line up with the text.
_NO_TAGS = str.maketrans("[]<>", "()()")


def unit_times_from_graph(units: list[str], chars: list[str], times: list) -> list[tuple[float, float] | None]:
    """Word timings from the character timings. The API echoes the spoken characters in order; walking them
    by count of non-space characters keeps the words aligned even if spacing differs from what was sent."""
    out, g, n = [], 0, min(len(chars), len(times))
    for unit in units:
        need = sum(1 for c in unit if not c.isspace())
        start = end = None
        while need and g < n:
            if not chars[g].isspace():
                if start is None:
                    start = times[g][0]
                end = times[g][1]
                need -= 1
            g += 1
        out.append((round(start, 3), round(end, 3)) if start is not None and not need else None)
    return out


class XaiProvider:
    name = "xai"
    content_type = "audio/mpeg"

    def __init__(self, api_key: str, voice: str = "eve"):
        self.api_key = api_key
        self.voice = voice or "eve"

    def voice_for(self, lang: str, voice: str | None) -> str:
        # the language travels inside the voice id: synthesize() only gets the voice
        return voice or f"{self.voice}:{LANG_CODES.get(lang, 'auto')}"

    def status(self, voice: str) -> dict:
        return {"state": "ready"}

    def prepare(self, voice: str, load: bool = True) -> dict:
        return self.status(voice)

    def synthesize(self, units: list[str], voice: str) -> tuple[bytes, float, list[tuple[float, float] | None]]:
        voice_id, _, language = voice.partition(":")
        payload = {
            "text": " ".join(units).translate(_NO_TAGS),
            "voice_id": voice_id,
            "language": language or "auto",
            "with_timestamps": True,
            "output_format": {"codec": "mp3", "sample_rate": 24000, "bit_rate": 64000},
        }
        for attempt in range(3):  # 429 / 5xx are documented as retryable with backoff
            resp = httpx.post(API_URL, headers={"Authorization": f"Bearer {self.api_key}"}, json=payload, timeout=120)
            if resp.status_code == 200:
                break
            if resp.status_code not in (429, 500, 502, 503) or attempt == 2:
                raise RuntimeError(f"xAI TTS error {resp.status_code}: {resp.text[:200]}")
            time.sleep(1.5 * (attempt + 1))
        body = resp.json()
        stamps = body.get("audio_timestamps") or {}
        words = unit_times_from_graph(units, stamps.get("graph_chars") or [], stamps.get("graph_times") or [])
        return base64.b64decode(body["audio"]), round(float(body.get("duration") or 0.0), 3), words
