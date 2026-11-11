"""Endpoints 85–89 and the slice 1-A changes of 6 / 7 / 8 (API.md §3): account codes (bind_phone / rebind_phone / reauth), bind,
unbind (last_login_method), rebind, the first-time profile, the password-or-code re-authentication of change-password and delete,
and the last-login-method guard of the e-mail field."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from wd import db, security
from wd.delivery.mailer import RecordingMailer
from wd.delivery.sms import RecordingSmsSender

PW = "Correct-Horse-7"
PW2 = "New-Pass-Word-9"
NOW_ISO = "2026-10-14T00:00:00Z"
PHONE = "13800138000"
E164 = "+8613800138000"
OTHER = "13900139000"
OTHER_E164 = "+8613900139000"


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


def register(client: TestClient, username: str, **extra) -> dict:
    r = client.post("/api/auth/register", json={"username": username, "password": PW, **extra})
    assert r.status_code == 201, r.text
    return r.json()["user"]


def code_account(client: TestClient, sms: RecordingSmsSender, target: str = PHONE) -> dict:
    """A code-created account (phone channel) logged in on ``client``."""
    assert client.post("/api/auth/code", json={"channel": "phone", "target": target, "purpose": "login", "consent": True}).status_code == 202
    r = client.post("/api/auth/code/login", json={"channel": "phone", "target": target, "code": sms.sent[-1].code})
    assert r.status_code == 201, r.text
    return r.json()["user"]


def email_account(client: TestClient, mailer: RecordingMailer, email: str = "alice@example.com") -> dict:
    assert client.post("/api/auth/code", json={"channel": "email", "target": email, "purpose": "login", "consent": True}).status_code == 202
    r = client.post("/api/auth/code/login", json={"channel": "email", "target": email, "code": mail_code(mailer)})
    assert r.status_code == 201, r.text
    return r.json()["user"]


def account_code(client: TestClient, purpose: str, channel: str = "phone", target: str | None = None):
    body: dict = {"channel": channel, "purpose": purpose}
    if target is not None:
        body["target"] = target
    return client.post("/api/account/code", json=body)


def mail_code(mailer: RecordingMailer) -> str:
    return re.search(r"(\d{6})", mailer.sent[-1].text).group(1)


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


# ------------------------------------------------------------------------------------- bind / unbind (85–87)
def test_bind_and_unbind_a_phone(client: TestClient, app, settings, sms, frozen_clock):
    root = register(client, "root")  # a password account (admin)
    r = account_code(client, "bind_phone", target=" 138 0013 8000 ")
    assert r.status_code == 202 and r.json() == {"sent": True, "expires_in_s": 600}
    assert sms.sent[-1].to == E164 and sms.sent[-1].template == "100004"
    row = rows(settings, "SELECT * FROM login_codes")[0]
    assert (row["purpose"], row["user_id"], row["target"]) == ("bind_phone", root["id"], E164)
    r = client.post("/api/account/identities/phone", json={"target": OTHER, "code": sms.sent[-1].code})
    assert r.status_code == 400 and error_code(r) == "invalid_code" and details(r) == {"attempts_left": 0}  # another number: no live code for it
    r = client.post("/api/account/identities/phone", json={"target": PHONE, "code": sms.sent[-1].code})
    assert r.status_code == 200, r.text
    assert r.json()["user"]["phone_masked"] == "138****8000" and r.json()["user"]["has_password"] is True and set(r.json()) == {"user"}
    identity = rows(settings, "SELECT * FROM identities")[0]
    assert (identity["user_id"], identity["subject"], identity["verified_at"], identity["last_login_at"]) == (root["id"], E164, NOW_ISO, NOW_ISO)
    assert client.get("/api/auth/me").json()["user"]["phone_masked"] == "138****8000"
    assert client.get("/api/admin/users").json()["items"][0]["phone_masked"] == "138****8000"  # AdminUser carries it too
    r = account_code(client, "bind_phone", target=PHONE)
    assert r.status_code == 409 and error_code(r) == "invalid_transition" and details(r) == {"reason": "already_bound"}
    frozen_clock.advance(minutes=1)
    r = account_code(client, "bind_phone", target=OTHER)
    assert r.status_code == 202
    r = client.post("/api/account/identities/phone", json={"target": OTHER, "code": sms.sent[-1].code})
    assert r.status_code == 409 and error_code(r) == "invalid_transition" and details(r) == {"reason": "already_bound"}  # one phone per account: use 88
    # another account cannot take the bound number
    bob_c = second_client(app)
    register(bob_c, "bob")
    r = account_code(bob_c, "bind_phone", target=PHONE)
    assert r.status_code == 409 and error_code(r) == "identity_taken"
    for bad in ({"channel": "email", "purpose": "bind_phone", "target": "a@example.com"}, {"channel": "phone", "purpose": "bind_phone"}, {"channel": "phone", "purpose": "rebind_phone"}, {"channel": "phone", "purpose": "reauth"}, {"channel": "email", "purpose": "reauth"}):
        r = bob_c.post("/api/account/code", json=bad)
        assert r.status_code == 400 and error_code(r) == "validation_error", bad
    r = bob_c.post("/api/account/code", json={"channel": "phone", "purpose": "bind_phone", "target": "12345"})
    assert r.status_code == 400 and error_code(r) == "invalid_phone"
    # the password login by phone works; unbinding needs the password (the account has one) and keeps the password login
    assert bob_c.post("/api/auth/login", json={"username": PHONE, "password": PW}).status_code == 200  # bob's client, root's number + password
    r = client.request("DELETE", "/api/account/identities/phone", json={"code": "123456"})
    assert r.status_code == 400 and error_code(r) == "validation_error" and "password" in details(r)["fields"]
    r = client.request("DELETE", "/api/account/identities/phone", json={"password": "wrong-password-1"})
    assert r.status_code == 401 and error_code(r) == "invalid_credentials"
    r = client.request("DELETE", "/api/account/identities/phone", json={"password": PW})
    assert r.status_code == 200 and r.json()["user"]["phone_masked"] is None
    assert count(settings, "identities") == 0
    r = client.request("DELETE", "/api/account/identities/phone", json={"password": PW})
    assert r.status_code == 409 and error_code(r) == "invalid_transition" and details(r) == {"reason": "no_phone"}
    r = client.request("DELETE", "/api/account/identities/phone", json={})
    assert r.status_code == 400 and error_code(r) == "validation_error"
    app.state.sms = None
    r = account_code(client, "bind_phone", target=OTHER)
    assert r.status_code == 409 and error_code(r) == "sms_unconfigured"


def test_bind_code_checks_count_failures_per_number_and_ip(client: TestClient, app, settings, sms, frozen_clock):
    """API.md §1 for the logged-in endpoints too (86, like 88 / 10): 20 failed checks on one number → the 21st is 429 before the code
    is looked at; the IP window counts the same failures; a correct code spends neither (the login:ip rule)."""
    register(client, "root")
    for _ in range(20):
        r = client.post("/api/account/identities/phone", json={"target": PHONE, "code": "000000"})
        assert r.status_code == 400 and error_code(r) == "invalid_code" and details(r) == {"attempts_left": 0}  # no live code: a failed check
    r = client.post("/api/account/identities/phone", json={"target": "138 0013 8000", "code": "000000"})
    assert r.status_code == 429 and error_code(r) == "rate_limited" and details(r) == {"retry_after_s": 3600} and r.headers["Retry-After"] == "3600"
    assert count(settings, "auth_throttle", "key = 'code_check:target:+8613800138000' AND count = 20") == 1  # the refusal was not counted
    assert count(settings, "auth_throttle", "key = 'code_check:ip:testclient' AND count = 20") == 1
    # another number is still checked (40 left on the IP window), and a correct code is never counted
    assert account_code(client, "bind_phone", target=OTHER).status_code == 202
    r = client.post("/api/account/identities/phone", json={"target": OTHER, "code": sms.sent[-1].code})
    assert r.status_code == 200 and r.json()["user"]["phone_masked"] == "139****9000"
    assert count(settings, "auth_throttle", "key = 'code_check:target:+8613900139000'") == 0
    assert count(settings, "auth_throttle", "key = 'code_check:ip:testclient' AND count = 20") == 1
    frozen_clock.advance(hours=1)
    r = client.post("/api/account/identities/phone", json={"target": PHONE, "code": "000000"})
    assert r.status_code == 400 and error_code(r) == "invalid_code"  # a fresh hour: checked again (and refused: the account has a phone)


def test_unbind_keeps_at_least_one_login_method(client: TestClient, app, settings, sms, frozen_clock):
    register(client, "root")
    learner = second_client(app)
    user = code_account(learner, sms)
    r = account_code(learner, "reauth")
    assert r.status_code == 429 and r.headers["Retry-After"] == "60"  # the login code went to the same number this minute (one send window per target)
    frozen_clock.advance(minutes=1)
    r = account_code(learner, "reauth")
    assert r.status_code == 202 and sms.sent[-1].template == "100005" and rows(settings, "SELECT purpose, user_id FROM login_codes WHERE purpose = 'reauth'")[0] == {"purpose": "reauth", "user_id": user["id"]}
    r = learner.request("DELETE", "/api/account/identities/phone", json={"password": PW})
    assert r.status_code == 400 and error_code(r) == "validation_error" and "code" in details(r)["fields"]  # no password on this account: a code is needed
    r = learner.request("DELETE", "/api/account/identities/phone", json={"code": sms.sent[-1].code})
    assert r.status_code == 409 and error_code(r) == "last_login_method"  # the phone is the only way in
    assert count(settings, "identities") == 1 and count(settings, "login_codes", "purpose = 'reauth' AND used_at IS NULL") == 1  # the code survives the refusal
    r = learner.post("/api/account/profile", json={"display_name": "小明", "age_band": "14plus", "password": PW})
    assert r.status_code == 200 and r.json()["user"]["has_password"] is True
    r = learner.request("DELETE", "/api/account/identities/phone", json={"code": sms.sent[-1].code})
    assert r.status_code == 400 and error_code(r) == "validation_error"  # with a password the password is the factor
    r = learner.request("DELETE", "/api/account/identities/phone", json={"password": PW})
    assert r.status_code == 200 and r.json()["user"]["phone_masked"] is None and r.json()["user"]["has_password"] is True


def test_rebind_the_phone(client: TestClient, app, settings, sms, frozen_clock):
    root = register(client, "root")
    account_code(client, "bind_phone", target=PHONE)
    client.post("/api/account/identities/phone", json={"target": PHONE, "code": sms.sent[-1].code})
    frozen_clock.advance(minutes=1)  # one send window per target
    r = account_code(client, "rebind_phone")
    assert r.status_code == 202 and sms.sent[-1].to == E164 and sms.sent[-1].template == "100002"
    code_old = sms.sent[-1].code
    r = account_code(client, "bind_phone", target=OTHER)
    assert r.status_code == 202 and sms.sent[-1].to == OTHER_E164 and sms.sent[-1].template == "100004"
    code_new = sms.sent[-1].code
    r = client.post("/api/account/identities/phone/rebind", json={"code_old": "000000" if code_old != "000000" else "111111", "target_new": OTHER, "code_new": code_new})
    assert r.status_code == 400 and error_code(r) == "invalid_code" and details(r) == {"attempts_left": 4}
    r = client.post("/api/account/identities/phone/rebind", json={"code_old": code_old, "target_new": PHONE, "code_new": code_new})
    assert r.status_code == 409 and error_code(r) == "invalid_transition" and details(r) == {"reason": "already_bound"}
    # the new number taken by somebody else meanwhile
    bob_c = second_client(app)
    frozen_clock.advance(minutes=1)
    bob = code_account(bob_c, sms, OTHER)
    r = client.post("/api/account/identities/phone/rebind", json={"code_old": code_old, "target_new": OTHER, "code_new": code_new})
    assert r.status_code == 409 and error_code(r) == "identity_taken"
    assert count(settings, "login_codes", "used_at IS NULL AND user_id = ?", (root["id"],)) == 2  # both codes still live after the refusal
    frozen_clock.advance(minutes=1)
    assert account_code(bob_c, "reauth").status_code == 202
    assert bob_c.request("DELETE", "/api/account", json={"code": sms.sent[-1].code}).status_code == 204  # bob leaves (frees the number)
    assert count(settings, "users", "id = ?", (bob["id"],)) == 0
    frozen_clock.advance(minutes=1)
    r = client.post("/api/account/identities/phone/rebind", json={"code_old": code_old, "target_new": OTHER, "code_new": code_new})
    assert r.status_code == 200 and r.json()["user"]["phone_masked"] == "139****9000"
    identity = rows(settings, "SELECT * FROM identities WHERE user_id = ?", (root["id"],))[0]
    assert identity["subject"] == OTHER_E164 and identity["verified_at"] == "2026-10-14T00:04:00Z" and identity["disputed_at"] is None
    assert count(settings, "login_codes", "used_at IS NULL") == 0
    assert client.post("/api/auth/login", json={"username": OTHER, "password": PW}).status_code == 200
    assert client.post("/api/auth/login", json={"username": PHONE, "password": PW}).status_code == 401
    r = client.post("/api/account/identities/phone/rebind", json={"code_old": "123456", "target_new": "+15551234567", "code_new": "123456"})
    assert r.status_code == 400 and error_code(r) == "invalid_phone"


# ------------------------------------------------------------------------------------- first-time profile (89)
def test_profile_first_time_setup(client: TestClient, app, settings, sms):
    register(client, "root")
    learner = second_client(app)
    user = code_account(learner, sms)
    assert learner.get("/api/auth/me").json()["user"]["needs_profile"] is True
    r = learner.post("/api/account/profile", json={"display_name": "小明", "age_band": "u14"})
    assert r.status_code == 400 and error_code(r) == "validation_error" and details(r)["fields"] == {"age_band": "未满 14 周岁的同学请由家长注册"}  # child accounts arrive in 1-B
    r = learner.post("/api/account/profile", json={"display_name": "小明", "age_band": "adult", "username": "13800138000"})
    assert r.status_code == 400 and error_code(r) == "validation_error" and details(r)["fields"] == {"username": "用户名不能是手机号"}  # the endpoint 2 rule
    r = learner.post("/api/account/profile", json={"display_name": "小明", "age_band": "adult", "username": "root"})
    assert r.status_code == 409 and error_code(r) == "username_taken"
    r = learner.post("/api/account/profile", json={"display_name": "小明", "age_band": "adult", "username": "xiaoming", "password": "password123"})
    assert r.status_code == 400 and error_code(r) == "weak_password"
    assert learner.get("/api/auth/me").json()["user"]["needs_profile"] is True  # nothing saved by a refused request
    r = learner.post("/api/account/profile", json={"display_name": " 小明 ", "age_band": "14plus", "username": "XiaoMing", "password": PW})
    assert r.status_code == 200, r.text
    saved = r.json()["user"]
    assert saved["display_name"] == "小明" and saved["username"] == "XiaoMing" and saved["age_band"] == "14plus"
    assert saved["has_password"] is True and saved["needs_profile"] is False and saved["phone_masked"] == "138****8000" and saved["id"] == user["id"]
    assert (saved["account_kind"], saved["is_child"], saved["needs_profile_prompt"]) == ("learner", False, False)  # slice 1-B: the default kind; a declared band is never prompted
    row = rows(settings, "SELECT * FROM users WHERE id = ?", (user["id"],))[0]
    assert (row["age_band"], row["age_declared_at"], row["age_declared_ip"], row["password_set_at"]) == ("14plus", NOW_ISO, "testclient", NOW_ISO)
    assert learner.get("/api/auth/me").status_code == 200  # the session survives the password set
    assert learner.get("/api/auth/me").json()["user"]["needs_profile"] is False
    r = learner.post("/api/account/profile", json={"display_name": "小明", "age_band": "adult"})
    assert r.status_code == 409 and error_code(r) == "invalid_transition" and details(r) == {"reason": "profile_done"}
    assert second_client(app).post("/api/auth/login", json={"username": "xiaoming", "password": PW}).status_code == 200
    # a nickname alone is enough; the placeholder username stays until the learner picks one (never again after)
    other = second_client(app)
    bob = code_account(other, sms, OTHER)
    r = other.post("/api/account/profile", json={"display_name": "小鲍", "age_band": "adult"})
    assert r.status_code == 200 and r.json()["user"]["username"] == bob["username"] and r.json()["user"]["has_password"] is False and r.json()["user"]["needs_profile"] is False
    for bad in ({"display_name": "", "age_band": "adult"}, {"display_name": "x" * 33, "age_band": "adult"}, {"age_band": "adult"}, {"display_name": "a", "age_band": "adult", "username": "x"}):
        r = other.post("/api/account/profile", json=bad)
        assert r.status_code == 400 and error_code(r) == "validation_error", bad
    assert register(second_client(app), "dave")["needs_profile"] is False  # a password registration never needs the step


# --------------------------------------------------------------------------- re-authentication of 7 / 8 (code or password)
def test_change_password_and_delete_with_a_reauth_code(client: TestClient, app, settings, sms, frozen_clock):
    register(client, "root")
    learner = second_client(app)
    user = code_account(learner, sms)
    r = learner.post("/api/account/password", json={"current_password": PW, "new_password": PW2})
    assert r.status_code == 400 and error_code(r) == "validation_error" and "code" in details(r)["fields"]  # no password yet: a code is the factor
    r = learner.post("/api/account/password", json={"new_password": PW2})
    assert r.status_code == 400 and error_code(r) == "validation_error"  # exactly one factor (schema)
    r = learner.post("/api/account/password", json={"current_password": PW, "code": "123456", "new_password": PW2})
    assert r.status_code == 400 and error_code(r) == "validation_error"
    key = f"pwcheck:user:{user['id']}"
    r = learner.post("/api/account/password", json={"code": "123456", "new_password": PW2})
    assert r.status_code == 400 and error_code(r) == "invalid_code" and details(r) == {"attempts_left": 0}  # no live reauth code
    assert count(settings, "auth_throttle", "key = ? AND count = 1", (key,)) == 1  # the attempt spent the pwcheck budget
    frozen_clock.advance(minutes=1)  # one send window per target
    assert account_code(learner, "reauth").status_code == 202 and sms.sent[-1].template == "100005"
    code = sms.sent[-1].code
    wrong = "000000" if code != "000000" else "111111"
    r = learner.post("/api/account/password", json={"code": wrong, "new_password": PW2})
    assert r.status_code == 400 and details(r) == {"attempts_left": 4}
    r = learner.post("/api/account/password", json={"code": code, "new_password": "password123"})
    assert r.status_code == 400 and error_code(r) == "weak_password"
    assert count(settings, "login_codes", "purpose = 'reauth' AND used_at IS NULL") == 1  # a weak password does not spend the code
    other = second_client(app)
    other.cookies.set("wd_session", learner.cookies["wd_session"])
    assert other.get("/api/auth/me").status_code == 200
    r = learner.post("/api/account/password", json={"code": code, "new_password": PW2})
    assert r.status_code == 204
    assert count(settings, "auth_throttle", "key = ?", (key,)) == 0  # cleared by the success
    assert count(settings, "login_codes", "purpose = 'reauth' AND used_at IS NULL") == 0
    assert learner.get("/api/auth/me").json()["user"]["has_password"] is True
    assert second_client(app).post("/api/auth/login", json={"username": PHONE, "password": PW2}).status_code == 200
    # with a password the password is the factor
    r = learner.post("/api/account/password", json={"code": code, "new_password": PW})
    assert r.status_code == 400 and error_code(r) == "validation_error" and "current_password" in details(r)["fields"]
    assert learner.post("/api/account/password", json={"current_password": PW2, "new_password": PW}).status_code == 204
    # the pwcheck budget bounds code guesses too (10 per 15 min)
    bob_c = second_client(app)
    bob = code_account(bob_c, sms, OTHER)
    for _ in range(10):
        assert bob_c.request("DELETE", "/api/account", json={"code": "123456"}).status_code == 400
    r = bob_c.request("DELETE", "/api/account", json={"code": "123456"})
    assert r.status_code == 429 and error_code(r) == "rate_limited" and details(r)["retry_after_s"] == 900
    frozen_clock.advance(minutes=15)
    assert account_code(bob_c, "reauth").status_code == 202
    r = bob_c.request("DELETE", "/api/account", json={"password": PW})
    assert r.status_code == 400 and error_code(r) == "validation_error"
    r = bob_c.request("DELETE", "/api/account", json={"code": sms.sent[-1].code})
    assert r.status_code == 204 and "wd_session=" in r.headers["set-cookie"].lower()
    assert count(settings, "users", "id = ?", (bob["id"],)) == 0 and count(settings, "identities", "user_id = ?", (bob["id"],)) == 0 and count(settings, "login_codes", "user_id = ?", (bob["id"],)) == 0


def test_reauth_code_by_email_and_the_last_login_method_of_the_email_field(client: TestClient, app, settings, mailer, sms, frozen_clock):
    register(client, "root")
    learner = second_client(app)
    user = email_account(learner, mailer)
    r = account_code(learner, "reauth", channel="phone")
    assert r.status_code == 400 and error_code(r) == "validation_error"  # no phone
    frozen_clock.advance(minutes=1)  # one send window per target
    r = account_code(learner, "reauth", channel="email")
    assert r.status_code == 202 and mailer.sent[-1].to == "alice@example.com" and "身份确认" in mailer.sent[-1].subject
    assert rows(settings, "SELECT channel, purpose, user_id FROM login_codes WHERE purpose = 'reauth'")[0] == {"channel": "email", "purpose": "reauth", "user_id": user["id"]}
    # the e-mail is this account's only login method: it cannot be cleared or changed
    r = learner.put("/api/account", json={"email": None})
    assert r.status_code == 409 and error_code(r) == "last_login_method"
    r = learner.put("/api/account", json={"email": "other@example.com"})
    assert r.status_code == 409 and error_code(r) == "last_login_method"
    assert learner.put("/api/account", json={"email": "ALICE@example.com"}).status_code == 200  # the same address: nothing changes
    assert learner.put("/api/account", json={"display_name": "小丽"}).status_code == 200
    r = learner.post("/api/account/password", json={"code": mail_code(mailer), "new_password": PW})
    assert r.status_code == 204
    r = learner.put("/api/account", json={"email": "other@example.com"})  # with a password the e-mail may change (and loses its verification)
    assert r.status_code == 200 and r.json()["user"]["email"] == "other@example.com" and r.json()["user"]["email_verified"] is False
    # a phone-only code account may clear an unverified e-mail; a verified one is then its second method, so clearing is fine too
    other = second_client(app)
    code_account(other, sms)
    assert other.put("/api/account", json={"email": "p@example.com"}).status_code == 200
    assert other.put("/api/account", json={"email": None}).status_code == 200
