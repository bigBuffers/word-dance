"""wd/sms_budget.py: the kv hour / WD_TZ-day counters, the hour cap, the day cap, the 70 % registration stop (503
sms_budget_exhausted with retry_after_s), the overview dict, the 50 / 80 / 100 % events once per day and the admin notices at 80 / 100."""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from wd import db, notify, sms_budget
from wd.errors import ApiError

UTC = timezone.utc
NOW = datetime(2026, 10, 14, 0, 12, 30, tzinfo=UTC)  # 08:12:30 Asia/Shanghai


def counters(conn: sqlite3.Connection) -> dict[str, str]:
    return {r[0]: r[1] for r in conn.execute("SELECT key, value FROM kv WHERE key LIKE 'sms.sent.%' ORDER BY key")}


def events(conn: sqlite3.Connection) -> list[tuple[str, dict]]:
    return [(r[0], json.loads(r[1])) for r in conn.execute("SELECT kind, detail_json FROM system_events WHERE kind LIKE 'sms_budget_%' ORDER BY id")]


def test_keys_and_usage(conn, settings):
    assert sms_budget.day_key(NOW, "Asia/Shanghai") == "sms.sent.2026-10-14" and sms_budget.hour_key(NOW) == "sms.sent.2026-10-14T00"
    assert sms_budget.day_key(datetime(2026, 10, 14, 17, 0, tzinfo=UTC), "Asia/Shanghai") == "sms.sent.2026-10-15"  # 01:00 the next local day
    assert sms_budget.seconds_to_next_hour(NOW) == 47 * 60 + 30 and sms_budget.seconds_to_next_day(NOW, "Asia/Shanghai") == 15 * 3600 + 47 * 60 + 30
    assert sms_budget.sms_usage(conn, settings, NOW) == {"provider": "off", "sent_today": 0, "daily_cap": 200, "sent_hour": 0, "hourly_cap": 40, "registration_open": True}
    assert sms_budget.registration_open(139, 200) and not sms_budget.registration_open(140, 200) and not sms_budget.registration_open(0, 0)


def test_reserve_counts_requests_and_enforces_the_caps(conn, settings, caplog):
    """The 503 carries `retry_after_s` only — which cap refused (hour / day / registration) goes to the log (event
    `sms_budget_refused`), never to the caller: a public `registration` scope would say "this number has no account"."""
    cfg = replace(settings, sms_provider="aliyun_verify", sms_daily_cap=10, sms_hourly_cap=4)
    for _ in range(4):
        sms_budget.reserve_sms(conn, cfg, NOW, new_account=False)
    assert counters(conn) == {"sms.sent.2026-10-14": "4", "sms.sent.2026-10-14T00": "4"}
    caplog.set_level(logging.INFO, logger="wd.sms_budget")
    with pytest.raises(ApiError) as e:
        sms_budget.reserve_sms(conn, cfg, NOW, new_account=False)  # the hour cap
    assert e.value.code == "sms_budget_exhausted" and e.value.status == 503 and e.value.details == {"retry_after_s": 47 * 60 + 30}
    assert [(r.event, r.scope) for r in caplog.records if getattr(r, "event", None) == "sms_budget_refused"] == [("sms_budget_refused", "hour")]
    assert counters(conn)["sms.sent.2026-10-14"] == "4"  # a refusal is not counted
    later = NOW + timedelta(hours=1)  # a new hour window, the same local day
    for _ in range(3):
        sms_budget.reserve_sms(conn, cfg, later, new_account=True)
    assert sms_budget.sms_usage(conn, cfg, later) == {"provider": "aliyun_verify", "sent_today": 7, "daily_cap": 10, "sent_hour": 3, "hourly_cap": 4, "registration_open": False}
    with pytest.raises(ApiError) as e:
        sms_budget.reserve_sms(conn, cfg, later, new_account=True)  # 7 ≥ 0.7 × 10: no more new accounts today
    assert e.value.details == {"retry_after_s": 14 * 3600 + 47 * 60 + 30}  # no `scope`
    assert [r.scope for r in caplog.records if getattr(r, "event", None) == "sms_budget_refused"] == ["hour", "registration"]
    sms_budget.reserve_sms(conn, cfg, later, new_account=False)  # an existing account's login still goes through
    later2 = later + timedelta(hours=1)
    for _ in range(2):
        sms_budget.reserve_sms(conn, cfg, later2, new_account=False)
    with pytest.raises(ApiError) as e:
        sms_budget.reserve_sms(conn, cfg, later2, new_account=False)  # the day cap
    assert e.value.details == {"retry_after_s": 13 * 3600 + 47 * 60 + 30}
    assert [r.scope for r in caplog.records if getattr(r, "event", None) == "sms_budget_refused"] == ["hour", "registration", "day"]
    assert sms_budget.sms_usage(conn, cfg, later2)["sent_today"] == 10
    # the next local day starts fresh; a cap of 0 is "already reached"
    tomorrow = datetime(2026, 10, 14, 16, 0, 0, tzinfo=UTC)
    sms_budget.reserve_sms(conn, cfg, tomorrow, new_account=True)
    assert counters(conn)["sms.sent.2026-10-15"] == "1"
    with pytest.raises(ApiError) as e:
        sms_budget.reserve_sms(conn, replace(cfg, sms_daily_cap=0), tomorrow, new_account=False)
    assert set(e.value.details) == {"retry_after_s"} and caplog.records[-1].scope == "day"
    # inside the caller's transaction it joins (the login_codes row and the counters commit together)
    with db.tx(conn):
        sms_budget.reserve_sms(conn, cfg, tomorrow, new_account=False)
        assert conn.in_transaction
    assert counters(conn)["sms.sent.2026-10-15"] == "2"


