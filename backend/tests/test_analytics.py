import time
import uuid

ADMIN = {"Authorization": "Bearer test-admin-token"}


def _batch(session, events, meta=None):
    return {"session": session, "meta": meta, "events": events}


def _event(type_, path="/read/abc", name=None, data=None):
    return {"t": int(time.time() * 1000), "type": type_, "path": path, "name": name, "data": data}


def test_track_and_read_back(client, make_user):
    user = make_user()
    session = str(uuid.uuid4())

    # signed out first, real address forwarded by the proxy
    r = client.post("/api/track", headers={"X-Forwarded-For": "203.0.113.7, 172.18.0.1", "User-Agent": "pytest"},
                    json=_batch(session, [_event("pageview", "/")], {"visitor": str(uuid.uuid4()), "language": "lv",
                                                                     "screen_w": 1920, "screen_h": 1080}))
    assert r.status_code == 204, r.text
    # then signed in: the session gets its user, events carry it
    events = [_event("click", name="Glosses", data={"x": 500, "y": 900}), _event("click", name="Glosses"),
              _event("key", name="ArrowDown"), _event("mouse", data={"points": [[10, 1, 2, 0]]}),
              _event("leave", data={"seconds": 12.5, "active_seconds": 10, "max_scroll": 0.8})]
    r = client.post("/api/track", headers={**user["headers"], "X-Forwarded-For": "203.0.113.7"}, json=_batch(session, events))
    assert r.status_code == 204, r.text

    row = next(s for s in client.get("/api/admin/analytics/sessions", headers=ADMIN).json() if s["id"] == session)
    assert row["ip"] == "203.0.113.7" and row["email"] == user["email"] and row["user_agent"] == "pytest"
    assert (row["pageviews"], row["clicks"], row["keys"], row["language"]) == (1, 2, 1, "lv")

    detail = client.get(f"/api/admin/analytics/sessions/{session}", headers=ADMIN).json()
    assert [e["type"] for e in detail] == ["pageview", "click", "click", "key", "mouse", "leave"]

    summary = client.get("/api/admin/analytics/summary", headers=ADMIN).json()
    glosses = next(u for u in summary["used"] if u["name"] == "Glosses" and u["page"] == "/read/:id")
    assert glosses["uses"] >= 2 and glosses["type"] == "click"
    assert any(p["page"] == "/read/:id" and p["avg_max_scroll"] is not None for p in summary["pages"])


def test_cloudflare_header_wins_and_bad_input(client):
    session = str(uuid.uuid4())
    r = client.post("/api/track", headers={"CF-Connecting-IP": "2001:db8::1", "X-Forwarded-For": "not-an-ip"},
                    json=_batch(session, [_event("pageview", "/")]))
    assert r.status_code == 204
    row = next(s for s in client.get("/api/admin/analytics/sessions", headers=ADMIN).json() if s["id"] == session)
    assert row["ip"] == "2001:db8::1"

    assert client.post("/api/track", json=_batch(session, [_event("keylog", "/")])).status_code == 422
    # an oversized event is dropped, the rest of the batch is kept
    big = _event("mouse", data={"points": [[0, 0, 0, 0]] * 5000})
    assert client.post("/api/track", json=_batch(session, [big, _event("key", name="g")])).status_code == 204
    detail = client.get(f"/api/admin/analytics/sessions/{session}", headers=ADMIN).json()
    assert [e["type"] for e in detail] == ["pageview", "key"]
    # an expired or foreign token still records the event, without a user
    assert client.post("/api/track", headers={"Authorization": "Bearer nope"},
                       json=_batch(session, [_event("click", name="x")])).status_code == 204


def test_admin_needs_token(client):
    assert client.get("/api/admin/analytics/sessions").status_code == 401
    assert client.get("/api/admin/analytics/summary", headers={"Authorization": "Bearer wrong"}).status_code == 401
