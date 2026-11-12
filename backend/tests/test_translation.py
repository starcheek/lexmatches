import pytest

from app import db, translation
from app.translation import pipeline
from app.translation.align import align
from app.translation.base import ChunkResult, RateLimited
from app.translation.mock import MockTranslator
from tests.helpers import wait_for


def _translate_and_wait(client, h, page_id):
    r = client.post(f"/api/pages/{page_id}/translate", headers=h)
    assert r.status_code in (200, 202), r.text

    def finished():
        p = client.get(f"/api/pages/{page_id}", headers=h).json()
        return p if p["status"] in ("completed", "failed") else None

    return wait_for(finished)


def test_translate_page_with_mock(client, pdf_book):
    user, book = pdf_book
    h = user["headers"]
    page = client.get(f"/api/books/{book['id']}/pages?numbers=1", headers=h).json()[0]
    assert page["progress"] == {"done": 0, "total": 3}
    result = _translate_and_wait(client, h, page["id"])

    assert result["status"] == "completed"
    data = result["translated_data"]
    assert set(data) == {"version", "lines", "sentences", "fullTranslation"} and data["version"] == 2
    assert len(data["lines"]) == len(data["sentences"]) == 3  # one entry per sentence, positional
    # sentences come from the unit's blocks: the chapter heading is its own paragraph
    assert data["sentences"][0]["source"] == "Chapitre premier" and data["sentences"][0]["block"] == "b1"
    first = data["lines"][1]
    assert first[0] == {"original": "Le", "translation": "The"}
    assert " ".join(p["original"] for p in first) == "Le chat est sur la table."
    assert data["sentences"][1] == {"source": "Le chat est sur la table.", "translation": "The cat is on the table.",
                                    "paragraph": 1, "block": "b2"}
    assert data["fullTranslation"].split("\n\n")[1].startswith("The cat is on the table.")
    assert result["progress"] == {"done": 3, "total": 3}

    assert client.get(f"/api/books/{book['id']}/stats", headers=h).json()["translated"] == 1
    # translating a completed page is a no-op
    assert client.post(f"/api/pages/{page['id']}/translate", headers=h).json()["status"] == "completed"


class CountingTranslator(MockTranslator):
    def __init__(self):
        self.chunks = []

    @property
    def seen(self):
        return [s for c in self.chunks for s in c.sentences]

    def translate(self, chunk):
        self.chunks.append(chunk)
        return super().translate(chunk)


def test_resume_only_translates_missing_sentences(client, pdf_book):
    user, book = pdf_book
    page = client.get(f"/api/books/{book['id']}/pages?numbers=2", headers=user["headers"]).json()[0]
    head_line = [{"original": "Chapitre deux", "translation": "Chapter two"}]
    head_sentence = {"source": "Chapitre deux", "translation": "Chapter two", "paragraph": 0}
    done_line = [{"original": "La technologie", "translation": "PRESERVED"}, {"original": "a réussi.", "translation": "x"}]
    done_sentence = {"source": "La technologie a réussi.", "translation": "Tech worked.", "paragraph": 1}
    db.execute(
        "UPDATE pages SET translated_data = %s, status = 'processing' WHERE id = %s",
        (db.json({"version": 2, "lines": [head_line, done_line, None], "sentences": [head_sentence, done_sentence, None],
                  "fullTranslation": ""}), page["id"]),
    )
    counting = CountingTranslator()
    pipeline.translate_page(page["id"], translator=counting)

    assert counting.seen == ["Nous allons à la plage."]
    # the already translated sentence is passed as context, with its translation
    assert counting.chunks[0].context == "Chapitre deux La technologie a réussi."
    assert counting.chunks[0].context_translation == "Chapter two Tech worked."
    row = db.fetch_one("SELECT status, translated_data FROM pages WHERE id = %s", (page["id"],))
    assert row["status"] == "completed"
    assert row["translated_data"]["lines"][1] == done_line
    assert row["translated_data"]["lines"][2][0]["original"] == "Nous"


