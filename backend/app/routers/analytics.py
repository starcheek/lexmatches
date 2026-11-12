"""Usage analytics: the browser posts batches of events (src/lib/track.ts); the owner reads them back
through /api/admin/analytics/* with the ADMIN_TOKEN bearer token (endpoints are off while it is empty)."""
import hmac
import ipaddress
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import UUID

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from app import db
from app.config import settings

router = APIRouter(prefix="/api", tags=["analytics"])
_bearer = HTTPBearer(auto_error=False)

MAX_DATA_BYTES = 16_000  # per event; a mouse batch of 300 points is about 6 kB


class Meta(BaseModel):
    visitor: UUID | None = None
    language: str | None = Field(None, max_length=35)
    timezone: str | None = Field(None, max_length=64)
    referrer: str | None = Field(None, max_length=500)
    screen_w: int | None = Field(None, ge=0, le=100_000)
    screen_h: int | None = Field(None, ge=0, le=100_000)


class Event(BaseModel):
    t: int = Field(ge=0)  # browser clock, ms since epoch
    # Problems: error (script/resource), api_error (failed request), toast_error (error message shown),
    # rage_click (same spot clicked 3+ times within a second), slow (request over 8 s)
    type: Literal["pageview", "click", "key", "mouse", "leave", "error", "api_error", "toast_error", "rage_click", "slow"]
    path: str = Field(max_length=300)
    name: str | None = Field(None, max_length=120)
    data: dict[str, Any] | None = None


class Batch(BaseModel):
    session: UUID
    meta: Meta | None = None
    events: list[Event] = Field(max_length=300)


def client_ip(request: Request) -> str | None:
    """The visitor's address. Behind a Cloudflare tunnel it is in CF-Connecting-IP; nginx puts it first in
    X-Forwarded-For. Both headers are client-controlled when the API is reached directly: a log, not proof."""
    candidates = [
        request.headers.get("cf-connecting-ip"),
        (request.headers.get("x-forwarded-for") or "").split(",")[0],
        request.client.host if request.client else None,
    ]
    for value in candidates:
        try:
            return str(ipaddress.ip_address((value or "").strip()))
        except ValueError:
            continue
    return None


def _optional_user_id(creds: HTTPAuthorizationCredentials | None) -> str | None:
    if creds is None:
        return None
    try:
        payload = jwt.decode(creds.credentials, settings.jwt_secret, algorithms=["HS256"],
                             options={"verify_iat": False})
    except jwt.PyJWTError:
        return None
    row = db.fetch_one("SELECT id FROM users WHERE id = %s", (payload.get("sub"),))
    return str(row["id"]) if row else None


@router.post("/track", status_code=204)
def track(body: Batch, request: Request, creds: HTTPAuthorizationCredentials | None = Depends(_bearer)):
    user_id = _optional_user_id(creds)
    meta = body.meta or Meta()
    now = datetime.now(timezone.utc)
    rows = []
    for e in body.events:
        if e.data is not None and len(json.dumps(e.data)) > MAX_DATA_BYTES:
            continue
        # A browser clock can be far off; keep the event but never store a timestamp from the future.
        ts = min(datetime.fromtimestamp(e.t / 1000, timezone.utc), now) if e.t < 4e12 else now
        rows.append((body.session, user_id, ts, e.type, e.path, e.name, db.json(e.data) if e.data is not None else None))
    with db.connection() as conn:
        conn.execute(
            "INSERT INTO analytics_sessions"
            " (id, visitor_id, user_id, ip, user_agent, language, timezone, referrer, screen_w, screen_h)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
            " ON CONFLICT (id) DO UPDATE SET last_seen_at = now(),"
            "   user_id = COALESCE(EXCLUDED.user_id, analytics_sessions.user_id),"
            "   ip = COALESCE(EXCLUDED.ip, analytics_sessions.ip)",
            (body.session, meta.visitor, user_id, client_ip(request),
             (request.headers.get("user-agent") or "")[:400] or None,
             meta.language, meta.timezone, meta.referrer, meta.screen_w, meta.screen_h),
        )
        if rows:
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO analytics_events (session_id, user_id, ts, type, path, name, data)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    rows,
                )


