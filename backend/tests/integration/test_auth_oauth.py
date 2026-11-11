"""Endpoints 118–122 (API.md §3.3, slice 2-A) with the fake providers installed as ``app.state.qq`` / ``app.state.apple``: the start
redirects with a verifiable state (next sanitised, invite carried, bind needs a non-child session, per-IP window) and the ``wd_oauth``
browser cookie whose hash the state carries; the QQ callback verifies the provider and mints a grant WITHOUT writing an identity or an
account; the finish hop (122) refuses any browser but the one that started the flow (an attacker's bind state in the victim's browser,
an attacker's login state, a handed-over finish URL, a bind grant in a browser whose session belongs to someone else — nothing written,
the victim's session untouched) and then does the login (created → /welcome, existing → next, the browser's previous session replaced)
or the bind (/settings?bound=qq, no new session) — the grant single use and 60 s, the shared helper's refusals as `?error=` redirects
from 122, every callback error as a 302 with `?error=` (a non-ASCII state included), the callbacks' per-IP windows, Apple's form_post
with a fake id_token (good / wrong nonce / expired / cancelled / CSRF exemption), `provider_unconfigured` when off, `User.providers`,
the startup warning for a callback URL without WD_PUBLIC_URL, and the fake consent pages that exist only under WD_AUTH_FAKE_PROVIDERS."""

from __future__ import annotations

import html
import json
import logging
import re
from dataclasses import replace
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from wd import db, oauth_state, security
from wd.routers import auth_oauth
from wd.delivery.apple import FAKE_AUDIENCE, FakeAppleKeys, fake_id_token
from wd.delivery.qq import FakeQQClient
from wd.main import create_app

PW = "Correct-Horse-7"
NOW_ISO = "2026-10-14T00:00:00Z"
NOW = datetime(2026, 10, 14, 0, 0, 0, tzinfo=timezone.utc)
PLACEHOLDER_RE = re.compile(r"^u_[a-z2-7]{8}$")
FINISH = "http://testserver/api/auth/oauth/finish?grant="
OAUTH_COOKIE = oauth_state.OAUTH_COOKIE


@pytest.fixture(autouse=True)
def fast_bcrypt(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(security, "BCRYPT_ROUNDS", 4)


@pytest.fixture
def qq(app) -> FakeQQClient:
    fake = FakeQQClient()
    app.state.qq = fake
    return fake


@pytest.fixture
def apple_keys(app) -> FakeAppleKeys:
    keys = FakeAppleKeys()
    app.state.apple = keys
    return keys


def second_client(app, *, csrf: bool = True) -> TestClient:
    c = TestClient(app, base_url="http://testserver")
    if csrf:
        c.headers["X-WD-Request"] = "1"
    return c


def bootstrap(client: TestClient, username: str = "root") -> dict:
    """The first account is a username + password registration (admin): a third-party sign-in refuses an empty site (setup_required)."""
    r = client.post("/api/auth/register", json={"username": username, "password": PW})
    assert r.status_code == 201, r.text
    return r.json()["user"]


def register(client: TestClient, username: str) -> dict:
    r = client.post("/api/auth/register", json={"username": username, "password": PW})
    assert r.status_code == 201, r.text
    return r.json()["user"]


def error_code(r) -> str:
    return r.json()["error"]["code"]


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


def location(r) -> str:
    assert r.status_code == 302, (r.status_code, r.text)
    return r.headers["location"]


def query(url: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query, keep_blank_values=True).items()}


def set_cookies(r) -> list[str]:
    return [c.lower() for c in r.headers.get_list("set-cookie")]


def start_response(client: TestClient, provider: str, **params):
    return client.get(f"/api/auth/{provider}/start", params=params, follow_redirects=False)


def start(client: TestClient, provider: str, **params) -> tuple[str, dict[str, str]]:
    """``GET /api/auth/<provider>/start`` → (its 302 location, the location's query); the ``wd_oauth`` cookie lands in ``client``'s jar."""
    url = location(start_response(client, provider, **params))
    return url, query(url)


def qq_callback(client: TestClient, state: str | None, code: str | None, **extra):
    params = {k: v for k, v in {"code": code, "state": state, **extra}.items() if v is not None}
    return client.get("/api/auth/qq/callback", params=params, follow_redirects=False)


def apple_callback(client: TestClient, **form):
    return client.post("/api/auth/apple/callback", data={k: v for k, v in form.items() if v is not None}, headers={"Origin": "https://appleid.apple.com"}, follow_redirects=False)


def finish(client: TestClient, url: str):
    assert url.startswith(FINISH), url
    return client.get(url, follow_redirects=False)


def qq_sign_in(client: TestClient, code: str, **start_params):
    """start → callback → finish for ``code`` in ONE client (the cookie travels); returns the finish response (its Set-Cookie signs ``client`` in)."""
    _url, q = start(client, "qq", **start_params)
    return finish(client, location(qq_callback(client, q["state"], code)))


def oauth_cookie(client: TestClient) -> str | None:
    return client.cookies.get(OAUTH_COOKIE)


def sessions_of(settings, user_id: int) -> int:
    return count(settings, "sessions", "user_id = ?", (user_id,))


# --------------------------------------------------------------------------------------------- 118 (start)
def test_qq_start_redirects_to_the_consent_page_with_a_verifiable_state(client: TestClient, app, settings, qq, frozen_clock):
    bootstrap(client)
    learner = second_client(app)
    r = start_response(learner, "qq", kind="login", next="/bank")
    url = location(r)
    q = query(url)
    assert url.startswith("/api/auth/fake/qq?state=") and set(q) == {"state"}
    # the browser secret: an HttpOnly cookie under /api/auth, 10 minutes, its sha256 inside the signed state
    cookie = next(c for c in set_cookies(r) if c.startswith("wd_oauth="))
    assert "httponly" in cookie and "samesite=lax" in cookie and "path=/api/auth" in cookie and "max-age=600" in cookie and "secure" not in cookie
    secret = oauth_cookie(learner)
    assert secret and re.fullmatch(r"[A-Za-z0-9_-]{43}", secret) and secret not in q["state"]
    payload = oauth_state.verify(settings, "qq", q["state"], frozen_clock.now_utc())
    assert payload == {"kind": "login", "next": "/bank", "bh": oauth_state.browser_hash(secret)}
    assert qq.calls == [("authorize_url", q["state"])]
    exp = int(q["state"].split(".")[0])
    assert exp == int(frozen_clock.now_utc().timestamp()) + 600
    # default kind, a foreign `next` sanitised, the invite code carried for a login; every start draws a fresh secret
    _url, q = start(learner, "qq", next="https://evil.example/", invite_code=" ABCD-EFGH-JKLM-NPQR ")
    assert oauth_cookie(learner) != secret
    assert oauth_state.verify(settings, "qq", q["state"], frozen_clock.now_utc()) == {"kind": "login", "next": "/", "invite": "ABCD-EFGH-JKLM-NPQR", "bh": oauth_state.browser_hash(oauth_cookie(learner))}
    r = learner.get("/api/auth/qq/start", params={"kind": "scan"}, follow_redirects=False)
    assert r.status_code == 400 and error_code(r) == "validation_error" and r.json()["error"]["details"]["fields"] == {"kind": "取值无效"}
    r = learner.get("/api/auth/qq/start", params={"kind": "bind"}, follow_redirects=False)
    assert r.status_code == 401 and error_code(r) == "unauthorized" and not set_cookies(r)  # a bind needs a session; a refusal sets no cookie
    # a bind state carries the session's user id and never an invite
    alice = register(learner, "alice")
    _url, q = start(learner, "qq", kind="bind", next="/settings", invite_code="X")
    assert oauth_state.verify(settings, "qq", q["state"], frozen_clock.now_utc()) == {"kind": "bind", "uid": alice["id"], "next": "/settings", "bh": oauth_state.browser_hash(oauth_cookie(learner))}
    assert count(settings, "auth_throttle", "key = 'qq_start:ip:testclient'") == 1