def test_previous_page_context_and_glossary(client, make_user):
    user = make_user()
    h = user["headers"]
    r = client.post("/api/books/text", headers=h, json={
        "title": "Names", "original_locale": "fr", "target_locale": "en",
        "text": "Hier Pierre et Marie mangent une pomme. Le chat dort."})
    book = r.json()
    db.execute("UPDATE books SET glossary = %s WHERE id = %s", (db.json({"Pierre": "Peter"}), book["id"]))
    page = client.get(f"/api/books/{book['id']}/pages", headers=h).json()[0]
    counting = CountingTranslator()
    pipeline.translate_page(page["id"], translator=counting)

    assert counting.chunks[0].glossary == {"Pierre": "Peter"}  # only terms occurring in the chunk
    glossary = db.fetch_one("SELECT glossary FROM books WHERE id = %s", (book["id"],))["glossary"]
    assert glossary == {"Pierre": "Peter", "Marie": "Marie"}
    pipeline.merge_glossary(book["id"], {"Marie": "Mary", "Paul": "Paul"})  # first decision wins
    glossary = db.fetch_one("SELECT glossary FROM books WHERE id = %s", (book["id"],))["glossary"]
    assert glossary == {"Pierre": "Peter", "Marie": "Marie", "Paul": "Paul"}


class EchoesTranslationOnce(MockTranslator):
    """First answers with chunks that are not the source (unusable), then behaves."""

    def __init__(self, always=False):
        self.calls, self.always = 0, always

    def translate(self, chunk):
        self.calls += 1
        if self.calls == 1 or self.always:
            return ChunkResult([{"t": "Whatever.", "u": [["Something else entirely", "x"]]} for _ in chunk.sentences], {})
        return super().translate(chunk)


def _run(translator, text):
    sents = pipeline.page_sentences(text)
    entries = [None] * len(sents)
    stats = pipeline.translate_sentences(translator, sents, entries, "fr", "en")
    return entries, stats


def test_one_retry_then_sentence_level_fallback():
    t = EchoesTranslationOnce()
    entries, stats = _run(t, "Le chat est sur la table ce soir.")
    assert t.calls == 2 and stats["retries"] == 1 and len(entries[0]["line"]) == 8
    assert "repaired" not in entries[0]["sentence"]

    t = EchoesTranslationOnce(always=True)
    entries, stats = _run(t, "Le chat dort.")
    assert t.calls == 2 and stats["fallbacks"] == 1
    assert entries[0]["line"] == [{"original": "Le chat dort.", "translation": "Whatever."}]
    assert entries[0]["sentence"]["repaired"] is True


def test_align_repairs_deterministically():
    s = "« Qu’avez-vous ? » lui demanda sa femme."
    # exact (modulo quote style), punctuation-only chunks are merged into their neighbours
    pairs, repaired = align(s, [["«", "«"], ["Qu'avez-vous", "what is wrong"], ["?", "?"], ["»", "»"],
                                ["lui demanda", "asked him"], ["sa femme", "his wife"], [".", "."]])
    assert not repaired
    assert [p["original"] for p in pairs] == ["« Qu’avez-vous ? »", "lui demanda", "sa femme."]
    assert pairs[2]["translation"] == "his wife."
    # a dropped/misspelt word is re-attached to its neighbours; originals still cover the sentence exactly
    pairs, repaired = align(s, [["Qu’avez-vous ?", "what's wrong?"], ["lui demande", "asks him"], ["sa", "his"]])
    assert repaired and " ".join(p["original"] for p in pairs) == s
    # chunks about another text are rejected
    assert align("Le chat dort.", [["The cat", "x"], ["sleeps", "y"]]) is None
    # no-space scripts
    pairs, repaired = align("ある日の暮方の事である。", [["ある日の", "one day's"], ["暮方の", "evening's"], ["事である。", "it was."]])
    assert not repaired and "".join(p["original"] for p in pairs) == "ある日の暮方の事である。"


