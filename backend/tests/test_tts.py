import os
import threading
import types
import uuid

import numpy as np
import pytest

from app import storage, tts
from app.tts.elevenlabs import unit_times_from_alignment
from app.tts.piper import phones, unit_times
from app.tts.text import spoken_units


class FakeProvider:
    name = "piper"
    content_type = "audio/mpeg"

    def __init__(self):
        self.calls = 0
        self.not_ready = False
        self.gate: threading.Event | None = None

    def voice_for(self, lang, voice):
        if lang == "ja":
            raise ValueError("No server voice for language 'ja'")
        return voice or f"fake-{lang}"

    def prepare(self, voice, load=True):
        return {"state": "ready"}

    def synthesize(self, units, voice):
        if self.not_ready:
            raise tts.VoiceNotReady(voice)
        if self.gate:
            self.gate.wait(5)
        self.calls += 1
        times = [(round(i * 0.5, 3), round(i * 0.5 + 0.4, 3)) for i in range(len(units))]
        return b"ID3" + " ".join(units).encode(), len(units) * 0.5, times


@pytest.fixture
def fake_tts():
    fake = FakeProvider()
    tts.set_provider("piper", fake)
    yield fake
    tts.set_provider("piper", None)


def say(client, headers, text, language="french", **extra):
    return client.post("/api/tts", json={"text": text, "language": language, **extra}, headers=headers)


# ---- API -------------------------------------------------------------------------------------------
def test_tts_metadata_audio_and_cache(client, make_user, fake_tts):
    h = make_user()["headers"]
    text = f"— Bonjour, « Paul »[1] ! {uuid.uuid4().hex[:6]}"
    r1 = say(client, h, text)
    assert r1.status_code == 200, r1.text
    meta = r1.json()
    assert meta["cached"] is False and meta["voice"] == "fake-fr" and meta["content_type"] == "audio/mpeg"
    # one entry per display token; the dialogue dash and lone quote marks are silent
    tokens = text.split()
    assert len(meta["words"]) == len(tokens)
    assert [w is None for w in meta["words"]] == [True, False, True, False, True, False, False]

    audio = client.get(meta["audio_url"], headers=h)
    assert audio.status_code == 200 and audio.headers["content-type"] == "audio/mpeg"
    assert audio.content.startswith(b"ID3") and "immutable" in audio.headers["cache-control"]
    etag = audio.headers["etag"]
    assert client.get(meta["audio_url"], headers={**h, "If-None-Match": etag}).status_code == 304

    r2 = say(client, h, text, language="fr")
    assert r2.json()["cached"] is True and r2.json()["audio_url"] == meta["audio_url"]
    assert fake_tts.calls == 1
    say(client, h, text, language="english")  # different language -> different key
    assert fake_tts.calls == 2


def test_tts_cache_is_per_user(client, make_user, fake_tts):
    a, b = make_user()["headers"], make_user()["headers"]
    text = f"Le chat dort {uuid.uuid4().hex[:6]}."
    url = say(client, a, text).json()["audio_url"]
    assert client.get(url, headers=b).status_code == 404  # b cannot read a's audio
    assert say(client, b, text).json()["cached"] is False  # and does not share a's cache
    assert fake_tts.calls == 2


def test_tts_book_scope_deleted_with_book(client, make_user, fake_tts):
    user, other = make_user(), make_user()
    book = client.post("/api/books/text", headers=user["headers"], json={
        "title": "t", "original_locale": "french", "target_locale": "english", "text": "Le chat dort."}).json()
    assert say(client, other["headers"], "Le chat dort.", book_id=book["id"]).status_code == 404
    meta = say(client, user["headers"], "Le chat dort.", book_id=book["id"]).json()
    assert f"/{book['id']}/" in meta["audio_url"]
    misc = say(client, user["headers"], "Le chien dort.").json()
    assert client.get(meta["audio_url"], headers=user["headers"]).status_code == 200

    assert client.delete(f"/api/books/{book['id']}", headers=user["headers"]).status_code == 204
    assert client.get(meta["audio_url"], headers=user["headers"]).status_code == 404
    assert client.get(misc["audio_url"], headers=user["headers"]).status_code == 200  # other scopes kept
    assert tts.delete_audio(user["id"]) >= 2  # account-level purge
    assert client.get(misc["audio_url"], headers=user["headers"]).status_code == 404


