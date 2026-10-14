"""ai/budget.py: estimates, WD_TZ windows and resume instants, the reservation that makes concurrent callers respect the
daily cap, monthly / hourly caps, the prewarm and SVG sub-caps, pause and kill switch, once-per-day events."""

from __future__ import annotations

import threading
from dataclasses import replace

import pytest

from wd import db
from wd.ai import budget, ledger
from wd.jobs import queue

NOW = "2026-10-14T00:00:00Z"  # 08:00 Asia/Shanghai on 2026-10-14


def add_call(conn, *, kind="content", cost=0.04, started_at=NOW, status="success", job_ids=(), words=10, reserved=0.05):
    call_id = ledger.insert_call(conn, kind=kind, model_requested="sonnet", flag_tier=0, word_count=words, job_ids=list(job_ids), max_budget_usd=0.25, reserved_usd=reserved, now=started_at)
    if status != "running":
        ledger.finish_call(conn, call_id, status=status, cost_usd=cost, now=started_at)
    return call_id


def events(conn, kind):
    return conn.execute("SELECT COUNT(*) FROM system_events WHERE kind = ?", (kind,)).fetchone()[0]


def test_estimates_and_per_call_budgets(settings):
    assert budget.estimate("content", 10) == pytest.approx(0.05)
    assert budget.estimate("content", 1) == pytest.approx(0.0095)
    assert budget.estimate("lookup", 20) == pytest.approx(0.044)
    assert budget.estimate("consolidate", 80) == 0.05 and budget.estimate("svg") == 0.03 and budget.estimate("probe") == 0.01
    assert [budget.budget_for(settings, k) for k in ("content", "lookup", "consolidate", "svg", "probe")] == [0.25, 0.15, 0.40, 0.10, 0.05]
    assert [budget.timeout_for(settings, k) for k in ("content", "lookup", "consolidate", "svg", "probe")] == [180, 120, 240, 120, 60]


def test_windows_and_resume_instants_in_wd_tz():
    assert budget.day_window(NOW, "Asia/Shanghai") == ("2026-10-13T16:00:00Z", "2026-10-14T16:00:00Z")
    assert budget.month_window(NOW, "Asia/Shanghai") == ("2026-09-30T16:00:00Z", "2026-10-31T16:00:00Z")
    assert budget.next_day_resume(NOW, "Asia/Shanghai") == "2026-10-14T16:05:00Z"  # next local day 00:05
    assert budget.next_month_resume(NOW, "Asia/Shanghai") == "2026-10-31T16:05:00Z"  # 1 Nov 00:05 local
    assert budget.next_month_resume("2026-12-15T00:00:00Z", "Asia/Shanghai") == "2026-12-31T16:05:00Z"
    assert budget.next_hour_resume("2026-10-14T00:10:00Z") == "2026-10-14T01:01:00Z"
    assert budget.day_window("2026-10-14T20:00:00Z", "America/New_York") == ("2026-10-14T04:00:00Z", "2026-10-15T04:00:00Z")


def test_spent_today_sums_cost_and_running_reservations(conn, settings):
    add_call(conn, cost=0.04)
    add_call(conn, cost=0.03, started_at="2026-10-13T20:00:00Z")  # still the same WD_TZ day (04:00 local)
    add_call(conn, cost=1.0, started_at="2026-10-13T10:00:00Z")  # yesterday local
    add_call(conn, status="running", reserved=0.05)
    assert budget.spent_today(conn, settings, NOW) == pytest.approx(0.12)
    assert budget.spent_month(conn, settings, NOW) == pytest.approx(1.12)
    assert budget.calls_last_hour(conn, NOW) == 2


