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
}
ISO_TO_NAME = {v: k for k, v in NAME_TO_ISO.items()}


def to_iso(locale: str | None) -> str:
    value = (locale or "").strip().lower()
    if value in NAME_TO_ISO:
        return NAME_TO_ISO[value]
    return value[:2] or "en"


def display_name(locale: str | None) -> str:
    iso = to_iso(locale)
    return ISO_TO_NAME.get(iso, locale or iso).capitalize()
