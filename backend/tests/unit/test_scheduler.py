"""jobs/scheduler.py (WP4) with a frozen clock: prebuild window, publish-once, deliveries, catch-up, stale skip, the
01:00 build_from clamp, Asia/Shanghai + America/New_York across the 2026-11-01 DST change, nightly consolidation guard,
03:30 maintenance with prefetch (fake wd.ai.budget), finalize via tick, downtime event, hourly GC, thread start/stop,
`wd tick --once` lease refusal."""

from __future__ import annotations

import argparse
import dataclasses
import logging
import sqlite3
import sys
import time as _time
import types
from datetime import datetime, timedelta, timezone

from wd import db
from wd.jobs import lease, queue, scheduler
from wd.jobs.registry import JobContext
from wd.services import bank, batches

UTC = timezone.utc
SH = "Asia/Shanghai"
NY = "America/New_York"


# ------------------------------------------------------------------------------------------- helpers
def make_user(conn: sqlite3.Connection, username: str, *, tz: str = SH, push_time: str = "08:00", next_push_at: str, push_enabled: int = 1, email: bool = False, webhook: bool = False, **cols) -> int:
    cur = conn.execute(
        "INSERT INTO users(username, password_hash, onboarding_state, email, email_verified_at) VALUES (?, 'x', 'done', ?, ?)",
        (username, f"{username}@example.com" if email else None, "2026-10-01T00:00:00Z" if email else None),
    )
    uid = int(cur.lastrowid)
    values = {
        "user_id": uid,
        "timezone": tz,
        "push_time": push_time,
        "push_enabled": push_enabled,
        "next_push_at": next_push_at,
        "email_enabled": 1 if email else 0,
        "webhook_enabled": 1 if webhook else 0,
        "webhook_url": "https://hooks.example.com/wd" if webhook else None,
        **cols,
    }
    conn.execute(f"INSERT INTO user_settings({', '.join(values)}) VALUES ({', '.join('?' * len(values))})", tuple(values.values()))
    return uid


def wid(conn, lemma: str) -> int:
    return int(conn.execute("SELECT id FROM words WHERE lemma = ?", (lemma,)).fetchone()[0])


def mark(conn, uid, lemma, now):
    return bank.apply_action(conn, uid, wid(conn, lemma), "unfamiliar", origin="browse", context="browse", now=now, tz=SH)


def tick(conn, cfg, now: datetime, **kw) -> scheduler.TickResult:
    return scheduler.run_tick(conn, now, cfg=cfg, boot_id="test", **kw)


def tick_range(conn, cfg, start: datetime, end: datetime, step: timedelta) -> list[tuple[datetime, scheduler.TickResult]]:
    out = []
    now = start
    while now <= end:
        out.append((now, tick(conn, cfg, now)))
        now += step
    return out


def batches_of(conn, uid) -> list[dict]:
    return [db.row_to_dict(r) for r in conn.execute("SELECT * FROM push_batches WHERE user_id = ? ORDER BY local_date", (uid,))]


def jobs(conn, type_=None) -> list[dict]:
    sql = "SELECT * FROM jobs" + (" WHERE type = ?" if type_ else "") + " ORDER BY id"
    return [db.row_to_dict(r) for r in conn.execute(sql, (type_,) if type_ else ())]


def next_push(conn, uid) -> str:
    return conn.execute("SELECT next_push_at FROM user_settings WHERE user_id = ?", (uid,)).fetchone()[0]