def test_daily_cap_defers_to_next_day_and_logs_the_event_once(conn, settings):
    cfg = replace(settings, ai_daily_budget_usd=3.0)
    add_call(conn, cost=2.96)
    ok, resumes = budget.can_spend(conn, "content", 10, 20, NOW, cfg=cfg)  # 2.96 + 0.05 > 3.00
    assert (ok, resumes) == (False, "2026-10-14T16:05:00Z")
    assert budget.can_spend(conn, "content", 1, 20, NOW, cfg=cfg) == (True, None)  # 2.96 + 0.0095 fits
    budget.can_spend(conn, "content", 10, 20, NOW, cfg=cfg)
    assert events(conn, "budget_daily") == 1  # once per day
    assert budget.can_spend(conn, "content", 10, 20, "2026-10-14T17:00:00Z", cfg=cfg) == (True, None)  # a new WD_TZ day


def test_monthly_cap_defers_to_the_first_of_next_month(conn, settings):
    cfg = replace(settings, ai_monthly_budget_usd=1.0, ai_daily_budget_usd=100.0)
    add_call(conn, cost=0.995, started_at="2026-10-01T10:00:00Z")
    assert budget.can_spend(conn, "content", 1, 20, NOW, cfg=cfg) == (False, "2026-10-31T16:05:00Z")
    assert events(conn, "budget_monthly") == 1
    assert budget.can_spend(conn, "lookup", 0, 20, NOW, cfg=replace(cfg, ai_monthly_budget_usd=1.1)) == (True, None)


def test_hourly_call_cap(conn, settings):
    cfg = replace(settings, ai_hourly_call_cap=3)
    for _ in range(3):
        add_call(conn, cost=0.001, started_at="2026-10-13T23:30:00Z")
    assert budget.can_spend(conn, "content", 1, 20, NOW, cfg=cfg) == (False, "2026-10-14T01:01:00Z")
    assert budget.can_spend(conn, "content", 1, 20, "2026-10-14T00:31:00Z", cfg=cfg) == (True, None)  # the 23:30 calls aged out


def test_prewarm_sub_cap_applies_only_to_priority_90(conn, settings):
    cfg = replace(settings, ai_prewarm_daily_budget_usd=0.10, ai_daily_budget_usd=10.0)
    plan_job = queue.enqueue(conn, "generate_content", {"word_id": 1, "plan_id": "p"}, dedupe_key="content:1", priority=90, now=NOW)
    user_job = queue.enqueue(conn, "generate_content", {"word_id": 2}, dedupe_key="content:2", priority=20, now=NOW)
    add_call(conn, cost=0.06, job_ids=[plan_job])
    add_call(conn, cost=0.06, job_ids=[user_job])  # user spend never counts against the prewarm sub-cap
    assert budget.prewarm_spent_today(conn, cfg, NOW) == pytest.approx(0.06)
    assert budget.can_spend(conn, "content", 10, 90, NOW, cfg=cfg) == (True, None)
    add_call(conn, cost=0.04, job_ids=[plan_job])
    assert budget.can_spend(conn, "content", 10, 90, NOW, cfg=cfg) == (False, "2026-10-14T16:05:00Z")  # 0.10 >= sub-cap
    assert budget.can_spend(conn, "content", 10, 20, NOW, cfg=cfg) == (True, None)
    # prewarm also leaves half the day's budget to real users
    half = replace(cfg, ai_prewarm_daily_budget_usd=5.0, ai_daily_budget_usd=0.30)
    assert budget.can_spend(conn, "content", 1, 90, NOW, cfg=half) == (False, "2026-10-14T16:05:00Z")
    assert budget.can_spend(conn, "content", 1, 20, NOW, cfg=half) == (True, None)