def test_start_is_rate_limited_per_ip_and_provider(client: TestClient, app, qq, apple_keys):
    bootstrap(client)
    learner = second_client(app)
    for _ in range(10):
        start(learner, "qq")
    r = learner.get("/api/auth/qq/start", follow_redirects=False)
    assert r.status_code == 429 and error_code(r) == "rate_limited" and r.json()["error"]["details"]["retry_after_s"] == 60 and r.headers["Retry-After"] == "60"
    start(learner, "apple")  # its own window
    for _ in range(9):
        start(learner, "apple")
    assert learner.get("/api/auth/apple/start", follow_redirects=False).status_code == 429


# ----------------------------------------------------------------------------------------- 119 + 122 (login)
def test_qq_login_creates_an_account_and_the_finish_hop_issues_the_session(client: TestClient, app, settings, qq, frozen_clock):
    bootstrap(client)
    learner = second_client(app)
    _url, q = start(learner, "qq", next="/bank")
    secret = oauth_cookie(learner)
    r = qq_callback(learner, q["state"], "qq-code-alice")
    finish_url = location(r)
    assert finish_url.startswith(FINISH) and "set-cookie" not in r.headers  # the callback never sets a cookie: the grant carries the result
    grant = query(finish_url)["grant"]
    assert len(grant) >= 43
    assert qq.calls[1:] == [("exchange", "qq-code-alice"), ("openid", "qq-token-alice")]
    keys = rows(settings, "SELECT key, value FROM kv WHERE key LIKE 'oauth_grant:%'")
    assert len(keys) == 1 and keys[0]["key"] == f"oauth_grant:2026-10-14T00:01:00Z:{oauth_state.grant_hash(grant)}" and grant not in keys[0]["key"]
    # the grant holds the VERIFIED subject and the browser hash — the callback wrote no account and no identity (it may run on the relay origin)
    assert json.loads(keys[0]["value"]) == {"provider": "qq", "subject": "qq_alice", "kind": "login", "invite": None, "next": "/bank", "bh": oauth_state.browser_hash(secret)}
    assert count(settings, "users") == 1 and count(settings, "identities") == 0 and count(settings, "sessions") == 1
    assert learner.get("/api/auth/me").status_code == 401

    r = finish(learner, finish_url)
    assert location(r) == "/welcome"  # a created account goes to the first-time setup whatever `next` said
    cookies = set_cookies(r)
    session_cookie = next(c for c in cookies if c.startswith("wd_session="))
    assert "httponly" in session_cookie and "max-age=2592000" in session_cookie and "path=/" in session_cookie
    cleared = next(c for c in cookies if c.startswith("wd_oauth="))
    assert 'wd_oauth=""' in cleared and ("max-age=0" in cleared or "expires=" in cleared) and "path=/api/auth" in cleared  # the flow is over
    assert oauth_cookie(learner) is None
    assert count(settings, "kv", "key LIKE 'oauth_grant:%'") == 0
    me = learner.get("/api/auth/me")
    assert me.status_code == 200, me.text
    user = me.json()["user"]
    user_id = user["id"]
    assert user["needs_profile"] is True and user["has_password"] is False and user["phone_masked"] is None and user["email"] is None
    assert user["providers"] == ["qq"] and user["account_kind"] == "learner" and user["is_child"] is False and user["needs_profile_prompt"] is False
    assert me.json()["server"]["qq_enabled"] is True and me.json()["server"]["wechat_enabled"] is False
    account = rows(settings, "SELECT * FROM users WHERE id = ?", (user_id,))[0]
    assert PLACEHOLDER_RE.match(account["username"]) and account["password_set_at"] is None and account["display_name"] is None and account["account_kind"] == "learner" and account["role"] == "user"
    assert account["password_hash"].startswith("$2b$") and not security.verify_password("", account["password_hash"]) and account["last_login_at"] == NOW_ISO
    identity = rows(settings, "SELECT * FROM identities WHERE user_id = ?", (user_id,))[0]
    assert (identity["provider"], identity["subject"], identity["verified_at"], identity["last_login_at"], identity["disputed_at"]) == ("qq", "qq_alice", NOW_ISO, NOW_ISO, None)
    assert sessions_of(settings, user_id) == 1
    # a password login against the account is a plain 401 (unusable hash)
    assert second_client(app).post("/api/auth/login", json={"username": account["username"], "password": PW}).status_code == 401

    # the second sign-in is a login: no new account, `next` honoured, last_login_at refreshed on the identity and the user
    frozen_clock.advance(minutes=1)
    other = second_client(app)
    r = qq_sign_in(other, "qq-code-alice", next="/bank")
    assert location(r) == "/bank"
    assert count(settings, "users") == 2 and count(settings, "identities") == 1 and sessions_of(settings, user_id) == 2
    assert rows(settings, "SELECT last_login_at FROM identities WHERE user_id = ?", (user_id,))[0]["last_login_at"] == "2026-10-14T00:01:00Z"
    assert rows(settings, "SELECT last_login_at FROM users WHERE id = ?", (user_id,))[0]["last_login_at"] == "2026-10-14T00:01:00Z"
    assert other.get("/api/auth/me").json()["user"]["id"] == user_id
    # the default `next` is the home page
    assert location(qq_sign_in(second_client(app), "qq-code-alice")) == "/"
    # a login from a browser that already holds a session replaces that session (its own), it does not pile up
    root_client = client
    before = count(settings, "sessions")
    assert location(qq_sign_in(root_client, "qq-code-alice", next="/bank")) == "/bank"
    assert count(settings, "sessions") == before and root_client.get("/api/auth/me").json()["user"]["id"] == user_id