# ----------------------------------------------------------------------------------------- the loop
def test_build_at_push_minus_3h_publish_once_deliveries_once_next_push_advances_once(settings, seeded):
    conn = seeded
    uid = make_user(conn, "alice", next_push_at="2026-10-15T00:00:00Z", email=True, webhook=True)  # 08:00 Shanghai
    mark(conn, uid, "apple", datetime(2026, 10, 14, 1, 0, tzinfo=UTC))
    conn.execute("DELETE FROM jobs")
    results = tick_range(conn, settings, datetime(2026, 10, 14, 20, 30, tzinfo=UTC), datetime(2026, 10, 15, 0, 10, tzinfo=UTC), timedelta(minutes=1))
    built = [(now, r.built) for now, r in results if r.built]
    published = [(now, r.published) for now, r in results if r.published]
    assert len(built) == 1 and built[0][0] == datetime(2026, 10, 14, 21, 0, tzinfo=UTC)  # exactly push − 3 h
    assert len(published) == 1 and published[0][0] == datetime(2026, 10, 15, 0, 0, tzinfo=UTC)  # exactly at push time
    (b,) = batches_of(conn, uid)
    assert (b["local_date"], b["trigger"], b["built_at"], b["published_at"], b["status"]) == ("2026-10-15", "scheduled", "2026-10-14T21:00:00Z", "2026-10-15T00:00:00Z", "published")
    assert (b["email_status"], b["webhook_status"]) == ("queued", "queued")
    delivery = [(j["type"], j["dedupe_key"], j["priority"]) for j in jobs(conn) if j["type"] in ("send_email", "send_webhook")]
    assert sorted(delivery) == [("send_email", f"email:{b['id']}", 20), ("send_webhook", f"webhook:{b['id']}", 20)]
    assert next_push(conn, uid) == "2026-10-16T00:00:00Z"
    # more ticks: nothing new, no re-publish, no duplicate deliveries
    more = tick_range(conn, settings, datetime(2026, 10, 15, 0, 11, tzinfo=UTC), datetime(2026, 10, 15, 1, 0, tzinfo=UTC), timedelta(minutes=5))
    assert all(not r.built and not r.published for _, r in more)
    assert len(batches_of(conn, uid)) == 1 and len([j for j in jobs(conn) if j["type"] in ("send_email", "send_webhook")]) == 2
    assert batches_of(conn, uid)[0]["published_at"] == "2026-10-15T00:00:00Z"
    assert db.kv_get(conn, "last_tick_at") == "2026-10-15T00:56:00Z"  # the last tick of the 5-minute range


def test_shanghai_and_new_york_users_across_the_dst_change(settings, seeded):
    conn = seeded
    ny = make_user(conn, "ny", tz=NY, next_push_at="2026-10-31T12:00:00Z")  # 08:00 EDT
    sh = make_user(conn, "sh", tz=SH, next_push_at="2026-11-01T00:00:00Z")  # 08:00 CST
    mark(conn, ny, "apple", datetime(2026, 10, 30, 12, 0, tzinfo=UTC))
    mark(conn, sh, "bank", datetime(2026, 10, 30, 12, 0, tzinfo=UTC))
    tick_range(conn, settings, datetime(2026, 10, 31, 6, 0, tzinfo=UTC), datetime(2026, 11, 2, 14, 0, tzinfo=UTC), timedelta(minutes=5))
    ny_batches = batches_of(conn, ny)
    assert [(b["local_date"], b["built_at"], b["published_at"]) for b in ny_batches] == [
        ("2026-10-31", "2026-10-31T09:00:00Z", "2026-10-31T12:00:00Z"),  # EDT: 05:00 build, 08:00 push
        ("2026-11-01", "2026-11-01T10:00:00Z", "2026-11-01T13:00:00Z"),  # EST after the fall back: 05:00 build, 08:00 push
        ("2026-11-02", "2026-11-02T10:00:00Z", "2026-11-02T13:00:00Z"),
    ]
    assert next_push(conn, ny) == "2026-11-03T13:00:00Z"
    sh_batches = batches_of(conn, sh)
    assert [(b["local_date"], b["built_at"], b["published_at"]) for b in sh_batches] == [
        ("2026-11-01", "2026-10-31T21:00:00Z", "2026-11-01T00:00:00Z"),
        ("2026-11-02", "2026-11-01T21:00:00Z", "2026-11-02T00:00:00Z"),
    ]
    assert next_push(conn, sh) == "2026-11-03T00:00:00Z"
    assert all(b["trigger"] == "scheduled" for b in ny_batches + sh_batches)