def test_svg_sub_cap_defers_the_19th_card_and_logs_budget_svg_once(conn, settings):
    cfg = replace(settings, ai_svg_daily_budget_usd=0.50)
    for _ in range(17):
        add_call(conn, kind="svg", cost=0.028, words=1, reserved=0.03)
    assert budget.svg_spent_today(conn, cfg, NOW) == pytest.approx(0.476)
    assert budget.can_spend(conn, "svg", 1, 20, NOW, cfg=cfg) == (True, None)  # the 18th card
    add_call(conn, kind="svg", cost=0.028, words=1, reserved=0.03)
    assert budget.can_spend(conn, "svg", 1, 20, NOW, cfg=cfg) == (False, "2026-10-14T16:05:00Z")  # the 19th is deferred
    budget.can_spend(conn, "svg", 1, 20, NOW, cfg=cfg)
    assert events(conn, "budget_svg") == 1
    assert budget.can_spend(conn, "content", 1, 20, NOW, cfg=cfg) == (True, None)  # other kinds unaffected
    assert budget.can_spend(conn, "svg", 1, 20, NOW, cfg=replace(cfg, ai_svg_daily_budget_usd=0)) == (False, "2026-10-14T16:05:00Z")


def test_pause_and_kill_switch(conn, settings):
    db.kv_set(conn, "claude.paused_until", "2026-10-14T00:30:00Z")
    assert budget.can_spend(conn, "content", 1, 20, NOW, cfg=settings) == (False, "2026-10-14T00:30:00Z")
    assert budget.paused_until(conn, "2026-10-14T00:31:00Z") is None
    budget.set_paused_until(conn, None)
    db.kv_set(conn, "claude.enabled", "0")
    assert budget.ai_enabled(conn, settings) is False
    assert budget.can_spend(conn, "content", 1, 20, NOW, cfg=settings) == (False, "2026-10-14T00:30:00Z")
    db.kv_set(conn, "claude.enabled", "1")
    assert budget.ai_enabled(conn, settings) is True
    assert budget.ai_enabled(conn, replace(settings, ai_enabled=False)) is False
    assert budget.can_spend(conn, "content", 1, 20, NOW, cfg=settings) == (True, None)


def test_reservation_makes_two_concurrent_callers_respect_the_daily_cap(connect, conn, settings):
    cfg = replace(settings, ai_daily_budget_usd=0.08)  # one 10-word content call (est 0.05) fits, two do not
    barrier = threading.Barrier(2)
    results: list[budget.Reservation] = []
    lock = threading.Lock()

    def worker():
        c = connect()
        try:
            barrier.wait()
            r = budget.reserve(c, kind="content", word_count=10, priority=20, now=NOW, cfg=cfg, flag_tier=0, job_ids=[1])
            with lock:
                results.append(r)
        finally:
            c.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert len(results) == 2 and sum(1 for r in results if r.ok) == 1
    refused = next(r for r in results if not r.ok)
    assert refused.resumes_at == "2026-10-14T16:05:00Z" and refused.reserved_usd == pytest.approx(0.05)
    assert conn.execute("SELECT COUNT(*) FROM ai_calls WHERE status = 'running'").fetchone()[0] == 1
    # once the running call is finished its reservation is released and its real cost counts
    granted = next(r for r in results if r.ok)
    ledger.finish_call(conn, granted.call_id, status="success", cost_usd=0.01, now=NOW)
    assert budget.reserve(conn, kind="content", word_count=10, priority=20, now=NOW, cfg=cfg, flag_tier=0, job_ids=[2]).ok


def test_spend_summary_numbers(conn, settings):
    add_call(conn, cost=0.04, words=10)
    add_call(conn, kind="svg", cost=0.028, words=1)
    add_call(conn, status="error", cost=0.0)
    db.kv_set(conn, "claude.flag_tier", "1")
    s = budget.spend_summary(conn, settings, NOW)
    assert s["today_usd"] == pytest.approx(0.068) and s["svg_today_usd"] == pytest.approx(0.028) and s["calls_today"] == 3
    assert s["flag_tier"] == 1 and s["enabled"] is True and s["paused_until"] is None
    assert s["avg_cost_per_word_7d"] == pytest.approx(0.004) and s["last_error"] == "error"
    assert s["daily_budget_usd"] == 3.0 and s["monthly_budget_usd"] == 40.0 and s["svg_daily_budget_usd"] == 0.5
