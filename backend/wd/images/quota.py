"""Provider quotas persisted in ``provider_usage`` (minute/day windows, UTC) and ``provider_state`` (cooldowns).

* :func:`allow` — False while the provider is in cooldown or its minute/day counter is exhausted.
* :func:`record` — count one request in both windows (also when the request failed: the provider saw it).
* :func:`cooldown` — set ``cooldown_until`` from ``Retry-After`` (429) or the provider default (Wikimedia 15 min on
  429/503, Openverse 10 min); :func:`mark_ok` clears the error streak.
* :func:`status` — the ``AdminOverview.images.providers`` rows.

Counters live in the database, so they survive restarts and are shared by every process using the same file.
"""

from __future__ import annotations

import sqlite3
from datetime import timedelta
from typing import Any

from ..clock import now_iso, parse_iso, to_iso
from ..config import Settings
from ..db import maybe_tx
from ..interfaces import ProviderError

WINDOW_MINUTE = "minute"
WINDOW_DAY = "day"

WIKIMEDIA_COOLDOWN_S = 15 * 60
OPENVERSE_COOLDOWN_S = 10 * 60
DEFAULT_COOLDOWN_S = 10 * 60
MAX_COOLDOWN_S = 6 * 3600

# (minute, day) limits for the keyed providers; conservative versus the published API limits
# (Pixabay 100 requests / 60 s; Pexels 200 / hour and 20,000 / month).
PIXABAY_LIMITS: tuple[int | None, int | None] = (60, 3000)
PEXELS_LIMITS: tuple[int | None, int | None] = (20, 600)


def limits_for(provider: str, cfg: Settings) -> tuple[int | None, int | None]:
    """``(minute_limit, day_limit)``; None = unlimited for that window, 0 = the provider is switched off."""
    if provider == "wikimedia":
        return (None, cfg.wikimedia_daily_limit)
    if provider == "openverse":
        return (cfg.openverse_minute_limit, cfg.openverse_daily_limit)
    if provider == "pixabay":
        return PIXABAY_LIMITS
    if provider == "pexels":
        return PEXELS_LIMITS
    return (None, None)


def window_keys(now: str) -> tuple[str, str]:
    """``('YYYY-MM-DDTHH:MM', 'YYYY-MM-DD')`` for an ISO instant."""
    return now[:16], now[:10]


def counts(conn: sqlite3.Connection, provider: str, now: str) -> tuple[int, int]:
    minute_key, day_key = window_keys(now)
    rows = conn.execute(
        "SELECT window, count FROM provider_usage WHERE provider = ? AND ((window = 'minute' AND window_start = ?) OR (window = 'day' AND window_start = ?))",
        (provider, minute_key, day_key),
    ).fetchall()
    minute = day = 0
    for window, count in rows:
        if window == WINDOW_MINUTE:
            minute = int(count)
        elif window == WINDOW_DAY:
            day = int(count)
    return minute, day


