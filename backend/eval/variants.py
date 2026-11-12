"""Eval-only alternative: the source is pre-tokenised and the model returns word-index spans
instead of echoing chunk text. Spans are turned back into text units and go through the same
`align` safety net, so both variants are measured with identical post-processing."""
import json

from app.translation.base import Chunk, ChunkResult
from app.translation.claude import ClaudeTranslator
from app.translation import prompts

SPAN_BULLET = ('- "u": the sentence\'s numbered words grouped, in order, into short chunks of one to three words, keeping '
               "together what a learner should learn together (article + noun, auxiliary + verb, fixed expressions, names). "
               "Give each chunk as {\"a\": first word number, \"b\": last word number, \"g\": its literal {tgt} meaning in "
               "this context}. Every word belongs to exactly one chunk.")


def _system(src, tgt):
    base = prompts.system_prompt(src, tgt)
    start = base.index('- "u":')
    end = base.index("\n\n", start)
    return base[:start] + SPAN_BULLET.replace("{tgt}", prompts.display_name(tgt)) + base[end:]


def _tokens(sentence: str) -> list[str]:
    toks = sentence.split()
    return toks if len(toks) > 1 or len(sentence) < 8 else list(sentence)  # no spaces (Japanese): characters


_UNIT = {"type": "object", "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}, "g": {"type": "string"}},
         "required": ["a", "b", "g"], "additionalProperties": False}
_SENT = {"type": "object", "properties": {"t": {"type": "string"}, "u": {"type": "array", "items": _UNIT}},
         "required": ["t", "u"], "additionalProperties": False}
SCHEMA = {"type": "object", "properties": {"s": {"type": "array", "items": _SENT}, "g": prompts._PAIRS},
          "required": ["s", "g"], "additionalProperties": False}


class SpanTranslator(ClaudeTranslator):
    def translate(self, chunk: Chunk) -> ChunkResult:
        toks = [_tokens(s) for s in chunk.sentences]
        numbered = [" ".join(f"{j + 1}:{t}" for j, t in enumerate(ts)) for ts in toks]
        shown = Chunk(numbered, chunk.paragraphs, chunk.source_locale, chunk.target_locale, chunk.glossary,
                      chunk.context, chunk.context_translation)
        params = dict(model=self.model, max_tokens=16000,
                      system=[{"type": "text", "text": _system(chunk.source_locale, chunk.target_locale),
                               "cache_control": {"type": "ephemeral"}}],
                      messages=[{"role": "user", "content": prompts.user_prompt(shown)}],
                      output_config={"format": {"type": "json_schema", "schema": SCHEMA},
                                     **({"effort": self.effort} if self.effort else {})})
        r = self.client.messages.create(**params)
        data = json.loads(next(b.text for b in r.content if b.type == "text"))
        sentences = []
        for i, ts in enumerate(toks):
            s = (data.get("s") or [])[i] if i < len(data.get("s") or []) else {}
            sep = "" if len(ts) > 1 and ts == list(chunk.sentences[i]) else " "
            units = [[sep.join(ts[max(0, u["a"] - 1):max(0, u["b"])]), u["g"]] for u in s.get("u") or []]
            sentences.append({"t": s.get("t", ""), "u": units})
        return ChunkResult(sentences, {str(p[0]): str(p[1]) for p in data.get("g") or [] if len(p) >= 2})
