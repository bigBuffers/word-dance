"""Endpoints 94–103 (API.md §3.2, slice 1-B): the children list and the two-factor readiness, creating a child (the first 家长 PIN, the
username + password pair, the cap, readiness), the 家长门 (stamp lifetime, PIN lockout, password and code paths, the one-of rule),
rename / simple login (a password revokes the child's sessions), delete with its cascade, revoke sessions, the 8-digit login code
(5/h, void older, never logged), the 独立 flow (own-phone code + emancipate), PIN set / change, and the 403s for learners and children."""

from __future__ import annotations

import logging
import re

import pytest
from fastapi.testclient import TestClient

from wd import db, family, security
from wd.delivery.mailer import RecordingMailer
from wd.delivery.sms import RecordingSmsSender

PW = "Correct-Horse-7"
KID_PW = "Kid-Pass-Word-9"
NOW_ISO = "2026-10-14T00:00:00Z"
PHONE = "13800138000"
E164 = "+8613800138000"
OTHER = "13900139000"
OTHER_E164 = "+8613900139000"
PIN = "135790"
PIN2 = "246813"


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
    """The first account is a username + password registration (admin): a code sign-in refuses an empty site (setup_required)."""
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


def code_account(c: TestClient, sms: RecordingSmsSender, target: str = PHONE) -> dict:
    """A code-created account (phone channel) logged in on ``c`` — a placeholder username, the phone identity, no password."""
    assert c.post("/api/auth/code", json={"channel": "phone", "target": target, "purpose": "login", "consent": True}).status_code == 202
    r = c.post("/api/auth/code/login", json={"channel": "phone", "target": target, "code": sms.sent[-1].code})
    assert r.status_code == 201, r.text
    return r.json()["user"]


def promote(settings, user_id: int) -> None:
    """Make the row a guardian. Endpoint 89 writes ``account_kind`` once B1b lands (make_guardian sends it); this keeps the helper
    independent of that router change (a no-op afterwards) and builds the phone-only / e-mail-only guardians of the readiness tests."""
    execute(settings, "UPDATE users SET account_kind = 'guardian', age_band = COALESCE(age_band, 'adult'), updated_at = ? WHERE id = ?", (NOW_ISO, user_id))


def make_guardian(app, settings, sms: RecordingSmsSender, *, phone: str = PHONE, display_name: str = "妈妈") -> tuple[TestClient, dict]:
    """A READY guardian: a code sign-up (the live phone identity) + the first-time profile with a password (the second factor)."""
    c = second_client(app)
    user = code_account(c, sms, phone)
    r = c.post("/api/account/profile", json={"display_name": display_name, "account_kind": "guardian", "age_band": "adult", "password": PW})
    assert r.status_code == 200, r.text
    promote(settings, int(user["id"]))
    me = c.get("/api/auth/me")
    assert me.status_code == 200 and me.json()["user"]["account_kind"] == "guardian" and me.json()["user"]["has_password"] is True
    return c, me.json()["user"]


def gate(c: TestClient, **factor):
    return c.post("/api/guardian/gate", json=factor)


def add_child(c: TestClient, display_name: str = "小明", **extra):
    return c.post("/api/guardian/children", json={"display_name": display_name, **extra})


def child_session(settings, child_id: int, token_hash: str = "child-device") -> None:
    execute(settings, "INSERT INTO sessions(token_hash, user_id, created_at, expires_at, last_seen_at) VALUES (?, ?, ?, '2027-01-12T00:00:00Z', ?)", (token_hash, child_id, NOW_ISO, NOW_ISO))


# ------------------------------------------------------------------------------------------------- 94
def test_children_list_readiness_and_pin_state(client: TestClient, app, settings, sms, mailer):
    root = bootstrap(client)
    mum, mum_user = make_guardian(app, settings, sms)
    r = mum.get("/api/guardian/children")
    assert r.status_code == 200, r.text
    assert r.json() == {"items": [], "pin_set": False, "ready": True, "missing": [], "gate_until": None}
    # an e-mail-only guardian: the verified e-mail is a second factor, the phone is missing
    dad = second_client(app)
    assert dad.post("/api/auth/code", json={"channel": "email", "target": "dad@example.com", "purpose": "login", "consent": True}).status_code == 202
    code = re.search(r"(\d{6})", mailer.sent[-1].text).group(1)
    r = dad.post("/api/auth/code/login", json={"channel": "email", "target": "dad@example.com", "code": code})
    assert r.status_code == 201
    promote(settings, int(r.json()["user"]["id"]))
    r = dad.get("/api/guardian/children")
    assert r.status_code == 200 and (r.json()["ready"], r.json()["missing"]) == (False, ["phone"])
    # a phone-only guardian (no password, no e-mail): the second factor is missing
    aunt = second_client(app)
    promote(settings, int(code_account(aunt, sms, OTHER)["id"]))
    r = aunt.get("/api/guardian/children")
    assert r.status_code == 200 and (r.json()["ready"], r.json()["missing"]) == (False, ["second_factor"])
    # a learner (the admin) never satisfies G
    r = client.get("/api/guardian/children")
    assert r.status_code == 403 and error_code(r) == "forbidden"
    assert second_client(app).get("/api/guardian/children").status_code == 401
    assert root["account_kind"] == "learner" and mum_user["is_child"] is False


