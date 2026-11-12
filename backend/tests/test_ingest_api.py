"""End-to-end: every input format through the API -> reading units -> mock translation from the unit's blocks;
paste/URL preview + commit with overrides; scanned / DRM / unsupported uploads."""
import io
import zipfile
from pathlib import Path

import pytest

from app.routers import books as books_router
from tests.helpers import make_pdf, wait_for

FIX = Path(__file__).parent / "fixtures" / "ingest"


def _odt() -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("mimetype", "application/vnd.oasis.opendocument.text")
        z.writestr("content.xml", '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
                   'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"><office:body><office:text>'
                   '<text:h text:outline-level="1">Chapitre premier</text:h><text:p>Le chat dort sur la table. '
                   'Il fait beau.</text:p></office:text></office:body></office:document-content>')
    return out.getvalue()


FORMATS = {
    "pdf": lambda: (FIX / "pdf" / "fr_verne_novel.pdf").read_bytes(),
    "epub": lambda: (FIX / "reflow" / "fr_candide.epub").read_bytes(),
    "fb2": lambda: (FIX / "reflow" / "ru_dama_handbuilt.fb2").read_bytes(),
    "docx": lambda: (FIX / "reflow" / "fr_user_notes.docx").read_bytes(),
    "odt": _odt,
    "rtf": lambda: rb"{\rtf1\ansi\ansicpg1252 Le ch\'e2teau \'e9tait vide.\par Il pleuvait sur la ville depuis le matin.\par}",
    "markdown": lambda: (FIX / "reflow" / "fr_horla_frontmatter.md").read_bytes(),
    "txt": lambda: (FIX / "reflow" / "ru_dama_librustyle.cp1251.txt").read_bytes(),
    "html": lambda: (FIX / "reflow" / "news_ru_globalvoices.html").read_bytes(),
}


def _upload(client, user, data, name="book.bin", locale="french"):
    return client.post("/api/books", headers=user["headers"],
                       data={"title": "Livre", "original_locale": locale, "target_locale": "english"},
                       files={"file": (name, data, "application/octet-stream")})


def _wait_book(client, user, book_id):
    return wait_for(lambda: (lambda b: b if b["status"] in ("completed", "failed") else None)(
        client.get(f"/api/books/{book_id}", headers=user["headers"]).json()), timeout=60)


@pytest.mark.parametrize("fmt", sorted(FORMATS))
def test_upload_each_format_units_and_translation(client, make_user, fmt):
    user = make_user()
    h = user["headers"]
    r = _upload(client, user, FORMATS[fmt](), name="whatever.pdf")  # the extension is ignored
    assert r.status_code == 201, r.text
    book = _wait_book(client, user, r.json()["id"])
    assert book["status"] == "completed", book
    assert book["source_format"] == fmt and book["source"] == ("pdf" if fmt == "pdf" else "text")
    assert book["total_pages"] >= 1 and isinstance(book["warnings"], list)
    pages = client.get(f"/api/books/{book['id']}/pages", headers=h).json()
    assert [p["page_number"] for p in pages] == list(range(1, book["total_pages"] + 1))
    assert all(p["original_text"] for p in pages) and all(len(p["original_text"]) < 4000 for p in pages)
    first = pages[0]
    assert (first["source_page_start"] is not None) == (fmt == "pdf")
    blocks = {b["id"]: b for b in first["blocks"]}
    r = client.post(f"/api/pages/{first['id']}/translate", headers=h)
    assert r.status_code in (200, 202)
    page = wait_for(lambda: (lambda p: p if p["status"] in ("completed", "failed") else None)(
        client.get(f"/api/pages/{first['id']}", headers=h).json()), timeout=60)
    assert page["status"] == "completed", page.get("error")
    sents = page["translated_data"]["sentences"]
    assert sents and all(s["block"] in blocks and blocks[s["block"]]["removed"] is None for s in sents)
    for s in sents:  # every translated sentence is an exact slice of its block
        b = blocks[s["block"]]
        assert s["source"] in b["text"] and b["role"] == "body"
    report = client.get(f"/api/books/{book['id']}/ingest", headers=h).json()
    assert report["meta"]["source_format"] == fmt and report["units"] == book["total_pages"] and "audit" in report


def test_pdf_units_keep_source_pages_and_pdf_view(client, make_user):
    user = make_user()
    r = _upload(client, user, (FIX / "pdf" / "fr_verne_novel.pdf").read_bytes())
    book = _wait_book(client, user, r.json()["id"])
    pages = client.get(f"/api/books/{book['id']}/pages", headers=user["headers"]).json()
    spans = [(p["source_page_start"], p["source_page_end"]) for p in pages]
    assert spans[0][0] >= 1 and all(a <= b for a, b in spans) and spans[-1][1] <= 18
    assert any(p["chapter_title"] for p in pages)
    assert client.get(f"/api/books/{book['id']}/pdf", headers=user["headers"]).content.startswith(b"%PDF")
    hits = client.get(f"/api/books/{book['id']}/search", params={"q": "Phileas"}, headers=user["headers"]).json()
    assert hits and all(1 <= h["pageNumber"] <= book["total_pages"] for h in hits)


def test_scanned_pdf_fails_with_clear_message(client, make_user):
    user = make_user()
    r = _upload(client, user, make_pdf(["", ""], image_only=(0, 1)))
    book = _wait_book(client, user, r.json()["id"])
    assert book["status"] == "failed" and "scanned" in book["error"].lower()


