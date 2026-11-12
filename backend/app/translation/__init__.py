from app.config import settings
from app.translation.base import Chunk, ChunkResult, RateLimited, Translator, TranslatorError

_override: Translator | None = None


def set_translator(translator: Translator | None) -> None:
    """Tests can inject a translator; None restores the configured one."""
    global _override
    _override = translator


def get_translator() -> Translator:
    if _override is not None:
        return _override
    if settings.translator_kind == "claude":
        from app.translation.claude import ClaudeTranslator

        return ClaudeTranslator(
            settings.anthropic_api_key,
            settings.anthropic_model,
            settings.anthropic_effort,
            settings.anthropic_fallbacks,
        )
    from app.translation.mock import MockTranslator

    return MockTranslator()


__all__ = ["Chunk", "ChunkResult", "RateLimited", "Translator", "TranslatorError", "get_translator", "set_translator"]
