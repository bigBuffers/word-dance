"""routers/admin_ops.py — API.md 54–55, 60–69, 72–74: admin-only guard, overview numbers incl. the photo / svg / card-only
split and svg_today_usd, health, jobs list/retry/requeue-dead/run-once, the AI ledger, pause/resume, the probe (exact
object), prewarm fan-out and stops, regenerate (key suffix :r1), refetch-image, events, config masking, push/run."""

from __future__ import annotations

import json
import logging
import secrets
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from wd import db
from wd.deps import hash_token
from wd.jobs import queue, registry, worker
from wd.jobs.registry import JobContext

NOW = "2026-10-14T00:00:00Z"
FAR = "2030-01-01T00:00:00Z"


def make_user(conn, name, role="user"):
    uid = int(conn.execute("INSERT INTO users(username, password_hash, role, onboarding_state) VALUES (?, 'x', ?, 'done')", (name, role)).lastrowid)
    conn.execute("INSERT INTO user_settings(user_id) VALUES (?)", (uid,))
    token = secrets.token_urlsafe(32)
    conn.execute("INSERT INTO sessions(token_hash, user_id, expires_at) VALUES (?, ?, ?)", (hash_token(token), uid, FAR))
    return uid, token


@pytest.fixture
def admin(client: TestClient, seeded):
    uid, token = make_user(seeded, "root", role="admin")
    client.cookies.set("wd_session", token)
    return uid


@pytest.fixture
def ctx(settings, connect, frozen_clock):
    registry.load_handlers()
    return JobContext(db=connect, cfg=replace(settings, ai_batch_size=2), clock=frozen_clock, enqueue=queue.enqueue, log=logging.getLogger("t"), worker_id="claude-1", boot_id="boot")


def word_ids(conn, n, where="is_valid_english = 1 AND is_public = 1"):
    return [int(r[0]) for r in conn.execute(f"SELECT id FROM words WHERE {where} ORDER BY (frq IS NULL OR frq = 0), frq, lemma LIMIT ?", (n,))]


def add_image(conn, word_id, provider, sha):
    iid = int(conn.execute(
        "INSERT INTO word_images(word_id, provider, license, file_path, file_bytes, sha256, mime, status) VALUES (?, ?, 'CC0', ?, 10, ?, ?, 'active') RETURNING id",
        (word_id, provider, f"{sha[:2]}/{sha}.jpg", sha, "image/svg+xml" if provider == "claude_svg" else "image/jpeg"),
    ).fetchone()[0])
    conn.execute("UPDATE words SET active_image_id = ?, image_state = 'ready' WHERE id = ?", (iid, word_id))
    return iid


def add_call(conn, kind, cost, started_at=NOW, status="success"):
    conn.execute(
        "INSERT INTO ai_calls(kind, status, model_requested, flag_tier, word_count, max_budget_usd, reserved_usd, cost_usd, started_at, finished_at) VALUES (?, ?, 'sonnet', 0, 1, 0.25, 0, ?, ?, ?)",
        (kind, status, cost, started_at, started_at),
    )


# -------------------------------------------------------------------------------------------- guard
def test_admin_endpoints_refuse_ordinary_users(client: TestClient, seeded):
    _, token = make_user(seeded, "alice")
    client.cookies.set("wd_session", token)
    for method, path, body in [
        ("GET", "/api/admin/overview", None), ("GET", "/api/admin/health", None), ("GET", "/api/admin/jobs", None), ("POST", "/api/admin/jobs/1/retry", None),
        ("POST", "/api/admin/jobs/requeue-dead", None), ("POST", "/api/admin/jobs/run-once", None), ("GET", "/api/admin/ai/calls", None),
        ("POST", "/api/admin/ai/pause", {"paused": True}), ("POST", "/api/admin/ai/probe", None), ("POST", "/api/admin/content/prewarm", {"stage": "cet4", "limit": 5, "max_budget_usd": 1}),
        ("POST", "/api/admin/words/1/regenerate", None), ("POST", "/api/admin/words/1/refetch-image", {}), ("GET", "/api/admin/events", None), ("GET", "/api/admin/config", None),
        ("POST", "/api/admin/push/run", {"user_id": 1}),
    ]:
        r = client.request(method, path, json=body)
        assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden", path
    client.cookies.clear()
    assert client.get("/api/admin/overview").status_code == 401