def test_the_grant_is_single_use_and_expires_after_sixty_seconds(client: TestClient, app, settings, qq, frozen_clock):
    bootstrap(client)
    learner = second_client(app)
    _url, q = start(learner, "qq")
    finish_url = location(qq_callback(learner, q["state"], "qq-code-bob"))
    assert location(finish(learner, finish_url)) == "/welcome"
    r = finish(learner, finish_url)
    assert location(r) == "/login?error=invalid_grant" and "set-cookie" not in r.headers  # used
    assert learner.get("/api/auth/me").status_code == 200  # the refusal touches no session
    _url, q = start(learner, "qq")
    finish_url = location(qq_callback(learner, q["state"], "qq-code-bob"))
    frozen_clock.advance(seconds=61)
    r = finish(learner, finish_url)
    assert location(r) == "/login?error=invalid_grant" and "set-cookie" not in r.headers
    assert count(settings, "kv", "key LIKE 'oauth_grant:%'") == 0  # the expired row is dropped by the redeem
    for junk in ("", "nonsense", "a" * 200):
        assert location(second_client(app).get("/api/auth/oauth/finish", params={"grant": junk}, follow_redirects=False)) == "/login?error=invalid_grant"
    assert location(second_client(app).get("/api/auth/oauth/finish", follow_redirects=False)) == "/login?error=invalid_grant"
    # a grant whose account was disabled meanwhile: the shared rules refuse at the finish
    bob = rows(settings, "SELECT user_id FROM identities WHERE subject = 'qq_bob'")[0]["user_id"]
    _url, q = start(learner, "qq")
    finish_url = location(qq_callback(learner, q["state"], "qq-code-bob"))
    execute(settings, "UPDATE users SET is_active = 0 WHERE id = ?", (bob,))
    r = finish(learner, finish_url)
    assert location(r) == "/login?error=account_disabled" and "wd_session=" not in r.headers.get("set-cookie", "")
    execute(settings, "UPDATE users SET is_active = 1 WHERE id = ?", (bob,))
    # an account deleted between the callback and the finish: its identity went with it, so the verified subject is new again
    _url, q = start(learner, "qq")
    finish_url = location(qq_callback(learner, q["state"], "qq-code-bob"))
    execute(settings, "DELETE FROM users WHERE id = ?", (bob,))
    assert location(finish(learner, finish_url)) == "/welcome"
    fresh = rows(settings, "SELECT i.created_at, u.created_at AS user_created_at FROM identities i JOIN users u ON u.id = i.user_id WHERE i.subject = 'qq_bob'")
    assert count(settings, "users") == 2 and fresh == [{"created_at": "2026-10-14T00:01:01Z", "user_created_at": "2026-10-14T00:01:01Z"}]  # a new account (SQLite may reuse the id)


def test_qq_callback_errors_become_redirects(client: TestClient, app, settings, qq, frozen_clock):
    bootstrap(client)
    learner = second_client(app)
    _url, q = start(learner, "qq")
    state = q["state"]
    exp, body, mac = state.split(".")
    assert location(qq_callback(learner, f"{exp}.{body}.{mac[:-1]}", "qq-code-x")) == "/login?error=invalid_identity_token"  # tampered
    assert location(qq_callback(learner, "garbage", "qq-code-x")) == "/login?error=invalid_identity_token"
    assert location(qq_callback(learner, None, "qq-code-x")) == "/login?error=invalid_identity_token"
    assert location(qq_callback(learner, state, "bad-code")) == "/login?error=invalid_identity_token"  # QQ refused the code
    assert location(qq_callback(learner, state, "down-code")) == "/login?error=provider_error"  # QQ unreachable
    assert location(qq_callback(learner, state, None)) == "/login"  # no code: the user came back without authorising
    assert location(qq_callback(learner, state, "qq-code-x", usercancel="1")) == "/login"
    assert location(qq_callback(learner, "garbage", None, usercancel="1")) == "/login"
    assert location(qq_callback(learner, state, None, msg="denied")) == "/login"
    # a crafted state is refused like any other, never a 500: Unicode digits (`str.isdigit()` true), non-ASCII hex, full-width digits
    for odd in ("²².abc.def", "².eyJraW5kIjoibG9naW4ifQ.00", "1800000000.abc.dé", "１２.abc.def", "١٢٣.abc.def", f"{exp}.{body}.{mac[:-1]}é"):
        assert location(qq_callback(learner, odd, "qq-code-x")) == "/login?error=invalid_identity_token", odd
        assert location(qq_callback(learner, odd, None, usercancel="1")) == "/login", odd  # the cancel path peeks at the state too
    # a state without the browser binding (not minted by this code) is not finished either
    unbound = oauth_state.sign(settings, "qq", {"kind": "login", "next": "/"}, frozen_clock.now_utc())
    assert location(qq_callback(learner, unbound, "qq-code-x")) == "/login?error=invalid_identity_token"
    frozen_clock.advance(seconds=601)
    assert location(qq_callback(learner, state, "qq-code-x")) == "/login?error=invalid_identity_token"  # the state expired
    assert count(settings, "users") == 1 and count(settings, "identities") == 0 and count(settings, "kv", "key LIKE 'oauth_grant:%'") == 0
    # a bind state sends the errors to the settings page
    alice_client = second_client(app)
    register(alice_client, "alice")
    _url, bq = start(alice_client, "qq", kind="bind")
    assert location(qq_callback(alice_client, bq["state"], None, usercancel="1")) == "/settings"
    assert location(qq_callback(alice_client, bq["state"], "bad-code")) == "/settings?error=invalid_identity_token"


