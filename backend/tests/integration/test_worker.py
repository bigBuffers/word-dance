"""jobs/worker.py with the real fake claude: one call for ten content jobs, the head job across types (a p10 lookup before
p90 content), group_size bisection 10→5→3→2→1 under --max-budget-usd stops, the stale lock sweep with a foreign boot_id,
the lease refusal of `wd worker-once`, the worker threads' start/stop/join, and the end-to-end valid=false on a public
custom word (holders keep seeing it, a third user does not)."""

from __future__ import annotations

import json
import logging
import secrets
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from wd import cli, db
from wd.ai import budget
from wd.deps import hash_token
from wd.jobs import lease, queue, registry, worker
from wd.jobs.queue import CLAUDE_TYPES
from wd.jobs.registry import JobContext
from wd.services import bank, words

NOW = "2026-10-14T00:00:00Z"
FAKE = Path(__file__).resolve().parents[1] / "fake_claude.py"
FAR = "2030-01-01T00:00:00Z"


def wrapper(directory: Path, mode: str) -> str:
    directory.mkdir(parents=True, exist_ok=True)
    script = directory / f"claude-{mode}"
    script.write_text(f"#!/usr/bin/env bash\nFAKE_CLAUDE_MODE='{mode}' exec '{sys.executable}' -I '{FAKE}' \"$@\"\n", encoding="utf-8")
    script.chmod(0o755)
    return str(script)


@pytest.fixture
def ctx(settings, connect, frozen_clock):
    registry.load_handlers()
    return JobContext(db=connect, cfg=settings, clock=frozen_clock, enqueue=queue.enqueue, log=logging.getLogger("t"), worker_id="claude-1", boot_id="boot-a")


def seed_words(conn, n):
    return [int(r[0]) for r in conn.execute("SELECT id FROM words WHERE is_valid_english = 1 AND is_public = 1 AND content_state = 'none' ORDER BY (frq IS NULL OR frq = 0), frq, lemma LIMIT ?", (n,))]


def enqueue_content(conn, word_ids, priority=20):
    return [queue.enqueue(conn, "generate_content", {"word_id": w}, dedupe_key=f"content:{w}", priority=priority, now=NOW) for w in word_ids]


def sync_lookups(conn, run_after="2026-10-14T00:00:20Z"):
    """words.resolve debounces lookups 20 s on the SYSTEM clock; pin them to the frozen clock's timeline."""
    conn.execute("UPDATE jobs SET run_after = ? WHERE type = 'lookup_word' AND status = 'queued'", (run_after,))


def calls(conn):
    return [dict(r) for r in conn.execute("SELECT id, kind, status, word_count, cost_usd FROM ai_calls ORDER BY id").fetchall()]


def jobs_by_status(conn):
    return {str(r[0]): int(r[1]) for r in conn.execute("SELECT status, COUNT(*) FROM jobs GROUP BY status")}


def make_user(conn, name, role="user"):
    uid = int(conn.execute("INSERT INTO users(username, password_hash, role, onboarding_state) VALUES (?, 'x', ?, 'done')", (name, role)).lastrowid)
    conn.execute("INSERT INTO user_settings(user_id) VALUES (?)", (uid,))
    token = secrets.token_urlsafe(32)
    conn.execute("INSERT INTO sessions(token_hash, user_id, expires_at) VALUES (?, ?, ?)", (hash_token(token), uid, FAR))
    return uid, token


# ------------------------------------------------------------------------------------------- drains
def test_ten_queued_content_jobs_make_exactly_one_call(seeded, ctx):
    ids = enqueue_content(seeded, seed_words(seeded, 10))
    processed = worker.drain(ctx, CLAUDE_TYPES)
    assert processed == 10
    rows = calls(seeded)
    assert len(rows) == 1 and rows[0]["kind"] == "content" and rows[0]["status"] == "success" and rows[0]["word_count"] == 10
    assert rows[0]["cost_usd"] == pytest.approx(0.04)
    assert all(queue.get_job(seeded, j).status == "done" for j in ids)
    assert seeded.execute("SELECT COUNT(*) FROM word_contents WHERE status = 'active'").fetchone()[0] == 10
    assert seeded.execute("SELECT COUNT(*) FROM words WHERE content_state = 'ready'").fetchone()[0] == 10
    assert seeded.execute("SELECT COUNT(*) FROM jobs WHERE type = 'fetch_image' AND status = 'queued'").fetchone()[0] == 10
    assert seeded.execute("SELECT COUNT(*) FROM word_contents WHERE cost_usd = 0.004").fetchone()[0] == 10