# ----------------------------------------------------------------------------------- overview / health
def test_overview_numbers(client: TestClient, seeded, admin):
    ids = word_ids(seeded, 5)
    seeded.execute("UPDATE words SET content_state = 'ready' WHERE id IN (?, ?, ?, ?)", ids[:4])
    add_image(seeded, ids[0], "wikimedia", "a" * 64)
    add_image(seeded, ids[1], "openverse", "b" * 64)
    add_image(seeded, ids[2], "claude_svg", "c" * 64)
    # ids[3] has content but no image → card_only; ids[4] has neither
    add_call(seeded, "content", 0.04)
    add_call(seeded, "svg", 0.028)
    add_call(seeded, "lookup", 0.0, status="auth")
    add_call(seeded, "content", 1.0, started_at="2026-10-01T00:00:00Z")
    queue.enqueue(seeded, "generate_content", {"word_id": ids[4]}, dedupe_key=f"content:{ids[4]}", now=NOW)
    dead = queue.enqueue(seeded, "lookup_word", {"word_id": ids[4]}, dedupe_key=f"lookup:{ids[4]}", now=NOW)
    seeded.execute("UPDATE jobs SET status = 'dead' WHERE id = ?", (dead,))
    seeded.execute("INSERT INTO system_events(kind, detail_json, created_at) VALUES ('budget_daily', '{\"cap_usd\": 3}', ?)", ("2026-10-13T12:00:00Z",))
    seeded.execute("INSERT INTO system_events(kind, detail_json, created_at) VALUES ('old', '{}', '2026-10-01T00:00:00Z')")
    db.kv_set(seeded, "claude.flag_tier", "1")
    db.kv_set(seeded, "last_tick_at", "2026-10-13T23:59:30Z")
    _, _ = make_user(seeded, "alice")
    seeded.execute("INSERT INTO user_words(user_id, word_id, state, origin) VALUES (?, ?, 'new', 'browse')", (admin, ids[0]))
    seeded.execute("INSERT INTO push_batches(user_id, local_date, timezone, trigger) VALUES (?, '2026-10-14', 'Asia/Shanghai', 'manual')", (admin,))
    r = client.get("/api/admin/overview")
    assert r.status_code == 200, r.text
    o = r.json()
    assert o["users"] == {"total": 2, "active_7d": 2}  # both sessions were seen "now"
    w = o["words"]
    assert w["total"] == 60 and w["with_content"] == 4 and (w["with_photo"], w["with_claude_svg"], w["card_only"]) == (2, 1, 1)
    assert w["user_added"] == 0 and w["pending_validation"] == 0
    assert o["bank_entries"] == 1 and o["batches_today"] == 1
    assert o["jobs"] == {"queued": 1, "running": 0, "dead": 1, "by_type": {"generate_content": 1}}
    ai = o["ai"]
    assert ai["enabled"] is True and ai["paused_until"] is None and ai["flag_tier"] == 1
    assert ai["today_usd"] == pytest.approx(0.068) and ai["month_usd"] == pytest.approx(1.068) and ai["svg_today_usd"] == pytest.approx(0.028)
    assert ai["daily_budget_usd"] == 3.0 and ai["svg_daily_budget_usd"] == 0.5 and ai["calls_today"] == 3 and ai["last_error"] == "auth"
    assert ai["avg_cost_per_word_7d"] == pytest.approx(0.04)
    assert isinstance(o["images"]["providers"], list) and {p["provider"] for p in o["images"]["providers"]} >= {"wikimedia", "openverse"}
    assert o["scheduler"] == {"last_tick_at": "2026-10-13T23:59:30Z", "alive": True}
    recent = [e for e in o["events_24h"] if e["kind"] != "seed_imported"]  # the seed import logs its own event
    assert [e["kind"] for e in recent] == ["budget_daily"] and recent[0]["detail"] == {"cap_usd": 3}