def test_callbacks_are_rate_limited_per_ip(client: TestClient, app, settings, qq, apple_keys, frozen_clock, monkeypatch: pytest.MonkeyPatch):
    """119 / 121 are public (121 CSRF-exempt): CALLBACK_IP_LIMIT per minute per IP (600 in production — a flood brake, the relay collapses IPs),
    the next one is the error redirect; each provider has its own window. The limit is lowered to 60 here to keep the test quick."""
    monkeypatch.setattr(auth_oauth, "CALLBACK_IP_LIMIT", 60)
    bootstrap(client)
    learner = second_client(app)
    _url, q = start(learner, "qq")
    for _ in range(60):
        assert location(qq_callback(learner, q["state"], "bad-code")) == "/login?error=invalid_identity_token"
    assert location(qq_callback(learner, q["state"], "bad-code")) == "/login?error=rate_limited"
    assert location(qq_callback(learner, q["state"], "qq-code-fine")) == "/login?error=rate_limited"  # a good code too: the window is per IP
    assert count(settings, "auth_throttle", "key = 'qq_callback:ip:testclient'") == 1
    browser = second_client(app, csrf=False)
    _url, aq = start(browser, "apple")
    for _ in range(60):
        assert location(apple_callback(browser, state=aq["state"], id_token="x.y.z")) == "/login?error=invalid_identity_token"
    assert location(apple_callback(browser, state=aq["state"], id_token="x.y.z")) == "/login?error=rate_limited"
    assert apple_keys.fetches == 0  # a token that is not even a JWS never reaches the key set
    # a bind state lands the limit on the settings page; the window passes after a minute
    alice_client = second_client(app)
    register(alice_client, "alice")
    _url, bq = start(alice_client, "qq", kind="bind")
    assert location(qq_callback(alice_client, bq["state"], "qq-code-alice")) == "/settings?error=rate_limited"
    frozen_clock.advance(seconds=61)
    assert location(qq_callback(learner, q["state"], "bad-code")) == "/login?error=invalid_identity_token"
    assert count(settings, "identities") == 0


def test_the_finish_hop_targets_the_public_url_when_set(settings, frozen_clock):
    # WD_COOKIE_SECURE=0: with an https WD_PUBLIC_URL the cookies would be `Secure`, which the http test client (rightly) never sends back
    app = create_app(replace(settings, public_url="https://words.example.com", cookie_secure="0"), clock=frozen_clock, configure_logs=False)
    app.state.qq = FakeQQClient()
    with TestClient(app, base_url="http://testserver") as c:
        c.headers["X-WD-Request"] = "1"
        bootstrap(c)
        learner = second_client(app)
        _url, q = start(learner, "qq")
        url = location(qq_callback(learner, q["state"], "qq-code-alice"))
        assert url.startswith("https://words.example.com/api/auth/oauth/finish?grant=")
        # the grant works on the SPA's origin (here the same test server), in the browser that started the flow
        r = learner.get("/api/auth/oauth/finish", params={"grant": query(url)["grant"]}, follow_redirects=False)
        assert location(r) == "/welcome" and "wd_session=" in r.headers["set-cookie"]


# ------------------------------------------------------------------------------------------- bind
def test_qq_bind_attaches_the_identity_to_the_session_account(client: TestClient, app, settings, qq, frozen_clock):
    root = bootstrap(client)
    alice_client = second_client(app)
    alice = register(alice_client, "alice")
    frozen_clock.advance(minutes=1)
    _url, q = start(alice_client, "qq", kind="bind", next="/settings")
    r = qq_callback(alice_client, q["state"], "qq-code-alice")
    finish_url = location(r)
    assert count(settings, "identities") == 0  # the callback only verified QQ: the bind itself waits for the browser that owns the session
    # the callback may land on another origin, but the FINISH runs on the SPA origin: a browser without alice's cookies is refused and nothing happens
    stranger = second_client(app)
    r = finish(stranger, finish_url)
    assert location(r) == "/settings?error=invalid_grant" and "set-cookie" not in r.headers
    assert count(settings, "identities") == 0 and stranger.get("/api/auth/me").status_code == 401 and sessions_of(settings, alice["id"]) == 1
    assert count(settings, "kv", "key LIKE 'oauth_grant:%'") == 0  # the refused grant was spent all the same
    # alice's own browser: the identity is written, her session is kept (no new one), the cookie cleared
    _url, q = start(alice_client, "qq", kind="bind", next="/settings")
    r = finish(alice_client, location(qq_callback(alice_client, q["state"], "qq-code-alice")))
    assert location(r) == "/settings?bound=qq"
    cookies = set_cookies(r)
    assert not any(c.startswith("wd_session=") for c in cookies) and any('wd_oauth=""' in c for c in cookies)
    identity = rows(settings, "SELECT * FROM identities WHERE user_id = ?", (alice["id"],))[0]
    assert (identity["provider"], identity["subject"], identity["verified_at"], identity["last_login_at"]) == ("qq", "qq_alice", "2026-10-14T00:01:00Z", "2026-10-14T00:01:00Z")
    assert rows(settings, "SELECT last_login_at FROM users WHERE id = ?", (alice["id"],))[0]["last_login_at"] is None  # a bind is not a login (register sets none)
    me = alice_client.get("/api/auth/me").json()
    assert me["user"]["providers"] == ["qq"] and me["user"]["has_password"] is True
    assert sessions_of(settings, alice["id"]) == 1  # the register session, and nothing else: a bind mints no session
    # binding the same QQ again is idempotent; a second QQ on the same account and alice's QQ on another account are refused at the finish
    _url, q = start(alice_client, "qq", kind="bind")
    assert location(finish(alice_client, location(qq_callback(alice_client, q["state"], "qq-code-alice")))) == "/settings?bound=qq"
    _url, q = start(alice_client, "qq", kind="bind")
    assert location(finish(alice_client, location(qq_callback(alice_client, q["state"], "qq-code-alice2")))) == "/settings?error=identity_taken"
    bob_client = second_client(app)
    bob = register(bob_client, "bob")
    _url, q = start(bob_client, "qq", kind="bind")
    assert location(finish(bob_client, location(qq_callback(bob_client, q["state"], "qq-code-alice")))) == "/settings?error=identity_taken"
    assert count(settings, "identities") == 1 and sessions_of(settings, bob["id"]) == 1 and bob_client.get("/api/auth/me").json()["user"]["id"] == bob["id"]
    # a learner who binds can then sign in through QQ (existing account, no new one)
    frozen_clock.advance(minutes=1)
    assert location(qq_sign_in(second_client(app), "qq-code-alice", next="/history")) == "/history"
    assert count(settings, "users") == 3
    # a child account cannot bind (the §1 restriction list)
    execute(settings, "UPDATE users SET guardian_user_id = ? WHERE id = ?", (root["id"], alice["id"]))
    r = alice_client.get("/api/auth/qq/start", params={"kind": "bind"}, follow_redirects=False)
    assert r.status_code == 403 and error_code(r) == "guardian_required"


