import time
import uuid

from app import db, jobs
from app.main import app

ADMIN = {"Authorization": "Bearer test-admin-token"}


@app.get("/api/_test/boom")
def _boom():
    raise RuntimeError("kaboom for the log")


def _problems(client):
    return client.get("/api/admin/problems", headers=ADMIN).json()


def test_failed_responses_and_crashes_are_logged(client, make_user):
    user = make_user()
    session = str(uuid.uuid4())
    headers = {**user["headers"], "X-Session": session, "X-Forwarded-For": "198.51.100.9"}

    # a rejection keeps its status and message for the user, and is logged with who and where
    r = client.get(f"/api/books/{uuid.uuid4()}", headers=headers)
    assert r.status_code == 404 and r.json()["detail"]
    # an unhandled exception becomes a clean 500 and is logged with its traceback
    r = client.get("/api/_test/boom", headers=headers)
    assert r.status_code == 500 and "logged" in r.json()["detail"]
    # validation errors (422) are logged with the field message
    assert client.post("/api/auth/login", json={"email": "x"}).status_code == 422
    # successful requests and the health check are not logged
    assert client.get("/api/books", headers=headers).status_code == 200

    rows = [s for s in _problems(client)["server"] if s["session_id"] == session]
    assert {(s["status"], s["method"]) for s in rows} == {(404, "GET"), (500, "GET")}
    assert all(s["email"] == user["email"] and s["ip"] == "198.51.100.9" for s in rows)
    crash = next(s for s in rows if s["status"] == 500)
    assert "kaboom for the log" in crash["detail"] and "RuntimeError" in crash["traceback"]
    assert next(s for s in rows if s["status"] == 404)["traceback"] is None
    assert db.fetch_one("SELECT count(*) AS n FROM server_errors WHERE status = 422 AND path = '/api/auth/login'")["n"] >= 1

    groups = _problems(client)["groups"]
    assert any(g["kind"] == "server_error" and g["what"] == "500 GET /api/_test/boom" for g in groups)
    assert any(g["kind"] == "rejected" and g["what"] == "404 GET /api/books/:id" for g in groups)


def test_job_crash_and_page_problems(client):
    def explode():
        raise ValueError("job blew up")

    key = f"test:{uuid.uuid4()}"
    assert jobs.submit(key, explode)
    for _ in range(100):
        row = db.fetch_one("SELECT detail, traceback FROM server_errors WHERE method = 'JOB' AND path = %s", (key,))
        if row:
            break
        time.sleep(0.05)
    assert row and "job blew up" in row["detail"] and "ValueError" in row["traceback"]

    session = str(uuid.uuid4())
    now = int(time.time() * 1000)
    events = [{"t": now, "type": "api_error", "path": "/dashboard", "name": "413 POST /api/books", "data": {"status": 413}},
              {"t": now, "type": "toast_error", "path": "/dashboard", "name": "File is too large"},
              {"t": now, "type": "rage_click", "path": "/read/x", "name": "Translate page", "data": {"count": 4}},
              {"t": now, "type": "click", "path": "/read/x", "data": {"tag": "p", "dead": True}}]
    assert client.post("/api/track", json={"session": session, "events": events}).status_code == 204
    p = _problems(client)
    assert {e["type"] for e in p["page"] if e["session_id"] == session} == {"api_error", "toast_error", "rage_click"}
    assert any(g["kind"] == "rage_click" and g["what"] == "Translate page" for g in p["groups"])
    assert any(d["tag"] == "p" and d["page"] == "/read/:id" for d in p["dead_clicks"])
