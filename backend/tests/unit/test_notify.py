"""wd/notify.py: admin webhooks (the failover.notify contract generalised) — every active admin with a URL, kv dedupe per kind,
skipped under the smoke mock / inside a transaction / without admins, every failure swallowed."""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import replace

import httpx
import pytest

from wd import db, notify
from wd.ai import failover
from wd.delivery import webhook

NOW = "2026-10-14T00:00:00Z"
HOOK_URL = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc"
PUBLIC_IP = "93.184.216.34"


def make_admin(conn: sqlite3.Connection, username: str = "root", *, url: str = HOOK_URL, fmt: str = "wecom", enabled: int = 1, role: str = "admin") -> int:
    uid = int(conn.execute("INSERT INTO users(username, password_hash, role, onboarding_state) VALUES (?, 'x', ?, 'done')", (username, role)).lastrowid)
    conn.execute(
        "INSERT INTO user_settings(user_id, next_push_at, webhook_enabled, webhook_url, webhook_format) VALUES (?, '2026-10-15T00:00:00Z', ?, ?, ?)",
        (uid, enabled, url, fmt),
    )
    return uid


class Captured:
    def __init__(self, status: int = 200):
        self.status = status
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status, json={"errcode": 0})

    def install(self, monkeypatch) -> "Captured":
        transport = httpx.MockTransport(self.handler)
        monkeypatch.setattr(notify, "WEBHOOK_CLIENT_FACTORY", lambda: httpx.Client(transport=transport, follow_redirects=False))
        monkeypatch.setattr(webhook, "resolve_host", lambda host: [PUBLIC_IP])  # the SSRF pin without DNS
        return self

    def bodies(self) -> list[dict]:
        return [json.loads(r.content) for r in self.requests]


@pytest.fixture(autouse=True)
def _no_client_hook(monkeypatch):
    monkeypatch.setattr(notify, "WEBHOOK_CLIENT_FACTORY", None)


def test_same_admin_rows_as_failover():
    assert notify.ADMIN_WEBHOOKS_SQL == failover.ADMIN_WEBHOOKS_SQL


def test_skipped_without_admins_under_the_smoke_mock_and_inside_a_transaction(conn, settings, monkeypatch, caplog):
    captured = Captured().install(monkeypatch)
    live = replace(settings, smoke_mock_http=False)
    assert notify.notify_admins(conn, live, "sms_budget_80", "短信额度提醒", "80%", now=NOW) == 0  # nobody
    make_admin(conn, "viewer", role="user")
    make_admin(conn, "quiet", enabled=0)
    make_admin(conn, "blank", url="")
    assert notify.notify_admins(conn, live, "sms_budget_80", "短信额度提醒", "80%", now=NOW) == 0
    assert captured.requests == [] and db.kv_get(conn, "notify.sms_budget_80.last_at") is None
    make_admin(conn, "root")
    assert notify.notify_admins(conn, settings, "sms_budget_80", "短信额度提醒", "80%", now=NOW) == 0  # WD_SMOKE_MOCK_HTTP=1 in the test env
    assert captured.requests == [] and db.kv_get(conn, "notify.sms_budget_80.last_at") is None
    with caplog.at_level(logging.WARNING, logger="wd.notify"):
        with db.tx(conn):
            assert notify.notify_admins(conn, live, "sms_budget_80", "短信额度提醒", "80%", now=NOW) == 0
    assert captured.requests == [] and any(getattr(r, "event", None) == "notify_skipped" for r in caplog.records)


def test_posts_to_every_admin_once_per_kind_per_window(conn, settings, monkeypatch):
    captured = Captured().install(monkeypatch)
    live = replace(settings, smoke_mock_http=False)
    make_admin(conn, "root", fmt="wecom")
    make_admin(conn, "second", url="https://open.feishu.cn/open-apis/bot/v2/hook/abc", fmt="feishu")
    make_admin(conn, "third", url="https://hooks.example.com/x", fmt="generic")
    make_admin(conn, "fourth", url="https://api.day.app/key", fmt="bark")
    assert notify.notify_admins(conn, live, "sms_budget_80", "短信额度提醒", "今日已发送 160 / 200 条（80%）", now=NOW) == 4
    assert len(captured.requests) == 4 and db.kv_get(conn, "notify.sms_budget_80.last_at") == NOW
    assert {r.headers["Host"] for r in captured.requests} == {"qyapi.weixin.qq.com", "open.feishu.cn", "hooks.example.com", "api.day.app"}
    wecom, feishu, generic, bark = captured.bodies()
    assert wecom == {"msgtype": "text", "text": {"content": "短信额度提醒\n今日已发送 160 / 200 条（80%）"}}
    assert feishu["msg_type"] == "text" and "80%" in feishu["content"]["text"]
    assert generic["type"] == "sms_budget_80" and generic["title"] == "短信额度提醒" and generic["date"] == "2026-10-14" and generic["url"] is None
    assert bark == {"title": "短信额度提醒", "body": "今日已发送 160 / 200 条（80%）"}
    # the same kind within the hour is not re-sent; another kind is; after the window it is again
    assert notify.notify_admins(conn, live, "sms_budget_80", "短信额度提醒", "again", now="2026-10-14T00:59:59Z") == 0
    assert notify.notify_admins(conn, live, "sms_budget_100", "短信额度提醒", "100%", now="2026-10-14T00:10:00Z") == 4
    assert notify.notify_admins(conn, live, "sms_budget_80", "短信额度提醒", "again", now="2026-10-14T01:00:00Z") == 4
    assert notify.notify_admins(conn, live, "sms_budget_80", "短信额度提醒", "again", now="2026-10-14T01:30:00Z", dedupe_s=60) == 4  # a shorter window
    assert len(captured.requests) == 16


def test_failures_are_swallowed_and_counted_as_not_sent(conn, settings, monkeypatch, caplog):
    captured = Captured(status=500).install(monkeypatch)
    live = replace(settings, smoke_mock_http=False)
    make_admin(conn, "root")
    with caplog.at_level(logging.WARNING, logger="wd.notify"):
        assert notify.notify_admins(conn, live, "sms_budget_100", "t", "b", now=NOW) == 0
    assert len(captured.requests) == 1 and db.kv_get(conn, "notify.sms_budget_100.last_at") == NOW  # claimed before the attempt: no retry storm
    assert any(getattr(r, "event", None) == "notify_failed" for r in caplog.records)
    # an exception anywhere inside (a broken client factory) never escapes
    monkeypatch.setattr(notify, "WEBHOOK_CLIENT_FACTORY", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    db.kv_delete(conn, "notify.sms_budget_100.last_at")
    with caplog.at_level(logging.WARNING, logger="wd.notify"):
        assert notify.notify_admins(conn, live, "sms_budget_100", "t", "b", now=NOW) == 0
    # a datetime `now` is accepted too
    from datetime import datetime, timezone

    db.kv_delete(conn, "notify.sms_budget_100.last_at")
    Captured().install(monkeypatch)
    assert notify.notify_admins(conn, live, "sms_budget_100", "t", "b", now=datetime(2026, 10, 14, 2, 0, tzinfo=timezone.utc)) == 1
    assert db.kv_get(conn, "notify.sms_budget_100.last_at") == "2026-10-14T02:00:00Z"