def test_health(client: TestClient, seeded, admin, settings):
    db.kv_set(seeded, "seed_version", "abc")
    db.kv_set(seeded, "claude.available", "1")
    db.kv_set(seeded, "claude.version", "2.1.299")
    db.kv_set(seeded, "claude.last_probe_at", NOW)
    db.kv_set(seeded, "backup.last", json.dumps({"file": "word-dance-20261014-0330.db.gz", "at": NOW, "bytes": 12345}))
    r = client.get("/api/admin/health")
    assert r.status_code == 200, r.text
    h = r.json()
    assert h["db_ok"] is True and h["db_size_bytes"] > 0 and h["disk_free_bytes"] > 0 and h["data_dir"] == str(settings.data_dir)
    assert h["scheduler_alive"] is False and h["scheduler_last_tick_at"] is None and h["claude_worker_alive"] is False and h["io_worker_alive"] is False
    assert h["claude_bin"] == {"path": settings.claude_bin, "version": "2.1.299", "ok": True, "flag_tier": 0, "last_probe_at": NOW}
    assert h["seed_version"] == "abc" and h["migrations_version"] == db.list_migration_files()[-1].version and h["worker_lease"] is None
    assert h["last_backup"] == {"file": "word-dance-20261014-0330.db.gz", "at": NOW, "bytes": 12345}


# ----------------------------------------------------------------------------------------------- jobs
def test_jobs_list_retry_requeue_dead_and_run_once(client: TestClient, seeded, admin, settings):
    ids = word_ids(seeded, 3)
    a = queue.enqueue(seeded, "generate_content", {"word_id": ids[0]}, dedupe_key=f"content:{ids[0]}", priority=20, now=NOW)
    b = queue.enqueue(seeded, "lookup_word", {"word_id": ids[1]}, dedupe_key=f"lookup:{ids[1]}", priority=10, now=NOW)
    seeded.execute("UPDATE jobs SET status = 'dead', attempts = 3, last_error = 'x', finished_at = ? WHERE id = ?", (NOW, b))
    r = client.get("/api/admin/jobs")
    assert r.status_code == 200 and r.json()["total"] == 2 and [j["id"] for j in r.json()["items"]] == [b, a]
    assert client.get("/api/admin/jobs?status=dead").json()["items"][0]["id"] == b
    assert client.get("/api/admin/jobs?type=generate_content&status=queued").json()["total"] == 1
    assert client.get("/api/admin/jobs?status=bogus").status_code == 400
    job = client.get("/api/admin/jobs").json()["items"][1]
    assert job == {"id": a, "type": "generate_content", "payload": {"word_id": ids[0]}, "dedupe_key": f"content:{ids[0]}", "priority": 20, "status": "queued", "attempts": 0, "max_attempts": 3, "run_after": NOW, "locked_by": None, "last_error": None, "created_at": NOW, "finished_at": None}
    r = client.post(f"/api/admin/jobs/{b}/retry")
    assert r.status_code == 200 and r.json()["status"] == "queued" and r.json()["attempts"] == 0 and r.json()["run_after"] == NOW and r.json()["finished_at"] is None
    assert client.post("/api/admin/jobs/999/retry").status_code == 404
    seeded.execute("UPDATE jobs SET status = 'running' WHERE id = ?", (b,))
    assert client.post(f"/api/admin/jobs/{b}/retry").json()["error"]["code"] == "invalid_transition"
    seeded.execute("UPDATE jobs SET status = 'dead', finished_at = ? WHERE id IN (?, ?)", (NOW, a, b))
    assert client.post("/api/admin/jobs/requeue-dead").json() == {"requeued": 2}
    assert client.get("/api/admin/jobs?status=queued").json()["total"] == 2
    r = client.post("/api/admin/jobs/run-once")
    assert r.status_code == 403 and "WD_DEV" in r.json()["error"]["details"]["reason"]


def test_run_once_in_dev_mode_drains_the_queue(test_env, monkeypatch, frozen_clock):
    monkeypatch.setenv("WD_DEV", "1")
    from wd.config import Settings, ensure_dirs
    from wd.main import create_app

    cfg = Settings.from_env()
    ensure_dirs(cfg)
    app = create_app(cfg, clock=frozen_clock, configure_logs=False)
    with TestClient(app, base_url="http://testserver") as client:
        client.headers["X-WD-Request"] = "1"
        conn = db.connect(cfg.db_path)
        try:
            from wd.seed import import_seed

            import_seed(conn, str(cfg.seed_path))
            _, token = make_user(conn, "root", role="admin")
            ids = word_ids(conn, 3)
            for w in ids:
                queue.enqueue(conn, "generate_content", {"word_id": w}, dedupe_key=f"content:{w}", now=NOW)
        finally:
            conn.close()
        client.cookies.set("wd_session", token)
        r = client.post("/api/admin/jobs/run-once")
        assert r.status_code == 200 and r.json()["processed"] >= 3
        conn = db.connect(cfg.db_path)
        try:
            assert conn.execute("SELECT COUNT(*) FROM jobs WHERE type = 'generate_content' AND status = 'done'").fetchone()[0] == 3
            assert conn.execute("SELECT COUNT(*) FROM ai_calls").fetchone()[0] == 1
        finally:
            conn.close()