def test_catch_up_after_a_three_day_gap_builds_today_only_and_skips_stale_deliveries(settings, seeded):
    conn = seeded
    uid = make_user(conn, "alice", next_push_at="2026-10-11T00:00:00Z", email=True, webhook=True)
    mark(conn, uid, "apple", datetime(2026, 10, 10, 1, 0, tzinfo=UTC))
    conn.execute("DELETE FROM jobs")
    now = datetime(2026, 10, 14, 2, 0, tzinfo=UTC)  # 10:00 Shanghai, three days late
    r = tick(conn, settings, now)
    (b,) = batches_of(conn, uid)
    assert r.built == [b["id"]] and r.published == [b["id"]]
    assert (b["local_date"], b["trigger"], b["status"]) == ("2026-10-14", "catchup", "published")
    assert (b["email_status"], b["webhook_status"]) == ("skipped", "skipped")  # > 6 h late
    assert [j for j in jobs(conn) if j["type"] in ("send_email", "send_webhook")] == []
    assert next_push(conn, uid) == "2026-10-15T00:00:00Z"  # advanced once, to the next 08:00
    r2 = tick(conn, settings, now + timedelta(minutes=1))
    assert not r2.built and not r2.published and len(batches_of(conn, uid)) == 1


def test_late_but_not_stale_publish_still_delivers(settings, seeded):
    conn = seeded
    uid = make_user(conn, "alice", next_push_at="2026-10-14T00:00:00Z", email=True)
    mark(conn, uid, "apple", datetime(2026, 10, 13, 1, 0, tzinfo=UTC))
    tick(conn, settings, datetime(2026, 10, 14, 5, 59, tzinfo=UTC))  # 5 h 59 late
    (b,) = batches_of(conn, uid)
    assert b["email_status"] == "queued" and b["trigger"] == "catchup"


def test_push_disabled_users_get_nothing(settings, seeded):
    conn = seeded
    uid = make_user(conn, "alice", next_push_at="2026-10-14T00:00:00Z", push_enabled=0)
    pending = make_user(conn, "bob", next_push_at="2026-10-14T00:00:00Z")
    conn.execute("UPDATE users SET onboarding_state = 'screen' WHERE id = ?", (pending,))
    inactive = make_user(conn, "carol", next_push_at="2026-10-14T00:00:00Z")
    conn.execute("UPDATE users SET is_active = 0 WHERE id = ?", (inactive,))
    for who in (uid, pending, inactive):
        mark(conn, who, "apple", datetime(2026, 10, 13, 1, 0, tzinfo=UTC))
    tick_range(conn, settings, datetime(2026, 10, 13, 20, 0, tzinfo=UTC), datetime(2026, 10, 14, 1, 0, tzinfo=UTC), timedelta(minutes=30))
    assert conn.execute("SELECT COUNT(*) FROM push_batches").fetchone()[0] == 0
    assert next_push(conn, uid) == "2026-10-14T00:00:00Z"  # untouched


def test_push_time_0100_is_built_at_local_midnight_never_the_evening_before(settings, seeded):
    conn = seeded
    uid = make_user(conn, "alice", push_time="01:00", next_push_at="2026-10-14T17:00:00Z")  # 01:00 on 2026-10-15 local
    mark(conn, uid, "apple", datetime(2026, 10, 14, 1, 0, tzinfo=UTC))
    assert not tick(conn, settings, datetime(2026, 10, 14, 14, 0, tzinfo=UTC)).built  # 22:00 local: push − 3 h, but clamped
    assert not tick(conn, settings, datetime(2026, 10, 14, 15, 59, tzinfo=UTC)).built  # 23:59 local
    r = tick(conn, settings, datetime(2026, 10, 14, 16, 0, tzinfo=UTC))  # 00:00 local of the batch day
    (b,) = batches_of(conn, uid)
    assert r.built == [b["id"]] and b["local_date"] == "2026-10-15" and b["built_at"] == "2026-10-14T16:00:00Z"
    assert tick(conn, settings, datetime(2026, 10, 14, 17, 0, tzinfo=UTC)).published == [b["id"]]
    assert next_push(conn, uid) == "2026-10-15T17:00:00Z"


