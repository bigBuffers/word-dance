"""delivery/email.py and delivery/webhook.py (WP4): the digest e-mail through a RecordingMailer spy (button URL from
WD_PUBLIC_URL, from kv.public_url_guess, none when both are empty), the test e-mail job and its dedupe key, every
webhook format's body shape, the SSRF guard (private / IP-literal / http / localhost URLs rejected), retries and the
sent-once idempotency — the jobs are driven synchronously through queue.run_once."""

from __future__ import annotations

import dataclasses
import json
import logging
from datetime import datetime, timezone

import httpx
import pytest

from wd import db
from wd.delivery import email, webhook
from wd.delivery.mailer import RecordingMailer
from wd.jobs import queue, registry
from wd.jobs.registry import JobContext
from wd.services import bank, batches

UTC = timezone.utc
TZ = "Asia/Shanghai"
NOW = datetime(2026, 10, 14, 1, 0, tzinfo=UTC)
PUBLIC_IP = "93.184.216.34"


# -------------------------------------------------------------------------------------------- helpers
def make_user(conn, username="alice", *, email_ok=True, email_enabled=1, webhook_url=None, webhook_format="generic", tz=TZ) -> int:
    uid = int(
        conn.execute(
            "INSERT INTO users(username, password_hash, onboarding_state, email, email_verified_at) VALUES (?, 'x', 'done', ?, ?)",
            (username, f"{username}@example.com", "2026-10-01T00:00:00Z" if email_ok else None),
        ).lastrowid
    )
    conn.execute(
        "INSERT INTO user_settings(user_id, timezone, next_push_at, email_enabled, webhook_enabled, webhook_url, webhook_format, daily_screen_count) VALUES (?, ?, '2026-10-15T00:00:00Z', ?, ?, ?, ?, 1)",
        (uid, tz, email_enabled, 1 if webhook_url else 0, webhook_url, webhook_format),
    )
    return uid


def wid(conn, lemma: str) -> int:
    return int(conn.execute("SELECT id FROM words WHERE lemma = ?", (lemma,)).fetchone()[0])


def build(conn, uid, *lemmas) -> int:
    for lemma in lemmas:
        bank.apply_action(conn, uid, wid(conn, lemma), "unfamiliar", origin="browse", context="browse", now=NOW, tz=TZ)
    b = batches.build_batch(conn, uid, "2026-10-14", "manual", NOW)
    conn.execute("DELETE FROM jobs")  # only delivery jobs should run in these tests
    return b.id


def ctx_for(connect, cfg, clock) -> JobContext:
    return JobContext(db=connect, cfg=cfg, clock=clock, enqueue=queue.enqueue, log=logging.getLogger("test"), worker_id="io-1", boot_id="test")


def give_content(conn, lemma: str) -> None:
    w = wid(conn, lemma)
    content = {
        "word": lemma,
        "valid": True,
        "meaning_zh": "放弃；抛弃",
        "meaning_en": "to leave",
        "examples": [{"en": "They had to abandon the car.", "zh": "他们不得不弃车。"}, {"en": "Never abandon hope.", "zh": "永不放弃希望。"}, {"en": "x abandon y", "zh": "甲放弃乙"}],
        "collocations": ["abandon ship"],
        "mnemonic_zh": "a + band + on",
        "image_keywords": ["abandoned car"],
        "image_alt_zh": "被遗弃的汽车",
        "difficulty": 3,
        "version": 1,
        "prompt_version": "content-v1",
        "model": "fake",
        "created_at": "2026-10-13T00:00:00Z",
    }
    cid = conn.execute(
        "INSERT INTO word_contents(word_id, version, prompt_version, model, content_json) VALUES (?, 1, 'content-v1', 'fake', ?)", (w, json.dumps(content, ensure_ascii=False))
    ).lastrowid
    conn.execute("UPDATE words SET active_content_id = ?, content_state = 'ready' WHERE id = ?", (cid, w))