# ------------------------------------------------------------------------------------------------- AI
def test_ai_calls_ledger_page(client: TestClient, seeded, admin):
    add_call(seeded, "content", 0.04)
    add_call(seeded, "content", 0.5, started_at="2026-10-02T00:00:00Z")
    r = client.get("/api/admin/ai/calls?page_size=1")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 2 and len(body["items"]) == 1 and body["items"][0]["kind"] == "content" and body["items"][0]["cost_usd"] == 0.04
    assert body["today_usd"] == pytest.approx(0.04) and body["month_usd"] == pytest.approx(0.54) and body["avg_cost_per_word_7d"] == pytest.approx(0.04)
    assert set(body["items"][0]) == {"id", "kind", "status", "model_requested", "model_used", "flag_tier", "word_count", "cost_usd", "duration_ms", "input_tokens", "output_tokens", "error", "started_at"}


def test_pause_and_resume(client: TestClient, seeded, admin, settings):
    r = client.post("/api/admin/ai/pause", json={"paused": True})
    assert r.status_code == 200 and r.json() == {"paused": True, "paused_until": "2026-10-15T00:00:00Z"}
    assert db.kv_get(seeded, "claude.enabled") == "0" and db.kv_get(seeded, "claude.paused_until") == "2026-10-15T00:00:00Z"
    assert client.get("/api/admin/overview").json()["ai"]["enabled"] is False
    assert client.post("/api/admin/content/prewarm", json={"stage": "cet4", "limit": 5, "max_budget_usd": 1}).json()["error"]["code"] == "ai_disabled"
    r = client.post("/api/admin/ai/pause", json={"paused": False})
    assert r.json() == {"paused": False, "paused_until": None}
    assert db.kv_get(seeded, "claude.enabled") == "1" and db.kv_get(seeded, "claude.paused_until") is None
    assert [e["kind"] for e in client.get("/api/admin/events").json()["items"] if e["kind"].startswith("claude_")] == ["claude_resumed", "claude_paused"]


def test_probe_endpoint_asserts_the_exact_probe_object(client: TestClient, seeded, admin):
    r = client.post("/api/admin/ai/probe")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body["flag_tier"] == 1 and body["cost_usd"] == pytest.approx(0.004) and body["model_used"] == "claude-sonnet-fake" and body["error"] is None
    assert body["duration_ms"] == 1200
    assert db.kv_get(seeded, "claude.flag_tier") == "1" and db.kv_get(seeded, "claude.available") == "1" and db.kv_get(seeded, "claude.last_probe_at") == NOW
    rows = seeded.execute("SELECT kind, status, flag_tier, max_budget_usd FROM ai_calls").fetchall()
    assert [tuple(r) for r in rows] == [("probe", "success", 1, 0.05)]
    r = client.post("/api/admin/ai/probe")
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited" and r.headers["Retry-After"]


def test_probe_falls_back_to_tier0_and_reports_unavailable(seeded, settings, tmp_path, frozen_clock):
    import sys

    from wd.ai import probe

    fake = __import__("pathlib").Path(__file__).resolve().parents[1] / "fake_claude.py"

    def wrapper(mode):
        p = tmp_path / f"claude-{mode}"
        p.write_text(f"#!/usr/bin/env bash\nFAKE_CLAUDE_MODE='{mode}' exec '{sys.executable}' -I '{fake}' \"$@\"\n")
        p.chmod(0o755)
        return str(p)

    res = probe.check(seeded, replace(settings, claude_bin=wrapper("usage_error")), now=NOW)
    assert res.ok and res.flag_tier == 0 and res.fallback and db.kv_get(seeded, "claude.flag_tier") == "0" and db.kv_get(seeded, "claude.available") == "1"
    assert [tuple(r) for r in seeded.execute("SELECT status, flag_tier FROM ai_calls ORDER BY id")] == [("error", 1), ("success", 0)]
    assert seeded.execute("SELECT COUNT(*) FROM system_events WHERE kind = 'claude_probe_fallback'").fetchone()[0] == 1
    res = probe.check(seeded, replace(settings, claude_bin=wrapper("auth")), now=NOW)
    assert not res.ok and db.kv_get(seeded, "claude.available") == "0" and "tier 1" in res.error and "tier 0" in res.error
    assert seeded.execute("SELECT COUNT(*) FROM system_events WHERE kind = 'claude_unavailable'").fetchone()[0] == 1
    assert db.kv_get(seeded, "claude.flag_tier") == "0"  # the runner never changes the tier on its own; the probe keeps the last good one
    assert probe.record_version(seeded, settings) is None  # the fake has no --version


