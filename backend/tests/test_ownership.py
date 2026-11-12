"""Every book/page endpoint must hide other users' data (replaces the former row-level security)."""


def test_other_user_cannot_access_book(client, pdf_book, make_user):
    owner, book = pdf_book
    intruder = make_user()["headers"]
    bid = book["id"]
    page = client.get(f"/api/books/{bid}/pages?numbers=1", headers=owner["headers"]).json()[0]

    assert client.get("/api/books", headers=intruder).json() == []
    checks = [
        client.get(f"/api/books/{bid}", headers=intruder),
        client.patch(f"/api/books/{bid}", json={"last_read_page": 2}, headers=intruder),
        client.get(f"/api/books/{bid}/pages", headers=intruder),
        client.get(f"/api/books/{bid}/pdf", headers=intruder),
        client.get(f"/api/books/{bid}/stats", headers=intruder),
        client.get(f"/api/books/{bid}/search", params={"q": "chat"}, headers=intruder),
        client.post(f"/api/books/{bid}/reset-failed", headers=intruder),
        client.post(f"/api/books/{bid}/export", json={"pageNumbers": [1]}, headers=intruder),
        client.get(f"/api/pages/{page['id']}", headers=intruder),
        client.post(f"/api/pages/{page['id']}/translate", headers=intruder),
        client.post("/api/reading-sessions", json={"book_id": bid, "page_number": 1, "translation_toggle_clicks": 3},
                    headers=intruder),
        client.delete(f"/api/books/{bid}", headers=intruder),
    ]
    assert [r.status_code for r in checks] == [404] * len(checks)
    # owner still has everything
    assert client.get(f"/api/books/{bid}", headers=owner["headers"]).status_code == 200
    assert client.get(f"/api/pages/{page['id']}", headers=owner["headers"]).json()["status"] == "pending"
