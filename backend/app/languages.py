"""Book locales are stored as the UI sends them (e.g. "french"); some callers use ISO codes."""

NAME_TO_ISO = {
    "english": "en",
    "french": "fr",
    "spanish": "es",
    "german": "de",
    "italian": "it",
    "portuguese": "pt",
    "russian": "ru",
    "japanese": "ja",
    "latvian": "lv",
    "dutch": "nl",
    "polish": "pl",
    "ukrainian": "uk",
    "czech": "cs",
    "swedish": "sv",
    "norwegian": "no",  # Bokmål (fastText reports "no"; "nb"/"nn" are normalised in app/ingest/langid.py)
    "danish": "da",
    "finnish": "fi",
    "romanian": "ro",
    "hungarian": "hu",
    "greek": "el",
    "turkish": "tr",
    "catalan": "ca",
}
ISO_TO_NAME = {v: k for k, v in NAME_TO_ISO.items()}
# Other spellings of a supported language (BCP-47 / local names) -> its code here.
_ALIASES = {"nb": "no", "nn": "no", "nob": "no", "nno": "no", "bokmål": "no", "bokmal": "no", "norsk": "no"}


def to_iso(locale: str | None) -> str:
    value = (locale or "").strip().lower()
    if value in NAME_TO_ISO:
        return NAME_TO_ISO[value]
    if value in _ALIASES:
        return _ALIASES[value]
    value = value.replace("_", "-").split("-")[0]  # "nb-NO" -> "nb"
    return _ALIASES.get(value, value[:2]) or "en"


def display_name(locale: str | None) -> str:
    iso = to_iso(locale)
    return ISO_TO_NAME.get(iso, locale or iso).capitalize()
