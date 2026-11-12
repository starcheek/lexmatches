"""Text normalisation before synthesis.

Works token by token (whitespace split) so every spoken unit maps back to exactly one display
token: the client highlights token *i* of the segment text using `words[i]` timings.
Numbers are left to espeak-ng, which already reads them per language ("1872" -> "mille huit
cent soixante-douze"). We only fix what espeak gets wrong or reads aloud: footnote markers,
quotes, dialogue dashes and abbreviations whose trailing period would end the sentence.
"""
import re

# Abbreviations espeak either spells out or treats as a sentence end ("M. Fogg" -> "M" + pause).
ABBREVIATIONS: dict[str, dict[str, str]] = {
    "fr": {"M.": "Monsieur", "MM.": "Messieurs", "Mme": "Madame", "Mme.": "Madame", "Mmes": "Mesdames",
           "Mlle": "Mademoiselle", "Mlle.": "Mademoiselle", "Dr": "Docteur", "Dr.": "Docteur",
           "St": "Saint", "Ste": "Sainte", "etc.": "et cetera", "cf.": "confer"},
    "en": {"Mr.": "Mister", "Mrs.": "Missus", "Dr.": "Doctor", "St.": "Saint", "etc.": "et cetera",
           "e.g.": "for example", "i.e.": "that is", "vs.": "versus"},
    "de": {"z.B.": "zum Beispiel", "usw.": "und so weiter", "d.h.": "das heißt", "bzw.": "beziehungsweise",
           "Hr.": "Herr", "Fr.": "Frau", "Dr.": "Doktor", "ca.": "circa"},
    "es": {"Sr.": "Señor", "Sra.": "Señora", "Srta.": "Señorita", "Dr.": "Doctor", "Dra.": "Doctora",
           "etc.": "etcétera", "Ud.": "usted", "Uds.": "ustedes"},
    "pt": {"Sr.": "Senhor", "Sra.": "Senhora", "Dr.": "Doutor", "Dra.": "Doutora", "etc.": "et cetera"},
    "it": {"Sig.": "Signor", "Sig.ra": "Signora", "Dott.": "Dottor", "ecc.": "eccetera"},
    "ru": {"т.е.": "то есть", "т.д.": "так далее", "т.п.": "тому подобное", "др.": "другие", "г-н": "господин",
           "г-жа": "госпожа"},
    "lv": {"utt.": "un tā tālāk", "u.c.": "un citi", "piem.": "piemēram", "t.i.": "tas ir"},
}

_FOOTNOTE = re.compile(r"\[\s*(?:\d{1,3}|[a-z*†‡]|note\s*\d+)\s*\]|[¹²³⁰⁴-⁹]+|[*†‡]+", re.IGNORECASE)
_ATTACHED_NUMBER_NOTE = re.compile(r"(?<=[^\W\d])\(\d{1,3}\)")  # "mot(3)" -> "mot"
_QUOTES = re.compile(r"[«»‹›“”„‟\"]")
_APOSTROPHES = re.compile(r"[’ʼ‘`]")
_DASHES = re.compile(r"[—–―]")  # em/en dash, horizontal bar (not the hyphen)
_SPEAKABLE = re.compile(r"[^\W_]")  # a letter or digit, any script


def tokens(text: str) -> list[str]:
    """Display tokens; `words[i]` in the API response refers to `tokens(text)[i]`."""
    return text.split()


def speakable(text: str) -> bool:
    return bool(_SPEAKABLE.search(text or ""))


def _normalize_token(token: str, previous: str, abbreviations: dict[str, str]) -> str:
    t = _APOSTROPHES.sub("'", token)
    t = _FOOTNOTE.sub("", t)
    t = _ATTACHED_NUMBER_NOTE.sub("", t)
    t = _QUOTES.sub("", t)
    if t in abbreviations:
        return abbreviations[t]
    stripped = t.rstrip(",;:!?")
    if stripped in abbreviations:  # "M.," keeps its trailing comma
        return abbreviations[stripped] + t[len(stripped):]
    if _DASHES.sub("", t) == "":
        # A bare dash: a dialogue marker at the start of a segment or sentence, otherwise a pause.
        return "" if not t or not previous or previous[-1] in ".!?…:" else ","
    # "—Bonjour" -> "Bonjour", "mot—mot" -> "mot, mot", "fin—" -> "fin,"
    return _DASHES.sub(", ", t).lstrip(", ").strip()


def spoken_units(text: str, lang: str) -> list[str]:
    """One spoken string per display token ('' = silent token: footnote marker, quote, dash…)."""
    abbreviations = ABBREVIATIONS.get(lang, {})
    toks = tokens(text)
    units = [_normalize_token(tok, toks[i - 1] if i else "", abbreviations) for i, tok in enumerate(toks)]
    # A pause-only unit is meaningless at the very start or end.
    return ["" if (u == "," and (i == 0 or i == len(units) - 1)) else u for i, u in enumerate(units)]
