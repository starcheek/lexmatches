from tests.helpers import make_pdf, wait_for


def test_upload_process_pages(client, pdf_book):
    user, book = pdf_book
    h = user["headers"]
    assert book["total_pages"] == 2

    pages = client.get(f"/api/books/{book['id']}/pages", headers=h).json()
    assert [p["page_number"] for p in pages] == [1, 2]
    assert "Le chat est sur la table." in pages[0]["original_text"]
    assert pages[0]["status"] == "pending"
    assert [b["type"] for b in pages[0]["blocks"]] == ["heading", "paragraph"]  # reading unit = chapter
    assert pages[0]["chapter_title"] == "Chapitre premier"
    assert (pages[1]["source_page_start"], pages[1]["source_page_end"]) == (2, 2)
    assert pages[0]["translated_data"] is None
    assert pages[0]["progress"] == {"done": 0, "total": 3}

    subset = client.get(f"/api/books/{book['id']}/pages?numbers=2,9", headers=h).json()
    assert [p["page_number"] for p in subset] == [2]

    listed = client.get("/api/books", headers=h).json()
    assert [b["id"] for b in listed] == [book["id"]]

    pdf = client.get(f"/api/books/{book['id']}/pdf", headers=h)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")

    assert client.get(f"/api/books/{book['id']}/stats", headers=h).json() == {"translated": 0, "total": 2}


def test_search_and_last_read_page(client, pdf_book):
    user, book = pdf_book
    h = user["headers"]
    results = client.get(f"/api/books/{book['id']}/search", params={"q": "plage"}, headers=h).json()
    assert len(results) == 1 and results[0]["pageNumber"] == 2 and results[0]["matchCount"] == 1

    r = client.patch(f"/api/books/{book['id']}", json={"last_read_page": 2}, headers=h)
    assert r.status_code == 200 and r.json()["last_read_page"] == 2


def test_text_book(client, make_user):
    user = make_user()
    r = client.post(
        "/api/books/text",
        headers=user["headers"],
        json={"title": "Pasted", "original_locale": "french", "target_locale": "english",
              "text": "Bonjour le monde.\nComment allez-vous ?"},
    )
    assert r.status_code == 201
    book = r.json()
    assert book["status"] == "completed" and book["total_pages"] == 1 and book["source"] == "text"
    pages = client.get(f"/api/books/{book['id']}/pages", headers=user["headers"]).json()
    assert pages[0]["original_text"].startswith("Bonjour")


def test_rejects_unsupported_file(client, make_user):
    user = make_user()
    r = client.post(
        "/api/books",
        headers=user["headers"],
        data={"title": "Nope", "original_locale": "french", "target_locale": "english"},
        files={"file": ("x.pdf", b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + bytes(64), "application/pdf")},
    )
    assert r.status_code == 415 and r.json()["code"] == "unsupported_format"


def test_units_span_pdf_pages(client, make_user):
    user = make_user()
    pdf = make_pdf(["Première page.", "", "Troisième page."])
    r = client.post(
        "/api/books", headers=user["headers"],
        data={"title": "Gaps", "original_locale": "french", "target_locale": "english"},
        files={"file": ("gaps.pdf", pdf, "application/pdf")},
    )
    book_id = r.json()["id"]
    wait_for(lambda: client.get(f"/api/books/{book_id}", headers=user["headers"]).json()["status"] == "completed")
    pages = client.get(f"/api/books/{book_id}/pages", headers=user["headers"]).json()
    # reading units are built from structure: one short text over three PDF pages is one unit
    assert [(p["page_number"], p["original_text"], p["source_page_start"], p["source_page_end"]) for p in pages] == [
        (1, "Première page.\n\nTroisième page.", 1, 3)]


def test_delete_book(client, pdf_book):
    user, book = pdf_book
    h = user["headers"]
    assert client.delete(f"/api/books/{book['id']}", headers=h).status_code == 204
    assert client.get(f"/api/books/{book['id']}", headers=h).status_code == 404
