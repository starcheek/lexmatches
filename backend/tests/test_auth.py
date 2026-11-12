def test_signup_login_me(client, make_user):
    user = make_user()
    r = client.get("/api/auth/me", headers=user["headers"])
    assert r.status_code == 200
    assert r.json()["email"] == user["email"]

    r = client.post("/api/auth/login", json={"email": user["email"].upper(), "password": user["password"]})
    assert r.status_code == 200
    token = r.json()["token"]
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_duplicate_signup_rejected(client, make_user):
    user = make_user()
    r = client.post("/api/auth/signup", json={"email": user["email"], "password": "another-pass-1"})
    assert r.status_code == 409


def test_bad_credentials(client, make_user):
    user = make_user()
    r = client.post("/api/auth/login", json={"email": user["email"], "password": "wrong-password"})
    assert r.status_code == 401
    r = client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "whatever-1"})
    assert r.status_code == 401


def test_validation(client):
    assert client.post("/api/auth/signup", json={"email": "not-an-email", "password": "longenough"}).status_code == 422
    assert client.post("/api/auth/signup", json={"email": "a@b.co", "password": "short"}).status_code == 400


def test_protected_endpoints_require_token(client):
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/books").status_code == 401
    assert client.get("/api/books", headers={"Authorization": "Bearer garbage"}).status_code == 401