@pytest.fixture(autouse=True)
def _clock_at_now(frozen_clock):
    frozen_clock.set(NOW)  # jobs are enqueued with run_after = NOW; the queue only claims what is due at the clock's time


@pytest.fixture
def spy() -> RecordingMailer:
    m = RecordingMailer()
    email.set_mailer(m)
    yield m
    email.set_mailer(None)


class Captured:
    def __init__(self, status: int = 200):
        self.status = status
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status, json={"ok": True})

    def install(self, monkeypatch, *, ips=(PUBLIC_IP,)) -> "Captured":
        transport = httpx.MockTransport(self.handler)
        monkeypatch.setattr(webhook, "CLIENT_FACTORY", lambda: httpx.Client(transport=transport, follow_redirects=False))
        monkeypatch.setattr(webhook, "resolve_host", lambda host: list(ips))
        return self

    def bodies(self) -> list[dict]:
        return [json.loads(r.content) for r in self.requests]


# ---------------------------------------------------------------------------------------------- email
def test_digest_email_with_public_url(settings, seeded, connect, frozen_clock, spy):
    conn = seeded
    cfg = dataclasses.replace(settings, public_url="https://wd.example.com/")
    uid = make_user(conn)
    give_content(conn, "abandon")
    bid = build(conn, uid, "abandon", "apple")
    assert batches.enqueue_deliveries(conn, bid, NOW) == {"email": "queued"}
    assert queue.run_once(ctx_for(connect, cfg, frozen_clock)) == 1
    (sent,) = spy.sent
    assert sent.to == "alice@example.com"
    assert sent.subject == "【word-Dance】今日词汇 10月14日 · 复习 0 · 新词 2 · 推荐 1"
    assert "https://wd.example.com/today" in sent.text and "https://wd.example.com/today" in sent.html
    assert "开始学习" in sent.html and "<img" not in sent.html
    assert "abandon" in sent.text and "放弃；抛弃" in sent.text and "They had to abandon the car." in sent.text and "他们不得不弃车。" in sent.text
    assert "apple" in sent.text and "苹果" in sent.text  # dictionary meaning when no content exists
    assert email.NO_LINK_ZH not in sent.text
    row = conn.execute("SELECT email_status, delivery_error FROM push_batches WHERE id = ?", (bid,)).fetchone()
    assert row[:] == ("sent", None)
    job = conn.execute("SELECT status, result_json FROM jobs WHERE type = 'send_email'").fetchone()
    assert job[0] == "done" and json.loads(job[1])["sent"] is True


def test_digest_email_falls_back_to_public_url_guess_then_no_button(settings, seeded, connect, frozen_clock, spy):
    conn = seeded
    uid = make_user(conn)
    bid = build(conn, uid, "apple")
    db.kv_set(conn, "public_url_guess", "http://192.168.1.5:8000")
    batches.enqueue_deliveries(conn, bid, NOW)
    queue.run_once(ctx_for(connect, settings, frozen_clock))
    assert "http://192.168.1.5:8000/today" in spy.sent[0].text and 'href="http://192.168.1.5:8000/today"' in spy.sent[0].html
    # no URL at all → text says 请在浏览器中打开 word-Dance, no link anywhere
    db.kv_delete(conn, "public_url_guess")
    bob = make_user(conn, "bob")
    bid2 = build(conn, bob, "bank")
    batches.enqueue_deliveries(conn, bid2, NOW)
    queue.run_once(ctx_for(connect, settings, frozen_clock))
    second = spy.sent[1]
    assert email.NO_LINK_ZH in second.text and email.NO_LINK_ZH in second.html and "http" not in second.text and "href=" not in second.html
    assert email.public_url(conn, settings) is None and email.public_url(conn, dataclasses.replace(settings, public_url="https://x.example")) == "https://x.example"


