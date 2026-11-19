import re
import uuid

from tests.helpers import wait_for

ADMIN = {"Authorization": "Bearer test-admin-token"}


def test_test_account_lifecycle(client, pdf_book):
    email = f"tester-{uuid.uuid4().hex[:8]}@example.com"
    assert client.post("/api/admin/users", json={"email": email}).status_code == 401

    made = client.post("/api/admin/users", headers=ADMIN, json={"email": email}).json()
    assert made["email"] == email and len(made["password"]) >= 8
    assert client.post("/api/admin/users", headers=ADMIN, json={"email": email}).status_code == 409
    assert client.post("/api/admin/users", headers=ADMIN, json={"email": "nope"}).status_code == 422
    assert client.post("/api/auth/login", json={"email": email, "password": made["password"]}).status_code == 200

    assert re.fullmatch(r"[a-z]+-[a-z]+-\d{3}", made["password"])  # easy to type: maple-river-482

    new = client.post(f"/api/admin/users/{made['id']}/password", headers=ADMIN, json={}).json()["password"]
    assert client.post("/api/auth/login", json={"email": email, "password": made["password"]}).status_code == 401
    assert client.post("/api/auth/login", json={"email": email, "password": new}).status_code == 200

    # the owner's own password, also short and simple ones
    r = client.post(f"/api/admin/users/{made['id']}/password", headers=ADMIN, json={"password": " lex2026 "})
    assert r.json() == {"password": "lex2026"}
    assert client.post("/api/auth/login", json={"email": email, "password": "lex2026"}).status_code == 200
    assert client.post(f"/api/admin/users/{made['id']}/password", headers=ADMIN, json={"password": "abc"}).status_code == 400
    custom = client.post("/api/admin/users", headers=ADMIN,
                         json={"email": f"c-{uuid.uuid4().hex[:8]}@example.com", "password": "reader1"}).json()
    assert custom["password"] == "reader1"
    client.delete(f"/api/admin/users/{custom['id']}", headers=ADMIN)

    # the list shows usage; deleting an account takes its books with it
    owner, book = pdf_book
    row = next(u for u in client.get("/api/admin/users", headers=ADMIN).json() if u["id"] == owner["id"])
    assert row["books"] == 1 and row["email"] == owner["email"]
    assert client.delete(f"/api/admin/users/{owner['id']}", headers=ADMIN).status_code == 204
    assert client.get(f"/api/books/{book['id']}", headers=owner["headers"]).status_code == 401
    assert client.delete(f"/api/admin/users/{owner['id']}", headers=ADMIN).status_code == 404
    assert client.delete(f"/api/admin/users/{made['id']}", headers=ADMIN).status_code == 204


def test_signup_switch(client):
    creds = lambda: {"email": f"s-{uuid.uuid4().hex[:8]}@example.com", "password": "correct-horse-1"}  # noqa: E731
    try:
        assert client.put("/api/admin/settings", headers=ADMIN, json={"signup_open": False}).json() == {"signup_open": False}
        r = client.post("/api/auth/signup", json=creds())
        assert r.status_code == 403 and "closed" in r.json()["detail"]
    finally:
        client.put("/api/admin/settings", headers=ADMIN, json={"signup_open": True})
    assert client.get("/api/admin/settings", headers=ADMIN).json() == {"signup_open": True}
    assert client.post("/api/auth/signup", json=creds()).status_code == 200


def test_books_share_and_logs(client, pdf_book, make_user):
    owner, book = pdf_book
    h = owner["headers"]
    first = client.get(f"/api/books/{book['id']}/pages", headers=h).json()[0]
    client.post(f"/api/pages/{first['id']}/translate", headers=h)
    wait_for(lambda: client.get(f"/api/pages/{first['id']}", headers=h).json()["status"] == "completed")

    assert client.get("/api/admin/books").status_code == 401
    row = next(b for b in client.get("/api/admin/books", headers=ADMIN).json() if b["id"] == book["id"])
    assert row["email"] == owner["email"] and row["total_pages"] == 2 and row["translated"] == [1]

    # the other account gets its own copy with the translation, and the PDF
    other = make_user()
    share = f"/api/admin/books/{book['id']}/share"
    assert client.post(share, headers=ADMIN, json={"user_ids": []}).status_code == 400
    assert client.post(share, headers=ADMIN, json={"user_ids": [str(uuid.uuid4())]}).status_code == 404
    made = client.post(share, headers=ADMIN, json={"user_ids": [other["id"]]})
    assert made.status_code == 201, made.text
    copy_id = made.json()["copies"][0]["book_id"]
    assert copy_id != book["id"]
    mine = client.get("/api/books", headers=other["headers"]).json()
    assert [b["id"] for b in mine] == [copy_id] and mine[0]["title"] == "Test book"
    pages = client.get(f"/api/books/{copy_id}/pages", headers=other["headers"]).json()
    assert [p["status"] for p in pages] == ["completed", "pending"]
    assert pages[0]["translated_data"] == client.get(f"/api/pages/{first['id']}", headers=h).json()["translated_data"]
    assert client.get(f"/api/books/{copy_id}/pdf", headers=other["headers"]).status_code == 200
    # independent: the owner deleting theirs leaves the copy
    assert client.delete(f"/api/books/{book['id']}", headers=h).status_code in (200, 204)
    assert client.get(f"/api/books/{copy_id}", headers=other["headers"]).status_code == 200

    import logging
    logging.getLogger("app.test").warning("marker-%s", copy_id)
    assert client.get("/api/admin/logs").status_code == 401
    body = client.get("/api/admin/logs", headers=ADMIN, params={"q": f"marker-{copy_id}"}).json()
    assert [(line["level"], line["logger"]) for line in body["lines"]] == [("WARNING", "app.test")]
    assert client.get("/api/admin/logs", headers=ADMIN, params={"q": f"marker-{copy_id}", "level": "error"}).json()["lines"] == []
