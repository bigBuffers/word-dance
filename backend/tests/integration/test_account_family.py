"""Endpoints 6 / 7 / 8 / 85–89 / 108–111 and GET /api/auth/me in slice 1-B (API.md §3 / §3.2): the child restriction list (403
guardian_required whatever the session), the session block of /me (the guardian behind a switched session, the 家长门 stamp), the
account_kind rules of the profile step (a guardian needs the adult band and a second factor; a claim-created guardian keeps its kind),
deleting a guardian with children (has_children / delete_children: a child with its own phone is set free, the rest deleted, the
event), the two-factor guards of 6 / 87 for a guardian with children, the claim flow 「这是孩子的账号」 (108 / 109: an unknown number →
a placeholder guardian account, a learner turned guardian, a child / a disabled guardian / an admin / the own number refused, attempts
and burn, the stamps and the event) and the legacy 「补充信息」 prompt (110 declare once, 111 snooze 30 days)."""

from __future__ import annotations

import json
import logging
import re

import pytest
from fastapi.testclient import TestClient

from wd import db, family, security
from wd.clock import to_iso
from wd.delivery.mailer import RecordingMailer
from wd.delivery.sms import RecordingSmsSender

PW = "Correct-Horse-7"
PW2 = "New-Pass-Word-9"
NOW_ISO = "2026-10-14T00:00:00Z"
PHONE, E164 = "13800138000", "+8613800138000"
OTHER, OTHER_E164 = "13900139000", "+8613900139000"
THIRD, THIRD_E164 = "13700137000", "+8613700137000"
FOURTH, FOURTH_E164 = "13600136000", "+8613600136000"
PIN = "135790"
PLACEHOLDER_RE = re.compile(r"^u_[a-z2-7]{8}$")
GUARDIAN_ADULT_ZH = "家长请选择「我是成人」"
GUARDIAN_PASSWORD_ZH = "家长账号需要设置密码"
GUARDIAN_PHONE_ZH = "请输入家长的手机号"
# the child restriction list (API.md §1): method, path, body — 104 is covered by test_auth_family (a child never satisfies G)
RESTRICTED = (
    ("PUT", "/api/account", {"display_name": "x"}),
    ("POST", "/api/account/password", {"current_password": PW, "new_password": PW2}),
    ("DELETE", "/api/account", {"password": PW}),
    ("POST", "/api/account/email/request-code", None),
    ("POST", "/api/account/email/verify", {"code": "123456"}),
    ("POST", "/api/account/code", {"channel": "phone", "purpose": "reauth"}),
    ("POST", "/api/account/identities/phone", {"target": OTHER, "code": "123456"}),
    ("DELETE", "/api/account/identities/phone", {"password": PW}),
    ("POST", "/api/account/identities/phone/rebind", {"code_old": "123456", "target_new": OTHER, "code_new": "123456"}),
    ("POST", "/api/account/profile", {"display_name": "x", "age_band": "adult"}),
    ("POST", "/api/account/guardian/code", {"target": OTHER}),
    ("POST", "/api/account/guardian", {"target": OTHER, "code": "123456", "age_band": "14plus"}),
    ("POST", "/api/account/declare", {"account_kind": "learner", "age_band": "14plus"}),
    ("POST", "/api/account/declare/skip", None),
)


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


def register(c: TestClient, username: str, **extra) -> dict:
    """A pre-1-A style account: username + password, nothing declared (``needs_profile_prompt``)."""
    r = c.post("/api/auth/register", json={"username": username, "password": PW, **extra})
    assert r.status_code == 201, r.text
    return r.json()["user"]


def bootstrap(client: TestClient) -> dict:
    return register(client, "root")


def code_account(c: TestClient, sms: RecordingSmsSender, target: str = PHONE) -> dict:
    """A code-created account (phone channel) logged in on ``c`` — a placeholder username, the phone identity, no password."""
    assert c.post("/api/auth/code", json={"channel": "phone", "target": target, "purpose": "login", "consent": True}).status_code == 202
    r = c.post("/api/auth/code/login", json={"channel": "phone", "target": target, "code": sms.sent[-1].code})
    assert r.status_code == 201, r.text
    return r.json()["user"]


def email_account(c: TestClient, mailer: RecordingMailer, email: str) -> dict:
    assert c.post("/api/auth/code", json={"channel": "email", "target": email, "purpose": "login", "consent": True}).status_code == 202
    r = c.post("/api/auth/code/login", json={"channel": "email", "target": email, "code": mail_code(mailer)})
    assert r.status_code == 201, r.text
    return r.json()["user"]


def mail_code(mailer: RecordingMailer) -> str:
    return re.search(r"(\d{6})", mailer.sent[-1].text).group(1)


def make_guardian(app, settings, sms: RecordingSmsSender, *, phone: str = PHONE, display_name: str = "妈妈") -> tuple[TestClient, dict]:
    """A READY guardian: a code sign-up (the live phone identity) + the first-time profile as 家长 with a password (the second factor)."""
    c = second_client(app)
    code_account(c, sms, phone)
    r = c.post("/api/account/profile", json={"display_name": display_name, "account_kind": "guardian", "age_band": "adult", "password": PW})
    assert r.status_code == 200, r.text
    assert r.json()["user"]["account_kind"] == "guardian" and r.json()["user"]["has_password"] is True
    return c, r.json()["user"]


def gate(c: TestClient, **factor):
    return c.post("/api/guardian/gate", json=factor)


def add_child(c: TestClient, display_name: str = "小明", **extra) -> dict:
    r = c.post("/api/guardian/children", json={"display_name": display_name, **extra})
    assert r.status_code == 201, r.text
    return r.json()["child"]


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


def child_session(settings, child_id: int, token_hash: str = "child-device") -> None:
    execute(settings, "INSERT INTO sessions(token_hash, user_id, created_at, expires_at, last_seen_at) VALUES (?, ?, ?, '2027-01-12T00:00:00Z', ?)", (token_hash, child_id, NOW_ISO, NOW_ISO))


