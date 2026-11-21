"""Daily cost limits for the paid APIs (Claude translation, xAI speech). Counted in usage_daily per user and day.

reserve_* checks and counts in one transaction under an advisory lock, so parallel requests cannot pass the
limit together. 0 in a setting means no limit.
"""
from fastapi import HTTPException

from app import db
from app.config import settings

_LOCK = 0x51F0A7  # pg_advisory_xact_lock key for the counters


def _exceeded(detail: str) -> HTTPException:
    return HTTPException(429, detail, headers={"Retry-After": "3600"})


def reserve_page(user_id) -> None:
    """One page started for translation, or 429 when the user's or the site's daily limit is reached."""
    with db.connection() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (_LOCK,))
        if settings.daily_page_limit:
            row = conn.execute("SELECT pages FROM usage_daily WHERE user_id = %s AND day = CURRENT_DATE",
                               (user_id,)).fetchone()
            if row and row["pages"] >= settings.daily_page_limit:
                raise _exceeded(f"Daily limit of {settings.daily_page_limit} translated pages reached. "
                                "It resets at midnight (UTC).")
        if settings.global_daily_page_limit:
            total = conn.execute("SELECT coalesce(sum(pages), 0) AS n FROM usage_daily WHERE day = CURRENT_DATE"
                                 ).fetchone()["n"]
            if total >= settings.global_daily_page_limit:
                raise _exceeded("Translation is paused for today: the site's daily limit is reached.")
        conn.execute("INSERT INTO usage_daily (user_id, pages) VALUES (%s, 1)"
                     " ON CONFLICT (user_id, day) DO UPDATE SET pages = usage_daily.pages + 1", (user_id,))


def release_page(user_id) -> None:
    """Give back a reservation that did not start a job."""
    db.execute("UPDATE usage_daily SET pages = greatest(pages - 1, 0) WHERE user_id = %s AND day = CURRENT_DATE",
               (user_id,))


def reserve_tts(user_id, chars: int) -> None:
    """Characters about to be synthesized (cache misses only), or 429 over the user's daily limit."""
    with db.connection() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (_LOCK,))
        if settings.daily_tts_chars:
            row = conn.execute("SELECT tts_chars FROM usage_daily WHERE user_id = %s AND day = CURRENT_DATE",
                               (user_id,)).fetchone()
            if (row["tts_chars"] if row else 0) + chars > settings.daily_tts_chars:
                raise _exceeded("Daily speech limit reached. It resets at midnight (UTC).")
        conn.execute("INSERT INTO usage_daily (user_id, tts_chars) VALUES (%s, %s)"
                     " ON CONFLICT (user_id, day) DO UPDATE SET tts_chars = usage_daily.tts_chars + EXCLUDED.tts_chars",
                     (user_id, chars))
