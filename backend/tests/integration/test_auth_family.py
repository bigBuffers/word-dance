"""Endpoints 104–107 (API.md §3.2, slice 1-B): switching the device into a child's account (the guardian's session replaced, other
devices untouched), switching back through the 家长门 (PIN / password / code from 106, the lockout, the gate stamp on the new
session, not_switched), the child-device sign-in with an 8-digit code (90-day cookie and row, single use, the failures-only IP
window, set-free / disabled children) and the never-shortening slide of deps.current_user."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from wd import db, security
from wd.delivery.mailer import RecordingMailer
from wd.delivery.sms import RecordingSmsSender

PW = "Correct-Horse-7"
KID_PW = "Kid-Pass-Word-9"
NOW_ISO = "2026-10-14T00:00:00Z"
PHONE = "13800138000"
E164 = "+8613800138000"
OTHER = "13900139000"
PIN = "135790"
PIN2 = "246813"
CHILD_MAX_AGE = 90 * 86400


@pytest.fixture(autouse=True)
def fast_bcrypt(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(security, "BCRYPT_ROUNDS", 4)


@pytest.fixture
def sms(app) -> RecordingSmsSender:
    sender = RecordingSmsSender()
    app.state.sms = sender
    return sender


@pytest.fixture
def mailer(app) -> RecordingMailer:
    m = RecordingMailer()
    app.state.mailer = m
    return m


def second_client(app) -> TestClient:
    c = TestClient(app, base_url="http://testserver")
    c.headers["X-WD-Request"] = "1"
    return c


def bootstrap(client: TestClient, username: str = "root") -> dict:
    r = client.post("/api/auth/register", json={"username": username, "password": PW})
    assert r.status_code == 201, r.text
    return r.json()["user"]


def error_code(r) -> str:
    return r.json()["error"]["code"]


def details(r) -> dict:
    return r.json()["error"].get("details") or {}


def count(settings, table: str, where: str = "1=1", params=()) -> int:
    c = db.connect(settings.db_path)
    try:
        return int(c.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}", params).fetchone()[0])
    finally:
        c.close()


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


def session_cookies(response) -> list[str]:
    return [v for v in response.headers.get_list("set-cookie") if v.lower().startswith("wd_session=")]


def code_account(c: TestClient, sms: RecordingSmsSender, target: str = PHONE) -> dict:
    assert c.post("/api/auth/code", json={"channel": "phone", "target": target, "purpose": "login", "consent": True}).status_code == 202
    r = c.post("/api/auth/code/login", json={"channel": "phone", "target": target, "code": sms.sent[-1].code})
    assert r.status_code == 201, r.text
    return r.json()["user"]


def promote(settings, user_id: int) -> None:
    """Endpoint 89 writes ``account_kind`` once B1b lands (make_guardian sends it); a no-op afterwards (see test_guardian.promote)."""
    execute(settings, "UPDATE users SET account_kind = 'guardian', age_band = COALESCE(age_band, 'adult'), updated_at = ? WHERE id = ?", (NOW_ISO, user_id))


def make_guardian(app, settings, sms: RecordingSmsSender, *, phone: str = PHONE, display_name: str = "妈妈") -> tuple[TestClient, dict]:
    """A READY guardian with a PIN and one child 小明 (placeholder username, no password); the gate stamp is fresh."""
    c = second_client(app)
    user = code_account(c, sms, phone)
    r = c.post("/api/account/profile", json={"display_name": display_name, "account_kind": "guardian", "age_band": "adult", "password": PW})
    assert r.status_code == 200, r.text
    promote(settings, int(user["id"]))
    assert c.post("/api/guardian/gate", json={"password": PW}).status_code == 200
    r = c.post("/api/guardian/children", json={"display_name": "小明", "pin": PIN})
    assert r.status_code == 201, r.text
    me = c.get("/api/auth/me").json()["user"]
    return c, {**me, "child_id": r.json()["child"]["id"]}


def session_rows(settings, user_id: int) -> list[dict]:
    return rows(settings, "SELECT token_hash, user_id, actor_user_id, expires_at, guardian_gate_at FROM sessions WHERE user_id = ? ORDER BY created_at, token_hash", (user_id,))


# ------------------------------------------------------------------------------------------------ 104
def test_switch_replaces_the_devices_session(client: TestClient, app, settings, sms):
    bootstrap(client)
    tablet, mum = make_guardian(app, settings, sms)
    kid = mum["child_id"]
    laptop = second_client(app)  # the guardian's other device: a password login by phone number
    assert laptop.post("/api/auth/login", json={"username": PHONE, "password": PW}).status_code == 200
    assert count(settings, "sessions", "user_id = ?", (mum["id"],)) == 2
    old_token = tablet.cookies.get("wd_session")
    r = tablet.post(f"/api/auth/switch/{kid}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"user", "settings"} and (body["user"]["id"], body["user"]["is_child"], body["user"]["account_kind"], body["user"]["display_name"], body["user"]["age_band"]) == (kid, True, "learner", "小明", "u14")
    assert body["user"]["needs_profile_prompt"] is False and body["settings"]["timezone"] == "Asia/Shanghai"
    (cookie,) = session_cookies(r)
    assert "max-age=2592000" in cookie.lower() and "httponly" in cookie.lower()  # the guardian's session days, not 90
    new_token = tablet.cookies.get("wd_session")
    assert new_token and new_token != old_token
    # the device's guardian session is gone, the child session names the guardian; the laptop keeps the guardian
    assert [s["token_hash"] for s in session_rows(settings, mum["id"])] != [] and all(s["token_hash"] != security.hash_token(old_token) for s in session_rows(settings, mum["id"]))
    child_sessions = session_rows(settings, kid)
    assert len(child_sessions) == 1 and child_sessions[0]["actor_user_id"] == mum["id"] and child_sessions[0]["token_hash"] == security.hash_token(new_token)
    assert rows(settings, "SELECT last_login_at FROM users WHERE id = ?", (kid,))[0]["last_login_at"] == NOW_ISO
    replay = second_client(app)
    replay.cookies.set("wd_session", old_token)
    assert replay.get("/api/auth/me").status_code == 401
    me = tablet.get("/api/auth/me")
    assert me.status_code == 200 and me.json()["user"]["id"] == kid and me.json()["user"]["is_child"] is True
    assert laptop.get("/api/auth/me").json()["user"]["id"] == mum["id"]
    # a switched child session never satisfies G, and cannot switch again (104 is on the §1 restriction list: guardian_required)
    r = tablet.get("/api/guardian/children")
    assert r.status_code == 403 and error_code(r) == "forbidden"
    r = tablet.post(f"/api/auth/switch/{kid}")
    assert r.status_code == 403 and error_code(r) == "guardian_required"
    # learning stays open to the child (the restriction list is the account routes')
    assert tablet.get("/api/settings").status_code == 200
    # the laptop: another guardian's child → 404; a disabled child → 403; a learner → 403
    dad, dad_user = make_guardian(app, settings, sms, phone=OTHER, display_name="爸爸")
    r = laptop.post(f"/api/auth/switch/{dad_user['child_id']}")
    assert r.status_code == 404 and error_code(r) == "not_found"
    r = laptop.post("/api/auth/switch/999")
    assert r.status_code == 404
    execute(settings, "UPDATE users SET is_active = 0 WHERE id = ?", (kid,))
    r = laptop.post(f"/api/auth/switch/{kid}")
    assert r.status_code == 403 and error_code(r) == "account_disabled"
    execute(settings, "UPDATE users SET is_active = 1 WHERE id = ?", (kid,))
    r = client.post(f"/api/auth/switch/{kid}")
    assert r.status_code == 403 and error_code(r) == "forbidden"
    assert second_client(app).post(f"/api/auth/switch/{kid}").status_code == 401
    # readiness: a guardian whose phone is gone cannot switch
    execute(settings, "DELETE FROM identities WHERE user_id = ?", (mum["id"],))
    r = laptop.post(f"/api/auth/switch/{kid}")
    assert r.status_code == 409 and error_code(r) == "guardian_factors_required" and details(r) == {"missing": ["phone"]}
    assert count(settings, "sessions", "user_id = ?", (mum["id"],)) == 1  # nothing changed on the laptop


# ------------------------------------------------------------------------------------------ 105 / 106
def test_switch_back_with_pin_password_and_code(client: TestClient, app, settings, sms, mailer, frozen_clock):
    bootstrap(client)
    tablet, mum = make_guardian(app, settings, sms)
    kid = mum["child_id"]
    # a self session is not switched
    for path, body in (("/api/auth/switch/back", {"pin": PIN}), ("/api/auth/switch/code", {"channel": "phone"})):
        r = tablet.post(path, json=body)
        assert r.status_code == 409 and error_code(r) == "invalid_transition" and details(r) == {"reason": "not_switched"}, path
    assert tablet.post(f"/api/auth/switch/{kid}").status_code == 200
    # exactly one factor; a wrong PIN
    for body in ({}, {"pin": PIN, "password": PW}):
        r = tablet.post("/api/auth/switch/back", json=body)
        assert r.status_code == 400 and error_code(r) == "validation_error" and details(r) == {"fields": {"body": "PIN、密码和验证码必须且只能提供一个"}}
    r = tablet.post("/api/auth/switch/back", json={"pin": PIN2})
    assert r.status_code == 401 and error_code(r) == "invalid_pin"
    assert rows(settings, "SELECT count FROM auth_throttle WHERE key = ?", (f"gate:user:{mum['id']}",))[0]["count"] == 1
    child_token = tablet.cookies.get("wd_session")
    # the PIN: back to the guardian, the child session gone, the new session carries the gate stamp
    frozen_clock.advance(minutes=1)
    r = tablet.post("/api/auth/switch/back", json={"pin": PIN})
    assert r.status_code == 200, r.text
    assert (r.json()["user"]["id"], r.json()["user"]["account_kind"], r.json()["user"]["is_child"]) == (mum["id"], "guardian", False)
    assert len(session_cookies(r)) == 1 and tablet.cookies.get("wd_session") != child_token
    assert session_rows(settings, kid) == []
    (guardian_session,) = session_rows(settings, mum["id"])
    assert guardian_session["actor_user_id"] is None and guardian_session["guardian_gate_at"] == "2026-10-14T00:01:00Z"
    assert rows(settings, "SELECT last_login_at FROM users WHERE id = ?", (mum["id"],))[0]["last_login_at"] == "2026-10-14T00:01:00Z"
    assert count(settings, "auth_throttle", "key = ?", (f"gate:user:{mum['id']}",)) == 0  # cleared by the success
    r = tablet.get("/api/guardian/children")
    assert r.status_code == 200 and r.json()["gate_until"] == "2026-10-14T00:11:00Z"  # no second prompt on 我的孩子
    replay = second_client(app)
    replay.cookies.set("wd_session", child_token)
    assert replay.get("/api/auth/me").status_code == 401
    # the password
    assert tablet.post(f"/api/auth/switch/{kid}").status_code == 200
    r = tablet.post("/api/auth/switch/back", json={"password": "wrong-password-1"})
    assert r.status_code == 401 and error_code(r) == "invalid_credentials"
    r = tablet.post("/api/auth/switch/back", json={"password": PW})
    assert r.status_code == 200 and r.json()["user"]["id"] == mum["id"]
    # a reauth code to the guardian's phone (106) — the child session asks for it
    assert tablet.post(f"/api/auth/switch/{kid}").status_code == 200
    frozen_clock.advance(minutes=1)
    r = tablet.post("/api/auth/switch/code", json={"channel": "phone"})
    assert r.status_code == 202 and r.json() == {"sent": True, "expires_in_s": 600}
    assert sms.sent[-1].to == E164 and sms.sent[-1].template == "100005"
    code_row = rows(settings, "SELECT purpose, user_id FROM login_codes ORDER BY id DESC LIMIT 1")[0]
    assert code_row == {"purpose": "reauth", "user_id": mum["id"]}  # the code belongs to the guardian
    code = sms.sent[-1].code
    wrong = "000000" if code != "000000" else "000001"
    r = tablet.post("/api/auth/switch/back", json={"code": wrong})
    assert r.status_code == 400 and error_code(r) == "invalid_code" and details(r) == {"attempts_left": 4}
    r = tablet.post("/api/auth/switch/back", json={"code": code})
    assert r.status_code == 200 and r.json()["user"]["id"] == mum["id"]
    assert count(settings, "login_codes", "purpose = 'reauth' AND used_at IS NULL") == 0  # consumed with the switch
    # the e-mail channel needs a verified e-mail on the guardian
    assert tablet.post(f"/api/auth/switch/{kid}").status_code == 200
    r = tablet.post("/api/auth/switch/code", json={"channel": "email"})
    assert r.status_code == 400 and error_code(r) == "validation_error" and details(r) == {"fields": {"channel": "家长账号尚未验证邮箱"}}
    execute(settings, "UPDATE users SET email = 'mum@example.com', email_verified_at = ? WHERE id = ?", (NOW_ISO, mum["id"]))
    app.state.mailer = None
    r = tablet.post("/api/auth/switch/code", json={"channel": "email"})
    assert r.status_code == 409 and error_code(r) == "smtp_unconfigured"
    app.state.mailer = mailer
    frozen_clock.advance(minutes=1)
    r = tablet.post("/api/auth/switch/code", json={"channel": "email"})
    assert r.status_code == 202 and mailer.sent[-1].to == "mum@example.com" and "身份确认" in mailer.sent[-1].subject
    mail_code = re.search(r"(\d{6})", mailer.sent[-1].text).group(1)
    r = tablet.post("/api/auth/switch/back", json={"code": mail_code})
    assert r.status_code == 200 and r.json()["user"]["id"] == mum["id"]
    # a guardian without a phone: the phone channel is refused; the sms double gone → 409
    assert tablet.post(f"/api/auth/switch/{kid}").status_code == 200
    app.state.sms = None
    r = tablet.post("/api/auth/switch/code", json={"channel": "phone"})
    assert r.status_code == 409 and error_code(r) == "sms_unconfigured"
    app.state.sms = sms
    execute(settings, "DELETE FROM identities WHERE user_id = ?", (mum["id"],))
    r = tablet.post("/api/auth/switch/code", json={"channel": "phone"})
    assert r.status_code == 400 and details(r) == {"fields": {"channel": "家长账号尚未绑定手机号"}}
    # the lockout: 10 wrong PINs lock the gate for the guardian everywhere (the laptop's own gate included)
    laptop = second_client(app)
    assert laptop.post("/api/auth/login", json={"username": "mum@example.com", "password": PW}).status_code == 200
    for _ in range(10):
        assert tablet.post("/api/auth/switch/back", json={"pin": PIN2}).status_code == 401
    r = tablet.post("/api/auth/switch/back", json={"pin": PIN})
    assert r.status_code == 423 and error_code(r) == "account_locked" and details(r) == {"retry_after_s": 900} and r.headers["Retry-After"] == "900"
    r = laptop.post("/api/guardian/gate", json={"password": PW})
    assert r.status_code == 423
    frozen_clock.advance(seconds=900)
    r = tablet.post("/api/auth/switch/back", json={"pin": PIN})
    assert r.status_code == 200 and r.json()["user"]["id"] == mum["id"]
    # a disabled guardian behind a switched session (a raw row: the guardian lost its phone above, so 104 would refuse): 403
    token = "raw-switched"
    execute(settings, "INSERT INTO sessions(token_hash, user_id, created_at, expires_at, last_seen_at, actor_user_id) VALUES (?, ?, ?, '2027-01-01T00:00:00Z', ?, ?)", (security.hash_token(token), kid, NOW_ISO, NOW_ISO, mum["id"]))
    orphan = second_client(app)
    orphan.cookies.set("wd_session", token)
    execute(settings, "UPDATE users SET is_active = 0 WHERE id = ?", (mum["id"],))
    r = orphan.post("/api/auth/switch/back", json={"pin": PIN})
    assert r.status_code == 403 and error_code(r) == "account_disabled"
    r = orphan.post("/api/auth/switch/code", json={"channel": "email"})
    assert r.status_code == 403 and error_code(r) == "account_disabled"
    execute(settings, "UPDATE users SET is_active = 1 WHERE id = ?", (mum["id"],))
    # a guardian that vanished altogether: the switched session is deleted and the device is signed out
    execute(settings, "UPDATE sessions SET actor_user_id = NULL WHERE user_id = ?", (kid,))  # detach first: the FK cascade would take the rows with the guardian
    execute(settings, "UPDATE users SET guardian_user_id = NULL WHERE id = ?", (kid,))
    execute(settings, "DELETE FROM users WHERE id = ?", (mum["id"],))
    execute(settings, "INSERT INTO users(id, username, password_hash, created_at, updated_at) VALUES (424242, 'ghost', 'x', ?, ?)", (NOW_ISO, NOW_ISO))
    execute(settings, "UPDATE sessions SET actor_user_id = 424242 WHERE token_hash = ?", (security.hash_token(token),))
    c = db.connect(settings.db_path)
    try:
        c.execute("PRAGMA foreign_keys = OFF")  # outside any transaction (inside one the PRAGMA is a no-op): leave the dangling actor behind
        c.execute("DELETE FROM users WHERE id = 424242")
    finally:
        c.close()
    assert count(settings, "sessions", "token_hash = ?", (security.hash_token(token),)) == 1  # the row survived the delete
    r = orphan.post("/api/auth/switch/back", json={"pin": PIN})
    assert r.status_code == 401 and error_code(r) == "unauthorized"
    assert count(settings, "sessions", "token_hash = ?", (security.hash_token(token),)) == 0


# ------------------------------------------------------------------------------------------------ 107
def test_child_login_with_code(client: TestClient, app, settings, sms, frozen_clock):
    bootstrap(client)
    tablet, mum = make_guardian(app, settings, sms)
    kid = mum["child_id"]
    code = tablet.post(f"/api/guardian/children/{kid}/login-code").json()["code"]
    device = second_client(app)
    r = device.post("/api/auth/child-login", json={"code": "1234567"})
    assert r.status_code == 400 and error_code(r) == "validation_error" and "code" in details(r)["fields"]
    r = device.post("/api/auth/child-login", json={"code": code})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"user", "settings"} and (body["user"]["id"], body["user"]["is_child"], body["user"]["display_name"]) == (kid, True, "小明")
    (cookie,) = session_cookies(r)
    assert f"max-age={CHILD_MAX_AGE}" in cookie.lower() and "httponly" in cookie.lower() and "samesite=lax" in cookie.lower()
    (session,) = session_rows(settings, kid)
    assert (session["expires_at"], session["actor_user_id"], session["guardian_gate_at"]) == ("2027-01-12T00:00:00Z", None, None)  # now + 90 days, a self session
    assert rows(settings, "SELECT last_login_at FROM users WHERE id = ?", (kid,))[0]["last_login_at"] == NOW_ISO
    assert rows(settings, "SELECT used_at FROM family_codes")[0]["used_at"] == NOW_ISO
    me = device.get("/api/auth/me")
    assert me.status_code == 200 and me.json()["user"]["id"] == kid and me.json()["user"]["is_child"] is True
    assert tablet.get("/api/guardian/children").json()["items"][0]["sessions"] == 1
    # single use; unknown; the failures-only IP window (a valid code in between never counts)
    r = second_client(app).post("/api/auth/child-login", json={"code": code})
    assert r.status_code == 400 and error_code(r) == "invalid_code" and details(r) == {"attempts_left": 0}
    assert count(settings, "auth_throttle", "key = 'child_login:ip:testclient' AND count = 1") == 1
    for _ in range(8):
        assert second_client(app).post("/api/auth/child-login", json={"code": "00000000"}).status_code == 400
    assert count(settings, "auth_throttle", "key = 'child_login:ip:testclient' AND count = 9") == 1
    code2 = tablet.post(f"/api/guardian/children/{kid}/login-code").json()["code"]
    assert second_client(app).post("/api/auth/child-login", json={"code": code2}).status_code == 200  # the 9 misses do not block a valid code
    assert count(settings, "auth_throttle", "key = 'child_login:ip:testclient' AND count = 9") == 1  # a success spends nothing
    assert second_client(app).post("/api/auth/child-login", json={"code": "00000000"}).status_code == 400  # the 10th miss
    r = second_client(app).post("/api/auth/child-login", json={"code": "00000000"})
    assert r.status_code == 429 and error_code(r) == "rate_limited" and details(r)["retry_after_s"] == 3600 and r.headers["Retry-After"] == "3600"
    code3 = tablet.post(f"/api/guardian/children/{kid}/login-code").json()["code"]
    r = second_client(app).post("/api/auth/child-login", json={"code": code3})
    assert r.status_code == 429  # read before the lookup: even a valid code waits for the window
    assert count(settings, "family_codes", "used_at IS NULL") == 1
    frozen_clock.advance(hours=1)
    # an expired code (10 minutes) is a miss
    frozen_clock.advance(seconds=1)
    r = second_client(app).post("/api/auth/child-login", json={"code": code3})
    assert r.status_code == 400 and details(r) == {"attempts_left": 0}
    # a child set free meanwhile: its code is dead, the row spent (the guardian's gate stamp expired with the hour: pass it again)
    assert tablet.post("/api/guardian/gate", json={"pin": PIN}).status_code == 200
    code4 = tablet.post(f"/api/guardian/children/{kid}/login-code").json()["code"]
    execute(settings, "UPDATE users SET guardian_user_id = NULL WHERE id = ?", (kid,))
    r = second_client(app).post("/api/auth/child-login", json={"code": code4})
    assert r.status_code == 400 and error_code(r) == "invalid_code"
    assert count(settings, "family_codes", "used_at IS NULL") == 0
    execute(settings, "UPDATE users SET guardian_user_id = ? WHERE id = ?", (mum["id"], kid))
    # a disabled child: the code is spent, no session
    code5 = tablet.post(f"/api/guardian/children/{kid}/login-code").json()["code"]
    execute(settings, "UPDATE users SET is_active = 0 WHERE id = ?", (kid,))
    sessions_before = count(settings, "sessions", "user_id = ?", (kid,))
    r = second_client(app).post("/api/auth/child-login", json={"code": code5})
    assert r.status_code == 403 and error_code(r) == "account_disabled"
    assert count(settings, "family_codes", "used_at IS NULL") == 0 and count(settings, "sessions", "user_id = ?", (kid,)) == sessions_before
    assert count(settings, "auth_throttle", "key LIKE 'login:%'") == 0  # never login:ip / the lockout
    # the CSRF rule applies like every POST
    raw = TestClient(app, base_url="http://testserver")
    r = raw.post("/api/auth/child-login", json={"code": "12345678"})
    assert r.status_code == 403 and error_code(r) == "csrf_rejected"


def test_slide_never_shortens_the_child_session(client: TestClient, app, settings, sms, frozen_clock):
    bootstrap(client)
    tablet, mum = make_guardian(app, settings, sms)
    kid = mum["child_id"]
    code = tablet.post(f"/api/guardian/children/{kid}/login-code").json()["code"]
    device = second_client(app)
    r = device.post("/api/auth/child-login", json={"code": code})
    assert r.status_code == 200 and f"max-age={CHILD_MAX_AGE}" in r.headers["set-cookie"].lower()
    token = device.cookies.get("wd_session")
    assert session_cookies(device.get("/api/auth/me")) == []  # same day: nothing slid, nothing re-sent
    frozen_clock.advance(days=2)
    r = device.get("/api/auth/me")
    assert r.status_code == 200
    (cookie,) = session_cookies(r)
    assert cookie.lower().startswith(f"wd_session={token.lower()};") and f"max-age={88 * 86400}" in cookie.lower()  # the seconds left, not 30 days
    (session,) = session_rows(settings, kid)
    assert session["expires_at"] == "2027-01-12T00:00:00Z"  # unchanged: now + 30 d would have shortened it
    assert rows(settings, "SELECT last_seen_at FROM sessions WHERE user_id = ?", (kid,))[0]["last_seen_at"] == "2026-10-16T00:00:00Z"
    assert session_cookies(device.get("/api/auth/me")) == []  # once per day
    # the guardian's 30-day session slides exactly as before (day 2 + 30 d, a 30-day cookie)
    r = tablet.get("/api/auth/me")
    assert r.status_code == 200 and "max-age=2592000" in session_cookies(r)[0].lower()
    assert session_rows(settings, mum["id"])[0]["expires_at"] == "2026-11-15T00:00:00Z"
    # once the slide passes the child session's horizon the row moves and the cookie is 30 days again
    frozen_clock.advance(days=59)  # day 61
    r = device.get("/api/auth/me")
    (cookie,) = session_cookies(r)
    assert "max-age=2592000" in cookie.lower()
    assert session_rows(settings, kid)[0]["expires_at"] == "2027-01-13T00:00:00Z"  # day 61 + 30 d



def test_disabling_a_guardian_signs_its_switched_devices_out(client: TestClient, app, settings, sms):
    """API.md 57 (slice 1-B): deactivating a guardian also deletes the sessions it issued by switching into its children — the shared
    tablet left in a child's account answers 401 instead of keeping a deactivated guardian's foothold; the child's own device stays."""
    bootstrap(client)
    tablet, mum = make_guardian(app, settings, sms)
    kid = mum["child_id"]
    assert tablet.post(f"/api/auth/switch/{kid}").status_code == 200
    execute(settings, "INSERT INTO sessions(token_hash, user_id, created_at, expires_at, last_seen_at) VALUES ('own-device', ?, ?, '2027-01-12T00:00:00Z', ?)", (kid, NOW_ISO, NOW_ISO))
    assert tablet.get("/api/auth/me").json()["user"]["id"] == kid
    r = client.post(f"/api/admin/users/{mum['id']}", json={"is_active": False})
    assert r.status_code == 200, r.text
    assert tablet.get("/api/auth/me").status_code == 401
    assert count(settings, "sessions", "actor_user_id = ?", (mum["id"],)) == 0 and count(settings, "sessions", "user_id = ?", (kid,)) == 1
