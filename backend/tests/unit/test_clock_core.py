"""clock.py: ISO helpers, local_date/day_start, compute_next_push across DST transitions (P0; WP4 adds test_clock.py)."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from wd import clock

UTC = timezone.utc


def test_iso_roundtrip():
    dt = datetime(2026, 10, 14, 8, 5, 9, tzinfo=UTC)
    assert clock.to_iso(dt) == "2026-10-14T08:05:09Z"
    assert clock.parse_iso("2026-10-14T08:05:09Z") == dt
    assert clock.parse_iso("2026-10-14T16:05:09+08:00") == dt
    assert clock.parse_iso("2026-10-14T08:05:09") == dt  # naive = UTC (SQL default)
    with pytest.raises(ValueError):
        clock.to_iso(datetime(2026, 1, 1))


def test_now_iso_uses_the_given_clock(frozen_clock):
    assert clock.now_iso(frozen_clock) == "2026-10-14T00:00:00Z"
    assert len(clock.now_iso()) == 20


def test_local_date_and_day_start():
    now = datetime(2026, 10, 14, 17, 30, tzinfo=UTC)  # 01:30 next day in Shanghai
    assert clock.local_date(now, "Asia/Shanghai") == date(2026, 10, 15)
    assert clock.local_date(now, "UTC") == date(2026, 10, 14)
    assert clock.local_date(now, "America/New_York") == date(2026, 10, 14)
    assert clock.day_start(date(2026, 10, 15), "Asia/Shanghai") == datetime(2026, 10, 14, 16, 0, tzinfo=UTC)
    assert clock.day_start(date(2026, 7, 1), "America/New_York") == datetime(2026, 7, 1, 4, 0, tzinfo=UTC)  # EDT
    assert clock.day_start(date(2026, 1, 1), "America/New_York") == datetime(2026, 1, 1, 5, 0, tzinfo=UTC)  # EST


def test_parse_push_time():
    assert clock.parse_push_time("08:00") == (8, 0)
    assert clock.parse_push_time("23:59") == (23, 59)
    for bad in ("25:00", "8:00", "08:60", "", "0800", "24:00"):
        with pytest.raises(ValueError):
            clock.parse_push_time(bad)


def test_compute_next_push_plain_and_strictly_after():
    now = datetime(2026, 10, 14, 0, 0, tzinfo=UTC)  # 08:00 Shanghai
    nxt = clock.compute_next_push(now, "Asia/Shanghai", "08:00")
    assert nxt == datetime(2026, 10, 15, 0, 0, tzinfo=UTC)  # exactly now → tomorrow (strictly after)
    assert clock.compute_next_push(now, "Asia/Shanghai", "08:01") == datetime(2026, 10, 14, 0, 1, tzinfo=UTC)
    assert clock.compute_next_push(now, "Asia/Shanghai", "07:59") == datetime(2026, 10, 15, 0, 0, tzinfo=UTC).replace(hour=23, minute=59, day=14)
    assert clock.compute_next_push(now, "Asia/Shanghai", "07:59") > now


def test_compute_next_push_across_dst_spring_forward():
    # New York springs forward 2026-03-08 at 02:00 → 02:30 does not exist that day
    before = datetime(2026, 3, 8, 5, 0, tzinfo=UTC)  # 00:00 EST
    nxt = clock.compute_next_push(before, "America/New_York", "02:30")
    assert nxt > before
    assert nxt == datetime(2026, 3, 8, 7, 30, tzinfo=UTC)  # resolved with the pre-transition offset = 03:30 EDT
    # the day after, 02:30 EDT = 06:30Z: the wall-clock time is honoured again
    assert clock.compute_next_push(nxt, "America/New_York", "02:30") == datetime(2026, 3, 9, 6, 30, tzinfo=UTC)
    # an 08:00 push moves from 13:00Z (EST) to 12:00Z (EDT) across the change
    assert clock.compute_next_push(datetime(2026, 3, 7, 13, 0, tzinfo=UTC), "America/New_York", "08:00") == datetime(2026, 3, 8, 12, 0, tzinfo=UTC)


def test_compute_next_push_across_dst_fall_back():
    # New York falls back 2026-11-01 at 02:00 EDT → 01:30 occurs twice; the first occurrence (EDT) is used
    before = datetime(2026, 11, 1, 4, 0, tzinfo=UTC)  # 00:00 EDT
    nxt = clock.compute_next_push(before, "America/New_York", "01:30")
    assert nxt == datetime(2026, 11, 1, 5, 30, tzinfo=UTC)
    # from that instant the next 01:30 is the following day (not the second occurrence an hour later)
    assert clock.compute_next_push(nxt, "America/New_York", "01:30") == datetime(2026, 11, 2, 6, 30, tzinfo=UTC)
    assert clock.compute_next_push(datetime(2026, 10, 31, 12, 0, tzinfo=UTC), "America/New_York", "08:00") == datetime(2026, 11, 1, 13, 0, tzinfo=UTC)


def test_compute_next_push_rejects_bad_input():
    now = datetime(2026, 10, 14, 0, 0, tzinfo=UTC)
    with pytest.raises(ValueError):
        clock.compute_next_push(now, "Asia/Shanghai", "25:00")
    with pytest.raises(ValueError):
        clock.compute_next_push(now, "Mars/Olympus", "08:00")


def test_is_valid_timezone():
    assert clock.is_valid_timezone("Asia/Shanghai") and clock.is_valid_timezone("UTC")
    assert not clock.is_valid_timezone("Asia/Nowhere") and not clock.is_valid_timezone("")
