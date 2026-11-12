"""Test setup: a dedicated database and bucket on the compose postgres/minio, mock translator.

Run with:  docker compose run --rm api pytest
"""
import os
import uuid

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict, make_conninfo

_base = os.environ.get("DATABASE_URL", "postgresql://lexmatches:lexmatches@localhost:5544/lexmatches")
_params = conninfo_to_dict(_base)
# TEST_DATABASE / TEST_S3_BUCKET let two suites run concurrently on the same compose services.
TEST_DB = os.environ.get("TEST_DATABASE") or _params.get("dbname", "lexmatches") + "_test"

with psycopg.connect(make_conninfo(_base), autocommit=True) as _conn:
    _conn.execute(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)')
    _conn.execute(f'CREATE DATABASE "{TEST_DB}"')

os.environ["DATABASE_URL"] = make_conninfo(_base, dbname=TEST_DB)
os.environ["S3_BUCKET"] = os.environ.get("TEST_S3_BUCKET") or "lexmatches-test"
os.environ["TRANSLATOR"] = "mock"
os.environ["STRIPE_SECRET_KEY"] = ""
os.environ["ELEVENLABS_API_KEY"] = ""
os.environ["ADMIN_TOKEN"] = "test-admin-token"
os.environ["PIPER_PRELOAD"] = "none"  # no background voice downloads during tests
os.environ["SEED_BOOKS"] = "0"  # accounts start empty; tests/test_seed.py turns the sample books on

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from tests.helpers import make_pdf, wait_for  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def make_user(client):
    def _make(password: str = "correct-horse-1"):
        email = f"user-{uuid.uuid4().hex[:10]}@example.com"
        r = client.post("/api/auth/signup", json={"email": email, "password": password})
        assert r.status_code == 200, r.text
        body = r.json()
        return {"email": email, "password": password, "id": body["user"]["id"],
                "headers": {"Authorization": f"Bearer {body['token']}"}}

    return _make


@pytest.fixture
def pdf_book(client, make_user):
    """A user with a processed French PDF book: 2 chapters on 2 PDF pages -> 2 reading units of 3 sentences
    (chapter heading + 2 sentences)."""
    user = make_user()
    pdf = make_pdf(["# Chapitre premier\nLe chat est sur la table.\nIl mange une pomme de terre.",
                    "# Chapitre deux\nLa technologie a réussi.\nNous allons à la plage."])
    r = client.post(
        "/api/books",
        headers=user["headers"],
        data={"title": "Test book", "original_locale": "french", "target_locale": "english"},
        files={"file": ("book.pdf", pdf, "application/pdf")},
    )
    assert r.status_code == 201, r.text
    book_id = r.json()["id"]

    def done():
        b = client.get(f"/api/books/{book_id}", headers=user["headers"]).json()
        return b if b["status"] in ("completed", "failed") else None

    book = wait_for(done)
    assert book["status"] == "completed", book
    return user, book