def test_a_p10_lookup_runs_before_thirty_p90_content_jobs(seeded, ctx):
    alice, _ = make_user(seeded, "alice")
    enqueue_content(seeded, seed_words(seeded, 30), priority=90)
    (res,) = bank.add_custom_words(seeded, alice, "GDP", None, False, NOW, "Asia/Shanghai")
    sync_lookups(seeded)
    lookup_job = queue.live_job(seeded, f"lookup:{res.word_id}")
    assert lookup_job.priority == 10 and lookup_job.run_after == "2026-10-14T00:00:20Z"
    ctx.clock.advance(seconds=20)
    worker.drain(ctx, CLAUDE_TYPES)
    rows = calls(seeded)
    assert rows[0]["kind"] == "lookup" and rows[0]["word_count"] == 1  # the p10 lookup first (head job across types)
    # the p10 content job the lookup enqueued heads the next claim, which fills up to WD_AI_BATCH_SIZE from the p90 queue
    assert [(r["kind"], r["word_count"]) for r in rows[1:]] == [("content", 10), ("content", 10), ("content", 10), ("content", 1)]
    gdp_content = seeded.execute("SELECT id FROM jobs WHERE type = 'generate_content' AND json_extract(payload_json, '$.word_id') = ?", (res.word_id,)).fetchone()[0]
    assert gdp_content in json.loads(seeded.execute("SELECT job_ids_json FROM ai_calls WHERE id = ?", (rows[1]["id"],)).fetchone()[0])
    assert words.word_row(seeded, res.word_id)["is_valid_english"] == 1


def test_group_size_bisection_on_budget_stops(seeded, ctx, tmp_path):
    cfg = replace(ctx.cfg, claude_bin=wrapper(tmp_path / "bin", "budget"), ai_daily_budget_usd=100.0)  # every stop costs $0.25: keep the daily cap out of the way
    ctx = replace(ctx, cfg=cfg)
    ids = enqueue_content(seeded, seed_words(seeded, 10))
    worker.drain(ctx, CLAUDE_TYPES)
    counts = [r["word_count"] for r in calls(seeded)]
    assert counts[:5] == [10, 5, 3, 2, 1]
    assert all(r["status"] == "budget" and r["cost_usd"] == pytest.approx(0.25) for r in calls(seeded))
    for job_id in ids:
        job = queue.get_job(seeded, job_id)
        assert job.status == "queued" and job.payload["group_size"] == 1 and job.attempts == 1  # bisection never consumed an attempt; the single failure did
        assert job.run_after == "2026-10-14T00:02:00Z" and "budget" in job.last_error
    assert seeded.execute("SELECT COUNT(*) FROM words WHERE content_state = 'failed'").fetchone()[0] == 0  # not dead yet


def test_stale_lock_sweep_with_a_foreign_boot_id(seeded, ctx):
    (a, b) = enqueue_content(seeded, seed_words(seeded, 2))
    seeded.execute("UPDATE jobs SET status = 'running', locked_by = 'claude-1:boot-z', locked_at = ? WHERE id = ?", (NOW, a))
    seeded.execute("UPDATE jobs SET status = 'running', locked_by = 'claude-1:boot-a', locked_at = ? WHERE id = ?", (NOW, b))
    w = worker.ClaudeWorker(ctx)
    w.maybe_sweep()
    assert queue.get_job(seeded, a).status == "queued" and queue.get_job(seeded, a).locked_by is None
    assert queue.get_job(seeded, b).status == "running"  # ours and fresh
    w._last_sweep = 0.0
    ctx.clock.advance(minutes=16)
    w.maybe_sweep()
    assert queue.get_job(seeded, b).status == "queued"  # ours but locked for more than 15 minutes