def test_test_email_job_dedupes_and_renders_next_push_time(settings, seeded, connect, frozen_clock, spy):
    conn = seeded
    uid = make_user(conn)
    conn.execute("UPDATE user_settings SET next_push_at = '2026-10-15T00:00:00Z' WHERE user_id = ?", (uid,))
    a = queue.enqueue(conn, "send_email", {"user_id": uid, "test": True}, dedupe_key=f"email:test:{uid}", priority=10, now="2026-10-14T01:00:00Z")
    b = queue.enqueue(conn, "send_email", {"user_id": uid, "test": True}, dedupe_key=f"email:test:{uid}", priority=10, now="2026-10-14T01:00:05Z")
    assert a == b and conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
    db.kv_set(conn, "public_url_guess", "http://10.0.0.7:8000")
    assert queue.run_once(ctx_for(connect, settings, frozen_clock)) == 1
    (sent,) = spy.sent
    assert sent.subject == email.TEST_SUBJECT == "【word-Dance】测试邮件"
    assert "这是一封测试邮件。你的下次推送时间：10月15日 08:00（Asia/Shanghai）" in sent.text
    assert "http://10.0.0.7:8000/today" in sent.text
    assert conn.execute("SELECT COUNT(*) FROM push_batches").fetchone()[0] == 0  # untouched
    # the time is rendered in the user's own timezone
    ny = make_user(conn, "ny", tz="America/New_York")
    conn.execute("UPDATE user_settings SET next_push_at = '2026-11-01T13:00:00Z' WHERE user_id = ?", (ny,))
    queue.enqueue(conn, "send_email", {"user_id": ny, "test": True}, dedupe_key=f"email:test:{ny}", priority=10, now="2026-10-14T01:00:00Z")
    queue.run_once(ctx_for(connect, settings, frozen_clock))
    assert "11月1日 08:00（America/New_York）" in spy.sent[1].text
    # an unverified address is skipped, never sent
    carol = make_user(conn, "carol", email_ok=False)
    queue.enqueue(conn, "send_email", {"user_id": carol, "test": True}, dedupe_key=f"email:test:{carol}", priority=10, now="2026-10-14T01:00:00Z")
    queue.run_once(ctx_for(connect, settings, frozen_clock))
    assert len(spy.sent) == 2
    assert json.loads(conn.execute("SELECT result_json FROM jobs ORDER BY id DESC LIMIT 1").fetchone()[0]) == {"skipped": "no_verified_email"}


def test_digest_email_skips_disabled_channel_and_unconfigured_smtp(settings, seeded, connect, frozen_clock, spy):
    conn = seeded
    off = make_user(conn, "off", email_enabled=0)
    bid = build(conn, off, "apple")
    assert batches.enqueue_deliveries(conn, bid, NOW) == {}  # the scheduler never enqueues for a disabled channel …
    queue.enqueue(conn, "send_email", {"batch_id": bid}, dedupe_key=f"email:{bid}", now="2026-10-14T01:00:00Z")  # … but a stray job is skipped cleanly
    queue.run_once(ctx_for(connect, settings, frozen_clock))
    assert spy.sent == [] and conn.execute("SELECT email_status FROM push_batches WHERE id = ?", (bid,)).fetchone()[0] == "skipped"
    email.set_mailer(None)  # SMTP unconfigured in the test environment
    on = make_user(conn, "on")
    bid2 = build(conn, on, "bank")
    batches.enqueue_deliveries(conn, bid2, NOW)
    queue.run_once(ctx_for(connect, settings, frozen_clock))
    assert conn.execute("SELECT email_status FROM push_batches WHERE id = ?", (bid2,)).fetchone()[0] == "skipped"
    assert email.get_mailer(settings) is None