# ------------------------------------------------------------------------------------ the restriction list
def test_child_accounts_get_guardian_required_on_the_restriction_list(client: TestClient, app, settings, sms):
    bootstrap(client)
    tablet, mum = make_guardian(app, settings, sms)
    assert gate(tablet, password=PW).status_code == 200
    kid = add_child(tablet, "小明", pin=PIN)["id"]
    assert tablet.post(f"/api/auth/switch/{kid}").status_code == 200  # a switched child session (104)
    for method, path, body in RESTRICTED:
        r = tablet.request(method, path, json=body) if body is not None else tablet.request(method, path)
        assert r.status_code == 403 and error_code(r) == "guardian_required", (method, path, r.text)
    # nothing happened: no code sent, nothing deleted, declared or snoozed
    assert count(settings, "users", "id = ?", (kid,)) == 1 and count(settings, "login_codes", "user_id = ?", (kid,)) == 0 and count(settings, "family_codes", "kind = 'claim_guardian'") == 0
    assert rows(settings, "SELECT profile_prompted_at, display_name, age_band FROM users WHERE id = ?", (kid,))[0] == {"profile_prompted_at": None, "display_name": "小明", "age_band": "u14"}
    # learning, settings, the bank and the export stay open to the child
    assert tablet.get("/api/settings").status_code == 200
    assert tablet.put("/api/settings", json={"auto_pronounce": False}).status_code == 200
    assert tablet.get("/api/bank").status_code == 200
    assert tablet.get("/api/account/export").status_code == 200
    # the child's own device signed in by a login code (a self session, 107) is restricted the same way — the list is the account's
    assert tablet.post("/api/auth/switch/back", json={"pin": PIN}).status_code == 200
    code = tablet.post(f"/api/guardian/children/{kid}/login-code").json()["code"]
    device = second_client(app)
    assert device.post("/api/auth/child-login", json={"code": code}).status_code == 200
    for method, path, body in (("POST", "/api/account/profile", {"display_name": "x", "age_band": "adult"}), ("PUT", "/api/account", {"display_name": "x"}), ("POST", "/api/account/declare/skip", None)):
        r = device.request(method, path, json=body) if body is not None else device.request(method, path)
        assert r.status_code == 403 and error_code(r) == "guardian_required", path
    me = device.get("/api/auth/me").json()
    assert me["user"]["is_child"] is True and me["user"]["account_kind"] == "learner" and me["session"] == {"guardian": None, "gate_until": None}
    # a learner and a guardian are not restricted
    assert client.put("/api/account", json={"display_name": "root2"}).status_code == 200
    assert tablet.put("/api/account", json={"display_name": "妈妈"}).status_code == 200


# ---------------------------------------------------------------------------------------------- /me (5)
def test_me_carries_the_session_block(client: TestClient, app, settings, sms, frozen_clock):
    bootstrap(client)
    me = client.get("/api/auth/me").json()
    assert set(me) == {"user", "settings", "server", "counters", "session"}
    assert me["session"] == {"guardian": None, "gate_until": None}
    assert (me["user"]["account_kind"], me["user"]["is_child"], me["user"]["needs_profile_prompt"]) == ("learner", False, True)  # nothing declared yet (admins included)
    tablet, mum = make_guardian(app, settings, sms)
    assert (mum["account_kind"], mum["is_child"], mum["needs_profile_prompt"]) == ("guardian", False, False)
    assert tablet.get("/api/auth/me").json()["session"] == {"guardian": None, "gate_until": None}  # a guardian before the gate
    frozen_clock.advance(minutes=1)
    r = gate(tablet, password=PW)
    assert r.status_code == 200 and r.json() == {"gate_until": "2026-10-14T00:11:00Z"}
    assert tablet.get("/api/auth/me").json()["session"] == {"guardian": None, "gate_until": "2026-10-14T00:11:00Z"}
    kid = add_child(tablet, "小明", pin=PIN)["id"]
    assert tablet.post(f"/api/auth/switch/{kid}").status_code == 200
    me = tablet.get("/api/auth/me").json()
    assert me["user"]["id"] == kid and me["user"]["is_child"] is True
    assert me["session"] == {"guardian": {"id": mum["id"], "display_name": "妈妈"}, "gate_until": None}  # the SPA shows 「切回家长」
    laptop = second_client(app)  # the guardian's other device: its own session, no stamp
    assert laptop.post("/api/auth/login", json={"username": PHONE, "password": PW}).status_code == 200
    assert laptop.get("/api/auth/me").json()["session"] == {"guardian": None, "gate_until": None}
    # back on the tablet: the new guardian session carries the stamp (105); it lapses after 10 minutes
    frozen_clock.advance(minutes=1)
    assert tablet.post("/api/auth/switch/back", json={"pin": PIN}).status_code == 200
    assert tablet.get("/api/auth/me").json()["session"] == {"guardian": None, "gate_until": "2026-10-14T00:12:00Z"}
    frozen_clock.advance(seconds=601)
    assert tablet.get("/api/auth/me").json()["session"] == {"guardian": None, "gate_until": None}
    # the admin list carries the three User fields too (AdminUser extends User)
    listing = client.get("/api/admin/users").json()["items"]
    by_name = {u["username"]: u for u in listing}
    assert (by_name["root"]["needs_profile_prompt"], by_name["root"]["account_kind"]) == (True, "learner")
    assert (by_name["妈妈"]["account_kind"] if "妈妈" in by_name else next(u for u in listing if u["id"] == mum["id"])["account_kind"]) == "guardian"
    assert next(u for u in listing if u["id"] == kid)["is_child"] is True