def test_claude_worker_idles_while_ai_is_disabled(seeded, ctx):
    w = worker.ClaudeWorker(ctx)
    assert w.gate() is None
    db.kv_set(seeded, "claude.enabled", "0")
    assert w.gate() == worker.DISABLED_WAIT_S
    ids = enqueue_content(seeded, seed_words(seeded, 2))
    assert w.step() is False
    assert all(queue.get_job(seeded, j).status == "queued" and queue.get_job(seeded, j).attempts == 0 for j in ids)  # untouched
    db.kv_set(seeded, "claude.enabled", "1")
    assert w.step() is True and all(queue.get_job(seeded, j).status == "done" for j in ids)
    assert w.processed == 2 and worker.IoWorker(ctx).gate() is None


def test_fenced_worker_neither_claims_nor_sweeps_and_sweeps_once_on_resume(seeded, ctx):
    lost = threading.Event()
    w = worker.ClaudeWorker(ctx, lease_lost=lost)
    assert not w.fenced
    mine = enqueue_content(seeded, seed_words(seeded, 3))
    theirs = mine.pop()  # in flight on the instance that holds the lease
    seeded.execute("UPDATE jobs SET status = 'running', locked_by = 'claude-1:boot-b', locked_at = ? WHERE id = ?", (NOW, theirs))
    lost.set()
    assert w.fenced
    assert w.step() is False
    assert all(queue.get_job(seeded, j).status == "queued" and queue.get_job(seeded, j).attempts == 0 for j in mine)  # untouched
    w._last_sweep = 0.0
    w.maybe_sweep()
    assert queue.get_job(seeded, theirs).status == "running" and queue.get_job(seeded, theirs).locked_by == "claude-1:boot-b"  # not swept
    assert calls(seeded) == [] and w.processed == 0
    lost.clear()
    assert w.step() is True
    # the resume sweep returned the (now stale, foreign-boot) job to queued and the claim took all three in one call
    assert all(queue.get_job(seeded, j).status == "done" for j in (*mine, theirs))
    assert w.processed == 3 and len(calls(seeded)) == 1


def test_worker_lost_lease_is_fenced_until_the_keeper_reacquires(seeded, ctx, connect):
    from datetime import timedelta

    t0 = ctx.clock.now_utc()
    assert lease.acquire(seeded, "A", t0)
    keeper = lease.LeaseKeeper(connect, "A", ctx.clock.now_utc, interval_s=0.05)
    w = worker.ClaudeWorker(ctx, lease_lost=keeper.lost)
    ids = enqueue_content(seeded, seed_words(seeded, 2))
    # A's renewals lapsed for > TTL and a second `wd serve` (B) took the lease (as of t0 + 91 s; A's clock still reads t0)
    assert lease.acquire(seeded, "B", t0 + timedelta(seconds=lease.TTL_SECONDS + 1))
    keeper.start()
    try:
        assert keeper.lost.wait(5)
        assert w.fenced and w.step() is False
        assert all(queue.get_job(seeded, j).status == "queued" and queue.get_job(seeded, j).attempts == 0 for j in ids)
        assert lease.release(seeded, "B")  # B stops; A's keeper takes the lease back on its next round
        deadline = time.monotonic() + 5
        while keeper.lost.is_set() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not keeper.lost.is_set() and lease.read(seeded)["instance"] == "A"
        assert w.step() is True
        assert all(queue.get_job(seeded, j).status == "done" for j in ids) and w.processed == 2
    finally:
        keeper.stop()
        keeper.join(timeout=5)


