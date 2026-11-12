"""Local Piper TTS with exact word timings.

Voices are downloaded in the background (startup preload and/or `prepare()`) from
rhasspy/piper-voices into a volume. On first load a model is patched once, on disk, to also
output per-phoneme durations (`piper.patch_voice_with_alignment`, needs the `onnx` package);
those durations give exact word boundaries.

Word timing: Piper yields one audio chunk per sentence with a sample count for every phoneme.
Each spoken unit (≈ display token) is also phonemized on its own; the per-unit phoneme sequence
is aligned to the in-context sequence with difflib, so every unit gets the exact start/end of its
own phonemes. Context differences (espeak merging "of the" into one word, French liaison, stress
shifts) only affect the few phonemes involved; units with no matched phoneme take the gap
between their neighbours.
"""
import difflib
import json
import logging
import threading
import urllib.parse
import urllib.request
from collections import OrderedDict
from pathlib import Path

import numpy as np

from app.config import settings
from app.tts.audio import encode_mp3

log = logging.getLogger(__name__)

VOICE_BASE_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main"

# ISO language -> Piper voice key. Chosen by an ASR intelligibility check plus listening notes,
# see docs/ARCHITECTURE.md (TTS). All "medium" (22.05 kHz): "high" models cost ~2x CPU.
DEFAULT_VOICES = {
    "en": "en_US-lessac-medium",
    "fr": "fr_FR-siwis-medium",
    "ru": "ru_RU-irina-medium",
    "pt": "pt_BR-cadu-medium",  # CER 2.0 % vs faber 6.7 %, tugão (pt_PT) 10 %
    "lv": "lv_LV-aivars-medium",  # the only Latvian voice
    "de": "de_DE-thorsten-medium",
    "es": "es_ES-davefx-medium",
    "it": "it_IT-serena-medium",  # CER 1.1 % vs paola 2.1 %
}

SENTENCE_PAUSE_S = 0.25
# Not phones: sentence markers, word gaps, punctuation (pauses) and stress marks.
_SKIP = set("^$ .,;:!?¡¿—–-…\"«»()[]ˈˌ")
_MAX_LOADED = 3


class VoiceNotReady(Exception):
    """Voice files are still downloading; retry after `prepare()` reports ready."""


def voice_url(key: str, suffix: str) -> str:
    """'fr_FR-siwis-medium' -> .../fr/fr_FR/siwis/medium/fr_FR-siwis-medium.onnx"""
    locale, name, quality = key.split("-", 2)
    family = locale.split("_")[0]
    path = f"{family}/{locale}/{name}/{quality}/{key}{suffix}"
    return f"{VOICE_BASE_URL}/{urllib.parse.quote(path)}"


def phones(phonemes: list[str]) -> list[str]:
    return [p for p in phonemes if p not in _SKIP]


def unit_times(units: list[list[str]], actual: list[tuple[str, int, int]]) -> list[tuple[int, int] | None]:
    """Map spoken units to sample ranges.

    units[u]: phones of unit u phonemized on its own; actual: (phone, start, end) as synthesized.
    """
    expected = [p for u in units for p in u]
    owner = [i for i, u in enumerate(units) for _ in u]
    span: list[list[int] | None] = [None] * len(units)
    matcher = difflib.SequenceMatcher(None, expected, [p for p, _, _ in actual], autojunk=False)
    for a, b, size in matcher.get_matching_blocks():
        for k in range(size):
            s, e = actual[b + k][1:]
            u = owner[a + k]
            if span[u] is None:
                span[u] = [s, e]
            else:
                span[u][1] = e
    out: list[tuple[int, int] | None] = []
    for i, sp in enumerate(span):
        if sp is None and units[i]:  # spoken but unmatched: the gap between its neighbours
            prev = next((x[1] for x in reversed(span[:i]) if x), 0)
            nxt = next((x[0] for x in span[i + 1:] if x), actual[-1][2] if actual else 0)
            sp = [prev, nxt] if nxt > prev else None
        out.append(tuple(sp) if sp else None)
    return out