def test_manual_build_is_published_by_the_tick_without_a_duplicate(settings, seeded):
    conn = seeded
    uid = make_user(conn, "alice", next_push_at="2026-10-15T00:00:00Z", email=True)
    mark(conn, uid, "apple", datetime(2026, 10, 14, 1, 0, tzinfo=UTC))
    manual = batches.build_batch(conn, uid, "2026-10-15", "manual", datetime(2026, 10, 14, 20, 0, tzinfo=UTC))
    r = tick(conn, settings, datetime(2026, 10, 14, 23, 0, tzinfo=UTC))
    assert not r.built and len(batches_of(conn, uid)) == 1
    r = tick(conn, settings, datetime(2026, 10, 15, 0, 0, tzinfo=UTC))
    assert r.published == [manual.id] and batches_of(conn, uid)[0]["trigger"] == "manual"


# ----------------------------------------------------------------------------------- consolidation
def test_nightly_consolidation_enqueued_once_per_user_per_local_day(settings, seeded):
    conn = seeded
    uid = make_user(conn, "alice", next_push_at="2026-10-15T00:00:00Z")
    empty = make_user(conn, "bob", next_push_at="2026-10-15T00:00:00Z")
    mark(conn, uid, "apple", datetime(2026, 10, 14, 1, 0, tzinfo=UTC))
    assert tick(conn, settings, datetime(2026, 10, 14, 18, 29, 59, tzinfo=UTC)).consolidations == 0  # 02:29:59 local
    results = [tick(conn, settings, datetime(2026, 10, 14, 18, 30, 0, tzinfo=UTC) + timedelta(seconds=i)) for i in range(10)]
    assert [r.consolidations for r in results] == [1] + [0] * 9
    (job,) = jobs(conn, "consolidate_bank")
    assert (job["dedupe_key"], job["priority"], job["status"]) == (f"consolidate:{uid}:2026-10-15", 50, "queued")
    assert __import__("json").loads(job["payload_json"]) == {"user_id": uid, "trigger": "nightly"}
    assert db.kv_get(conn, f"consolidate:{uid}:last_date") == "2026-10-15"
    assert db.kv_get(conn, f"consolidate:{empty}:last_date") == "2026-10-15"  # guard set even when the bank is empty
    # the job is done; the next tick does not re-enqueue (kv guard, not the dedupe key)
    queue.finish(conn, job["id"], {"ok": True}, now="2026-10-14T18:40:00Z")
    assert tick(conn, settings, datetime(2026, 10, 14, 19, 0, tzinfo=UTC)).consolidations == 0
    # a new local day → exactly one more
    assert tick(conn, settings, datetime(2026, 10, 15, 18, 29, tzinfo=UTC)).consolidations == 0
    assert tick(conn, settings, datetime(2026, 10, 15, 18, 31, tzinfo=UTC)).consolidations == 1
    assert [j["dedupe_key"] for j in jobs(conn, "consolidate_bank")] == [f"consolidate:{uid}:2026-10-15", f"consolidate:{uid}:2026-10-16"]


def test_nightly_consolidation_skips_an_unchanged_fully_validated_bank(settings, seeded):
    conn = seeded
    uid = make_user(conn, "alice", next_push_at="2026-10-15T00:00:00Z")
    mark(conn, uid, "apple", datetime(2026, 10, 14, 1, 0, tzinfo=UTC))
    conn.execute("UPDATE words SET difficulty = 2 WHERE id = ?", (wid(conn, "apple"),))
    conn.execute("INSERT INTO consolidation_runs(user_id, trigger, status, started_at, finished_at) VALUES (?, 'nightly', 'done', '2026-10-14T10:00:00Z', '2026-10-14T10:01:00Z')", (uid,))
    assert tick(conn, settings, datetime(2026, 10, 14, 18, 31, tzinfo=UTC)).consolidations == 0
    assert db.kv_get(conn, f"consolidate:{uid}:last_date") == "2026-10-15"
    # a change after the run → next night enqueues again
    bank.apply_action(conn, uid, wid(conn, "bank"), "unfamiliar", origin="browse", context="browse", now=datetime(2026, 10, 15, 1, 0, tzinfo=UTC), tz=SH)
    assert tick(conn, settings, datetime(2026, 10, 15, 18, 31, tzinfo=UTC)).consolidations == 1