def test_mailer_failure_retries_then_dies_and_resend_is_idempotent(settings, seeded, connect, frozen_clock, spy):
    conn = seeded
    uid = make_user(conn)
    bid = build(conn, uid, "apple")
    batches.enqueue_deliveries(conn, bid, NOW)
    spy.fail_with = "connection refused"
    ctx = ctx_for(connect, settings, frozen_clock)
    assert queue.run_once(ctx) == 1
    job = db.row_to_dict(conn.execute("SELECT * FROM jobs WHERE type = 'send_email'").fetchone())
    assert job["status"] == "queued" and job["attempts"] == 1 and "connection refused" in job["last_error"] and job["run_after"] > "2026-10-14T00:00:00Z"
    assert conn.execute("SELECT email_status, delivery_error FROM push_batches WHERE id = ?", (bid,)).fetchone()[:] == ("queued", "connection refused")
    for _ in range(2):
        frozen_clock.advance(hours=2)
        queue.run_once(ctx)
    job = db.row_to_dict(conn.execute("SELECT * FROM jobs WHERE type = 'send_email'").fetchone())
    assert job["status"] == "dead" and job["attempts"] == 3
    assert conn.execute("SELECT email_status FROM push_batches WHERE id = ?", (bid,)).fetchone()[0] == "failed"
    # recovery: a fresh job sends once; a second job for the same batch does not send again
    spy.fail_with = None
    queue.enqueue(conn, "send_email", {"batch_id": bid}, dedupe_key=f"email:{bid}:r1", now=ctx.now())
    queue.run_once(ctx)
    assert len(spy.sent) == 1 and conn.execute("SELECT email_status FROM push_batches WHERE id = ?", (bid,)).fetchone()[0] == "sent"
    queue.enqueue(conn, "send_email", {"batch_id": bid}, dedupe_key=f"email:{bid}:r2", now=ctx.now())
    queue.run_once(ctx)
    assert len(spy.sent) == 1
    assert json.loads(conn.execute("SELECT result_json FROM jobs ORDER BY id DESC LIMIT 1").fetchone()[0]) == {"skipped": "already_sent"}


def test_handlers_are_registered_through_load_handlers():
    registry.load_handlers()
    assert {"send_email", "send_webhook"} <= registry.registered_types()
    assert registry.get_handler("send_email") is email.handle_send_email and registry.get_handler("send_webhook") is webhook.handle_send_webhook


# ------------------------------------------------------------------------------------------- webhooks
@pytest.mark.parametrize("fmt", webhook.FORMATS)
def test_webhook_format_bodies(settings, seeded, connect, frozen_clock, monkeypatch, fmt):
    conn = seeded
    captured = Captured().install(monkeypatch)
    uid = make_user(conn, email_enabled=0, webhook_url="https://hooks.example.com/wd/abc?token=1", webhook_format=fmt)
    give_content(conn, "abandon")
    bid = build(conn, uid, "abandon")
    assert batches.enqueue_deliveries(conn, bid, NOW) == {"webhook": "queued"}
    assert queue.run_once(ctx_for(connect, settings, frozen_clock)) == 1
    (request,) = captured.requests
    assert request.url.host == PUBLIC_IP and request.url.path == "/wd/abc" and request.url.query == b"token=1"  # pinned to the resolved address
    assert request.headers["host"] == "hooks.example.com" and request.extensions.get("sni_hostname") == "hooks.example.com"
    assert request.headers["content-type"].startswith("application/json")
    (body,) = captured.bodies()
    title = "word-Dance 今日词汇 10月14日 · 复习 0 · 新词 1 · 推荐 1"
    if fmt == "generic":
        assert body["type"] == "daily_push" and body["date"] == "2026-10-14" and body["title"] == title and body["url"] is None
        assert body["counts"] == {"review": 0, "new": 1, "screen": 1, "extra": 0, "deferred_reviews": 0}
        assert body["words"][0] == {"word": "abandon", "phonetic": "ə'bændən", "meaning_zh": "放弃；抛弃"} and len(body["words"]) == 2
        assert "放弃" in body["body"] and webhook.NO_LINK_ZH in body["body"]
    elif fmt == "wecom":
        assert set(body) == {"msgtype", "text"} and body["msgtype"] == "text" and body["text"]["content"].startswith(title)
    elif fmt == "feishu":
        assert set(body) == {"msg_type", "content"} and body["msg_type"] == "text" and body["content"]["text"].startswith(title)
    elif fmt == "serverchan":
        assert set(body) == {"title", "desp"} and body["title"] == title and "abandon" in body["desp"]
    else:
        assert set(body) == {"title", "body"} and body["title"] == title  # bark: url key omitted when unknown
    assert conn.execute("SELECT webhook_status FROM push_batches WHERE id = ?", (bid,)).fetchone()[0] == "sent"
    job = json.loads(conn.execute("SELECT result_json FROM jobs WHERE type = 'send_webhook'").fetchone()[0])
    assert job == {"sent": True, "http_status": 200, "format": fmt}


