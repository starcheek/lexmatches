import uuid

ADMIN = {"Authorization": "Bearer test-admin-token"}


def test_test_account_lifecycle(client, pdf_book):
    email = f"tester-{uuid.uuid4().hex[:8]}@example.com"
    assert client.post("/api/admin/users", json={"email": email}).status_code == 401

    made = client.post("/api/admin/users", headers=ADMIN, json={"email": email}).json()
    assert made["email"] == email and len(made["password"]) >= 8
    assert client.post("/api/admin/users", headers=ADMIN, json={"email": email}).status_code == 409
    assert client.post("/api/admin/users", headers=ADMIN, json={"email": "nope"}).status_code == 422
    assert client.post("/api/auth/login", json={"email": email, "password": made["password"]}).status_code == 200

    new = client.post(f"/api/admin/users/{made['id']}/password", headers=ADMIN, json={}).json()["password"]
    assert client.post("/api/auth/login", json={"email": email, "password": made["password"]}).status_code == 401
    assert client.post("/api/auth/login", json={"email": email, "password": new}).status_code == 200

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