# ------------------------------------------------------------------------------------- maintenance
class FakeBudget:
    def __init__(self, spent: float = 0.0, enabled: bool = True):
        self.spent = spent
        self.enabled = enabled
        self.calls: list[str] = []

    def install(self, monkeypatch) -> "FakeBudget":
        mod = types.ModuleType("wd.ai.budget")
        mod.spent_today = self.spent_today  # type: ignore[attr-defined]
        mod.ai_enabled = self.ai_enabled  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "wd.ai.budget", mod)
        return self

    def spent_today(self, conn, cfg=None, now=None):  # the real wd.ai.budget.spent_today signature (WP5)
        self.calls.append(now)
        return self.spent

    def ai_enabled(self, conn, cfg):
        return self.enabled


def test_prefetch_enqueues_priority_30_content_for_tomorrows_words(settings, seeded, monkeypatch):
    conn = seeded
    budget = FakeBudget(spent=1.0).install(monkeypatch)  # 1.00 of 3.00 → under 50 %
    alice = make_user(conn, "alice", next_push_at="2026-10-15T00:00:00Z", daily_new_count=10, daily_screen_count=3)
    bob = make_user(conn, "bob", next_push_at="2026-10-15T00:00:00Z", push_enabled=0, daily_new_count=10, daily_screen_count=3)
    t = datetime(2026, 10, 14, 1, 0, tzinfo=UTC)
    for lemma in ("apple", "bank", "cat", "dog", "glass"):
        mark(conn, alice, lemma, t)
    for lemma in ("house", "happy"):
        mark(conn, bob, lemma, t)
    # the marks enqueued p20 content for every word; keep ONE live p20 job (bank), drop the rest, and give `cat` content
    keep = f"content:{wid(conn, 'bank')}"
    conn.execute("DELETE FROM jobs WHERE dedupe_key != ?", (keep,))
    conn.execute("UPDATE words SET content_state = 'none' WHERE lemma IN ('apple','dog','glass','house','happy')")
    conn.execute("UPDATE words SET content_state = 'ready' WHERE lemma = 'cat'")
    conn.execute("UPDATE words SET content_state = 'failed' WHERE lemma = 'dog'")
    preview = batches.preview_selection(conn, alice, "2026-10-15", t)
    assert len(preview) == 8 and conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1  # read-only
    r = tick(conn, settings, datetime(2026, 10, 14, 19, 30, tzinfo=UTC))  # 03:30 Asia/Shanghai (WD_TZ) on 2026-10-15
    assert r.maintenance is True and db.kv_get(conn, "maintenance.last_date") == "2026-10-15"
    assert budget.calls == ["2026-10-14T19:30:00Z"]
    content = {j["dedupe_key"]: j["priority"] for j in jobs(conn, "generate_content")}
    screens = [w for w in preview if w not in {wid(conn, x) for x in ("apple", "bank", "cat", "dog", "glass")}]
    expected = {f"content:{wid(conn, 'apple')}": 30, f"content:{wid(conn, 'dog')}": 30, f"content:{wid(conn, 'glass')}": 30, keep: 20, **{f"content:{w}": 30 for w in screens}}
    assert content == expected  # cat (ready) skipped, bank keeps p20, bob's words untouched
    assert r.prefetched == 3 + len(screens)
    assert conn.execute("SELECT content_state FROM words WHERE lemma = 'apple'").fetchone()[0] == "queued"
    assert conn.execute("SELECT content_state FROM words WHERE lemma = 'house'").fetchone()[0] == "none"
    # the next build_batch enqueues nothing for the prefetched words
    before = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    batches.build_batch(conn, alice, "2026-10-15", "scheduled", datetime(2026, 10, 14, 21, 0, tzinfo=UTC))
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == before
    # maintenance runs once per WD_TZ day
    assert tick(conn, settings, datetime(2026, 10, 14, 19, 31, tzinfo=UTC)).maintenance is False