# ------------------------------------------------------------------------------------------------- 95
def test_create_child_rules(client: TestClient, app, settings, sms, caplog):
    bootstrap(client)
    mum, mum_user = make_guardian(app, settings, sms)
    me = int(mum_user["id"])
    r = add_child(mum, pin=PIN)
    assert r.status_code == 403 and error_code(r) == "guardian_gate_required"  # the gate first
    r = gate(mum, password=PW)
    assert r.status_code == 200 and r.json() == {"gate_until": "2026-10-14T00:10:00Z"}
    assert mum.get("/api/guardian/children").json()["gate_until"] == "2026-10-14T00:10:00Z"
    r = add_child(mum)
    assert r.status_code == 400 and error_code(r) == "validation_error" and details(r) == {"fields": {"pin": "请设置 6 位家长 PIN"}}  # the first child needs the PIN
    r = add_child(mum, pin="123456")
    assert r.status_code == 400 and details(r) == {"fields": {"pin": "PIN 不能是连号或重复数字"}}
    r = add_child(mum, pin="12345")
    assert r.status_code == 400 and error_code(r) == "validation_error" and "pin" in details(r)["fields"]  # the schema's pattern
    r = add_child(mum, pin=PIN, username="xiaoming")
    assert r.status_code == 400 and details(r) == {"fields": {"password": "用户名和密码需要一起设置"}}
    r = add_child(mum, pin=PIN, password=KID_PW)
    assert r.status_code == 400 and details(r) == {"fields": {"username": "用户名和密码需要一起设置"}}
    r = add_child(mum, " ", pin=PIN)
    assert r.status_code == 400 and "display_name" in details(r)["fields"]
    assert count(settings, "users", "guardian_user_id IS NOT NULL") == 0 and rows(settings, "SELECT guardian_pin_hash FROM users WHERE id = ?", (me,))[0]["guardian_pin_hash"] is None
    caplog.set_level(logging.INFO, logger="wd")
    r = add_child(mum, " 小明 ", pin=PIN)
    assert r.status_code == 201, r.text
    child = r.json()["child"]
    assert child == {
        "id": child["id"],
        "display_name": "小明",
        "username": None,
        "has_password": False,
        "phone_masked": None,
        "age_band": "u14",
        "onboarding_state": "pending",
        "created_at": NOW_ISO,
        "last_login_at": None,
        "bank_size": 0,
        "streak_days": 0,
        "sessions": 0,
    }
    row = rows(settings, "SELECT * FROM users WHERE id = ?", (child["id"],))[0]
    assert (row["guardian_user_id"], row["account_kind"], row["age_band"], row["age_declared_at"], row["age_declared_ip"], row["guardian_consent_at"], row["password_set_at"], row["role"], row["onboarding_state"]) == (me, "learner", "u14", NOW_ISO, "testclient", NOW_ISO, None, "user", "pending")
    assert security.PLACEHOLDER_USERNAME_RE.match(row["username"]) and not security.verify_password("", row["password_hash"])
    assert count(settings, "user_settings", "user_id = ?", (child["id"],)) == 1
    pin_hash = rows(settings, "SELECT guardian_pin_hash FROM users WHERE id = ?", (me,))[0]["guardian_pin_hash"]
    assert pin_hash and family.verify_pin(PIN, pin_hash)
    events = rows(settings, "SELECT kind, detail_json FROM system_events WHERE kind = 'child_created'")
    assert len(events) == 1 and f'"child_id": {child["id"]}' in events[0]["detail_json"] and f'"guardian_id": {me}' in events[0]["detail_json"]
    assert PIN not in caplog.text and any(getattr(rec, "event", None) == "child_created" and rec.child_id == child["id"] for rec in caplog.records)
    assert mum.get("/api/guardian/children").json()["pin_set"] is True
    # the PIN is set now: refused in later creations; the simple login pair
    r = add_child(mum, "小红", pin=PIN)
    assert r.status_code == 400 and details(r) == {"fields": {"pin": "PIN 已设置，请在「家长 PIN」中修改"}}
    r = add_child(mum, "小红", username="xiaohong", password=KID_PW)
    assert r.status_code == 201, r.text
    assert (r.json()["child"]["username"], r.json()["child"]["has_password"]) == ("xiaohong", True)
    kid2 = rows(settings, "SELECT * FROM users WHERE username = 'xiaohong'")[0]
    assert kid2["password_set_at"] == NOW_ISO and security.verify_password(KID_PW, kid2["password_hash"])
    r = add_child(mum, "小兰", username="XiaoHong", password=KID_PW)
    assert r.status_code == 409 and error_code(r) == "username_taken"
    r = add_child(mum, "小兰", username="root", password=KID_PW)
    assert r.status_code == 409 and error_code(r) == "username_taken"  # a learner's name
    r = add_child(mum, "小兰", username="xiaolan", password="password123")
    assert r.status_code == 400 and error_code(r) == "weak_password"
    r = add_child(mum, "小兰", username="xiaolan", password="xiaolan-xiaolan")
    assert r.status_code == 201  # not equal to the username → acceptable
    r = add_child(mum, "小兰", username="13700137000", password=KID_PW)
    assert r.status_code == 400 and error_code(r) == "validation_error" and "username" in details(r)["fields"]  # never a phone-like name
    assert [c["display_name"] for c in mum.get("/api/guardian/children").json()["items"]] == ["小明", "小红", "小兰"]
    # the cap: 10 children per guardian
    for i in range(7):
        execute(settings, "INSERT INTO users(username, password_hash, guardian_user_id, age_band, created_at, updated_at) VALUES (?, 'x', ?, 'u14', ?, ?)", (f"extra{i}", me, NOW_ISO, NOW_ISO))
    r = add_child(mum, "第十一个")
    assert r.status_code == 409 and error_code(r) == "invalid_transition" and details(r) == {"reason": "too_many_children"}
    assert count(settings, "users", "guardian_user_id = ?", (me,)) == 10
    # the two-factor rule: a guardian without a phone cannot create children
    dad = second_client(app)
    bob = dad.post("/api/auth/register", json={"username": "bob", "password": PW}).json()["user"]
    promote(settings, int(bob["id"]))
    assert gate(dad, password=PW).status_code == 200
    r = add_child(dad, "谁的孩子", pin=PIN)
    assert r.status_code == 409 and error_code(r) == "guardian_factors_required" and details(r) == {"missing": ["phone"]}


