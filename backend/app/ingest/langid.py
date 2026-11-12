"""Language identification: fastText `lid.176.ftz` ("lite", bundled with fast-langdetect; model CC BY-SA 3.0,
see README). Used for the document language vote and for scoring candidate decodings of legacy encodings."""
import re

_ISO3 = {"fre": "fr", "fra": "fr", "eng": "en", "ger": "de", "deu": "de", "rus": "ru", "por": "pt", "lav": "lv",
         "jpn": "ja", "spa": "es", "ita": "it", "lat": "la", "ukr": "uk", "pol": "pl", "lit": "lt", "est": "et"}


def norm_lang(code: str | None) -> str | None:
    """'fr-FR' / 'fre' / 'French'-less ISO codes -> 'fr'; None if it does not look like a language code."""
    if not code:
        return None
    c = code.strip().lower().replace("_", "-").split("-")[0]
    if len(c) == 3:
        return _ISO3.get(c)
    return c if len(c) == 2 and c.isalpha() else None


_detector = None


def detect(text: str) -> tuple[str | None, float]:
    """(ISO code, confidence) on up to 3000 characters (fast-langdetect's default silently keeps only 80)."""
    global _detector
    sample = re.sub(r"\s+", " ", text or "")[:3000].strip()
    if len(sample) < 12:
        return None, 0.0
    try:
        if _detector is None:
            from fast_langdetect.infer import LangDetectConfig, LangDetector
            _detector = LangDetector(LangDetectConfig(max_input_length=None, model="lite"))
        r = _detector.detect(sample, model="lite", k=1)[0]
        return norm_lang(r["lang"]) or r["lang"], float(r["score"])
    except Exception:
        return None, 0.0