def test_prefetch_caps_at_50_per_user(settings, seeded, monkeypatch):
    conn = seeded
    FakeBudget(spent=0.0).install(monkeypatch)
    uid = make_user(conn, "alice", next_push_at="2026-10-15T00:00:00Z", daily_new_count=0, daily_screen_count=50, stages_json='["zk","gk","cet4","cet6"]')
    conn.execute("DELETE FROM jobs")
    n = scheduler.prefetch(conn, datetime(2026, 10, 14, 19, 30, tzinfo=UTC), cfg=settings)
    assert n == scheduler.PREFETCH_LIMIT == 50
    assert conn.execute("SELECT COUNT(*) FROM jobs WHERE type = 'generate_content' AND priority = 30").fetchone()[0] == 50
    assert conn.execute("SELECT COUNT(*) FROM words WHERE is_valid_english = 1 AND is_public = 1").fetchone()[0] > 50
    assert uid  # silence unused warning


def test_prefetch_skips_when_spend_is_high_ai_paused_or_module_missing(settings, seeded, monkeypatch):
    conn = seeded
    uid = make_user(conn, "alice", next_push_at="2026-10-15T00:00:00Z", daily_screen_count=5)
    t = datetime(2026, 10, 14, 19, 30, tzinfo=UTC)
    # WP5 absent → skipped
    monkeypatch.setitem(sys.modules, "wd.ai.budget", None)
    assert scheduler.prefetch(conn, t, cfg=settings) == 0 and conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
    # ≥ 50 % of the daily cap → skipped
    FakeBudget(spent=1.5).install(monkeypatch)
    assert scheduler.prefetch(conn, t, cfg=settings) == 0
    # paused → skipped
    FakeBudget(spent=0.0).install(monkeypatch)
    db.kv_set(conn, "claude.paused_until", "2026-10-14T20:00:00Z")
    assert scheduler.prefetch(conn, t, cfg=settings) == 0
    db.kv_delete(conn, "claude.paused_until")
    # kill switch off → skipped
    FakeBudget(spent=0.0, enabled=False).install(monkeypatch)
    assert scheduler.prefetch(conn, t, cfg=settings) == 0
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
    # everything fine → jobs for the 5 推荐词
    FakeBudget(spent=0.0).install(monkeypatch)
    assert scheduler.prefetch(conn, t, cfg=settings) == 5
    assert uid


def test_prefetch_against_the_real_budget_module(settings, seeded):
    """Integration seam: the late import meets WP5's real ``spent_today(conn, cfg=None, now=None)`` (no FakeBudget)."""
    import importlib

    conn = seeded
    budget = importlib.import_module("wd.ai.budget")
    assert budget.spent_today.__module__ == "wd.ai.budget"  # the real module, not a stub left over from another test
    uid = make_user(conn, "alice", next_push_at="2026-10-15T00:00:00Z", daily_screen_count=5)
    t = datetime(2026, 10, 14, 19, 30, tzinfo=UTC)  # 03:30 Asia/Shanghai (WD_TZ) on 2026-10-15
    cap = float(settings.ai_daily_budget_usd)
    # a real ledger row worth 50 % of the daily cap, started on the WD_TZ day of `t` → prefetch skipped
    conn.execute(
        "INSERT INTO ai_calls(kind, status, model_requested, flag_tier, word_count, max_budget_usd, reserved_usd, cost_usd, started_at, finished_at) "
        "VALUES ('content', 'success', 'sonnet', 0, 1, 0.25, 0, ?, '2026-10-14T19:00:00Z', '2026-10-14T19:00:00Z')",
        (cap * scheduler.PREFETCH_SPEND_SHARE,),
    )
    assert budget.spent_today(conn, settings, "2026-10-14T19:30:00Z") >= cap * scheduler.PREFETCH_SPEND_SHARE
    assert scheduler.prefetch(conn, t, cfg=settings) == 0
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
    # nothing spent → the 5 推荐词 get priority-30 content jobs
    conn.execute("DELETE FROM ai_calls")
    assert scheduler.prefetch(conn, t, cfg=settings) == 5
    assert conn.execute("SELECT COUNT(*) FROM jobs WHERE type = 'generate_content' AND priority = 30").fetchone()[0] == 5
    assert uid