# ------------------------------------------------------------------------------------------- 102 / 103
def test_gate_paths_and_lockout(client: TestClient, app, settings, sms, frozen_clock):
    bootstrap(client)
    mum, mum_user = make_guardian(app, settings, sms)
    me = int(mum_user["id"])
    # exactly one factor (the schema), a factor the account lacks
    for body in ({}, {"pin": PIN, "password": PW}, {"pin": PIN, "code": "123456", "password": PW}):
        r = gate(mum, **body)
        assert r.status_code == 400 and error_code(r) == "validation_error" and details(r) == {"fields": {"body": "PIN、密码和验证码必须且只能提供一个"}}, body
    r = gate(mum, pin="12345")
    assert r.status_code == 400 and "pin" in details(r)["fields"]
    # no PIN yet: the dummy path fails (and counts), the password opens the gate and sets the first PIN through 103
    r = gate(mum, pin=PIN)
    assert r.status_code == 401 and error_code(r) == "invalid_pin"
    assert rows(settings, "SELECT count FROM auth_throttle WHERE key = ?", (f"gate:user:{me}",))[0]["count"] == 1
    assert gate(mum, password=PW).status_code == 200
    assert count(settings, "auth_throttle", "key = ?", (f"gate:user:{me}",)) == 0  # cleared by the success
    assert mum.put("/api/guardian/pin", json={"pin": PIN}).status_code == 204
    # the stamp lives 10 minutes
    frozen_clock.advance(seconds=599)
    assert mum.get("/api/guardian/children").json()["gate_until"] == "2026-10-14T00:10:00Z"
    assert add_child(mum, "小明").status_code == 201
    frozen_clock.advance(seconds=2)
    assert mum.get("/api/guardian/children").json()["gate_until"] is None
    r = add_child(mum, "小红")
    assert r.status_code == 403 and error_code(r) == "guardian_gate_required"
    # the PIN path and its lockout: 10 wrong → 423 with the login cadence; the right PIN after the lock clears the streak
    for _ in range(10):
        r = gate(mum, pin=PIN2)
        assert r.status_code == 401 and error_code(r) == "invalid_pin"
    r = gate(mum, pin=PIN)
    assert r.status_code == 423 and error_code(r) == "account_locked" and details(r) == {"retry_after_s": 900} and r.headers["Retry-After"] == "900"
    r = gate(mum, password=PW)
    assert r.status_code == 423  # whatever the factor
    frozen_clock.advance(seconds=900)
    r = gate(mum, pin=PIN)
    assert r.status_code == 200 and r.json()["gate_until"] == "2026-10-14T00:35:01Z"  # 00:10:01 + 15 min lock + 10 min stamp
    assert count(settings, "auth_throttle", "key = ?", (f"gate:user:{me}",)) == 0
    # the password path counts on the gate too (and on its own pwcheck budget)
    r = gate(mum, password="wrong-password-1")
    assert r.status_code == 401 and error_code(r) == "invalid_credentials"
    assert rows(settings, "SELECT count FROM auth_throttle WHERE key = ?", (f"gate:user:{me}",))[0]["count"] == 1
    assert count(settings, "auth_throttle", "key = ?", (f"pwcheck:user:{me}",)) == 1
    assert gate(mum, password=PW).status_code == 200
    # the code path: a reauth code of endpoint 85 to the bound phone
    frozen_clock.advance(minutes=1)
    r = mum.post("/api/account/code", json={"channel": "phone", "purpose": "reauth"})
    assert r.status_code == 202 and sms.sent[-1].template == "100005" and sms.sent[-1].to == E164
    code = sms.sent[-1].code
    wrong = "000000" if code != "000000" else "000001"
    r = gate(mum, code=wrong)
    assert r.status_code == 400 and error_code(r) == "invalid_code" and details(r) == {"attempts_left": 4}
    r = gate(mum, code=code)
    assert r.status_code == 200
    assert count(settings, "login_codes", "purpose = 'reauth' AND used_at IS NULL") == 0  # consumed with the stamp
    r = gate(mum, code=code)
    assert r.status_code == 400 and details(r) == {"attempts_left": 0}  # single use
    # a guardian without a password cannot use the password factor
    dad = second_client(app)
    promote(settings, int(code_account(dad, sms, OTHER)["id"]))
    r = gate(dad, password=PW)
    assert r.status_code == 400 and details(r) == {"fields": {"password": "账号没有密码，请用 PIN 或验证码"}}
    # learners get 403 on the gate; so does a child session
    r = client.post("/api/guardian/gate", json={"password": PW})
    assert r.status_code == 403 and error_code(r) == "forbidden"


