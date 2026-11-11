"""Endpoints 79–84, 90, 91 (API.md §3.1): the captcha, code sends (consent, normalisation, channel availability, the captcha gate,
the per-target / per-IP / per-prefix throttles, the site-wide SMS caps, provider failures), login-or-register in one transaction
(placeholder account, registration modes, setup_required, admins, disabled accounts), the stale-phone challenge (password, e-mail
code, dispute) and forgot + reset password."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import replace
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from wd import captcha, db, security
from wd.delivery.mailer import RecordingMailer
from wd.delivery.sms import RecordingSmsSender, SmsError
from wd.main import create_app

PW = "Correct-Horse-7"
NOW_ISO = "2026-10-14T00:00:00Z"
PHONE = "13800138000"
E164 = "+8613800138000"
OTHER = "13900139000"
OTHER_E164 = "+8613900139000"
PLACEHOLDER_RE = re.compile(r"^u_[a-z2-7]{8}$")


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


def bootstrap(client: TestClient, username: str = "root", **extra) -> dict:
    """The first account is a username + password registration (admin): a code sign-in refuses an empty site (setup_required)."""
    r = client.post("/api/auth/register", json={"username": username, "password": PW, **extra})
    assert r.status_code == 201, r.text
    return r.json()["user"]


def error_code(r) -> str:
    return r.json()["error"]["code"]


def details(r) -> dict:
    return r.json()["error"].get("details") or {}


def send(client: TestClient, target: str = PHONE, *, channel: str = "phone", purpose: str = "login", consent: bool | None = True, **extra):
    body: dict = {"channel": channel, "target": target, "purpose": purpose, **extra}
    if consent is not None:
        body["consent"] = consent
    return client.post("/api/auth/code", json=body)


def code_login(client: TestClient, target: str, code: str, *, channel: str = "phone", **extra):
    return client.post("/api/auth/code/login", json={"channel": channel, "target": target, "code": code, **extra})


def sign_in(client: TestClient, sms: RecordingSmsSender, target: str = PHONE, **extra) -> dict:
    """Send + login through the phone channel; returns the CodeLoginResponse body (201 or 200)."""
    assert send(client, target).status_code == 202
    r = code_login(client, target, sms.sent[-1].code, **extra)
    assert r.status_code in (200, 201), r.text
    return r.json()


def mail_code(mailer: RecordingMailer) -> str:
    return re.search(r"(\d{6})", mailer.sent[-1].text).group(1)


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


def captcha_answer(settings, challenge: dict) -> str:
    """The four digits behind a challenge: the signature is HMAC(id:exp:answer), so a test recovers them by trying all 10 000."""
    return next(a for a in (f"{i:04d}" for i in range(10_000)) if captcha.signature(settings.secret_key, challenge["id"], challenge["exp"], a) == challenge["sig"])


# ------------------------------------------------------------------------------------- send + login (80, 81)
def test_send_and_login_creates_a_placeholder_account_then_logs_it_in(client: TestClient, app, settings, sms, frozen_clock):
    bootstrap(client)
    learner = second_client(app)
    r = send(learner)
    assert r.status_code == 202 and r.json() == {"sent": True, "expires_in_s": 600}
    assert len(sms.sent) == 1 and sms.sent[0].to == E164 and sms.sent[0].template == "100001" and sms.sent[0].minutes == 10
    code = sms.sent[0].code
    assert re.fullmatch(r"\d{6}", code)
    row = rows(settings, "SELECT * FROM login_codes")[0]
    assert (row["channel"], row["target"], row["purpose"], row["user_id"], row["ip"], row["expires_at"]) == ("phone", E164, "login", None, "testclient", "2026-10-14T00:10:00Z")
    assert row["code_hash"] == security.login_code_hash(settings.secret_key, code, "phone", E164, "login") and code not in str(row)

    r = code_login(learner, " 138 0013-8000 ", code)
    assert r.status_code == 201, r.text
    body = r.json()
    user = body["user"]
    assert body["created"] is True and body["challenge"] is None and body["settings"]["timezone"] == "Asia/Shanghai"
    assert PLACEHOLDER_RE.match(user["username"]) and user["display_name"] == user["username"]
    assert user["has_password"] is False and user["needs_profile"] is True and user["phone_masked"] == "138****8000" and user["age_band"] is None
    assert (user["account_kind"], user["is_child"], user["needs_profile_prompt"]) == ("learner", False, False)  # slice 1-B: a placeholder account goes through 89, never the 「补充信息」 prompt
    assert user["email"] is None and user["email_verified"] is False and user["role"] == "user" and user["onboarding_state"] == "pending"
    cookie = r.headers["set-cookie"].lower()
    assert "wd_session=" in cookie and "httponly" in cookie
    identity = rows(settings, "SELECT * FROM identities")[0]
    assert (identity["user_id"], identity["provider"], identity["subject"], identity["verified_at"], identity["last_login_at"], identity["disputed_at"]) == (user["id"], "phone", E164, NOW_ISO, NOW_ISO, None)
    account = rows(settings, "SELECT * FROM users WHERE id = ?", (user["id"],))[0]
    assert account["password_set_at"] is None and account["last_login_at"] == NOW_ISO and account["account_kind"] == "learner"
    assert not security.verify_password("", account["password_hash"]) and account["password_hash"].startswith("$2b$")
    assert count(settings, "login_codes", "used_at IS NULL") == 0  # consumed with the account write
    assert count(settings, "auth_throttle", "key = 'register:ip:testclient' AND count = 1") == 1  # only the bootstrap counted
    assert count(settings, "auth_throttle", "key LIKE 'login:%'") == 0  # never login:ip / the lockout
    me = learner.get("/api/auth/me")
    assert me.status_code == 200 and me.json()["user"]["needs_profile"] is True and me.json()["server"]["sms_enabled"] is True
    r = code_login(learner, PHONE, code)
    assert r.status_code == 400 and error_code(r) == "invalid_code" and details(r) == {"attempts_left": 0}  # single use

    # the second sign-in is a login (200, created false), last_login_at refreshed on the identity and the user
    frozen_clock.advance(minutes=1)
    body = sign_in(learner, sms)
    assert body["created"] is False and body["user"]["id"] == user["id"] and body["user"]["needs_profile"] is True
    assert rows(settings, "SELECT last_login_at FROM identities")[0]["last_login_at"] == "2026-10-14T00:01:00Z"
    assert rows(settings, "SELECT last_login_at FROM users WHERE id = ?", (user["id"],))[0]["last_login_at"] == "2026-10-14T00:01:00Z"
    assert count(settings, "users") == 2 and count(settings, "sessions", "user_id = ?", (user["id"],)) == 2
    # a password login against the code-created account is a plain 401 (unusable password), without a lockout key leak of its number
    assert learner.post("/api/auth/login", json={"username": PHONE, "password": PW}).status_code == 401


def test_email_channel_creates_a_verified_email_account(client: TestClient, app, settings, mailer, frozen_clock):
    bootstrap(client)
    learner = second_client(app)
    r = send(learner, " Alice@Example.com ", channel="email")
    assert r.status_code == 202 and r.json() == {"sent": True, "expires_in_s": 600}
    assert mailer.sent[0].to == "alice@example.com" and "登录验证码" in mailer.sent[0].subject and "10 分钟" in mailer.sent[0].text
    code = mail_code(mailer)
    assert rows(settings, "SELECT target, purpose FROM login_codes")[0] == {"target": "alice@example.com", "purpose": "login"}
    r = code_login(learner, "alice@example.com", code, channel="email")
    assert r.status_code == 201, r.text
    user = r.json()["user"]
    assert user["email"] == "alice@example.com" and user["email_verified"] is True and user["phone_masked"] is None and user["has_password"] is False
    assert count(settings, "identities") == 0
    account = rows(settings, "SELECT email_verified_at FROM users WHERE id = ?", (user["id"],))[0]
    assert account["email_verified_at"] == NOW_ISO
    frozen_clock.advance(minutes=1)
    assert send(learner, "ALICE@example.com", channel="email").status_code == 202
    r = code_login(learner, "alice@example.com", mail_code(mailer), channel="email")
    assert r.status_code == 200 and r.json()["created"] is False and r.json()["user"]["id"] == user["id"]
    # the same address held UNVERIFIED by a password account is released to its verifier
    frozen_clock.advance(minutes=1)
    holder = second_client(app)
    holder.post("/api/auth/register", json={"username": "holder", "password": PW, "email": "bob@example.com"})
    assert send(learner, "bob@example.com", channel="email").status_code == 202
    r = code_login(second_client(app), "bob@example.com", mail_code(mailer), channel="email")
    assert r.status_code == 201 and r.json()["user"]["email"] == "bob@example.com" and r.json()["user"]["email_verified"] is True
    assert rows(settings, "SELECT email FROM users WHERE username = 'holder'")[0]["email"] is None


def test_send_validation_and_channel_availability(client: TestClient, app, settings, sms, mailer):
    bootstrap(client)
    learner = second_client(app)
    for consent in (None, False):
        r = send(learner, consent=consent)
        assert r.status_code == 400 and error_code(r) == "consent_required", consent
    for bad in ("12345", "+15551234567", "1380013800", "abc"):
        r = send(learner, bad)
        assert r.status_code == 400 and error_code(r) == "invalid_phone", bad
    r = send(learner, "nope", channel="email")
    assert r.status_code == 400 and error_code(r) == "validation_error"
    r = learner.post("/api/auth/code", json={"channel": "fax", "target": PHONE, "purpose": "login", "consent": True})
    assert r.status_code == 400 and error_code(r) == "validation_error"
    r = learner.post("/api/auth/code", json={"channel": "phone", "target": PHONE, "purpose": "bind_phone", "consent": True})
    assert r.status_code == 400 and error_code(r) == "validation_error"  # 80 knows login / reset_password only
    assert send(learner, purpose="reset_password", consent=None).status_code == 202  # no consent needed; unknown target → still 202
    assert sms.sent == [] and count(settings, "login_codes") == 0  # … and nothing issued for a target without an account
    app.state.sms = None
    r = send(learner)
    assert r.status_code == 409 and error_code(r) == "sms_unconfigured"
    assert client.get("/api/health").json()["sms_enabled"] is False and client.get("/api/auth/me").json()["server"]["sms_enabled"] is False
    app.state.sms = sms
    assert client.get("/api/health").json()["sms_enabled"] is True and client.get("/api/auth/me").json()["server"]["sms_enabled"] is True
    app.state.mailer = None
    r = send(learner, "a@example.com", channel="email")
    assert r.status_code == 409 and error_code(r) == "smtp_unconfigured"


def test_setup_required_while_no_user_exists(client: TestClient, settings, sms):
    assert client.get("/api/health").json()["needs_setup"] is True
    r = send(client)
    assert r.status_code == 403 and error_code(r) == "setup_required"
    assert sms.sent == []
    c = db.connect(settings.db_path)
    try:
        code = security.issue_login_code(c, channel="phone", target=E164, purpose="login", user_id=None, ip=None, secret_key=settings.secret_key, now=datetime(2026, 10, 14, tzinfo=timezone.utc))
    finally:
        c.close()
    r = code_login(client, PHONE, code)
    assert r.status_code == 403 and error_code(r) == "setup_required"
    assert count(settings, "users") == 0 and count(settings, "login_codes", "used_at IS NULL") == 1  # nothing created, the code still live


def test_captcha_gate_when_enabled(settings, frozen_clock):
    app = create_app(replace(settings, captcha="on"), clock=frozen_clock, configure_logs=False)
    sms = RecordingSmsSender()
    app.state.sms = sms
    with TestClient(app, base_url="http://testserver") as admin:
        admin.headers["X-WD-Request"] = "1"
        bootstrap(admin)
        learner = second_client(app)
        r = send(learner)
        assert r.status_code == 400 and error_code(r) == "captcha_required"
        r = learner.get("/api/auth/captcha")
        assert r.status_code == 200, r.text
        challenge = r.json()
        assert set(challenge) == {"id", "image", "exp", "sig", "expires_in_s"} and challenge["expires_in_s"] == 120
        assert challenge["image"].startswith("data:image/png;base64,") and challenge["exp"] == int(frozen_clock.now_utc().timestamp()) + 120
        token = {k: challenge[k] for k in ("id", "exp", "sig")}
        r = send(learner, captcha={**token, "answer": "0000" if captcha_answer(settings, challenge) != "0000" else "0001"})
        assert r.status_code == 400 and error_code(r) == "invalid_captcha"
        r = send(learner, captcha={**token, "answer": captcha_answer(settings, challenge)})
        assert r.status_code == 400 and error_code(r) == "invalid_captcha"  # a wrong answer burnt the challenge
        challenge = learner.get("/api/auth/captcha").json()
        good = {**{k: challenge[k] for k in ("id", "exp", "sig")}, "answer": captcha_answer(settings, challenge)}
        assert send(learner, captcha=good).status_code == 202 and len(sms.sent) == 1
        frozen_clock.advance(minutes=1)
        r = send(learner, captcha=good)
        assert r.status_code == 400 and error_code(r) == "invalid_captcha"  # single use
        # a logged-in user needs no captcha; forgot-password obeys the same gate
        assert send(admin, OTHER).status_code == 202
        r = learner.post("/api/auth/password/forgot", json={"identifier": "root"})
        assert r.status_code == 400 and error_code(r) == "captcha_required"
        r = learner.post("/api/auth/password/forgot", json={"identifier": "nobody", "captcha": good})
        assert r.status_code == 400 and error_code(r) == "invalid_captcha"  # the token above was spent by the send
        challenge = learner.get("/api/auth/captcha").json()
        good = {**{k: challenge[k] for k in ("id", "exp", "sig")}, "answer": captcha_answer(settings, challenge)}
        assert learner.post("/api/auth/password/forgot", json={"identifier": "nobody", "captcha": good}).status_code == 202
        # 79 is a throttled GET: 60 per hour per IP (three challenges were fetched above)
        served = 3
        while served < 100 and learner.get("/api/auth/captcha").status_code == 200:
            served += 1
        assert served == 60
        r = learner.get("/api/auth/captcha")
        assert r.status_code == 429 and error_code(r) == "rate_limited" and r.headers["Retry-After"] == "3540"  # the window opened a frozen minute ago


def test_send_throttles_per_target_ip_and_prefix(client: TestClient, app, settings, sms, frozen_clock):
    bootstrap(client)
    learner = second_client(app)
    assert send(learner).status_code == 202
    r = send(learner)
    assert r.status_code == 429 and error_code(r) == "rate_limited" and r.headers["Retry-After"] == "60"  # 1/min per target
    assert send(learner, "+86 138-0013-8000").status_code == 429  # the same number in another spelling
    for _ in range(4):
        frozen_clock.advance(minutes=1)
        assert send(learner).status_code == 202
    frozen_clock.advance(minutes=1)
    r = send(learner)
    assert r.status_code == 429 and details(r)["retry_after_s"] == 3600 - 5 * 60  # 5/h per target
    assert len(sms.sent) == 5
    # 5/h per 7-digit prefix (号段): the five sends above already spent 1380013 — a neighbour in the same prefix is refused at once
    r = send(learner, "13800138001")
    assert r.status_code == 429 and count(settings, "auth_throttle", "key = 'code_send:prefix:1380013' AND count = 5") == 1
    assert sum(1 for n in range(5) if send(learner, f"1390013900{n}").status_code == 202) == 5  # five numbers of a fresh prefix …
    r = send(learner, "13900139005")
    assert r.status_code == 429 and count(settings, "auth_throttle", "key = 'code_send:prefix:1390013' AND count = 5") == 1  # … are its cap
    assert send(learner, "13700137000").status_code == 202  # another prefix
    assert count(settings, "auth_throttle", "key = 'code_send:ip:testclient' AND count = 13") == 1  # every attempt past the target windows counts for the IP (the two prefix refusals included), the hour-refused one does not
    # WD_CODE_IP_HOURLY per client IP
    small = create_app(replace(settings, code_ip_hourly=2), clock=frozen_clock, configure_logs=False)
    small.state.sms = RecordingSmsSender()
    with TestClient(small, base_url="http://testserver") as c:
        c.headers["X-WD-Request"] = "1"
        frozen_clock.advance(hours=2)
        assert c.post("/api/auth/code", json={"channel": "phone", "target": "13700137000", "purpose": "login", "consent": True}).status_code == 202
        assert c.post("/api/auth/code", json={"channel": "phone", "target": "13600136000", "purpose": "login", "consent": True}).status_code == 202
        r = c.post("/api/auth/code", json={"channel": "phone", "target": "13500135000", "purpose": "login", "consent": True})
        assert r.status_code == 429 and error_code(r) == "rate_limited"


def test_sms_budget_hour_cap_day_cap_and_the_registration_stop(settings, frozen_clock):
    hourly = create_app(replace(settings, sms_hourly_cap=1), clock=frozen_clock, configure_logs=False)
    hourly.state.sms = RecordingSmsSender()
    with TestClient(hourly, base_url="http://testserver") as c:
        c.headers["X-WD-Request"] = "1"
        bootstrap(c)
        assert send(c, PHONE).status_code == 202
        r = send(c, OTHER)
        assert r.status_code == 503 and error_code(r) == "sms_budget_exhausted" and details(r) == {"retry_after_s": 3600}  # which cap refused is logged, never returned
        assert len(hourly.state.sms.sent) == 1 and count(settings, "login_codes") == 1  # the refused send wrote no row
        c.cookies.clear()
        c.post("/api/auth/login", json={"username": "root", "password": PW})
        sms = c.get("/api/admin/overview").json()["sms"]
        assert (sms["sent_hour"], sms["hourly_cap"], sms["sent_today"]) == (1, 1, 1)
    # the registration stop: a `login` send to a number without an account stops at 70 % of the day cap
    daily = create_app(replace(settings, sms_daily_cap=10, sms_hourly_cap=100, code_ip_hourly=100), clock=frozen_clock, configure_logs=False)
    sender = RecordingSmsSender()
    daily.state.sms = sender
    frozen_clock.advance(days=1)
    with TestClient(daily, base_url="http://testserver") as admin:
        admin.headers["X-WD-Request"] = "1"
        assert admin.post("/api/auth/login", json={"username": "root", "password": PW}).status_code == 200  # the same database: root is the admin
        learner = second_client(daily)
        sign_in(learner, sender, PHONE)  # send 1 + an account with a live identity
        for i in range(6):  # sends 2–7, each a new number of its own prefix
            assert send(learner, f"139{i:02d}013900").status_code == 202
        r = send(learner, "13700137000")
        assert r.status_code == 503 and error_code(r) == "sms_budget_exhausted" and set(details(r)) == {"retry_after_s"}  # no `scope`: it would spell out "no account"
        frozen_clock.advance(minutes=1)
        assert send(learner, PHONE).status_code == 202  # an existing account keeps the last 30 % (send 8)
        frozen_clock.advance(minutes=1)
        assert send(learner, PHONE, purpose="reset_password", consent=None).status_code == 202  # a reset to an account's number is not a new account either (send 9)
        overview = admin.get("/api/admin/overview").json()["sms"]
        assert (overview["sent_today"], overview["daily_cap"], overview["registration_open"]) == (9, 10, False)
        kinds = [e["kind"] for e in rows(settings, "SELECT kind FROM system_events WHERE kind LIKE 'sms_budget_%' ORDER BY id")]
        assert kinds == ["sms_budget_50", "sms_budget_80"]  # once per day each, at the crossing
        frozen_clock.advance(minutes=1)
        assert send(learner, PHONE).status_code == 202  # 10 / 10
        frozen_clock.advance(minutes=1)
        r = send(learner, PHONE)
        assert r.status_code == 503 and set(details(r)) == {"retry_after_s"} and details(r)["retry_after_s"] > 0
        assert [e["kind"] for e in rows(settings, "SELECT kind FROM system_events WHERE kind LIKE 'sms_budget_%' ORDER BY id")] == ["sms_budget_50", "sms_budget_80", "sms_budget_100"]
        # the reset flows never tell a registered number apart: at the day cap 80 reset_password and 90 are still 202, no row written
        before = count(settings, "login_codes")
        frozen_clock.advance(hours=1)  # a fresh per-target hour window; the WD_TZ day (and its cap) is the same
        assert send(learner, PHONE, purpose="reset_password", consent=None).status_code == 202
        frozen_clock.advance(minutes=1)
        assert learner.post("/api/auth/password/forgot", json={"identifier": PHONE}).status_code == 202
        assert count(settings, "login_codes") == before and len(sender.sent) == 10


def test_provider_failures_void_the_code(client: TestClient, app, settings, sms, mailer, frozen_clock):
    bootstrap(client)
    learner = second_client(app)
    sms.fail_with = SmsError("temporary", "boom")
    r = send(learner)
    assert r.status_code == 503 and error_code(r) == "sms_send_failed"
    assert sms.sent == [] and count(settings, "login_codes", "used_at IS NULL") == 0 and count(settings, "login_codes") == 1  # issued, then voided
    frozen_clock.advance(minutes=1)
    sms.fail_with = SmsError("rate_limited", "busy", retry_after_s=30, code="FREQUENCY_FAIL")
    r = send(learner)
    assert r.status_code == 429 and error_code(r) == "rate_limited" and r.headers["Retry-After"] == "30" and details(r)["retry_after_s"] == 30
    frozen_clock.advance(minutes=1)
    sms.fail_with = SmsError("invalid_target", "illegal")
    r = send(learner)
    assert r.status_code == 400 and error_code(r) == "invalid_phone"
    assert count(settings, "login_codes", "used_at IS NULL") == 0
    frozen_clock.advance(minutes=1)
    sms.fail_with = None
    assert send(learner).status_code == 202 and len(sms.sent) == 1
    mailer.fail_with = "boom"
    r = send(learner, "a@example.com", channel="email")
    assert r.status_code == 503 and error_code(r) == "email_send_failed"
    assert count(settings, "login_codes", "channel = 'email' AND used_at IS NULL") == 0
    assert count(settings, "kv", "key LIKE 'sms.sent.%' AND CAST(value AS INTEGER) = 4") == 2  # every send request counted, failed ones included


def test_provider_failures_on_the_reset_flows_are_still_202(client: TestClient, app, settings, sms, mailer, frozen_clock):
    """API.md 80 / 90: a `reset_password` send answers 202 for a registered target whatever the provider says — the 429 / 400 / 503
    of a `login` send would otherwise tell a registered number from an unknown one; the code is voided, nothing goes out."""
    bootstrap(client)
    learner = second_client(app)
    sign_in(learner, sms)  # PHONE belongs to an account now
    learner.cookies.clear()
    emailer = second_client(app)
    assert send(emailer, "c@example.com", channel="email").status_code == 202
    assert code_login(emailer, "c@example.com", mail_code(mailer), channel="email").status_code == 201  # a verified e-mail account
    emailer.cookies.clear()
    for failure in (SmsError("temporary", "boom"), SmsError("rate_limited", "busy", retry_after_s=30, code="FREQUENCY_FAIL"), SmsError("invalid_target", "illegal"), SmsError("config", "FUNCTION_NOT_OPENED")):
        sms.fail_with = failure
        sent = len(sms.sent)
        frozen_clock.advance(hours=1)  # two requests per kind: a fresh per-target hour window each (the 10/day window takes nine)
        r = send(learner, PHONE, purpose="reset_password", consent=None)
        assert r.status_code == 202 and r.json() == {"sent": True, "expires_in_s": 600}, failure.kind
        frozen_clock.advance(minutes=1)
        r = learner.post("/api/auth/password/forgot", json={"identifier": PHONE})
        assert r.status_code == 202 and r.json() == {"sent": True, "expires_in_s": 600}, failure.kind
        assert len(sms.sent) == sent and count(settings, "login_codes", "purpose = 'reset_password' AND used_at IS NULL") == 0  # issued, voided, nothing delivered
    sms.fail_with = None
    mailer.fail_with = "boom"
    mailed = len(mailer.sent)
    frozen_clock.advance(minutes=1)
    assert send(emailer, "c@example.com", channel="email", purpose="reset_password", consent=None).status_code == 202
    frozen_clock.advance(minutes=1)
    assert emailer.post("/api/auth/password/forgot", json={"identifier": "c@example.com"}).status_code == 202
    assert len(mailer.sent) == mailed and count(settings, "login_codes", "purpose = 'reset_password' AND used_at IS NULL") == 0
    # a `login` send keeps reporting the provider (the registration stop of D7 is an accepted oracle; a reset is not)
    sms.fail_with = SmsError("temporary", "boom")
    frozen_clock.advance(minutes=1)
    assert send(learner, PHONE).status_code == 503


def test_email_send_failure_logs_the_failure_class_only(client: TestClient, app, settings, mailer, caplog):
    """The mailer's message may echo the recipient (plain or percent-encoded) and the body with the code — a DirectMail gateway does on
    SignatureDoesNotMatch — so the `email_code_failed` line carries the failure class alone."""
    bootstrap(client)
    learner = second_client(app)
    mailer.fail_with = "DirectMail send failed: SignatureDoesNotMatch (config): ToAddress%3Dbob%2540example.com%26TextBody%3D%25E9%25AA%258C%25E8%25AF%2581%25E7%25A0%2581%2520123456"
    with caplog.at_level(logging.INFO, logger="wd.routers.auth_codes"):
        r = send(learner, "bob@example.com", channel="email")
    assert r.status_code == 503 and error_code(r) == "email_send_failed"
    failed = [rec for rec in caplog.records if getattr(rec, "event", None) == "email_code_failed"]
    assert len(failed) == 1 and failed[0].getMessage() == "e-mail code not sent: MailerError"
    joined = " ".join(rec.getMessage() for rec in caplog.records)
    assert "bob" not in joined and "123456" not in joined and "%2540" not in joined and "ToAddress" not in joined


def test_wrong_codes_count_and_burn(client: TestClient, app, settings, sms):
    bootstrap(client)
    learner = second_client(app)
    assert send(learner).status_code == 202
    code = sms.sent[-1].code
    wrong = "000000" if code != "000000" else "111111"
    for left in (4, 3, 2, 1, 0):
        r = code_login(learner, PHONE, wrong)
        assert r.status_code == 400 and error_code(r) == "invalid_code" and details(r) == {"attempts_left": left}
    r = code_login(learner, PHONE, code)
    assert r.status_code == 400 and details(r) == {"attempts_left": 0}  # burnt
    assert count(settings, "users") == 1
    r = code_login(learner, PHONE, "12345")
    assert r.status_code == 400 and error_code(r) == "validation_error"


def test_code_check_throttles_count_failures_per_target_and_ip(client: TestClient, app, settings, sms, frozen_clock):
    """API.md §1: code checks count 20/h per target and 60/h per IP (81, 83, 91) — failed checks only, read before the code is looked
    at: a correct code spends nothing, the 21st failed check on a number is refused even with the right code, 83 and 91 draw on the
    same IP window."""
    bootstrap(client)
    learner = second_client(app)
    sign_in(learner, sms, OTHER)  # a correct code spends no code-check window
    assert count(settings, "auth_throttle", "key LIKE 'code_check:%'") == 0
    learner.cookies.clear()
    for _ in range(4):  # 4 × (send → 5 wrong guesses burn the code) = 20 failed checks on one number
        assert send(learner).status_code == 202
        code = sms.sent[-1].code
        wrong = "000000" if code != "000000" else "111111"
        for left in (4, 3, 2, 1, 0):
            r = code_login(learner, PHONE, wrong)
            assert r.status_code == 400 and error_code(r) == "invalid_code" and details(r) == {"attempts_left": left}
        frozen_clock.advance(minutes=1)
    assert send(learner).status_code == 202  # the 5th code of the hour
    code = sms.sent[-1].code
    r = code_login(learner, PHONE, code)  # the 21st check, with the CORRECT code
    assert r.status_code == 429 and error_code(r) == "rate_limited" and r.headers["Retry-After"] == str(3600 - 4 * 60)
    assert rows(settings, "SELECT attempts, used_at FROM login_codes WHERE target = ? AND used_at IS NULL", (E164,)) == [{"attempts": 0, "used_at": None}]  # refused before verify_login_code
    assert count(settings, "users") == 2
    assert code_login(learner, "138 0013 8000", code).status_code == 429  # the normalised target is the key
    assert rows(settings, "SELECT key, count FROM auth_throttle WHERE key LIKE 'code_check:%' ORDER BY key") == [
        {"key": "code_check:ip:testclient", "count": 20},  # the two refusals were not counted (nor was the correct login)
        {"key": "code_check:target:+8613800138000", "count": 20},
    ]
    served = 20  # fill the IP window with failed checks on code-less numbers (3 targets, each stays under 20)
    while served < 100:
        r = code_login(learner, f"1390013900{served % 3}", "000000")
        if r.status_code == 429:
            break
        assert r.status_code == 400 and details(r) == {"attempts_left": 0}
        served += 1
    assert served == 60 and error_code(r) == "rate_limited" and details(r) == {"retry_after_s": 3600 - 4 * 60}
    assert code_login(learner, "13700137000", "000000").status_code == 429  # whatever the target
    assert count(settings, "auth_throttle", "key = 'code_check:ip:testclient' AND count = 60") == 1
    # 83 and 91 draw on the same IP window: a fresh hour, 59 failed resets + 1 dead token, then 81 is the 61st
    frozen_clock.advance(hours=1)
    for _ in range(59):
        r = learner.post("/api/auth/password/reset", json={"identifier": "nobody", "code": "000000", "new_password": "New-Pass-Word-9"})
        assert r.status_code == 400 and error_code(r) == "invalid_code"
    r = learner.post("/api/auth/challenge/confirm", json={"token": "not-a-real-challenge-token-0123456789abcdef", "password": PW})
    assert r.status_code == 400 and error_code(r) == "challenge_expired"  # a dead token is a failed check too
    r = code_login(learner, PHONE, "000000")
    assert r.status_code == 429 and details(r) == {"retry_after_s": 3600}
    assert learner.post("/api/auth/password/reset", json={"identifier": "nobody", "code": "000000", "new_password": "New-Pass-Word-9"}).status_code == 429
    assert learner.post("/api/auth/challenge/confirm", json={"token": "not-a-real-challenge-token-0123456789abcdef", "password": PW}).status_code == 429
    assert learner.post("/api/account/email/verify", json={"code": "000000"}).status_code == 401  # 10 / 86 / 88 need a session; they share the windows (test_account_phone)


def test_code_login_retries_as_a_login_when_a_racer_created_the_account(client: TestClient, app, settings, sms, frozen_clock, caplog, monkeypatch):
    """API.md 81: a racing request that created the account for the number first surfaces as `sqlite3.IntegrityError` on
    `ux_identities_live` — the transaction is rolled back and run again as a login (200, created false); a code consumed by a
    concurrent request meanwhile is 400 `invalid_code`, nothing created."""
    bootstrap(client)
    racer = second_client(app)
    racer_user = sign_in(racer, sms)["user"]  # the racing request committed first
    frozen_clock.advance(minutes=1)
    learner = second_client(app)
    assert send(learner).status_code == 202
    code = sms.sent[-1].code
    real = security.identity_by_subject
    seen: list[str] = []

    def blind_twice(conn, provider, subject):  # the pre-lock lookup and the one inside the first transaction see no identity yet
        seen.append(subject)
        return None if len(seen) <= 2 else real(conn, provider, subject)

    monkeypatch.setattr(security, "identity_by_subject", blind_twice)
    with caplog.at_level(logging.INFO, logger="wd.routers.auth_codes"):
        r = code_login(learner, PHONE, code)
    assert r.status_code == 200, r.text
    assert r.json()["created"] is False and r.json()["user"]["id"] == racer_user["id"] and "wd_session=" in r.headers["set-cookie"].lower()
    assert len(seen) == 3 and any(getattr(rec, "event", None) == "code_login_retry" for rec in caplog.records)
    logged = [rec for rec in caplog.records if getattr(rec, "event", None) == "code_login"]  # at INFO the event line is emitted (it once carried a reserved key)
    assert len(logged) == 1 and logged[0].created_account is False and logged[0].user_id == racer_user["id"]
    assert count(settings, "users") == 2 and count(settings, "identities") == 1 and count(settings, "login_codes", "used_at IS NULL") == 0
    assert count(settings, "users", "username LIKE 'u@_%' ESCAPE '@'") == 1  # the rolled-back placeholder account never landed
    # the code consumed by a concurrent request between the check and the write
    frozen_clock.advance(minutes=1)
    assert send(learner).status_code == 202
    monkeypatch.setattr(security, "mark_login_code_used", lambda conn, row_id, now: False)
    r = code_login(learner, PHONE, sms.sent[-1].code)
    assert r.status_code == 400 and error_code(r) == "invalid_code" and details(r) == {"attempts_left": 0}
    assert count(settings, "users") == 2 and count(settings, "sessions", "user_id = ?", (racer_user["id"],)) == 2


def test_admins_and_disabled_accounts(client: TestClient, app, settings, sms, frozen_clock):
    root = bootstrap(client)
    c = db.connect(settings.db_path)
    try:
        c.execute("INSERT INTO identities(user_id, provider, subject, verified_at, last_login_at) VALUES (?, 'phone', ?, ?, ?)", (root["id"], E164, NOW_ISO, NOW_ISO))
    finally:
        c.close()
    learner = second_client(app)
    assert send(learner).status_code == 202  # the send never reveals whose number it is
    r = code_login(learner, PHONE, sms.sent[-1].code)
    assert r.status_code == 403 and error_code(r) == "password_required"
    assert count(settings, "login_codes", "used_at IS NULL") == 1  # nothing consumed by a refusal
    bob = sign_in(learner, sms, OTHER)["user"]
    assert client.post(f"/api/admin/users/{bob['id']}", json={"is_active": False}).status_code == 200
    frozen_clock.advance(minutes=1)
    assert send(learner, OTHER).status_code == 202
    r = code_login(learner, OTHER, sms.sent[-1].code)
    assert r.status_code == 403 and error_code(r) == "account_disabled"


def test_registration_modes_for_code_accounts(settings, frozen_clock):
    def app_in(mode: str):
        a = create_app(replace(settings, registration_mode=mode), clock=frozen_clock, configure_logs=False)
        a.state.sms = RecordingSmsSender()
        return a

    closed = app_in("closed")
    with TestClient(closed, base_url="http://testserver") as admin:
        admin.headers["X-WD-Request"] = "1"
        bootstrap(admin)
        learner = second_client(closed)
        assert send(learner).status_code == 202
        r = code_login(learner, PHONE, closed.state.sms.sent[-1].code)
        assert r.status_code == 403 and error_code(r) == "registration_closed"
        assert count(settings, "users") == 1
    frozen_clock.advance(hours=1)
    invite = app_in("invite")
    with TestClient(invite, base_url="http://testserver") as admin:
        admin.headers["X-WD-Request"] = "1"
        admin.post("/api/auth/login", json={"username": "root", "password": PW})
        learner = second_client(invite)
        assert send(learner).status_code == 202
        code = invite.state.sms.sent[-1].code
        r = code_login(learner, PHONE, code)
        assert r.status_code == 403 and error_code(r) == "invalid_invite"
        r = code_login(learner, PHONE, code, invite_code="NOPE-NOPE-NOPE-NOPE")
        assert r.status_code == 403 and error_code(r) == "invalid_invite"
        invite_code = admin.post("/api/admin/invites", json={}).json()["code"]
        r = code_login(learner, PHONE, code, invite_code=invite_code)
        assert r.status_code == 201 and r.json()["created"] is True
        assert admin.get("/api/admin/invites").json()["items"][0]["uses"] == 1
        frozen_clock.advance(minutes=1)
        assert send(learner).status_code == 202
        assert code_login(learner, PHONE, invite.state.sms.sent[-1].code).status_code == 200  # an existing account needs no code
    frozen_clock.advance(hours=1)
    verified = app_in("verified")
    with TestClient(verified, base_url="http://testserver") as admin:
        admin.headers["X-WD-Request"] = "1"
        admin.post("/api/auth/login", json={"username": "root", "password": PW})
        learner = second_client(verified)
        assert send(learner, OTHER).status_code == 202
        r = code_login(learner, OTHER, verified.state.sms.sent[-1].code, invite_code="NOPE-NOPE-NOPE-NOPE")
        assert r.status_code == 403 and error_code(r) == "invalid_invite"  # optional, but a given code must be valid
        frozen_clock.advance(minutes=1)
        assert send(learner, OTHER).status_code == 202
        r = code_login(learner, OTHER, verified.state.sms.sent[-1].code)
        assert r.status_code == 201 and r.json()["user"]["phone_masked"] == "139****9000"
        assert count(settings, "users") == 3


# ---------------------------------------------------------------------------- the stale-phone challenge (82–84)
def test_stale_phone_challenge_confirmed_by_password(client: TestClient, app, settings, sms, frozen_clock):
    bootstrap(client)
    learner = second_client(app)
    user = sign_in(learner, sms)["user"]
    r = learner.post("/api/account/profile", json={"display_name": "小明", "age_band": "adult", "password": PW})
    assert r.status_code == 200 and r.json()["user"]["has_password"] is True
    learner.post("/api/auth/logout")
    learner.cookies.clear()
    frozen_clock.advance(days=89)
    sign_in(learner, sms)  # 89 days later: not stale yet (90 is the limit), a plain login
    learner.cookies.clear()
    frozen_clock.advance(days=91)
    assert send(learner).status_code == 202
    r = code_login(learner, PHONE, sms.sent[-1].code)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user"] is None and body["settings"] is None and body["created"] is False and "set-cookie" not in r.headers
    challenge = body["challenge"]
    assert set(challenge) == {"token", "display_name_masked", "since", "can_password", "can_email", "email_masked"}
    assert challenge["display_name_masked"] == "小＊＊" and challenge["since"] == "2026-10" and challenge["can_password"] is True and challenge["can_email"] is False and challenge["email_masked"] is None
    assert count(settings, "login_codes", "purpose = 'challenge' AND used_at IS NULL") == 1
    assert count(settings, "login_codes", "purpose = 'login' AND used_at IS NOT NULL AND target = ?", (E164,)) == 3  # the login code was consumed
    token = challenge["token"]
    r = learner.post("/api/auth/challenge/confirm", json={"token": token})
    assert r.status_code == 403 and error_code(r) == "second_factor_required"
    r = learner.post("/api/auth/challenge/confirm", json={"token": token, "code": "123456"})
    assert r.status_code == 403 and error_code(r) == "second_factor_required"  # no verified e-mail
    r = learner.post("/api/auth/challenge/confirm", json={"token": token, "password": "wrong-password-1"})
    assert r.status_code == 401 and error_code(r) == "invalid_credentials"
    assert count(settings, "auth_throttle", "key = ? AND count = 1", (f"pwcheck:user:{user['id']}",)) == 1
    r = learner.post("/api/auth/challenge/confirm", json={"token": token, "password": PW})
    assert r.status_code == 200 and "wd_session=" in r.headers["set-cookie"].lower() and r.json()["user"]["id"] == user["id"]
    assert rows(settings, "SELECT last_login_at FROM identities")[0]["last_login_at"] == "2027-04-12T00:00:00Z"
    assert learner.get("/api/auth/me").status_code == 200
    r = learner.post("/api/auth/challenge/confirm", json={"token": token, "password": PW})
    assert r.status_code == 400 and error_code(r) == "challenge_expired"  # consumed
    for bad in ("x" * 43, token + "x"):
        r = learner.post("/api/auth/challenge/email", json={"token": bad})
        assert r.status_code == 400 and error_code(r) == "challenge_expired", bad  # a well-formed token nobody issued
    r = learner.post("/api/auth/challenge/email", json={"token": "x" * 129})
    assert r.status_code == 400 and error_code(r) == "validation_error"  # over the schema's length
    # the next code login is plain again (last_login_at is fresh); a challenge token expires after 10 minutes
    learner.cookies.clear()
    frozen_clock.advance(minutes=1)
    assert sign_in(learner, sms)["user"]["id"] == user["id"]
    learner.cookies.clear()
    frozen_clock.advance(days=100)
    assert send(learner).status_code == 202
    token2 = code_login(learner, PHONE, sms.sent[-1].code).json()["challenge"]["token"]
    frozen_clock.advance(minutes=10)
    r = learner.post("/api/auth/challenge/confirm", json={"token": token2, "password": PW})
    assert r.status_code == 400 and error_code(r) == "challenge_expired"


def test_stale_phone_challenge_confirmed_by_email_code(client: TestClient, app, settings, sms, mailer, frozen_clock):
    bootstrap(client)
    learner = second_client(app)
    user = sign_in(learner, sms)["user"]
    assert learner.put("/api/account", json={"email": "Xiao@Example.com"}).status_code == 200
    assert learner.post("/api/account/email/request-code").status_code == 202
    assert learner.post("/api/account/email/verify", json={"code": mail_code(mailer)}).status_code == 200
    learner.cookies.clear()
    frozen_clock.advance(days=91)
    assert send(learner).status_code == 202
    challenge = code_login(learner, PHONE, sms.sent[-1].code).json()["challenge"]
    assert challenge["can_password"] is False and challenge["can_email"] is True and challenge["email_masked"] == "x***@example.com"
    assert challenge["display_name_masked"] == "u＊＊"  # the placeholder username is the display name until endpoint 89
    token = challenge["token"]
    r = learner.post("/api/auth/challenge/confirm", json={"token": token, "password": PW})
    assert r.status_code == 403 and error_code(r) == "second_factor_required"  # no password on this account
    r = learner.post("/api/auth/challenge/email", json={"token": token})
    assert r.status_code == 202 and r.json() == {"sent": True, "expires_in_s": 600}
    assert mailer.sent[-1].to == "xiao@example.com" and "登录验证码" in mailer.sent[-1].subject
    issued = rows(settings, "SELECT * FROM login_codes WHERE channel = 'email' AND purpose = 'login'")
    assert len(issued) == 1 and issued[0]["user_id"] == user["id"] and issued[0]["target"] == "xiao@example.com"
    r = learner.post("/api/auth/challenge/email", json={"token": token})
    assert r.status_code == 429  # the e-mail's own send throttle (1/min)
    code = mail_code(mailer)
    wrong = "000000" if code != "000000" else "111111"
    r = learner.post("/api/auth/challenge/confirm", json={"token": token, "code": wrong})
    assert r.status_code == 400 and error_code(r) == "invalid_code" and details(r) == {"attempts_left": 4}
    r = learner.post("/api/auth/challenge/confirm", json={"token": token, "code": code})
    assert r.status_code == 200 and r.json()["user"]["id"] == user["id"] and r.json()["user"]["email_verified"] is True
    assert count(settings, "login_codes", "used_at IS NULL") == 0  # the challenge and the e-mail code are both consumed
    # a challenge for an account without a verified e-mail cannot ask for one
    other = second_client(app)
    frozen_clock.advance(minutes=1)
    sign_in(other, sms, OTHER)
    other.cookies.clear()
    frozen_clock.advance(days=91)
    assert send(other, OTHER).status_code == 202
    challenge = code_login(other, OTHER, sms.sent[-1].code).json()["challenge"]
    assert challenge["can_password"] is False and challenge["can_email"] is False  # the SPA shows 「请联系管理员」; 「不是我的」 stays available
    r = other.post("/api/auth/challenge/email", json={"token": challenge["token"]})
    assert r.status_code == 403 and error_code(r) == "second_factor_required"


def test_stale_phone_dispute_creates_a_new_account_and_notifies_the_old_one(client: TestClient, app, settings, sms, mailer, frozen_clock):
    bootstrap(client)
    old_client = second_client(app)
    old = sign_in(old_client, sms)["user"]
    old_client.put("/api/account", json={"email": "old@example.com"})
    old_client.post("/api/account/email/request-code")
    old_client.post("/api/account/email/verify", json={"code": mail_code(mailer)})
    frozen_clock.advance(days=91)
    newcomer = second_client(app)
    assert send(newcomer).status_code == 202
    token = code_login(newcomer, PHONE, sms.sent[-1].code).json()["challenge"]["token"]
    r = newcomer.post("/api/auth/challenge/dispute", json={"token": token})
    assert r.status_code == 201, r.text
    new = r.json()["user"]
    assert new["id"] != old["id"] and new["phone_masked"] == "138****8000" and new["needs_profile"] is True and "wd_session=" in r.headers["set-cookie"].lower()
    identities = rows(settings, "SELECT * FROM identities ORDER BY id")
    assert len(identities) == 2
    assert identities[0]["user_id"] == old["id"] and identities[0]["disputed_at"] == "2027-01-13T00:00:00Z"
    assert identities[1]["user_id"] == new["id"] and identities[1]["disputed_at"] is None and identities[1]["subject"] == E164
    event = rows(settings, "SELECT detail_json FROM system_events WHERE kind = 'phone_disputed'")
    assert len(event) == 1 and json.loads(event[0]["detail_json"]) == {"identity_id": identities[0]["id"], "new_user_id": new["id"], "old_user_id": old["id"]}
    notice = mailer.sent[-1]
    assert notice.to == "old@example.com" and "手机号" in notice.subject and "138****8000" in notice.text and PHONE not in notice.text
    r = newcomer.post("/api/auth/challenge/dispute", json={"token": token})
    assert r.status_code == 400 and error_code(r) == "challenge_expired"  # consumed
    assert old_client.get("/api/auth/me").status_code == 401  # 91 frozen days: the old owner's session expired long ago …
    assert send(old_client, "old@example.com", channel="email").status_code == 202  # … but its e-mail login still works
    r = code_login(old_client, "old@example.com", mail_code(mailer), channel="email")
    assert r.status_code == 200 and r.json()["user"]["id"] == old["id"] and r.json()["user"]["phone_masked"] is None  # the old account lost the binding
    # the number now logs the newcomer in directly
    frozen_clock.advance(minutes=1)
    assert sign_in(newcomer, sms)["user"]["id"] == new["id"]


def test_dispute_follows_the_registration_mode_and_closed_mode_still_logs_existing_accounts_in(settings, frozen_clock):
    """API.md 84: the dispute creates the new account exactly like 81's new-user branch — `closed` → 403 and the old binding and the
    challenge survive the refusal, `invite` → a valid code is required and consumed; an existing account keeps signing in by code
    while registration is closed."""

    def app_in(mode: str):
        a = create_app(replace(settings, registration_mode=mode), clock=frozen_clock, configure_logs=False)
        a.state.sms = RecordingSmsSender()
        return a

    closed = app_in("closed")
    with TestClient(closed, base_url="http://testserver") as admin:
        admin.headers["X-WD-Request"] = "1"
        bootstrap(admin)
        now = frozen_clock.now_utc()
        c = db.connect(settings.db_path)
        try:
            with db.tx(c):
                old = security.create_user(c, username="olduser", password_hash=security.hash_password(PW), now=now, password_set_at=NOW_ISO)
                c.execute("INSERT INTO identities(user_id, provider, subject, verified_at, last_login_at) VALUES (?, 'phone', ?, ?, ?)", (old, E164, NOW_ISO, NOW_ISO))
                fresh = security.create_user(c, username="fresh", password_hash=security.hash_password(PW), now=now, password_set_at=NOW_ISO)
                c.execute("INSERT INTO identities(user_id, provider, subject, verified_at, last_login_at) VALUES (?, 'phone', ?, ?, ?)", (fresh, OTHER_E164, "2027-01-13T00:00:00Z", "2027-01-13T00:00:00Z"))
        finally:
            c.close()
        frozen_clock.advance(days=91)  # olduser's binding is stale now; fresh's is not
        newcomer = second_client(closed)
        assert send(newcomer).status_code == 202
        challenge = code_login(newcomer, PHONE, closed.state.sms.sent[-1].code).json()["challenge"]
        assert challenge["can_password"] is True
        r = newcomer.post("/api/auth/challenge/dispute", json={"token": challenge["token"]})
        assert r.status_code == 403 and error_code(r) == "registration_closed"
        assert rows(settings, "SELECT disputed_at FROM identities WHERE user_id = ?", (old,))[0]["disputed_at"] is None  # the old binding survives the refusal …
        assert count(settings, "login_codes", "purpose = 'challenge' AND used_at IS NULL") == 1  # … and so does the challenge (one transaction)
        assert count(settings, "users") == 3 and count(settings, "system_events", "kind = 'phone_disputed'") == 0
        assert newcomer.post("/api/auth/login", json={"username": "olduser", "password": PW}).status_code == 200
        newcomer.cookies.clear()
        frozen_clock.advance(minutes=1)
        existing = second_client(closed)
        assert send(existing, OTHER).status_code == 202
        r = code_login(existing, OTHER, closed.state.sms.sent[-1].code)
        assert r.status_code == 200 and r.json()["created"] is False and r.json()["user"]["username"] == "fresh"  # closed mode: a login, not a registration
    frozen_clock.advance(hours=1)
    invite = app_in("invite")
    with TestClient(invite, base_url="http://testserver") as admin:
        admin.headers["X-WD-Request"] = "1"
        assert admin.post("/api/auth/login", json={"username": "root", "password": PW}).status_code == 200
        newcomer = second_client(invite)
        assert send(newcomer).status_code == 202
        token = code_login(newcomer, PHONE, invite.state.sms.sent[-1].code).json()["challenge"]["token"]
        r = newcomer.post("/api/auth/challenge/dispute", json={"token": token})
        assert r.status_code == 403 and error_code(r) == "invalid_invite"
        r = newcomer.post("/api/auth/challenge/dispute", json={"token": token, "invite_code": "NOPE-NOPE-NOPE-NOPE"})
        assert r.status_code == 403 and error_code(r) == "invalid_invite"
        assert rows(settings, "SELECT disputed_at FROM identities WHERE user_id = ?", (old,))[0]["disputed_at"] is None
        invite_code = admin.post("/api/admin/invites", json={}).json()["code"]
        r = newcomer.post("/api/auth/challenge/dispute", json={"token": token, "invite_code": invite_code})
        assert r.status_code == 201, r.text
        assert r.json()["user"]["needs_profile"] is True and r.json()["user"]["phone_masked"] == "138****8000"
        assert admin.get("/api/admin/invites").json()["items"][0]["uses"] == 1
        assert rows(settings, "SELECT disputed_at FROM identities WHERE user_id = ?", (old,))[0]["disputed_at"] is not None
        assert count(settings, "users") == 4 and count(settings, "system_events", "kind = 'phone_disputed'") == 1


# -------------------------------------------------------------------------------- forgot + reset (90, 91)
def test_forgot_and_reset_password(client: TestClient, app, settings, sms, mailer, frozen_clock):
    bootstrap(client, email="root@example.com")
    learner = second_client(app)
    user = sign_in(learner, sms)["user"]
    assert learner.post("/api/account/profile", json={"display_name": "小明", "age_band": "adult", "username": "xiaoming", "password": PW}).status_code == 200
    other_session = second_client(app)
    assert other_session.post("/api/auth/login", json={"username": "xiaoming", "password": PW}).status_code == 200
    learner.cookies.clear()
    sent_before = len(sms.sent)
    ip_window = "key = 'code_send:ip:testclient' AND count = ?"
    assert count(settings, "auth_throttle", ip_window, (1,)) == 1  # the sign-in's send
    r = learner.post("/api/auth/password/forgot", json={"identifier": "nobody"})
    assert r.status_code == 202 and r.json() == {"sent": True, "expires_in_s": 600} and len(sms.sent) == sent_before  # unknown: nothing sent
    assert count(settings, "auth_throttle", ip_window, (2,)) == 1
    r = learner.post("/api/auth/password/forgot", json={"identifier": "root"})
    assert r.status_code == 202 and len(sms.sent) == sent_before and mailer.sent == []  # root's e-mail is not verified: no channel, still 202
    assert count(settings, "auth_throttle", ip_window, (3,)) == 1
    frozen_clock.advance(minutes=1)
    r = learner.post("/api/auth/password/forgot", json={"identifier": "XiaoMing"})
    assert r.status_code == 202 and len(sms.sent) == sent_before + 1
    assert count(settings, "auth_throttle", ip_window, (4,)) == 1  # a known identifier counts the IP window exactly once, like an unknown one
    reset_sms = sms.sent[-1]
    assert reset_sms.to == E164 and reset_sms.template == "100003"
    row = rows(settings, "SELECT * FROM login_codes WHERE purpose = 'reset_password'")[0]
    assert row["user_id"] == user["id"] and row["channel"] == "phone"
    r = learner.post("/api/auth/password/reset", json={"identifier": "nobody", "code": reset_sms.code, "new_password": "New-Pass-Word-9"})
    assert r.status_code == 400 and error_code(r) == "invalid_code" and details(r) == {"attempts_left": 0}
    wrong = "000000" if reset_sms.code != "000000" else "111111"
    r = learner.post("/api/auth/password/reset", json={"identifier": PHONE, "code": wrong, "new_password": "New-Pass-Word-9"})
    assert r.status_code == 400 and error_code(r) == "invalid_code" and details(r) == {"attempts_left": 4}
    r = learner.post("/api/auth/password/reset", json={"identifier": PHONE, "code": reset_sms.code, "new_password": "password123"})
    assert r.status_code == 400 and error_code(r) == "weak_password"
    assert count(settings, "login_codes", "purpose = 'reset_password' AND used_at IS NULL") == 1  # a weak password does not spend the code
    r = learner.post("/api/auth/password/reset", json={"identifier": "xiaoming", "code": reset_sms.code, "new_password": "New-Pass-Word-9"})
    assert r.status_code == 204
    assert other_session.get("/api/auth/me").status_code == 401  # every session revoked
    assert learner.post("/api/auth/login", json={"username": PHONE, "password": PW}).status_code == 401
    assert learner.post("/api/auth/login", json={"username": "13800138000", "password": "New-Pass-Word-9"}).status_code == 200
    assert count(settings, "system_events", "kind = 'password_reset' AND json_extract(detail_json, '$.user_id') = ?", (user["id"],)) == 1
    assert count(settings, "login_codes", "purpose = 'reset_password' AND used_at IS NULL") == 0
    # the e-mail channel when the account has no phone (the admin, once verified) and the forgot IP throttle
    c = db.connect(settings.db_path)
    try:
        c.execute("UPDATE users SET email_verified_at = ? WHERE username = 'root'", (NOW_ISO,))
    finally:
        c.close()
    frozen_clock.advance(minutes=1)
    assert learner.post("/api/auth/password/forgot", json={"identifier": "root@example.com"}).status_code == 202
    assert mailer.sent[-1].to == "root@example.com" and "重置密码" in mailer.sent[-1].subject
    code = mail_code(mailer)
    assert learner.post("/api/auth/password/reset", json={"identifier": "root", "code": code, "new_password": "New-Pass-Word-9"}).status_code == 204
    assert client.get("/api/auth/me").status_code == 401  # the admin's session is gone too
    assert client.post("/api/auth/login", json={"username": "root", "password": "New-Pass-Word-9"}).status_code == 200
    small = create_app(replace(settings, code_ip_hourly=1), clock=frozen_clock, configure_logs=False)
    small.state.sms = RecordingSmsSender()
    with TestClient(small, base_url="http://testserver") as c:
        c.headers["X-WD-Request"] = "1"
        frozen_clock.advance(hours=2)
        assert c.post("/api/auth/password/forgot", json={"identifier": "nobody"}).status_code == 202
        r = c.post("/api/auth/password/forgot", json={"identifier": "nobody"})
        assert r.status_code == 429 and error_code(r) == "rate_limited"
        # the order does not matter: a known identifier spends the one slot like an unknown one (no enumeration at the boundary)
        frozen_clock.advance(hours=2)
        assert c.post("/api/auth/password/forgot", json={"identifier": PHONE}).status_code == 202 and len(small.state.sms.sent) == 1
        assert count(settings, "auth_throttle", ip_window, (1,)) == 1
        r = c.post("/api/auth/password/forgot", json={"identifier": "nobody"})
        assert r.status_code == 429 and error_code(r) == "rate_limited"
        frozen_clock.advance(hours=2)
        assert c.post("/api/auth/password/forgot", json={"identifier": "nobody"}).status_code == 202
        r = c.post("/api/auth/password/forgot", json={"identifier": PHONE})
        assert r.status_code == 429 and error_code(r) == "rate_limited" and len(small.state.sms.sent) == 1  # nothing sent by the refused one


def test_forgot_password_silent_branches_and_the_daily_target_window(client: TestClient, app, settings, sms, frozen_clock):
    """API.md 90: an exhausted target window and a site-wide cap are still 202 with nothing sent; the per-target 10/day window
    (`code_send:target:<t>:d`, shared with 80) refuses the 11th send of a day with the seconds to its end."""
    bootstrap(client)
    learner = second_client(app)
    sign_in(learner, sms)  # PHONE's account; send 1 to PHONE at t = 0
    learner.cookies.clear()
    forgot = lambda identifier: learner.post("/api/auth/password/forgot", json={"identifier": identifier})  # noqa: E731
    frozen_clock.advance(minutes=1)
    sent = len(sms.sent)
    assert forgot(PHONE).status_code == 202 and len(sms.sent) == sent + 1 and sms.sent[-1].template == "100003"
    assert forgot(PHONE).status_code == 202 and len(sms.sent) == sent + 1  # the same minute: the target's 1/min window, still 202, no second SMS
    assert count(settings, "auth_throttle", "key = 'code_send:target:+8613800138000:m' AND count = 1") == 1
    assert count(settings, "auth_throttle", "key = 'code_send:ip:testclient' AND count = 3") == 1  # each request once
    capped = create_app(replace(settings, sms_daily_cap=0), clock=frozen_clock, configure_logs=False)
    capped.state.sms = RecordingSmsSender()
    with TestClient(capped, base_url="http://testserver") as c:
        c.headers["X-WD-Request"] = "1"
        frozen_clock.advance(minutes=1)
        before = count(settings, "login_codes", "purpose = 'reset_password'")
        r = c.post("/api/auth/password/forgot", json={"identifier": PHONE})
        assert r.status_code == 202 and capped.state.sms.sent == [] and count(settings, "login_codes", "purpose = 'reset_password'") == before  # the cap: no row, no SMS
    # the 10/day window of the number, shared by 80 and 90: three requests so far this hour (the sign-in, the forgot, the capped
    # forgot — counted before the cap refused it), two more make five, five in the second hour make ten, the 11th in the third → 429
    frozen_clock.advance(minutes=8)  # t = 10 min
    for i in range(2):
        assert send(learner, PHONE).status_code == 202, i
        frozen_clock.advance(minutes=1)
    frozen_clock.advance(minutes=58)  # t = 70 min: a fresh hour window
    for i in range(5):
        assert send(learner, PHONE).status_code == 202, i
        frozen_clock.advance(minutes=1)
    frozen_clock.advance(minutes=55)  # t = 130 min: the day window opened at t = 0
    r = send(learner, PHONE)
    assert r.status_code == 429 and error_code(r) == "rate_limited" and details(r) == {"retry_after_s": 86400 - 130 * 60}
    assert count(settings, "auth_throttle", "key = 'code_send:target:+8613800138000:d' AND count = 10") == 1
    assert sum(1 for x in sms.sent if x.to == E164) == 9  # ten requests, nine delivered (the capped one counted, sent nothing)
    frozen_clock.advance(minutes=1)
    assert forgot(PHONE).status_code == 202 and sum(1 for x in sms.sent if x.to == E164) == 9  # 90 shares the window: still 202, nothing sent