def test_maintenance_requeues_dead_jobs_once_and_prunes_logs(settings, seeded, monkeypatch):
    conn = seeded
    FakeBudget(spent=3.0).install(monkeypatch)
    make_user(conn, "alice", next_push_at="2026-10-15T00:00:00Z")
    old = queue.enqueue(conn, "generate_content", {"word_id": 1}, dedupe_key="content:1", now="2026-10-12T00:00:00Z")
    conn.execute("UPDATE jobs SET status = 'dead', attempts = 3, finished_at = '2026-10-12T01:00:00Z' WHERE id = ?", (old,))
    fresh = queue.enqueue(conn, "lookup_word", {"word_id": 2}, dedupe_key="lookup:2", now="2026-10-14T18:00:00Z")
    conn.execute("UPDATE jobs SET status = 'dead', attempts = 3, finished_at = '2026-10-14T18:30:00Z' WHERE id = ?", (fresh,))
    logs = settings.claude_logs_dir
    (logs / "2026-09-01").mkdir(parents=True)
    (logs / "2026-10-14").mkdir(parents=True)
    r = tick(conn, settings, datetime(2026, 10, 14, 19, 30, tzinfo=UTC))
    assert r.maintenance and r.prefetched == 0
    row = db.row_to_dict(conn.execute("SELECT * FROM jobs WHERE id = ?", (old,)).fetchone())
    assert row["status"] == "queued" and row["attempts"] == 0 and __import__("json").loads(row["payload_json"])["group_size"] == 1
    assert conn.execute("SELECT status FROM jobs WHERE id = ?", (fresh,)).fetchone()[0] == "dead"  # younger than 24 h
    assert not (logs / "2026-09-01").exists() and (logs / "2026-10-14").exists()
    # dying again does not get a second nightly requeue; `fresh` (now older than 24 h) gets its one
    conn.execute("UPDATE jobs SET status = 'dead', attempts = 3, finished_at = '2026-10-15T01:00:00Z' WHERE id = ?", (old,))
    assert scheduler.requeue_dead_once(conn, datetime(2026, 10, 16, 19, 30, tzinfo=UTC)) == 1
    assert conn.execute("SELECT status FROM jobs WHERE id = ?", (old,)).fetchone()[0] == "dead"
    assert conn.execute("SELECT status FROM jobs WHERE id = ?", (fresh,)).fetchone()[0] == "queued"


# ------------------------------------------------------------------------------------------ finalize
def test_finalize_building_via_tick_when_ai_is_disabled(settings, seeded):
    conn = seeded
    uid = make_user(conn, "alice", next_push_at="2026-10-15T00:00:00Z", daily_screen_count=2)
    mark(conn, uid, "apple", datetime(2026, 10, 14, 1, 0, tzinfo=UTC))
    b = batches.build_batch(conn, uid, "2026-10-14", "manual", datetime(2026, 10, 14, 1, 0, tzinfo=UTC))
    assert tick(conn, settings, datetime(2026, 10, 14, 1, 1, tzinfo=UTC)).finalized == 0
    db.kv_set(conn, "claude.enabled", "0")
    assert tick(conn, settings, datetime(2026, 10, 14, 1, 2, tzinfo=UTC)).finalized == 1
    assert conn.execute("SELECT status FROM push_batches WHERE id = ?", (b.id,)).fetchone()[0] == "ready"
    today = batches.today_response(conn, uid, datetime(2026, 10, 14, 1, 2, tzinfo=UTC), cfg=settings)
    assert today["status"] == "ready" and today["batch"]["counts"]["pending_content"] == 0


# ------------------------------------------------------------------------------------------ downtime
def test_downtime_event_on_startup_gap(settings, seeded):
    conn = seeded
    now = datetime(2026, 10, 14, 1, 0, tzinfo=UTC)
    assert tick(conn, settings, now, startup=True).downtime is None  # no previous tick
    db.kv_set(conn, "last_tick_at", "2026-10-14T00:55:00Z")
    assert tick(conn, settings, now, startup=True).downtime is None  # 5 min: within the tolerance
    db.kv_set(conn, "last_tick_at", "2026-10-13T20:00:00Z")
    r = tick(conn, settings, now, startup=True)
    assert r.downtime == {"from": "2026-10-13T20:00:00Z", "to": "2026-10-14T01:00:00Z"}
    events = [db.row_to_dict(x) for x in conn.execute("SELECT kind, detail_json FROM system_events WHERE kind = 'downtime'")]
    assert len(events) == 1 and __import__("json").loads(events[0]["detail_json"]) == r.downtime
    assert tick(conn, settings, now + timedelta(minutes=1), startup=False).downtime is None
    assert tick(conn, settings, now + timedelta(minutes=2), startup=True).downtime is None  # the gap is gone after a tick
    assert conn.execute("SELECT COUNT(*) FROM system_events WHERE kind = 'downtime'").fetchone()[0] == 1