def state(conn: sqlite3.Connection, provider: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM provider_state WHERE provider = ?", (provider,)).fetchone()
    return None if row is None else {k: row[k] for k in row.keys()}


def check(conn: sqlite3.Connection, provider: str, cfg: Settings, now: str | None = None) -> str | None:
    """Why the provider may not be called right now (``cooldown`` / ``minute`` / ``day`` / ``disabled``), or None."""
    now = now or now_iso()
    st = state(conn, provider)
    if st and st.get("cooldown_until") and str(st["cooldown_until"]) > now:
        return "cooldown"
    minute_limit, day_limit = limits_for(provider, cfg)
    if minute_limit == 0 or day_limit == 0:
        return "disabled"
    minute, day = counts(conn, provider, now)
    if minute_limit is not None and minute >= minute_limit:
        return "minute"
    if day_limit is not None and day >= day_limit:
        return "day"
    return None


def allow(conn: sqlite3.Connection, provider: str, cfg: Settings, now: str | None = None) -> bool:
    return check(conn, provider, cfg, now) is None


def record(conn: sqlite3.Connection, provider: str, now: str | None = None, n: int = 1) -> None:
    """Count ``n`` requests in the minute and day windows; prunes windows older than a day / three days."""
    now = now or now_iso()
    minute_key, day_key = window_keys(now)
    old_minute = to_iso(parse_iso(now) - timedelta(days=1))[:16]
    old_day = to_iso(parse_iso(now) - timedelta(days=3))[:10]
    with maybe_tx(conn):
        for window, key in ((WINDOW_MINUTE, minute_key), (WINDOW_DAY, day_key)):
            conn.execute(
                "INSERT INTO provider_usage(provider, window, window_start, count) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(provider, window, window_start) DO UPDATE SET count = count + excluded.count",
                (provider, window, key, int(n)),
            )
        conn.execute("DELETE FROM provider_usage WHERE window = 'minute' AND window_start < ?", (old_minute,))
        conn.execute("DELETE FROM provider_usage WHERE window = 'day' AND window_start < ?", (old_day,))


def cooldown_seconds(provider: str, error: ProviderError | None = None) -> int:
    """``Retry-After`` when the provider sent one (clamped), else the provider default."""
    if error is not None and error.retry_after_s is not None:
        return int(max(1, min(MAX_COOLDOWN_S, error.retry_after_s)))
    if provider == "wikimedia":
        return WIKIMEDIA_COOLDOWN_S
    if provider == "openverse":
        return OPENVERSE_COOLDOWN_S
    return DEFAULT_COOLDOWN_S


def cooldown(conn: sqlite3.Connection, provider: str, now: str | None, seconds: int, error: str | None = None) -> str:
    """Put the provider in cooldown until ``now + seconds``; returns that instant (ISO)."""
    now = now or now_iso()
    until = to_iso(parse_iso(now) + timedelta(seconds=int(seconds)))
    with maybe_tx(conn):
        conn.execute(
            "INSERT INTO provider_state(provider, cooldown_until, last_error, consecutive_errors, updated_at) VALUES (?, ?, ?, 1, ?) "
            "ON CONFLICT(provider) DO UPDATE SET cooldown_until = excluded.cooldown_until, last_error = excluded.last_error, "
            "consecutive_errors = provider_state.consecutive_errors + 1, updated_at = excluded.updated_at",
            (provider, until, (error or "")[:500] or None, now),
        )
    return until


def mark_error(conn: sqlite3.Connection, provider: str, now: str | None, error: str) -> None:
    """Record a failure that does not warrant a cooldown (e.g. a parse error)."""
    now = now or now_iso()
    with maybe_tx(conn):
        conn.execute(
            "INSERT INTO provider_state(provider, last_error, consecutive_errors, updated_at) VALUES (?, ?, 1, ?) "
            "ON CONFLICT(provider) DO UPDATE SET last_error = excluded.last_error, "
            "consecutive_errors = provider_state.consecutive_errors + 1, updated_at = excluded.updated_at",
            (provider, error[:500], now),
        )


def mark_ok(conn: sqlite3.Connection, provider: str, now: str | None = None) -> None:
    now = now or now_iso()
    with maybe_tx(conn):
        conn.execute(
            "INSERT INTO provider_state(provider, last_ok_at, consecutive_errors, updated_at) VALUES (?, ?, 0, ?) "
            "ON CONFLICT(provider) DO UPDATE SET last_ok_at = excluded.last_ok_at, last_error = NULL, consecutive_errors = 0, updated_at = excluded.updated_at",
            (provider, now, now),
        )


def status(conn: sqlite3.Connection, cfg: Settings, now: str | None = None) -> list[dict[str, Any]]:
    """``AdminOverview.images.providers`` rows for every configured provider (API.md §9 ``ProviderQuota``)."""
    now = now or now_iso()
    out: list[dict[str, Any]] = []
    for provider in cfg.image_providers:
        minute, day = counts(conn, provider, now)
        minute_limit, day_limit = limits_for(provider, cfg)
        st = state(conn, provider) or {}
        cooldown_until = st.get("cooldown_until")
        out.append(
            {
                "provider": provider,
                "minute_count": minute,
                "day_count": day,
                "minute_limit": minute_limit,
                "day_limit": day_limit,
                "cooldown_until": cooldown_until if cooldown_until and str(cooldown_until) > now else None,
            }
        )
    return out