# ------------------------------------------------------------------------------------ the profile step (89)
def test_profile_account_kind_rules(client: TestClient, app, settings, sms, mailer, frozen_clock):
    bootstrap(client)
    learner = second_client(app)
    user = code_account(learner, sms)  # a phone account without a password
    r = learner.post("/api/account/profile", json={"display_name": "妈妈", "account_kind": "guardian", "age_band": "14plus", "password": PW})
    assert r.status_code == 400 and error_code(r) == "validation_error" and details(r)["fields"] == {"age_band": GUARDIAN_ADULT_ZH}
    r = learner.post("/api/account/profile", json={"display_name": "妈妈", "account_kind": "guardian", "age_band": "adult"})
    assert r.status_code == 400 and error_code(r) == "validation_error" and details(r)["fields"] == {"password": GUARDIAN_PASSWORD_ZH}
    r = learner.post("/api/account/profile", json={"display_name": "妈妈", "account_kind": "teacher", "age_band": "adult"})
    assert r.status_code == 400 and error_code(r) == "validation_error" and "account_kind" in details(r)["fields"]
    assert learner.get("/api/auth/me").json()["user"]["needs_profile"] is True  # nothing saved by a refused request
    r = learner.post("/api/account/profile", json={"display_name": "妈妈", "account_kind": "guardian", "age_band": "adult", "password": PW})
    assert r.status_code == 200, r.text
    saved = r.json()["user"]
    assert (saved["account_kind"], saved["has_password"], saved["age_band"], saved["needs_profile"], saved["is_child"], saved["needs_profile_prompt"]) == ("guardian", True, "adult", False, False, False)
    assert rows(settings, "SELECT account_kind, age_band, age_declared_ip FROM users WHERE id = ?", (user["id"],))[0] == {"account_kind": "guardian", "age_band": "adult", "age_declared_ip": "testclient"}
    assert learner.get("/api/guardian/children").json()["ready"] is True  # `G` from now on, both factors in place
    # a verified e-mail is the second factor: no password needed
    dad = second_client(app)
    email_account(dad, mailer, "dad@example.com")
    r = dad.post("/api/account/profile", json={"display_name": "爸爸", "account_kind": "guardian", "age_band": "adult"})
    assert r.status_code == 200 and r.json()["user"]["account_kind"] == "guardian" and r.json()["user"]["has_password"] is False
    assert dad.get("/api/guardian/children").json()["missing"] == ["phone"]
    # a password set through endpoint 7 before the profile step counts as well
    uncle = second_client(app)
    code_account(uncle, sms, OTHER)
    frozen_clock.advance(minutes=1)
    assert uncle.post("/api/account/code", json={"channel": "phone", "purpose": "reauth"}).status_code == 202
    assert uncle.post("/api/account/password", json={"code": sms.sent[-1].code, "new_password": PW}).status_code == 204
    r = uncle.post("/api/account/profile", json={"display_name": "叔叔", "account_kind": "guardian", "age_band": "adult"})
    assert r.status_code == 200 and r.json()["user"]["account_kind"] == "guardian" and r.json()["user"]["has_password"] is True
    # the default kind is learner and the 1-A rules stay (u14 refused, a nickname alone is enough)
    other = second_client(app)
    code_account(other, sms, THIRD)
    r = other.post("/api/account/profile", json={"display_name": "小鲍", "age_band": "u14"})
    assert r.status_code == 400 and details(r)["fields"] == {"age_band": "未满 14 周岁的同学请由家长注册"}
    r = other.post("/api/account/profile", json={"display_name": "小鲍", "age_band": "14plus"})
    assert r.status_code == 200 and (r.json()["user"]["account_kind"], r.json()["user"]["is_child"], r.json()["user"]["needs_profile_prompt"]) == ("learner", False, False)
    r = other.post("/api/account/profile", json={"display_name": "小鲍", "account_kind": "guardian", "age_band": "adult", "password": PW})
    assert r.status_code == 409 and details(r) == {"reason": "profile_done"}


# ------------------------------------------------------------------------------ deleting a guardian (8)
def test_delete_guardian_with_children(client: TestClient, app, settings, sms, frozen_clock):
    bootstrap(client)
    tablet, mum = make_guardian(app, settings, sms)
    assert gate(tablet, password=PW).status_code == 200
    ming = add_child(tablet, "小明", pin=PIN)["id"]
    hong = add_child(tablet, "小红")["id"]
    # 小红 holds her own phone (a claimed legacy account would); both children have live login codes, 小明 a signed-in device
    execute(settings, "INSERT INTO identities(user_id, provider, subject, verified_at, last_login_at, created_at) VALUES (?, 'phone', ?, ?, ?, ?)", (hong, OTHER_E164, NOW_ISO, NOW_ISO, NOW_ISO))
    hong_code = tablet.post(f"/api/guardian/children/{hong}/login-code").json()["code"]
    assert tablet.post(f"/api/guardian/children/{ming}/login-code").status_code == 201
    child_session(settings, ming)
    r = tablet.request("DELETE", "/api/account", json={"password": PW})
    assert r.status_code == 409 and error_code(r) == "has_children" and details(r) == {"children": [{"id": ming, "display_name": "小明"}, {"id": hong, "display_name": "小红"}]}
    r = tablet.request("DELETE", "/api/account", json={"password": PW, "delete_children": False})
    assert r.status_code == 409 and error_code(r) == "has_children"
    r = tablet.request("DELETE", "/api/account", json={"password": "wrong-password-1", "delete_children": True})
    assert r.status_code == 401 and error_code(r) == "invalid_credentials"
    assert count(settings, "users") == 4 and tablet.get("/api/auth/me").status_code == 200  # root, mum, 小明, 小红 — nothing happened
    r = tablet.request("DELETE", "/api/account", json={"password": PW, "delete_children": True})
    assert r.status_code == 204 and "wd_session=" in r.headers["set-cookie"].lower()
    assert count(settings, "users", "id IN (?, ?)", (mum["id"], ming)) == 0
    assert count(settings, "sessions", "user_id IN (?, ?)", (mum["id"], ming)) == 0 and count(settings, "family_codes", "user_id = ?", (ming,)) == 0 and count(settings, "user_settings", "user_id = ?", (ming,)) == 0
    freed = rows(settings, "SELECT guardian_user_id, account_kind, age_band, guardian_consent_at, display_name FROM users WHERE id = ?", (hong,))[0]
    assert freed == {"guardian_user_id": None, "account_kind": "learner", "age_band": "14plus", "guardian_consent_at": NOW_ISO, "display_name": "小红"}  # set free, data kept
    assert count(settings, "identities", "user_id = ?", (hong,)) == 1 and count(settings, "family_codes", "user_id = ? AND used_at IS NULL", (hong,)) == 0  # her login codes are void
    events = rows(settings, "SELECT detail_json FROM system_events WHERE kind = 'guardian_deleted'")
    assert len(events) == 1 and json.loads(events[0]["detail_json"]) == {"deleted": [ming], "emancipated": [hong], "guardian_id": mum["id"]}
    r = second_client(app).post("/api/auth/child-login", json={"code": hong_code})
    assert r.status_code == 400 and error_code(r) == "invalid_code"  # the voided code is dead on her device
    frozen_clock.advance(minutes=1)
    device = second_client(app)
    assert device.post("/api/auth/code", json={"channel": "phone", "target": OTHER, "purpose": "login", "consent": True}).status_code == 202
    r = device.post("/api/auth/code/login", json={"channel": "phone", "target": OTHER, "code": sms.sent[-1].code})
    assert r.status_code == 200 and r.json()["user"]["id"] == hong and r.json()["user"]["is_child"] is False  # a learner with her own number
    assert device.put("/api/account", json={"display_name": "小红红"}).status_code == 200  # no restriction list any more
    # a guardian without children deletes like anybody, without the event
    dad, dad_user = make_guardian(app, settings, sms, phone=THIRD, display_name="爸爸")
    assert dad.request("DELETE", "/api/account", json={"password": PW}).status_code == 204
    assert count(settings, "users", "id = ?", (dad_user["id"],)) == 0 and count(settings, "system_events", "kind = 'guardian_deleted'") == 1


