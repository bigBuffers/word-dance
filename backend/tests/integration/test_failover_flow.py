"""End-to-end failover (CLAUDE_INTEGRATION §10) with the real fake ``claude`` subprocess and the fake OpenAI transport:
a lookup group and a consolidation hit the enterprise "managed settings" outage on the CLI and finish on the fallback
within the same claim (ledger rows of both providers, ``kv.ai.active_provider`` flipped, events, deferral-free); content
is routed to the fallback by default since slice 2 (``WD_AI_FALLBACK_KINDS=content,lookup,consolidate``) — a 10-word
group claimed for the CLI is regrouped to ``WD_AI_FALLBACK_BATCH_SIZE`` before it reruns there, later claims use that
size, prewarm groups (priority ≥ 90) keep waiting for the CLI, three unusable fallback answers pause it for quality,
and the fail-back requeues the content jobs that died during the outage — while a content group waits for the CLI's
pause when the operator removed ``content`` from the kinds; the fail-back probe flips the sticky state back;
``openai_http`` mode never spawns the CLI and pauses only the fallback on its own hard failure; in ``auto`` mode a
fallback hard failure reruns the group on the healthy CLI (and fails back); ``claude_cli`` mode keeps today's behaviour
byte for byte (pause + ``claude_auth`` event, no fallback row). The review follow-ups are driven end to end as well: the
handlers' quality hooks (a group rejected whole strikes, an applied group ends the streak), the prewarm split parking the
whole backlog and its release on fail-back, a ``truncated:`` answer bisecting without an attempt, the fallback's
``valid=false`` never invalidating a word, the §6.3 → dead → fail-back → ``queued`` → CLI regeneration chain of the 死词,
and a revived regenerate superseded by a newer card."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import secrets
import sys
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import fake_openai
from wd import db
from wd.ai import budget, common, failover, probe
from wd.ai.providers import openai_http
from wd.deps import hash_token
from wd.jobs import queue, registry, worker
from wd.jobs.queue import CLAUDE_TYPES
from wd.jobs.registry import JobContext
from wd.main import create_app
from wd.services import bank, words

NOW = "2026-10-14T00:00:00Z"
CLAUDE_PAUSE_END = "2026-10-14T00:30:00Z"  # NOW + WD_AI_FAILOVER_COOLDOWN_MIN
FAKE = Path(__file__).resolve().parents[1] / "fake_claude.py"


def wrapper(directory: Path, mode: str) -> str:
    directory.mkdir(parents=True, exist_ok=True)
    script = directory / f"claude-{mode}"
    script.write_text(f"#!/usr/bin/env bash\nFAKE_CLAUDE_MODE='{mode}' exec '{sys.executable}' -I '{FAKE}' \"$@\"\n", encoding="utf-8")
    script.chmod(0o755)
    return str(script)


@pytest.fixture
def fb_cfg(settings, tmp_path):
    """``auto`` mode: the CLI first, the fallback for content + lookup + consolidate (the spec's defaults since slice 2)."""
    key_file = tmp_path / "zhipu.key"
    key_file.write_text("sk-test-not-a-real-key\n", encoding="utf-8")
    key_file.chmod(0o600)

    def _cfg(claude_mode: str = "ok", **overrides):
        fields = {
            "claude_bin": wrapper(tmp_path / "bin", claude_mode),
            "ai_provider": "auto",
            "ai_fallback_kind": "openai_http",
            "ai_fallback_base_url": "https://mock.example/api/paas/v4",
            "ai_fallback_model": "glm-4.7-flash",
            "ai_fallback_dialect": "zhipu",  # the mock host would resolve to `generic`; a real bigmodel.cn URL resolves to zhipu by itself
            "ai_fallback_api_key_file": str(key_file),
        }
        fields.update(overrides)
        return replace(settings, **fields)

    return _cfg


@pytest.fixture
def fake_http(monkeypatch):
    """Route the adapter's httpx client to ``fake_openai``; returns the recorded requests and a mode switch."""
    state = {"mode": "ok", "calls": []}

    def factory(timeout_s: float) -> httpx.Client:
        return httpx.Client(transport=fake_openai.transport(state["mode"], calls=state["calls"]), timeout=timeout_s)

    monkeypatch.setattr(openai_http, "CLIENT_FACTORY", factory)
    return state


def rewriting_http(monkeypatch, state, mutate_item):
    """Route the adapter to the fake in ``ok`` mode but rewrite every answer item through ``mutate_item``: the answer stays ON
    schema (no adapter error, no repair round) and fails only the handler's post-validation."""

    def factory(timeout_s: float) -> httpx.Client:
        inner = fake_openai.transport("ok", calls=state["calls"])

        def handler(request: httpx.Request) -> httpx.Response:
            resp = inner.handler(request)
            data = json.loads(resp.content)
            obj = json.loads(data["choices"][0]["message"]["content"])
            obj["items"] = [mutate_item(dict(it)) for it in obj["items"]]
            data["choices"][0]["message"]["content"] = json.dumps(obj, ensure_ascii=False)
            return httpx.Response(200, headers={"Content-Type": "application/json"}, content=json.dumps(data, ensure_ascii=False).encode("utf-8"))

        return httpx.Client(transport=httpx.MockTransport(handler), timeout=timeout_s)

    monkeypatch.setattr(openai_http, "CLIENT_FACTORY", factory)


def make_ctx(connect, cfg, clock):
    registry.load_handlers()
    return JobContext(db=connect, cfg=cfg, clock=clock, enqueue=queue.enqueue, log=logging.getLogger("t"), worker_id="claude-1", boot_id="boot-a")


def make_user(conn, name="learner"):
    uid = int(conn.execute("INSERT INTO users(username, password_hash, role, onboarding_state) VALUES (?, 'x', 'user', 'done')", (name,)).lastrowid)
    conn.execute("INSERT INTO user_settings(user_id) VALUES (?)", (uid,))
    return uid


def session_for(conn, uid: int) -> str:
    token = secrets.token_urlsafe(32)
    conn.execute("INSERT INTO sessions(token_hash, user_id, expires_at) VALUES (?, ?, '2030-01-01T00:00:00Z')", (hash_token(token), uid))
    return token


def add_custom_words(conn, uid, texts, now=NOW):
    """Provisional words + their debounced lookups, pinned to the frozen clock."""
    for t in texts:
        res = bank.add_one(conn, uid, t, note=None, study_today=False, now=now, tz="Asia/Shanghai")
        assert res.status in ("added", "readded", "exists", "pending_ai"), res  # a provisional word reports pending_ai
    conn.execute("UPDATE jobs SET run_after = ? WHERE type = 'lookup_word' AND status = 'queued'", (now,))


def calls(conn):
    return [dict(r) for r in conn.execute("SELECT id, kind, status, provider, model_requested, model_used, word_count, error FROM ai_calls ORDER BY id").fetchall()]


def events(conn):
    """AI-related event kinds in order (the seed import's own event is not under test)."""
    return [str(r[0]) for r in conn.execute("SELECT kind FROM system_events WHERE kind != 'seed_imported' ORDER BY id")]


def event_details(conn, kind: str) -> list[dict]:
    return [json.loads(r[0]) for r in conn.execute("SELECT detail_json FROM system_events WHERE kind = ? ORDER BY id", (kind,))]


def seed_words(conn, n):
    return [int(r[0]) for r in conn.execute("SELECT id FROM words WHERE is_valid_english = 1 AND is_public = 1 AND content_state = 'none' ORDER BY (frq IS NULL OR frq = 0), frq, lemma LIMIT ?", (n,))]


def enqueue_content(conn, word_ids, priority=20):
    return [queue.enqueue(conn, "generate_content", {"word_id": w}, dedupe_key=f"content:{w}", priority=priority, now=NOW) for w in word_ids]


def items_of(call: dict) -> list[dict]:
    """The words a fallback content request carries: the JSON object inside ``<items>…</items>`` of its user message
    (CLAUDE_INTEGRATION §5.2: ``{"audience": …, "words": [...]}``; the repair round appends messages, index 1 stays the original)."""
    user = call["json"]["messages"][1]["content"]
    m = re.search(r"<items>\s*(.*?)\s*</items>", user, re.DOTALL)
    assert m, user[:200]
    return json.loads(m.group(1))["words"]


def displays(conn, word_ids) -> set[str]:
    return {str(r[0]).lower() for r in conn.execute(f"SELECT display FROM words WHERE id IN ({','.join('?' * len(word_ids))})", list(word_ids))}


# --------------------------------------------------------------------------------------------- lookup
def test_lookup_group_fails_over_to_the_fallback_within_one_claim(seeded, connect, frozen_clock, fb_cfg, fake_http):
    uid = make_user(seeded)
    add_custom_words(seeded, uid, ["zorblax", "quintessentially"])
    ctx = make_ctx(connect, fb_cfg("managed_settings"), frozen_clock)
    assert worker.drain(ctx, CLAUDE_TYPES) >= 2  # the two lookups + the content jobs they enqueue (content is a fallback kind too: same drain)
    rows = calls(seeded)
    assert [(r["kind"], r["status"], r["provider"]) for r in rows[:2]] == [("lookup", "auth", "claude"), ("lookup", "success", "fallback")]
    assert rows[2:] and all((r["kind"], r["status"], r["provider"]) == ("content", "success", "fallback") for r in rows[2:])
    assert "managed settings" in rows[0]["error"] and rows[1]["model_requested"] == "glm-4.7-flash" and rows[1]["model_used"]
    assert all(j["status"] == "done" for j in seeded.execute("SELECT status FROM jobs WHERE type IN ('lookup_word', 'generate_content')").fetchall())
    assert db.kv_get(seeded, "ai.active_provider") == "fallback"
    assert db.kv_get(seeded, "claude.paused_until") == CLAUDE_PAUSE_END
    assert db.kv_get(seeded, "ai.failover.next_probe_at") == CLAUDE_PAUSE_END
    assert events(seeded).count("claude_auth") == 1 and events(seeded).count("ai_failover") == 1
    # the words were validated by the fallback answer: nothing is flagged 暂时无法校验
    assert seeded.execute("SELECT COUNT(*) FROM words WHERE is_valid_english IS NULL AND created_by_user_id = ?", (uid,)).fetchone()[0] == 0
    assert seeded.execute("SELECT COUNT(*) FROM user_words WHERE user_id = ? AND needs_attention = 1", (uid,)).fetchone()[0] == 0
    # the fake transport saw the lookup request first (then the content ones), each with a bearer token it never stores
    assert len(fake_http["calls"]) == 1 + len(rows[2:]) and all(c["url"].endswith("/chat/completions") for c in fake_http["calls"])
    assert all("Authorization" not in c["headers"] for c in fake_http["calls"])
    # the credential sent is exactly the first line of the 0600 key file (the fake keeps only its SHA-256, never the token)
    assert fake_http["calls"][0]["auth_sha256"] == hashlib.sha256(b"sk-test-not-a-real-key").hexdigest()
    body = fake_http["calls"][0]["json"]
    assert body["model"] == "glm-4.7-flash" and body["response_format"] == {"type": "json_object"} and body["thinking"] == {"type": "disabled"}
    assert "JSON" in body["messages"][0]["content"] and "<items>" in body["messages"][1]["content"]


def test_subsequent_groups_stay_on_the_fallback_and_user_gates_report_available(seeded, connect, frozen_clock, fb_cfg, fake_http):
    uid = make_user(seeded)
    add_custom_words(seeded, uid, ["zorblax"])
    cfg = fb_cfg("managed_settings")
    ctx = make_ctx(connect, cfg, frozen_clock)
    worker.drain(ctx, CLAUDE_TYPES)
    assert db.kv_get(seeded, "ai.active_provider") == "fallback"
    assert [(r["kind"], r["status"], r["provider"]) for r in calls(seeded)] == [("lookup", "auth", "claude"), ("lookup", "success", "fallback"), ("content", "success", "fallback")]
    # a second lookup (and the content job it enqueues) goes straight to the fallback: no CLI spawn
    frozen_clock.advance(minutes=1)
    now = ctx.now()
    add_custom_words(seeded, uid, ["frobnicate"], now=now)
    worker.drain(ctx, CLAUDE_TYPES)
    assert [(r["kind"], r["status"], r["provider"]) for r in calls(seeded)][3:] == [("lookup", "success", "fallback"), ("content", "success", "fallback")]
    # the consolidate gate (立即整理) and the content gates (生成例句, deferred_until) see an available provider although the CLI is paused
    assert bank.ai_paused_until(seeded, now, cfg=cfg, kind="consolidate") is None
    assert bank.ai_paused_until(seeded, now, cfg=cfg, kind="content") is None
    assert bank.ai_paused_until(seeded, now) == CLAUDE_PAUSE_END  # legacy readers still see the CLI pause
    queued_word = seed_words(seeded, 1)[0]
    queue.enqueue(seeded, "generate_content", {"word_id": queued_word}, dedupe_key=f"content:{queued_word}", priority=20, now=now)
    assert words.content_deferred_until(seeded, queued_word, now=now, cfg=cfg) is None  # the fallback takes it at the next claim
    assert words.content_deferred_until(seeded, queued_word, now=now) == CLAUDE_PAUSE_END  # the legacy reader
    assert bank.ai_paused_until(seeded, now, cfg=fb_cfg("managed_settings", ai_fallback_kinds=("lookup", "consolidate")), kind="content") == CLAUDE_PAUSE_END  # content removed from the kinds: a pause again
    avail = failover.availability(seeded, cfg, kind="lookup", now=now)
    assert avail.ok and avail.provider == "fallback" and avail.active == "fallback"
    avail = failover.availability(seeded, cfg, kind="content", now=now)
    assert avail.ok and avail.provider == "fallback" and avail.reason == "ok"


# -------------------------------------------------------------------------------------------- content
def test_content_group_waits_for_the_cli_when_content_is_excluded_from_the_kinds(seeded, connect, frozen_clock, fb_cfg, fake_http):
    ids = enqueue_content(seeded, seed_words(seeded, 3))
    ctx = make_ctx(connect, fb_cfg("managed_settings", ai_fallback_kinds=("lookup", "consolidate")), frozen_clock)
    worker.drain(ctx, CLAUDE_TYPES)
    rows = calls(seeded)
    assert [(r["kind"], r["status"], r["provider"]) for r in rows] == [("content", "auth", "claude")]
    paused = db.kv_get(seeded, "claude.paused_until")
    assert paused == CLAUDE_PAUSE_END
    assert all(queue.get_job(seeded, j).status == "queued" and queue.get_job(seeded, j).run_after == paused for j in ids)
    # a hard trigger announces the outage (sticky state, probe schedule, event) even when the failing kind is not routable;
    # the content group itself is never rerun on the fallback
    assert db.kv_get(seeded, "ai.active_provider") == "fallback" and events(seeded).count("ai_failover") == 1
    assert fake_http["calls"] == []


def test_content_group_runs_on_the_fallback_by_default(seeded, connect, frozen_clock, fb_cfg, fake_http):
    ids = enqueue_content(seeded, seed_words(seeded, 3))
    ctx = make_ctx(connect, fb_cfg("managed_settings"), frozen_clock)
    worker.drain(ctx, CLAUDE_TYPES)
    assert [(r["kind"], r["status"], r["provider"]) for r in calls(seeded)] == [("content", "auth", "claude"), ("content", "success", "fallback")]
    assert all(queue.get_job(seeded, j).status == "done" for j in ids)
    models = {str(r[0]) for r in seeded.execute("SELECT model FROM word_contents")}
    assert models == {"glm-4.7-flash"}  # provenance: the vendor id, never a Claude name
    assert seeded.execute("SELECT COUNT(*) FROM words WHERE content_state = 'ready'").fetchone()[0] == 3
    assert db.kv_get(seeded, "ai.fallback.streak.invalid") is None  # applied answers never count


def test_a_ten_word_content_group_is_regrouped_to_the_fallback_batch(seeded, connect, frozen_clock, fb_cfg, fake_http):
    """§10.5: the 10-word group claimed for the CLI fails there, is regrouped to WD_AI_FALLBACK_BATCH_SIZE (no attempt
    consumed) and runs as 5 + 5 on the fallback within the same drain."""
    word_ids = seed_words(seeded, 10)
    ids = enqueue_content(seeded, word_ids)
    ctx = make_ctx(connect, fb_cfg("managed_settings"), frozen_clock)
    worker.drain(ctx, CLAUDE_TYPES)
    rows = calls(seeded)
    assert [(r["kind"], r["status"], r["provider"], r["word_count"]) for r in rows] == [("content", "auth", "claude", 10), ("content", "success", "fallback", 5), ("content", "success", "fallback", 5)]
    assert [len(items_of(c)) for c in fake_http["calls"]] == [5, 5]
    sent = [w["word"].lower() for c in fake_http["calls"] for w in items_of(c)]
    assert len(sent) == len(set(sent)) == 10 and set(sent) == displays(seeded, word_ids)  # every word exactly once
    for j in ids:
        job = queue.get_job(seeded, j)
        assert (job.status, job.payload["group_size"], job.attempts) == ("done", 5, 1), job
    assert {str(r[0]) for r in seeded.execute("SELECT model FROM word_contents")} == {"glm-4.7-flash"}
    assert seeded.execute("SELECT COUNT(*) FROM words WHERE content_state = 'ready'").fetchone()[0] == 10
    assert events(seeded).count("ai_failover") == 1 and events(seeded).count("claude_auth") == 1
    assert db.kv_get(seeded, "ai.active_provider") == "fallback" and db.kv_get(seeded, "claude.paused_until") == CLAUDE_PAUSE_END


@pytest.mark.parametrize(
    ("claude_mode", "overrides", "sticky", "sizes"),
    [
        ("ok", {}, True, [5, 2]),
        ("ok", {"ai_fallback_batch_size": 3}, True, [3, 3, 1]),
        ("ok", {"ai_batch_size": 3, "ai_fallback_batch_size": 8}, True, [3, 3, 1]),  # the CLI batch is the ceiling of the effective size
        ("auth", {"ai_provider": "openai_http"}, False, [5, 2]),  # openai_http: every content head goes to the fallback — no sticky state, no CLI spawn
        ("auth", {"ai_provider": "openai_http", "ai_fallback_batch_size": 3}, False, [3, 3, 1]),
    ],
)
def test_claims_use_the_fallback_batch_size_while_the_fallback_takes_content(seeded, connect, frozen_clock, fb_cfg, fake_http, claude_mode, overrides, sticky, sizes):
    """§10.5: while the sticky state names the fallback and the CLI is paused — or in mode ``openai_http`` — ``failover.claim_limit``
    claims content in groups of min(WD_AI_BATCH_SIZE, WD_AI_FALLBACK_BATCH_SIZE): no regroup mark, no CLI row (the ``auth`` fake
    would leave one if the CLI were spawned in ``openai_http`` mode)."""
    if sticky:
        db.kv_set(seeded, "ai.active_provider", "fallback")  # left by an earlier CLI outage
        budget.set_paused_until(seeded, CLAUDE_PAUSE_END, now=NOW)
    word_ids = seed_words(seeded, 7)
    ids = enqueue_content(seeded, word_ids)
    ctx = make_ctx(connect, fb_cfg(claude_mode, **overrides), frozen_clock)
    worker.drain(ctx, CLAUDE_TYPES)
    assert [(r["kind"], r["status"], r["provider"], r["word_count"]) for r in calls(seeded)] == [("content", "success", "fallback", n) for n in sizes]
    assert [len(items_of(c)) for c in fake_http["calls"]] == sizes
    sent = [w["word"].lower() for c in fake_http["calls"] for w in items_of(c)]
    assert len(sent) == len(set(sent)) == 7 and set(sent) == displays(seeded, word_ids)  # every word exactly once
    for j in ids:
        job = queue.get_job(seeded, j)
        assert (job.status, job.attempts) == ("done", 1) and "group_size" not in job.payload, job  # claimed at the right size: no bisection / regroup mark
    assert events(seeded).count("ai_failback") == 0 and events(seeded).count("claude_auth") == 0 and events(seeded).count("ai_failover") == 0
    if sticky:
        assert db.kv_get(seeded, "ai.active_provider") == "fallback"  # a fallback success never flips
    else:
        assert db.kv_get(seeded, "claude.paused_until") is None and db.kv_get(seeded, "ai.active_provider") is None  # the broken CLI fake was never spawned


def test_prewarm_content_waits_for_the_cli_while_ordinary_content_uses_the_fallback(seeded, connect, frozen_clock, fb_cfg, fake_http):
    """§10.1: prewarm groups (priority ≥ 90) stay off the fallback without WD_AI_FALLBACK_PREWARM — also when the claim
    mixed them with ordinary jobs: the ordinary ones run on the fallback alone, the prewarm ones wait for the CLI."""
    word_ids = seed_words(seeded, 5)
    prewarm = enqueue_content(seeded, word_ids[:3], priority=90)
    ordinary = enqueue_content(seeded, word_ids[3:], priority=20)
    ctx = make_ctx(connect, fb_cfg("managed_settings"), frozen_clock)
    worker.drain(ctx, CLAUDE_TYPES)
    rows = calls(seeded)
    assert [(r["kind"], r["status"], r["provider"], r["word_count"]) for r in rows] == [("content", "auth", "claude", 5), ("content", "success", "fallback", 2)]
    paused = db.kv_get(seeded, "claude.paused_until")
    assert paused == CLAUDE_PAUSE_END
    assert all(queue.get_job(seeded, j).status == "done" for j in ordinary)
    for j in prewarm:
        job = queue.get_job(seeded, j)
        assert (job.status, job.run_after, job.attempts) == ("queued", paused, 0), job
    sent = {w["word"].lower() for c in fake_http["calls"] for w in items_of(c)}
    assert len(fake_http["calls"]) == 1 and sent == displays(seeded, word_ids[3:]) and sent.isdisjoint(displays(seeded, word_ids[:3]))
    assert seeded.execute("SELECT COUNT(*) FROM words WHERE content_state = 'ready'").fetchone()[0] == 2
    # a fail-back BEFORE the pause instant releases the parked p90 jobs (the exact-instant match of _release_parked — at
    # +30 min the instant is already past and run_after legitimately stays 00:30) and the pure prewarm group runs on the
    # restored CLI, never on the fallback
    frozen_clock.advance(minutes=10)
    good = make_ctx(connect, fb_cfg("ok"), frozen_clock)
    assert failover.maybe_probe(seeded, good.cfg, now=good.now(), probe_claude=lambda: probe.check(seeded, good.cfg, now=good.now()), force=True) == "failback"
    assert db.kv_get(seeded, "ai.active_provider") == "claude" and budget.provider_paused_until(seeded, "claude", good.now()) is None
    for j in prewarm:
        job = queue.get_job(seeded, j)
        assert (job.status, job.run_after, job.attempts) == ("queued", good.now(), 0), job  # released from the lifted pause instant
    worker.drain(good, CLAUDE_TYPES)
    rows = calls(seeded)
    assert (rows[-1]["kind"], rows[-1]["status"], rows[-1]["provider"], rows[-1]["word_count"]) == ("content", "success", "claude", 3)
    assert [r["kind"] for r in rows[2:-1]] == ["probe"] * (len(rows) - 3)  # only the probe between the split and the CLI run
    assert len(fake_http["calls"]) == 1  # still only the p20 request: no p90 word ever reached the fallback
    assert all(queue.get_job(seeded, j).status == "done" and queue.get_job(seeded, j).attempts == 1 for j in prewarm)
    assert seeded.execute("SELECT COUNT(*) FROM words WHERE content_state = 'ready'").fetchone()[0] == 5
    assert "glm-4.7-flash" not in {str(r[0]) for r in seeded.execute(f"SELECT model FROM word_contents WHERE word_id IN ({','.join('?' * 3)})", word_ids[:3])}


def test_a_pure_prewarm_group_waits_at_the_claude_pause_while_the_fallback_is_active(seeded, connect, frozen_clock, fb_cfg, fake_http):
    """§10.1: a pure prewarm group while the sticky state names the fallback is claimed at the plain CLI size, spawns no CLI
    (paused) and sends no fallback request (prewarm is not routable): it waits at the claude pause with no attempt spent and
    runs on the restored CLI in one call after the fail-back."""
    uid = make_user(seeded)
    add_custom_words(seeded, uid, ["zorblax"])
    ctx = make_ctx(connect, fb_cfg("managed_settings"), frozen_clock)
    worker.drain(ctx, CLAUDE_TYPES)
    assert db.kv_get(seeded, "ai.active_provider") == "fallback" and db.kv_get(seeded, "claude.paused_until") == CLAUDE_PAUSE_END
    rows_before, http_before = calls(seeded), len(fake_http["calls"])
    prewarm = enqueue_content(seeded, seed_words(seeded, 3), priority=90)
    assert failover.claim_limit(seeded, ctx.cfg, "generate_content", now=ctx.now()) == 10  # a p90 head: the fallback does not take it
    worker.drain(ctx, CLAUDE_TYPES)
    assert calls(seeded) == rows_before and len(fake_http["calls"]) == http_before
    for j in prewarm:
        job = queue.get_job(seeded, j)
        assert (job.status, job.run_after, job.attempts) == ("queued", CLAUDE_PAUSE_END, 0) and "group_size" not in job.payload, job
    frozen_clock.advance(minutes=31)
    good = make_ctx(connect, fb_cfg("ok"), frozen_clock)
    assert failover.maybe_probe(seeded, good.cfg, now=good.now(), probe_claude=lambda: probe.check(seeded, good.cfg, now=good.now())) == "failback"
    worker.drain(good, CLAUDE_TYPES)
    rows = calls(seeded)
    assert (rows[-1]["kind"], rows[-1]["status"], rows[-1]["provider"], rows[-1]["word_count"]) == ("content", "success", "claude", 3)
    assert all(queue.get_job(seeded, j).status == "done" for j in prewarm) and len(fake_http["calls"]) == http_before


def test_three_invalid_content_groups_pause_the_fallback_for_quality(seeded, connect, frozen_clock, fb_cfg, fake_http):
    """§10.4: a silently degraded fallback model (every answer off-schema, also after the repair round) must not burn every
    content job to dead — the third unusable group in a row pauses the fallback for the cooldown (``ai_fallback_quality``),
    the rejected groups follow the §6.3 error path (one attempt, the 2-minute backoff) and the jobs never attempted wait
    for the earlier of the two pauses."""
    fake_http["mode"] = "schema_mismatch"
    ids = enqueue_content(seeded, seed_words(seeded, 20))
    ctx = make_ctx(connect, fb_cfg("managed_settings"), frozen_clock)
    worker.drain(ctx, CLAUDE_TYPES)
    rows = calls(seeded)
    assert [(r["kind"], r["status"], r["provider"], r["word_count"]) for r in rows] == [("content", "auth", "claude", 10), *([("content", "error", "fallback", 5)] * 3)]
    assert all(r["error"].startswith("schema:") for r in rows[1:])
    assert len(fake_http["calls"]) == 6  # three groups × (the answer + its one repair round); no 4th group reaches the fallback
    assert db.kv_get(seeded, "ai.fallback.paused_until") == CLAUDE_PAUSE_END == db.kv_get(seeded, "claude.paused_until")
    assert db.kv_get(seeded, "ai.fallback.streak.invalid") == "0" and db.kv_get(seeded, "ai.active_provider") == "fallback"
    quality = event_details(seeded, "ai_fallback_quality")
    assert len(quality) == 1 and quality[0]["consecutive"] == 3 and quality[0]["kind"] == "content" and quality[0]["status"] == "error"
    assert quality[0]["paused_until"] == CLAUDE_PAUSE_END and quality[0]["model_seen"] == "glm-4.7-flash" and quality[0]["call_id"] == rows[3]["id"]
    assert events(seeded).count("ai_fallback_paused") == 0 and events(seeded).count("ai_failover") == 1
    # the 15 rejected jobs: one attempt each (the regroup gave the claim's attempt back), the 2-minute backoff, nothing dead
    for j in ids[:15]:
        job = queue.get_job(seeded, j)
        assert (job.status, job.attempts, job.run_after) == ("queued", 1, "2026-10-14T00:02:00Z"), job
        assert job.last_error.startswith("error: schema:")
    # the 5 never attempted: deferred to the earlier of the two pauses — both end 00:30 here (the discriminating instants are
    # in test_never_attempted_jobs_wait_for_the_earlier_of_the_two_pauses below), no attempt consumed
    for j in ids[15:]:
        job = queue.get_job(seeded, j)
        assert (job.status, job.attempts, job.run_after) == ("queued", 0, CLAUDE_PAUSE_END), job
    assert seeded.execute("SELECT COUNT(*) FROM word_contents").fetchone()[0] == 0
    assert seeded.execute("SELECT COUNT(*) FROM words WHERE content_state = 'failed'").fetchone()[0] == 0


@pytest.mark.parametrize(("claude_until", "expected"), [("2026-10-14T00:45:00Z", "2026-10-14T00:30:00Z"), ("2026-10-14T00:20:00Z", "2026-10-14T00:20:00Z")])
def test_never_attempted_jobs_wait_for_the_earlier_of_the_two_pauses(seeded, connect, frozen_clock, fb_cfg, fake_http, claude_until, expected):
    """§10.5 "the earlier of the two pauses" with DISTINCT instants: the quality pause of the third strike (00:30) against a
    claude pause ending later (00:45 → the fallback's 00:30 wins) or earlier (00:20 → claude's wins); no CLI row either way."""
    fake_http["mode"] = "schema_mismatch"
    db.kv_set(seeded, "ai.active_provider", "fallback")
    budget.set_paused_until(seeded, claude_until, now=NOW)
    ids = enqueue_content(seeded, seed_words(seeded, 20))
    worker.drain(make_ctx(connect, fb_cfg("ok"), frozen_clock), CLAUDE_TYPES)
    assert [(r["kind"], r["status"], r["provider"], r["word_count"]) for r in calls(seeded)] == [("content", "error", "fallback", 5)] * 3
    assert len(fake_http["calls"]) == 6 and db.kv_get(seeded, "ai.fallback.paused_until") == CLAUDE_PAUSE_END
    for j in ids[:15]:
        job = queue.get_job(seeded, j)
        assert (job.status, job.attempts, job.run_after) == ("queued", 1, "2026-10-14T00:02:00Z"), job
    for j in ids[15:]:
        job = queue.get_job(seeded, j)
        assert (job.status, job.attempts, job.run_after) == ("queued", 0, expected), job


# ------------------------------------------------------------------------------- the handlers' quality hooks (§10.4)
def test_applied_fallback_groups_end_a_counting_quality_streak(seeded, connect, frozen_clock, fb_cfg, fake_http):
    """§10.4: only the handlers' ``record_applied`` hooks end the streak (an HTTP-ok call never does): two unusable content
    groups → 2; an applied CONTENT group → 0; the two come back and fail again → 2 (not 4: no pause); an applied LOOKUP group
    → 0 (drained alone, so the content job it enqueues cannot be the resetter)."""
    db.kv_set(seeded, "ai.active_provider", "fallback")
    budget.set_paused_until(seeded, "2026-10-14T02:00:00Z", now=NOW)  # the CLI is down for every drain below
    word_ids = seed_words(seeded, 15)
    bad = enqueue_content(seeded, word_ids[:10])
    fake_http["mode"] = "schema_mismatch"
    ctx = make_ctx(connect, fb_cfg("ok"), frozen_clock)
    worker.drain(ctx, CLAUDE_TYPES)
    assert [(r["kind"], r["status"], r["provider"], r["word_count"]) for r in calls(seeded)] == [("content", "error", "fallback", 5)] * 2
    assert db.kv_get(seeded, "ai.fallback.streak.invalid") == "2"
    fake_http["mode"] = "ok"
    good = enqueue_content(seeded, word_ids[10:])
    worker.drain(ctx, CLAUDE_TYPES)
    assert all(queue.get_job(seeded, j).status == "done" for j in good) and db.kv_get(seeded, "ai.fallback.streak.invalid") == "0"
    fake_http["mode"] = "schema_mismatch"
    frozen_clock.advance(minutes=2)  # the backed-off groups return and fail again: 2 strikes, not 4
    worker.drain(ctx, CLAUDE_TYPES)
    assert db.kv_get(seeded, "ai.fallback.streak.invalid") == "2" and db.kv_get(seeded, "ai.fallback.paused_until") is None and events(seeded).count("ai_fallback_quality") == 0
    for j in bad:
        job = queue.get_job(seeded, j)
        assert (job.status, job.attempts, job.payload.get("group_size")) == ("queued", 2, 3), job  # bisected on the second failure
    fake_http["mode"] = "ok"
    uid = make_user(seeded)
    add_custom_words(seeded, uid, ["zorblax"], now=ctx.now())
    worker.drain(ctx, ("lookup_word",))
    assert [(r["kind"], r["status"], r["provider"]) for r in calls(seeded)][-1] == ("lookup", "success", "fallback")
    assert seeded.execute("SELECT COUNT(*) FROM jobs WHERE type = 'generate_content' AND status = 'queued' AND run_after <= ?", (ctx.now(),)).fetchone()[0] == 1  # its content job did not run
    assert db.kv_get(seeded, "ai.fallback.streak.invalid") == "0"


def test_a_lookup_group_rejected_whole_on_the_fallback_counts_a_quality_strike(seeded, connect, frozen_clock, fb_cfg, fake_http, monkeypatch):
    """§10.4 / §6.3 for lookups: an HTTP-ok fallback answer with no usable item for any string (what a model that echoes ``input``
    wrongly produces) is re-classified ``invalid_output`` with ``provider=fallback`` — the strike comes from the handler's own
    reclassification, the call's ``record_success`` leaves the streak alone; the group follows §6.3 (backoff → bisect → dead with
    the 暂时无法校验 flag) and its third attempt is the third strike: the fallback is paused for quality while the other single job
    waits for the earlier pause (claude's) with its attempt given back."""
    db.kv_set(seeded, "ai.active_provider", "fallback")
    budget.set_paused_until(seeded, CLAUDE_PAUSE_END, now=NOW)
    uid = make_user(seeded)
    add_custom_words(seeded, uid, ["zorblax", "quintessentially"])
    monkeypatch.setattr(common, "item_index", lambda items, key: {})
    ctx = make_ctx(connect, fb_cfg("ok"), frozen_clock)
    worker.drain(ctx, CLAUDE_TYPES)
    assert [(r["kind"], r["status"], r["provider"]) for r in calls(seeded)] == [("lookup", "invalid_output", "fallback")]
    assert len(fake_http["calls"]) == 1 and db.kv_get(seeded, "ai.fallback.streak.invalid") == "1"
    jobs = [queue.get_job(seeded, int(r[0])) for r in seeded.execute("SELECT id FROM jobs WHERE type = 'lookup_word' ORDER BY id")]
    assert [(j.status, j.attempts, j.run_after, j.last_error) for j in jobs] == [("queued", 1, "2026-10-14T00:02:00Z", "invalid_output: no item for this string in the response")] * 2
    frozen_clock.advance(minutes=2)
    worker.drain(ctx, CLAUDE_TYPES)  # strike 2: the second group failure bisects to 1 (the attempt counts)
    assert db.kv_get(seeded, "ai.fallback.streak.invalid") == "2" and db.kv_get(seeded, "ai.fallback.paused_until") is None
    assert [(queue.get_job(seeded, j.id).status, queue.get_job(seeded, j.id).attempts, queue.get_job(seeded, j.id).payload["group_size"], queue.get_job(seeded, j.id).run_after) for j in jobs] == [("queued", 2, 1, "2026-10-14T00:12:00Z")] * 2
    frozen_clock.advance(minutes=10)
    worker.drain(ctx, CLAUDE_TYPES)  # strike 3 on the first single job: the quality pause; the second finds both providers paused
    assert [(r["kind"], r["status"], r["provider"]) for r in calls(seeded)] == [("lookup", "invalid_output", "fallback")] * 3
    assert db.kv_get(seeded, "ai.fallback.paused_until") == "2026-10-14T00:42:00Z" and db.kv_get(seeded, "ai.fallback.streak.invalid") == "0"
    quality = event_details(seeded, "ai_fallback_quality")
    assert len(quality) == 1 and (quality[0]["consecutive"], quality[0]["kind"], quality[0]["status"], quality[0]["call_id"]) == (3, "lookup", "invalid_output", calls(seeded)[2]["id"])
    first, second = (queue.get_job(seeded, j.id) for j in jobs)
    assert (first.status, first.attempts) == ("dead", 3) and bank.my_row(seeded, uid, first.payload["word_id"])["attention_msg"] == "暂时无法校验，请稍后重试或检查拼写"
    assert (second.status, second.attempts, second.run_after) == ("queued", 2, CLAUDE_PAUSE_END)
    assert db.kv_get(seeded, "ai.active_provider") == "fallback"  # a quality pause never flips the sticky state


def test_a_content_group_rejected_whole_by_the_handler_is_a_quality_strike_too(seeded, connect, frozen_clock, fb_cfg, fake_http, monkeypatch):
    """§10.4: the content handler's own re-classification (an ON-schema answer whose every ``word`` is unmatched) feeds the
    streak with ``provider=fallback`` — the outage test above only reaches the adapter's ``schema:`` path. Two adapter strikes,
    then the handler-rejected group is the third: the fallback is paused; ``record_applied`` never ran for it (nothing stored)."""
    db.kv_set(seeded, "ai.active_provider", "fallback")
    budget.set_paused_until(seeded, "2026-10-14T02:00:00Z", now=NOW)
    word_ids = seed_words(seeded, 15)
    enqueue_content(seeded, word_ids[:10])
    fake_http["mode"] = "schema_mismatch"
    ctx = make_ctx(connect, fb_cfg("ok"), frozen_clock)
    worker.drain(ctx, CLAUDE_TYPES)
    assert db.kv_get(seeded, "ai.fallback.streak.invalid") == "2" and len(calls(seeded)) == 2
    rewriting_http(monkeypatch, fake_http, lambda it: {**it, "word": "x" + str(it["word"])})
    ids = enqueue_content(seeded, word_ids[10:])
    worker.drain(ctx, CLAUDE_TYPES)
    rows = calls(seeded)
    assert [(r["kind"], r["status"], r["provider"], r["word_count"]) for r in rows[2:]] == [("content", "invalid_output", "fallback", 5)]
    assert db.kv_get(seeded, "ai.fallback.paused_until") == CLAUDE_PAUSE_END and db.kv_get(seeded, "ai.fallback.streak.invalid") == "0"
    quality = event_details(seeded, "ai_fallback_quality")
    assert len(quality) == 1 and (quality[0]["consecutive"], quality[0]["kind"], quality[0]["status"], quality[0]["call_id"]) == (3, "content", "invalid_output", rows[2]["id"])
    for j in ids:
        job = queue.get_job(seeded, j)
        assert (job.status, job.attempts, job.run_after) == ("queued", 1, "2026-10-14T00:02:00Z") and job.last_error == "invalid_output: no item for this word in the response", job
    assert seeded.execute("SELECT COUNT(*) FROM word_contents").fetchone()[0] == 0
    assert seeded.execute("SELECT COUNT(*) FROM words WHERE content_state = 'failed'").fetchone()[0] == 0


def test_a_fallback_valid_false_on_a_validated_user_word_is_a_strike_not_a_rejection(seeded, connect, frozen_clock, fb_cfg, fake_http):
    """§10.4 / §6.4: only the CLI may invalidate a word. During the outage the fallback validated the learner's word (its
    lookup); when its content answer then says ``valid=false`` the word stays valid and public, no holder is flagged, the
    group is re-classified ``invalid_output`` (a quality strike — the third here) and the job follows §6.3, so the restored
    CLI gets the final say."""
    uid = make_user(seeded)
    add_custom_words(seeded, uid, ["zzzquill"])  # the fake's item builders say valid=false for a word containing "zzz" in mode invalid_word only
    ctx = make_ctx(connect, fb_cfg("managed_settings"), frozen_clock)
    worker.drain(ctx, ("lookup_word",))
    w = dict(seeded.execute("SELECT id, is_valid_english, is_public FROM words WHERE lemma = 'zzzquill'").fetchone())
    assert (w["is_valid_english"], w["is_public"]) == (1, 1) and db.kv_get(seeded, "ai.active_provider") == "fallback"
    db.kv_set(seeded, "ai.fallback.streak.invalid", "2")
    fake_http["mode"] = "invalid_word"
    worker.drain(ctx, ("generate_content",))
    after = dict(seeded.execute("SELECT is_valid_english, is_public, content_state FROM words WHERE id = ?", (w["id"],)).fetchone())
    assert (after["is_valid_english"], after["is_public"], after["content_state"]) == (1, 1, "queued")
    assert [(r["kind"], r["status"], r["provider"]) for r in calls(seeded)][2:] == [("content", "invalid_output", "fallback")]
    job = queue.live_job(seeded, f"content:{w['id']}")
    assert job is not None and (job.status, job.attempts, job.run_after) == ("queued", 1, "2026-10-14T00:02:00Z") and job.last_error.startswith("invalid_output: valid=false from the fallback")
    assert bank.my_row(seeded, uid, w["id"])["needs_attention"] == 0
    assert db.kv_get(seeded, "ai.fallback.streak.invalid") == "0" and db.kv_get(seeded, "ai.fallback.paused_until") == CLAUDE_PAUSE_END
    quality = event_details(seeded, "ai_fallback_quality")
    assert len(quality) == 1 and quality[0]["consecutive"] == 3 and quality[0]["status"] == "invalid_output"


def test_a_truncated_fallback_answer_bisects_without_an_attempt_and_each_call_counts_a_strike(seeded, connect, frozen_clock, fb_cfg, fake_http):
    """§6.3 / §10.4: a ``truncated:`` answer is a size signal — the group halves at once with no attempt spent (5 → 3 → 2 inside
    one drain) while every call is a quality strike, so a persistently truncating model pauses the fallback at the third call
    BEFORE any job can die; the jobs wait at the pause with attempts 0 and finish once the model behaves."""
    fake_http["mode"] = "truncated"
    db.kv_set(seeded, "ai.active_provider", "fallback")
    budget.set_paused_until(seeded, "2026-10-14T02:00:00Z", now=NOW)
    ids = enqueue_content(seeded, seed_words(seeded, 5))
    ctx = make_ctx(connect, fb_cfg("ok"), frozen_clock)
    worker.drain(ctx, CLAUDE_TYPES)
    assert [(r["status"], r["provider"], r["word_count"]) for r in calls(seeded)] == [("error", "fallback", 5), ("error", "fallback", 3), ("error", "fallback", 2)]
    assert all(r["error"].startswith("truncated:") for r in calls(seeded)) and len(fake_http["calls"]) == 3  # no repair round for a truncation
    assert db.kv_get(seeded, "ai.fallback.paused_until") == CLAUDE_PAUSE_END and db.kv_get(seeded, "ai.fallback.streak.invalid") == "0"
    quality = event_details(seeded, "ai_fallback_quality")
    assert len(quality) == 1 and quality[0]["consecutive"] == 3 and quality[0]["error"].startswith("truncated:")
    for j in ids:
        job = queue.get_job(seeded, j)
        assert (job.status, job.attempts, job.run_after) == ("queued", 0, CLAUDE_PAUSE_END) and job.payload["group_size"] <= 3, job  # parked at the earlier pause (the fallback's), nothing spent
    assert seeded.execute("SELECT COUNT(*) FROM jobs WHERE status = 'dead'").fetchone()[0] == 0
    assert seeded.execute("SELECT COUNT(*) FROM words WHERE content_state = 'failed'").fetchone()[0] == 0
    fake_http["mode"] = "ok"
    frozen_clock.advance(minutes=31)
    worker.drain(ctx, CLAUDE_TYPES)
    assert all(queue.get_job(seeded, j).status == "done" and queue.get_job(seeded, j).attempts == 1 for j in ids)
    assert seeded.execute("SELECT COUNT(*) FROM words WHERE content_state = 'ready'").fetchone()[0] == 5


@pytest.mark.parametrize(
    ("claude_mode", "overrides", "sticky", "parked_until", "first_rows"),
    [
        ("managed_settings", {}, False, CLAUDE_PAUSE_END, [("content", "auth", "claude", 10)]),  # the CLI dies on the mixed claim: parked at the claude pause
        ("ok", {}, True, "2026-10-14T00:02:00Z", []),  # sticky fallback, the CLI not paused (a soft switch): two minutes ahead, when claude could take them
        ("auth", {"ai_provider": "openai_http"}, False, "2026-10-14T00:30:00Z", []),  # openai_http: nothing is scheduled for prewarm — 30 minutes
    ],
)
def test_a_split_parks_the_whole_runnable_prewarm_backlog_so_an_ordinary_job_is_split_once(seeded, connect, frozen_clock, fb_cfg, fake_http, caplog, claude_mode, overrides, sticky, parked_until, first_rows):
    """§10.5: a prewarm plan left a runnable p90 backlog; one learner's p20 content job is claimed with some of it. The split
    parks the claimed p90 members AND every other runnable p90 job of the type at the same instant, so the ordinary job is
    split once and runs alone at the next claim — not once per four p90 jobs of the backlog."""
    caplog.set_level(logging.INFO, logger="t")
    if sticky:
        db.kv_set(seeded, "ai.active_provider", "fallback")
    word_ids = seed_words(seeded, 13)
    ordinary = enqueue_content(seeded, word_ids[:1], priority=20)[0]
    prewarm = enqueue_content(seeded, word_ids[1:], priority=90)
    ctx = make_ctx(connect, fb_cfg(claude_mode, **overrides), frozen_clock)
    worker.drain(ctx, CLAUDE_TYPES)
    assert [(r["kind"], r["status"], r["provider"], r["word_count"]) for r in calls(seeded)] == [*first_rows, ("content", "success", "fallback", 1)]
    assert len(fake_http["calls"]) == 1 and {w["word"].lower() for w in items_of(fake_http["calls"][0])} == displays(seeded, word_ids[:1])
    done = queue.get_job(seeded, ordinary)
    assert (done.status, done.attempts) == ("done", 1)  # the split gave the claim's attempt back: one real attempt
    for j in prewarm:
        job = queue.get_job(seeded, j)
        assert (job.status, job.run_after, job.attempts) == ("queued", parked_until, 0) and "group_size" not in job.payload, job
    splits = [r for r in caplog.records if getattr(r, "event", None) == "ai_failover_split"]
    assert len(splits) == 1 and "runnable prewarm job(s) of the backlog parked with them" in splits[0].getMessage()


def test_with_the_prewarm_flag_a_mixed_group_is_not_split(seeded, connect, frozen_clock, fb_cfg, fake_http, caplog):
    """§10.1: with ``WD_AI_FALLBACK_PREWARM=1`` the fallback takes prewarm too — the mixed group runs there as one (capped) group."""
    caplog.set_level(logging.INFO, logger="t")
    db.kv_set(seeded, "ai.active_provider", "fallback")
    budget.set_paused_until(seeded, CLAUDE_PAUSE_END, now=NOW)
    word_ids = seed_words(seeded, 4)
    ids = enqueue_content(seeded, word_ids[:1], priority=20) + enqueue_content(seeded, word_ids[1:], priority=90)
    worker.drain(make_ctx(connect, fb_cfg("ok", ai_fallback_prewarm=True), frozen_clock), CLAUDE_TYPES)
    assert [(r["kind"], r["status"], r["provider"], r["word_count"]) for r in calls(seeded)] == [("content", "success", "fallback", 4)]
    assert all(queue.get_job(seeded, j).status == "done" for j in ids)
    assert not [r for r in caplog.records if getattr(r, "event", None) == "ai_failover_split"]


# ---------------------------------------------------------------------------------------- consolidate
def test_consolidation_fails_over_and_applies_the_fallback_answer(seeded, connect, frozen_clock, fb_cfg, fake_http):
    uid = make_user(seeded)
    # two bank rows (validated seed words) so the nightly selection has something to examine
    for wid in seed_words(seeded, 2):
        bank.apply_action(seeded, uid, wid, "unfamiliar", origin="browse", context="browse", now=NOW, tz="Asia/Shanghai")
    seeded.execute("UPDATE jobs SET status = 'done', finished_at = ? WHERE type = 'generate_content'", (NOW,))  # not under test here
    from wd.ai import consolidate

    job_id = consolidate.enqueue_for_user(seeded, uid, trigger="manual", now=NOW)
    ctx = make_ctx(connect, fb_cfg("managed_settings"), frozen_clock)
    worker.drain(ctx, CLAUDE_TYPES)
    assert [(r["kind"], r["status"], r["provider"]) for r in calls(seeded)] == [("consolidate", "auth", "claude"), ("consolidate", "success", "fallback")]
    job = queue.get_job(seeded, job_id)
    assert job.status == "done" and job.result and job.result.get("examined") == 2
    run = seeded.execute("SELECT status, ai_call_id FROM consolidation_runs ORDER BY id DESC LIMIT 1").fetchone()
    assert run["status"] == "done" and int(run["ai_call_id"]) == calls(seeded)[1]["id"]


# ------------------------------------------------------------------------------------------- fail-back
def test_failback_probe_restores_the_cli_and_new_groups_use_it(seeded, connect, frozen_clock, fb_cfg, fake_http):
    uid = make_user(seeded)
    add_custom_words(seeded, uid, ["zorblax"])
    ctx = make_ctx(connect, fb_cfg("managed_settings"), frozen_clock)
    worker.drain(ctx, CLAUDE_TYPES)
    assert db.kv_get(seeded, "ai.active_provider") == "fallback"
    # too early: nothing happens (the CLI is still the broken fake)
    assert failover.maybe_probe(seeded, ctx.cfg, now=ctx.now(), probe_claude=lambda: probe.check(seeded, ctx.cfg, now=ctx.now())) is None
    # 30 minutes later the probe runs against the healthy CLI and fails back
    frozen_clock.advance(minutes=30, seconds=1)
    good = make_ctx(connect, fb_cfg("ok"), frozen_clock)
    outcome = failover.maybe_probe(seeded, good.cfg, now=good.now(), probe_claude=lambda: probe.check(seeded, good.cfg, now=good.now()))
    assert outcome == "failback"
    assert db.kv_get(seeded, "ai.active_provider") == "claude" and budget.provider_paused_until(seeded, "claude", good.now()) is None
    assert events(seeded).count("ai_failback") == 1 and event_details(seeded, "ai_failback")[0]["requeued_dead"] == 0
    add_custom_words(seeded, uid, ["frobnicate"], now=good.now())
    worker.drain(good, CLAUDE_TYPES)
    assert calls(seeded)[-1]["provider"] == "claude" and calls(seeded)[-1]["status"] == "success"


def test_failback_requeues_the_content_jobs_that_died_during_the_outage(seeded, connect, frozen_clock, fb_cfg, fake_http):
    """§10.6 / AI_FALLBACK_MODEL §4.5 死词: the content jobs that went dead since ``ai.failover.since`` come back queued on
    the fail-back (attempts 0, no ``group_size``: they batch like fresh claims), their ``failed`` words go back to ``queued``
    and the restored CLI regenerates them in one call; what died before the outage waits for the nightly requeue (this test
    pins the ``since`` boundary with SQL-made dead rows — the realistic §6.3 → dead → fail-back chain is the next test)."""
    uid = make_user(seeded)
    add_custom_words(seeded, uid, ["zorblax"])
    ctx = make_ctx(connect, fb_cfg("managed_settings"), frozen_clock)
    worker.drain(ctx, CLAUDE_TYPES)
    assert db.kv_get(seeded, "ai.active_provider") == "fallback" and db.kv_get(seeded, "ai.failover.since") == NOW
    old, a, b = enqueue_content(seeded, seed_words(seeded, 3))
    for job_id, finished_at in ((old, "2026-10-13T20:00:00Z"), (a, NOW), (b, "2026-10-14T00:10:00Z")):
        seeded.execute(
            "UPDATE jobs SET status = 'dead', attempts = 3, finished_at = ?, last_error = 'error: schema: x', payload_json = json_set(payload_json, '$.group_size', 2) WHERE id = ?",
            (finished_at, job_id),
        )
    word_a, word_b = (queue.get_job(seeded, j).payload["word_id"] for j in (a, b))
    seeded.execute("UPDATE words SET content_state = 'failed' WHERE id IN (?, ?)", (word_a, word_b))  # what on_dead / mark_failed leaves behind
    frozen_clock.advance(minutes=31)
    good = make_ctx(connect, fb_cfg("ok"), frozen_clock)
    assert failover.maybe_probe(seeded, good.cfg, now=good.now(), probe_claude=lambda: probe.check(seeded, good.cfg, now=good.now())) == "failback"
    for job_id in (a, b):
        job = queue.get_job(seeded, job_id)
        assert (job.status, job.attempts, job.run_after, job.finished_at) == ("queued", 0, good.now(), None) and "group_size" not in job.payload, job
    assert {str(r[0]) for r in seeded.execute("SELECT content_state FROM words WHERE id IN (?, ?)", (word_a, word_b))} == {"queued"}  # a word is queued ⇔ it has a live content job
    assert queue.get_job(seeded, old).status == "dead"
    fb = event_details(seeded, "ai_failback")
    assert len(fb) == 1 and fb[0]["requeued_dead"] == 2 and fb[0]["since"] == NOW
    assert all(db.kv_get(seeded, key) is None for key in failover.FAILOVER_KEYS)  # the episode is over (the detail kept since)
    # the requeued jobs run on the restored CLI as ONE group (no group_size mark), not one word per call
    worker.drain(good, CLAUDE_TYPES)
    assert all(queue.get_job(seeded, j).status == "done" for j in (a, b)) and queue.get_job(seeded, old).status == "dead"
    assert [(r["kind"], r["status"], r["provider"], r["word_count"]) for r in calls(seeded)[-1:]] == [("content", "success", "claude", 2)]
    assert seeded.execute("SELECT COUNT(*) FROM words WHERE content_state = 'ready'").fetchone()[0] == 3  # zorblax (fallback) + the two requeued


def test_words_that_died_on_the_fallback_are_requeued_on_failback_and_regenerated_on_the_cli(seeded, connect, frozen_clock, fb_cfg, fake_http):
    """§4.5 死词 end to end through the real §6.3 ladder: a content group the fallback's filter rejects on every attempt
    (``content_filter:`` — a quality miss that keeps the ordinary error path) backs off, bisects and dies on the third attempt,
    which is also the third strike (the quality pause), leaving its words ``failed``; the fail-back requeues exactly those
    jobs, their words go back to ``queued``, and the restored CLI regenerates them (``select_jobs`` takes a ``failed`` word
    with a live job, ``store_content`` flips it to ``ready``)."""
    uid = make_user(seeded)
    add_custom_words(seeded, uid, ["zorblax"])
    broken = make_ctx(connect, fb_cfg("managed_settings"), frozen_clock)
    worker.drain(broken, CLAUDE_TYPES)
    assert db.kv_get(seeded, "ai.active_provider") == "fallback" and db.kv_get(seeded, "ai.failover.since") == NOW
    base_rows, base_http = len(calls(seeded)), len(fake_http["calls"])
    fake_http["mode"] = "content_filter"
    word_ids = seed_words(seeded, 5)
    ids = enqueue_content(seeded, word_ids)

    def states(word_set):
        return {int(r[0]): str(r[1]) for r in seeded.execute(f"SELECT id, content_state FROM words WHERE id IN ({','.join('?' * len(word_set))})", list(word_set))}

    def jobs():
        return [queue.get_job(seeded, j) for j in ids]

    worker.drain(broken, CLAUDE_TYPES)  # attempt 1 @ 00:00: strike 1, the 2-minute backoff
    assert db.kv_get(seeded, "ai.fallback.streak.invalid") == "1"
    assert [(j.status, j.attempts, j.run_after, j.payload.get("group_size")) for j in jobs()] == [("queued", 1, "2026-10-14T00:02:00Z", None)] * 5
    frozen_clock.advance(minutes=2)
    worker.drain(broken, CLAUDE_TYPES)  # attempt 2 @ 00:02: strike 2, bisected to 3 (the attempt counts), the 10-minute backoff
    assert db.kv_get(seeded, "ai.fallback.streak.invalid") == "2"
    assert [(j.status, j.attempts, j.run_after, j.payload.get("group_size")) for j in jobs()] == [("queued", 2, "2026-10-14T00:12:00Z", 3)] * 5
    frozen_clock.advance(minutes=10)
    worker.drain(broken, CLAUDE_TYPES)  # attempt 3 @ 00:12: the half of 3 strikes a third time → quality pause; attempts exhausted → dead → words failed
    dead = [j for j in jobs() if j.status == "dead"]
    parked = [j for j in jobs() if j.status == "queued"]
    assert len(dead) == 3 and len(parked) == 2
    assert all((j.attempts, j.finished_at, j.payload["group_size"]) == (3, "2026-10-14T00:12:00Z", 2) and j.last_error.startswith("error: content_filter:") for j in dead)
    dead_words = [int(j.payload["word_id"]) for j in dead]
    assert set(states(dead_words).values()) == {"failed"}
    assert [(j.attempts, j.run_after, j.payload.get("group_size")) for j in parked] == [(2, CLAUDE_PAUSE_END, 3)] * 2  # the other two wait for the earlier pause (claude's), attempt given back
    assert db.kv_get(seeded, "ai.fallback.paused_until") == "2026-10-14T00:42:00Z" and db.kv_get(seeded, "ai.fallback.streak.invalid") == "0"
    quality = event_details(seeded, "ai_fallback_quality")
    assert len(quality) == 1 and quality[0]["consecutive"] == 3 and quality[0]["error"].startswith("content_filter:")
    assert [(r["status"], r["provider"], r["word_count"]) for r in calls(seeded)[base_rows:]] == [("error", "fallback", 5), ("error", "fallback", 5), ("error", "fallback", 3)]
    assert len(fake_http["calls"]) == base_http + 3
    # 00:31: the probe fails back and requeues exactly the three casualties; their words are queued again (a live job each)
    frozen_clock.advance(minutes=19)
    good = make_ctx(connect, fb_cfg("ok"), frozen_clock)
    assert good.now() == "2026-10-14T00:31:00Z"
    assert failover.maybe_probe(seeded, good.cfg, now=good.now(), probe_claude=lambda: probe.check(seeded, good.cfg, now=good.now())) == "failback"
    fb = event_details(seeded, "ai_failback")
    assert len(fb) == 1 and fb[0]["requeued_dead"] == 3 and fb[0]["since"] == NOW and fb[0]["outage_min"] == 31
    for j in dead:
        job = queue.get_job(seeded, j.id)
        assert (job.status, job.attempts, job.run_after, job.finished_at) == ("queued", 0, good.now(), None) and "group_size" not in job.payload, job
    assert set(states(dead_words).values()) == {"queued"} and all(queue.live_job(seeded, f"content:{w}") is not None for w in dead_words)
    assert set(states([int(j.payload["word_id"]) for j in parked]).values()) == {"none"}
    assert db.kv_get(seeded, "ai.active_provider") == "claude" and db.kv_get(seeded, "ai.fallback.paused_until") == "2026-10-14T00:42:00Z"  # the quality pause stays; irrelevant while claude is active
    # the drain on the restored CLI: the two parked (group_size 3, runnable since 00:30) head the claim and take one revived job with them, the other two follow
    worker.drain(good, CLAUDE_TYPES)
    cli = [(r["status"], r["provider"], r["word_count"]) for r in calls(seeded) if r["kind"] == "content" and r["provider"] == "claude"]
    assert cli == [("success", "claude", 3), ("success", "claude", 2)]
    assert all(queue.get_job(seeded, j).status == "done" for j in ids) and set(states(word_ids).values()) == {"ready"}
    models = {str(r[0]) for r in seeded.execute(f"SELECT model FROM word_contents WHERE status = 'active' AND word_id IN ({','.join('?' * 3)})", dead_words)}
    assert len(models) == 1 and "glm-4.7-flash" not in models  # regenerated by the CLI
    assert seeded.execute(f"SELECT COUNT(*) FROM word_contents WHERE word_id IN ({','.join('?' * 3)})", dead_words).fetchone()[0] == 3  # exactly one version each
    assert len(fake_http["calls"]) == base_http + 3  # nothing went back to the fallback


def test_a_revived_dead_regenerate_superseded_by_a_newer_card_is_skipped_on_the_cli(seeded, connect, frozen_clock, fb_cfg, fake_http):
    """§6.4 / §10.6: a forced regenerate (``content:<id>:r1``) that died during the outage comes back with the fail-back; a
    later regenerate (``r2``) already stored a newer card, so the revived job is finished ``superseded_regenerate`` — the
    learner keeps the newer card, no CLI call is spent, and the revival never flipped a word with a live version to ``queued``."""
    uid = make_user(seeded)
    add_custom_words(seeded, uid, ["zorblax"])
    ctx = make_ctx(connect, fb_cfg("managed_settings"), frozen_clock)
    worker.drain(ctx, CLAUDE_TYPES)
    assert db.kv_get(seeded, "ai.active_provider") == "fallback" and db.kv_get(seeded, "ai.failover.since") == NOW
    (wid,) = seed_words(seeded, 1)
    enqueue_content(seeded, [wid])
    worker.drain(ctx, CLAUDE_TYPES)  # v1 on the fallback

    def active():
        row = seeded.execute("SELECT wc.id, wc.version, w.content_state FROM words w JOIN word_contents wc ON wc.id = w.active_content_id WHERE w.id = ?", (wid,)).fetchone()
        return (int(row[0]), int(row[1]), str(row[2]))

    def regenerate(n: int, now: str) -> int:  # what POST /api/admin/words/{id}/regenerate enqueues
        return queue.enqueue(seeded, "generate_content", {"word_id": wid, "force": True}, dedupe_key=f"content:{wid}:r{n}", priority=10, now=now)

    assert active()[1:] == (1, "ready")
    frozen_clock.advance(minutes=5)
    r1 = regenerate(1, ctx.now())
    seeded.execute("UPDATE jobs SET status = 'dead', attempts = 3, finished_at = ?, last_error = 'error: schema: x' WHERE id = ?", (ctx.now(), r1))  # died on the fallback during the outage
    frozen_clock.advance(minutes=5)
    r2 = regenerate(2, ctx.now())
    worker.drain(ctx, CLAUDE_TYPES)
    assert queue.get_job(seeded, r2).status == "done"
    v2_id, version, state = active()
    assert (version, state) == (2, "ready")
    frozen_clock.advance(minutes=21)  # 00:31: the probe fails back and revives r1
    good = make_ctx(connect, fb_cfg("ok"), frozen_clock)
    assert failover.maybe_probe(seeded, good.cfg, now=good.now(), probe_claude=lambda: probe.check(seeded, good.cfg, now=good.now())) == "failback"
    assert event_details(seeded, "ai_failback")[0]["requeued_dead"] == 1
    revived = queue.get_job(seeded, r1)
    assert (revived.status, revived.attempts, revived.payload.get("force")) == ("queued", 0, True) and active() == (v2_id, 2, "ready")
    before = len(calls(seeded))
    worker.drain(good, CLAUDE_TYPES)
    assert (queue.get_job(seeded, r1).status, queue.get_job(seeded, r1).result) == ("done", {"skipped": "superseded_regenerate"})
    assert active() == (v2_id, 2, "ready") and len(calls(seeded)) == before  # the newer card stays, no CLI call spent


def test_worker_housekeeping_probes_immediately_after_a_restart(seeded, connect, frozen_clock, fb_cfg, fake_http):
    uid = make_user(seeded)
    add_custom_words(seeded, uid, ["zorblax"])
    broken = make_ctx(connect, fb_cfg("managed_settings"), frozen_clock)
    worker.drain(broken, CLAUDE_TYPES)
    assert db.kv_get(seeded, "ai.active_provider") == "fallback"
    # a fresh worker (restart) with a healthy CLI: the first housekeeping forces the probe although next_probe_at is 30 min away
    w = worker.ClaudeWorker(make_ctx(connect, fb_cfg("ok"), frozen_clock))
    w.maybe_sweep()
    assert db.kv_get(seeded, "ai.active_provider") == "claude"
    assert [r["kind"] for r in calls(seeded)][-1] == "probe"


# ------------------------------------------------------------------------------------- the other modes
def test_openai_http_mode_never_spawns_the_cli(seeded, connect, frozen_clock, fb_cfg, fake_http):
    uid = make_user(seeded)
    add_custom_words(seeded, uid, ["zorblax"])
    ctx = make_ctx(connect, fb_cfg("auth", ai_provider="openai_http"), frozen_clock)
    worker.drain(ctx, CLAUDE_TYPES)
    assert [(r["kind"], r["status"], r["provider"]) for r in calls(seeded)] == [("lookup", "success", "fallback"), ("content", "success", "fallback")]
    assert db.kv_get(seeded, "claude.paused_until") is None and db.kv_get(seeded, "ai.active_provider") in (None, "claude", "fallback")


def test_openai_http_mode_fallback_hard_failure_pauses_only_the_fallback(seeded, connect, frozen_clock, fb_cfg, fake_http):
    uid = make_user(seeded)
    add_custom_words(seeded, uid, ["zorblax"])
    fake_http["mode"] = "401"
    ctx = make_ctx(connect, fb_cfg("ok", ai_provider="openai_http"), frozen_clock)
    worker.drain(ctx, CLAUDE_TYPES)
    rows = calls(seeded)
    assert [(r["status"], r["provider"]) for r in rows] == [("auth", "fallback")]  # no CLI rerun in this mode
    assert db.kv_get(seeded, "ai.fallback.paused_until") == CLAUDE_PAUSE_END and db.kv_get(seeded, "claude.paused_until") is None
    job = seeded.execute("SELECT status, run_after FROM jobs WHERE type = 'lookup_word'").fetchone()
    assert job["status"] == "queued" and job["run_after"] == CLAUDE_PAUSE_END
    assert "ai_fallback_paused" in events(seeded) and "claude_auth" not in events(seeded)


def test_auto_mode_fallback_hard_failure_reruns_the_group_on_the_healthy_cli(seeded, connect, frozen_clock, fb_cfg, fake_http):
    uid = make_user(seeded)
    add_custom_words(seeded, uid, ["zorblax"])
    db.kv_set(seeded, "ai.active_provider", "fallback")  # sticky state left by an earlier CLI outage
    fake_http["mode"] = "401"
    ctx = make_ctx(connect, fb_cfg("ok"), frozen_clock)
    worker.drain(ctx, CLAUDE_TYPES)
    rows = calls(seeded)
    assert [(r["kind"], r["status"], r["provider"]) for r in rows][:2] == [("lookup", "auth", "fallback"), ("lookup", "success", "claude")]
    assert db.kv_get(seeded, "ai.fallback.paused_until") == CLAUDE_PAUSE_END
    assert db.kv_get(seeded, "ai.active_provider") == "claude"  # the successful CLI call fails back
    assert "ai_fallback_paused" in events(seeded) and "ai_failback" in events(seeded)
    assert all(j["status"] == "done" for j in seeded.execute("SELECT status FROM jobs WHERE type = 'lookup_word'").fetchall())
    assert len(fake_http["calls"]) == 1  # exactly one fallback request, then the CLI (the content job runs on the restored CLI too)


def test_claude_cli_mode_keeps_todays_behaviour(seeded, connect, frozen_clock, settings, tmp_path, fake_http):
    uid = make_user(seeded)
    add_custom_words(seeded, uid, ["zorblax"])
    ctx = make_ctx(connect, replace(settings, claude_bin=wrapper(tmp_path / "bin", "managed_settings")), frozen_clock)
    worker.drain(ctx, CLAUDE_TYPES)
    assert [(r["status"], r["provider"]) for r in calls(seeded)] == [("auth", "claude")]
    assert db.kv_get(seeded, "claude.paused_until") == CLAUDE_PAUSE_END and db.kv_get(seeded, "ai.active_provider") in (None, "claude")
    assert events(seeded) == ["claude_auth"] and fake_http["calls"] == []
    # the queued lookup's bank row is flagged only when the job dies / AI is off — a pause leaves it 待校验
    assert budget.can_spend(seeded, "lookup", 1, 10, ctx.now(), cfg=ctx.cfg) == (False, CLAUDE_PAUSE_END)


def test_manual_pause_holds_every_provider_and_resume_clears_all(seeded, connect, frozen_clock, fb_cfg, fake_http):
    uid = make_user(seeded)
    add_custom_words(seeded, uid, ["zorblax"])
    cfg = fb_cfg("ok")
    failover.set_manual_pause(seeded, "2026-10-15T00:00:00Z", now=NOW)
    ctx = make_ctx(connect, cfg, frozen_clock)
    worker.drain(ctx, CLAUDE_TYPES)
    assert calls(seeded) == [] and seeded.execute("SELECT run_after FROM jobs WHERE type = 'lookup_word'").fetchone()[0] == "2026-10-15T00:00:00Z"
    assert bank.ai_paused_until(seeded, NOW, cfg=cfg, kind="lookup") == "2026-10-15T00:00:00Z"
    db.kv_set(seeded, "ai.active_provider", "fallback")
    budget.set_paused_until(seeded, "2026-10-14T05:00:00Z", now=NOW, provider="fallback")
    failover.clear_pauses(seeded, now=NOW)
    assert db.kv_get(seeded, "ai.paused_until") is None and db.kv_get(seeded, "ai.fallback.paused_until") is None
    assert db.kv_get(seeded, "ai.active_provider") == "claude" and db.kv_get(seeded, "claude.enabled") == "1"


def test_fallback_probe_records_availability_and_model(seeded, fb_cfg, fake_http):
    res = probe.check_fallback(seeded, fb_cfg("ok"), now=NOW)
    assert res.ok and res.flag_tier == 0 and res.model_used and res.error is None
    assert db.kv_get(seeded, "ai.fallback.available") == "1" and db.kv_get(seeded, "ai.fallback.last_probe_at") == NOW and db.kv_get(seeded, "ai.fallback.model_seen") == res.model_used
    assert [(r["kind"], r["status"], r["provider"]) for r in calls(seeded)] == [("probe", "success", "fallback")]
    fake_http["mode"] = "schema_mismatch"  # a transient / quality miss: the event is written but the '0' mark is not
    res = probe.check_fallback(seeded, fb_cfg("ok"), now="2026-10-14T00:05:00Z")
    assert not res.ok and db.kv_get(seeded, "ai.fallback.available") == "1" and "fallback_unavailable" in events(seeded)
    fake_http["mode"] = "404_model"  # a configuration / endpoint failure marks the fallback unavailable until a probe or call succeeds
    res = probe.check_fallback(seeded, fb_cfg("ok"), now="2026-10-14T00:06:00Z")
    assert not res.ok and db.kv_get(seeded, "ai.fallback.available") == "0" and res.error.startswith("not_found:")
    assert probe.check_fallback(seeded, fb_cfg("ok", ai_provider="claude_cli", ai_fallback_kind="none", ai_fallback_model="", ai_fallback_api_key_file=""), now=NOW).error.startswith("fallback provider not configured")


# ------------------------------------------------------------------------------------ the request route
def test_content_request_route_accepts_while_the_fallback_serves_content(seeded, connect, frozen_clock, fb_cfg, fake_http):
    """API.md 30 / §10.5: 生成例句 goes through ``failover.availability(kind="content")`` + ``budget.can_spend(provider=…)``, so a
    paused CLI with the fallback serving content accepts the request (202, the job then runs on the fallback); with content
    removed from the kinds the same request is refused like any pause (503 ``ai_disabled``)."""
    uid = make_user(seeded)
    token = session_for(seeded, uid)
    db.kv_set(seeded, "ai.active_provider", "fallback")
    budget.set_paused_until(seeded, CLAUDE_PAUSE_END, now=NOW)
    wid, other = seed_words(seeded, 2)
    cfg = fb_cfg("ok")
    assert failover.availability(seeded, cfg, kind="content", now=NOW, priority=10).provider == "fallback"
    assert budget.can_spend(seeded, "content", 1, 10, NOW, cfg=cfg, provider="fallback") == (True, None)
    with TestClient(create_app(cfg, clock=frozen_clock, configure_logs=False), base_url="http://testserver") as api:
        api.headers["X-WD-Request"] = "1"
        api.cookies.set("wd_session", token)
        r = api.post(f"/api/words/{wid}/content/request")
        assert r.status_code == 202 and r.json()["state"] == "queued" and r.json()["job_id"], r.text
        assert api.get(f"/api/words/{wid}/content").json()["state"] == "queued"
        assert api.get(f"/api/words/{wid}").json()["content_deferred_until"] is None  # not a pause from the learner's point of view
    worker.drain(make_ctx(connect, cfg, frozen_clock), CLAUDE_TYPES)
    assert [(r["kind"], r["status"], r["provider"]) for r in calls(seeded)] == [("content", "success", "fallback")]
    assert words.word_row(seeded, wid)["content_state"] == "ready"
    cli_content = fb_cfg("ok", ai_fallback_kinds=("lookup", "consolidate"))
    with TestClient(create_app(cli_content, clock=frozen_clock, configure_logs=False), base_url="http://testserver") as api:
        api.headers["X-WD-Request"] = "1"
        api.cookies.set("wd_session", token)
        r = api.post(f"/api/words/{other}/content/request")
        assert r.status_code == 503 and r.json()["error"]["code"] == "ai_disabled", r.text
        assert api.get(f"/api/words/{other}").json()["content_state"] == "none"  # nothing was enqueued (deferred_until exists for queued words only)
    assert queue.live_job(seeded, f"content:{other}") is None
    assert bank.ai_paused_until(seeded, NOW, cfg=cli_content, kind="content") == CLAUDE_PAUSE_END  # the gate the route consulted
