"""Time helpers (Phase 0, frozen contract — TASKS.md §I).

Conventions (SCHEMA.sql header): timestamps are UTC ISO-8601 ``YYYY-MM-DDTHH:MM:SSZ``
(lexicographically sortable), local dates ``YYYY-MM-DD`` in an IANA timezone.
Every function here is pure; the only clock access is through a :class:`Clock`
so tests can freeze time (``tests/conftest.py`` ``FrozenClock``).
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Protocol, runtime_checkable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

UTC = timezone.utc
ISO_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
PUSH_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


@runtime_checkable
class Clock(Protocol):
    """Source of the current UTC instant (aware datetime)."""

    def now_utc(self) -> datetime: ...


class SystemClock:
    """The real clock; seconds precision so ``to_iso`` round-trips exactly."""

    def now_utc(self) -> datetime:
        return datetime.now(UTC).replace(microsecond=0)


SYSTEM_CLOCK = SystemClock()


def to_iso(dt: datetime) -> str:
    """Format an aware datetime as ``YYYY-MM-DDTHH:MM:SSZ`` (converted to UTC)."""
    if dt.tzinfo is None:
        raise ValueError("naive datetime; all timestamps must be timezone-aware")
    return dt.astimezone(UTC).strftime(ISO_FORMAT)


def parse_iso(value: str) -> datetime:
    """Parse ``YYYY-MM-DDTHH:MM:SSZ`` (or any ISO-8601 with an offset) into an aware UTC datetime.

    A value without an offset is taken as UTC, matching the SQL default
    ``strftime('%Y-%m-%dT%H:%M:%SZ','now')``.
    """
    s = value.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def now_iso(clock: Clock | None = None) -> str:
    """Current instant as an ISO string, from ``clock`` (default: the system clock)."""
    return to_iso((clock or SYSTEM_CLOCK).now_utc())


def zone(tz: str) -> ZoneInfo:
    """``ZoneInfo(tz)`` with a clearer error for unknown names."""
    try:
        return ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError) as e:  # pragma: no cover - message only
        raise ValueError(f"unknown timezone: {tz!r}") from e


def is_valid_timezone(tz: str) -> bool:
    """True when ``tz`` names a zone known to the system tzdata (used by config and settings validation)."""
    if not tz:
        return False
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True


def local_date(now_utc: datetime, tz: str) -> date:
    """The calendar date in ``tz`` at the UTC instant ``now_utc`` (DESIGN §7: no 04:00 rollover)."""
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=UTC)
    return now_utc.astimezone(zone(tz)).date()


def day_start(d: date, tz: str) -> datetime:
    """UTC instant of local midnight at the start of ``d`` in ``tz``.

    On the rare DST transition that skips local midnight, ``fold=0`` resolves to a real
    instant (the pre-transition offset), so the result is always a valid UTC datetime.
    """
    local_midnight = datetime(d.year, d.month, d.day, tzinfo=zone(tz))
    return local_midnight.astimezone(UTC)


def parse_push_time(push_time: str) -> tuple[int, int]:
    """Validate ``HH:MM`` (00:00–23:59, API.md endpoint 15) and return ``(hour, minute)``."""
    m = PUSH_TIME_RE.match(push_time or "")
    if not m:
        raise ValueError(f"push_time must be HH:MM between 00:00 and 23:59, got {push_time!r}")
    return int(m.group(1)), int(m.group(2))


def compute_next_push(now_utc: datetime, tz: str, push_time: str) -> datetime:
    """Next UTC instant strictly after ``now_utc`` whose local wall time in ``tz`` is ``push_time``.

    DST-safe via :mod:`zoneinfo`: each candidate is built as an aware local datetime and
    converted to UTC, so a push time inside a spring-forward gap resolves to the first
    real instant after the gap and an ambiguous fall-back time uses its first occurrence
    (``fold=0``). The search covers today, tomorrow and the day after (a wall time can
    be skipped or duplicated only once per transition), and the result always satisfies
    ``result > now_utc``.
    """
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=UTC)
    now_utc = now_utc.astimezone(UTC)
    hour, minute = parse_push_time(push_time)
    z = zone(tz)
    today = now_utc.astimezone(z).date()
    for offset in range(0, 3):
        d = today + timedelta(days=offset)
        candidate = datetime(d.year, d.month, d.day, hour, minute, tzinfo=z).astimezone(UTC)
        if candidate > now_utc:
            return candidate
    raise AssertionError("compute_next_push: no candidate within 3 days")  # pragma: no cover
