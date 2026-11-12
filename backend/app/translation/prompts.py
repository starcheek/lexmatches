"""Prompt and output schema for interlinear translation."""
from app.languages import display_name
from app.translation.base import Chunk

SYSTEM = """You translate {src} into {tgt} for language learners, who read the original with your translation underneath.

For each numbered sentence return:
- "t": a natural, faithful {tgt} translation, as a good published translation would read.
- "u": the sentence cut, in order, into chunks of usually two or three words that a learner should learn together (preposition + article + noun, auxiliary + verb, fixed expressions, names), as [chunk, meaning] pairs: the chunk copied from the sentence, the meaning its literal {tgt} sense in this context. Punctuation stays attached to its word. The chunks together must reproduce the sentence exactly.

Use the glossary and the preceding translation so names and terms stay consistent. In "g", list proper nouns and recurring terms you rendered that the glossary lacks, as [source, rendering]."""


def system_prompt(source_locale: str, target_locale: str) -> str:
    return SYSTEM.format(src=display_name(source_locale), tgt=display_name(target_locale))


def user_prompt(chunk: Chunk) -> str:
    parts = []
    if chunk.glossary:
        parts.append("Glossary:\n" + "\n".join(f"{k} = {v}" for k, v in chunk.glossary.items()))
    if chunk.context:
        ctx = f"Preceding text (context only, do not translate):\n{chunk.context}"
        if chunk.context_translation:
            ctx += f"\nIts translation:\n{chunk.context_translation}"
        parts.append(ctx)
    numbered = []
    for i, sentence in enumerate(chunk.sentences):
        if i and chunk.paragraphs[i] != chunk.paragraphs[i - 1]:
            numbered.append("")
        numbered.append(f"{i + 1}. {sentence}")
    parts.append("Sentences:\n" + "\n".join(numbered))
    return "\n\n".join(parts)


_PAIRS = {"type": "array", "items": {"type": "array", "items": {"type": "string"}}}
_SENTENCE = {"type": "object", "properties": {"t": {"type": "string"}, "u": _PAIRS},
             "required": ["t", "u"], "additionalProperties": False}
# Fixed on purpose: a schema per sentence count recompiles the grammar (slow first call) and
# breaks the grammar size limit on long chunks. Sentence count is checked by alignment instead.
OUTPUT_SCHEMA = {"type": "object", "properties": {"s": {"type": "array", "items": _SENTENCE}, "g": _PAIRS},
                 "required": ["s", "g"], "additionalProperties": False}