# -------------------------------------------------------------------------------------------- prewarm
def test_prewarm_fans_out_in_passes_and_stops_at_the_limit(client: TestClient, seeded, admin, ctx):
    available = seeded.execute("SELECT COUNT(*) FROM words WHERE stage_cet4 = 1 AND is_public = 1 AND is_valid_english = 1 AND content_state = 'none'").fetchone()[0]
    assert available >= 12
    r = client.post("/api/admin/content/prewarm", json={"stage": "cet4", "limit": 12, "max_budget_usd": 2.0})
    assert r.status_code == 202, r.text
    plan_job = r.json()["job_id"]
    assert r.json()["planned"] == 12
    job = queue.get_job(seeded, plan_job)
    assert job.priority == 90 and job.dedupe_key == f"prewarm:{job.payload['plan_id']}" and job.payload["limit"] == 12 and job.payload["stage"] == "cet4"
    plan_id = job.payload["plan_id"]
    worker.drain(ctx, ("prewarm_plan",))  # pass 1: 5 × batch(2) = 10 content jobs
    content = seeded.execute("SELECT priority, payload_json FROM jobs WHERE type = 'generate_content' ORDER BY id").fetchall()
    assert len(content) == 10 and all(r[0] == 90 and json.loads(r[1])["plan_id"] == plan_id for r in content)
    assert db.kv_get(seeded, f"prewarm:{plan_id}:planned") == "10"
    plan = queue.get_job(seeded, plan_job)
    assert plan.status == "queued" and plan.run_after == "2026-10-14T00:02:00Z" and plan.attempts == 0
    assert worker.drain(ctx, ("prewarm_plan",)) == 0  # not runnable before the deferral ends
    ctx.clock.advance(minutes=2)
    worker.drain(ctx, ("prewarm_plan",))  # pass 2: the remaining 2
    assert seeded.execute("SELECT COUNT(*) FROM jobs WHERE type = 'generate_content'").fetchone()[0] == 12
    ctx.clock.advance(minutes=2)
    worker.drain(ctx, ("prewarm_plan",))  # pass 3: planned ≥ limit → done, nothing cancelled
    plan = queue.get_job(seeded, plan_job)
    assert plan.status == "done" and plan.result["stopped"] == "limit" and plan.result["planned"] == 12 and plan.result["cancelled"] == 0
    assert seeded.execute("SELECT COUNT(*) FROM jobs WHERE type = 'generate_content' AND status = 'queued'").fetchone()[0] == 12
    assert seeded.execute("SELECT COUNT(*) FROM words WHERE content_state = 'queued'").fetchone()[0] == 12


def test_prewarm_stops_at_budget_and_cancels_leftovers(client: TestClient, seeded, admin, ctx):
    r = client.post("/api/admin/content/prewarm", json={"stage": "all", "limit": 100, "max_budget_usd": 0.5})
    plan_job = r.json()["job_id"]
    plan_id = queue.get_job(seeded, plan_job).payload["plan_id"]
    worker.drain(ctx, ("prewarm_plan",))
    queued = [int(x[0]) for x in seeded.execute("SELECT id FROM jobs WHERE type = 'generate_content' AND status = 'queued'")]
    assert len(queued) == 10
    seeded.execute("UPDATE jobs SET status = 'done' WHERE id = ?", (queued[0],))  # one content job already ran
    db.kv_set(seeded, f"prewarm:{plan_id}:spent", "0.52")
    ctx.clock.advance(minutes=2)
    worker.drain(ctx, ("prewarm_plan",))
    plan = queue.get_job(seeded, plan_job)
    assert plan.status == "done" and plan.result["stopped"] == "budget" and plan.result["cancelled"] == 9 and plan.result["spent"] == 0.52
    assert seeded.execute("SELECT COUNT(*) FROM jobs WHERE type = 'generate_content' AND status = 'cancelled'").fetchone()[0] == 9
    assert seeded.execute("SELECT COUNT(*) FROM words WHERE content_state = 'queued'").fetchone()[0] == 1  # the done one keeps its state here; cancelled words are back to none
    assert client.post("/api/admin/content/prewarm", json={"stage": "nope", "limit": 1, "max_budget_usd": 1}).status_code == 400
    assert client.post("/api/admin/content/prewarm", json={"stage": "cet4", "limit": 0, "max_budget_usd": 1}).status_code == 400


