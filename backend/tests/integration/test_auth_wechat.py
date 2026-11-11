"""Endpoints 112–116 (API.md §3.3, slice 2-A) with the FakeWechatClient installed as ``app.state.wechat``: the login ticket (cookie, shape,
row), the poll (404 without the cookie), the 小程序码 PNG (and its 502), the scan by ticket and by pairing code (re-scan, scanned_elsewhere,
bad / down js_code), the confirmation that creates the account and the poll that turns it into the session (201, providers, the poll cookie
cleared, a second poll 404), the second login of the same openid, invite / closed modes, admins and disabled accounts (a disabling between
the confirmation and the poll consumes the ticket before the 403), cancel, expiry and the 60-s delivery grace of a confirmed / cancelled
result, a signed-in browser's previous session replaced by the login, bind (self / other / new, identity_taken with the WeChat wording,
guardian_required), the second confirmation by pairing code (409 wrong_state like the scene path, a re-drawn code), the endpoint-89 password
rule for a third-party-only account, every rate-limit window (ticket minute / hour, poll — 114 exempt —, scan ip / openid, confirm ip /
openid), the ``providers`` list on ``/me`` and the hourly GC."""

from __future__ import annotations

import logging
import re
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from wd import db, security, third_party, wechat_bridge as bridge
from wd.clock import to_iso
from wd.delivery.wechat import FakeWechatClient, WechatError
from wd.deps import hash_token
from wd.jobs import scheduler
from wd.main import create_app
from wd.wechat_bridge import POLL_COOKIE, TICKET_RE, pair_hash, poll_hash, ticket_hash

PW = "Correct-Horse-7"
NOW = datetime(2026, 10, 14, 0, 0, 0, tzinfo=timezone.utc)
NOW_ISO = "2026-10-14T00:00:00Z"
MAC_CHROME = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
PLACEHOLDER_RE = re.compile(r"^u_[a-z2-7]{8}$")


