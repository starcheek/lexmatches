"""The server's own log output, kept in memory for the /admin page (GET /api/admin/logs).

The newest MAX_RECORDS lines of this process: they are gone after a restart (use `docker compose logs api`
for older ones). Failed requests are also stored durably in the server_errors table (app/errorlog.py)."""
import logging
import threading
from collections import deque
from datetime import datetime, timezone

MAX_RECORDS = 3000
# Request lines that would drown everything else: health checks, analytics beacons, the log page's own polling.
_NOISE = ("/api/health", "/api/track", "/api/admin/logs")

_records: deque[dict] = deque(maxlen=MAX_RECORDS)
_lock = threading.Lock()
_seq = 0
STARTED = datetime.now(timezone.utc)


class _Buffer(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        global _seq
        try:
            message = record.getMessage()
            if record.name == "uvicorn.access" and any(path in message for path in _NOISE):
                return
            if record.exc_info:
                message += "\n" + logging.Formatter().formatException(record.exc_info)
            with _lock:
                _seq += 1
                _records.append({
                    "id": _seq,
                    "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
                    "level": record.levelname,
                    "logger": record.name,
                    "message": message[:8000],
                })
        except Exception:  # logging must never raise
            pass


_handler = _Buffer(level=logging.INFO)


def install() -> None:
    """Attach to the root logger and to uvicorn's loggers (those do not propagate to the root)."""
    for name in ("", "uvicorn", "uvicorn.access"):
        logger = logging.getLogger(name)
        if _handler not in logger.handlers:
            logger.addHandler(_handler)


def read(limit: int = 500, level: str | None = None, q: str | None = None, after: int = 0) -> list[dict]:
    """Oldest first. `level`: that level and above; `q`: text in the message or logger name; `after`: only
    records with a larger id (for polling)."""
    floor = logging.getLevelName((level or "INFO").upper())
    floor = floor if isinstance(floor, int) else logging.INFO
    needle = (q or "").strip().lower()
    with _lock:
        rows = list(_records)
    out = [
        r for r in rows
        if r["id"] > after
        and logging.getLevelName(r["level"]) >= floor
        and (not needle or needle in r["message"].lower() or needle in r["logger"].lower())
    ]
    return out[-max(1, min(limit, MAX_RECORDS)):]