def test_pin_set_and_change(client: TestClient, app, settings, sms, frozen_clock):
    bootstrap(client)
    mum, mum_user = make_guardian(app, settings, sms)
    r = mum.put("/api/guardian/pin", json={"pin": PIN})
    assert r.status_code == 403 and error_code(r) == "guardian_gate_required"  # the first PIN is gated too: the password / a code open 102 while no PIN exists
    assert gate(mum, password=PW).status_code == 200
    r = mum.put("/api/guardian/pin", json={"pin": "111111"})
    assert r.status_code == 400 and details(r) == {"fields": {"pin": "PIN 不能是连号或重复数字"}}
    r = mum.put("/api/guardian/pin", json={"pin": "1234"})
    assert r.status_code == 400 and "pin" in details(r)["fields"]
    assert mum.put("/api/guardian/pin", json={"pin": PIN}).status_code == 204
    assert mum.get("/api/guardian/children").json()["pin_set"] is True
    frozen_clock.advance(minutes=11)  # the stamp expired
    r = mum.put("/api/guardian/pin", json={"pin": PIN2})
    assert r.status_code == 403 and error_code(r) == "guardian_gate_required"  # a change needs the gate as well
    assert gate(mum, pin=PIN).status_code == 200
    assert mum.put("/api/guardian/pin", json={"pin": PIN2}).status_code == 204
    pin_hash = rows(settings, "SELECT guardian_pin_hash FROM users WHERE id = ?", (mum_user["id"],))[0]["guardian_pin_hash"]
    assert family.verify_pin(PIN2, pin_hash) and not family.verify_pin(PIN, pin_hash)
    r = client.put("/api/guardian/pin", json={"pin": PIN})
    assert r.status_code == 403 and error_code(r) == "forbidden"


# -------------------------------------------------------------------------------------------- 96 / 97 / 98
def test_rename_and_simple_login(client: TestClient, app, settings, sms):
    bootstrap(client)
    mum, mum_user = make_guardian(app, settings, sms)
    dad, dad_user = make_guardian(app, settings, sms, phone=OTHER, display_name="爸爸")
    assert gate(mum, password=PW).status_code == 200 and gate(dad, password=PW).status_code == 200
    kid = add_child(mum, "小明", pin=PIN).json()["child"]["id"]
    other = add_child(dad, "别人家的", pin=PIN).json()["child"]["id"]
    r = mum.patch(f"/api/guardian/children/{kid}", json={})
    assert r.status_code == 400 and error_code(r) == "validation_error" and details(r) == {"fields": {"body": "至少提供昵称、用户名或密码之一"}}
    r = mum.patch(f"/api/guardian/children/{other}", json={"display_name": "抢来的"})
    assert r.status_code == 404 and error_code(r) == "not_found"
    r = mum.patch(f"/api/guardian/children/{kid}", json={"display_name": " 明明 "})
    assert r.status_code == 200 and r.json()["child"]["display_name"] == "明明" and r.json()["child"]["username"] is None
    r = mum.patch(f"/api/guardian/children/{kid}", json={"password": KID_PW})
    assert r.status_code == 400 and details(r) == {"fields": {"username": "请先为孩子设置用户名"}}  # a placeholder cannot be typed
    r = mum.patch(f"/api/guardian/children/{kid}", json={"username": "root"})
    assert r.status_code == 409 and error_code(r) == "username_taken"
    r = mum.patch(f"/api/guardian/children/{kid}", json={"username": "xiaoming"})
    assert r.status_code == 200 and (r.json()["child"]["username"], r.json()["child"]["has_password"]) == ("xiaoming", False)
    child_session(settings, kid, "tablet")
    child_session(settings, kid, "phone")
    assert mum.get("/api/guardian/children").json()["items"][0]["sessions"] == 2
    r = mum.patch(f"/api/guardian/children/{kid}", json={"password": "xiaoming"})
    assert r.status_code == 400 and error_code(r) == "weak_password"  # equals the username (final username = the current one)
    r = mum.patch(f"/api/guardian/children/{kid}", json={"password": KID_PW})
    assert r.status_code == 200 and r.json()["child"]["has_password"] is True and r.json()["child"]["sessions"] == 0  # every child session revoked
    assert count(settings, "sessions", "user_id = ?", (kid,)) == 0
    # the child can now sign in with the simple login — a child self session that never satisfies G
    tablet = second_client(app)
    r = tablet.post("/api/auth/login", json={"username": "xiaoming", "password": KID_PW})
    assert r.status_code == 200, r.text
    assert (r.json()["user"]["is_child"], r.json()["user"]["account_kind"], r.json()["user"]["display_name"]) == (True, "learner", "明明")
    for method, path, body in (("GET", "/api/guardian/children", None), ("POST", "/api/guardian/children", {"display_name": "x"}), ("POST", "/api/guardian/gate", {"pin": PIN}), ("PUT", "/api/guardian/pin", {"pin": PIN})):
        r = tablet.request(method, path, json=body)
        assert r.status_code == 403 and error_code(r) == "forbidden", path
    # both in one body: the username of this body counts for the password rule
    kid2 = add_child(mum, "小红").json()["child"]["id"]
    r = mum.patch(f"/api/guardian/children/{kid2}", json={"username": "xiaohong", "password": "xiaohong"})
    assert r.status_code == 400 and error_code(r) == "weak_password"
    r = mum.patch(f"/api/guardian/children/{kid2}", json={"username": "xiaohong", "password": KID_PW, "display_name": "红红"})
    assert r.status_code == 200 and (r.json()["child"]["username"], r.json()["child"]["has_password"], r.json()["child"]["display_name"]) == ("xiaohong", True, "红红")
    assert dad_user["id"] != mum_user["id"]


