"""Claude-backed translator (official `anthropic` SDK, structured JSON output)."""
import json

import anthropic

from app.translation.base import Chunk, ChunkResult, RateLimited, TranslatorError
from app.translation.prompts import OUTPUT_SCHEMA, system_prompt, user_prompt

# Models that accept the server-side refusal fallback (`fallbacks: "default"`).
FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class ClaudeTranslator:
    name = "claude"

    def __init__(self, api_key: str, model: str, effort: str = "low", fallbacks: str = "default",
                 base_url: str | None = None):
        self.client = anthropic.Anthropic(api_key=api_key, timeout=120.0, max_retries=2, base_url=base_url)
        self.model = model
        self.effort = effort
        self.use_fallbacks = fallbacks == "default" and model in FALLBACK_MODELS

    def translate(self, chunk: Chunk) -> ChunkResult:
        output_config: dict = {"format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}}
        if self.effort:
            output_config["effort"] = self.effort
        params = dict(
            model=self.model,
            max_tokens=16000,
            # Stable per language pair and first in the prompt, so it is cacheable once long enough.
            system=[{"type": "text", "text": system_prompt(chunk.source_locale, chunk.target_locale),
                     "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user_prompt(chunk)}],
            output_config=output_config,
        )
        try:
            if self.use_fallbacks:
                response = self.client.beta.messages.create(
                    **params, betas=[FALLBACK_BETA], extra_body={"fallbacks": "default"}
                )
            else:
                response = self.client.messages.create(**params)
        except anthropic.RateLimitError as e:
            try:
                retry_after = float(e.response.headers.get("retry-after") or 0)
            except (TypeError, ValueError):
                retry_after = 0.0
            raise RateLimited(retry_after=retry_after) from e
        except anthropic.APIStatusError as e:
            raise TranslatorError(f"Claude API error {e.status_code}: {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise TranslatorError(f"Claude API connection error: {e}") from e

        if response.stop_reason == "refusal":
            raise TranslatorError("Claude declined to translate this text")
        if response.stop_reason == "max_tokens":
            raise TranslatorError("Claude output was truncated (max_tokens)")
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise TranslatorError("Claude returned invalid JSON") from e
        if not isinstance(data, dict) or not isinstance(data.get("s"), list):
            raise TranslatorError("Claude returned an invalid structure")
        return ChunkResult(
            sentences=data["s"][: len(chunk.sentences)],
            glossary={str(p[0]).strip(): str(p[1]).strip() for p in data.get("g") or [] if len(p) >= 2},
        )
