"""Daily housekeeping in a background thread: old analytics, logged errors and usage counters are deleted."""
import logging
import threading

from app import db
from app.config import settings

log = logging.getLogger(__name__)
_stop = threading.Event()


def purge() -> dict:
    days = settings.retention_days
    counts = {}
    with db.connection() as conn:
        # sessions cascade to their events; events of long-lived sessions are cut separately
        counts["events"] = conn.execute(
            "DELETE FROM analytics_events WHERE ts < now() - make_interval(days => %s)", (days,)).rowcount
        counts["sessions"] = conn.execute(
            "DELETE FROM analytics_sessions WHERE last_seen_at < now() - make_interval(days => %s)", (days,)).rowcount
        counts["errors"] = conn.execute(
            "DELETE FROM server_errors WHERE ts < now() - make_interval(days => %s)", (days,)).rowcount
        counts["usage"] = conn.execute(
            "DELETE FROM usage_daily WHERE day < CURRENT_DATE - %s", (max(days, 400),)).rowcount
    return counts


def _loop() -> None:
    while not _stop.is_set():
        try:
            counts = purge()
            if any(counts.values()):
                log.info("retention purge (%d days): %s", settings.retention_days, counts)
        except Exception:
            log.exception("retention purge failed")
        _stop.wait(24 * 3600)


def start() -> None:
    if settings.retention_days > 0:
        threading.Thread(target=_loop, name="maintenance", daemon=True).start()


def stop() -> None:
    _stop.set()