def test_a_state_started_by_another_browser_is_useless_in_the_victims_browser(client: TestClient, app, settings, qq, apple_keys, frozen_clock):
    """The review's hijack scenarios: an attacker's bind state (fixation) or login state (login CSRF), or a handed-over finish URL, visited
    by the victim's browser — which lacks the attacker's `wd_oauth` cookie — binds nothing, signs nobody in and leaves the victim's own
    session alone."""
    bootstrap(client)
    attacker = second_client(app)
    mallory = register(attacker, "mallory")
    victim = second_client(app)
    alice = register(victim, "alice")
    # 1 bind-state fixation: mallory starts a BIND with her session and lures alice to the provider with that state; QQ sends alice's
    #   browser to the callback with ALICE's code — the callback cannot tell (it may run on the relay) and mints a grant, nothing more
    _url, q = start(attacker, "qq", kind="bind")
    finish_url = location(qq_callback(victim, q["state"], "qq-code-victimqq"))
    assert count(settings, "identities") == 0
    r = finish(victim, finish_url)
    assert location(r) == "/settings?error=invalid_grant" and "set-cookie" not in r.headers
    assert count(settings, "identities") == 0 and count(settings, "users") == 3
    assert victim.get("/api/auth/me").json()["user"]["id"] == alice["id"] and sessions_of(settings, alice["id"]) == 1
    # alice's QQ stays hers: signing in with it later makes a NEW account, not mallory's
    fresh = second_client(app)
    assert location(qq_sign_in(fresh, "qq-code-victimqq")) == "/welcome"
    assert fresh.get("/api/auth/me").json()["user"]["id"] not in (alice["id"], mallory["id"])
    # 2 login CSRF: a login state from anybody's browser + the attacker's own code, visited by the victim
    anybody = second_client(app)
    _url, q = start(anybody, "qq")
    finish_url = location(qq_callback(victim, q["state"], "qq-code-mallory"))
    r = finish(victim, finish_url)
    assert location(r) == "/login?error=invalid_grant" and "set-cookie" not in r.headers
    assert victim.get("/api/auth/me").json()["user"]["id"] == alice["id"] and sessions_of(settings, alice["id"]) == 1
    assert count(settings, "identities", "subject = 'qq_mallory'") == 0  # no account for the attacker's code either
    # 3 a handed-over finish URL: the attacker runs start + callback herself and makes the victim open the 60 s bearer URL
    _url, q = start(attacker, "qq")
    finish_url = location(qq_callback(attacker, q["state"], "qq-code-mallory"))
    r = finish(victim, finish_url)
    assert location(r) == "/login?error=invalid_grant" and "set-cookie" not in r.headers
    assert victim.get("/api/auth/me").json()["user"]["id"] == alice["id"] and sessions_of(settings, alice["id"]) == 1
    assert location(finish(attacker, finish_url)) == "/login?error=invalid_grant"  # and the grant is spent: single use
    assert attacker.get("/api/auth/me").json()["user"]["id"] == mallory["id"]
    # 4 Apple: a cross-site form_post with the attacker's bind state and the victim's id_token (121 is CSRF-exempt) — the same dead end
    _url, aq = start(attacker, "apple", kind="bind")
    token = fake_id_token("apple_alice", aud=FAKE_AUDIENCE, nonce=aq["nonce"], now=frozen_clock.now_utc())
    finish_url = location(apple_callback(victim, state=aq["state"], id_token=token))
    r = finish(victim, finish_url)
    assert location(r) == "/settings?error=invalid_grant"
    assert count(settings, "identities", "provider = 'apple'") == 0 and victim.get("/api/auth/me").json()["user"]["id"] == alice["id"] and sessions_of(settings, alice["id"]) == 1
    # the attacker's own browser finishing her own LOGIN flow still works, of course
    _url, q = start(attacker, "qq")
    assert location(finish(attacker, location(qq_callback(attacker, q["state"], "qq-code-mallory")))) == "/welcome"


def test_a_bind_grant_needs_the_binders_own_session_in_the_browser(client: TestClient, app, settings, qq):
    """A bind grant carries the account that started it; 122 insists the browser's current session belongs to that account (the cookie
    alone is not enough — alice may have signed out, or bob signed in on the same browser)."""
    bootstrap(client)
    alice_client = second_client(app)
    alice = register(alice_client, "alice")
    bob_client = second_client(app)
    bob = register(bob_client, "bob")
    # the same browser secret, but bob's session: refused, nothing written, bob keeps his session
    _url, q = start(alice_client, "qq", kind="bind")
    finish_url = location(qq_callback(alice_client, q["state"], "qq-code-alice"))
    bob_client.cookies.set(OAUTH_COOKIE, oauth_cookie(alice_client), domain="testserver", path=oauth_state.OAUTH_COOKIE_PATH)
    r = finish(bob_client, finish_url)
    assert location(r) == "/settings?error=invalid_grant" and "set-cookie" not in r.headers
    assert count(settings, "identities") == 0 and bob_client.get("/api/auth/me").json()["user"]["id"] == bob["id"] and sessions_of(settings, bob["id"]) == 1
    # the cookie but no session at all (alice signed out between the start and the finish)
    _url, q = start(alice_client, "qq", kind="bind")
    finish_url = location(qq_callback(alice_client, q["state"], "qq-code-alice"))
    assert alice_client.post("/api/auth/logout").status_code == 204
    assert oauth_cookie(alice_client) is not None
    r = finish(alice_client, finish_url)
    assert location(r) == "/settings?error=invalid_grant" and "set-cookie" not in r.headers and count(settings, "identities") == 0
    # the cookie and a session for a DISABLED binder
    assert alice_client.post("/api/auth/login", json={"username": "alice", "password": PW}).status_code == 200
    _url, q = start(alice_client, "qq", kind="bind")
    finish_url = location(qq_callback(alice_client, q["state"], "qq-code-alice"))
    execute(settings, "UPDATE users SET is_active = 0 WHERE id = ?", (alice["id"],))
    assert location(finish(alice_client, finish_url)) == "/settings?error=account_disabled" and count(settings, "identities") == 0
    execute(settings, "UPDATE users SET is_active = 1 WHERE id = ?", (alice["id"],))
    # alice, signed in, in her own browser: bound, her session kept
    _url, q = start(alice_client, "qq", kind="bind")
    assert location(finish(alice_client, location(qq_callback(alice_client, q["state"], "qq-code-alice")))) == "/settings?bound=qq"
    assert rows(settings, "SELECT user_id, subject FROM identities") == [{"user_id": alice["id"], "subject": "qq_alice"}]
    assert alice_client.get("/api/auth/me").json()["user"]["providers"] == ["qq"] and sessions_of(settings, alice["id"]) == 1


