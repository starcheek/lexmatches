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
# Regional variants: one ISO code (same ingest rules), their own name for the translator and their own voice.
# "portuguese" is the European one; a bare "pt" stays unspecified.
NAME_TO_ISO["brazilian portuguese"] = "pt"
_VARIANTS = {
    "portuguese": ("pt-PT", "European Portuguese"),
    "pt-pt": ("pt-PT", "European Portuguese"),
    "brazilian portuguese": ("pt-BR", "Brazilian Portuguese"),
    "pt-br": ("pt-BR", "Brazilian Portuguese"),
}
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


def is_supported(locale: str | None) -> bool:
    """A language this app knows by name, ISO code, regional variant or alias (case-insensitive)."""
    value = (locale or "").strip().lower().replace("_", "-")
    return bool(value) and (value in NAME_TO_ISO or value in ISO_TO_NAME or value in _VARIANTS or value in _ALIASES)


def _variant(locale: str | None) -> tuple[str, str] | None:
    return _VARIANTS.get((locale or "").strip().lower().replace("_", "-"))


def voice_key(locale: str | None) -> str:
    """Key for choosing a voice: "pt-BR" / "pt-PT" for a regional variant, the ISO code otherwise."""
    variant = _variant(locale)
    return variant[0] if variant else to_iso(locale)


def display_name(locale: str | None) -> str:
    variant = _variant(locale)
    if variant:
        return variant[1]
    iso = to_iso(locale)
    return ISO_TO_NAME.get(iso, locale or iso).capitalize()
