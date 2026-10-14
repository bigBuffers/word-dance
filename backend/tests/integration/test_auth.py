"""Endpoints 2–11: registration (bootstrap, modes, invites, throttle), login/lockout, cookies, CSRF, logout, /me, account."""

from __future__ import annotations

import csv
import io
import re
import sqlite3
import threading
from dataclasses import replace
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from wd import db, security
from wd.clock import compute_next_push, to_iso
from wd.delivery.mailer import RecordingMailer
from wd.jobs import queue
from wd.main import create_app
from wd.routers.account import EXPORT_COLUMNS

PW = "Correct-Horse-7"
NOW = datetime(2026, 10, 14, 0, 0, 0, tzinfo=timezone.utc)
NOW_ISO = "2026-10-14T00:00:00Z"
INVITE_RE = re.compile(r"^[A-Z0-9-]{10,}$")


@pytest.fixture(autouse=True)
def fast_bcrypt(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(security, "BCRYPT_ROUNDS", 4)


def register(client: TestClient, username: str, password: str = PW, **extra):
    r = client.post("/api/auth/register", json={"username": username, "password": password, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def second_client(app) -> TestClient:
    """Another browser on the same running app (the lifespan already ran through the ``client`` fixture)."""
    c = TestClient(app, base_url="http://testserver")
    c.headers["X-WD-Request"] = "1"
    return c


def error_code(r) -> str:
    return r.json()["error"]["code"]


def count(settings, table: str, where: str = "1=1", params=()) -> int:
    c = db.connect(settings.db_path)
    try:
        return int(c.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}", params).fetchone()[0])
    finally:
        c.close()


def insert_word(c: sqlite3.Connection, lemma: str, *, is_public: int = 1, created_by: int | None = None, **cols) -> int:
    """Insert a word row and return its id.

    A lemma that is already present (the lifespan imports the mini seed through WP1's ``wd.seed``, so public words such as
    ``abandon`` exist before the test runs) is reused: the given columns are written onto the existing row instead.
    """
    base = {"lemma": lemma, "display": lemma, "source": "seed" if is_public else "user", "is_public": is_public, "is_valid_english": 1 if is_public else None, "created_by_user_id": created_by}
    base.update(cols)
    keys = ", ".join(base)
    marks = ", ".join("?" * len(base))
    updates = ", ".join(f"{k} = excluded.{k}" for k in base if k != "lemma")
    c.execute(f"INSERT INTO words({keys}) VALUES ({marks}) ON CONFLICT(lemma) DO UPDATE SET {updates}", list(base.values()))
    return int(c.execute("SELECT id FROM words WHERE lemma = ?", (lemma,)).fetchone()[0])


# ------------------------------------------------------------------------------------- register
def test_register_first_user_is_admin_with_defaults_and_cookie(client: TestClient, settings):
    assert client.get("/api/health").json()["needs_setup"] is True
    r = client.post("/api/auth/register", json={"username": "alice", "password": PW, "display_name": " 小张 ", "email": "Alice@Example.com"})
    assert r.status_code == 201, r.text
    user, st = r.json()["user"], r.json()["settings"]
    assert user["role"] == "admin" and user["onboarding_state"] == "pending" and user["display_name"] == "小张"
    assert user["email"] == "Alice@Example.com" and user["email_verified"] is False and user["created_at"] == NOW_ISO
    assert st["timezone"] == "Asia/Shanghai" and st["push_time"] == "08:00" and st["stages"] == ["cet4", "cet6"] and st["current_stage"] == "cet4"
    assert st["next_push_at"] == "2026-10-15T00:00:00Z" == to_iso(compute_next_push(NOW, "Asia/Shanghai", "08:00"))
    assert st["email_verified"] is False and st["push_enabled"] is True and st["daily_new_count"] == 10 and st["webhook_url"] is None
    cookie = r.headers["set-cookie"].lower()
    assert "wd_session=" in cookie and "httponly" in cookie and "samesite=lax" in cookie and "path=/" in cookie
    assert "max-age=2592000" in cookie and "secure" not in cookie
    assert client.get("/api/health").json()["needs_setup"] is False
    me = client.get("/api/auth/me")
    assert me.status_code == 200, me.text
    body = me.json()
    assert body["user"]["username"] == "alice" and body["settings"]["next_push_at"] == "2026-10-15T00:00:00Z"
    assert body["server"] == {"version": body["server"]["version"], "registration_mode": "open", "email_configured": False, "ai_enabled": True, "images_enabled": True, "dev": False, "needs_setup": False}
    assert body["counters"] == {"suggestions_open": 0, "attention": 0}
    bob = register(client, "bob")
    assert bob["user"]["role"] == "user" and bob["settings"]["next_push_at"] == "2026-10-15T00:00:00Z"
    assert count(settings, "users") == 2 and count(settings, "user_settings", "next_push_at IS NOT NULL") == 2 and count(settings, "sessions") == 2


def test_duplicate_username_and_email_409(client: TestClient, settings):
    register(client, "alice", email="a@example.com")
    r = client.post("/api/auth/register", json={"username": "Alice", "password": PW})
    assert r.status_code == 409 and error_code(r) == "username_taken"
    r = client.post("/api/auth/register", json={"username": "bob", "password": PW, "email": "A@EXAMPLE.COM"})
    assert r.status_code == 409 and error_code(r) == "email_taken"
    assert count(settings, "users") == 1 and count(settings, "user_settings") == 1


@pytest.mark.parametrize(
    "username,password,code",
    [("alice", "short", "validation_error"), ("alice", "x" * 65, "validation_error"), ("alice", "password123", "weak_password"), ("alice_wonder", "Alice_Wonder", "weak_password")],
)
def test_weak_passwords_rejected(client: TestClient, username, password, code):
    r = client.post("/api/auth/register", json={"username": username, "password": password})
    assert r.status_code == 400 and error_code(r) == code, r.text
    if code == "weak_password":
        assert r.json()["error"]["details"]["reason"]
    assert client.get("/api/health").json()["needs_setup"] is True


def test_invite_mode_bootstrap_then_codes(settings, frozen_clock):
    app = create_app(replace(settings, registration_mode="invite"), clock=frozen_clock, configure_logs=False)
    with TestClient(app, base_url="http://testserver") as admin:
        admin.headers["X-WD-Request"] = "1"
        users = second_client(app)
        h = admin.get("/api/health").json()
        assert h["registration_mode"] == "invite" and h["needs_setup"] is True
        alice = register(admin, "alice")  # bootstrap: no code needed in invite mode, becomes admin
        assert alice["user"]["role"] == "admin"
        assert admin.get("/api/health").json()["needs_setup"] is False
        r = users.post("/api/auth/register", json={"username": "bob", "password": PW})
        assert r.status_code == 403 and error_code(r) == "invalid_invite"
        r = users.post("/api/auth/register", json={"username": "bob", "password": PW, "invite_code": "NOPE-NOPE-NOPE-NOPE"})
        assert r.status_code == 403 and error_code(r) == "invalid_invite"
        inv = admin.post("/api/admin/invites", json={})
        assert inv.status_code == 201, inv.text
        code = inv.json()["code"]
        assert INVITE_RE.match(code) and inv.json()["expires_at"] is None
        bob = register(users, "bob", invite_code=code)
        assert bob["user"]["role"] == "user"
        r = users.post("/api/auth/register", json={"username": "carol", "password": PW, "invite_code": code})
        assert r.status_code == 403 and error_code(r) == "invalid_invite"  # consumed
        listing = admin.get("/api/admin/invites").json()["items"]
        assert len(listing) == 1 and listing[0]["uses"] == 1 and listing[0]["max_uses"] == 1 and "code" not in listing[0]
        assert listing[0]["created_by"] == alice["user"]["id"] and listing[0]["created_at"] == NOW_ISO
        frozen_clock.advance(hours=1)  # the registration throttle (5/h per IP) is clock based
        inv2 = admin.post("/api/admin/invites", json={"max_uses": 2, "expires_in_days": 1, "note": "friends"}).json()
        assert inv2["expires_at"] == "2026-10-15T01:00:00Z"
        register(users, "dave", invite_code=inv2["code"].lower())
        register(users, "erin", invite_code=" " + inv2["code"] + " ")
        r = users.post("/api/auth/register", json={"username": "fred", "password": PW, "invite_code": inv2["code"]})
        assert r.status_code == 403 and error_code(r) == "invalid_invite"
        inv3 = admin.post("/api/admin/invites", json={"expires_in_days": 1}).json()
        frozen_clock.advance(days=2)
        r = users.post("/api/auth/register", json={"username": "gina", "password": PW, "invite_code": inv3["code"]})
        assert r.status_code == 403 and error_code(r) == "invalid_invite"
        assert count(settings, "users") == 4 and count(settings, "users", "role = 'admin'") == 1


def test_closed_mode_only_allows_the_bootstrap_registration(settings, frozen_clock):
    with TestClient(create_app(replace(settings, registration_mode="closed"), clock=frozen_clock, configure_logs=False)) as c:
        c.headers["X-WD-Request"] = "1"
        assert register(c, "alice")["user"]["role"] == "admin"
        r = c.post("/api/auth/register", json={"username": "bob", "password": PW, "invite_code": "ABCD-EFGH-JKLM-NPQR"})
        assert r.status_code == 403 and error_code(r) == "registration_closed"


def test_concurrent_first_registrations_yield_exactly_one_admin(settings, frozen_clock):
    app = create_app(replace(settings, registration_mode="invite"), clock=frozen_clock, configure_logs=False)
    results: dict[str, tuple[int, dict]] = {}
    barrier = threading.Barrier(2)

    def worker(name: str) -> None:
        c = second_client(app)
        barrier.wait()
        r = c.post("/api/auth/register", json={"username": name, "password": PW})
        results[name] = (r.status_code, r.json())

    with TestClient(app):  # runs the lifespan (migrations)
        threads = [threading.Thread(target=worker, args=(n,)) for n in ("alice", "bob")]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
    statuses = sorted(s for s, _ in results.values())
    assert statuses == [201, 403], results
    winner = next(b for s, b in results.values() if s == 201)
    loser = next(b for s, b in results.values() if s == 403)
    assert winner["user"]["role"] == "admin" and loser["error"]["code"] == "invalid_invite"
    assert count(settings, "users") == 1 and count(settings, "users", "role = 'admin'") == 1


def test_register_ip_throttle_5_per_hour(client: TestClient, frozen_clock):
    for i in range(5):
        register(client, f"user{i}")
    r = client.post("/api/auth/register", json={"username": "user5", "password": PW})
    assert r.status_code == 429 and error_code(r) == "rate_limited"
    assert r.headers["Retry-After"] == "3600" and r.json()["error"]["details"]["retry_after_s"] == 3600
    frozen_clock.advance(hours=1)
    register(client, "user5")


# ---------------------------------------------------------------------------------- login / logout
def test_login_logout_and_session_rotation(client: TestClient, settings):
    reg = client.post("/api/auth/register", json={"username": "alice", "password": PW})
    first_token = reg.cookies["wd_session"]
    r = client.post("/api/auth/login", json={"username": "alice", "password": "wrong-password-1"})
    assert r.status_code == 401 and error_code(r) == "invalid_credentials"
    r = client.post("/api/auth/login", json={"username": "nobody", "password": PW})
    assert r.status_code == 401 and error_code(r) == "invalid_credentials"  # same answer for unknown users
    r = client.post("/api/auth/login", json={"username": " ALICE ", "password": PW})
    assert r.status_code == 200, r.text
    assert r.json()["user"]["username"] == "alice" and set(r.json()) == {"user", "settings"}
    token = r.cookies["wd_session"]
    assert token != first_token  # a new session every login (no fixation)
    c = db.connect(settings.db_path)
    try:
        assert c.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 2
        assert c.execute("SELECT last_login_at FROM users WHERE username = 'alice'").fetchone()[0] == NOW_ISO
    finally:
        c.close()
    r = client.post("/api/auth/logout")
    assert r.status_code == 204
    cleared = r.headers["set-cookie"].lower()
    assert "wd_session=" in cleared and ("max-age=0" in cleared or "expires=" in cleared)
    client.cookies.clear()
    r = client.get("/api/auth/me")
    assert r.status_code == 401 and error_code(r) == "unauthorized"
    client.cookies.set("wd_session", token)  # the revoked token is dead even if replayed
    assert client.get("/api/auth/me").status_code == 401
    assert count(settings, "sessions") == 1
    client.cookies.set("wd_session", first_token)  # the other session still works
    assert client.get("/api/auth/me").status_code == 200


def test_login_lockout_persists_across_app_instances(client: TestClient, settings, frozen_clock):
    register(client, "alice")
    for _ in range(10):
        r = client.post("/api/auth/login", json={"username": "alice", "password": "wrong-password-1"})
        assert r.status_code == 401
    r = client.post("/api/auth/login", json={"username": "alice", "password": PW})
    assert r.status_code == 423 and error_code(r) == "account_locked"
    assert r.json()["error"]["details"]["retry_after_s"] == 900 and r.headers["Retry-After"] == "900"
    # a fresh process on the same database sees the lock (auth_throttle is persistent)
    other = create_app(settings, clock=frozen_clock, configure_logs=False)
    with TestClient(other, base_url="http://testserver") as c2:
        c2.headers["X-WD-Request"] = "1"
        r = c2.post("/api/auth/login", json={"username": "Alice", "password": PW})
        assert r.status_code == 423 and r.json()["error"]["details"]["retry_after_s"] == 900
    frozen_clock.advance(seconds=899)
    r = client.post("/api/auth/login", json={"username": "alice", "password": PW})
    assert r.status_code == 423 and r.json()["error"]["details"]["retry_after_s"] == 1
    frozen_clock.advance(seconds=2)
    assert client.post("/api/auth/login", json={"username": "alice", "password": PW}).status_code == 200
    assert count(settings, "auth_throttle", "key = 'login:user:alice'") == 0  # reset on success
    assert client.post("/api/auth/login", json={"username": "alice", "password": "wrong-password-1"}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "alice", "password": PW}).status_code == 200


def test_login_ip_throttle_20_per_10_minutes(client: TestClient, frozen_clock):
    register(client, "alice")
    for i in range(20):
        assert client.post("/api/auth/login", json={"username": f"ghost{i}", "password": PW}).status_code == 401
    r = client.post("/api/auth/login", json={"username": "alice", "password": PW})
    assert r.status_code == 429 and error_code(r) == "rate_limited" and r.json()["error"]["details"]["retry_after_s"] == 600
    frozen_clock.advance(minutes=10)
    assert client.post("/api/auth/login", json={"username": "alice", "password": PW}).status_code == 200


def test_disabled_account_cannot_log_in(client: TestClient, app, settings):
    register(client, "alice")  # admin
    bob_c = second_client(app)
    bob = register(bob_c, "bob")
    assert bob_c.get("/api/auth/me").status_code == 200
    r = client.post(f"/api/admin/users/{bob['user']['id']}", json={"is_active": False})
    assert r.status_code == 200 and r.json()["is_active"] is False
    assert bob_c.get("/api/auth/me").status_code == 401  # sessions revoked
    r = bob_c.post("/api/auth/login", json={"username": "bob", "password": PW})
    assert r.status_code == 403 and error_code(r) == "account_disabled"
    r = bob_c.post("/api/auth/login", json={"username": "bob", "password": "wrong-password-1"})
    assert r.status_code == 401 and error_code(r) == "invalid_credentials"  # credentials are checked first


def test_csrf_rules_on_auth_endpoints(raw_client: TestClient, client: TestClient):
    body = {"username": "alice", "password": PW}
    r = raw_client.post("/api/auth/login", json=body)
    assert r.status_code == 403 and error_code(r) == "csrf_rejected"
    r = client.post("/api/auth/login", json=body, headers={"Origin": "http://evil.example"})
    assert r.status_code == 403 and error_code(r) == "csrf_rejected"
    r = client.post("/api/auth/login", json=body, headers={"Origin": "http://testserver"})
    assert r.status_code == 401  # passes CSRF, then no such user


def test_cookie_secure_flag(settings, frozen_clock):
    for i, cfg in enumerate((replace(settings, cookie_secure="1"), replace(settings, public_url="https://words.example.com"))):
        with TestClient(create_app(cfg, clock=frozen_clock, configure_logs=False)) as c:  # same DB both times → distinct users
            c.headers["X-WD-Request"] = "1"
            r = c.post("/api/auth/register", json={"username": f"alice{i}", "password": PW}, headers={"Origin": "http://testserver"})
            assert r.status_code == 201 and "secure" in r.headers["set-cookie"].lower(), r.text


# ---------------------------------------------------------------------------------------- /me
def test_me_requires_login_and_carries_counters(client: TestClient, settings):
    r = client.get("/api/auth/me")
    assert r.status_code == 401 and error_code(r) == "unauthorized"
    alice = register(client, "alice")["user"]
    c = db.connect(settings.db_path)
    try:
        w1 = insert_word(c, "zzqx", is_public=0, created_by=alice["id"])
        w2 = insert_word(c, "zzqy", is_public=0, created_by=alice["id"])
        w3 = insert_word(c, "abandon")
        uw = c.execute(
            "INSERT INTO user_words(user_id, word_id, state, origin, needs_attention, attention_msg) VALUES (?, ?, 'new', 'custom', 1, '未识别为英文单词')",
            (alice["id"], w1),
        ).lastrowid
        c.execute("INSERT INTO user_words(user_id, word_id, state, origin, needs_attention) VALUES (?, ?, 'removed', 'custom', 1)", (alice["id"], w2))
        c.execute("INSERT INTO user_words(user_id, word_id, state, origin) VALUES (?, ?, 'learning', 'browse')", (alice["id"], w3))
        c.execute("INSERT INTO bank_suggestions(user_id, type, user_word_id, payload_json, status) VALUES (?, 'fix_spelling', ?, '{}', 'open')", (alice["id"], uw))
        c.execute("INSERT INTO bank_suggestions(user_id, type, user_word_id, payload_json, status) VALUES (?, 'fix_spelling', ?, '{}', 'accepted')", (alice["id"], uw))
    finally:
        c.close()
    me = client.get("/api/auth/me").json()
    assert me["counters"] == {"suggestions_open": 1, "attention": 1}  # removed rows and resolved suggestions do not count


# ------------------------------------------------------------------------------------- account
def test_password_change_revokes_other_sessions(client: TestClient, app):
    register(client, "alice")
    other = second_client(app)
    assert other.post("/api/auth/login", json={"username": "alice", "password": PW}).status_code == 200
    assert other.get("/api/auth/me").status_code == 200
    r = client.post("/api/account/password", json={"current_password": "wrong-password-1", "new_password": "New-Pass-Word-9"})
    assert r.status_code == 401 and error_code(r) == "invalid_credentials"
    r = client.post("/api/account/password", json={"current_password": PW, "new_password": "password123"})
    assert r.status_code == 400 and error_code(r) == "weak_password"
    r = client.post("/api/account/password", json={"current_password": PW, "new_password": "New-Pass-Word-9"})
    assert r.status_code == 204
    assert client.get("/api/auth/me").status_code == 200  # the current session survives
    assert other.get("/api/auth/me").status_code == 401  # every other session is gone
    assert other.post("/api/auth/login", json={"username": "alice", "password": PW}).status_code == 401
    assert other.post("/api/auth/login", json={"username": "alice", "password": "New-Pass-Word-9"}).status_code == 200


def test_update_account_display_name_and_email(client: TestClient, app, settings):
    alice = register(client, "alice")["user"]
    register(second_client(app), "bob", email="bob@example.com")
    r = client.put("/api/account", json={"display_name": " 小张 "})
    assert r.status_code == 200 and r.json()["user"]["display_name"] == "小张"
    r = client.put("/api/account", json={"display_name": None})
    assert r.json()["user"]["display_name"] == "alice"
    r = client.put("/api/account", json={"email": "BOB@example.com"})
    assert r.status_code == 409 and error_code(r) == "email_taken"
    r = client.put("/api/account", json={"email": "alice@example.com"})
    assert r.status_code == 200 and r.json()["user"]["email"] == "alice@example.com" and r.json()["user"]["email_verified"] is False
    c = db.connect(settings.db_path)
    try:
        c.execute("UPDATE users SET email_verified_at = ? WHERE id = ?", (NOW_ISO, alice["id"]))
        c.execute("UPDATE user_settings SET email_enabled = 1 WHERE user_id = ?", (alice["id"],))
    finally:
        c.close()
    assert client.get("/api/auth/me").json()["user"]["email_verified"] is True
    r = client.put("/api/account", json={"email": "ALICE@example.com"})  # same address, different case: nothing is reset
    assert r.json()["user"]["email_verified"] is True
    r = client.put("/api/account", json={"email": "alice2@example.com"})  # a new address resets verification and the channel
    assert r.json()["user"]["email_verified"] is False
    assert count(settings, "user_settings", "user_id = ? AND email_enabled = 0", (alice["id"],)) == 1
    r = client.put("/api/account", json={"email": None})
    assert r.status_code == 200 and r.json()["user"]["email"] is None
    r = client.put("/api/account", json={"nickname": "x"})
    assert r.status_code == 400 and error_code(r) == "validation_error"


def test_email_verification_flow(client: TestClient, app, settings, frozen_clock):
    alice = register(client, "alice")["user"]
    r = client.post("/api/account/email/request-code")
    assert r.status_code == 400 and error_code(r) == "validation_error"  # no e-mail on the account
    client.put("/api/account", json={"email": "alice@example.com"})
    r = client.post("/api/account/email/request-code")
    assert r.status_code == 409 and error_code(r) == "smtp_unconfigured"
    mailer = RecordingMailer()
    app.state.mailer = mailer
    r = client.post("/api/account/email/request-code")
    assert r.status_code == 202 and r.json() == {"sent": True, "expires_in_s": 900}
    assert len(mailer.sent) == 1 and mailer.sent[0].to == "alice@example.com" and "邮箱验证码" in mailer.sent[0].subject
    code = re.search(r"(\d{6})", mailer.sent[0].text).group(1)
    c = db.connect(settings.db_path)
    try:
        row = c.execute("SELECT * FROM email_codes WHERE user_id = ?", (alice["id"],)).fetchone()
        assert row["code_hash"] == security.email_code_hash(settings.secret_key, code, alice["id"]) and row["used_at"] is None
        assert row["expires_at"] == "2026-10-14T00:15:00Z"
    finally:
        c.close()
    wrong = "000000" if code != "000000" else "111111"
    r = client.post("/api/account/email/verify", json={"code": wrong})
    assert r.status_code == 400 and error_code(r) == "invalid_code" and r.json()["error"]["details"]["attempts_left"] == 4
    r = client.post("/api/account/email/verify", json={"code": "12345"})
    assert r.status_code == 400 and error_code(r) == "validation_error"
    r = client.post("/api/account/email/verify", json={"code": code})
    assert r.status_code == 200 and r.json()["user"]["email_verified"] is True
    assert client.get("/api/auth/me").json()["settings"]["email_verified"] is True
    r = client.post("/api/account/email/verify", json={"code": code})
    assert r.status_code == 400 and r.json()["error"]["details"]["attempts_left"] == 0  # single use
    # 5 wrong attempts burn the code
    client.post("/api/account/email/request-code")
    code2 = re.search(r"(\d{6})", mailer.sent[-1].text).group(1)
    wrong2 = "000000" if code2 != "000000" else "111111"
    for left in (4, 3, 2, 1, 0):
        r = client.post("/api/account/email/verify", json={"code": wrong2})
        assert r.status_code == 400 and r.json()["error"]["details"]["attempts_left"] == left
    assert client.post("/api/account/email/verify", json={"code": code2}).status_code == 400
    # 3 per hour per user
    assert client.post("/api/account/email/request-code").status_code == 202
    r = client.post("/api/account/email/request-code")
    assert r.status_code == 429 and error_code(r) == "rate_limited"
    assert len(mailer.sent) == 3
    # expiry after 15 minutes
    frozen_clock.advance(hours=1)
    client.post("/api/account/email/request-code")
    code3 = re.search(r"(\d{6})", mailer.sent[-1].text).group(1)
    frozen_clock.advance(minutes=15)
    r = client.post("/api/account/email/verify", json={"code": code3})
    assert r.status_code == 400 and r.json()["error"]["details"]["attempts_left"] == 0
    # a newer code invalidates the previous one
    client.post("/api/account/email/request-code")
    code4 = re.search(r"(\d{6})", mailer.sent[-1].text).group(1)
    client.post("/api/account/email/request-code")
    code5 = re.search(r"(\d{6})", mailer.sent[-1].text).group(1)
    assert client.post("/api/account/email/verify", json={"code": code4}).status_code == 400
    assert client.post("/api/account/email/verify", json={"code": code5}).status_code == 200
    # SMTP failure → 503 and nothing marked verified by it
    frozen_clock.advance(hours=1)
    mailer.fail_with = "boom"
    r = client.post("/api/account/email/request-code")
    assert r.status_code == 503 and error_code(r) == "email_send_failed"


def test_delete_account_cascade_keeps_shared_private_word(client: TestClient, app, settings):
    alice = register(client, "alice")["user"]  # the only admin
    bob_c = second_client(app)
    bob = register(bob_c, "bob")["user"]
    r = client.request("DELETE", "/api/account", json={"password": PW})
    assert r.status_code == 409 and error_code(r) == "last_admin"
    c = db.connect(settings.db_path)
    try:
        shared = insert_word(c, "zzqx", is_public=0, created_by=bob["id"])
        private = insert_word(c, "zzqy", is_public=0, created_by=bob["id"])
        public = insert_word(c, "abandon")
        for uid, wid in ((bob["id"], shared), (alice["id"], shared), (bob["id"], private), (bob["id"], public)):
            c.execute("INSERT INTO user_words(user_id, word_id, state, origin) VALUES (?, ?, 'new', 'custom')", (uid, wid))
        c.execute("INSERT INTO review_logs(user_id, word_id, action, context, local_date) VALUES (?, ?, 'add_custom', 'api', '2026-10-14')", (bob["id"], shared))
        c.execute("INSERT INTO daily_stats(user_id, local_date, added) VALUES (?, '2026-10-14', 1)", (bob["id"],))
        batch = c.execute("INSERT INTO push_batches(user_id, local_date, timezone, trigger) VALUES (?, '2026-10-14', 'Asia/Shanghai', 'manual')", (bob["id"],)).lastrowid
        c.execute("INSERT INTO push_items(batch_id, word_id, kind, position) VALUES (?, ?, 'new', 1)", (batch, public))
        c.execute("INSERT INTO email_codes(user_id, email, code_hash, expires_at) VALUES (?, 'b@example.com', 'h', '2026-10-14T00:15:00Z')", (bob["id"],))
        c.execute("INSERT INTO bank_suggestions(user_id, type, payload_json) VALUES (?, 'fill_data', '{}')", (bob["id"],))
        c.execute("INSERT INTO content_reports(user_id, word_id, target, reason) VALUES (?, ?, 'content', 'other')", (bob["id"], public))
        job_private = queue.enqueue(c, "lookup_word", {"word_id": private}, dedupe_key=f"lookup:{private}", priority=10, now=NOW_ISO)
        job_shared = queue.enqueue(c, "lookup_word", {"word_id": shared}, dedupe_key=f"lookup:{shared}", priority=10, now=NOW_ISO)
    finally:
        c.close()
    r = bob_c.request("DELETE", "/api/account", json={"password": "wrong-password-1"})
    assert r.status_code == 401 and error_code(r) == "invalid_credentials"
    r = bob_c.request("DELETE", "/api/account", json={"password": PW})
    assert r.status_code == 204 and "wd_session=" in r.headers["set-cookie"].lower()
    for table in ("users", "sessions", "user_settings", "user_words", "review_logs", "daily_stats", "push_batches", "email_codes", "bank_suggestions", "content_reports"):
        assert count(settings, table, "user_id = ?" if table != "users" else "id = ?", (bob["id"],)) == 0, table
    assert count(settings, "push_items", "batch_id = ?", (batch,)) == 0
    c = db.connect(settings.db_path)
    try:
        kept = c.execute("SELECT created_by_user_id, is_public FROM words WHERE id = ?", (shared,)).fetchone()
        assert kept is not None and kept["created_by_user_id"] is None and kept["is_public"] == 0  # alice still holds it
        assert c.execute("SELECT COUNT(*) FROM user_words WHERE user_id = ? AND word_id = ?", (alice["id"], shared)).fetchone()[0] == 1
        assert c.execute("SELECT COUNT(*) FROM words WHERE id = ?", (private,)).fetchone()[0] == 0  # nobody else held it
        assert c.execute("SELECT COUNT(*) FROM words WHERE id = ?", (public,)).fetchone()[0] == 1
        assert c.execute("SELECT status FROM jobs WHERE id = ?", (job_private,)).fetchone()[0] == "cancelled"
        assert c.execute("SELECT status FROM jobs WHERE id = ?", (job_shared,)).fetchone()[0] == "queued"
    finally:
        c.close()
    bob_c.cookies.clear()
    assert bob_c.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me").status_code == 200
    assert register(bob_c, "bob")["user"]["role"] == "user"  # the name is free again; no second bootstrap


def test_export_csv_and_json(client: TestClient, settings):
    alice = register(client, "alice")["user"]
    c = db.connect(settings.db_path)
    try:
        wid = insert_word(c, "abandon", phonetic="ə'bændən", translation="v. 放弃\nn. 放纵")
        c.execute(
            "INSERT INTO user_words(user_id, word_id, state, origin, note, times_added, added_at, ease, interval_days, repetitions, lapses, due_at) "
            "VALUES (?, ?, 'learning', 'browse', '工作中遇到', 2, '2026-10-01T01:00:00Z', 2.6, 3, 2, 0, '2026-10-17T00:00:00Z')",
            (alice["id"], wid),
        )
        c.execute(
            "INSERT INTO review_logs(user_id, word_id, action, context, prev_state, new_state, prev_interval, new_interval, local_date, created_at) VALUES (?, ?, 'good', 'today', 'new', 'learning', 0, 1, '2026-10-02', '2026-10-02T01:00:00Z')",
            (alice["id"], wid),
        )
        c.execute(
            "INSERT INTO review_logs(user_id, word_id, action, context, local_date, created_at) VALUES (?, ?, 'unfamiliar', 'browse', '2025-09-01', '2025-09-01T01:00:00Z')",
            (alice["id"], wid),
        )  # older than 365 days → not exported
    finally:
        c.close()
    r = client.get("/api/account/export?format=csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert r.headers["content-disposition"] == 'attachment; filename="word-dance-export-20261014.csv"'
    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows[0] == list(EXPORT_COLUMNS) and len(rows) == 2
    row = dict(zip(rows[0], rows[1]))
    assert row["word"] == "abandon" and row["state"] == "learning" and row["times_added"] == "2" and row["ease"] == "2.6" and row["mastered_at"] == ""
    assert row["translation"] == "v. 放弃\nn. 放纵" and row["due_at"] == "2026-10-17T00:00:00Z"
    r = client.get("/api/account/export?format=json")
    assert r.status_code == 200 and r.headers["content-disposition"] == 'attachment; filename="word-dance-export-20261014.json"'
    body = r.json()
    assert body["version"] == 1 and body["exported_at"] == NOW_ISO and body["username"] == "alice"
    assert len(body["words"]) == 1 and set(body["words"][0]) == set(EXPORT_COLUMNS) and body["words"][0]["interval_days"] == 3
    assert body["review_logs"] == [{"created_at": "2026-10-02T01:00:00Z", "word": "abandon", "action": "good", "context": "today", "prev_state": "new", "new_state": "learning", "prev_interval": 0, "new_interval": 1}]
    assert client.get("/api/account/export").headers["content-type"].startswith("application/json")  # default json
    r = client.get("/api/account/export?format=xml")
    assert r.status_code == 400 and error_code(r) == "validation_error"
