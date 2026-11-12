"""In-process background jobs (no broker).

Long work (PDF processing, page translation) runs on a small thread pool. Job state lives in
Postgres (`books.status`, `pages.status`), so after a restart `recover()` re-queues unfinished
book processing and resets interrupted page translations to `pending` (the reader resumes them;
translation is positional so no work is lost or duplicated).
"""
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from app import db
from app.config import settings

log = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=settings.job_workers, thread_name_prefix="job")
# Uploaded books are split one after another (BOOK_WORKERS=1): parsing a big PDF is CPU- and memory-heavy,
# and a queue keeps a small server responsive. A waiting book stays `pending` and does not hold up translations.
_book_executor = ThreadPoolExecutor(max_workers=max(1, settings.book_workers), thread_name_prefix="book")
_running: set[str] = set()
_lock = threading.Lock()


def is_running(key: str) -> bool:
    with _lock:
        return key in _running


def submit(key: str, fn: Callable, *args) -> bool:
    """Run fn(*args) in the background unless a job with the same key is already running."""
    with _lock:
        if key in _running:
            return False
        _running.add(key)

    def run():
        try:
            fn(*args)
        except Exception as exc:
            log.exception("job %s failed", key)
            from app import errorlog

            errorlog.record_job_failure(key, exc)
        finally:
            with _lock:
                _running.discard(key)

    (_book_executor if key.startswith("book:") else _executor).submit(run)
    return True


def wait_idle(timeout: float = 30.0) -> bool:
    """Test helper: block until no job is running."""
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        with _lock:
            if not _running:
                return True
        time.sleep(0.05)
    return False


def recover() -> None:
    from app.services.processing import process_book

    reset = db.execute("UPDATE pages SET status = 'pending' WHERE status = 'processing'")
    if reset:
        log.info("reset %d interrupted page translations to pending", reset)
    for row in db.fetch_all(  # uploads of any format (imports are written completed in one transaction)
        "SELECT id FROM books WHERE status IN ('pending', 'processing')"
        " AND COALESCE(source_format, 'pdf') NOT IN ('paste', 'paste_html', 'url')"
    ):
        submit(f"book:{row['id']}", process_book, str(row["id"]))