def test_delete_child_cascades_and_revoke_sessions(client: TestClient, app, settings, sms):
    bootstrap(client)
    mum, mum_user = make_guardian(app, settings, sms)
    dad, _ = make_guardian(app, settings, sms, phone=OTHER)
    assert gate(mum, password=PW).status_code == 200 and gate(dad, password=PW).status_code == 200
    kid = add_child(mum, "小明", pin=PIN).json()["child"]["id"]
    other = add_child(dad, "别人家的", pin=PIN).json()["child"]["id"]
    # revoke: every session of the child, the guardian's own stays
    child_session(settings, kid, "tablet")
    child_session(settings, kid, "phone")
    r = mum.post(f"/api/guardian/children/{other}/sessions/revoke")
    assert r.status_code == 404
    r = mum.post(f"/api/guardian/children/{kid}/sessions/revoke")
    assert r.status_code == 204 and count(settings, "sessions", "user_id = ?", (kid,)) == 0
    assert mum.get("/api/guardian/children").status_code == 200
    # delete: sessions, user_words, family_codes, login_codes, identities, user_settings all go
    child_session(settings, kid, "tablet2")
    (word_id,) = [r["id"] for r in rows(settings, "SELECT id FROM words ORDER BY id LIMIT 1")]
    execute(settings, "INSERT INTO user_words(user_id, word_id, state, origin) VALUES (?, ?, 'new', 'browse')", (kid, word_id))
    assert mum.post(f"/api/guardian/children/{kid}/login-code").status_code == 201
    execute(settings, "INSERT INTO login_codes(channel, target, purpose, user_id, code_hash, expires_at) VALUES ('phone', ?, 'bind_phone', ?, 'h', '2026-10-14T00:10:00Z')", (OTHER_E164, kid))
    r = mum.delete(f"/api/guardian/children/{other}")
    assert r.status_code == 404 and error_code(r) == "not_found"
    r = mum.delete(f"/api/guardian/children/{kid}")
    assert r.status_code == 204
    assert count(settings, "users", "id = ?", (kid,)) == 0
    for table in ("sessions", "user_words", "family_codes", "login_codes", "user_settings"):
        assert count(settings, table, "user_id = ?", (kid,)) == 0, table
    assert count(settings, "system_events", "kind = 'child_deleted'") == 1
    assert count(settings, "users", "id = ?", (mum_user["id"],)) == 1 and mum.get("/api/guardian/children").json()["items"] == []
    r = mum.delete(f"/api/guardian/children/{kid}")
    assert r.status_code == 404
    assert count(settings, "users", "id = ?", (other,)) == 1  # the other guardian's child is untouched