def test_tts_errors(client, make_user, fake_tts):
    assert client.post("/api/tts", json={"text": "x"}).status_code == 401
    h = make_user()["headers"]
    assert say(client, h, "").status_code == 422
    assert say(client, h, "x" * 2001).status_code == 422
    assert say(client, h, "— « … » [2]").status_code == 400  # nothing speakable
    r = say(client, h, "こんにちは", language="japanese")
    assert r.status_code == 404 and "ja" in r.json()["detail"]
    assert client.get("/api/tts/audio/misc/..%2fsecret.mp3", headers=h).status_code == 404
    assert client.get("/api/tts/audio/misc/" + "0" * 64 + ".mp3", headers=h).status_code == 404

    fake_tts.not_ready = True
    r = say(client, h, f"Pas prête {uuid.uuid4().hex[:6]}")
    assert r.status_code == 503 and r.headers["retry-after"]


def test_tts_prepare(client, make_user, fake_tts):
    h = make_user()["headers"]
    r = client.post("/api/tts/prepare", json={"language": "french"}, headers=h)
    assert r.json() == {"language": "fr", "provider": "piper", "voice": "fake-fr", "state": "ready"}
    assert client.post("/api/tts/prepare", json={"language": "japanese"}, headers=h).json()["state"] == "unavailable"


def test_tts_rate_limit(client, make_user, fake_tts, monkeypatch):
    from app.routers import tts as router

    monkeypatch.setattr(router, "settings", types.SimpleNamespace(tts_rate_per_min=2))
    h = make_user()["headers"]
    assert say(client, h, "un").status_code == 200
    assert say(client, h, "deux").status_code == 200
    r = say(client, h, "trois")
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0
    assert say(client, make_user()["headers"], "trois").status_code == 200  # per user


def test_identical_requests_share_one_synthesis(client, make_user, fake_tts):
    fake_tts.gate = threading.Event()
    p = tts.plan(f"Une fois {uuid.uuid4().hex[:6]}", "fr", user_id=uuid.uuid4())
    f1, f2 = tts.submit(p), tts.submit(p)
    assert f1 is f2
    fake_tts.gate.set()
    assert f1.result(5).duration > 0 and fake_tts.calls == 1


# ---- text / timing units --------------------------------------------------------------------------
def test_spoken_units():
    assert spoken_units("— Bonjour, M. Fogg[12] — dit-il¹.", "fr") == ["", "Bonjour,", "Monsieur", "Fogg", ",", "dit-il."]
    assert spoken_units("Il part. — Déjà ?", "fr") == ["Il", "part.", "", "Déjà", "?"]  # dialogue turn, no pause unit
    assert spoken_units("«Oui» mot—mot fin— (3) a(2)", "fr") == ["Oui", "mot, mot", "fin,", "(3)", "a"]
    assert spoken_units("Mr. Smith, e.g. this", "en") == ["Mister", "Smith,", "for example", "this"]
    assert spoken_units("т.е. всё", "ru") == ["то есть", "всё"]
    assert spoken_units("l’homme", "fr") == ["l'homme"]


def test_unit_times_alignment():
    assert phones(list("ˈab cd, e.")) == list("abcde")
    # "of the" merged by espeak into one word "ʌvðə": still split exactly at the phone boundary
    actual = [("ʌ", 0, 10), ("v", 10, 20), ("ð", 20, 30), ("ə", 30, 45), ("m", 50, 60)]
    assert unit_times([list("ʌv"), list("ðə"), [], list("m")], actual) == [(0, 20), (20, 45), None, (50, 60)]
    # context changed a unit completely (no phone matched): it takes the gap between neighbours
    actual = [("a", 0, 10), ("x", 10, 30), ("b", 30, 40)]
    assert unit_times([["a"], ["q"], ["b"]], actual) == [(0, 10), (10, 30), (30, 40)]
    # liaison: an extra phone in context does not shift the next unit
    actual = [("d", 0, 5), ("e", 5, 10), ("t", 10, 15), ("a", 15, 30)]
    assert unit_times([list("de"), ["a"]], actual) == [(0, 10), (15, 30)]


def test_elevenlabs_alignment_parsing():
    units = ["Hi", "there"]
    chars = list("Hi there")
    alignment = {"characters": chars,
                 "character_start_times_seconds": [i * 0.1 for i in range(len(chars))],
                 "character_end_times_seconds": [i * 0.1 + 0.1 for i in range(len(chars))]}
    times, duration = unit_times_from_alignment(units, alignment)
    assert times == [(0.0, 0.2), (0.3, 0.8)] and duration == 0.8