# ------------------------------------------------------------------------------ the two-factor guards (6 / 87)
def test_guardian_with_children_keeps_both_factors(client: TestClient, app, settings, sms, mailer, frozen_clock):
    bootstrap(client)
    tablet, mum = make_guardian(app, settings, sms)  # the phone + a password
    assert gate(tablet, password=PW).status_code == 200
    add_child(tablet, "小明", pin=PIN)
    r = tablet.request("DELETE", "/api/account/identities/phone", json={"password": PW})
    assert r.status_code == 409 and error_code(r) == "guardian_factors_required" and details(r) == {"missing": ["phone"]}
    assert count(settings, "identities", "user_id = ?", (mum["id"],)) == 1
    r = tablet.put("/api/account", json={"email": "mum@example.com"})  # with a password the e-mail is free to change
    assert r.status_code == 200 and r.json()["user"]["email"] == "mum@example.com"
    # a guardian whose second factor is the verified e-mail: the e-mail is locked while children exist
    dad = second_client(app)
    dad_user = email_account(dad, mailer, "dad@example.com")
    assert dad.post("/api/account/profile", json={"display_name": "爸爸", "account_kind": "guardian", "age_band": "adult"}).status_code == 200
    frozen_clock.advance(minutes=1)
    assert dad.post("/api/account/code", json={"channel": "phone", "purpose": "bind_phone", "target": OTHER}).status_code == 202
    assert dad.post("/api/account/identities/phone", json={"target": OTHER, "code": sms.sent[-1].code}).status_code == 200
    frozen_clock.advance(minutes=1)
    assert dad.post("/api/account/code", json={"channel": "email", "purpose": "reauth"}).status_code == 202
    assert gate(dad, code=mail_code(mailer)).status_code == 200
    kid = add_child(dad, "小红", pin=PIN)["id"]
    for body in ({"email": None}, {"email": "other@example.com"}):
        r = dad.put("/api/account", json=body)
        assert r.status_code == 409 and error_code(r) == "guardian_factors_required" and details(r) == {"missing": ["second_factor"]}, body
    assert dad.put("/api/account", json={"email": "DAD@example.com"}).status_code == 200  # the same address: nothing changes
    assert dad.put("/api/account", json={"display_name": "老爸"}).status_code == 200
    assert rows(settings, "SELECT email, email_verified_at FROM users WHERE id = ?", (dad_user["id"],))[0] == {"email": "dad@example.com", "email_verified_at": NOW_ISO}
    # the phone of a password-less guardian with children is refused too (a reauth code is its factor; the code survives the refusal)
    frozen_clock.advance(minutes=1)
    assert dad.post("/api/account/code", json={"channel": "email", "purpose": "reauth"}).status_code == 202
    r = dad.request("DELETE", "/api/account/identities/phone", json={"code": mail_code(mailer)})
    assert r.status_code == 409 and error_code(r) == "guardian_factors_required" and details(r) == {"missing": ["phone"]}
    assert count(settings, "identities", "user_id = ?", (dad_user["id"],)) == 1 and count(settings, "login_codes", "purpose = 'reauth' AND used_at IS NULL") == 1
    # once the child is gone the 1-A rules alone apply: the e-mail may go (the phone stays as the login method)
    assert gate(dad, code=mail_code(mailer)).status_code == 200
    assert dad.delete(f"/api/guardian/children/{kid}").status_code == 204
    r = dad.put("/api/account", json={"email": None})
    assert r.status_code == 200 and r.json()["user"]["email"] is None