# ---------------------------------------------------------------------------------- regenerate / image
def test_regenerate_uses_the_r_suffix_and_refetch_image_enqueues(client: TestClient, seeded, admin):
    wid = word_ids(seeded, 1)[0]
    queue.enqueue(seeded, "generate_content", {"word_id": wid}, dedupe_key=f"content:{wid}", now=NOW)  # a live plain job does not collide
    r = client.post(f"/api/admin/words/{wid}/regenerate")
    assert r.status_code == 202, r.text
    job = queue.get_job(seeded, r.json()["job_id"])
    assert job.dedupe_key == f"content:{wid}:r1" and job.payload == {"word_id": wid, "force": True} and job.priority == 10
    r2 = client.post(f"/api/admin/words/{wid}/regenerate")
    assert queue.get_job(seeded, r2.json()["job_id"]).dedupe_key == f"content:{wid}:r2"
    assert client.post("/api/admin/words/999999/regenerate").status_code == 404
    prov = int(seeded.execute("INSERT INTO words(lemma, display, source, is_public, is_valid_english) VALUES ('zzqx', 'zzqx', 'user', 0, NULL) RETURNING id").fetchone()[0])
    assert client.post(f"/api/admin/words/{prov}/regenerate").json()["error"]["code"] == "invalid_transition"
    r = client.post(f"/api/admin/words/{wid}/refetch-image", json={"provider": "openverse", "query": "red apple"})
    assert r.status_code == 202, r.text
    fetch = queue.get_job(seeded, r.json()["job_id"])
    assert fetch.type == "fetch_image" and fetch.payload["word_id"] == wid and fetch.payload["provider"] == "openverse" and fetch.payload["query"] == "red apple" and fetch.priority == 10
    assert seeded.execute("SELECT image_state FROM words WHERE id = ?", (wid,)).fetchone()[0] == "queued"
    assert client.post("/api/admin/words/999999/refetch-image", json={}).status_code == 404
    assert client.post(f"/api/admin/words/{wid}/refetch-image", json={"provider": "bing"}).status_code == 400


# ---------------------------------------------------------------------------------- events / config
def test_events_and_config(client: TestClient, seeded, admin, settings):
    for i in range(3):
        seeded.execute("INSERT INTO system_events(kind, detail_json, created_at) VALUES (?, ?, ?)", (f"k{i}", json.dumps({"i": i}), f"2026-10-1{i}T00:00:00Z"))
    seeded.execute("DELETE FROM system_events WHERE kind = 'seed_imported'")
    r = client.get("/api/admin/events?page_size=2")
    assert r.status_code == 200 and r.json()["total"] == 3 and [e["kind"] for e in r.json()["items"]] == ["k2", "k1"] and r.json()["items"][0]["detail"] == {"i": 2}
    assert [e["kind"] for e in client.get("/api/admin/events?page=2&page_size=2").json()["items"]] == ["k0"]
    r = client.get("/api/admin/config")
    assert r.status_code == 200
    entries = {e["key"]: e for e in r.json()["entries"]}
    assert entries["WD_SECRET_KEY"] == {"key": "WD_SECRET_KEY", "value": "***", "source": "env"}
    assert entries["WD_AI_MODEL"]["value"] == "sonnet" and entries["WD_AI_MODEL"]["source"] == "default"
    assert entries["WD_CLAUDE_BIN"]["value"] == settings.claude_bin and entries["WD_CLAUDE_BIN"]["source"] == "env"
    assert "test-secret" not in r.text


def test_push_run_without_the_batches_module(client: TestClient, seeded, admin):
    import importlib.util

    r = client.post("/api/admin/push/run", json={"user_id": admin})
    if importlib.util.find_spec("wd.services.batches") is None:
        assert r.status_code == 503 and r.json()["error"]["code"] == "ai_disabled" and "推送" in r.json()["error"]["message"]
    else:  # WP4 merged: builds and publishes
        assert r.status_code == 200 and r.json()["status"] == "published"
    assert client.post("/api/admin/push/run", json={"user_id": 999999}).status_code == 404