class PiperProvider:
    name = "piper"
    content_type = "audio/mpeg"

    def __init__(self, voices_dir: str, overrides: str = ""):
        self.dir = Path(voices_dir)
        self.voices = dict(DEFAULT_VOICES)
        for item in filter(None, (s.strip() for s in overrides.split(","))):
            lang, _, key = item.partition("=")
            if key:
                self.voices[lang.strip()] = key.strip()
        self._loaded: OrderedDict = OrderedDict()
        self._lock = threading.Lock()
        self._load_locks: dict[str, threading.Lock] = {}
        self._downloads: dict[str, dict] = {}  # key -> {"progress": float, "error": str|None, "thread"}

    # ---- voices -------------------------------------------------------------------------
    def voice_for(self, lang: str, voice: str | None) -> str:
        if voice:
            if voice not in self.voices.values():
                raise ValueError(f"Unknown voice '{voice}'")
            return voice
        if lang not in self.voices:
            raise ValueError(f"No server voice for language '{lang}'")
        return self.voices[lang]

    def _files(self, key: str) -> tuple[Path, Path]:
        return self.dir / f"{key}.onnx", self.dir / f"{key}.onnx.json"

    def _present(self, key: str) -> bool:
        return all(p.exists() for p in self._files(key))

    def status(self, key: str) -> dict:
        """ready (in memory) | loading (on disk; first synthesis loads it) | downloading | missing | error"""
        if key in self._loaded:
            return {"state": "ready"}
        dl = self._downloads.get(key) or {}
        alive = bool(dl) and dl["thread"].is_alive()
        if alive and not self._present(key):
            return {"state": "downloading", "progress": round(dl["progress"], 2)}
        if dl.get("error") and not alive:
            return {"state": "error", "error": dl["error"]}
        return {"state": "loading" if self._present(key) else "missing"}

    def prepare(self, key: str, load: bool = True) -> dict:
        """Start a background download (and optionally model load); returns status()."""
        with self._lock:
            dl = self._downloads.get(key)
            busy = dl is not None and dl["thread"].is_alive()
            if not busy and key not in self._loaded and (load or not self._present(key)):
                state = {"progress": 0.0, "error": None}
                state["thread"] = threading.Thread(
                    target=self._prepare_worker, args=(key, state, load), name=f"piper-{key}", daemon=True
                )
                self._downloads[key] = state
                state["thread"].start()
        return self.status(key)

    def wait(self, key: str, timeout: float | None = None) -> None:
        dl = self._downloads.get(key)
        if dl:
            dl["thread"].join(timeout)

    def _prepare_worker(self, key: str, state: dict, load: bool) -> None:
        try:
            self._download(key, state)
            if load:
                self._voice(key)
        except Exception as e:  # surfaced through status()
            log.exception("preparing Piper voice %s failed", key)
            state["error"] = str(e)[:200]

    def _download(self, key: str, state: dict) -> None:
        model, config = self._files(key)
        self.dir.mkdir(parents=True, exist_ok=True)
        for suffix, target in ((".onnx.json", config), (".onnx", model)):
            if target.exists():
                continue
            url = voice_url(key, suffix)
            log.info("downloading Piper voice file %s", url)
            tmp = target.with_suffix(target.suffix + ".part")
            with urllib.request.urlopen(url, timeout=300) as resp, open(tmp, "wb") as fh:
                total = int(resp.headers.get("Content-Length") or 0)
                done = 0
                while chunk := resp.read(1 << 20):
                    fh.write(chunk)
                    done += len(chunk)
                    if total and suffix == ".onnx":
                        state["progress"] = done / total
            tmp.rename(target)
        state["progress"] = 1.0

    def _session(self, model: Path):
        import onnxruntime

        opts = onnxruntime.SessionOptions()
        # The default (one spinning thread per core) is pathological on a shared CPU: 14-18 s
        # instead of ~1 s for 8 s of audio under load. A couple of non-spinning threads is plenty.
        opts.intra_op_num_threads = settings.piper_threads
        opts.inter_op_num_threads = 1
        opts.add_session_config_entry("session.intra_op.allow_spinning", "0")
        return onnxruntime.InferenceSession(str(model), sess_options=opts, providers=["CPUExecutionProvider"])

    def _patch_alignment(self, model: Path) -> bool:
        """Rewrite the model once so it also outputs phoneme durations. False if impossible."""
        try:
            import onnx
            from piper.patch_voice_with_alignment import add_alignment_output

            graph = onnx.load(str(model))
            add_alignment_output(graph)
            tmp = model.with_suffix(".onnx.patching")
            onnx.save(graph, str(tmp))
            tmp.rename(model)
            log.info("patched %s for phoneme alignments", model.name)
            return True
        except Exception as e:
            log.warning("no phoneme alignments for %s (%s); word timings will be proportional", model.name, e)
            return False

    def _voice(self, key: str):
        with self._lock:
            if key in self._loaded:
                self._loaded.move_to_end(key)
                return self._loaded[key]
            lock = self._load_locks.setdefault(key, threading.Lock())
        with lock:  # load outside the global lock: loading takes seconds
            if key in self._loaded:
                return self._loaded[key]
            if not self._present(key):
                raise VoiceNotReady(key)
            from piper import PiperVoice
            from piper.config import PiperConfig

            model, config = self._files(key)
            session = self._session(model)
            if len(session.get_outputs()) < 2 and self._patch_alignment(model):
                session = self._session(model)
            voice = PiperVoice(config=PiperConfig.from_dict(json.loads(config.read_text("utf-8"))), session=session)
            for _ in voice.synthesize("a", include_alignments=True):  # warm-up: first run is much slower
                pass
            with self._lock:
                self._loaded[key] = voice
                while len(self._loaded) > _MAX_LOADED:
                    self._loaded.popitem(last=False)
            return voice

    # ---- synthesis ----------------------------------------------------------------------
    def synthesize(self, units: list[str], voice: str) -> tuple[bytes, float, list[tuple[float, float] | None]]:
        """units: non-empty spoken strings. Returns (mp3, duration_s, per-unit (start, end) seconds)."""
        samples, rate, times = self.render(units, voice)
        return encode_mp3(samples.tobytes(), rate), round(len(samples) / rate, 3), times

    def render(self, units: list[str], voice: str) -> tuple[np.ndarray, int, list[tuple[float, float] | None]]:
        """-> (int16 mono samples, sample_rate, per-unit (start, end) seconds or None)."""
        from piper import SynthesisConfig

        if not self._present(voice):
            self.prepare(voice)
            raise VoiceNotReady(voice)
        v = self._voice(voice)
        rate = v.config.sample_rate
        pause = np.zeros(int(rate * SENTENCE_PAUSE_S), dtype=np.int16)
        cfg = SynthesisConfig(length_scale=settings.piper_length_scale)

        pcm: list[np.ndarray] = []
        actual: list[tuple[str, int, int]] = []
        offset = 0
        for i, chunk in enumerate(v.synthesize(" ".join(units), syn_config=cfg, include_alignments=True)):
            if i:
                pcm.append(pause)
                offset += len(pause)
            audio = chunk.audio_int16_array
            if chunk.phoneme_alignments:
                timeline = [(a.phoneme, int(a.num_samples)) for a in chunk.phoneme_alignments]
            else:  # unpatched model: spread the chunk evenly over its phonemes
                seq = ["^", *chunk.phonemes, "$"]
                timeline = [(p, len(audio) // len(seq)) for p in seq]
            pos = offset
            for phoneme, n in timeline:
                if phoneme not in _SKIP:
                    actual.append((phoneme, pos, pos + n))
                pos += n
            pcm.append(audio)
            offset += len(audio)

        expected = [[p for sentence in v.phonemize(u) for p in phones(sentence)] for u in units]
        times = [None if t is None else (round(t[0] / rate, 3), round(t[1] / rate, 3)) for t in unit_times(expected, actual)]
        samples = np.concatenate(pcm) if pcm else np.zeros(0, dtype=np.int16)
        return samples, rate, times