# ---- reading the data back (owner only) ----

def admin(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> None:
    if not settings.admin_token:
        raise HTTPException(404, "Not found")
    if creds is None or not hmac.compare_digest(creds.credentials.encode(), settings.admin_token.encode()):
        raise HTTPException(401, "Admin token required")


def _since(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


@router.get("/admin/analytics/sessions", dependencies=[Depends(admin)])
def sessions(days: int = 7, limit: int = 200):
    """Newest sessions: who (email, IP, browser), how long, and how much they did."""
    return db.fetch_all(
        "SELECT s.id, s.visitor_id, s.user_id, u.email, host(s.ip) AS ip, s.user_agent, s.language, s.timezone,"
        "  s.referrer, s.screen_w, s.screen_h, s.started_at, s.last_seen_at,"
        "  round(extract(epoch FROM s.last_seen_at - s.started_at))::int AS seconds,"
        "  count(e.id) FILTER (WHERE e.type = 'pageview') AS pageviews,"
        "  count(e.id) FILTER (WHERE e.type = 'click') AS clicks,"
        "  count(e.id) FILTER (WHERE e.type = 'key') AS keys,"
        "  count(e.id) FILTER (WHERE e.type = 'error') AS errors"
        " FROM analytics_sessions s"
        " LEFT JOIN users u ON u.id = s.user_id"
        " LEFT JOIN analytics_events e ON e.session_id = s.id"
        " WHERE s.started_at >= %s GROUP BY s.id, u.email ORDER BY s.started_at DESC LIMIT %s",
        (_since(days), min(limit, 1000)),
    )


@router.get("/admin/analytics/sessions/{session_id}", dependencies=[Depends(admin)])
def session_events(session_id: UUID):
    """Every event of one session in order (the mouse path is in the 'mouse' events)."""
    return db.fetch_all(
        "SELECT ts, type, path, name, data FROM analytics_events WHERE session_id = %s ORDER BY ts, id",
        (session_id,),
    )


PROBLEM_TYPES = ("error", "api_error", "toast_error", "rage_click", "slow")


@router.get("/admin/problems", dependencies=[Depends(admin)])
def problems(days: int = 7, limit: int = 200):
    """Everything that went wrong: grouped by kind (how often, how many users), then the newest of each
    source in full. `page` = seen in the browser, `server` = failed responses, exceptions and jobs,
    `failed` = books and pages whose processing or translation ended in an error. Also dead clicks."""
    since = _since(days)
    limit = min(limit, 1000)
    fold = (r"regexp_replace(regexp_replace({0}, '[0-9a-f]{{8}}-[0-9a-f-]{{27}}', ':id', 'g'),"
            r" '[0-9a-f]{{16,}}', ':id', 'g')")
    groups = db.fetch_all(
        f"SELECT 'page' AS source, type AS kind, {fold.format('COALESCE(name, type)')} AS what, count(*) AS times,"
        "  count(DISTINCT session_id) AS sessions, count(DISTINCT user_id) AS users, max(ts) AS last"
        " FROM analytics_events WHERE ts >= %s AND type = ANY(%s) GROUP BY 1, 2, 3"
        " UNION ALL"
        f" SELECT 'server', CASE WHEN method = 'JOB' THEN 'job' WHEN status >= 500 THEN 'server_error' ELSE 'rejected' END,"
        f"  COALESCE(status::text || ' ', '') || method || ' ' || {fold.format('path')}, count(*),"
        "  count(DISTINCT session_id), count(DISTINCT user_id), max(ts)"
        " FROM server_errors WHERE ts >= %s GROUP BY 1, 2, 3"
        " ORDER BY times DESC",
        (since, list(PROBLEM_TYPES), since),
    )
    page = db.fetch_all(
        "SELECT e.ts, e.type, e.path, e.name, e.data, e.session_id, u.email FROM analytics_events e"
        " LEFT JOIN users u ON u.id = e.user_id WHERE e.ts >= %s AND e.type = ANY(%s) ORDER BY e.ts DESC LIMIT %s",
        (since, list(PROBLEM_TYPES), limit),
    )
    server = db.fetch_all(
        "SELECT e.ts, e.method, e.path, e.status, e.duration_ms, e.detail, e.traceback, e.session_id, host(e.ip) AS ip,"
        "  u.email FROM server_errors e LEFT JOIN users u ON u.id = e.user_id"
        " WHERE e.ts >= %s ORDER BY e.ts DESC LIMIT %s",
        (since, limit),
    )
    failed = db.fetch_all(
        "SELECT b.updated_at AS ts, 'book' AS kind, b.title, NULL::int AS page_number, b.error, u.email"
        " FROM books b JOIN users u ON u.id = b.user_id WHERE b.status = 'failed' AND b.updated_at >= %s"
        " UNION ALL"
        " SELECT p.updated_at, 'page', b.title, p.page_number, p.error, u.email"
        " FROM pages p JOIN books b ON b.id = p.book_id JOIN users u ON u.id = b.user_id"
        " WHERE p.status = 'failed' AND p.updated_at >= %s ORDER BY ts DESC LIMIT %s",
        (since, since, limit),
    )
    dead_clicks = db.fetch_all(
        "SELECT regexp_replace(path, '^/read/.*', '/read/:id') AS page, data->>'tag' AS tag, count(*) AS times,"
        "  count(DISTINCT session_id) AS sessions FROM analytics_events"
        " WHERE ts >= %s AND type = 'click' AND data->>'dead' = 'true' GROUP BY 1, 2 ORDER BY times DESC LIMIT 30",
        (since,),
    )
    return {"days": days, "groups": groups, "page": page, "server": server, "failed": failed, "dead_clicks": dead_clicks}


@router.get("/admin/analytics/summary", dependencies=[Depends(admin)])
def summary(days: int = 7):
    """What is used: clicks per control and shortcut keys per page kind, with the number of sessions that
    used each. A control that is missing from the list was not used. Book ids are folded into /read/:id."""
    since = _since(days)
    page = "regexp_replace(path, '^/read/.*', '/read/:id')"
    used = db.fetch_all(
        f"SELECT type, {page} AS page, name, count(*) AS uses, count(DISTINCT session_id) AS sessions"
        " FROM analytics_events WHERE ts >= %s AND type IN ('click', 'key')"
        " GROUP BY 1, 2, 3 ORDER BY uses DESC",
        (since,),
    )
    pages = db.fetch_all(
        f"SELECT {page} AS page, count(*) FILTER (WHERE type = 'pageview') AS views,"
        "  count(DISTINCT session_id) AS sessions,"
        "  round(avg((data->>'seconds')::numeric) FILTER (WHERE type = 'leave'), 1) AS avg_seconds,"
        "  round(avg((data->>'active_seconds')::numeric) FILTER (WHERE type = 'leave'), 1) AS avg_active_seconds,"
        "  round(avg((data->>'max_scroll')::numeric) FILTER (WHERE type = 'leave'), 2) AS avg_max_scroll"
        " FROM analytics_events WHERE ts >= %s AND type IN ('pageview', 'leave') GROUP BY 1 ORDER BY views DESC",
        (since,),
    )
    totals = db.fetch_one(
        "SELECT count(*) AS sessions, count(DISTINCT visitor_id) AS visitors, count(DISTINCT user_id) AS users,"
        "  count(DISTINCT ip) AS ips FROM analytics_sessions WHERE started_at >= %s",
        (since,),
    )
    return {"days": days, "totals": totals, "pages": pages, "used": used}