def test_lease_blocks_worker_once(seeded, settings, test_env, monkeypatch, capsys):
    from datetime import datetime, timezone

    monkeypatch.setenv("WD_CLAUDE_BIN", settings.claude_bin)
    assert lease.acquire(seeded, "other-instance", datetime.now(timezone.utc))  # the CLI checks the lease against the real clock
    assert cli.main(["worker-once"]) == 2
    assert cli.LEASE_HINT in capsys.readouterr().err
    enqueue_content(seeded, seed_words(seeded, 3))
    lease.release(seeded, "other-instance")
    assert cli.main(["worker-once", "--types", "claude"]) == 0  # the IO types would reach for the image providers
    assert "processed 3 job(s)" in capsys.readouterr().out
    assert jobs_by_status(seeded)["done"] == 3 and len(calls(seeded)) == 1


def test_worker_threads_start_stop_join(seeded, ctx):
    alice, _ = make_user(seeded, "alice")
    (res,) = bank.add_custom_words(seeded, alice, "GDP", None, False, NOW, "Asia/Shanghai")
    sync_lookups(seeded)
    ctx.clock.advance(seconds=20)
    queue.enqueue(seeded, "send_webhook", {"batch_id": 1}, dedupe_key="webhook:1", now=NOW)  # no such batch → WP4's handler finishes it as skipped in the IoWorker
    claude = worker.ClaudeWorker(ctx, idle_wait=0.05)
    io = worker.IoWorker(replace(ctx, worker_id="io-1"), idle_wait=0.05)
    claude.start()
    io.start()
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        c = ctx.db()
        try:
            lookup_done = c.execute("SELECT COUNT(*) FROM jobs WHERE type = 'lookup_word' AND status = 'done'").fetchone()[0] == 1
            content_done = c.execute("SELECT COUNT(*) FROM jobs WHERE type = 'generate_content' AND status = 'done'").fetchone()[0] == 1
            webhook_row = c.execute("SELECT status, result_json FROM jobs WHERE type = 'send_webhook'").fetchone()
            webhook_done = webhook_row[0] == "done" and json.loads(webhook_row[1] or "{}").get("skipped") == "batch_missing"
        finally:
            c.close()
        if lookup_done and content_done and webhook_done:
            break
        time.sleep(0.05)
    claude.stop()
    io.stop()
    claude.join(timeout=10)
    io.join(timeout=10)
    assert not claude.is_alive() and not io.is_alive()
    assert lookup_done and content_done and webhook_done
    assert claude.processed == 2 and claude.last_error is None and claude.name == "claude-1" and io.name == "io-1"
    assert words.word_row(seeded, res.word_id)["content_state"] == "ready"


def test_overloaded_and_auth_outcomes_defer_and_pause(seeded, ctx, tmp_path):
    ids = enqueue_content(seeded, seed_words(seeded, 2))
    over = replace(ctx, cfg=replace(ctx.cfg, claude_bin=wrapper(tmp_path / "bin", "overloaded")))
    worker.drain(over, CLAUDE_TYPES)
    for j in ids:
        job = queue.get_job(seeded, j)
        assert job.status == "queued" and job.attempts == 0 and job.run_after == "2026-10-14T00:02:00Z"
    assert db.kv_get(seeded, "claude.overloaded_streak") == "1"
    ctx.clock.advance(minutes=2)
    auth = replace(ctx, cfg=replace(ctx.cfg, claude_bin=wrapper(tmp_path / "bin", "auth")))
    worker.drain(auth, CLAUDE_TYPES)
    paused = db.kv_get(seeded, "claude.paused_until")
    assert paused == "2026-10-14T00:32:00Z"
    assert all(queue.get_job(seeded, j).status == "queued" and queue.get_job(seeded, j).run_after == paused for j in ids)
    assert seeded.execute("SELECT COUNT(*) FROM system_events WHERE kind = 'claude_auth'").fetchone()[0] == 1
    assert budget.can_spend(seeded, "content", 1, 20, ctx.now(), cfg=ctx.cfg) == (False, paused)
    ctx.clock.advance(minutes=31)
    worker.drain(ctx, CLAUDE_TYPES)  # back on the real (ok) fake after the pause
    assert all(queue.get_job(seeded, j).status == "done" for j in ids)
    assert db.kv_get(seeded, "claude.overloaded_streak") == "0"


