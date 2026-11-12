"""Deterministic offline translator for tests, e2e and running without an API key.

Splits each sentence into single words and "translates" with a tiny French->English glossary;
unknown words are echoed in guillemets; capitalised non-initial words are reported as names.
"""
import re

from app.translation.base import Chunk, ChunkResult

GLOSSARY = {
    "le": "the", "la": "the", "les": "the", "l'": "the", "un": "a", "une": "a", "des": "some",
    "de": "of", "du": "of the", "à": "to", "au": "to the", "en": "in", "dans": "in", "sur": "on",
    "sous": "under", "avec": "with", "pour": "for", "par": "by", "et": "and", "ou": "or",
    "mais": "but", "est": "is", "sont": "are", "était": "was", "a": "has", "il": "he",
    "elle": "she", "nous": "we", "vous": "you", "ils": "they", "je": "I", "ne": "not",
    "pas": "not", "qui": "who", "que": "that", "chat": "cat", "chien": "dog", "table": "table",
    "maison": "house", "livre": "book", "homme": "man", "femme": "woman", "jour": "day",
    "nuit": "night", "temps": "time", "mange": "eats", "pomme": "apple", "terre": "earth",
    "plage": "beach", "allons": "go", "technologie": "technology", "réussi": "succeeded",
    "ville": "town", "monde": "world", "petit": "small", "grand": "big", "bien": "well",
    "très": "very", "tout": "all", "lui": "him", "son": "his", "sa": "her", "ses": "his",
    "se": "himself", "plus": "more", "comme": "like", "fait": "done", "dit": "said",
}

_EDGE = re.compile(r"^([«“\"(\[]*)(.*?)([.,;:!?…»”\")\]]*)$")


def translate_word(word: str) -> str:
    lead, core, trail = _EDGE.match(word).groups()
    key = core.lower().replace("’", "'")
    if key in GLOSSARY:
        out = GLOSSARY[key]
        if core[:1].isupper():
            out = out[:1].upper() + out[1:]
    else:
        out = f"«{core}»" if core else ""
    return f"{lead}{out}{trail}"


class MockTranslator:
    name = "mock"

    def translate(self, chunk: Chunk) -> ChunkResult:
        sentences, glossary = [], {}
        for sentence in chunk.sentences:
            words = sentence.split()
            units = [[w, translate_word(w)] for w in words]
            sentences.append({"t": " ".join(g for _, g in units), "u": units})
            for w in words[1:]:  # capitalised words after the first one count as names
                core = _EDGE.match(w).group(2)
                if core[:1].isupper() and core.lower() not in GLOSSARY:
                    glossary.setdefault(core, chunk.glossary.get(core, core))
        return ChunkResult(sentences, {k: v for k, v in glossary.items() if k not in chunk.glossary})