def test_partially_scanned_pdf_completes_with_warning(client, make_user):
    user = make_user()
    pdf = make_pdf(["Le chat est sur la table. Il mange une pomme.", "", "Le chien dort sous la table."], image_only=(1,))
    book = _wait_book(client, user, _upload(client, user, pdf).json()["id"])
    assert book["status"] == "completed"
    assert any(w["code"] == "scanned_pages" and w["pages"] == [2] for w in book["warnings"])


def test_drm_and_unsupported_uploads_rejected_immediately(client, make_user):
    user = make_user()
    epub = (FIX / "reflow" / "fr_candide.epub").read_bytes()
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(epub)) as src, zipfile.ZipFile(out, "w") as z:
        for info in src.infolist():
            z.writestr(info, src.read(info.filename))
        z.writestr("META-INF/rights.xml", "<rights/>")
    r = _upload(client, user, out.getvalue())
    assert r.status_code == 422 and r.json()["code"] == "drm_protected" and "DRM" in r.json()["detail"]
    mobi = bytearray(400)
    mobi[60:68] = b"BOOKMOBI"
    r = _upload(client, user, bytes(mobi))
    assert r.status_code == 415 and "EPUB" in r.json()["detail"]
    assert client.get("/api/books", headers=user["headers"]).json() == []  # nothing was created


def test_legacy_text_endpoint_long_text(client, make_user):
    user = make_user()
    para = "Le chat dort sur la table pendant que la pluie tombe sur la ville endormie. " * 12
    text = "\n\n".join(para for _ in range(30))  # ~27 000 chars, over the old 10 000 cap
    r = client.post("/api/books/text", headers=user["headers"], json={
        "title": "Long", "original_locale": "french", "target_locale": "english", "text": text})
    assert r.status_code == 201, r.text
    book = r.json()
    assert book["status"] == "completed" and book["total_pages"] >= 10 and book["source_format"] == "paste"


def test_paste_preview_then_commit_with_overrides(client, make_user):
    user = make_user()
    h = user["headers"]
    text = (FIX / "reflow" / "wp_fr_baguette_ctrl_a.txt").read_text(encoding="utf-8")
    r = client.post("/api/books/preview", headers=h, json={"text": text})
    assert r.status_code == 200, r.text
    pv = r.json()
    assert pv["language_detected"] == "fr" and pv["language_confidence"] > 0.9 and "Baguette" in pv["title"]
    removed = [b for b in pv["blocks"] if b["removed"]]
    kept = [b for b in pv["blocks"] if not b["removed"]]
    assert removed and kept and pv["size"]["kept_blocks"] == len(kept) and pv["size"]["units"] >= 1
    assert client.get("/api/books", headers=h).json() == []  # preview saves nothing
    restore, drop = removed[0], next(b for b in kept if b["type"] == "paragraph")
    r = client.post("/api/books/import", headers=h, json={
        "text": text, "title": "Ma baguette", "original_locale": "french", "target_locale": "english",
        "restore": [restore["id"]], "remove": [drop["id"]]})
    assert r.status_code == 201, r.text
    book = r.json()
    assert book["title"] == "Ma baguette" and book["status"] == "completed" and book["source_format"] == "paste"
    pages = client.get(f"/api/books/{book['id']}/pages", headers=h).json()
    blocks = {b["id"]: b for p in pages for b in p["blocks"]}
    assert blocks[restore["id"]]["removed"] is None and blocks[drop["id"]]["removed"] == "user"
    full = "\n".join(p["original_text"] for p in pages)
    assert restore["text"] in full and drop["text"] not in full


def test_rich_paste_and_url_preview_commit(client, make_user, monkeypatch):
    user = make_user()
    h = user["headers"]
    html = (FIX / "reflow" / "wp_fr_baguette_ctrl_a.html").read_text(encoding="utf-8")
    pv = client.post("/api/books/preview", headers=h, json={"html": html, "text": "ignored when html is given"}).json()
    assert pv["source_format"] == "paste_html" and pv["size"]["kept_blocks"] > 10
    page = (FIX / "reflow" / "news_ru_globalvoices.html").read_bytes()
    current = {"body": page}
    monkeypatch.setattr(books_router, "fetch", lambda url: (current["body"], url))
    url = "https://ru.globalvoices.org/2026/11/10/131471/"
    pv = client.post("/api/books/preview", headers=h, json={"url": url}).json()
    assert pv["source_format"] == "url" and pv["language"] == "ru" and pv["content_hash"]
    current["body"] = page.replace(b"</body>", b"<p>changed</p></body>")
    r = client.post("/api/books/import", headers=h, json={"url": url, "content_hash": pv["content_hash"],
                                                          "original_locale": "russian", "target_locale": "english"})
    assert r.status_code == 409 and r.json()["code"] == "content_changed"
    current["body"] = page
    r = client.post("/api/books/import", headers=h, json={"url": url, "content_hash": pv["content_hash"],
                                                          "original_locale": "russian", "target_locale": "english"})
    assert r.status_code == 201 and r.json()["title"] == pv["title"]


def test_url_ssrf_is_refused_by_the_api(client, make_user):
    user = make_user()
    r = client.post("/api/books/preview", headers=user["headers"], json={"url": "http://169.254.169.254/latest/"})
    assert r.status_code == 400 and r.json()["code"] == "url_blocked"
    r = client.post("/api/books/preview", headers=user["headers"], json={"text": "   "})
    assert r.status_code == 400