def test_events_once_per_day_and_notices_at_80_and_100(conn, settings, monkeypatch):
    cfg = replace(settings, sms_provider="aliyun_verify", sms_daily_cap=10, sms_hourly_cap=100, smoke_mock_http=False)
    notices: list[tuple[str, str, str]] = []
    monkeypatch.setattr(sms_budget, "notify_admins", lambda conn_, cfg_, kind, title, body, *, now, dedupe_s=3600: notices.append((kind, title, body)) or 1)
    assert sms_budget.sms_events(conn, cfg, NOW) == [] and events(conn) == []
    for _ in range(5):
        sms_budget.reserve_sms(conn, cfg, NOW, new_account=False)
    assert sms_budget.sms_events(conn, cfg, NOW) == ["sms_budget_50"]
    assert sms_budget.sms_events(conn, cfg, NOW + timedelta(minutes=1)) == []  # once per day
    for _ in range(3):
        sms_budget.reserve_sms(conn, cfg, NOW, new_account=False)
    assert sms_budget.sms_events(conn, cfg, NOW) == ["sms_budget_80"]
    assert notices == [("sms_budget_80", "短信额度提醒", notices[0][2])] and "8 / 10" in notices[0][2] and "80%" in notices[0][2] and "新手机号" in notices[0][2]
    for _ in range(2):
        sms_budget.reserve_sms(conn, cfg, NOW, new_account=False)
    assert sms_budget.sms_events(conn, cfg, NOW) == ["sms_budget_100"]
    assert len(notices) == 2 and notices[1][0] == "sms_budget_100" and "停发" in notices[1][2]
    kinds = [k for k, _ in events(conn)]
    assert kinds == ["sms_budget_50", "sms_budget_80", "sms_budget_100"]
    detail = dict(events(conn))["sms_budget_100"]
    assert detail == {"percent": 100, "sent_today": 10, "daily_cap": 10, "sent_hour": 10, "hourly_cap": 100, "registration_open": False}
    # a new local day: the thresholds fire again; a cap of 0 writes nothing
    tomorrow = datetime(2026, 10, 14, 16, 0, 0, tzinfo=UTC)
    for _ in range(5):
        sms_budget.reserve_sms(conn, cfg, tomorrow, new_account=False)
    assert sms_budget.sms_events(conn, cfg, tomorrow) == ["sms_budget_50"]
    assert sms_budget.sms_events(conn, replace(cfg, sms_daily_cap=0), tomorrow) == []
    # the real notifier is skipped under the smoke mock (the test env) and never raises into the send path
    assert sms_budget.notify_admins is not notify.notify_admins  # (patched above) — restore and prove the real one is quiet
    monkeypatch.setattr(sms_budget, "notify_admins", notify.notify_admins)
    db.kv_delete(conn, "notify.sms_budget_80.last_at")
    conn.execute("DELETE FROM system_events")
    assert sms_budget.sms_events(conn, settings, NOW) == []  # the test env: cap 200, nothing crossed
    assert sms_budget.sms_events(conn, replace(cfg, smoke_mock_http=True), tomorrow) == ["sms_budget_50"]  # no admin webhook exists: the event is still written