# ----------------------------------------------------------------------------------- the claim flow (108 / 109)
def test_claim_flow_turns_the_phone_owner_into_a_guardian(client: TestClient, app, settings, sms, frozen_clock, caplog):
    bootstrap(client)
    # an admin never becomes a child
    r = client.post("/api/account/guardian/code", json={"target": PHONE})
    assert r.status_code == 409 and error_code(r) == "invalid_transition" and details(r) == {"reason": "admin"}
    r = client.post("/api/account/guardian", json={"target": PHONE, "code": "123456", "age_band": "14plus"})
    assert r.status_code == 409 and details(r) == {"reason": "admin"}
    # lily: a pre-1-A account (username + password, nothing declared) that bound her own phone
    lily_c = second_client(app)
    lily = register(lily_c, "lily")
    assert lily["needs_profile_prompt"] is True and lily["is_child"] is False
    assert lily_c.post("/api/account/code", json={"channel": "phone", "purpose": "bind_phone", "target": OTHER}).status_code == 202
    assert lily_c.post("/api/account/identities/phone", json={"target": OTHER, "code": sms.sent[-1].code}).status_code == 200
    r = lily_c.post("/api/account/guardian/code", json={"target": "12345"})
    assert r.status_code == 400 and error_code(r) == "invalid_phone"
    r = lily_c.post("/api/account/guardian/code", json={"target": OTHER})
    assert r.status_code == 400 and error_code(r) == "validation_error" and details(r) == {"fields": {"target": GUARDIAN_PHONE_ZH}}  # her own number
    r = lily_c.post("/api/account/guardian", json={"target": PHONE, "code": "12345", "age_band": "14plus"})
    assert r.status_code == 400 and error_code(r) == "validation_error" and "code" in details(r)["fields"]
    app.state.sms = None
    r = lily_c.post("/api/account/guardian/code", json={"target": PHONE})
    assert r.status_code == 409 and error_code(r) == "sms_unconfigured"
    app.state.sms = sms
    # the claim code: a family_codes row sent under the 绑定 template, nothing in login_codes, never logged
    caplog.set_level(logging.INFO, logger="wd")
    login_codes_before = count(settings, "login_codes")
    r = lily_c.post("/api/account/guardian/code", json={"target": " 138 0013 8000 "})
    assert r.status_code == 202 and r.json() == {"sent": True, "expires_in_s": 600}
    assert sms.sent[-1].to == E164 and sms.sent[-1].template == "100004" and sms.sent[-1].minutes == 10
    code = sms.sent[-1].code
    assert count(settings, "login_codes") == login_codes_before
    row = rows(settings, "SELECT * FROM family_codes")[0]
    assert (row["kind"], row["user_id"], row["target"], row["attempts"], row["used_at"], row["expires_at"], row["ip"]) == ("claim_guardian", lily["id"], E164, 0, None, "2026-10-14T00:10:00Z", "testclient")
    assert code not in caplog.text and code not in str(row)
    # a wrong code counts on the row and on the §1 code-check windows; a wrong number finds no row
    wrong = "000000" if code != "000000" else "111111"
    r = lily_c.post("/api/account/guardian", json={"target": PHONE, "code": wrong, "age_band": "14plus"})
    assert r.status_code == 400 and error_code(r) == "invalid_code" and details(r) == {"attempts_left": 4}
    assert count(settings, "auth_throttle", "key = 'code_check:target:+8613800138000' AND count = 1") == 1 and count(settings, "auth_throttle", "key = 'code_check:ip:testclient' AND count = 1") == 1
    r = lily_c.post("/api/account/guardian", json={"target": THIRD, "code": code, "age_band": "14plus"})
    assert r.status_code == 400 and details(r) == {"attempts_left": 0}
    assert lily_c.get("/api/auth/me").json()["user"]["is_child"] is False and count(settings, "users") == 2
    # the claim: nobody owns the number → a placeholder guardian account holding the phone; lily becomes its child
    r = lily_c.post("/api/account/guardian", json={"target": PHONE, "code": code, "age_band": "14plus"})
    assert r.status_code == 200, r.text
    me = r.json()["user"]
    assert (me["id"], me["is_child"], me["account_kind"], me["age_band"], me["needs_profile_prompt"], me["phone_masked"]) == (lily["id"], True, "learner", "14plus", False, "139****9000")
    lily_row = rows(settings, "SELECT * FROM users WHERE id = ?", (lily["id"],))[0]
    g = rows(settings, "SELECT * FROM users WHERE id = ?", (lily_row["guardian_user_id"],))[0]
    assert (lily_row["account_kind"], lily_row["age_band"], lily_row["age_declared_at"], lily_row["age_declared_ip"], lily_row["guardian_consent_at"], lily_row["updated_at"]) == ("learner", "14plus", NOW_ISO, "testclient", NOW_ISO, NOW_ISO)
    assert g["account_kind"] == "guardian" and PLACEHOLDER_RE.match(g["username"]) and g["password_set_at"] is None and g["age_band"] is None and g["role"] == "user" and g["display_name"] is None
    assert not security.verify_password("", g["password_hash"]) and g["password_hash"].startswith("$2b$")
    identity = rows(settings, "SELECT * FROM identities WHERE user_id = ?", (g["id"],))[0]
    assert (identity["subject"], identity["verified_at"], identity["last_login_at"], identity["disputed_at"]) == (E164, NOW_ISO, None, None)
    assert count(settings, "user_settings", "user_id = ?", (g["id"],)) == 1
    assert rows(settings, "SELECT used_at FROM family_codes")[0]["used_at"] == NOW_ISO
    events = rows(settings, "SELECT detail_json FROM system_events WHERE kind = 'account_claimed'")
    assert len(events) == 1 and json.loads(events[0]["detail_json"]) == {"child_id": lily["id"], "guardian_created": True, "guardian_id": g["id"]}
    assert code not in caplog.text and [getattr(rec, "event", None) for rec in caplog.records if rec.name == "wd.routers.account"] == ["claim_code_sent", "account_claimed"]
    # from the next request on lily's session is a child session (a self session: no 「切回家长」)
    r = lily_c.put("/api/account", json={"display_name": "x"})
    assert r.status_code == 403 and error_code(r) == "guardian_required"
    me = lily_c.get("/api/auth/me").json()
    assert me["user"]["is_child"] is True and me["session"] == {"guardian": None, "gate_until": None}
    # the guardian's first code login: step 0 with 我是家长 fixed — 89 ignores `learner`, needs the adult band and a password
    frozen_clock.advance(minutes=1)
    mum = second_client(app)
    assert mum.post("/api/auth/code", json={"channel": "phone", "target": PHONE, "purpose": "login", "consent": True}).status_code == 202
    r = mum.post("/api/auth/code/login", json={"channel": "phone", "target": PHONE, "code": sms.sent[-1].code})
    assert r.status_code == 200 and r.json()["created"] is False
    assert (r.json()["user"]["id"], r.json()["user"]["needs_profile"], r.json()["user"]["account_kind"], r.json()["user"]["has_password"]) == (g["id"], True, "guardian", False)
    r = mum.post("/api/account/profile", json={"display_name": "妈妈", "account_kind": "learner", "age_band": "14plus", "password": PW})
    assert r.status_code == 400 and error_code(r) == "validation_error" and details(r)["fields"] == {"age_band": GUARDIAN_ADULT_ZH}
    r = mum.post("/api/account/profile", json={"display_name": "妈妈", "account_kind": "learner", "age_band": "adult"})
    assert r.status_code == 400 and details(r)["fields"] == {"password": GUARDIAN_PASSWORD_ZH}
    r = mum.post("/api/account/profile", json={"display_name": "妈妈", "account_kind": "learner", "age_band": "adult", "password": PW})
    assert r.status_code == 200 and r.json()["user"]["account_kind"] == "guardian" and r.json()["user"]["has_password"] is True and r.json()["user"]["needs_profile"] is False
    children = mum.get("/api/guardian/children")
    assert children.status_code == 200 and children.json()["ready"] is True and children.json()["pin_set"] is False
    (child,) = children.json()["items"]
    assert (child["id"], child["display_name"], child["username"], child["age_band"], child["phone_masked"], child["has_password"]) == (lily["id"], "lily", "lily", "14plus", "139****9000", True)
    # a known account becomes the guardian: a declared learner keeps its own band, a code-created one still in first-time setup declares at step 0
    carol = second_client(app)
    carol_user = code_account(carol, sms, THIRD)
    frozen_clock.advance(minutes=1)
    stamp = to_iso(frozen_clock.now_utc())
    dave_c = second_client(app)
    dave = register(dave_c, "dave")
    assert dave_c.post("/api/account/guardian/code", json={"target": THIRD}).status_code == 202
    r = dave_c.post("/api/account/guardian", json={"target": THIRD, "code": sms.sent[-1].code, "age_band": "u14"})
    assert r.status_code == 200 and r.json()["user"]["is_child"] is True and r.json()["user"]["age_band"] == "u14"
    carol_row = rows(settings, "SELECT * FROM users WHERE id = ?", (carol_user["id"],))[0]
    # carol is still in her first-time setup (placeholder username, no band): only the kind flips — step 0 (89) declares the band at her next visit
    assert (carol_row["account_kind"], carol_row["age_band"], carol_row["age_declared_at"], carol_row["age_declared_ip"], carol_row["guardian_user_id"], carol_row["updated_at"]) == ("guardian", None, None, None, None, stamp)
    assert rows(settings, "SELECT guardian_user_id, guardian_consent_at FROM users WHERE id = ?", (dave["id"],))[0] == {"guardian_user_id": carol_user["id"], "guardian_consent_at": stamp}
    assert json.loads(rows(settings, "SELECT detail_json FROM system_events WHERE kind = 'account_claimed' ORDER BY id DESC LIMIT 1")[0]["detail_json"]) == {"child_id": dave["id"], "guardian_created": False, "guardian_id": carol_user["id"]}
    assert carol.get("/api/auth/me").json()["user"]["account_kind"] == "guardian" and carol.get("/api/guardian/children").json()["items"][0]["id"] == dave["id"]
    assert carol.get("/api/auth/me").json()["user"]["needs_profile"] is True
    r = carol.post("/api/account/profile", json={"display_name": "Carol", "account_kind": "learner", "age_band": "14plus", "password": PW})
    assert r.status_code == 400 and details(r)["fields"] == {"age_band": GUARDIAN_ADULT_ZH}  # the kind is locked to guardian: adult + a password
    r = carol.post("/api/account/profile", json={"display_name": "Carol", "account_kind": "learner", "age_band": "adult", "password": PW})
    assert r.status_code == 200 and (r.json()["user"]["account_kind"], r.json()["user"]["age_band"], r.json()["user"]["needs_profile"]) == ("guardian", "adult", False)
    # a child's number cannot be claimed (lily is a child now); the refusal leaves the code live
    eve_c = second_client(app)
    eve = register(eve_c, "eve")
    assert eve_c.post("/api/account/guardian/code", json={"target": OTHER}).status_code == 202  # the answer never reveals the account behind the number
    r = eve_c.post("/api/account/guardian", json={"target": OTHER, "code": sms.sent[-1].code, "age_band": "14plus"})
    assert r.status_code == 409 and error_code(r) == "invalid_transition" and details(r) == {"reason": "guardian_is_child"}
    assert count(settings, "family_codes", "user_id = ? AND used_at IS NULL", (eve["id"],)) == 1 and rows(settings, "SELECT guardian_user_id FROM users WHERE id = ?", (eve["id"],))[0]["guardian_user_id"] is None
    # a disabled guardian
    execute(settings, "UPDATE users SET is_active = 0 WHERE id = ?", (carol_user["id"],))
    frank_c = second_client(app)
    register(frank_c, "frank")
    frozen_clock.advance(minutes=1)
    assert frank_c.post("/api/account/guardian/code", json={"target": THIRD}).status_code == 202
    r = frank_c.post("/api/account/guardian", json={"target": THIRD, "code": sms.sent[-1].code, "age_band": "14plus"})
    assert r.status_code == 409 and details(r) == {"reason": "guardian_disabled"}
    execute(settings, "UPDATE users SET is_active = 1 WHERE id = ?", (carol_user["id"],))
    # a guardian with children cannot become a child
    r = carol.post("/api/account/guardian/code", json={"target": PHONE})
    assert r.status_code == 409 and details(r) == {"reason": "has_children"}
    r = carol.post("/api/account/guardian", json={"target": PHONE, "code": "123456", "age_band": "14plus"})
    assert r.status_code == 409 and details(r) == {"reason": "has_children"}
    # five wrong guesses burn the code — the right one is dead afterwards and no guardian account was created
    frozen_clock.advance(hours=1)  # a fresh register:ip window (5 per hour) for the sixth account
    grace_c = second_client(app)
    grace = register(grace_c, "grace")
    assert grace_c.post("/api/account/guardian/code", json={"target": FOURTH}).status_code == 202
    good = sms.sent[-1].code
    bad = "000000" if good != "000000" else "111111"
    for left in (4, 3, 2, 1, 0):
        r = grace_c.post("/api/account/guardian", json={"target": FOURTH, "code": bad, "age_band": "14plus"})
        assert r.status_code == 400 and error_code(r) == "invalid_code" and details(r) == {"attempts_left": left}
    r = grace_c.post("/api/account/guardian", json={"target": FOURTH, "code": good, "age_band": "14plus"})
    assert r.status_code == 400 and details(r) == {"attempts_left": 0}
    assert rows(settings, "SELECT guardian_user_id FROM users WHERE id = ?", (grace["id"],))[0]["guardian_user_id"] is None and count(settings, "identities", "subject = ?", (FOURTH_E164,)) == 0
    # a second code to the same number within the minute is throttled like every send; a minute later the burnt row stays used
    r = grace_c.post("/api/account/guardian/code", json={"target": FOURTH})
    assert r.status_code == 429 and error_code(r) == "rate_limited"
    frozen_clock.advance(minutes=1)
    assert grace_c.post("/api/account/guardian/code", json={"target": FOURTH}).status_code == 202
    assert count(settings, "family_codes", "user_id = ?", (grace["id"],)) == 2 and count(settings, "family_codes", "user_id = ? AND used_at IS NULL", (grace["id"],)) == 1
    assert count(settings, "auth_throttle", "key LIKE 'login:%'") == 0  # never login:ip / the lockout


