def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["translator"] == "mock"


def test_billing_disabled_reports_unlimited(client, make_user):
    h = make_user()["headers"]
    body = client.get("/api/subscription", headers=h).json()
    assert body["billing_enabled"] is False and body["subscribed"] is True
    assert client.post("/api/billing/checkout", headers=h).status_code == 404
    assert client.post("/api/billing/portal", headers=h).status_code == 404


def test_reading_sessions_and_progress(client, pdf_book):
    user, book = pdf_book
    h = user["headers"]
    for clicks in (2, 5):  # upsert keeps the latest count for the day
        r = client.post("/api/reading-sessions",
                        json={"book_id": book["id"], "page_number": 1, "translation_toggle_clicks": clicks}, headers=h)
        assert r.status_code == 200
    data = client.get("/api/progress", headers=h).json()
    assert data["books"] == [{"id": book["id"], "title": "Test book", "total_pages": 2}]
    assert data["sessions"] == [
        {"book_id": book["id"], "page_number": 1, "translation_toggle_clicks": 5, "words": 14}
    ]


def test_migrations_are_idempotent():
    from app import db

    assert db.migrate() == []
