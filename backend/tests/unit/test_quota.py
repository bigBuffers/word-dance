"""images/quota.py: persisted minute/day counters, cooldowns from Retry-After, provider status rows."""

from __future__ import annotations

from dataclasses import replace

from wd import db
from wd.images import quota
from wd.interfaces import ProviderError

NOW = "2026-10-14T08:00:00Z"


def test_window_keys():
    assert quota.window_keys(NOW) == ("2026-10-14T08:00", "2026-10-14")


def test_limits_follow_settings(settings):
    assert quota.limits_for("wikimedia", settings) == (None, 2000)
    assert quota.limits_for("openverse", settings) == (15, 160)
    assert quota.limits_for("pixabay", settings) == quota.PIXABAY_LIMITS
    assert quota.limits_for("pexels", settings) == quota.PEXELS_LIMITS
    assert quota.limits_for("unknown", settings) == (None, None)


def test_minute_and_day_counters_block_and_roll_over(conn, settings):
    assert quota.allow(conn, "openverse", settings, NOW)
    for _ in range(15):
        quota.record(conn, "openverse", NOW)
    assert quota.counts(conn, "openverse", NOW) == (15, 15)
    assert quota.check(conn, "openverse", settings, NOW) == "minute"
    assert quota.allow(conn, "openverse", settings, NOW) is False
    # the next minute window is free again (the day counter keeps counting)
    assert quota.check(conn, "openverse", settings, "2026-10-14T08:01:00Z") is None
    low_day = replace(settings, openverse_minute_limit=1000, openverse_daily_limit=20)
    for i in range(5):
        quota.record(conn, "openverse", f"2026-10-14T08:0{i + 1}:00Z")
    assert quota.counts(conn, "openverse", "2026-10-14T08:05:00Z")[1] == 20
    assert quota.check(conn, "openverse", low_day, "2026-10-14T08:05:00Z") == "day"
    assert quota.check(conn, "openverse", low_day, "2026-10-15T00:00:00Z") is None  # new UTC day
    # wikimedia has no minute limit, only the soft day limit
    for _ in range(30):
        quota.record(conn, "wikimedia", NOW)
    assert quota.check(conn, "wikimedia", settings, NOW) is None
    assert quota.check(conn, "wikimedia", replace(settings, wikimedia_daily_limit=30), NOW) == "day"


def test_zero_limit_disables_a_provider(conn, settings):
    assert quota.check(conn, "openverse", replace(settings, openverse_minute_limit=0), NOW) == "disabled"
    assert quota.check(conn, "wikimedia", replace(settings, wikimedia_daily_limit=0), NOW) == "disabled"


def test_counters_survive_a_new_connection_same_db(settings, connect):
    c1 = connect()
    db.run_migrations(c1)
    quota.record(c1, "openverse", NOW)
    quota.record(c1, "openverse", NOW)
    quota.record(c1, "openverse", NOW)
    c1.close()
    c2 = connect()  # a "new process" on the same file
    try:
        assert quota.counts(c2, "openverse", NOW) == (3, 3)
        rows = c2.execute("SELECT provider, window, window_start, count FROM provider_usage ORDER BY window").fetchall()
        assert [tuple(r) for r in rows] == [("openverse", "day", "2026-10-14", 3), ("openverse", "minute", "2026-10-14T08:00", 3)]
    finally:
        c2.close()


def test_record_prunes_old_windows(conn):
    quota.record(conn, "openverse", "2026-10-10T08:00:00Z")
    quota.record(conn, "openverse", NOW)
    starts = {r[0] for r in conn.execute("SELECT window_start FROM provider_usage")}
    assert starts == {"2026-10-14T08:00", "2026-10-14"}


def test_cooldown_honours_retry_after_and_defaults(conn, settings):
    err = ProviderError("openverse: HTTP 429", status=429, retry_after_s=120)
    assert quota.cooldown_seconds("openverse", err) == 120
    assert quota.cooldown_seconds("openverse", ProviderError("x", status=429)) == 600
    assert quota.cooldown_seconds("wikimedia", ProviderError("x", status=503)) == 900
    assert quota.cooldown_seconds("pixabay", None) == 600
    assert quota.cooldown_seconds("openverse", ProviderError("x", status=429, retry_after_s=10 ** 9)) == quota.MAX_COOLDOWN_S
    until = quota.cooldown(conn, "openverse", NOW, quota.cooldown_seconds("openverse", err), str(err))
    assert until == "2026-10-14T08:02:00Z"
    assert quota.check(conn, "openverse", settings, NOW) == "cooldown"
    assert quota.check(conn, "openverse", settings, "2026-10-14T08:01:59Z") == "cooldown"
    assert quota.check(conn, "openverse", settings, "2026-10-14T08:02:00Z") is None
    st = quota.state(conn, "openverse")
    assert st["consecutive_errors"] == 1 and st["last_error"] == "openverse: HTTP 429" and st["cooldown_until"] == until
    quota.cooldown(conn, "openverse", NOW, 60)
    assert quota.state(conn, "openverse")["consecutive_errors"] == 2
    quota.mark_error(conn, "openverse", NOW, "parse error")
    assert quota.state(conn, "openverse")["consecutive_errors"] == 3
    quota.mark_ok(conn, "openverse", "2026-10-14T08:03:00Z")
    st = quota.state(conn, "openverse")
    assert st["consecutive_errors"] == 0 and st["last_error"] is None and st["last_ok_at"] == "2026-10-14T08:03:00Z"


def test_status_rows_for_admin_overview(conn, settings):
    quota.record(conn, "wikimedia", NOW)
    quota.cooldown(conn, "openverse", NOW, 300)
    rows = quota.status(conn, settings, NOW)
    assert [r["provider"] for r in rows] == ["wikimedia", "openverse"]
    assert rows[0] == {"provider": "wikimedia", "minute_count": 1, "day_count": 1, "minute_limit": None, "day_limit": 2000, "cooldown_until": None}
    assert rows[1]["minute_limit"] == 15 and rows[1]["day_limit"] == 160 and rows[1]["cooldown_until"] == "2026-10-14T08:05:00Z"
    assert quota.status(conn, settings, "2026-10-14T09:00:00Z")[1]["cooldown_until"] is None  # expired cooldowns are not shown
    from wd.schemas import ProviderQuota

    for row in rows:
        ProviderQuota.model_validate(row)