def test_webhook_url_fields_with_a_public_url(settings, seeded, connect, frozen_clock, monkeypatch):
    conn = seeded
    captured = Captured().install(monkeypatch)
    cfg = dataclasses.replace(settings, public_url="https://wd.example.com")
    uid = make_user(conn, email_enabled=0, webhook_url="https://hooks.example.com/g", webhook_format="generic")
    bob = make_user(conn, "bob", email_enabled=0, webhook_url="https://api.day.app/key", webhook_format="bark")
    bids = [build(conn, who, lemma) for who, lemma in ((uid, "apple"), (bob, "bank"))]  # build() clears the queue, so enqueue afterwards
    for bid in bids:
        assert batches.enqueue_deliveries(conn, bid, NOW) == {"webhook": "queued"}
    assert queue.run_once(ctx_for(connect, cfg, frozen_clock)) == 2
    generic, bark = captured.bodies()
    assert generic["url"] == "https://wd.example.com/today" and bark["url"] == "https://wd.example.com/today"
    assert "https://wd.example.com/today" in generic["body"]


def test_webhook_ssrf_guard_rejects_private_targets(settings, seeded, connect, frozen_clock, monkeypatch):
    captured = Captured().install(monkeypatch, ips=("10.0.0.1",))
    row = {"webhook_url": "https://hooks.example.com/x", "webhook_format": "generic"}
    r = webhook.send_test_webhook(row)
    assert r["ok"] is False and r["http_status"] is None and "rejected" in r["error"] and "10.0.0.1" in r["error"]
    assert captured.requests == []
    for bad in ("http://hooks.example.com/x", "https://127.0.0.1/x", "https://[::1]/x", "https://localhost/x", "https://intranet.local/x", "https://user:pw@hooks.example.com/x", "https://hooks/x", ""):
        assert webhook.send_test_webhook({**row, "webhook_url": bad})["ok"] is False
    for ip in ("127.0.0.1", "10.0.0.1", "192.168.1.1", "169.254.169.254", "100.64.0.1", "::1", "fe80::1", "::ffff:10.0.0.1", "64:ff9b::7f00:1", "0.0.0.0"):
        assert not webhook.is_public_ip(ip)
    assert webhook.is_public_ip(PUBLIC_IP) and webhook.is_public_ip("2606:2800:220:1:248:1893:25c8:1946")
    # a mixed record set (one private) is refused as a whole
    Captured().install(monkeypatch, ips=(PUBLIC_IP, "192.168.0.9"))
    assert webhook.send_test_webhook(row)["ok"] is False
    # the job handler treats a refused URL as final: webhook_status failed, job done, no retry
    conn = seeded
    uid = make_user(conn, email_enabled=0, webhook_url="https://hooks.example.com/x")
    bid = build(conn, uid, "apple")
    batches.enqueue_deliveries(conn, bid, NOW)
    queue.run_once(ctx_for(connect, settings, frozen_clock))
    assert conn.execute("SELECT webhook_status FROM push_batches WHERE id = ?", (bid,)).fetchone()[0] == "failed"
    job = db.row_to_dict(conn.execute("SELECT status, result_json FROM jobs WHERE type = 'send_webhook'").fetchone())
    assert job["status"] == "done" and json.loads(job["result_json"])["final"] is True