# ------------------------------------------------------------------------------------------------- 99
def test_login_code(client: TestClient, app, settings, sms, frozen_clock, caplog):
    bootstrap(client)
    mum, mum_user = make_guardian(app, settings, sms)
    assert gate(mum, password=PW).status_code == 200
    kid = add_child(mum, "小明", pin=PIN).json()["child"]["id"]
    caplog.set_level(logging.INFO, logger="wd")
    r = mum.post(f"/api/guardian/children/{kid}/login-code")
    assert r.status_code == 201, r.text
    body = r.json()
    assert set(body) == {"code", "expires_in_s"} and re.fullmatch(r"\d{8}", body["code"]) and body["expires_in_s"] == 600
    row = rows(settings, "SELECT * FROM family_codes")[0]
    assert (row["kind"], row["user_id"], row["target"], row["used_at"], row["attempts"], row["expires_at"], row["ip"]) == ("child_login", kid, None, None, 0, "2026-10-14T00:10:00Z", "testclient")
    assert row["code_hash"] == family.family_code_hash(settings.secret_key, body["code"], "child_login", None) and body["code"] not in str(row)
    assert body["code"] not in caplog.text and any(getattr(rec, "event", None) == "child_code_issued" and rec.child_id == kid for rec in caplog.records)
    # a new code voids the older one
    r = mum.post(f"/api/guardian/children/{kid}/login-code")
    assert r.status_code == 201 and r.json()["code"] != body["code"]
    assert [r_["used_at"] for r_ in rows(settings, "SELECT used_at FROM family_codes ORDER BY id")] == [NOW_ISO, None]
    # 5 per hour per child (the whole hour counts, not only the misses)
    for _ in range(3):
        assert mum.post(f"/api/guardian/children/{kid}/login-code").status_code == 201
    r = mum.post(f"/api/guardian/children/{kid}/login-code")
    assert r.status_code == 429 and error_code(r) == "rate_limited" and details(r) == {"retry_after_s": 3600} and r.headers["Retry-After"] == "3600"
    kid2 = add_child(mum, "小红").json()["child"]["id"]
    assert mum.post(f"/api/guardian/children/{kid2}/login-code").status_code == 201  # another child, another window
    frozen_clock.advance(hours=1)
    assert gate(mum, pin=PIN).status_code == 200
    assert mum.post(f"/api/guardian/children/{kid}/login-code").status_code == 201
    assert count(settings, "family_codes", "user_id = ? AND used_at IS NULL", (kid,)) == 1
    # the gate, the ownership and the readiness are required
    r = mum.post(f"/api/guardian/children/{kid + 100}/login-code")
    assert r.status_code == 404
    execute(settings, "DELETE FROM identities WHERE user_id = ?", (mum_user["id"],))
    r = mum.post(f"/api/guardian/children/{kid}/login-code")
    assert r.status_code == 409 and error_code(r) == "guardian_factors_required" and details(r) == {"missing": ["phone"]}
    frozen_clock.advance(minutes=11)
    r = mum.post(f"/api/guardian/children/{kid}/login-code")
    assert r.status_code == 403 and error_code(r) == "guardian_gate_required"


# ------------------------------------------------------------------------------------------- 100 / 101
def test_own_phone_code_and_emancipate(client: TestClient, app, settings, sms, frozen_clock):
    bootstrap(client)
    mum, mum_user = make_guardian(app, settings, sms)
    assert gate(mum, password=PW).status_code == 200
    kid = add_child(mum, "小明", pin=PIN).json()["child"]["id"]
    assert mum.post(f"/api/guardian/children/{kid}/login-code").status_code == 201
    child_session(settings, kid, "tablet")
    r = mum.post(f"/api/guardian/children/{kid}/code", json={"target": "12345"})
    assert r.status_code == 400 and error_code(r) == "invalid_phone"
    r = mum.post(f"/api/guardian/children/{kid}/code", json={"target": PHONE})
    assert r.status_code == 409 and error_code(r) == "identity_taken"  # the guardian's own number
    r = mum.post(f"/api/guardian/children/{kid + 100}/code", json={"target": OTHER})
    assert r.status_code == 404
    sent_before = len(sms.sent)
    r = mum.post(f"/api/guardian/children/{kid}/code", json={"target": " 139 0013 9000 "})
    assert r.status_code == 202 and r.json() == {"sent": True, "expires_in_s": 600}
    assert len(sms.sent) == sent_before + 1 and sms.sent[-1].to == OTHER_E164 and sms.sent[-1].template == "100004"
    code_row = rows(settings, "SELECT * FROM login_codes WHERE purpose = 'bind_phone'")[0]
    assert (code_row["user_id"], code_row["target"], code_row["channel"]) == (kid, OTHER_E164, "phone")  # the code belongs to the CHILD
    code = sms.sent[-1].code
    wrong = "000000" if code != "000000" else "000001"
    r = mum.post(f"/api/guardian/children/{kid}/emancipate", json={"target": OTHER, "code": wrong, "password": KID_PW})
    assert r.status_code == 400 and error_code(r) == "invalid_code" and details(r) == {"attempts_left": 4}
    r = mum.post(f"/api/guardian/children/{kid}/emancipate", json={"target": OTHER, "code": code, "password": "password123"})
    assert r.status_code == 400 and error_code(r) == "weak_password"
    r = mum.post(f"/api/guardian/children/{kid}/emancipate", json={"target": PHONE, "code": code, "password": KID_PW})
    assert r.status_code == 400 and details(r) == {"attempts_left": 0}  # the code was sent to the other number
    assert count(settings, "users", "guardian_user_id = ?", (mum_user["id"],)) == 1
    r = mum.post(f"/api/guardian/children/{kid}/emancipate", json={"target": OTHER, "code": code, "password": KID_PW})
    assert r.status_code == 200, r.text
    child = r.json()["child"]
    assert (child["id"], child["phone_masked"], child["has_password"], child["age_band"], child["sessions"]) == (kid, "139****9000", True, "14plus", 0)
    row = rows(settings, "SELECT * FROM users WHERE id = ?", (kid,))[0]
    assert (row["guardian_user_id"], row["account_kind"], row["age_band"], row["age_declared_at"], row["age_declared_ip"], row["password_set_at"]) == (None, "learner", "14plus", NOW_ISO, "testclient", NOW_ISO)
    identity = rows(settings, "SELECT * FROM identities WHERE user_id = ?", (kid,))[0]
    assert (identity["subject"], identity["verified_at"], identity["last_login_at"], identity["disputed_at"]) == (OTHER_E164, NOW_ISO, NOW_ISO, None)
    assert count(settings, "sessions", "user_id = ?", (kid,)) == 0  # the shared tablet is signed out of the child
    assert count(settings, "family_codes", "user_id = ? AND used_at IS NULL", (kid,)) == 0  # its login codes are void
    assert count(settings, "login_codes", "purpose = 'bind_phone' AND used_at IS NULL") == 0
    assert count(settings, "system_events", "kind = 'child_emancipated'") == 1
    assert mum.get("/api/guardian/children").json()["items"] == []
    r = mum.post(f"/api/guardian/children/{kid}/emancipate", json={"target": OTHER, "code": code, "password": KID_PW})
    assert r.status_code == 404  # no longer mine: irreversible
    # the learner signs in with its own phone and the new password
    phone_c = second_client(app)
    r = phone_c.post("/api/auth/login", json={"username": OTHER, "password": KID_PW})
    assert r.status_code == 200 and (r.json()["user"]["is_child"], r.json()["user"]["phone_masked"], r.json()["user"]["age_band"]) == (False, "139****9000", "14plus")
    # another account already holds the number → 409 on the send
    kid2 = add_child(mum, "小红").json()["child"]["id"]
    r = mum.post(f"/api/guardian/children/{kid2}/code", json={"target": OTHER})
    assert r.status_code == 409 and error_code(r) == "identity_taken"
    app.state.sms = None
    r = mum.post(f"/api/guardian/children/{kid2}/code", json={"target": "13700137000"})
    assert r.status_code == 409 and error_code(r) == "sms_unconfigured"
    app.state.sms = sms
    # readiness guards both steps
    execute(settings, "DELETE FROM identities WHERE user_id = ?", (mum_user["id"],))
    r = mum.post(f"/api/guardian/children/{kid2}/code", json={"target": "13700137000"})
    assert r.status_code == 409 and error_code(r) == "guardian_factors_required"
    r = mum.post(f"/api/guardian/children/{kid2}/emancipate", json={"target": "13700137000", "code": "123456", "password": KID_PW})
    assert r.status_code == 409 and error_code(r) == "guardian_factors_required"