# -------------------------------------------------------------------------------- end to end over HTTP
def test_content_valid_false_on_a_public_custom_word_hides_it_from_third_users(client: TestClient, settings, connect, frozen_clock, tmp_path):
    conn = connect()
    try:
        alice, a_tok = make_user(conn, "alice")
        bob, b_tok = make_user(conn, "bob")
        carol, c_tok = make_user(conn, "carol")
    finally:
        conn.close()
    registry.load_handlers()
    ok_ctx = JobContext(db=connect, cfg=settings, clock=frozen_clock, enqueue=queue.enqueue, worker_id="claude-1", boot_id="b")
    client.cookies.set("wd_session", a_tok)
    r = client.post("/api/bank/add", json={"text": "zzzap"})
    assert r.status_code == 200 and r.json()["results"][0]["status"] == "pending_ai"
    wid = r.json()["results"][0]["word"]["id"]
    client.cookies.set("wd_session", b_tok)
    assert client.post("/api/bank/add", json={"text": "zzzap"}).json()["results"][0]["status"] == "pending_ai"
    conn = connect()
    try:
        sync_lookups(conn)
    finally:
        conn.close()
    frozen_clock.advance(seconds=20)
    worker.drain(ok_ctx, ("lookup_word",))  # the ok fake validates it → public, content job enqueued
    conn = connect()
    try:
        w = words.word_row(conn, wid)
        assert w["is_valid_english"] == 1 and w["is_public"] == 1 and queue.live_job(conn, f"content:{wid}") is not None
    finally:
        conn.close()
    client.cookies.set("wd_session", c_tok)
    assert [x["lemma"] for x in client.get("/api/vocab?q=zzzap").json()["items"]] == ["zzzap"]
    bad_ctx = replace(ok_ctx, cfg=replace(settings, claude_bin=wrapper(tmp_path / "bin", "invalid_word")))
    worker.drain(bad_ctx, ("generate_content",))  # the content call now says valid=false
    conn = connect()
    try:
        w = words.word_row(conn, wid)
        assert (w["is_valid_english"], w["is_public"], w["content_state"]) == (0, 0, "failed")
        assert conn.execute("SELECT COUNT(*) FROM user_words WHERE word_id = ? AND needs_attention = 1", (wid,)).fetchone()[0] == 2
    finally:
        conn.close()
    assert client.get("/api/vocab?q=zzzap").json()["items"] == []  # the third user no longer sees it
    assert client.get(f"/api/words/{wid}").status_code == 404
    for tok in (a_tok, b_tok):  # the holders still do
        client.cookies.set("wd_session", tok)
        assert client.get(f"/api/words/{wid}").status_code == 200
        assert client.get(f"/api/words/{wid}/content").json()["state"] == "failed"
        assert any(i["lemma"] == "zzzap" and i["mine"]["needs_attention"] for i in client.get("/api/bank").json()["items"])


def test_requeue_dead_jobs_helper(seeded):
    ids = enqueue_content(seeded, seed_words(seeded, 3))
    for j in ids:
        seeded.execute("UPDATE jobs SET status = 'dead', attempts = 3, finished_at = '2026-10-12T00:00:00Z' WHERE id = ?", (j,))
    live = queue.enqueue(seeded, "generate_content", {"word_id": queue.get_job(seeded, ids[0]).payload["word_id"]}, dedupe_key=queue.get_job(seeded, ids[0]).dedupe_key, now=NOW)
    assert live != ids[0]
    assert worker.requeue_dead_jobs(seeded, now=NOW, types=("generate_content",), older_than=__import__("datetime").timedelta(hours=24), limit=50) == 2  # the first collides with the live key
    for j in ids[1:]:
        job = queue.get_job(seeded, j)
        assert job.status == "queued" and job.attempts == 0 and job.payload["group_size"] == 1 and job.run_after == NOW and job.finished_at is None
    assert queue.get_job(seeded, ids[0]).status == "dead"