def test_u14_claim_detaches_the_accounts_own_contacts(client: TestClient, app, settings, sms, frozen_clock):
    """children.html §2: a child under 14 holds no phone or e-mail — a legacy account claimed as such loses its own phone identity and
    e-mail (and the e-mail reminders) with the claim; a 14plus claim keeps them (test_claim_flow_turns_the_phone_owner_into_a_guardian)."""
    bootstrap(client)
    mum, mum_user = make_guardian(app, settings, sms)
    tom_c = second_client(app)
    tom = register(tom_c, "tom")
    assert tom_c.post("/api/account/code", json={"channel": "phone", "purpose": "bind_phone", "target": OTHER}).status_code == 202
    assert tom_c.post("/api/account/identities/phone", json={"target": OTHER, "code": sms.sent[-1].code}).status_code == 200
    assert tom_c.put("/api/account", json={"email": "tom@example.com"}).status_code == 200
    execute(settings, "UPDATE user_settings SET email_enabled = 1 WHERE user_id = ?", (tom["id"],))
    frozen_clock.advance(hours=1)  # the §1 per-IP send window (three sends so far in this test)
    assert tom_c.post("/api/account/guardian/code", json={"target": PHONE}).status_code == 202
    r = tom_c.post("/api/account/guardian", json={"target": PHONE, "code": sms.sent[-1].code, "age_band": "u14"})
    assert r.status_code == 200, r.text
    me = r.json()["user"]
    assert (me["is_child"], me["age_band"], me["phone_masked"], me["email"], me["email_verified"]) == (True, "u14", None, None, False)
    assert count(settings, "identities", "user_id = ?", (tom["id"],)) == 0 and count(settings, "identities", "subject = ?", (OTHER_E164,)) == 0  # the number is free again
    row = rows(settings, "SELECT guardian_user_id, email, email_verified_at FROM users WHERE id = ?", (tom["id"],))[0]
    assert row == {"guardian_user_id": mum_user["id"], "email": None, "email_verified_at": None}
    assert rows(settings, "SELECT email_enabled FROM user_settings WHERE user_id = ?", (tom["id"],))[0]["email_enabled"] == 0
    assert mum.get("/api/guardian/children").json()["items"][0]["phone_masked"] is None
    # a guardian that already was one is left as it is
    g = rows(settings, "SELECT account_kind, age_band FROM users WHERE id = ?", (mum_user["id"],))[0]
    assert g == {"account_kind": "guardian", "age_band": "adult"}


