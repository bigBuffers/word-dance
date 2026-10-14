"""Endpoints 56–59: admin user list/update (last-admin guard, password reset, deactivation) and invite codes."""

from __future__ import annotations

import re
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from wd import db, security

PW = "Correct-Horse-7"
NOW = datetime(2026, 10, 14, 0, 0, 0, tzinfo=timezone.utc)
NOW_ISO = "2026-10-14T00:00:00Z"
INVITE_RE = re.compile(r"^[A-Z0-9-]{10,}$")
ADMIN_USER_KEYS = {"id", "username", "display_name", "email", "email_verified", "role", "onboarding_state", "created_at", "is_active", "last_login_at", "bank_size", "streak_days"}


@pytest.fixture(autouse=True)
def fast_bcrypt(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(security, "BCRYPT_ROUNDS", 4)


def second_client(app) -> TestClient:
    c = TestClient(app, base_url="http://testserver")
    c.headers["X-WD-Request"] = "1"
    return c


def register(client: TestClient, username: str, **extra) -> dict:
    r = client.post("/api/auth/register", json={"username": username, "password": PW, **extra})
    assert r.status_code == 201, r.text
    return r.json()["user"]


def error(r) -> dict:
    return r.json()["error"]


@pytest.fixture
def people(client: TestClient, app):
    """alice (admin, on ``client``), bob and carol (users, each on their own client)."""
    alice = register(client, "alice", email="alice@example.com")
    bob_c, carol_c = second_client(app), second_client(app)
    bob = register(bob_c, "bob", display_name="小鲍")
    carol = register(carol_c, "carol", email="carol@example.com")
    return {"alice": alice, "bob": bob, "carol": carol, "bob_c": bob_c, "carol_c": carol_c}


def test_requires_admin(people):
    bob_c = people["bob_c"]
    for method, path in (("GET", "/api/admin/users"), ("GET", "/api/admin/invites")):
        r = bob_c.request(method, path)
        assert r.status_code == 403 and error(r)["code"] == "forbidden", path
    r = bob_c.post("/api/admin/invites", json={})
    assert r.status_code == 403 and error(r)["code"] == "forbidden"
    r = bob_c.post(f"/api/admin/users/{people['alice']['id']}", json={"is_active": False})
    assert r.status_code == 403
    bob_c.cookies.clear()
    assert bob_c.get("/api/admin/users").status_code == 401


def test_list_users_with_search_paging_and_derived_fields(client: TestClient, people, settings):
    r = client.get("/api/admin/users")
    assert r.status_code == 200, r.text
    page = r.json()
    assert page["total"] == 3 and page["page"] == 1 and page["page_size"] == 50 and [u["username"] for u in page["items"]] == ["alice", "bob", "carol"]
    alice = page["items"][0]
    assert set(alice) == ADMIN_USER_KEYS and alice["role"] == "admin" and alice["is_active"] is True and alice["last_login_at"] is None
    assert alice["bank_size"] == 0 and alice["streak_days"] == 0 and alice["email"] == "alice@example.com" and alice["email_verified"] is False
    assert page["items"][1]["display_name"] == "小鲍"
    bob = people["bob"]
    c = db.connect(settings.db_path)
    try:
        for i, lemma in enumerate(("w1", "w2", "w3")):
            wid = c.execute("INSERT INTO words(lemma, display, source) VALUES (?, ?, 'seed')", (lemma, lemma)).lastrowid
            state = ("new", "learning", "mastered")[i]
            c.execute("INSERT INTO user_words(user_id, word_id, state, origin) VALUES (?, ?, ?, 'browse')", (bob["id"], wid, state))
        for d, graded in (("2026-10-14", 3), ("2026-10-13", 1), ("2026-10-12", 2), ("2026-10-10", 5)):  # gap on the 11th ends the streak
            c.execute("INSERT INTO daily_stats(user_id, local_date, graded) VALUES (?, ?, ?)", (bob["id"], d, graded))
        c.execute("INSERT INTO daily_stats(user_id, local_date, graded, screened) VALUES (?, '2026-10-14', 0, 4)", (people["carol"]["id"],))  # screening alone is no streak
    finally:
        c.close()
    r = client.get("/api/admin/users", params={"q": "bo"})
    assert r.json()["total"] == 1 and r.json()["items"][0]["username"] == "bob"
    assert r.json()["items"][0]["bank_size"] == 2 and r.json()["items"][0]["streak_days"] == 3  # new + learning only; 14,13,12
    assert client.get("/api/admin/users", params={"q": "小鲍"}).json()["total"] == 1
    assert client.get("/api/admin/users", params={"q": "example.com"}).json()["total"] == 2
    assert client.get("/api/admin/users", params={"q": "%"}).json()["total"] == 0  # LIKE wildcards are escaped
    r = client.get("/api/admin/users", params={"page": 2, "page_size": 1})
    assert r.json()["total"] == 3 and [u["username"] for u in r.json()["items"]] == ["bob"] and r.json()["page"] == 2
    assert client.get("/api/admin/users", params={"page_size": 101}).status_code == 400
    carol = next(u for u in client.get("/api/admin/users").json()["items"] if u["username"] == "carol")
    assert carol["streak_days"] == 0
    # last_login_at is filled by a login
    people["bob_c"].post("/api/auth/login", json={"username": "bob", "password": PW})
    assert client.get("/api/admin/users", params={"q": "bob"}).json()["items"][0]["last_login_at"] == NOW_ISO


def test_role_and_active_updates_with_last_admin_guard(client: TestClient, people, settings):
    alice, bob, bob_c = people["alice"], people["bob"], people["bob_c"]
    r = client.post(f"/api/admin/users/{alice['id']}", json={"is_active": False})
    assert r.status_code == 409 and error(r)["code"] == "last_admin"
    r = client.post(f"/api/admin/users/{alice['id']}", json={"role": "user"})
    assert r.status_code == 409 and error(r)["code"] == "last_admin"
    r = client.post(f"/api/admin/users/{bob['id']}", json={"role": "admin"})
    assert r.status_code == 200 and r.json()["role"] == "admin" and r.json()["username"] == "bob"
    assert bob_c.get("/api/auth/me").json()["user"]["role"] == "admin"
    r = client.post(f"/api/admin/users/{alice['id']}", json={"role": "user"})  # now allowed: bob is an active admin
    assert r.status_code == 200 and r.json()["role"] == "user"
    r = client.get("/api/admin/users")
    assert r.status_code == 403 and error(r)["code"] == "forbidden"  # alice lost admin rights immediately
    r = bob_c.post(f"/api/admin/users/{alice['id']}", json={"is_active": False})
    assert r.status_code == 200 and r.json()["is_active"] is False
    assert client.get("/api/auth/me").status_code == 401  # alice's sessions were revoked
    r = client.post("/api/auth/login", json={"username": "alice", "password": PW})
    assert r.status_code == 403 and error(r)["code"] == "account_disabled"
    r = bob_c.post(f"/api/admin/users/{bob['id']}", json={"is_active": False})  # bob is now the last active admin
    assert r.status_code == 409 and error(r)["code"] == "last_admin"
    r = bob_c.post(f"/api/admin/users/{alice['id']}", json={"is_active": True, "role": "admin"})
    assert r.status_code == 200 and r.json()["is_active"] is True and r.json()["role"] == "admin"
    assert client.post("/api/auth/login", json={"username": "alice", "password": PW}).status_code == 200
    r = bob_c.post(f"/api/admin/users/{bob['id']}", json={"is_active": False})  # alice is active again → bob may step down
    assert r.status_code == 200 and bob_c.get("/api/auth/me").status_code == 401
    r = client.post("/api/admin/users/999999", json={"role": "admin"})
    assert r.status_code == 404 and error(r)["code"] == "not_found"
    r = client.post(f"/api/admin/users/{alice['id']}", json={})
    assert r.status_code == 400 and error(r)["code"] == "validation_error"
    r = client.post(f"/api/admin/users/{alice['id']}", json={"role": "root"})
    assert r.status_code == 400
    c = db.connect(settings.db_path)
    try:
        assert c.execute("SELECT updated_at FROM users WHERE id = ?", (bob["id"],)).fetchone()[0] == NOW_ISO
    finally:
        c.close()


def test_admin_password_reset(client: TestClient, people):
    bob, bob_c = people["bob"], people["bob_c"]
    r = client.post(f"/api/admin/users/{bob['id']}", json={"new_password": "password123"})
    assert r.status_code == 400 and error(r)["code"] == "weak_password"
    r = client.post(f"/api/admin/users/{bob['id']}", json={"new_password": "short"})
    assert r.status_code == 400 and error(r)["code"] == "validation_error"
    assert bob_c.get("/api/auth/me").status_code == 200
    r = client.post(f"/api/admin/users/{bob['id']}", json={"new_password": "Reset-Pass-Word-9"})
    assert r.status_code == 200 and r.json()["username"] == "bob" and r.json()["is_active"] is True
    assert bob_c.get("/api/auth/me").status_code == 401  # every session of bob revoked
    assert bob_c.post("/api/auth/login", json={"username": "bob", "password": PW}).status_code == 401
    assert bob_c.post("/api/auth/login", json={"username": "bob", "password": "Reset-Pass-Word-9"}).status_code == 200


def test_invites_created_hashed_and_listed_without_codes(client: TestClient, people, settings):
    alice = people["alice"]
    r = client.post("/api/admin/invites", json={})
    assert r.status_code == 201, r.text
    first = r.json()
    assert set(first) == {"id", "code", "expires_at"} and INVITE_RE.match(first["code"]) and first["expires_at"] is None
    r = client.post("/api/admin/invites", json={"max_uses": 5, "expires_in_days": 7, "note": "同事"})
    second = r.json()
    assert second["expires_at"] == "2026-10-21T00:00:00Z" and second["code"] != first["code"]
    listing = client.get("/api/admin/invites").json()["items"]
    assert [i["id"] for i in listing] == [second["id"], first["id"]]  # newest first
    assert listing[0] == {"id": second["id"], "max_uses": 5, "uses": 0, "expires_at": "2026-10-21T00:00:00Z", "note": "同事", "created_at": NOW_ISO, "created_by": alice["id"]}
    assert all("code" not in i for i in listing)
    c = db.connect(settings.db_path)
    try:
        rows = {r["id"]: r for r in c.execute("SELECT * FROM invite_codes")}
        assert rows[first["id"]]["code_hash"] == security.hash_invite_code(first["code"])
        assert rows[second["id"]]["code_hash"] == security.hash_invite_code(second["code"])
        assert first["code"] not in str([tuple(r) for r in rows.values()])
    finally:
        c.close()
    for bad in ({"max_uses": 0}, {"max_uses": 101}, {"expires_in_days": 0}, {"expires_in_days": 366}, {"note": "x" * 201}, {"code": "MINE"}):
        r = client.post("/api/admin/invites", json=bad)
        assert r.status_code == 400 and error(r)["code"] == "validation_error", bad
    # the code works for a registration and the listing reflects the use
    fresh = second_client(client.app)
    r = fresh.post("/api/auth/register", json={"username": "dave", "password": PW, "invite_code": second["code"]})
    assert r.status_code == 201  # open mode ignores codes but accepts them; invite mode is covered in test_auth
    c = db.connect(settings.db_path)
    try:
        security.consume_invite(c, second["code"], NOW)
    finally:
        c.close()
    assert client.get("/api/admin/invites").json()["items"][0]["uses"] == 1