# --------------------------------------------------------------------------- the shared login rules (admins, disabled, modes)
def test_admin_and_disabled_accounts_cannot_sign_in_through_qq(client: TestClient, app, settings, qq):
    root = bootstrap(client)
    execute(settings, "INSERT INTO identities(user_id, provider, subject, verified_at, last_login_at, created_at) VALUES (?, 'qq', 'qq_root', ?, ?, ?)", (root["id"], NOW_ISO, NOW_ISO, NOW_ISO))
    learner = second_client(app)
    _url, q = start(learner, "qq")
    finish_url = location(qq_callback(learner, q["state"], "qq-code-root"))  # the callback only verifies QQ; the rule fires at the finish
    r = finish(learner, finish_url)
    assert location(r) == "/login?error=password_required" and "wd_session=" not in r.headers.get("set-cookie", "")
    assert learner.get("/api/auth/me").status_code == 401 and count(settings, "kv", "key LIKE 'oauth_grant:%'") == 0 and sessions_of(settings, root["id"]) == 1
    # a disabled learner with a QQ identity
    bob_client = second_client(app)
    bob = register(bob_client, "bob")
    execute(settings, "INSERT INTO identities(user_id, provider, subject, verified_at, last_login_at, created_at) VALUES (?, 'qq', 'qq_bob', ?, ?, ?)", (bob["id"], NOW_ISO, NOW_ISO, NOW_ISO))
    execute(settings, "UPDATE users SET is_active = 0 WHERE id = ?", (bob["id"],))
    _url, q = start(learner, "qq")
    assert location(finish(learner, location(qq_callback(learner, q["state"], "qq-code-bob")))) == "/login?error=account_disabled"
    assert count(settings, "users") == 2 and learner.get("/api/auth/me").status_code == 401


def test_registration_modes_apply_to_new_qq_accounts(settings, frozen_clock):
    def app_in(mode: str):
        a = create_app(replace(settings, registration_mode=mode), clock=frozen_clock, configure_logs=False)
        a.state.qq = FakeQQClient()
        return a

    # an empty site: no account from a third party (the bootstrap rule of endpoint 2)
    empty = app_in("open")
    with TestClient(empty, base_url="http://testserver") as c:
        c.headers["X-WD-Request"] = "1"
        assert location(qq_sign_in(c, "qq-code-first")) == "/login?error=setup_required"
        assert count(settings, "users") == 0
        bootstrap(c)
    closed = app_in("closed")
    with TestClient(closed, base_url="http://testserver") as c:
        c.headers["X-WD-Request"] = "1"
        learner = second_client(closed)
        assert location(qq_sign_in(learner, "qq-code-new")) == "/login?error=registration_closed"
        assert count(settings, "users") == 1 and learner.get("/api/auth/me").status_code == 401
        # an existing binding still signs in while registration is closed (closed mode refuses registrations: the account is inserted directly)
        execute(settings, "INSERT INTO users(username, password_hash, role, created_at, updated_at, onboarding_state) VALUES ('carol', ?, 'user', ?, ?, 'pending')", (security.hash_password(PW), NOW_ISO, NOW_ISO))
        carol_id = rows(settings, "SELECT id FROM users WHERE username = 'carol'")[0]["id"]
        execute(settings, "INSERT INTO identities(user_id, provider, subject, verified_at, last_login_at, created_at) VALUES (?, 'qq', 'qq_carol', ?, ?, ?)", (carol_id, NOW_ISO, NOW_ISO, NOW_ISO))
        r = qq_sign_in(second_client(closed), "qq-code-carol")
        assert location(r) == "/" and "wd_session=" in r.headers["set-cookie"]
    invite = app_in("invite")
    with TestClient(invite, base_url="http://testserver") as c:
        c.headers["X-WD-Request"] = "1"
        learner = second_client(invite)
        assert location(qq_sign_in(learner, "qq-code-dave")) == "/login?error=invalid_invite"
        assert location(qq_sign_in(learner, "qq-code-dave", invite_code="NOPE-NOPE-NOPE-NOPE")) == "/login?error=invalid_invite"
        conn = db.connect(settings.db_path)
        try:
            with db.tx(conn):
                _id, code, _exp = security.create_invite(conn, created_by=None, max_uses=1, now=frozen_clock.now_utc())
        finally:
            conn.close()
        assert rows(settings, "SELECT uses FROM invite_codes")[0]["uses"] == 0  # the start only carries the code; nothing consumed before the finish
        assert location(qq_sign_in(learner, "qq-code-dave", invite_code=code)) == "/welcome"
        assert rows(settings, "SELECT uses FROM invite_codes")[0]["uses"] == 1  # consumed with the account, at the finish
        assert learner.get("/api/auth/me").json()["user"]["providers"] == ["qq"]
        assert location(qq_sign_in(second_client(invite), "qq-code-erin", invite_code=code)) == "/login?error=invalid_invite"  # used up
    verified = app_in("verified")
    with TestClient(verified, base_url="http://testserver") as c:
        c.headers["X-WD-Request"] = "1"
        r = qq_sign_in(second_client(verified), "qq-code-frank")
        assert location(r) == "/welcome"  # a third-party identity counts as verified
    assert count(settings, "users") == 4


# ------------------------------------------------------------------------------------------ 120 / 121 (Apple)
def test_apple_start_and_callback_sign_in_with_a_fake_id_token(client: TestClient, app, settings, apple_keys, frozen_clock):
    bootstrap(client)
    browser = second_client(app, csrf=False)  # Apple's form_post carries neither the header nor a same-origin Origin; the GETs need none
    r = start_response(browser, "apple", next="/bank")
    url = location(r)
    q = query(url)
    assert url.startswith("/api/auth/fake/apple?state=") and set(q) == {"state", "nonce"} and re.fullmatch(r"[0-9a-f]{32}", q["nonce"])
    assert any(c.startswith("wd_oauth=") and "path=/api/auth" in c and "max-age=600" in c for c in set_cookies(r))
    payload = oauth_state.verify(settings, "apple", q["state"], frozen_clock.now_utc())
    assert payload == {"kind": "login", "next": "/bank", "nonce": q["nonce"], "bh": oauth_state.browser_hash(oauth_cookie(browser))}
    now = frozen_clock.now_utc()
    token = fake_id_token("apple_carol", aud=FAKE_AUDIENCE, nonce=q["nonce"], now=now)
    r = apple_callback(browser, state=q["state"], id_token=token, code="c001", user=json.dumps({"name": {"firstName": "C"}, "email": "c@example.com"}))
    finish_url = location(r)
    assert finish_url.startswith(FINISH) and apple_keys.fetches == 1 and "set-cookie" not in r.headers
    grant = json.loads(rows(settings, "SELECT value FROM kv WHERE key LIKE 'oauth_grant:%'")[0]["value"])
    assert grant == {"provider": "apple", "subject": "apple_carol", "kind": "login", "invite": None, "next": "/bank", "bh": oauth_state.browser_hash(oauth_cookie(browser)), "nonce": q["nonce"]}
    assert count(settings, "users") == 1 and count(settings, "identities") == 0  # nothing written at the callback
    r = finish(browser, finish_url)
    assert location(r) == "/welcome" and "wd_session=" in r.headers["set-cookie"]
    me = browser.get("/api/auth/me").json()
    user = me["user"]
    assert user["providers"] == ["apple"] and user["needs_profile"] is True and user["has_password"] is False and user["email"] is None  # the `user` field is ignored
    identity = rows(settings, "SELECT * FROM identities WHERE user_id = ?", (user["id"],))[0]
    assert (identity["provider"], identity["subject"], identity["verified_at"]) == ("apple", "apple_carol", NOW_ISO)
    assert count(settings, "users", "email IS NOT NULL") == 0
    # the same sub signs in again (existing account, `next` honoured); a nonce reuse across states is refused by the state, not the token
    frozen_clock.advance(minutes=1)
    other = second_client(app, csrf=False)
    url, q2 = start(other, "apple", next="/history")
    token2 = fake_id_token("apple_carol", aud=FAKE_AUDIENCE, nonce=q2["nonce"], now=frozen_clock.now_utc())
    r = finish(other, location(apple_callback(other, state=q2["state"], id_token=token2, code="c002")))
    assert location(r) == "/history" and count(settings, "users") == 2
    assert rows(settings, "SELECT last_login_at FROM identities WHERE subject = 'apple_carol'")[0]["last_login_at"] == "2026-10-14T00:01:00Z"
    assert other.get("/api/auth/me").json()["user"]["id"] == user["id"]