def test_piper_voice_url():
    from app.tts.piper import voice_url

    assert voice_url("fr_FR-siwis-medium", ".onnx").endswith("/fr/fr_FR/siwis/medium/fr_FR-siwis-medium.onnx")


# ---- real Piper (downloads voices; slow) ---------------------------------------------------------
SAMPLES = {
    "fr": "Phileas Fogg demeurait en 1872 au numéro 7 de Saville-row. — Bonjour, dit-il, l'homme sourit.",
    "en": "Mr. Fogg lived, in 1872, at No. 7, Saville Row. He was one of the most noticeable members.",
    "lv": "Lāčplēsis bija varonis, kurš cīnījās par savu tautu. Viņš dzīvoja pie Daugavas.",
    "ru": "Все счастливые семьи похожи друг на друга, каждая несчастливая семья несчастлива по-своему. Всё смешалось в доме Облонских.",
}


def _mp3_frames_ok(data: bytes) -> bool:
    i = data.find(b"\xff")
    return i >= 0 and data[i + 1] & 0xE0 == 0xE0


@pytest.mark.skipif(not os.environ.get("RUN_PIPER_TESTS"), reason="downloads Piper voices (network); set RUN_PIPER_TESTS=1")
@pytest.mark.parametrize("lang", list(SAMPLES))
def test_piper_real_synthesis(client, make_user, lang):
    from app.tts.piper import VoiceNotReady

    prov = tts.get_provider("piper")
    voice = prov.voice_for(lang, None)
    prov.prepare(voice)
    prov.wait(voice, 600)
    h = make_user()["headers"]
    text = SAMPLES[lang]
    r = say(client, h, text, language=lang)
    assert r.status_code == 200, r.text
    meta = r.json()
    audio = client.get(meta["audio_url"], headers=h).content
    # valid CBR 48 kbps MP3 whose length matches the reported duration
    assert _mp3_frames_ok(audio)
    assert abs(len(audio) * 8 / 48_000 - meta["duration"]) < 0.25, (len(audio), meta["duration"])

    tokens, words = text.split(), meta["words"]
    assert len(words) == len(tokens)
    timed = [w for w, t in zip(words, tokens) if t != "—"]
    assert all(timed)  # every token except the dialogue dash is speakable
    for (s1, e1), (s2, e2) in zip(timed, timed[1:]):
        assert 0 <= s1 < e1 <= s2 < e2 <= meta["duration"] + 1e-6
    assert timed[0][0] < 0.5 and meta["duration"] - timed[-1][1] < 0.6

    # Timings come from the model's own phoneme durations (exact to one 256-sample hop). Guard the
    # bookkeeping (sentence chunks, inserted pauses): sentence breaks must fall in silence and every
    # punctuation boundary must sit on an energy dip. (Synthesis is stochastic: render again here.)
    units = spoken_units(text, lang)
    try:
        samples, rate, spoken_times = prov.render([u for u in units if u], voice)
    except VoiceNotReady:
        pytest.fail("voice not ready")
    it = iter(spoken_times)
    times = [next(it) if u else None for u in units]
    env = np.abs(samples.astype(np.float32))
    rms = lambda a, b: float(np.sqrt(np.mean(env[int(a * rate):int(b * rate)] ** 2) + 1e-9))  # noqa: E731
    loud = np.median([rms(*t) for t in spoken_times if t and t[1] - t[0] > 0.15])
    frame_min = lambda a, b: min(rms(t, t + 0.02) for t in np.arange(a, b, 0.01))  # noqa: E731
    timed_idx = [i for i, t in enumerate(times) if t]
    pairs = list(zip(timed_idx, timed_idx[1:]))
    boundaries = [(units[i][-1], times[i][1], times[j][0]) for i, j in pairs if units[i][-1] in ",."]
    assert any(p == "." for p, _, _ in boundaries) and any(p == "," for p, _, _ in boundaries)
    for punct, a, b in boundaries:
        assert b > a, (lang, punct, a, b)
        if punct == ".":
            assert rms(a + 0.03, b - 0.03) < 0.1 * loud, (lang, a, b)
        assert frame_min(a - 0.03, b + 0.03) < 0.3 * loud, (lang, punct, a, b)
