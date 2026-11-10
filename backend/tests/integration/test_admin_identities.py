"""Endpoints 92–93 (API.md §8) and the 57 rule: the disputed phone bindings an admin sees (masked numbers, the account now holding the
live binding), restoring one (409 identity_taken while the number is live elsewhere, 404 for a live or unknown row, system_events
phone_restored) and admin_needs_password for promoting a code-created account."""

from __future__ import annotations

import json
import re

import pytest
from fastapi.testclient import TestClient

from wd import db, security
from wd.delivery.sms import RecordingSmsSender

PW = "Correct-Horse-7"
PHONE = "13800138000"
E164 = "+8613800138000"


@pytest.fixture(autouse=True)
def fast_bcrypt(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(security, "BCRYPT_ROUNDS", 4)


@pytest.fixture
def sms(app) -> RecordingSmsSender:
    sender = RecordingSmsSender()
    app.state.sms = sender
    return sender


def second_client(app) -> TestClient:
    c = TestClient(app, base_url="http://testserver")
    c.headers["X-WD-Request"] = "1"
    return c


def register(client: TestClient, username: str) -> dict:
    r = client.post("/api/auth/register", json={"username": username, "password": PW})
    assert r.status_code == 201, r.text
    return r.json()["user"]


def code_login(client: TestClient, sms: RecordingSmsSender, target: str = PHONE):
    assert client.post("/api/auth/code", json={"channel": "phone", "target": target, "purpose": "login", "consent": True}).status_code == 202
    r = client.post("/api/auth/code/login", json={"channel": "phone", "target": target, "code": sms.sent[-1].code})
    assert r.status_code in (200, 201), r.text
    return r.json()


def error(r) -> dict:
    return r.json()["error"]


def rows(settings, sql: str, params=()) -> list[dict]:
    c = db.connect(settings.db_path)
    try:
        return [dict(r) for r in c.execute(sql, params).fetchall()]
    finally:
        c.close()


def test_disputed_identities_are_listed_and_restored(client: TestClient, app, settings, sms, frozen_clock):
    admin = register(client, "root")
    assert client.get("/api/admin/identities/disputed").json() == {"items": [], "page": 1, "page_size": 50, "total": 0}
    old_c = second_client(app)
    old = code_login(old_c, sms)["user"]
    old_c.post("/api/account/profile", json={"display_name": "小明", "age_band": "adult", "password": PW})  # the old owner keeps a password login
    frozen_clock.advance(days=91)
    new_c = second_client(app)
    token = code_login(new_c, sms)["challenge"]["token"]
    r = new_c.post("/api/auth/challenge/dispute", json={"token": token})
    assert r.status_code == 201
    new = r.json()["user"]
    # the admin sees the disputed row with a masked number and the account now holding the live binding
    assert client.get("/api/auth/me").status_code == 401  # 91 frozen days expired the admin's session too
    assert client.post("/api/auth/login", json={"username": "root", "password": PW}).status_code == 200
    page = client.get("/api/admin/identities/disputed").json()
    assert page["total"] == 1 and page["page"] == 1 and page["page_size"] == 50
    item = page["items"][0]
    disputed_id = item["id"]
    assert set(item) == {"id", "user", "provider", "subject_masked", "verified_at", "last_login_at", "disputed_at", "current_user_id"}
    assert item["user"] == {"id": old["id"], "username": old["username"], "display_name": "小明"} and item["provider"] == "phone"
    assert item["subject_masked"] == "138****8000" and E164 not in json.dumps(page) and PHONE not in json.dumps(page)
    assert item["verified_at"] == "2026-10-14T00:00:00Z" and item["last_login_at"] == "2026-10-14T00:00:00Z" and item["disputed_at"] == "2027-01-13T00:00:00Z"
    assert item["current_user_id"] == new["id"]
    assert client.get("/api/admin/identities/disputed", params={"page": 2}).json()["items"] == []
    assert client.get("/api/admin/identities/disputed", params={"page_size": 0}).status_code == 400
    # not while the number is live on the newcomer's account
    r = client.post(f"/api/admin/identities/{disputed_id}/restore")
    assert r.status_code == 409 and error(r)["code"] == "identity_taken"
    # the newcomer leaves (a code-created account deletes itself with a reauth code) → the restore succeeds
    frozen_clock.advance(minutes=1)
    assert new_c.post("/api/account/code", json={"channel": "phone", "purpose": "reauth"}).status_code == 202
    assert new_c.request("DELETE", "/api/account", json={"code": sms.sent[-1].code}).status_code == 204
    r = client.post(f"/api/admin/identities/{disputed_id}/restore")
    assert r.status_code == 200, r.text
    restored = r.json()
    assert restored["id"] == disputed_id and restored["current_user_id"] == old["id"] and restored["disputed_at"] == "2027-01-13T00:00:00Z" and restored["subject_masked"] == "138****8000"
    assert rows(settings, "SELECT disputed_at FROM identities WHERE id = ?", (disputed_id,))[0]["disputed_at"] is None
    assert client.get("/api/admin/identities/disputed").json()["total"] == 0
    event = rows(settings, "SELECT detail_json FROM system_events WHERE kind = 'phone_restored'")
    assert len(event) == 1 and json.loads(event[0]["detail_json"]) == {"by": admin["id"], "identity_id": disputed_id, "user_id": old["id"]}
    r = second_client(app).post("/api/auth/login", json={"username": PHONE, "password": PW})  # the number resolves to the old owner again
    assert r.status_code == 200 and r.json()["user"]["id"] == old["id"] and r.json()["user"]["phone_masked"] == "138****8000"
    # a live or unknown row is 404; the old account having bound another number meanwhile is a 409 invalid_transition
    r = client.post(f"/api/admin/identities/{disputed_id}/restore")
    assert r.status_code == 404 and error(r)["code"] == "not_found"
    assert client.post("/api/admin/identities/999999/restore").status_code == 404
    c = db.connect(settings.db_path)
    try:
        c.execute("UPDATE identities SET disputed_at = '2027-01-14T00:00:00Z' WHERE id = ?", (disputed_id,))
        c.execute("INSERT INTO identities(user_id, provider, subject) VALUES (?, 'phone', '+8613900139000')", (old["id"],))
    finally:
        c.close()
    r = client.post(f"/api/admin/identities/{disputed_id}/restore")
    assert r.status_code == 409 and error(r)["code"] == "invalid_transition" and error(r)["details"] == {"reason": "already_bound"}
    # ordinary users never see the admin routes
    user_c = second_client(app)
    assert user_c.post("/api/auth/login", json={"username": old["username"], "password": PW}).status_code == 200
    r = user_c.get("/api/admin/identities/disputed")
    assert r.status_code == 403 and error(r)["code"] == "forbidden"
    assert user_c.post(f"/api/admin/identities/{disputed_id}/restore").status_code == 403


def test_promoting_an_account_without_a_password_is_refused(client: TestClient, app, settings, sms, frozen_clock):
    register(client, "root")
    learner = second_client(app)
    bob = code_login(learner, sms)["user"]
    listed = next(u for u in client.get("/api/admin/users").json()["items"] if u["id"] == bob["id"])
    assert listed["has_password"] is False and listed["phone_masked"] == "138****8000" and listed["needs_profile"] is True and re.match(r"^u_[a-z2-7]{8}$", listed["username"])
    r = client.post(f"/api/admin/users/{bob['id']}", json={"role": "admin"})
    assert r.status_code == 409 and error(r)["code"] == "admin_needs_password"
    assert learner.get("/api/auth/me").json()["user"]["role"] == "user"
    assert client.post(f"/api/admin/users/{bob['id']}", json={"is_active": False}).status_code == 200  # other fields are fine
    assert client.post(f"/api/admin/users/{bob['id']}", json={"is_active": True}).status_code == 200
    # a reset password in the same request gives the account a password first
    r = client.post(f"/api/admin/users/{bob['id']}", json={"role": "admin", "new_password": "Reset-Pass-Word-9"})
    assert r.status_code == 200 and r.json()["role"] == "admin" and r.json()["has_password"] is True
    assert second_client(app).post("/api/auth/login", json={"username": PHONE, "password": "Reset-Pass-Word-9"}).status_code == 200
    # … and a code login now refuses the admin
    frozen_clock.advance(minutes=1)  # one send window per target
    assert learner.post("/api/auth/code", json={"channel": "phone", "target": PHONE, "purpose": "login", "consent": True}).status_code == 202
    r = learner.post("/api/auth/code/login", json={"channel": "phone", "target": PHONE, "code": sms.sent[-1].code})
    assert r.status_code == 403 and error(r)["code"] == "password_required"