def test_apple_callback_refusals_and_cancellations(client: TestClient, app, settings, apple_keys, frozen_clock, caplog: pytest.LogCaptureFixture):
    bootstrap(client)
    browser = second_client(app, csrf=False)
    _url, q = start(browser, "apple")
    now = frozen_clock.now_utc()
    good = fake_id_token("apple_dan", aud=FAKE_AUDIENCE, nonce=q["nonce"], now=now)
    assert location(apple_callback(browser, state=q["state"], id_token=fake_id_token("apple_dan", aud=FAKE_AUDIENCE, nonce="0" * 32, now=now))) == "/login?error=invalid_identity_token"  # wrong nonce
    assert location(apple_callback(browser, state=q["state"], id_token=fake_id_token("apple_dan", aud=FAKE_AUDIENCE, nonce=q["nonce"], now=now, exp_s=-1))) == "/login?error=invalid_identity_token"  # expired
    assert location(apple_callback(browser, state=q["state"], id_token=fake_id_token("apple_dan", aud="com.other.app", nonce=q["nonce"], now=now))) == "/login?error=invalid_identity_token"  # wrong aud
    header, payload, sig = good.split(".")
    none_header = oauth_state.b64url_encode(b'{"alg":"none","kid":"fake-apple-key-1"}')
    assert location(apple_callback(browser, state=q["state"], id_token=f"{none_header}.{payload}.")) == "/login?error=invalid_identity_token"  # alg none
    assert location(apple_callback(browser, state=q["state"], id_token=f"{header}.{payload}.{sig[:-3]}AAA")) == "/login?error=invalid_identity_token"  # tampered signature
    assert location(apple_callback(browser, state=q["state"], id_token=None)) == "/login?error=invalid_identity_token"  # no token
    assert location(apple_callback(browser, state=None, id_token=good)) == "/login?error=invalid_identity_token"  # no state
    assert location(apple_callback(browser, state=q["state"][:-1], id_token=good)) == "/login?error=invalid_identity_token"  # tampered state
    assert location(apple_callback(browser, state="²².abc.def", id_token=good)) == "/login?error=invalid_identity_token"  # a crafted state: a 302, not a 500
    with caplog.at_level(logging.INFO, logger="wd.routers.auth_oauth"):
        assert location(apple_callback(browser, state=q["state"], id_token=good, error="user_cancelled_authorize")) == "/login"  # cancelled: no error shown
        evil = "invalid_request\nFAKE LOG LINE <script>" + "x" * 100
        assert location(apple_callback(browser, state=q["state"], id_token=good, error=evil)) == "/login?error=provider_error"
    assert location(apple_callback(browser, state="garbage", error="user_cancelled_authorize")) == "/login"
    # the attacker-controlled `error` value never reaches the log raw: the cancel is a closed word, anything else a short sanitised excerpt
    assert "FAKE LOG LINE" not in caplog.text and "<script>" not in caplog.text and "\nFAKE" not in caplog.text
    cancelled = [r for r in caplog.records if getattr(r, "event", None) == "apple_cancelled"]
    other = [r for r in caplog.records if getattr(r, "event", None) == "apple_error"]
    assert len(cancelled) == 1 and cancelled[0].cancelled is True and "cancelled" in cancelled[0].getMessage()
    assert len(other) == 1 and other[0].cancelled is False and "(invalid_request_FAKE_LOG_LINE__s)" in other[0].getMessage() and "xxxx" not in other[0].getMessage()
    assert count(settings, "users") == 1 and count(settings, "identities") == 0
    # a QQ state is not an Apple state (the provider name is inside the signed string)
    qq_state = oauth_state.sign(settings, "qq", {"kind": "login", "next": "/", "nonce": q["nonce"], "bh": "b" * 64}, now)
    assert location(apple_callback(browser, state=qq_state, id_token=good)) == "/login?error=invalid_identity_token"
    # the good token finally signs in; replaying the same state + token afterwards still passes the state (10 min) but creates nothing new
    assert location(finish(browser, location(apple_callback(browser, state=q["state"], id_token=good)))) == "/welcome"
    assert count(settings, "users") == 2
    # a bind through Apple: the form_post may come from any origin, the FINISH runs in alice's browser
    alice_client = second_client(app)
    alice = register(alice_client, "alice")
    _url, bq = start(alice_client, "apple", kind="bind")
    assert location(apple_callback(browser, state=bq["state"], id_token=good, error="user_cancelled_authorize")) == "/settings"
    token = fake_id_token("apple_alice", aud=FAKE_AUDIENCE, nonce=bq["nonce"], now=now)
    r = finish(alice_client, location(apple_callback(browser, state=bq["state"], id_token=token)))
    assert location(r) == "/settings?bound=apple" and "wd_session=" not in r.headers.get("set-cookie", "")
    assert alice_client.get("/api/auth/me").json()["user"]["providers"] == ["apple"] and sessions_of(settings, alice["id"]) == 1
    assert rows(settings, "SELECT subject FROM identities WHERE user_id = ?", (alice["id"],)) == [{"subject": "apple_alice"}]


