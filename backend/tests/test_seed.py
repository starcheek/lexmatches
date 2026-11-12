"""Sample books (app/seed.py): a new account starts with them, as its own deletable copy."""
import dataclasses
import uuid

from app import seed
from app.config import settings
from tests.helpers import wait_for


def test_new_account_gets_the_sample_book(client, monkeypatch):
    monkeypatch.setattr(seed, "settings", dataclasses.replace(settings, seed_books=True))
    r = client.post("/api/auth/signup", json={"email": f"seed-{uuid.uuid4().hex[:8]}@example.com",
                                              "password": "password123"})
    assert r.status_code == 200
    auth = {"Authorization": f"Bearer {r.json()['token']}"}

    books = client.get("/api/books", headers=auth).json()
    assert [b["title"] for b in books] == [title for title, *_ in seed.BOOKS]
    book_id = books[0]["id"]
    book = wait_for(lambda: (b := client.get(f"/api/books/{book_id}", headers=auth).json())["status"] == "completed" and b)
    assert book["original_locale"] == "french" and book["total_pages"] > 100
    pages = client.get(f"/api/books/{book_id}/pages?numbers=1,2", headers=auth).json()
    assert pages[0]["original_text"].startswith("Les Étoiles")
    assert pages[0]["chapter_title"] == "Les Étoiles" and pages[0]["translated_data"] is None
    assert client.delete(f"/api/books/{book_id}", headers=auth).status_code == 204


def test_sample_files_exist():
    for _, name, *_ in seed.BOOKS:
        assert (seed.SEED_DIR / name).stat().st_size > 1000