def test_legacy_text_is_segmented_without_blocks():
    # units stored before structured ingestion (blocks NULL) are segmented from their plain text: hard-wrapped
    # lines are re-flowed, typesetter hyphenation removed, "M." is not a sentence end
    text = ("Un jour le baron de Thunder-ten-tronckh, qui était très puis‐\nsant, passa auprès du grand paravent de la "
            "salle et\nchassa Candide. Il vit M. Pangloss.\nCunégonde s'évanouit.")
    sents = pipeline.page_sentences({"original_text": text, "blocks": None})
    assert [s for _, s in sents] == [
        "Un jour le baron de Thunder-ten-tronckh, qui était très puissant, passa auprès du grand paravent de la "
        "salle et chassa Candide.", "Il vit M. Pangloss.", "Cunégonde s'évanouit."]
    assert [s for _, s in pipeline.page_sentences("ある日の暮方の事である。一人の下人が、\n羅生門の下で雨やみを待っていた。")] == [
        "ある日の暮方の事である。", "一人の下人が、羅生門の下で雨やみを待っていた。"]
    assert pipeline.page_sentences("\n \n") == []


class RateLimitedOnce(MockTranslator):
    def __init__(self):
        self.calls = 0

    def translate(self, chunk):
        self.calls += 1
        if self.calls == 1:
            raise RateLimited(retry_after=0)
        return super().translate(chunk)


def test_rate_limit_backoff(client, pdf_book, monkeypatch):
    monkeypatch.setattr(pipeline, "_sleep", lambda s: None)
    user, book = pdf_book
    page = client.get(f"/api/books/{book['id']}/pages?numbers=1", headers=user["headers"]).json()[0]
    translator = RateLimitedOnce()
    pipeline.translate_page(page["id"], translator=translator)
    row = db.fetch_one("SELECT status FROM pages WHERE id = %s", (page["id"],))
    assert row["status"] == "completed" and translator.calls == 2


class Broken(MockTranslator):
    def translate(self, chunk):
        raise RuntimeError("model exploded")


def test_failure_marks_page_failed_and_reset(client, pdf_book, monkeypatch):
    monkeypatch.setattr(pipeline, "_sleep", lambda s: None)
    user, book = pdf_book
    h = user["headers"]
    page = client.get(f"/api/books/{book['id']}/pages?numbers=1", headers=h).json()[0]
    translation.set_translator(Broken())
    try:
        result = _translate_and_wait(client, h, page["id"])
    finally:
        translation.set_translator(None)
    assert result["status"] == "failed" and "model exploded" in result["error"]
    assert client.post(f"/api/books/{book['id']}/reset-failed", headers=h).json() == {"reset": 1}


def test_legacy_line_data_progress():
    legacy = {"lines": [[{"original": "a", "translation": "b"}], None], "fullTranslation": "b"}
    assert pipeline.page_progress({"original_text": "whatever", "blocks": None, "translated_data": legacy}) == \
        {"done": 1, "total": 2}


def test_export_html(client, pdf_book):
    user, book = pdf_book
    h = user["headers"]
    page = client.get(f"/api/books/{book['id']}/pages?numbers=1", headers=h).json()[0]
    _translate_and_wait(client, h, page["id"])
    r = client.post(f"/api/books/{book['id']}/export", json={"pageNumbers": [1, 2]}, headers=h)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert '<span class="original">chat</span>' in r.text and "Test book" in r.text
    assert client.post(f"/api/books/{book['id']}/export", json={"pageNumbers": [2]}, headers=h).status_code == 404


@pytest.mark.skipif(not __import__("os").environ.get("ANTHROPIC_API_KEY"), reason="needs ANTHROPIC_API_KEY")
def test_claude_translator_live():
    from app.config import settings
    from app.translation.claude import ClaudeTranslator

    t = ClaudeTranslator(settings.anthropic_api_key, settings.anthropic_model, settings.anthropic_effort)
    entries, stats = _run(t, "Le chat est sur la table. Il dort.")
    assert all(e and e["line"] for e in entries) and stats["fallbacks"] == 0