@pytest.fixture(autouse=True)
def fast_bcrypt(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(security, "BCRYPT_ROUNDS", 4)


@pytest.fixture
def wechat(app) -> FakeWechatClient:
    fake = FakeWechatClient()
    app.state.wechat = fake
    return fake


def second_client(app, *, user_agent: str | None = MAC_CHROME) -> TestClient:
    c = TestClient(app, base_url="http://testserver")
    c.headers["X-WD-Request"] = "1"
    if user_agent:
        c.headers["User-Agent"] = user_agent
    return c


def bootstrap(client: TestClient, username: str = "root") -> dict:
    """The first account is a username + password registration (admin): a third-party sign-in refuses an empty site (setup_required)."""
    r = client.post("/api/auth/register", json={"username": username, "password": PW})
    assert r.status_code == 201, r.text
    return r.json()["user"]


def error_code(r) -> str:
    return r.json()["error"]["code"]


def details(r) -> dict:
    return r.json()["error"].get("details") or {}


def rows(settings, sql: str, params=()) -> list[dict]:
    c = db.connect(settings.db_path)
    try:
        return [dict(r) for r in c.execute(sql, params).fetchall()]
    finally:
        c.close()


def execute(settings, sql: str, params=()) -> None:
    c = db.connect(settings.db_path)
    try:
        with db.tx(c):
            c.execute(sql, params)
    finally:
        c.close()


def ticket(web: TestClient, kind: str = "login", **extra) -> dict:
    r = web.post("/api/auth/wechat/ticket", json={"kind": kind, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def scan(mp: TestClient, js_code: str, *, ticket: str | None = None, pairing_code: str | None = None):
    body: dict = {"js_code": js_code}
    if ticket is not None:
        body["ticket"] = ticket
    if pairing_code is not None:
        body["pairing_code"] = pairing_code
    return mp.post("/api/auth/wechat/scan", json=body)


def confirm(mp: TestClient, info: dict, ticket_value: str, accept: bool = True):
    return mp.post("/api/auth/wechat/confirm", json={"mp_token": info["mp_token"], "ticket": ticket_value, "accept": accept})


def poll(web: TestClient, ticket_value: str):
    return web.get(f"/api/auth/wechat/ticket/{ticket_value}")


def sign_in_with_wechat(app, mp: TestClient, js_code: str, **ticket_extra) -> tuple[TestClient, dict]:
    """A browser signs in through the bridge: ticket → scan → confirm → poll; returns the browser client and the final poll body."""
    web = second_client(app)
    t = ticket(web, **ticket_extra)
    info = scan(mp, js_code, ticket=t["ticket"]).json()
    assert confirm(mp, info, t["ticket"]).status_code == 200
    r = poll(web, t["ticket"])
    assert r.status_code in (200, 201), r.text
    return web, r.json()


def app_with(settings, frozen_clock, **overrides):
    app = create_app(replace(settings, **overrides), clock=frozen_clock, configure_logs=False)
    app.state.wechat = FakeWechatClient()
    return app


# ------------------------------------------------------------------------------------ 112 / 113 / 114
def test_login_ticket_cookie_shape_row_poll_and_qr(client: TestClient, app, settings, wechat, caplog):
    bootstrap(client)
    web = second_client(app)
    with caplog.at_level(logging.INFO, logger="wd"):
        r = web.post("/api/auth/wechat/ticket", json={"kind": "login"})
    assert r.status_code == 201, r.text
    t = r.json()
    assert set(t) == {"ticket", "pairing_code", "expires_in_s", "qr_url"}
    assert TICKET_RE.match(t["ticket"]) and re.fullmatch(r"\d{6}", t["pairing_code"]) and t["expires_in_s"] == 180
    assert t["qr_url"] == f"/api/auth/wechat/ticket/{t['ticket']}/qr"
    cookie = r.headers["set-cookie"].lower()
    assert cookie.startswith("wd_wxt=") and "httponly" in cookie and "samesite=lax" in cookie and "path=/api/auth/wechat/ticket" in cookie and "max-age=180" in cookie
    assert "wd_session=" not in cookie  # the ticket is not a session
    secret = web.cookies.get(POLL_COOKIE)
    row = rows(settings, "SELECT * FROM wechat_tickets")[0]
    assert row["ticket_hash"] == ticket_hash(t["ticket"]) and row["pair_hash"] == pair_hash(settings, t["pairing_code"]) and row["poll_hash"] == poll_hash(secret)
    assert (row["kind"], row["status"], row["bind_user_id"], row["invite_code"], row["openid"], row["user_id"], row["created_account"]) == ("login", "pending", None, None, None, None, 0)
    assert (row["web_ip"], row["web_ua"], row["created_at"], row["expires_at"]) == ("testclient", MAC_CHROME, NOW_ISO, "2026-10-14T00:03:00Z")
    assert t["ticket"] not in str(row) and t["pairing_code"] not in str(row) and secret not in str(row)  # hashes only
    # the log line names the kind and ids, never the ticket, the code or the cookie
    created = [rec for rec in caplog.records if getattr(rec, "event", None) == "wx_ticket_created"]
    assert len(created) == 1 and created[0].kind == "login" and created[0].ticket_id == row["id"] and created[0].user_id is None
    assert t["ticket"] not in caplog.text and t["pairing_code"] not in caplog.text and secret not in caplog.text
    # 113: another browser (no cookie) → 404; the initiating browser → pending; an unknown ticket → 404 (same answer)
    stranger = second_client(app)
    r = stranger.get(f"/api/auth/wechat/ticket/{t['ticket']}")
    assert r.status_code == 404 and error_code(r) == "not_found"
    r = poll(web, t["ticket"])
    assert r.status_code == 200 and r.json() == {"status": "pending", "user": None, "settings": None, "created": None}
    assert poll(web, "a" * 26).status_code == 404 and poll(web, "not-a-ticket").status_code == 404
    # 114: the PNG of the fake, drawn once and cached; a stranger gets 404
    r = web.get(t["qr_url"])
    assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.content[:8] == PNG_MAGIC and len(r.content) > 500
    assert wechat.calls == [("qr_png", t["ticket"])]
    assert web.get(t["qr_url"]).content == r.content and len(wechat.calls) == 1  # served from the process cache
    assert stranger.get(t["qr_url"]).status_code == 404
    # the poll cookie is scoped to the ticket path: /api/auth/me never sees it
    assert web.get("/api/auth/me").status_code == 401


def test_qr_failure_answers_502_until_wechat_recovers(client: TestClient, app, settings, wechat):
    bootstrap(client)
    web = second_client(app)
    t = ticket(web)
    wechat.fail_qr_with = WechatError("temporary", "fake: 系统繁忙", code=-1)
    r = web.get(t["qr_url"])
    assert r.status_code == 502 and error_code(r) == "provider_error" and "繁忙" not in r.text  # the SPA shows the pairing code alone
    wechat.fail_qr_with = WechatError("config", "fake: invalid appid", code=40013)
    assert web.get(t["qr_url"]).status_code == 502
    wechat.fail_qr_with = None
    assert web.get(t["qr_url"]).status_code == 200  # nothing was cached for the failed calls
    assert len([c for c in wechat.calls if c[0] == "qr_png"]) == 3


def test_provider_unconfigured_without_a_client(client: TestClient, app):
    bootstrap(client)
    assert getattr(app.state, "wechat", None) is None  # the test env has no WD_WECHAT_* and no fakes
    web = second_client(app)
    mp = second_client(app, user_agent=None)
    r = web.post("/api/auth/wechat/ticket", json={"kind": "login"})
    assert r.status_code == 409 and error_code(r) == "provider_unconfigured"
    assert web.get("/api/auth/wechat/ticket/" + "a" * 26).status_code == 409
    assert web.get("/api/auth/wechat/ticket/" + "a" * 26 + "/qr").status_code == 409
    assert scan(mp, "code-1", pairing_code="123456").status_code == 409
    assert mp.post("/api/auth/wechat/confirm", json={"mp_token": "1.x", "ticket": "a" * 26, "accept": True}).status_code == 409
    assert client.get("/api/auth/me").json()["server"]["wechat_enabled"] is False


# ------------------------------------------------------------------------------------------ 115
def test_scan_by_ticket_and_by_pairing_code(client: TestClient, app, settings, wechat, frozen_clock, caplog):
    bootstrap(client)
    web = second_client(app)
    mp = second_client(app, user_agent=None)
    t = ticket(web)
    # neither or both → 400 on details.fields.body (the schema's exactly-one rule)
    r = scan(mp, "code-1")
    assert r.status_code == 400 and details(r)["fields"] == {"body": "请提供小程序码场景值或配对码"}
    r = scan(mp, "code-1", ticket=t["ticket"], pairing_code=t["pairing_code"])
    assert r.status_code == 400 and "body" in details(r)["fields"]
    # a bad js_code → 400 on fields.js_code; WeChat down → 502; neither touched the ticket
    r = scan(mp, "bad-code", ticket=t["ticket"])
    assert r.status_code == 400 and error_code(r) == "validation_error" and details(r)["fields"] == {"js_code": "微信登录凭证无效，请重试"}
    r = scan(mp, "down-code", ticket=t["ticket"])
    assert r.status_code == 502 and error_code(r) == "provider_error"
    assert poll(web, t["ticket"]).json()["status"] == "pending"
    # by the scene (the 小程序码)
    frozen_clock.advance(seconds=10)
    with caplog.at_level(logging.INFO, logger="wd"):
        r = scan(mp, "code-1", ticket=t["ticket"])
    assert r.status_code == 200, r.text
    info = r.json()
    assert set(info) == {"mp_token", "kind", "account", "bind_display_name", "web_ip_masked", "web_ua_summary", "created_at", "expires_in_s"}
    assert (info["kind"], info["account"], info["bind_display_name"], info["web_ip_masked"], info["web_ua_summary"]) == ("login", "new", None, "*", "Chrome · macOS")
    assert info["created_at"] == NOW_ISO and info["expires_in_s"] == 170
    exp, sig = info["mp_token"].split(".")
    assert int(exp) == int(frozen_clock.now_utc().timestamp()) + 300 and re.fullmatch(r"[0-9a-f]{64}", sig)
    row = rows(settings, "SELECT * FROM wechat_tickets")[0]
    assert (row["status"], row["openid"], row["scanned_at"]) == ("scanned", "wx_code-1", "2026-10-14T00:00:10Z")
    assert wechat.calls[-1] == ("code2session", "code-1")
    assert "wx_code-1" not in caplog.text and t["ticket"] not in caplog.text and info["mp_token"] not in caplog.text
    scanned = [rec for rec in caplog.records if getattr(rec, "event", None) == "wx_scanned"]
    assert len(scanned) == 1 and scanned[0].ticket_id == row["id"] and scanned[0].kind == "login"
    assert poll(web, t["ticket"]).json()["status"] == "scanned"
    # the same openid re-scans (a second tap): fine, scanned_at refreshed; another openid → 409 scanned_elsewhere
    frozen_clock.advance(seconds=5)
    r = scan(mp, "code-1", pairing_code=t["pairing_code"])
    assert r.status_code == 200 and r.json()["expires_in_s"] == 165
    assert rows(settings, "SELECT scanned_at FROM wechat_tickets")[0]["scanned_at"] == "2026-10-14T00:00:15Z"
    r = scan(mp, "code-2", ticket=t["ticket"])
    assert r.status_code == 409 and error_code(r) == "invalid_transition" and details(r) == {"reason": "scanned_elsewhere"}
    # by the pairing code on a fresh ticket; a wrong / unknown code → 404; the confirmation may name the pairing code too (the mini program
    # that paired by code never sees the scene) — the mp_token binds it to the row either way
    web2 = second_client(app)
    t2 = ticket(web2)
    r = scan(mp, "code-3", pairing_code=t2["pairing_code"])
    assert r.status_code == 200
    info2 = r.json()
    assert mp.post("/api/auth/wechat/confirm", json={"mp_token": info["mp_token"], "ticket": t2["pairing_code"], "accept": True}).status_code == 401  # the first ticket's token
    assert mp.post("/api/auth/wechat/confirm", json={"mp_token": info2["mp_token"], "ticket": t2["pairing_code"], "accept": True}).json() == {"status": "confirmed", "created": True}
    assert poll(web2, t2["ticket"]).status_code == 201
    r = mp.post("/api/auth/wechat/confirm", json={"mp_token": info2["mp_token"], "ticket": t2["pairing_code"], "accept": True})
    assert r.status_code == 409 and details(r) == {"reason": "wrong_state"}  # the finished row keeps its hash: the same answer as the scene path
    t3 = ticket(second_client(app))
    wrong = "000000" if t3["pairing_code"] != "000000" else "000001"
    r = scan(mp, "code-4", pairing_code=wrong)
    assert r.status_code == 404 and error_code(r) == "not_found"
    assert scan(mp, "code-4", ticket="b" * 26).status_code == 404
    assert mp.post("/api/auth/wechat/confirm", json={"mp_token": "1.x", "ticket": "neither-a-scene-nor-a-code", "accept": True}).status_code == 404


# ------------------------------------------------------------------------------------- 116 + 113 login
def test_confirm_creates_the_account_and_the_poll_signs_the_browser_in(client: TestClient, app, settings, wechat, frozen_clock, caplog):
    root = bootstrap(client)
    web = second_client(app)
    mp = second_client(app, user_agent=None)
    t = ticket(web)
    info = scan(mp, "code-1", ticket=t["ticket"]).json()
    # a wrong token / another ticket's token → 401; a pending ticket (no openid yet) → 401 too
    t_other = ticket(second_client(app))
    r = mp.post("/api/auth/wechat/confirm", json={"mp_token": info["mp_token"][:-1] + ("0" if info["mp_token"][-1] != "0" else "1"), "ticket": t["ticket"], "accept": True})
    assert r.status_code == 401 and error_code(r) == "invalid_identity_token"
    assert confirm(mp, info, t_other["ticket"]).status_code == 401
    assert mp.post("/api/auth/wechat/confirm", json={"mp_token": "garbage", "ticket": t["ticket"], "accept": True}).status_code == 401
    assert mp.post("/api/auth/wechat/confirm", json={"mp_token": info["mp_token"], "ticket": "c" * 26, "accept": True}).status_code == 404
    frozen_clock.advance(seconds=20)
    with caplog.at_level(logging.INFO, logger="wd"):
        r = confirm(mp, info, t["ticket"])
    assert r.status_code == 200 and r.json() == {"status": "confirmed", "created": True}
    assert "set-cookie" not in {k.lower() for k in r.headers}  # the mini program never receives a session
    users = rows(settings, "SELECT * FROM users WHERE id != ?", (root["id"],))
    assert len(users) == 1
    new = users[0]
    assert PLACEHOLDER_RE.match(new["username"]) and new["display_name"] is None and new["password_set_at"] is None and new["role"] == "user"
    assert (new["account_kind"], new["age_band"], new["last_login_at"]) == ("learner", None, "2026-10-14T00:00:20Z")
    identity = rows(settings, "SELECT * FROM identities")[0]
    assert (identity["user_id"], identity["provider"], identity["subject"], identity["verified_at"], identity["last_login_at"], identity["disputed_at"]) == (new["id"], "wechat_mini", "wx_code-1", "2026-10-14T00:00:20Z", "2026-10-14T00:00:20Z", None)
    row = rows(settings, "SELECT * FROM wechat_tickets WHERE ticket_hash = ?", (ticket_hash(t["ticket"]),))[0]
    assert (row["status"], row["user_id"], row["created_account"], row["confirmed_at"], row["pair_hash"]) == ("confirmed", new["id"], 1, "2026-10-14T00:00:20Z", pair_hash(settings, t["pairing_code"]))
    confirmed = [rec for rec in caplog.records if getattr(rec, "event", None) == "wx_confirmed"]
    assert len(confirmed) == 1 and (confirmed[0].ticket_id, confirmed[0].kind, confirmed[0].created_account, confirmed[0].user_id) == (row["id"], "login", True, new["id"])
    assert "wx_code-1" not in caplog.text
    # a second confirmation of the same ticket → 409 wrong_state (the token still verifies)
    r = confirm(mp, info, t["ticket"])
    assert r.status_code == 409 and details(r) == {"reason": "wrong_state"}
    assert rows(settings, "SELECT COUNT(*) AS n FROM users")[0]["n"] == 2
    # the poll delivers the session: 201 (created), the User with providers, the Settings, the session cookie, the poll cookie cleared
    frozen_clock.advance(seconds=2)
    with caplog.at_level(logging.INFO, logger="wd"):
        r = poll(web, t["ticket"])
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "confirmed" and body["created"] is True and body["settings"]["timezone"] == "Asia/Shanghai"
    user = body["user"]
    assert user["id"] == new["id"] and user["providers"] == ["wechat_mini"] and user["needs_profile"] is True and user["has_password"] is False
    assert user["phone_masked"] is None and user["email"] is None and user["display_name"] == user["username"]
    cookies = [v.lower() for k, v in r.headers.multi_items() if k.lower() == "set-cookie"]
    session = next(c for c in cookies if c.startswith("wd_session="))
    assert "max-age=2592000" in session and "httponly" in session  # WD_SESSION_DAYS, a self session
    cleared = next(c for c in cookies if c.startswith("wd_wxt="))
    assert 'wd_wxt=""' in cleared and ("max-age=0" in cleared or "expires=" in cleared) and "path=/api/auth/wechat/ticket" in cleared
    assert rows(settings, "SELECT status, consumed_at FROM wechat_tickets WHERE id = ?", (row["id"],))[0] == {"status": "consumed", "consumed_at": "2026-10-14T00:00:22Z"}
    assert rows(settings, "SELECT last_login_at FROM users WHERE id = ?", (new["id"],))[0]["last_login_at"] == "2026-10-14T00:00:22Z"
    sessions = rows(settings, "SELECT * FROM sessions WHERE user_id = ?", (new["id"],))
    assert len(sessions) == 1 and sessions[0]["actor_user_id"] is None and sessions[0]["user_agent"] == MAC_CHROME
    logged = [rec for rec in caplog.records if getattr(rec, "event", None) == "wx_login"]
    assert len(logged) == 1 and logged[0].user_id == new["id"] and logged[0].created_account is True
    # the browser is signed in; a second poll finds nothing (consumed); the scan of a consumed ticket is a 404 too
    me = web.get("/api/auth/me").json()
    assert me["user"]["id"] == new["id"] and me["user"]["providers"] == ["wechat_mini"] and me["session"] == {"guardian": None, "gate_until": None}
    assert poll(web, t["ticket"]).status_code == 404
    assert scan(mp, "code-1", ticket=t["ticket"]).status_code == 404
    # the same WeChat signs in again: account 'bound', no new account, the identity's last_login_at refreshed, 200 not 201
    frozen_clock.advance(minutes=5)
    web2 = second_client(app)
    t2 = ticket(web2)
    info2 = scan(mp, "code-1", ticket=t2["ticket"]).json()
    assert info2["account"] == "bound"
    assert confirm(mp, info2, t2["ticket"]).json() == {"status": "confirmed", "created": False}
    r = poll(web2, t2["ticket"])
    assert r.status_code == 200 and r.json()["created"] is False and r.json()["user"]["id"] == new["id"]
    assert rows(settings, "SELECT COUNT(*) AS n FROM users")[0]["n"] == 2
    assert rows(settings, "SELECT last_login_at FROM identities WHERE subject = 'wx_code-1'")[0]["last_login_at"] == "2026-10-14T00:05:22Z"
    assert web2.get("/api/auth/me").json()["user"]["id"] == new["id"]
    assert len(rows(settings, "SELECT * FROM sessions WHERE user_id = ?", (new["id"],))) == 2


def test_invite_mode_consumes_the_code_at_the_confirmation(settings, frozen_clock):
    app = app_with(settings, frozen_clock, registration_mode="invite")
    with TestClient(app, base_url="http://testserver") as client:
        client.headers["X-WD-Request"] = "1"
        root = bootstrap(client)
        mp = second_client(app, user_agent=None)
        c = db.connect(settings.db_path)
        try:
            with db.tx(c):
                _, code, _ = security.create_invite(c, created_by=root["id"], max_uses=1, now=NOW)
        finally:
            c.close()
        # a ticket without a code is issued (an existing binding may sign in) but a NEW account is refused at the confirmation
        web = second_client(app)
        t = ticket(web)
        info = scan(mp, "code-1", ticket=t["ticket"]).json()
        assert info["account"] == "new"
        r = confirm(mp, info, t["ticket"])
        assert r.status_code == 403 and error_code(r) == "invalid_invite"
        assert poll(web, t["ticket"]).json()["status"] == "scanned"  # the row stayed scanned (the transaction rolled back)
        assert rows(settings, "SELECT COUNT(*) AS n FROM users")[0]["n"] == 1
        # a dead code is refused when the ticket is created; a live one is checked read-only and consumed by the confirmation only
        r = web.post("/api/auth/wechat/ticket", json={"kind": "login", "invite_code": "NOPE-NOPE-NOPE-NOPE"})
        assert r.status_code == 403 and error_code(r) == "invalid_invite"
        web2 = second_client(app)
        t2 = ticket(web2, invite_code=code.lower())
        assert rows(settings, "SELECT uses FROM invite_codes")[0]["uses"] == 0
        assert rows(settings, "SELECT invite_code FROM wechat_tickets WHERE ticket_hash = ?", (ticket_hash(t2["ticket"]),))[0]["invite_code"] == code
        info2 = scan(mp, "code-1", ticket=t2["ticket"]).json()
        assert confirm(mp, info2, t2["ticket"]).json() == {"status": "confirmed", "created": True}
        assert rows(settings, "SELECT uses FROM invite_codes")[0]["uses"] == 1
        r = poll(web2, t2["ticket"])
        assert r.status_code == 201 and r.json()["user"]["providers"] == ["wechat_mini"]
        # the code is spent: a third ticket carrying it is refused up front
        r = second_client(app).post("/api/auth/wechat/ticket", json={"kind": "login", "invite_code": code})
        assert r.status_code == 403 and error_code(r) == "invalid_invite"


def test_closed_mode_refuses_new_accounts_but_signs_bindings_in(settings, frozen_clock):
    app = app_with(settings, frozen_clock, registration_mode="closed")
    with TestClient(app, base_url="http://testserver") as client:
        client.headers["X-WD-Request"] = "1"
        root = bootstrap(client)
        r = client.post("/api/auth/register", json={"username": "bob", "password": PW})
        assert r.status_code == 403 and error_code(r) == "registration_closed"  # the site is closed for everyone
        mp = second_client(app, user_agent=None)
        web = second_client(app)
        t = ticket(web)  # still issued
        info = scan(mp, "code-1", ticket=t["ticket"]).json()
        assert info["account"] == "closed"
        r = confirm(mp, info, t["ticket"])
        assert r.status_code == 403 and error_code(r) == "registration_closed"
        assert rows(settings, "SELECT COUNT(*) AS n FROM users")[0]["n"] == 1
        # an existing binding signs in: bob (created by hand) holds wx_code-2
        c = db.connect(settings.db_path)
        try:
            with db.tx(c):
                bob = security.create_user(c, username="bob", password_hash=security.hash_password(PW), now=NOW, password_set_at=NOW_ISO)
                c.execute("INSERT INTO identities(user_id, provider, subject, verified_at, created_at) VALUES (?, 'wechat_mini', 'wx_code-2', ?, ?)", (bob, NOW_ISO, NOW_ISO))
        finally:
            c.close()
        web2, body = sign_in_with_wechat(app, mp, "code-2")
        assert body["created"] is False and body["user"]["id"] == bob and body["user"]["providers"] == ["wechat_mini"]
        assert root["id"] != bob


def test_admins_and_disabled_accounts_cannot_sign_in_through_wechat(client: TestClient, app, settings, wechat):
    root = bootstrap(client)
    bob = client.post("/api/auth/register", json={"username": "bob", "password": PW}).json()["user"]
    execute(settings, "INSERT INTO identities(user_id, provider, subject, verified_at, created_at) VALUES (?, 'wechat_mini', 'wx_admin', ?, ?)", (root["id"], NOW_ISO, NOW_ISO))
    execute(settings, "INSERT INTO identities(user_id, provider, subject, verified_at, created_at) VALUES (?, 'wechat_mini', 'wx_bob', ?, ?)", (bob["id"], NOW_ISO, NOW_ISO))
    execute(settings, "UPDATE users SET is_active = 0 WHERE id = ?", (bob["id"],))
    mp = second_client(app, user_agent=None)
    for js_code, code in (("admin", "password_required"), ("bob", "account_disabled")):
        web = second_client(app)
        t = ticket(web)
        info = scan(mp, js_code, ticket=t["ticket"]).json()
        assert info["account"] == "bound"
        r = confirm(mp, info, t["ticket"])
        assert r.status_code == 403 and error_code(r) == code, r.text
        assert poll(web, t["ticket"]).json()["status"] == "scanned"
    assert rows(settings, "SELECT COUNT(*) AS n FROM sessions")[0]["n"] == 2  # root's and bob's registration sessions only: the bridge issued none


def test_cancel_is_reported_once(client: TestClient, app, settings, wechat, caplog):
    bootstrap(client)
    web = second_client(app)
    mp = second_client(app, user_agent=None)
    t = ticket(web)
    info = scan(mp, "code-1", ticket=t["ticket"]).json()
    with caplog.at_level(logging.INFO, logger="wd"):
        r = confirm(mp, info, t["ticket"], accept=False)
    assert r.status_code == 200 and r.json() == {"status": "cancelled", "created": False}
    assert any(getattr(rec, "event", None) == "wx_cancelled" for rec in caplog.records)
    assert rows(settings, "SELECT status, pair_hash FROM wechat_tickets")[0] == {"status": "cancelled", "pair_hash": pair_hash(settings, t["pairing_code"])}
    assert confirm(mp, info, t["ticket"], accept=True).status_code == 409  # wrong_state: a cancelled ticket cannot be confirmed
    r = poll(web, t["ticket"])
    assert r.status_code == 200 and r.json() == {"status": "cancelled", "user": None, "settings": None, "created": None}
    assert 'wd_wxt=""' in r.headers["set-cookie"]
    assert poll(web, t["ticket"]).status_code == 404  # consumed
    assert rows(settings, "SELECT status FROM wechat_tickets")[0]["status"] == "consumed"
    assert rows(settings, "SELECT COUNT(*) AS n FROM users")[0]["n"] == 1


def test_expiry(client: TestClient, app, settings, wechat, frozen_clock):
    bootstrap(client)
    web = second_client(app)
    mp = second_client(app, user_agent=None)
    t = ticket(web)
    frozen_clock.advance(seconds=179)
    assert poll(web, t["ticket"]).json()["status"] == "pending"
    info = scan(mp, "code-1", ticket=t["ticket"]).json()
    assert info["expires_in_s"] == 1
    frozen_clock.advance(seconds=2)  # +181 s
    r = poll(web, t["ticket"])
    assert r.status_code == 200 and r.json() == {"status": "expired", "user": None, "settings": None, "created": None}
    assert scan(mp, "code-1", ticket=t["ticket"]).status_code == 404 and scan(mp, "code-1", pairing_code=t["pairing_code"]).status_code == 404
    assert web.get(t["qr_url"]).status_code == 404
    r = confirm(mp, info, t["ticket"])
    assert r.status_code == 404 and error_code(r) == "not_found"  # the token still verifies (5 min) but the ticket is gone
    # the pairing code of the expired ticket is free again (no live row holds its hash)
    assert rows(settings, "SELECT COUNT(*) AS n FROM wechat_tickets WHERE pair_hash = ? AND status IN ('pending','scanned') AND expires_at > ?", (pair_hash(settings, t["pairing_code"]), to_iso(frozen_clock.now_utc())))[0]["n"] == 0
    # an mp_token older than 5 minutes is refused before anything else
    t2 = ticket(second_client(app))
    info2 = scan(mp, "code-2", ticket=t2["ticket"]).json()
    frozen_clock.advance(seconds=301)
    r = confirm(mp, info2, t2["ticket"])
    assert r.status_code == 401 and error_code(r) == "invalid_identity_token"


# ------------------------------------------------------------------------------------------- bind
def test_bind_self_other_new_and_identity_taken(client: TestClient, app, settings, wechat, caplog):
    root = bootstrap(client)
    mp = second_client(app, user_agent=None)
    # a bind ticket needs a session
    r = second_client(app).post("/api/auth/wechat/ticket", json={"kind": "bind"})
    assert r.status_code == 401 and error_code(r) == "unauthorized"
    # root binds a WeChat: account 'new', the binder's display name shown in the mini program
    client.headers["User-Agent"] = MAC_CHROME
    t = ticket(client, kind="bind")
    row = rows(settings, "SELECT * FROM wechat_tickets WHERE ticket_hash = ?", (ticket_hash(t["ticket"]),))[0]
    assert (row["kind"], row["bind_user_id"]) == ("bind", root["id"])
    info = scan(mp, "code-1", ticket=t["ticket"]).json()
    assert (info["kind"], info["account"], info["bind_display_name"]) == ("bind", "new", "root")
    with caplog.at_level(logging.INFO, logger="wd"):
        assert confirm(mp, info, t["ticket"]).json() == {"status": "confirmed", "created": False}
        r = poll(client, t["ticket"])
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "confirmed" and r.json()["settings"] is None and r.json()["created"] is False
    assert r.json()["user"]["id"] == root["id"] and r.json()["user"]["providers"] == ["wechat_mini"]
    assert not any(v.lower().startswith("wd_session=") for k, v in r.headers.multi_items() if k.lower() == "set-cookie")  # a binding issues no session
    assert any(getattr(rec, "event", None) == "wx_bound" and rec.user_id == root["id"] for rec in caplog.records)
    assert client.get("/api/auth/me").json()["user"]["providers"] == ["wechat_mini"]
    identity = rows(settings, "SELECT * FROM identities")[0]
    assert (identity["user_id"], identity["provider"], identity["subject"]) == (root["id"], "wechat_mini", "wx_code-1")
    # the same WeChat again: 'self' → idempotent; a second WeChat on the same account → identity_taken
    t2 = ticket(client, kind="bind")
    info2 = scan(mp, "code-1", ticket=t2["ticket"]).json()
    assert info2["account"] == "self"
    assert confirm(mp, info2, t2["ticket"]).status_code == 200 and poll(client, t2["ticket"]).json()["user"]["providers"] == ["wechat_mini"]
    t3 = ticket(client, kind="bind")
    info3 = scan(mp, "code-9", ticket=t3["ticket"]).json()
    assert info3["account"] == "new"
    r = confirm(mp, info3, t3["ticket"])
    assert r.status_code == 409 and error_code(r) == "identity_taken"
    assert r.json()["error"]["message"] == third_party.IDENTITY_TAKEN_ZH["wechat_mini"] == "该微信已绑定其他账号"  # not the catalogue's phone wording
    assert rows(settings, "SELECT COUNT(*) AS n FROM identities")[0]["n"] == 1
    # another account cannot take root's WeChat: 'other' → identity_taken
    bob_client = second_client(app)
    assert bob_client.post("/api/auth/register", json={"username": "bob", "password": PW}).status_code == 201
    t4 = ticket(bob_client, kind="bind")
    info4 = scan(mp, "code-1", pairing_code=t4["pairing_code"]).json()
    assert (info4["account"], info4["bind_display_name"]) == ("other", "bob")
    r = confirm(mp, info4, t4["ticket"])
    assert r.status_code == 409 and error_code(r) == "identity_taken" and r.json()["error"]["message"] == "该微信已绑定其他账号"
    assert poll(bob_client, t4["ticket"]).json()["status"] == "scanned"
    assert bob_client.get("/api/auth/me").json()["user"]["providers"] == []
    # a child never binds (the restriction list); a login ticket with a session is allowed
    bob = bob_client.get("/api/auth/me").json()["user"]
    execute(settings, "UPDATE users SET guardian_user_id = ? WHERE id = ?", (root["id"], bob["id"]))
    r = bob_client.post("/api/auth/wechat/ticket", json={"kind": "bind"})
    assert r.status_code == 403 and error_code(r) == "guardian_required"
    assert bob_client.post("/api/auth/wechat/ticket", json={"kind": "login"}).status_code == 201


# ------------------------------------------------------------------------------- 89 for a third-party-only account
def test_profile_of_a_third_party_only_account_requires_a_password(client: TestClient, app, settings, wechat):
    bootstrap(client)
    mp = second_client(app, user_agent=None)
    web, body = sign_in_with_wechat(app, mp, "code-1")
    assert body["created"] is True and body["user"]["needs_profile"] is True
    r = web.post("/api/account/profile", json={"display_name": "微信用户", "age_band": "adult"})
    assert r.status_code == 400 and error_code(r) == "validation_error"
    assert details(r)["fields"] == {"password": third_party.THIRD_PARTY_PASSWORD_ZH} and r.json()["error"]["message"] == third_party.THIRD_PARTY_PASSWORD_ZH
    # with a phone bound (another way in) the password is optional again
    uid = body["user"]["id"]
    execute(settings, "INSERT INTO identities(user_id, provider, subject, verified_at, created_at) VALUES (?, 'phone', '+8613800138000', ?, ?)", (uid, NOW_ISO, NOW_ISO))
    web2, body2 = sign_in_with_wechat(app, mp, "code-2")
    r = web2.post("/api/account/profile", json={"display_name": "微信用户二", "age_band": "adult"})
    assert r.status_code == 400  # still third-party-only
    r = web.post("/api/account/profile", json={"display_name": "微信用户", "age_band": "adult"})
    assert r.status_code == 200 and r.json()["user"]["phone_masked"] == "138****8000" and r.json()["user"]["has_password"] is False
    # the password path for the second account
    r = web2.post("/api/account/profile", json={"display_name": "微信用户二", "age_band": "adult", "password": PW})
    assert r.status_code == 200 and r.json()["user"]["has_password"] is True and r.json()["user"]["providers"] == ["wechat_mini"]
    # the guardian rule stays first (its own message)
    web3, _ = sign_in_with_wechat(app, mp, "code-3")
    r = web3.post("/api/account/profile", json={"display_name": "家长", "account_kind": "guardian", "age_band": "adult"})
    assert r.status_code == 400 and details(r)["fields"] == {"password": "家长账号需要设置密码"}


# -------------------------------------------------------------------------------- rate limits / me / gc
def test_ticket_rate_limit_per_ip(client: TestClient, app, settings, wechat, frozen_clock):
    bootstrap(client)
    web = second_client(app)
    for _ in range(30):  # a classroom behind one NAT opening the sheet together
        assert web.post("/api/auth/wechat/ticket", json={"kind": "login"}).status_code == 201
    r = web.post("/api/auth/wechat/ticket", json={"kind": "login"})
    assert r.status_code == 429 and error_code(r) == "rate_limited" and details(r)["retry_after_s"] == 60 and r.headers["retry-after"] == "60"
    assert rows(settings, "SELECT COUNT(*) AS n FROM wechat_tickets")[0]["n"] == 30
    frozen_clock.advance(seconds=60)
    assert web.post("/api/auth/wechat/ticket", json={"kind": "login"}).status_code == 201
    keys = {r["key"] for r in rows(settings, "SELECT key FROM auth_throttle")}
    assert {"wx_ticket:ip:testclient:m", "wx_ticket:ip:testclient:h"} <= keys
    # the hourly window: 300 tickets within the hour (ten minutes of 30, across minute boundaries) → the 301st → 429 until the hour turns
    for minute in range(1, 10):
        for _ in range(29 if minute == 1 else 30):
            assert web.post("/api/auth/wechat/ticket", json={"kind": "login"}).status_code == 201
        frozen_clock.advance(seconds=60)
    assert rows(settings, "SELECT COUNT(*) AS n FROM wechat_tickets")[0]["n"] == 300
    r = web.post("/api/auth/wechat/ticket", json={"kind": "login"})  # a fresh minute window, the hour window full
    assert r.status_code == 429 and details(r)["retry_after_s"] == 3000 and r.headers["retry-after"] == "3000"  # 3600 − 600 s elapsed
    assert rows(settings, "SELECT COUNT(*) AS n FROM wechat_tickets")[0]["n"] == 300
    frozen_clock.advance(seconds=3000)
    assert web.post("/api/auth/wechat/ticket", json={"kind": "login"}).status_code == 201
    # the scan window per openid: the 11th scan of one WeChat within a minute → 429 (the IP window is 600: a flood brake only)
    mp = second_client(app, user_agent=None)
    tickets = [ticket(second_client(app)) for _ in range(5)]
    for _ in range(2):
        for t in tickets:
            assert scan(mp, "code-1", ticket=t["ticket"]).status_code == 200
    r = scan(mp, "code-1", ticket=tickets[0]["ticket"])
    assert r.status_code == 429 and error_code(r) == "rate_limited"
    assert scan(mp, "code-2", ticket=tickets[1]["ticket"]).status_code == 409  # another WeChat is not throttled (scanned_elsewhere instead)
    assert not any("wx_code-1" in k for k in {r["key"] for r in rows(settings, "SELECT key FROM auth_throttle")})  # the openid is hashed in the key


def test_poll_window_counts_113_only_and_never_hides_the_picture(client: TestClient, app, settings, wechat, frozen_clock):
    """``wx_poll:ip`` 1200/min on 113 alone: thirty sheets behind one NAT polling every 2 s; 114 is not counted and still answers once the
    window is spent (a 429 on the <img> would hide the 小程序码 for the rest of the ticket's life)."""
    bootstrap(client)
    web = second_client(app)
    t = ticket(web)
    for _ in range(3):
        assert web.get(t["qr_url"]).status_code == 200  # not counted
    for _ in range(1200):
        assert poll(web, t["ticket"]).status_code == 200
    r = poll(web, t["ticket"])
    assert r.status_code == 429 and error_code(r) == "rate_limited" and details(r)["retry_after_s"] == 60 and r.headers["retry-after"] == "60"
    assert web.get(t["qr_url"]).status_code == 200  # the picture is never hidden by the poll window
    throttle = {r["key"]: r["count"] for r in rows(settings, "SELECT key, count FROM auth_throttle")}
    assert throttle["wx_poll:ip:testclient"] == 1200 and not any(k.startswith("wx_poll") and k != "wx_poll:ip:testclient" for k in throttle)
    frozen_clock.advance(seconds=60)
    assert poll(web, t["ticket"]).status_code == 200


def test_scan_and_confirm_ip_windows_are_flood_brakes(client: TestClient, app, settings, wechat, frozen_clock):
    """Behind the mainland relay every mini-program request arrives from ONE client IP, so ``wx_scan:ip`` / ``wx_confirm:ip`` are site-wide
    caps: 600/min each, counted before anything else (the 601st scan never reaches WeChat), a minute later open again."""
    bootstrap(client)
    mp = second_client(app, user_agent=None)
    web = second_client(app)
    t = ticket(web)
    for i in range(600):  # 600 different WeChat users (distinct openids) naming an unknown ticket → 404 each, all counted on the IP
        assert scan(mp, f"code-{i}", ticket="b" * 26).status_code == 404
    calls = len(wechat.calls)
    r = scan(mp, "code-real", ticket=t["ticket"])
    assert r.status_code == 429 and error_code(r) == "rate_limited" and details(r)["retry_after_s"] == 60
    assert len(wechat.calls) == calls  # refused before code2Session
    assert poll(web, t["ticket"]).json()["status"] == "pending"
    frozen_clock.advance(seconds=60)
    r = scan(mp, "code-real", ticket=t["ticket"])
    assert r.status_code == 200, r.text
    info = r.json()
    for _ in range(600):  # 600 confirmations naming an unknown ticket → 404 each, counted on the IP before the row lookup
        assert mp.post("/api/auth/wechat/confirm", json={"mp_token": "1.x", "ticket": "c" * 26, "accept": True}).status_code == 404
    r = confirm(mp, info, t["ticket"])
    assert r.status_code == 429 and error_code(r) == "rate_limited"  # a valid proof is refused too: the IP window comes first
    assert rows(settings, "SELECT status FROM wechat_tickets WHERE ticket_hash = ?", (ticket_hash(t["ticket"]),))[0]["status"] == "scanned"
    frozen_clock.advance(seconds=60)
    assert confirm(mp, info, t["ticket"]).json() == {"status": "confirmed", "created": True}
    keys = {r["key"] for r in rows(settings, "SELECT key FROM auth_throttle")}
    assert {"wx_scan:ip:testclient", "wx_confirm:ip:testclient"} <= keys


def test_confirm_window_per_openid_is_the_brute_force_brake(client: TestClient, app, settings, wechat, frozen_clock):
    """``wx_confirm:openid`` 20/min on the ticket row's openid, counted BEFORE the proof is checked: junk tokens against a known ticket spend
    the scanner's bucket (then even the valid proof waits a minute), another WeChat user's ticket is untouched, the key carries a hash."""
    bootstrap(client)
    mp = second_client(app, user_agent=None)
    web, web2 = second_client(app), second_client(app)
    t, t2 = ticket(web), ticket(web2)
    info = scan(mp, "code-1", ticket=t["ticket"]).json()
    info2 = scan(mp, "code-2", ticket=t2["ticket"]).json()
    for _ in range(20):
        r = mp.post("/api/auth/wechat/confirm", json={"mp_token": "1.x", "ticket": t["ticket"], "accept": True})
        assert r.status_code == 401 and error_code(r) == "invalid_identity_token"
    r = confirm(mp, info, t["ticket"])
    assert r.status_code == 429 and error_code(r) == "rate_limited" and details(r)["retry_after_s"] == 60
    assert rows(settings, "SELECT status FROM wechat_tickets WHERE ticket_hash = ?", (ticket_hash(t["ticket"]),))[0]["status"] == "scanned"
    assert confirm(mp, info2, t2["ticket"]).json() == {"status": "confirmed", "created": True}  # another scanner: not throttled
    keys = {r["key"] for r in rows(settings, "SELECT key FROM auth_throttle")}
    assert any(k.startswith("wx_confirm:openid:") for k in keys) and not any("wx_code-1" in k for k in keys)
    assert bridge.openid_key("wx_code-1", scope="confirm") in keys
    frozen_clock.advance(seconds=60)
    assert confirm(mp, info, t["ticket"]).json() == {"status": "confirmed", "created": True}
    # a pending ticket (nobody scanned it) spends no bucket: there is no openid to count against
    t3 = ticket(second_client(app))
    assert mp.post("/api/auth/wechat/confirm", json={"mp_token": "1.x", "ticket": t3["ticket"], "accept": True}).status_code == 401
    assert len([k for k in {r["key"] for r in rows(settings, "SELECT key FROM auth_throttle")} if k.startswith("wx_confirm:openid:")]) == 2


def test_confirmed_or_cancelled_result_is_delivered_only_within_the_grace(client: TestClient, app, settings, wechat, frozen_clock):
    """A confirmation at +179 s reaches a poll at +181 s (expires_at + 60 s has not passed); a poll at +241 s finds the result void: ``expired``,
    the row consumed, no session, the next poll a 404 — a captured ticket + poll cookie never mints a session a day later. A cancelled
    result expires the same way (the boundary expires_at + 60 s itself is already void)."""
    bootstrap(client)
    mp = second_client(app, user_agent=None)
    web = second_client(app)
    t = ticket(web)
    frozen_clock.advance(seconds=179)
    info = scan(mp, "code-1", ticket=t["ticket"]).json()
    assert confirm(mp, info, t["ticket"]).json() == {"status": "confirmed", "created": True}
    frozen_clock.advance(seconds=2)  # +181 s
    r = poll(web, t["ticket"])
    assert r.status_code == 201 and r.json()["status"] == "confirmed" and r.json()["created"] is True
    assert web.get("/api/auth/me").status_code == 200
    uid = r.json()["user"]["id"]
    # the same WeChat, a new ticket: confirmed at +179 s, first polled at +241 s
    web2 = second_client(app)
    t2 = ticket(web2)
    frozen_clock.advance(seconds=179)
    info2 = scan(mp, "code-1", ticket=t2["ticket"]).json()
    assert info2["account"] == "bound" and confirm(mp, info2, t2["ticket"]).json() == {"status": "confirmed", "created": False}
    frozen_clock.advance(seconds=62)  # +241 s
    r = poll(web2, t2["ticket"])
    assert r.status_code == 200 and r.json() == {"status": "expired", "user": None, "settings": None, "created": None}
    row = rows(settings, "SELECT * FROM wechat_tickets WHERE ticket_hash = ?", (ticket_hash(t2["ticket"]),))[0]
    assert (row["status"], row["consumed_at"], row["user_id"]) == ("consumed", to_iso(frozen_clock.now_utc()), uid)
    assert len(rows(settings, "SELECT * FROM sessions WHERE user_id = ?", (uid,))) == 1  # only the first login's session
    assert web2.get("/api/auth/me").status_code == 401
    assert poll(web2, t2["ticket"]).status_code == 404  # consumed: nothing can deliver this result later
    assert confirm(mp, info2, t2["ticket"]).status_code == 404  # the proof still verifies (5 min) but the ticket is expired: 404, as on the scene path
    # a cancelled result: void at exactly expires_at + 60 s
    web3 = second_client(app)
    t3 = ticket(web3)
    frozen_clock.advance(seconds=10)
    info3 = scan(mp, "code-1", ticket=t3["ticket"]).json()
    assert confirm(mp, info3, t3["ticket"], accept=False).json() == {"status": "cancelled", "created": False}
    frozen_clock.advance(seconds=230)  # +240 s
    assert poll(web3, t3["ticket"]).json()["status"] == "expired"
    assert rows(settings, "SELECT status FROM wechat_tickets WHERE ticket_hash = ?", (ticket_hash(t3["ticket"]),))[0]["status"] == "consumed"
    assert poll(web3, t3["ticket"]).status_code == 404


def test_confirmed_login_ticket_replaces_the_browsers_previous_session(client: TestClient, app, settings, wechat):
    """A login ticket from a signed-in tab is allowed; when its confirmation signs the browser in, the browser's previous ``wd_session`` is
    deleted (the OAuth-finish rule), not left alive until it expires."""
    bootstrap(client)
    mp = second_client(app, user_agent=None)
    bob_client = second_client(app)
    bob = bob_client.post("/api/auth/register", json={"username": "bob", "password": PW}).json()["user"]
    previous = hash_token(bob_client.cookies.get("wd_session"))
    assert len(rows(settings, "SELECT * FROM sessions WHERE token_hash = ?", (previous,))) == 1
    t = ticket(bob_client)
    info = scan(mp, "code-1", ticket=t["ticket"]).json()
    assert confirm(mp, info, t["ticket"]).json() == {"status": "confirmed", "created": True}
    r = poll(bob_client, t["ticket"])
    assert r.status_code == 201, r.text
    new_uid = r.json()["user"]["id"]
    assert new_uid != bob["id"]
    assert rows(settings, "SELECT * FROM sessions WHERE token_hash = ?", (previous,)) == []  # replaced
    assert rows(settings, "SELECT * FROM sessions WHERE user_id = ?", (bob["id"],)) == []
    assert len(rows(settings, "SELECT * FROM sessions WHERE user_id = ?", (new_uid,))) == 1
    assert bob_client.get("/api/auth/me").json()["user"]["id"] == new_uid


def test_account_disabled_after_the_confirmation_consumes_the_ticket_before_the_403(client: TestClient, app, settings, wechat):
    """Disabled between 116 and 113: the poll consumes the row and COMMITS, then answers 403 ``account_disabled`` without a session; the next
    poll is a 404, so the SPA stops and the result can never be delivered later."""
    bootstrap(client)
    mp = second_client(app, user_agent=None)
    web = second_client(app)
    t = ticket(web)
    info = scan(mp, "code-1", ticket=t["ticket"]).json()
    assert confirm(mp, info, t["ticket"]).status_code == 200
    uid = rows(settings, "SELECT user_id FROM wechat_tickets")[0]["user_id"]
    execute(settings, "UPDATE users SET is_active = 0 WHERE id = ?", (uid,))
    r = poll(web, t["ticket"])
    assert r.status_code == 403 and error_code(r) == "account_disabled"
    assert not any(v.lower().startswith("wd_session=") for k, v in r.headers.multi_items() if k.lower() == "set-cookie")
    assert rows(settings, "SELECT status FROM wechat_tickets")[0]["status"] == "consumed"  # committed before the 403
    assert rows(settings, "SELECT * FROM sessions WHERE user_id = ?", (uid,)) == []
    assert poll(web, t["ticket"]).status_code == 404
    assert web.get("/api/auth/me").status_code == 401


def test_second_confirmation_by_pairing_code_answers_wrong_state_like_the_scene_path(client: TestClient, app, settings, wechat, monkeypatch: pytest.MonkeyPatch):
    """The pairing-code path keeps ``pair_hash`` on the finished row, so a double tap — before or after the web consumed the ticket — answers
    409 ``wrong_state`` exactly like the scene path (not 404 「二维码已过期」); when a live ticket re-draws a finished ticket's code, each
    mini program's ``mp_token`` picks its own row."""
    bootstrap(client)
    mp = second_client(app, user_agent=None)
    web = second_client(app)
    t = ticket(web)
    code = t["pairing_code"]
    info = scan(mp, "code-1", pairing_code=code).json()

    def by_code(token: str, accept: bool = True):
        return mp.post("/api/auth/wechat/confirm", json={"mp_token": token, "ticket": code, "accept": accept})

    assert by_code(info["mp_token"]).json() == {"status": "confirmed", "created": True}
    r = by_code(info["mp_token"])  # a double tap
    assert r.status_code == 409 and error_code(r) == "invalid_transition" and details(r) == {"reason": "wrong_state"}
    assert rows(settings, "SELECT pair_hash FROM wechat_tickets")[0]["pair_hash"] == pair_hash(settings, code)
    assert poll(web, t["ticket"]).status_code == 201  # consumed by the web
    for accept in (True, False):
        r = by_code(info["mp_token"], accept)
        assert r.status_code == 409 and details(r) == {"reason": "wrong_state"}  # still found after the consume: not a 404
    assert rows(settings, "SELECT pair_hash FROM wechat_tickets")[0]["pair_hash"] == pair_hash(settings, code)  # until the GC
    # the finished ticket's code is free (unique_pairing_code looks at live rows only) and gets re-drawn by a new ticket
    monkeypatch.setattr(bridge, "new_pairing_code", lambda: code)
    web2 = second_client(app)
    t2 = ticket(web2)
    assert t2["pairing_code"] == code
    info2 = scan(mp, "code-2", pairing_code=code).json()  # 115 resolves the LIVE holder only
    assert rows(settings, "SELECT openid FROM wechat_tickets WHERE ticket_hash = ?", (ticket_hash(t2["ticket"]),))[0]["openid"] == "wx_code-2"
    r = by_code(info["mp_token"])  # the first mini program's stale tap still names ITS row: wrong_state, never the live ticket
    assert r.status_code == 409 and details(r) == {"reason": "wrong_state"}
    assert rows(settings, "SELECT status FROM wechat_tickets WHERE ticket_hash = ?", (ticket_hash(t2["ticket"]),))[0]["status"] == "scanned"
    assert by_code(info2["mp_token"]).json() == {"status": "confirmed", "created": True}
    r = poll(web2, t2["ticket"])
    assert r.status_code == 201 and r.json()["user"]["id"] != poll_user_id(settings, t["ticket"])
    assert rows(settings, "SELECT COUNT(*) AS n FROM wechat_tickets WHERE pair_hash = ?", (pair_hash(settings, code),))[0]["n"] == 2


def poll_user_id(settings, ticket_value: str) -> int:
    return int(rows(settings, "SELECT user_id FROM wechat_tickets WHERE ticket_hash = ?", (ticket_hash(ticket_value),))[0]["user_id"])


def test_me_providers_admin_list_and_hourly_gc(client: TestClient, app, settings, wechat, frozen_clock):
    root = bootstrap(client)
    mp = second_client(app, user_agent=None)
    web, body = sign_in_with_wechat(app, mp, "code-1")
    uid = body["user"]["id"]
    execute(settings, "INSERT INTO identities(user_id, provider, subject, verified_at, created_at) VALUES (?, 'apple', 'sub-1', ?, ?)", (uid, NOW_ISO, NOW_ISO))
    assert web.get("/api/auth/me").json()["user"]["providers"] == ["apple", "wechat_mini"]  # sorted
    listed = {u["id"]: u for u in client.get("/api/admin/users").json()["items"]}
    assert listed[uid]["providers"] == ["apple", "wechat_mini"] and listed[root["id"]]["providers"] == []
    execute(settings, "UPDATE identities SET disputed_at = ? WHERE provider = 'apple'", (NOW_ISO,))
    assert web.get("/api/auth/me").json()["user"]["providers"] == ["wechat_mini"]  # a disputed row stops counting
    # the hourly GC: the consumed ticket stays a day as the audit trail, then goes
    assert rows(settings, "SELECT status FROM wechat_tickets")[0]["status"] == "consumed"
    c = db.connect(settings.db_path)
    try:
        assert scheduler.hourly_gc(c, frozen_clock.now_utc() + timedelta(hours=23), boot_id="test") is True
        assert c.execute("SELECT COUNT(*) FROM wechat_tickets").fetchone()[0] == 1
        assert scheduler.hourly_gc(c, frozen_clock.now_utc() + timedelta(hours=25), boot_id="test") is True
        assert c.execute("SELECT COUNT(*) FROM wechat_tickets").fetchone()[0] == 0
    finally:
        c.close()
