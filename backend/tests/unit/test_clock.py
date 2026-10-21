"""Clock helpers as the WP4 scheduler uses them: the build window (``build_from`` clamp) across DST, day ends,
local-time rendering for e-mails, downtime overlap (P0's test_clock_core.py covers the primitives themselves)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from wd import clock
from wd.delivery import email
from wd.jobs import scheduler
from wd.services import batches, stats

UTC = timezone.utc


def test_build_window_asia_shanghai_default_prebuild():
    push = datetime(2026, 10, 15, 0, 0, tzinfo=UTC)  # 08:00 Shanghai
    target, start = scheduler.build_from(push, "Asia/Shanghai", 3, datetime(2026, 10, 14, 20, 0, tzinfo=UTC))
    assert target == date(2026, 10, 15)
    assert start == datetime(2026, 10, 14, 21, 0, tzinfo=UTC)  # push − 3 h, still inside 2026-10-15 local (00:00 local = 16:00Z)


def test_build_window_clamps_to_the_batch_day():
    push = datetime(2026, 10, 14, 17, 0, tzinfo=UTC)  # 01:00 Shanghai on 2026-10-15
    target, start = scheduler.build_from(push, "Asia/Shanghai", 3, datetime(2026, 10, 14, 14, 30, tzinfo=UTC))
    assert target == date(2026, 10, 15)
    assert start == clock.day_start(date(2026, 10, 15), "Asia/Shanghai") == datetime(2026, 10, 14, 16, 0, tzinfo=UTC)  # never 22:00 the evening before
    assert datetime(2026, 10, 14, 14, 0, tzinfo=UTC) < start  # 22:00 local is before the window


def test_build_window_never_targets_a_past_day():
    push = datetime(2026, 10, 12, 0, 0, tzinfo=UTC)  # three days ago
    now = datetime(2026, 10, 15, 2, 0, tzinfo=UTC)  # 10:00 Shanghai 2026-10-15
    target, start = scheduler.build_from(push, "Asia/Shanghai", 3, now)
    assert target == date(2026, 10, 15) and start <= now


def test_build_window_across_new_york_dst_change():
    tz = "America/New_York"
    # 2026-10-31: 08:00 EDT = 12:00Z; the window opens 05:00 EDT = 09:00Z
    target, start = scheduler.build_from(datetime(2026, 10, 31, 12, 0, tzinfo=UTC), tz, 3, datetime(2026, 10, 31, 8, 0, tzinfo=UTC))
    assert (target, start) == (date(2026, 10, 31), datetime(2026, 10, 31, 9, 0, tzinfo=UTC))
    # 2026-11-01 (fall back at 02:00): 08:00 EST = 13:00Z; the window opens 05:00 EST = 10:00Z, inside the local day that started at 04:00Z
    target, start = scheduler.build_from(datetime(2026, 11, 1, 13, 0, tzinfo=UTC), tz, 3, datetime(2026, 11, 1, 8, 0, tzinfo=UTC))
    assert (target, start) == (date(2026, 11, 1), datetime(2026, 11, 1, 10, 0, tzinfo=UTC))
    assert clock.day_start(date(2026, 11, 1), tz) == datetime(2026, 11, 1, 4, 0, tzinfo=UTC)
    assert clock.day_start(date(2026, 11, 2), tz) == datetime(2026, 11, 2, 5, 0, tzinfo=UTC)  # the local day has 25 hours
    # a 01:00 push on the fall-back day: window 00:00–01:00 EDT = 04:00–05:00Z
    target, start = scheduler.build_from(datetime(2026, 11, 1, 5, 0, tzinfo=UTC), tz, 3, datetime(2026, 11, 1, 1, 0, tzinfo=UTC))
    assert (target, start) == (date(2026, 11, 1), datetime(2026, 11, 1, 4, 0, tzinfo=UTC))


def test_next_push_after_publish_advances_one_local_day_across_dst():
    tz = "America/New_York"
    published_at = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)  # 08:00 EDT
    nxt = clock.compute_next_push(published_at, tz, "08:00")
    assert nxt == datetime(2026, 11, 1, 13, 0, tzinfo=UTC)  # 08:00 EST, 25 h later
    assert clock.compute_next_push(nxt, tz, "08:00") == datetime(2026, 11, 2, 13, 0, tzinfo=UTC)


def test_day_end_iso_and_due_today_predicate():
    assert batches.day_end_iso("2026-10-14", "Asia/Shanghai") == "2026-10-14T16:00:00Z"
    assert batches.day_end_iso(date(2026, 11, 1), "America/New_York") == "2026-11-02T05:00:00Z"
    # "due today" ⇔ due_at < day_end (DESIGN §7): a card in the 10-minute step at 23:55 local is still due today
    assert "2026-10-14T15:55:00Z" < batches.day_end_iso("2026-10-14", "Asia/Shanghai")
    assert not ("2026-10-14T16:00:00Z" < batches.day_end_iso("2026-10-14", "Asia/Shanghai"))


def test_email_local_time_rendering():
    assert email.local_time_zh("2026-10-15T00:00:00Z", "Asia/Shanghai") == "10月15日 08:00"
    assert email.local_time_zh(datetime(2026, 11, 1, 13, 0, tzinfo=UTC), "America/New_York") == "11月1日 08:00"
    assert email.date_zh("2026-01-05") == "1月5日" and email.date_zh(date(2026, 12, 31)) == "12月31日"


def test_offline_overlap_rule():
    tz = "Asia/Shanghai"
    windows = [(datetime(2026, 10, 10, 20, 0, tzinfo=UTC), datetime(2026, 10, 12, 1, 0, tzinfo=UTC))]  # 04:00 10-11 → 09:00 10-12 local
    assert not stats.is_offline(date(2026, 10, 10), tz, windows)  # ends 00:00 local 10-11 = 16:00Z 10-10 < from
    assert stats.is_offline(date(2026, 10, 11), tz, windows)
    assert stats.is_offline(date(2026, 10, 12), tz, windows)
    assert not stats.is_offline(date(2026, 10, 13), tz, windows)
    assert not stats.is_offline(date(2026, 10, 11), tz, [])


def test_scheduler_time_of_day_thresholds():
    shanghai_0229 = datetime(2026, 10, 14, 18, 29, tzinfo=UTC)
    shanghai_0230 = datetime(2026, 10, 14, 18, 30, tzinfo=UTC)
    z = clock.zone("Asia/Shanghai")
    assert shanghai_0229.astimezone(z).time() < scheduler.CONSOLIDATE_AT <= shanghai_0230.astimezone(z).time()
    assert scheduler.MAINTENANCE_AT.hour == 3 and scheduler.MAINTENANCE_AT.minute == 30
    assert scheduler.STALE_DELIVERY == timedelta(hours=6) and scheduler.DOWNTIME_GAP == timedelta(minutes=10)
