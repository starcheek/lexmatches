"""Page translation job: sentences -> parallel chunks with context + book glossary -> deterministic
alignment (one retry, then a sentence-level fallback) -> positional persistence after every chunk
(resume). Data contract (translated_data v2): docs/ARCHITECTURE.md#translation-data-contract-v2."""
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from app import db
from app.ingest.units import unit_sentences
from app.translation import RateLimited, Translator, get_translator
from app.translation.align import align
from app.translation.base import Chunk

log = logging.getLogger(__name__)
_CJK = re.compile(r"[　-ヿ㐀-鿿＀-￯]")

CHUNK_CHARS = 800
CONTEXT_CHARS = 600
CONCURRENCY = 4
GLOSSARY_CAP = 300         # entries stored per book
GLOSSARY_PER_CHUNK = 40    # entries injected per request (only terms that occur in the chunk)
RATE_LIMIT_RETRIES = 6
FIRST_CHUNK_ALONE = True   # see translate_sentences
_sleep = time.sleep  # patched in tests


def _sentences(page) -> list[tuple[int, str, str]]:
    """(paragraph, sentence, block id) from the unit's structured blocks (app.ingest); a plain string or a row
    without blocks (stored before structured ingestion) is segmented from its text."""
    if isinstance(page, str):
        return unit_sentences(None, page)
    return unit_sentences(page.get("blocks"), page.get("original_text") or "")


def page_sentences(page) -> list[tuple[int, str]]:
    return [(p, s) for p, s, _ in _sentences(page)]


def _weight(text: str) -> int:
    return len(text) * (3 if _CJK.search(text) else 1)  # a CJK character carries ~3x the output