def test_send_test_webhook_ok_and_server_errors_retry(settings, seeded, connect, frozen_clock, monkeypatch):
    captured = Captured().install(monkeypatch)
    r = webhook.send_test_webhook({"webhook_url": "https://hooks.example.com/x", "webhook_format": "wecom"})
    assert r == {"ok": True, "http_status": 200, "error": None}
    assert captured.bodies()[0]["text"]["content"].startswith(webhook.TEST_TITLE_ZH)
    generic = webhook.build_payload("generic", webhook.TEST_TITLE_ZH, webhook.TEST_BODY_ZH, url=None, date="2026-10-14", type_="test")
    assert generic["type"] == "test" and generic["words"] == [] and generic["url"] is None
    # an HTTP 500 is retried with backoff, then dead → failed
    failing = Captured(status=500).install(monkeypatch)
    conn = seeded
    uid = make_user(conn, email_enabled=0, webhook_url="https://hooks.example.com/x")
    bid = build(conn, uid, "apple")
    batches.enqueue_deliveries(conn, bid, NOW)
    ctx = ctx_for(connect, settings, frozen_clock)
    queue.run_once(ctx)
    job = db.row_to_dict(conn.execute("SELECT * FROM jobs WHERE type = 'send_webhook'").fetchone())
    assert job["status"] == "queued" and job["attempts"] == 1 and job["last_error"] == "HTTP 500"
    assert conn.execute("SELECT webhook_status, delivery_error FROM push_batches WHERE id = ?", (bid,)).fetchone()[:] == ("queued", "HTTP 500")
    for _ in range(2):
        frozen_clock.advance(hours=2)
        queue.run_once(ctx)
    assert conn.execute("SELECT status FROM jobs WHERE type = 'send_webhook'").fetchone()[0] == "dead"
    assert conn.execute("SELECT webhook_status FROM push_batches WHERE id = ?", (bid,)).fetchone()[0] == "failed"
    assert len(failing.requests) == 3
    # recovery sends once; a re-run for a sent batch sends nothing
    ok = Captured().install(monkeypatch)
    queue.enqueue(conn, "send_webhook", {"batch_id": bid}, dedupe_key=f"webhook:{bid}:r1", now=ctx.now())
    queue.run_once(ctx)
    queue.enqueue(conn, "send_webhook", {"batch_id": bid}, dedupe_key=f"webhook:{bid}:r2", now=ctx.now())
    queue.run_once(ctx)
    assert len(ok.requests) == 1 and conn.execute("SELECT webhook_status FROM push_batches WHERE id = ?", (bid,)).fetchone()[0] == "sent"
    assert webhook.send_test_webhook({"webhook_url": "https://hooks.example.com/x", "webhook_format": "unknown"})["ok"] is True  # falls back to generic


def test_webhook_test_route_uses_the_late_import(client, settings, monkeypatch):
    """WP2's POST /api/settings/webhook/test reaches delivery.webhook.send_test_webhook once WP4 exists."""
    import secrets

    from wd.deps import hash_token

    captured = Captured().install(monkeypatch)
    conn = db.connect(settings.db_path)
    try:
        with db.tx(conn):
            uid = int(conn.execute("INSERT INTO users(username, password_hash, onboarding_state) VALUES ('hook', 'x', 'done')").lastrowid)
            conn.execute(
                "INSERT INTO user_settings(user_id, webhook_enabled, webhook_url, webhook_format, next_push_at) VALUES (?, 1, 'https://hooks.example.com/x', 'feishu', '2026-10-15T00:00:00Z')",
                (uid,),
            )
            token = secrets.token_urlsafe(32)
            conn.execute("INSERT INTO sessions(token_hash, user_id, expires_at) VALUES (?, ?, '2030-01-01T00:00:00Z')", (hash_token(token), uid))
    finally:
        conn.close()
    client.cookies.set("wd_session", token)
    r = client.post("/api/settings/webhook/test")
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "http_status": 200, "error": None}
    assert captured.bodies()[0]["msg_type"] == "text"
