"""Deterministic alignment of the model's chunks onto the exact source sentence.

The model echoes each chunk's source text. We never trust that echo for display: chunk
boundaries are mapped onto the real sentence, so `original`s are always exact slices of the
source that cover it in order. If the echo differs from the source (typo, dropped word,
normalised quote) the boundaries are mapped through a character diff and the sentence is
flagged `repaired`. Punctuation-only chunks are merged into their neighbour.
"""
from difflib import SequenceMatcher

MIN_SIMILARITY = 0.6  # below this the response is about another text: treat as broken
_OPENING = set("«“‘„([{¿¡—–-\"'")
_FOLD = str.maketrans({"’": "'", "‘": "'", "´": "'", "`": "'", "“": '"', "”": '"', "«": '"', "»": '"',
                       "„": '"', "—": "-", "–": "-", "‐": "-", " ": " "})


def _fold(ch: str) -> str:
    low = ch.lower()
    return (low if len(low) == 1 else ch).translate(_FOLD)


def _map(pos: int, opcodes: list) -> int:
    for _tag, i1, i2, j1, j2 in opcodes:
        if i1 <= pos < i2:
            return j1 + (pos - i1) * (j2 - j1) // (i2 - i1)
    return opcodes[-1][4] if opcodes else 0


def _has_word(text: str) -> bool:
    return any(ch.isalnum() for ch in text)


def align(sentence: str, units: list) -> tuple[list[dict], bool] | None:
    """`units` = [[source_chunk, gloss], ...]. Returns (pairs, repaired) or None if unusable."""
    units = [(str(u[0]), str(u[1]) if len(u) > 1 else "") for u in units or [] if u and str(u[0]).strip()]
    src_idx = [i for i, ch in enumerate(sentence) if not ch.isspace()]
    src = "".join(_fold(sentence[i]) for i in src_idx)
    if not units or not src:
        return None
    pieces = ["".join(_fold(c) for c in u[0] if not c.isspace()) for u in units]
    model = "".join(pieces)
    bounds, acc = [0], 0
    for p in pieces:
        acc += len(p)
        bounds.append(acc)
    repaired = model != src
    if repaired:
        matcher = SequenceMatcher(None, model, src, autojunk=False)
        if matcher.ratio() < MIN_SIMILARITY:
            return None
        ops = matcher.get_opcodes()
        bounds = [0] + [_map(b, ops) for b in bounds[1:-1]] + [len(src)]
        bounds = [max(bounds[: k + 1]) for k in range(len(bounds))]  # keep monotone
    offset = lambda q: src_idx[q] if q < len(src_idx) else len(sentence)  # noqa: E731
    spans = [[offset(bounds[k]), offset(bounds[k + 1]), units[k][1]] for k in range(len(units))]
    spans = [s for s in spans if sentence[s[0]:s[1]].strip()]
    repaired = repaired or len(spans) != len(units)

    merged: list[list] = []
    pending = None  # punctuation waiting for the next word (opening quote, leading dash)
    for span in spans:
        text = sentence[span[0]:span[1]].strip()
        if _has_word(text):
            if pending:
                span[0], span[2] = pending[0], _glue(pending[2], span[2], before=True)
                pending = None
            merged.append(span)
        elif merged and not (text[0] in _OPENING and span is not spans[-1]):
            merged[-1][1], merged[-1][2] = span[1], _glue(span[2], merged[-1][2], before=False)
        else:
            pending = [pending[0], span[1], pending[2] + span[2]] if pending else span
    if pending:
        merged.append(pending)
    pairs = [{"original": sentence[a:b].strip(), "translation": g.strip()} for a, b, g in merged]
    return pairs, repaired


def _glue(punct_gloss: str, gloss: str, before: bool) -> str:
    """Attach a merged punctuation chunk's gloss (if it is just punctuation) to its neighbour."""
    p, g = punct_gloss.strip(), gloss.strip()
    if not p or _has_word(p) or (g.startswith(p) if before else g.endswith(p)):
        return g if not _has_word(p) else (f"{p} {g}" if before else f"{g} {p}")
    return p + g if before else g + p