def test_claim_refuses_a_minor_or_a_stale_holder_and_converts_an_admin(client: TestClient, app, settings, sms, frozen_clock):
    """API.md 109: the number's owner must be able to be a guardian — a self-declared 14plus minor never is (409 guardian_minor), a
    phone identity under the stale rule of 81 is not handed a child before its owner signs in with it (409 guardian_stale); both leave
    the code live. An admin holding the number becomes a guardian (and stays an admin)."""
    root = bootstrap(client)
    hank_c = second_client(app)
    hank = code_account(hank_c, sms, THIRD)
    assert hank_c.post("/api/account/profile", json={"display_name": "Hank", "account_kind": "learner", "age_band": "14plus", "password": PW}).status_code == 200
    ivy_c = second_client(app)
    ivy = register(ivy_c, "ivy")
    frozen_clock.advance(minutes=1)  # the per-number send interval
    assert ivy_c.post("/api/account/guardian/code", json={"target": THIRD}).status_code == 202
    r = ivy_c.post("/api/account/guardian", json={"target": THIRD, "code": sms.sent[-1].code, "age_band": "u14"})
    assert r.status_code == 409 and error_code(r) == "invalid_transition" and details(r) == {"reason": "guardian_minor"}
    assert rows(settings, "SELECT account_kind, age_band FROM users WHERE id = ?", (hank["id"],))[0] == {"account_kind": "learner", "age_band": "14plus"}
    assert count(settings, "family_codes", "user_id = ? AND used_at IS NULL", (ivy["id"],)) == 1 and ivy_c.get("/api/auth/me").json()["user"]["is_child"] is False
    # the admin binds a number and is claimed as a guardian: the kind flips, the role stays
    frozen_clock.advance(hours=1)  # the per-IP send window
    assert client.post("/api/account/code", json={"channel": "phone", "purpose": "bind_phone", "target": PHONE}).status_code == 202
    assert client.post("/api/account/identities/phone", json={"target": PHONE, "code": sms.sent[-1].code}).status_code == 200
    leo_c = second_client(app)
    register(leo_c, "leo")
    frozen_clock.advance(minutes=1)
    assert leo_c.post("/api/account/guardian/code", json={"target": PHONE}).status_code == 202
    r = leo_c.post("/api/account/guardian", json={"target": PHONE, "code": sms.sent[-1].code, "age_band": "14plus"})
    assert r.status_code == 200, r.text
    assert rows(settings, "SELECT account_kind, role, age_band FROM users WHERE id = ?", (root["id"],))[0] == {"account_kind": "guardian", "role": "admin", "age_band": "adult"}
    assert client.get("/api/guardian/children").json()["items"][0]["display_name"] == "leo"
    # jane: an adult learner whose phone identity goes stale (no code login for WD_PHONE_STALE_DAYS)
    frozen_clock.advance(hours=1)
    jane_c = second_client(app)
    jane = code_account(jane_c, sms, FOURTH)
    assert jane_c.post("/api/account/profile", json={"display_name": "Jane", "account_kind": "learner", "age_band": "adult", "password": PW}).status_code == 200
    frozen_clock.advance(days=int(settings.phone_stale_days) + 1)
    kate_c = second_client(app)
    kate = register(kate_c, "kate")
    assert kate_c.post("/api/account/guardian/code", json={"target": FOURTH}).status_code == 202  # 108 answers the same for every number (no stale probe)
    code = sms.sent[-1].code
    r = kate_c.post("/api/account/guardian", json={"target": FOURTH, "code": code, "age_band": "14plus"})
    assert r.status_code == 409 and details(r) == {"reason": "guardian_stale"}
    assert rows(settings, "SELECT account_kind FROM users WHERE id = ?", (jane["id"],))[0]["account_kind"] == "learner"
    assert count(settings, "family_codes", "user_id = ? AND used_at IS NULL", (kate["id"],)) == 1  # the code stays live
    # jane signs in with the number (81 refreshes last_login_at — simulated) and the same code now succeeds
    execute(settings, "UPDATE identities SET last_login_at = ? WHERE user_id = ?", (to_iso(frozen_clock.now_utc()), jane["id"]))
    r = kate_c.post("/api/account/guardian", json={"target": FOURTH, "code": code, "age_band": "14plus"})
    assert r.status_code == 200 and r.json()["user"]["is_child"] is True, r.text
    assert rows(settings, "SELECT account_kind, age_band FROM users WHERE id = ?", (jane["id"],))[0] == {"account_kind": "guardian", "age_band": "adult"}


