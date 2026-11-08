"""Endpoints 14–18: settings read/partial update + validation, timezones, webhook test (late import), e-mail test job."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from wd import db, security
from wd.delivery import webhook
from wd.delivery.mailer import RecordingMailer
from wd.routers.settings import CURATED_TIMEZONES
from wd.schemas import stage_to_index
from wd.services import bank

PW = "Correct-Horse-7"
NOW = datetime(2026, 10, 14, 0, 0, 0, tzinfo=timezone.utc)
NOW_ISO = "2026-10-14T00:00:00Z"
HOOK = "https://hooks.example.com/word-dance"


@pytest.fixture(autouse=True)
def fast_bcrypt(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(security, "BCRYPT_ROUNDS", 4)


@pytest.fixture
def alice(client: TestClient) -> dict:
    r = client.post("/api/auth/register", json={"username": "alice", "password": PW, "email": "alice@example.com"})
    assert r.status_code == 201, r.text
    return r.json()["user"]


def error(r) -> dict:
    return r.json()["error"]


def verify_email(settings, user_id: int) -> None:
    c = db.connect(settings.db_path)
    try:
        c.execute("UPDATE users SET email_verified_at = ? WHERE id = ?", (NOW_ISO, user_id))
    finally:
        c.close()


def test_get_settings_defaults(client: TestClient, alice):
    r = client.get("/api/settings")
    assert r.status_code == 200
    assert r.json() == {
        "timezone": "Asia/Shanghai",
        "push_time": "08:00",
        "push_enabled": True,
        "daily_new_count": 10,
        "daily_screen_count": 15,
        "max_reviews": 60,
        "stages": ["xs", "zk"],  # the K-12 DDL defaults (0011 / bank.DEFAULT_*): 主攻 小学, 目标 小学 + 初中
        "current_stage": "xs",
        "show_images": True,
        "zh_examples": "tap",
        "auto_pronounce": True,
        "accent": "en-US",
        "dance_mode": "full",
        "email_enabled": False,
        "webhook_enabled": False,
        "webhook_url": None,
        "webhook_format": "generic",
        "next_push_at": "2026-10-15T00:00:00Z",
        "email_verified": False,
        "updated_at": NOW_ISO,
    }
    assert client.get("/api/settings/timezones").status_code == 200


def test_settings_with_an_unknown_stage_code_fall_back_like_the_study_paths(client: TestClient, alice, settings, caplog):
    """A stored stages_json naming no known stage code (hand-edited, or written by a newer server): GET /api/settings and
    GET /api/auth/me answer 200 with bank.DEFAULT_STAGES plus one stage_fallback warning — the same fallback /api/today
    already applied through bank.user_settings_row (PLAN §2.1) — instead of failing response validation with a 500 that
    kept the SPA from booting (impl-review final F2). Known codes beside an unknown one are kept; PUT repairs the row."""

    def store(stages_json: str, current_stage: int) -> None:
        c = db.connect(settings.db_path)
        try:
            c.execute("UPDATE user_settings SET stages_json = ?, current_stage = ? WHERE user_id = ?", (stages_json, current_stage, alice["id"]))
        finally:
            c.close()

    store('["cet9"]', stage_to_index("xs"))
    with caplog.at_level(logging.WARNING, logger="wd.bank"):
        r = client.get("/api/settings")
    assert r.status_code == 200, r.text
    assert r.json()["stages"] == list(bank.DEFAULT_STAGES) and r.json()["current_stage"] == "xs"
    fallbacks = [rec for rec in caplog.records if getattr(rec, "event", None) == "stage_fallback"]
    assert len(fallbacks) == 1 and fallbacks[0].user_id == alice["id"] and "cet9" in fallbacks[0].getMessage()
    me = client.get("/api/auth/me")
    assert me.status_code == 200 and me.json()["settings"]["stages"] == list(bank.DEFAULT_STAGES)
    store('["cet9", "gk"]', stage_to_index("gk"))
    r = client.get("/api/settings")
    assert r.status_code == 200 and r.json()["stages"] == ["gk"] and r.json()["current_stage"] == "gk"  # unknown dropped, known kept
    r = client.put("/api/settings", json={"stages": ["zk"], "current_stage": "zk"})
    assert r.status_code == 200 and r.json()["stages"] == ["zk"] and r.json()["current_stage"] == "zk"
    assert client.get("/api/settings").json()["stages"] == ["zk"]


def test_partial_update_recomputes_next_push_at(client: TestClient, alice, settings, frozen_clock):
    r = client.put("/api/settings", json={"push_time": "21:00", "daily_new_count": 20, "zh_examples": "always", "accent": "en-GB", "show_images": False, "dance_mode": "off"})
    assert r.status_code == 200, r.text
    st = r.json()
    assert st["push_time"] == "21:00" and st["daily_new_count"] == 20 and st["zh_examples"] == "always" and st["accent"] == "en-GB" and st["show_images"] is False
    assert st["dance_mode"] == "off" and client.get("/api/settings").json()["dance_mode"] == "off"
    assert st["timezone"] == "Asia/Shanghai" and st["stages"] == ["xs", "zk"] and st["max_reviews"] == 60  # untouched
    assert st["next_push_at"] == "2026-10-14T13:00:00Z"  # 21:00 Shanghai later today
    frozen_clock.advance(minutes=5)
    r = client.put("/api/settings", json={"timezone": "Europe/London"})
    assert r.json()["next_push_at"] == "2026-10-14T20:00:00Z" and r.json()["updated_at"] == "2026-10-14T00:05:00Z"  # 21:00 BST
    r = client.put("/api/settings", json={"stages": ["zk", "gk"], "current_stage": "gk", "push_enabled": False})
    assert r.json()["stages"] == ["zk", "gk"] and r.json()["current_stage"] == "gk" and r.json()["push_enabled"] is False
    c = db.connect(settings.db_path)
    try:
        row = c.execute("SELECT current_stage, stages_json, push_enabled FROM user_settings WHERE user_id = ?", (alice["id"],)).fetchone()
        assert row[0] == 3 and json.loads(row[1]) == ["zk", "gk"] and row[2] == 0  # 'gk' stored as 3
    finally:
        c.close()
    assert client.get("/api/settings").json()["current_stage"] == "gk"
    r = client.put("/api/settings", json={})  # an empty body is a no-op save that still recomputes
    assert r.status_code == 200 and r.json()["current_stage"] == "gk"
    r = client.put("/api/settings", json={"timezone": None, "push_enabled": None, "stages": None})  # explicit null on NOT NULL fields = no change
    assert r.status_code == 200 and r.json()["timezone"] == "Europe/London" and r.json()["push_enabled"] is False and r.json()["stages"] == ["zk", "gk"]


@pytest.mark.parametrize(
    "body,field",
    [
        ({"timezone": "Mars/Olympus"}, "timezone"),
        ({"push_time": "25:00"}, "push_time"),
        ({"push_time": "8:00"}, "push_time"),
        ({"daily_new_count": 51}, "daily_new_count"),
        ({"daily_screen_count": -1}, "daily_screen_count"),
        ({"max_reviews": 301}, "max_reviews"),
        ({"stages": []}, "stages"),
        ({"stages": ["cet9"]}, "stages"),
        ({"stages": ["zk"], "current_stage": "gk"}, "body"),  # cross-field in the request itself
        ({"stages": ["zk"]}, "current_stage"),  # stored current_stage xs would fall outside
        ({"current_stage": "gk"}, "current_stage"),  # stored stages are xs/zk
        ({"zh_examples": "never"}, "zh_examples"),
        ({"dance_mode": "loud"}, "dance_mode"),
        ({"accent": "en-AU"}, "accent"),
        ({"webhook_format": "slack"}, "webhook_format"),
        ({"nickname": "x"}, "nickname"),
    ],
)
def test_update_validation(client: TestClient, alice, body, field):
    r = client.put("/api/settings", json=body)
    assert r.status_code == 400 and error(r)["code"] == "validation_error", r.text
    fields = error(r)["details"]["fields"]
    assert any(k == field or k.startswith(field + ".") for k in fields), error(r)  # list items are reported as stages.0
    assert client.get("/api/settings").json()["current_stage"] == "xs"  # nothing changed


def test_email_enabled_requires_verified_email_and_smtp(client: TestClient, alice, app, settings):
    r = client.put("/api/settings", json={"email_enabled": True})
    assert r.status_code == 409 and error(r)["code"] == "email_not_verified"
    verify_email(settings, alice["id"])
    r = client.put("/api/settings", json={"email_enabled": True})
    assert r.status_code == 409 and error(r)["code"] == "smtp_unconfigured"
    app.state.mailer = RecordingMailer()
    r = client.put("/api/settings", json={"email_enabled": True})
    assert r.status_code == 200 and r.json()["email_enabled"] is True and r.json()["email_verified"] is True
    app.state.mailer = None
    r = client.put("/api/settings", json={"email_enabled": False, "push_time": "09:00"})  # disabling never needs SMTP
    assert r.status_code == 200 and r.json()["email_enabled"] is False


def test_webhook_url_policy(client: TestClient, alice, settings):
    for bad in ("http://hooks.example.com/x", "https://10.0.0.1/x", "https://127.0.0.1/x", "https://localhost/x", "https://[::1]/x", "https://nas.local/x", "https://169.254.169.254/latest"):
        r = client.put("/api/settings", json={"webhook_url": bad})
        assert r.status_code == 400 and error(r)["code"] == "validation_error" and "webhook_url" in error(r)["details"]["fields"], bad
    r = client.put("/api/settings", json={"webhook_enabled": True})
    assert r.status_code == 409 and error(r)["code"] == "webhook_unconfigured"
    r = client.put("/api/settings", json={"webhook_enabled": True, "webhook_url": HOOK, "webhook_format": "wecom"})
    assert r.status_code == 200 and r.json()["webhook_enabled"] is True and r.json()["webhook_url"] == HOOK and r.json()["webhook_format"] == "wecom"
    r = client.put("/api/settings", json={"webhook_url": None})  # clearing the URL while enabled is refused
    assert r.status_code == 409 and error(r)["code"] == "webhook_unconfigured"
    r = client.put("/api/settings", json={"webhook_url": "https://10.0.0.1/x"})  # a bad replacement is refused and the old one kept
    assert r.status_code == 400 and client.get("/api/settings").json()["webhook_url"] == HOOK
    r = client.put("/api/settings", json={"webhook_enabled": False, "webhook_url": None})
    assert r.status_code == 200 and r.json()["webhook_enabled"] is False and r.json()["webhook_url"] is None


def test_timezones_curated_and_all(client: TestClient, alice):
    r = client.get("/api/settings/timezones")
    items = r.json()["items"]
    assert len(items) == 30 and items[0] == "Asia/Shanghai" and items == list(CURATED_TIMEZONES) and len(set(items)) == 30
    r = client.get("/api/settings/timezones?all=1")
    everything = r.json()["items"]
    assert len(everything) > 300 and everything[0] == "Asia/Shanghai" and everything.count("Asia/Shanghai") == 1
    assert "Factory" not in everything and "America/New_York" in everything and everything[1:] == sorted(everything[1:])
    assert client.get("/api/settings/timezones?all=0").json()["items"] == items
    assert client.get("/api/settings/timezones?all=maybe").status_code == 400


def test_webhook_test_endpoint(client: TestClient, alice, frozen_clock, monkeypatch: pytest.MonkeyPatch):
    r = client.post("/api/settings/webhook/test")
    assert r.status_code == 409 and error(r)["code"] == "webhook_unconfigured"
    assert client.put("/api/settings", json={"webhook_enabled": True, "webhook_url": HOOK, "webhook_format": "feishu"}).status_code == 200
    calls: list[dict] = []

    def send_test_webhook(row):
        calls.append(dict(row))
        return {"ok": True, "http_status": 200, "error": None, "reason": None}

    monkeypatch.setattr(webhook, "send_test_webhook", send_test_webhook)  # WP4's sender; test_delivery exercises the real one
    r = client.post("/api/settings/webhook/test")
    assert r.status_code == 200 and r.json() == {"ok": True, "http_status": 200, "error": None, "reason": None}, r.text
    assert len(calls) == 1 and calls[0]["webhook_url"] == HOOK and calls[0]["webhook_format"] == "feishu" and calls[0]["user_id"] == alice["id"]
    r = client.post("/api/settings/webhook/test")
    assert r.status_code == 429 and error(r)["code"] == "rate_limited" and r.headers["Retry-After"] == "600"  # 1 per 10 min
    frozen_clock.advance(minutes=10)
    monkeypatch.setattr(webhook, "send_test_webhook", lambda row: {"ok": False, "http_status": 500, "error": "boom", "reason": "http_error"})
    r = client.post("/api/settings/webhook/test")
    assert r.status_code == 200 and r.json() == {"ok": False, "http_status": 500, "error": "boom", "reason": "http_error"}


def test_webhook_test_endpoint_reports_reason_and_status(client: TestClient, alice, frozen_clock, monkeypatch: pytest.MonkeyPatch):
    """API.md 17 through the real sender: the response carries the closed-set ``reason`` next to ``http_status`` and the
    English ``error`` — the outbound request goes through the webhook module's httpx seam (``CLIENT_FACTORY`` + pinned
    ``resolve_host``), so nothing leaves the box."""
    assert client.put("/api/settings", json={"webhook_enabled": True, "webhook_url": HOOK, "webhook_format": "generic"}).status_code == 200
    monkeypatch.setattr(webhook, "resolve_host", lambda host: ["93.184.216.34"])  # the DNS pin: a public address

    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("[Errno 111] Connection refused")

    monkeypatch.setattr(webhook, "CLIENT_FACTORY", lambda: httpx.Client(transport=httpx.MockTransport(refused), follow_redirects=False))
    r = client.post("/api/settings/webhook/test")
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": False, "http_status": None, "error": "request failed: ConnectError: [Errno 111] Connection refused", "reason": "connect_failed"}

    frozen_clock.advance(minutes=10)
    monkeypatch.setattr(webhook, "CLIENT_FACTORY", lambda: httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(503, text="maintenance")), follow_redirects=False))
    r = client.post("/api/settings/webhook/test")
    assert r.status_code == 200 and r.json() == {"ok": False, "http_status": 503, "error": "HTTP 503", "reason": "http_error"}

    frozen_clock.advance(minutes=10)
    monkeypatch.setattr(webhook, "resolve_host", lambda host: ["10.0.0.1"])  # the saved name now resolves into a private range
    r = client.post("/api/settings/webhook/test")
    body = r.json()
    assert r.status_code == 200 and body["ok"] is False and body["http_status"] is None and body["reason"] == "host_not_public"
    assert body["error"] == "rejected: hooks.example.com resolves to a non-public address 10.0.0.1"


def test_email_test_endpoint_enqueues_the_test_job(client: TestClient, alice, app, settings, frozen_clock):
    r = client.post("/api/settings/email/test")
    assert r.status_code == 409 and error(r)["code"] == "email_not_verified"
    verify_email(settings, alice["id"])
    r = client.post("/api/settings/email/test")
    assert r.status_code == 409 and error(r)["code"] == "smtp_unconfigured"
    app.state.mailer = RecordingMailer()
    r = client.post("/api/settings/email/test")
    assert r.status_code == 202 and r.json() == {"queued": True}
    c = db.connect(settings.db_path)
    try:
        jobs = c.execute("SELECT * FROM jobs").fetchall()
        assert len(jobs) == 1
        job = jobs[0]
        assert job["type"] == "send_email" and json.loads(job["payload_json"]) == {"user_id": alice["id"], "test": True}
        assert job["dedupe_key"] == f"email:test:{alice['id']}" and job["priority"] == 10 and job["status"] == "queued" and job["run_after"] == NOW_ISO
    finally:
        c.close()
    r = client.post("/api/settings/email/test")
    assert r.status_code == 429 and error(r)["code"] == "rate_limited"
    frozen_clock.advance(minutes=10)
    assert client.post("/api/settings/email/test").status_code == 202
    c = db.connect(settings.db_path)
    try:
        assert c.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1  # the live-key UPSERT folds it into the queued job
    finally:
        c.close()
