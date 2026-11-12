import base64

import pytest

from app.tts import xai
from app.tts.xai import XaiProvider, unit_times_from_graph


def _graph(text: str, step: float = 0.1):
    return list(text), [[round(i * step, 3), round((i + 1) * step, 3)] for i in range(len(text))]


def test_word_times_from_character_times():
    chars, times = _graph("Le chat dort.")
    assert unit_times_from_graph(["Le", "chat", "dort."], chars, times) == [(0.0, 0.2), (0.3, 0.7), (0.8, 1.3)]
    # spacing that differs from what was sent does not shift the words
    chars, times = _graph("Le  chat dort.")
    assert unit_times_from_graph(["Le", "chat", "dort."], chars, times)[1] == (0.4, 0.8)
    # timings that end early leave the remaining words without a span instead of a wrong one
    chars, times = _graph("Le ch")
    assert unit_times_from_graph(["Le", "chat", "dort."], chars, times) == [(0.0, 0.2), None, None]
    assert unit_times_from_graph(["Le"], [], []) == [None]


class _Resp:
    def __init__(self, status, body=None):
        self.status_code, self._body, self.text = status, body, "busy"

    def json(self):
        return self._body


def test_synthesize_request_and_retry(monkeypatch):
    calls = []
    text = "Voir (pause) ici"
    chars, times = _graph(text)
    ok = _Resp(200, {"audio": base64.b64encode(b"mp3-bytes").decode(), "duration": 1.6,
                     "audio_timestamps": {"graph_chars": chars, "graph_times": times}})

    def post(url, headers, json, timeout):
        calls.append((url, headers, json))
        return _Resp(503) if len(calls) == 1 else ok

    monkeypatch.setattr(xai.httpx, "post", post)
    monkeypatch.setattr(xai.time, "sleep", lambda s: None)
    prov = XaiProvider("key-123", "ara")
    voice = prov.voice_for("fr", None)
    assert voice == "ara:fr" and prov.voice_for("lv", None) == "ara:auto" and prov.voice_for("es", None) == "ara:es-ES"

    audio, duration, words = prov.synthesize(["Voir", "[pause]", "ici"], voice)
    assert (audio, duration) == (b"mp3-bytes", 1.6) and len(calls) == 2  # retried once after the 503
    url, headers, body = calls[-1]
    assert url == "https://api.x.ai/v1/tts" and headers["Authorization"] == "Bearer key-123"
    # square brackets would be read as a speech tag: sent as parentheses, same length
    assert body["text"] == text and body["voice_id"] == "ara" and body["language"] == "fr" and body["with_timestamps"]
    assert words == [(0.0, 0.4), (0.5, 1.2), (1.3, 1.6)]


def test_synthesize_error_is_reported(monkeypatch):
    monkeypatch.setattr(xai.httpx, "post", lambda *a, **k: _Resp(401))
    with pytest.raises(RuntimeError, match="401"):
        XaiProvider("bad").synthesize(["Bonjour"], "eve:fr")