def test_claim_re_validates_the_claimant_inside_the_lock(client: TestClient, app, settings, sms, frozen_clock, monkeypatch: pytest.MonkeyPatch):
    """API.md 109: my own row is read again inside the write transaction — a claim racing with 95 (I created a child on another device)
    or with another claim of mine is refused, and the UPDATE only lands while `guardian_user_id IS NULL`."""
    bootstrap(client)
    mum, mum_user = make_guardian(app, settings, sms)
    nora_c = second_client(app)
    nora = register(nora_c, "nora")
    frozen_clock.advance(minutes=1)  # the per-number send interval
    assert nora_c.post("/api/account/guardian/code", json={"target": PHONE}).status_code == 202
    real = family.verify_claim_code
    def claimed_meanwhile(*args, **kwargs):
        row_id = real(*args, **kwargs)
        execute(settings, "UPDATE users SET guardian_user_id = ? WHERE id = ?", (mum_user["id"], nora["id"]))  # another device finished a claim first
        return row_id
    monkeypatch.setattr(family, "verify_claim_code", claimed_meanwhile)
    r = nora_c.post("/api/account/guardian", json={"target": PHONE, "code": sms.sent[-1].code, "age_band": "14plus"})
    assert r.status_code == 403 and error_code(r) == "guardian_required"
    assert count(settings, "family_codes", "user_id = ? AND used_at IS NULL", (nora["id"],)) == 1  # rolled back: the code stays live
    assert count(settings, "system_events", "kind = 'account_claimed'") == 0
    monkeypatch.setattr(family, "verify_claim_code", real)
    # a child of my own that appeared meanwhile (95 on another device) → has_children
    execute(settings, "UPDATE users SET guardian_user_id = NULL WHERE id = ?", (nora["id"],))
    olga_c = second_client(app)
    olga = register(olga_c, "olga")
    def child_meanwhile(*args, **kwargs):
        row_id = real(*args, **kwargs)
        execute(settings, "UPDATE users SET guardian_user_id = ? WHERE id = ?", (nora["id"], olga["id"]))
        return row_id
    monkeypatch.setattr(family, "verify_claim_code", child_meanwhile)
    r = nora_c.post("/api/account/guardian", json={"target": PHONE, "code": sms.sent[-1].code, "age_band": "14plus"})
    assert r.status_code == 409 and details(r) == {"reason": "has_children"}
    assert rows(settings, "SELECT guardian_user_id FROM users WHERE id = ?", (nora["id"],))[0]["guardian_user_id"] is None


# -------------------------------------------------------------------------------- the legacy prompt (110 / 111)
def test_declare_and_skip_the_legacy_prompt(client: TestClient, app, settings, sms, frozen_clock):
    root = bootstrap(client)
    assert client.get("/api/auth/me").json()["user"]["needs_profile_prompt"] is True  # admins included
    r = client.post("/api/account/declare", json={"account_kind": "guardian", "age_band": "14plus"})
    assert r.status_code == 400 and error_code(r) == "validation_error" and details(r)["fields"] == {"age_band": GUARDIAN_ADULT_ZH}
    for bad in ({"account_kind": "learner", "age_band": "u14"}, {"account_kind": "learner"}, {"age_band": "adult"}, {"account_kind": "teacher", "age_band": "adult"}):
        r = client.post("/api/account/declare", json=bad)
        assert r.status_code == 400 and error_code(r) == "validation_error", bad
    assert client.get("/api/auth/me").json()["user"]["needs_profile_prompt"] is True  # nothing saved by a refused request
    r = client.post("/api/account/declare", json={"account_kind": "learner", "age_band": "adult"})
    assert r.status_code == 200, r.text
    assert (r.json()["user"]["age_band"], r.json()["user"]["account_kind"], r.json()["user"]["needs_profile_prompt"]) == ("adult", "learner", False)
    assert rows(settings, "SELECT age_band, age_declared_at, age_declared_ip, profile_prompted_at, account_kind FROM users WHERE id = ?", (root["id"],))[0] == {"age_band": "adult", "age_declared_at": NOW_ISO, "age_declared_ip": "testclient", "profile_prompted_at": None, "account_kind": "learner"}
    r = client.post("/api/account/declare", json={"account_kind": "guardian", "age_band": "adult"})
    assert r.status_code == 409 and error_code(r) == "invalid_transition" and details(r) == {"reason": "declared"}  # once
    # a code-created account in its first-time setup declares through 89 (and is never prompted)
    learner = second_client(app)
    code_account(learner, sms)
    r = learner.post("/api/account/declare", json={"account_kind": "learner", "age_band": "14plus"})
    assert r.status_code == 409 and details(r) == {"reason": "profile_required"}
    assert learner.get("/api/auth/me").json()["user"]["needs_profile_prompt"] is False
    # snooze: 30 days, idempotent, cleared by a declaration
    bob_c = second_client(app)
    bob = register(bob_c, "bob")
    assert bob_c.get("/api/auth/me").json()["user"]["needs_profile_prompt"] is True
    assert bob_c.post("/api/account/declare/skip").status_code == 204
    assert rows(settings, "SELECT profile_prompted_at FROM users WHERE id = ?", (bob["id"],))[0]["profile_prompted_at"] == NOW_ISO
    assert bob_c.get("/api/auth/me").json()["user"]["needs_profile_prompt"] is False
    frozen_clock.advance(days=29)
    assert bob_c.get("/api/auth/me").json()["user"]["needs_profile_prompt"] is False
    frozen_clock.advance(days=2)  # day 31
    assert bob_c.get("/api/auth/me").json()["user"]["needs_profile_prompt"] is True
    assert bob_c.post("/api/account/declare/skip").status_code == 204  # snoozed again
    assert rows(settings, "SELECT profile_prompted_at FROM users WHERE id = ?", (bob["id"],))[0]["profile_prompted_at"] == "2026-11-14T00:00:00Z"
    assert bob_c.get("/api/auth/me").json()["user"]["needs_profile_prompt"] is False
    r = bob_c.post("/api/account/declare", json={"account_kind": "guardian", "age_band": "adult"})
    assert r.status_code == 200 and r.json()["user"]["account_kind"] == "guardian" and r.json()["user"]["age_band"] == "adult" and r.json()["user"]["needs_profile_prompt"] is False
    assert rows(settings, "SELECT profile_prompted_at, age_declared_at, account_kind FROM users WHERE id = ?", (bob["id"],))[0] == {"profile_prompted_at": None, "age_declared_at": "2026-11-14T00:00:00Z", "account_kind": "guardian"}
    r = bob_c.get("/api/guardian/children")  # `G` from now on; a password but no phone yet
    assert r.status_code == 200 and r.json() == {"items": [], "pin_set": False, "ready": False, "missing": ["phone"], "gate_until": None}
    assert count(settings, "system_events", "kind IN ('account_declared', 'account_claimed', 'guardian_deleted')") == 0  # declarations and snoozes write no event
