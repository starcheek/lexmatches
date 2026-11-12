"""Frozen copy of the pre-v2 translation pipeline (prompts + validation/retry/split machinery),
kept only so the eval can run OLD vs NEW on the same passages. Not used by the app."""
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor

GLOBAL_PROMPT = (
    "You are a language translation assistant. Translate the provided text accurately while "
    "preserving meaning and context. Provide word-by-word translations aligned with the original text."
)
LANGUAGE_PROMPTS = {"fr": "The source text is French."}
RULES = """Rules:
- Split every line into small units of 1-3 source words. Never put a whole clause or line in one unit.
- Article + noun stay one unit ("la technologie" -> "the technology"). Compound verbs stay one unit ("a réussi" -> "has succeeded").
- Prepositions are their own unit ("de" -> "of", "à" -> "to").
- Fixed expressions stay one unit ("pomme de terre" -> "potato").
- Keep the source word order. Cover every source word exactly once; add nothing.

Return JSON: {"lines":[[{"original":"...","translation":"..."}]]} — one array per input line, same order."""
NAMES = {"en": "English", "fr": "French", "de": "German", "ru": "Russian", "pt": "Portuguese",
         "lv": "Latvian", "ja": "Japanese", "es": "Spanish", "it": "Italian"}


def system_prompt(src: str, tgt: str) -> str:
    return (f"{GLOBAL_PROMPT}\n{LANGUAGE_PROMPTS.get(src, '')}\n"
            f"Translate from {NAMES[src]} to {NAMES[tgt]} literally, word by word, for a language learner.\n\n{RULES}")


def user_prompt(lines: list[str]) -> str:
    n = len(lines)
    numbered = "\n".join(f"[{i + 1}] {line}" for i, line in enumerate(lines))
    return (f'Translate exactly {n} numbered line(s). "lines" MUST have exactly {n} element(s), in the same '
            "order — never split one input line into several output lines, even if it contains several "
            "sentences. Split every line into small word/phrase units before translating; never return a "
            f"whole line as one pair.\n\n{numbered}")


SCHEMA = {"type": "object", "properties": {"lines": {"type": "array", "items": {"type": "array", "items": {
    "type": "object", "properties": {"original": {"type": "string"}, "translation": {"type": "string"}},
    "required": ["original", "translation"], "additionalProperties": False}}}},
    "required": ["lines"], "additionalProperties": False}

BATCH_SIZE, CONCURRENCY, MAX_ATTEMPTS = 8, 4, 2
_PUNCT = re.compile(r"[«»“”\"()\[\]{}.,;:!?…—–\-]")
_APOS = re.compile(r"[’´`]")
_NUMBERING = re.compile(r"^\s*\[\d+\]\s*")


def source_lines(text: str) -> list[str]:
    return [line for line in (text or "").split("\n") if line.strip()]


def tokenize(text):
    return [t for t in _APOS.sub("'", _PUNCT.sub(" ", text.lower())).split() if t]


def split_line(line):
    parts = [p.strip() for p in re.split(r"(?<=[.!?…»:;])\s+", line) if p.strip()]
    if len(parts) > 1:
        return parts
    words = line.split()
    if len(words) < 8:
        return [line]
    mid = (len(words) + 1) // 2
    return [" ".join(words[:mid]), " ".join(words[mid:])]


def repair_line(source, pairs):
    src = tokenize(source)
    out, idx = [], 0
    for pair in pairs:
        tok = tokenize(str((pair or {}).get("original", "")))
        if not tok:
            continue
        match_at = -1
        for start in range(idx, min(len(src) - len(tok), idx + 4) + 1):
            if src[start:start + len(tok)] == tok:
                match_at = start
                break
        if match_at == -1:
            continue
        out.append(pair)
        idx = match_at + len(tok)
    return out, idx < len(src)


def validate_line(source, pairs):
    if not isinstance(pairs, list) or not pairs:
        return "empty alignment"
    words = len(source.split())
    bad = any(not isinstance(p, dict) or not isinstance(p.get("original"), str)
              or not isinstance(p.get("translation"), str) or len(p["original"].split()) > 4 for p in pairs)
    if bad or len(pairs) < max(1, -(-words // 4)):
        return "sentence-level alignment"
    if repair_line(source, pairs)[1]:
        return "incomplete coverage of the source line"
    return None


class OldTranslator:
    """Old ClaudeTranslator.translate_lines, with a pluggable `call(system, user, schema)`."""

    def __init__(self, call, src, tgt):
        self.call, self.src, self.tgt = call, src, tgt

    def translate_lines(self, lines):
        data = self.call(system_prompt(self.src, self.tgt), user_prompt(lines), SCHEMA)
        result = data.get("lines") if isinstance(data, dict) else None
        if not isinstance(result, list):
            raise ValueError("invalid structure")
        return result


class Stats:
    def __init__(self):
        self.calls = self.retries = self.splits = self.best_effort = 0
        self.lock = threading.Lock()

    def inc(self, k):
        with self.lock:
            setattr(self, k, getattr(self, k) + 1)


def translate_batch(t, batch, stats, sem):
    last_error, best = None, None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            with sem:
                stats.inc("calls")
                lines = t.translate_lines(batch)
            for line in lines:
                for p in line if isinstance(line, list) else []:
                    if isinstance(p, dict):
                        for k in ("original", "translation"):
                            if isinstance(p.get(k), str):
                                p[k] = _NUMBERING.sub("", p[k])
            if len(batch) == 1 and len(lines) > 1:
                flat = [p for line in lines if isinstance(line, list) for p in line if isinstance(p, dict)]
                if flat:
                    lines = [flat]
            if len(lines) != len(batch):
                raise ValueError("wrong number of lines")
            if best is None:
                best = lines
            for i, line in enumerate(lines):
                problem = validate_line(batch[i], line)
                if problem:
                    raise ValueError(problem)
            return lines
        except Exception as e:  # noqa: BLE001
            last_error = e
            if attempt < MAX_ATTEMPTS:
                stats.inc("retries")
    if len(batch) > 1:
        stats.inc("splits")
        mid = (len(batch) + 1) // 2
        return translate_batch(t, batch[:mid], stats, sem) + translate_batch(t, batch[mid:], stats, sem)
    chunks = split_line(batch[0])
    if len(chunks) > 1:
        stats.inc("splits")
        merged = []
        for c in chunks:
            for line in translate_batch(t, [c], stats, sem):
                merged.extend(line)
        return [merged]
    if best is not None:
        stats.inc("best_effort")
        return best
    raise last_error


def translate_page(call, text, src, tgt):
    """Returns (lines, stats). lines[i] = pairs for the i-th non-empty source line."""
    t, stats, sem = OldTranslator(call, src, tgt), Stats(), threading.Semaphore(CONCURRENCY)
    src_lines = source_lines(text)
    batches = [src_lines[i:i + BATCH_SIZE] for i in range(0, len(src_lines), BATCH_SIZE)]
    with ThreadPoolExecutor(CONCURRENCY) as pool:
        results = list(pool.map(lambda b: translate_batch(t, b, stats, sem), batches))
    lines = [line for r in results for line in r]
    return src_lines, lines, stats


def full_translation(lines):
    return " ".join(" ".join(str(p.get("translation", "")) for p in line) for line in lines if isinstance(line, list))


__all__ = ["translate_page", "full_translation", "json"]