# ------------------------------------------------------------------------------------------ hourly GC
def test_hourly_gc(settings, seeded):
    conn = seeded
    uid = make_user(conn, "alice", next_push_at="2026-10-15T00:00:00Z")
    conn.execute("INSERT INTO sessions(token_hash, user_id, expires_at) VALUES ('old', ?, '2026-10-13T00:00:00Z')", (uid,))
    conn.execute("INSERT INTO sessions(token_hash, user_id, expires_at) VALUES ('live', ?, '2026-11-13T00:00:00Z')", (uid,))
    conn.execute("INSERT INTO auth_throttle(key, window_start, count) VALUES ('login:ip:1.2.3.4', '2026-10-01T00:00:00Z', 3)")
    conn.execute("INSERT INTO auth_throttle(key, window_start, count, blocked_until) VALUES ('login:user:bob', '2026-10-01T00:00:00Z', 10, '2026-10-20T00:00:00Z')")
    job = queue.enqueue(conn, "send_webhook", {"batch_id": 1}, dedupe_key="webhook:1", now="2026-10-14T00:00:00Z")
    conn.execute("UPDATE jobs SET status = 'running', locked_by = 'io-1:otherboot', locked_at = '2026-10-14T00:50:00Z' WHERE id = ?", (job,))
    now = datetime(2026, 10, 14, 1, 0, tzinfo=UTC)
    assert tick(conn, settings, now).gc is True
    assert [r[0] for r in conn.execute("SELECT token_hash FROM sessions")] == ["live"]
    assert [r[0] for r in conn.execute("SELECT key FROM auth_throttle")] == ["login:user:bob"]  # still locked out → kept
    assert conn.execute("SELECT status, locked_by FROM jobs WHERE id = ?", (job,)).fetchone()[:] == ("queued", None)
    assert tick(conn, settings, now + timedelta(minutes=30)).gc is False
    assert tick(conn, settings, now + timedelta(hours=1)).gc is True


# -------------------------------------------------------------------------------------------- thread
def test_scheduler_thread_start_stop(settings, connect, frozen_clock, seeded):
    cfg = dataclasses.replace(settings, tick_seconds=1)
    ctx = JobContext(db=connect, cfg=cfg, clock=frozen_clock, enqueue=queue.enqueue, log=logging.getLogger("test"), worker_id="scheduler", boot_id="thread")
    s = scheduler.Scheduler(ctx)
    s.start()
    deadline = _time.monotonic() + 10
    while s.last_result is None and _time.monotonic() < deadline:
        _time.sleep(0.05)
    s.stop()
    s.join(timeout=10)
    assert not s.is_alive() and s.last_result is not None and s.name == "scheduler"
    assert db.kv_get(seeded, "last_tick_at") == "2026-10-14T00:00:00Z"


def test_tick_cli_refuses_while_the_lease_is_live(settings, seeded, capsys):
    from wd.cli import LEASE_HINT

    assert lease.acquire(seeded, "other-instance", datetime.now(UTC))
    assert scheduler.cmd_tick(argparse.Namespace(once=True)) == 2
    assert LEASE_HINT in capsys.readouterr().err
    lease.release(seeded, "other-instance")
    assert scheduler.cmd_tick(argparse.Namespace(once=True)) == 0
    assert "tick: built" in capsys.readouterr().out
    assert db.kv_get(seeded, "last_tick_at") is not None


def test_register_cli_adds_tick(settings):
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")
    scheduler.register_cli(sub)
    args = parser.parse_args(["tick", "--once"])
    assert args.once is True and args.func is scheduler.cmd_tick