def test_emancipate_with_the_number_the_child_already_holds(client: TestClient, app, settings, sms, frozen_clock):
    """API.md 100 / 101: a claimed legacy account that kept its phone (a 14plus claim) is set free with that very number — the code goes
    to it (no `identity_taken`), and 101 re-verifies the identity it already holds instead of inserting a second one."""
    bootstrap(client)
    mum, mum_user = make_guardian(app, settings, sms)
    assert gate(mum, password=PW).status_code == 200
    kid = add_child(mum, "小明", pin=PIN).json()["child"]["id"]
    execute(
        settings,
        "INSERT INTO identities(user_id, provider, subject, verified_at, last_login_at, created_at) VALUES (?, 'phone', ?, ?, NULL, ?)",
        (kid, OTHER_E164, "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
    )
    assert mum.get("/api/guardian/children").json()["items"][0]["phone_masked"] == "139****9000"
    r = mum.post(f"/api/guardian/children/{kid}/code", json={"target": OTHER})
    assert r.status_code == 202, r.text  # the child's own number is accepted
    assert sms.sent[-1].to == OTHER_E164
    r = mum.post(f"/api/guardian/children/{kid}/emancipate", json={"target": OTHER, "code": sms.sent[-1].code, "password": KID_PW})
    assert r.status_code == 200, r.text
    identities = rows(settings, "SELECT * FROM identities WHERE user_id = ?", (kid,))
    assert len(identities) == 1 and (identities[0]["subject"], identities[0]["verified_at"], identities[0]["last_login_at"]) == (OTHER_E164, NOW_ISO, NOW_ISO)
    row = rows(settings, "SELECT guardian_user_id, account_kind, age_band FROM users WHERE id = ?", (kid,))[0]
    assert row == {"guardian_user_id": None, "account_kind": "learner", "age_band": "14plus"}
    assert mum.get("/api/guardian/children").json()["items"] == []
    # a child that kept ANOTHER number is set free with the verified one: the identity is re-pointed (the 88 shape), never doubled
    frozen_clock.advance(hours=1)
    assert gate(mum, pin=PIN).status_code == 200
    kid2 = add_child(mum, "小红").json()["child"]["id"]
    execute(
        settings,
        "INSERT INTO identities(user_id, provider, subject, verified_at, last_login_at, created_at) VALUES (?, 'phone', '+8613700137000', ?, NULL, ?)",
        (kid2, "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
    )
    r = mum.post(f"/api/guardian/children/{kid2}/code", json={"target": "13600136000"})
    assert r.status_code == 202, r.text
    r = mum.post(f"/api/guardian/children/{kid2}/emancipate", json={"target": "13600136000", "code": sms.sent[-1].code, "password": KID_PW})
    assert r.status_code == 200 and r.json()["child"]["phone_masked"] == "136****6000", r.text
    identities = rows(settings, "SELECT subject FROM identities WHERE user_id = ?", (kid2,))
    assert [i["subject"] for i in identities] == ["+8613600136000"]


# ------------------------------------------------------------------------------------------ the 403s
def test_learners_and_children_get_403_on_every_guardian_endpoint(client: TestClient, app, settings, sms):
    bootstrap(client)  # root: a learner (admin)
    mum, _ = make_guardian(app, settings, sms)
    assert gate(mum, password=PW).status_code == 200
    kid = add_child(mum, "小明", pin=PIN, username="xiaoming", password=KID_PW).json()["child"]["id"]
    tablet = second_client(app)
    assert tablet.post("/api/auth/login", json={"username": "xiaoming", "password": KID_PW}).status_code == 200
    calls = (
        ("GET", "/api/guardian/children", None),
        ("POST", "/api/guardian/children", {"display_name": "x", "pin": PIN}),
        ("PATCH", f"/api/guardian/children/{kid}", {"display_name": "x"}),
        ("DELETE", f"/api/guardian/children/{kid}", None),
        ("POST", f"/api/guardian/children/{kid}/sessions/revoke", None),
        ("POST", f"/api/guardian/children/{kid}/login-code", None),
        ("POST", f"/api/guardian/children/{kid}/code", {"target": OTHER}),
        ("POST", f"/api/guardian/children/{kid}/emancipate", {"target": OTHER, "code": "123456", "password": KID_PW}),
        ("POST", "/api/guardian/gate", {"pin": PIN}),
        ("PUT", "/api/guardian/pin", {"pin": PIN}),
    )
    for c, who in ((client, "learner"), (tablet, "child")):
        for method, path, body in calls:
            r = c.request(method, path, json=body)
            assert r.status_code == 403 and error_code(r) == "forbidden", (who, method, path, r.text)
    anonymous = second_client(app)
    for method, path, body in calls:
        r = anonymous.request(method, path, json=body)
        assert r.status_code == 401 and error_code(r) == "unauthorized", (method, path)
    assert count(settings, "users", "id = ?", (kid,)) == 1


# ------------------------------------------------------------------------- the shared send machinery (issuer / voider hooks)
def test_issue_and_send_hooks_write_a_family_code_instead_of_a_login_code(client: TestClient, app, settings, sms, frozen_clock):
    """``auth_codes.issue_and_send(..., issuer=, voider=)`` (the claim code of endpoint 108, B1b): on the phone channel the issuer's code
    goes out under the purpose's template with the SMS caps, a failed send runs the voider, the e-mail channel refuses the hooks."""
    from fastapi import Request

    from wd.delivery.sms import SmsError
    from wd.errors import ApiError
    from wd.routers.auth_codes import issue_and_send

    bootstrap(client)
    legacy = second_client(app)
    uid = int(code_account(legacy, sms, OTHER)["id"])
    request = Request({"type": "http", "app": app, "headers": [], "method": "POST", "path": "/api/account/guardian/code", "query_string": b""})
    now = frozen_clock.now_utc()
    conn = db.connect(settings.db_path)
    try:
        issuer = lambda c: family.issue_claim_code(c, user_id=uid, target=E164, ip="testclient", secret_key=settings.secret_key, now=now)  # noqa: E731
        voider = lambda c: family.void_family_codes(c, kind="claim_guardian", user_id=uid, now=now)  # noqa: E731
        codes_before = count(settings, "login_codes")
        issue_and_send(request, conn, settings, channel="phone", target=E164, purpose="bind_phone", user_id=uid, ip="testclient", now=now, issuer=issuer, voider=voider)
        assert sms.sent[-1].to == E164 and sms.sent[-1].template == "100004" and sms.sent[-1].minutes == 10
        assert count(settings, "login_codes") == codes_before  # no login_codes row: the issuer wrote family_codes
        row = rows(settings, "SELECT * FROM family_codes")[0]
        assert (row["kind"], row["user_id"], row["target"], row["used_at"]) == ("claim_guardian", uid, E164, None)
        assert row["code_hash"] == family.family_code_hash(settings.secret_key, sms.sent[-1].code, "claim_guardian", E164)
        assert family.verify_claim_code(conn, user_id=uid, target=E164, code=sms.sent[-1].code, secret_key=settings.secret_key, now=now) == row["id"]
        # a failed send: the voider marks the new row used, the 1-A error mapping stays
        sms.fail_with = SmsError("temporary", "boom")
        with pytest.raises(ApiError) as e:
            issue_and_send(request, conn, settings, channel="phone", target=E164, purpose="bind_phone", user_id=uid, ip="testclient", now=now, issuer=issuer, voider=voider)
        assert e.value.code == "sms_send_failed"
        assert count(settings, "family_codes", "used_at IS NULL") == 0 and count(settings, "family_codes") == 2
        sms.fail_with = None
        # the e-mail channel has no such rows
        with pytest.raises(ValueError):
            issue_and_send(request, conn, settings, channel="email", target="x@example.com", purpose="bind_phone", user_id=uid, ip="testclient", now=now, issuer=issuer)
        with pytest.raises(ValueError):
            issue_and_send(request, conn, settings, channel="email", target="x@example.com", purpose="bind_phone", user_id=uid, ip="testclient", now=now, voider=voider)
        assert not conn.in_transaction
    finally:
        conn.close()