def plan_chunks(sents: list[tuple[int, str]], pending: list[int]) -> list[list[int]]:
    """Consecutive pending sentences in chunks of similar weight, at most ~CHUNK_CHARS: chunks
    run in parallel, so a page takes as long as its largest chunk."""
    total = sum(_weight(sents[i][1]) for i in pending)
    target = total / max(1, -(-total // CHUNK_CHARS))
    chunks, cur, size = [], [], 0
    for i in pending:
        w = _weight(sents[i][1])
        if cur and (i != cur[-1] + 1 or size + w / 2 > target):
            chunks.append(cur)
            cur, size = [], 0
        cur.append(i)
        size += w
    return chunks + [cur] if cur else chunks


def relevant_glossary(glossary: dict, text: str) -> dict:
    """Entries whose words (stems, to survive inflection) all occur in `text`."""
    low = text.casefold()
    hits = {k: v for k, v in glossary.items()
            if all(w.casefold()[: max(4, len(w) - 2)] in low for w in k.split())}
    return dict(list(hits.items())[:GLOSSARY_PER_CHUNK])


def _entry(source: str, paragraph: int, result, fallback: bool = False) -> dict | None:
    t = str((result or {}).get("t") or "").strip() if isinstance(result, dict) else ""
    aligned = align(source, result.get("u")) if t else None
    if aligned is None:
        if not (fallback and t):
            return None
        aligned = ([{"original": source, "translation": t}], True)
    sentence = {"source": source, "translation": t, "paragraph": paragraph}
    if aligned[1]:
        sentence["repaired"] = True
    return {"line": aligned[0], "sentence": sentence}


def _call(translator: Translator, chunk: Chunk):
    for hit in range(RATE_LIMIT_RETRIES + 1):
        try:
            return translator.translate(chunk)
        except RateLimited as e:
            if hit == RATE_LIMIT_RETRIES:
                raise
            wait = min(max(e.retry_after, 5.0) * (hit + 1), 60.0)
            log.info("rate limited, backing off %.0fs", wait)
            _sleep(wait)


def _tail(pairs: list[tuple[str, str | None]]) -> tuple[str, str]:
    """Last sentences up to CONTEXT_CHARS -> (source, translation or "" if any is unknown)."""
    picked, size = [], 0
    for src, tr in reversed(pairs):
        if picked and size + len(src) > CONTEXT_CHARS:
            break
        picked.insert(0, (src, tr))
        size += len(src)
    translated = all(tr for _, tr in picked)
    return " ".join(s for s, _ in picked), " ".join(t for _, t in picked) if translated else ""


def translate_sentences(translator: Translator, sents: list[tuple[int, str]], entries: list,
                        source_locale: str, target_locale: str, previous: tuple[str, str] = ("", ""),
                        glossary=lambda: {}, on_chunk=lambda new_terms: None) -> dict:
    """Fill `entries[i]` (None = pending) in place. `glossary()` returns the current book glossary;
    `on_chunk(new_terms)` runs on the calling thread after each finished chunk (persist, merge)."""
    stats = {"calls": 0, "retries": 0, "fallbacks": 0}

    def run(idxs: list[int]):
        first = idxs[0]
        before = [(s, (entries[j] or {}).get("sentence", {}).get("translation")) for j, (_, s) in enumerate(sents[:first])]
        context, context_tr = _tail(before) if before else previous
        text = context + " " + " ".join(sents[i][1] for i in idxs)
        out, terms, todo, last = {}, {}, idxs, {}
        for attempt in range(2):
            chunk = Chunk([sents[i][1] for i in todo], [sents[i][0] for i in todo], source_locale, target_locale,
                          relevant_glossary(glossary(), text), context, context_tr)
            try:
                result = _call(translator, chunk)
            except Exception:
                if attempt:
                    raise
                stats["retries"] += 1
                continue
            stats["calls"] += 1
            for k, v in result.glossary.items():
                terms.setdefault(k, v)
            for i, res in zip(todo, result.sentences):
                last[i] = res
                out[i] = _entry(sents[i][1], sents[i][0], res)
            todo = [i for i in idxs if out.get(i) is None]
            if not todo:
                break
            if not attempt:
                stats["retries"] += 1
        for i in todo:
            out[i] = _entry(sents[i][1], sents[i][0], last.get(i), fallback=True)
            stats["fallbacks"] += 1
        return out, terms

    chunks = plan_chunks(sents, [i for i, e in enumerate(entries) if e is None])
    # A book's first page has no glossary yet: translate its first chunk alone so the others start
    # with its names/terms (and its translation as context) instead of inventing their own.
    rounds = [chunks[:1], chunks[1:]] if FIRST_CHUNK_ALONE and len(chunks) > 1 and not glossary() else [chunks]
    failure: Exception | None = None
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        for batch in rounds:
            for fut in as_completed([pool.submit(run, c) for c in batch]):
                try:
                    out, terms = fut.result()
                except Exception as e:
                    failure = failure or e
                    continue
                for i, entry in out.items():
                    if entry is not None:
                        entries[i] = entry
                on_chunk(terms)
    if failure is not None:
        raise failure
    if any(e is None for e in entries):
        raise RuntimeError("some sentences could not be translated")
    return stats


def build_data(sents: list[tuple[int, str]], entries: list, blocks: list[str] | None = None) -> dict:
    lines = [e["line"] if e else None for e in entries]
    sentences = [e["sentence"] if e else None for e in entries]
    for s, block in zip(sentences, blocks or []):
        if s is not None:
            s["block"] = block  # IR block id in pages.blocks (type, heading level, ...)
    paras: dict[int, list[str]] = {}
    for (p, _), s in zip(sents, sentences):
        if s:
            paras.setdefault(p, []).append(s["translation"])
    full = "\n\n".join(" ".join(ts) for _, ts in sorted(paras.items()))
    return {"version": 2, "lines": lines, "sentences": sentences, "fullTranslation": full}


def _stored_entries(data, sents: list[tuple[int, str]]) -> list:
    """Entries from stored v2 data, kept only where the stored source matches the current sentence."""
    entries: list = [None] * len(sents)
    if isinstance(data, dict) and data.get("version") == 2:
        for i, (line, s) in enumerate(zip(data.get("lines") or [], data.get("sentences") or [])):
            if i < len(sents) and line and s and s.get("source") == sents[i][1]:
                entries[i] = {"line": line, "sentence": s}
    return entries


def page_progress(page: dict) -> dict:
    data = page.get("translated_data") if isinstance(page.get("translated_data"), dict) else {}
    lines = data.get("lines")
    if isinstance(lines, list) and (data.get("version") == 2 or lines):  # v2, or legacy line-based data
        return {"done": sum(1 for line in lines if line), "total": len(lines)}
    return {"done": 0, "total": len(page_sentences(page))}


def merge_glossary(book_id, terms: dict) -> None:
    """Add new terms; existing entries are never rewritten (first decision wins, safe in parallel)."""
    terms = {k: v for k, v in terms.items() if k and v and len(k) <= 60 and len(v) <= 80}
    if not terms:
        return
    with db.connection() as conn:
        row = conn.execute("SELECT glossary FROM books WHERE id = %s FOR UPDATE", (book_id,)).fetchone()
        current = (row or {}).get("glossary") or {}
        new = {k: v for k, v in terms.items() if k not in current}
        new = dict(list(new.items())[: max(0, GLOSSARY_CAP - len(current))])
        if new:
            conn.execute("UPDATE books SET glossary = %s || glossary WHERE id = %s", (db.json(new), book_id))


def _previous_page(book_id, page_number: int) -> tuple[str, str]:
    prev = db.fetch_one("SELECT original_text, blocks, translated_data FROM pages WHERE book_id = %s"
                        " AND page_number = %s", (book_id, page_number - 1))
    if not prev:
        return "", ""
    sents = page_sentences(prev)
    stored = _stored_entries(prev["translated_data"], sents)
    return _tail([(s, (e or {}).get("sentence", {}).get("translation")) for (_, s), e in zip(sents, stored)])


def translate_page(page_id: str, translator: Translator | None = None) -> None:
    row = db.fetch_one(
        "SELECT p.original_text, p.blocks, p.translated_data, p.page_number, p.book_id, b.original_locale,"
        " b.target_locale, b.user_id FROM pages p JOIN books b ON b.id = p.book_id WHERE p.id = %s",
        (page_id,),
    )
    if row is None:
        return
    triples = _sentences(row)
    sents, block_ids = [(p, s) for p, s, _ in triples], [b for _, _, b in triples]
    entries = _stored_entries(row["translated_data"], sents)

    def persist(status: str) -> None:
        with db.connection() as conn:
            fresh = conn.execute("SELECT translated_data FROM pages WHERE id = %s FOR UPDATE", (page_id,)).fetchone()
            for i, e in enumerate(_stored_entries((fresh or {}).get("translated_data"), sents)):
                entries[i] = entries[i] or e  # keep work a concurrent run may have stored
            conn.execute("UPDATE pages SET translated_data = %s, status = %s, error = NULL WHERE id = %s",
                         (db.json(build_data(sents, entries, block_ids)), status, page_id))

    def on_chunk(terms: dict) -> None:
        merge_glossary(row["book_id"], terms)
        persist("processing")

    def glossary() -> dict:
        return (db.fetch_one("SELECT glossary FROM books WHERE id = %s", (row["book_id"],)) or {}).get("glossary") or {}

    db.execute("UPDATE pages SET status = 'processing', error = NULL WHERE id = %s", (page_id,))
    try:
        stats = translate_sentences(
            translator or get_translator(), sents, entries, row["original_locale"], row["target_locale"],
            _previous_page(row["book_id"], row["page_number"]), glossary, on_chunk)
        persist("completed")
        db.execute(
            "UPDATE users SET daily_translations_count = CASE WHEN last_translation_date = CURRENT_DATE"
            " THEN daily_translations_count + 1 ELSE 1 END, last_translation_date = CURRENT_DATE WHERE id = %s",
            (row["user_id"],),
        )
        log.info("page %s translated (%d sentences, %s)", page_id, len(sents), stats)
    except Exception as e:
        log.exception("translating page %s failed", page_id)  # finished chunks are already persisted
        db.execute("UPDATE pages SET status = 'failed', error = %s WHERE id = %s", (str(e)[:500], page_id))