def test_csrf_rule_exempts_only_the_apple_callback(client: TestClient, app, apple_keys):
    bootstrap(client)
    raw = second_client(app, csrf=False)
    r = raw.post("/api/auth/apple/callback", data={"state": "x", "id_token": "y"}, headers={"Origin": "https://appleid.apple.com"}, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/login?error=invalid_identity_token"  # through the middleware, refused by the endpoint
    assert raw.post("/api/auth/oauth/finish", follow_redirects=False).status_code == 403 and error_code(raw.post("/api/auth/oauth/finish")) == "csrf_rejected"
    assert raw.post("/api/auth/qq/callback", follow_redirects=False).status_code == 403
    assert raw.post("/api/auth/apple/start", headers={"Origin": "https://appleid.apple.com"}).status_code == 403
    assert raw.get("/api/auth/oauth/finish", follow_redirects=False).status_code == 302  # GETs never need the header


# ------------------------------------------------------------------------------------- dark: providers off
def test_provider_unconfigured_when_the_providers_are_off(client: TestClient, app, settings):
    bootstrap(client)
    assert (app.state.qq, app.state.apple) == (None, None)
    for provider in ("qq", "apple"):
        r = client.get(f"/api/auth/{provider}/start", follow_redirects=False)
        assert r.status_code == 409 and error_code(r) == "provider_unconfigured" and not set_cookies(r), provider
    state = oauth_state.sign(settings, "qq", {"kind": "login", "next": "/", "bh": "b" * 64}, NOW)
    assert location(qq_callback(client, state, "qq-code-x")) == "/login?error=provider_unconfigured"
    apple_state = oauth_state.sign(settings, "apple", {"kind": "bind", "uid": 1, "next": "/", "nonce": "a" * 32, "bh": "b" * 64}, NOW)
    assert location(apple_callback(second_client(app, csrf=False), state=apple_state, id_token="x.y.z")) == "/settings?error=provider_unconfigured"
    health = client.get("/api/health").json()
    assert (health["wechat_enabled"], health["qq_enabled"], health["apple_enabled"]) == (False, False, False)
    server = client.get("/api/auth/me").json()["server"]
    assert (server["wechat_enabled"], server["qq_enabled"], server["apple_enabled"]) == (False, False, False)
    assert client.get("/api/auth/fake/qq", params={"state": "x"}).status_code == 404  # the consent pages exist only under the flag
    assert client.get("/api/auth/fake/apple", params={"state": "x", "nonce": "y"}).status_code == 404


def test_startup_warns_when_a_callback_url_is_set_without_a_public_url(settings, frozen_clock, caplog: pytest.LogCaptureFixture):
    """Behind the relay the callback request's origin is the relay's domain; without WD_PUBLIC_URL endpoint 122's URL would be built from
    it and the login would silently die there — one warning at startup, none once WD_PUBLIC_URL is set."""
    cfg = replace(settings, apple_client_id="com.worddance.web", apple_callback_url="https://relay.example.cn/api/auth/apple/callback", public_url="")
    assert cfg.apple_configured and not cfg.public_url
    with caplog.at_level(logging.WARNING, logger="wd.main"):
        with TestClient(create_app(cfg, clock=frozen_clock, configure_logs=False), base_url="http://testserver"):
            pass
    warnings = [r for r in caplog.records if getattr(r, "event", None) == "oauth_public_url_missing"]
    assert len(warnings) == 1 and warnings[0].levelno == logging.WARNING
    assert "WD_APPLE_CALLBACK_URL" in warnings[0].getMessage() and "WD_PUBLIC_URL" in warnings[0].getMessage() and "relay.example.cn" not in warnings[0].getMessage()
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="wd.main"):
        with TestClient(create_app(replace(cfg, public_url="https://words.example.com"), clock=frozen_clock, configure_logs=False), base_url="http://testserver"):
            pass
    assert not [r for r in caplog.records if getattr(r, "event", None) == "oauth_public_url_missing"]


# ------------------------------------------------------------------------------- the dev fakes (WD_AUTH_FAKE_PROVIDERS=1)
def test_fake_consent_pages_drive_both_flows_end_to_end(settings, frozen_clock):
    app = create_app(replace(settings, dev=True, auth_fake_providers=True), clock=frozen_clock, configure_logs=False)
    assert isinstance(app.state.qq, FakeQQClient) and isinstance(app.state.apple, FakeAppleKeys)
    with TestClient(app, base_url="http://testserver") as c:
        c.headers["X-WD-Request"] = "1"
        bootstrap(c)
        health = c.get("/api/health").json()
        assert (health["wechat_enabled"], health["qq_enabled"], health["apple_enabled"]) == (True, True, True)
        # QQ: start → the consent page → 同意 → callback → finish → session, all in ONE browser (the wd_oauth cookie travels with it)
        learner = second_client(app)
        consent_url, q = start(learner, "qq", next="/bank")
        assert oauth_cookie(learner)
        page = learner.get(consent_url)
        assert page.status_code == 200 and page.headers["content-type"].startswith("text/html") and "假 QQ 登录" in page.text and "<script" not in page.text
        hrefs = [html.unescape(h) for h in re.findall(r"href='([^']+)'", page.text)]  # the attribute values are HTML-escaped (&amp;)
        accept = next(h for h in hrefs if "code=qq-code-" in h)
        cancel = next(h for h in hrefs if "usercancel=1" in h)
        assert accept.startswith("/api/auth/qq/callback?") and query(accept)["state"] == q["state"] and query(cancel)["state"] == q["state"]
        assert location(learner.get(cancel, follow_redirects=False)) == "/login"
        r = finish(learner, location(learner.get(accept, follow_redirects=False)))
        assert location(r) == "/welcome" and "wd_session=" in r.headers["set-cookie"] and oauth_cookie(learner) is None
        user = learner.get("/api/auth/me").json()["user"]
        assert user["providers"] == ["qq"] and PLACEHOLDER_RE.match(user["username"])
        assert c.get("/api/auth/fake/qq").status_code == 400  # the state is required
        # Apple: start → the consent page (a form, no script) → 同意 posts the minted id_token → callback → finish → session
        browser = second_client(app, csrf=False)
        consent_url, aq = start(browser, "apple")
        page = browser.get(consent_url)
        assert page.status_code == 200 and "假 Apple 登录" in page.text and "<script" not in page.text
        assert "action='/api/auth/apple/callback'" in page.text and "name='error' value='user_cancelled_authorize'" in page.text
        id_token = html.unescape(re.search(r"name='id_token' value='([^']+)'", page.text).group(1))
        assert id_token.count(".") == 2 and html.unescape(re.search(r"name='state' value='([^']+)'", page.text).group(1)) == aq["state"]
        r = apple_callback(browser, state=aq["state"], id_token=id_token, code="fake-code-1")
        r = finish(browser, location(r))
        assert location(r) == "/welcome"
        user = browser.get("/api/auth/me").json()["user"]
        assert user["providers"] == ["apple"]
        assert rows(settings, "SELECT subject FROM identities WHERE user_id = ?", (user["id"],))[0]["subject"].startswith("apple_")
        assert c.get("/api/auth/fake/apple", params={"state": "x"}).status_code == 400  # the nonce is required
        assert count(settings, "users") == 3
