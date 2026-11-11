"""Endpoint 117 `DELETE /api/account/identities/{provider}` (API.md §3.3, slice 2-A): unbinding a WeChat / QQ / Apple identity after the
endpoint-7 re-authentication — the password path and the reauth-code path, `not_bound`, `provider_unconfigured` when the provider is off
and nothing is bound, `last_login_method` for a third-party-only account, a successful unbind shrinking `providers`, a child → 403, an
unknown provider → 404, and the admin list carrying `providers`."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from wd import db, security
from wd.clock import to_iso
from wd.delivery.wechat import FakeWechatClient

PW = "Correct-Horse-7"
NOW = datetime(2026, 10, 14, 0, 0, 0, tzinfo=timezone.utc)
NOW_ISO = "2026-10-14T00:00:00Z"
E164 = "+8613800138000"


@pytest.fixture(autouse=True)
def fast_bcrypt(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(security, "BCRYPT_ROUNDS", 4)


@pytest.fixture
def wechat(app) -> FakeWechatClient:
    fake = FakeWechatClient()
    app.state.wechat = fake
    return fake


def second_client(app) -> TestClient:
    c = TestClient(app, base_url="http://testserver")
    c.headers["X-WD-Request"] = "1"
    return c


def register(client: TestClient, username: str) -> dict:
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


def bind(settings, user_id: int, provider: str, subject: str) -> None:
    c = db.connect(settings.db_path)
    try:
        with db.tx(c):
            c.execute("INSERT INTO identities(user_id, provider, subject, verified_at, last_login_at, created_at) VALUES (?, ?, ?, ?, ?, ?)", (user_id, provider, subject, NOW_ISO, NOW_ISO, NOW_ISO))
    finally:
        c.close()


def password_less_account(app, settings, *, identities: list[tuple[str, str]], email: str | None = None, verified: bool = False) -> tuple[TestClient, int]:
    """An account without a password (the unusable hash, ``password_set_at`` NULL) holding ``identities``, signed in on a fresh client
    through a session row written directly — the shape a WeChat / QQ / Apple sign-in leaves behind."""
    c = db.connect(settings.db_path)
    try:
        with db.tx(c):
            uid = security.create_user(
                c,
                username=security.placeholder_username(c),
                password_hash=security.unusable_password_hash(),
                now=NOW,
                email=email,
                password_set_at=None,
                email_verified_at=NOW_ISO if (email and verified) else None,
            )
            for provider, subject in identities:
                c.execute("INSERT INTO identities(user_id, provider, subject, verified_at, last_login_at, created_at) VALUES (?, ?, ?, ?, ?, ?)", (uid, provider, subject, NOW_ISO, NOW_ISO, NOW_ISO))
            token = security.create_session(c, uid, NOW, session_days=settings.session_days)
    finally:
        c.close()
    client = second_client(app)
    client.cookies.set("wd_session", token)
    return client, uid


def reauth_code(settings, user_id: int, *, channel: str = "email", target: str = "x@example.com") -> str:
    """A ``reauth`` code written straight into ``login_codes`` (endpoint 85 would refuse an account without a phone / verified e-mail)."""
    c = db.connect(settings.db_path)
    try:
        return security.issue_login_code(c, channel=channel, target=target, purpose="reauth", user_id=user_id, ip="testclient", secret_key=settings.secret_key, now=NOW)
    finally:
        c.close()


def unbind(client: TestClient, provider: str, **body):
    return client.request("DELETE", f"/api/account/identities/{provider}", json=body)


# ------------------------------------------------------------------------------------------- the paths
def test_unbind_with_the_password(client: TestClient, settings, caplog):
    root = register(client, "root")
    bind(settings, root["id"], "wechat_mini", "wx_root")
    bind(settings, root["id"], "qq", "qq_root")
    assert client.get("/api/auth/me").json()["user"]["providers"] == ["qq", "wechat_mini"]
    r = unbind(client, "wechat_mini")  # no factor → 400 like endpoint 87
    assert r.status_code == 400 and error_code(r) == "validation_error"
    r = unbind(client, "wechat_mini", password="wrong-password-1")
    assert r.status_code == 401 and error_code(r) == "invalid_credentials"
    r = unbind(client, "wechat_mini", password=PW, code="123456")
    assert r.status_code == 400 and "body" in details(r)["fields"]  # the 87 one-of: never both
    with caplog.at_level(logging.INFO, logger="wd"):
        r = unbind(client, "wechat_mini", password=PW)
    assert r.status_code == 200, r.text
    assert set(r.json()) == {"user"} and r.json()["user"]["providers"] == ["qq"] and r.json()["user"]["has_password"] is True
    assert [i["provider"] for i in rows(settings, "SELECT provider FROM identities ORDER BY provider")] == ["qq"]
    unbound = [rec for rec in caplog.records if getattr(rec, "event", None) == "auth_identity_unbound"]
    assert len(unbound) == 1 and (unbound[0].provider, unbound[0].user_id) == ("wechat_mini", root["id"])
    assert "wx_root" not in caplog.text
    # the password alone is a way in: the last third-party identity may go too (ways_in = password + qq = 2 before the delete)
    r = unbind(client, "qq", password=PW)
    assert r.status_code == 200 and r.json()["user"]["providers"] == []
    assert client.get("/api/auth/me").json()["user"]["providers"] == []


def test_unbind_with_a_reauth_code_for_a_password_less_account(app, client: TestClient, settings):
    register(client, "root")
    me, uid = password_less_account(app, settings, identities=[("phone", E164), ("apple", "sub-1")])
    assert me.get("/api/auth/me").json()["user"]["providers"] == ["apple"]
    r = unbind(me, "apple", password=PW)
    assert r.status_code == 400 and details(r)["fields"] == {"code": "必填"}  # no password on this account: the code path
    code = reauth_code(settings, uid, channel="phone", target=E164)
    r = unbind(me, "apple", code="000000" if code != "000000" else "000001")
    assert r.status_code == 400 and error_code(r) == "invalid_code" and details(r)["attempts_left"] == 4
    r = unbind(me, "apple", code=code)
    assert r.status_code == 200 and r.json()["user"]["providers"] == [] and r.json()["user"]["phone_masked"] == "138****8000"
    assert rows(settings, "SELECT used_at FROM login_codes")[0]["used_at"] == NOW_ISO  # the code was consumed with the delete
    r = unbind(me, "apple", code=code)
    assert r.status_code == 400 and error_code(r) == "invalid_code"  # spent


def test_not_bound_and_provider_unconfigured(client: TestClient, app, settings, wechat):
    root = register(client, "root")
    assert getattr(app.state, "apple", None) is None and getattr(app.state, "qq", None) is None  # off in the test env; the WeChat fake is installed
    r = unbind(client, "wechat_mini", password=PW)
    assert r.status_code == 409 and error_code(r) == "invalid_transition" and details(r) == {"reason": "not_bound"}
    r = unbind(client, "apple", password=PW)
    assert r.status_code == 409 and error_code(r) == "provider_unconfigured"  # off AND nothing bound
    bind(settings, root["id"], "apple", "sub-1")
    r = unbind(client, "apple", password=PW)
    assert r.status_code == 200 and r.json()["user"]["providers"] == []  # a bound identity can always be unbound, flag or no flag
    # the re-authentication runs before the state checks: a wrong password is a 401 even for an unbound provider
    r = unbind(client, "qq", password="wrong-password-1")
    assert r.status_code == 401


def test_last_login_method_for_a_third_party_only_account(app, client: TestClient, settings):
    register(client, "root")
    me, uid = password_less_account(app, settings, identities=[("wechat_mini", "wx_only")])
    r = unbind(me, "wechat_mini", code=reauth_code(settings, uid))
    assert r.status_code == 409 and error_code(r) == "last_login_method"
    assert rows(settings, "SELECT COUNT(*) AS n FROM identities WHERE user_id = ?", (uid,))[0]["n"] == 1
    assert rows(settings, "SELECT used_at FROM login_codes")[0]["used_at"] is None  # the transaction rolled the consumption back
    # a second third-party identity is another way in: it may go, the last one may not
    bind(settings, uid, "qq", "qq_only")
    assert me.get("/api/auth/me").json()["user"]["providers"] == ["qq", "wechat_mini"]
    r = unbind(me, "qq", code=reauth_code(settings, uid))
    assert r.status_code == 200 and r.json()["user"]["providers"] == ["wechat_mini"]
    r = unbind(me, "wechat_mini", code=reauth_code(settings, uid))
    assert r.status_code == 409 and error_code(r) == "last_login_method"
    # a verified e-mail counts as a way in
    me2, uid2 = password_less_account(app, settings, identities=[("qq", "qq_mail")], email="mail@example.com", verified=True)
    r = unbind(me2, "qq", code=reauth_code(settings, uid2, target="mail@example.com"))
    assert r.status_code == 200 and r.json()["user"]["providers"] == [] and r.json()["user"]["email_verified"] is True
    # an unverified e-mail does not
    me3, uid3 = password_less_account(app, settings, identities=[("qq", "qq_unverified")], email="raw@example.com", verified=False)
    r = unbind(me3, "qq", code=reauth_code(settings, uid3, target="raw@example.com"))
    assert r.status_code == 409 and error_code(r) == "last_login_method"


def test_children_unknown_providers_and_phone_routing(client: TestClient, app, settings, wechat):
    root = register(client, "root")
    bob_client = second_client(app)
    bob = register(bob_client, "bob")
    bind(settings, bob["id"], "wechat_mini", "wx_bob")
    r = unbind(bob_client, "github", password=PW)
    assert r.status_code == 404 and error_code(r) == "not_found"  # outside PROVIDERS, before any re-authentication
    r = unbind(bob_client, "phone", password=PW)
    assert r.status_code == 409 and details(r) == {"reason": "no_phone"}  # endpoint 87 answers for `phone`
    c = db.connect(settings.db_path)
    try:
        with db.tx(c):
            c.execute("UPDATE users SET guardian_user_id = ? WHERE id = ?", (root["id"], bob["id"]))
    finally:
        c.close()
    r = unbind(bob_client, "wechat_mini", password=PW)
    assert r.status_code == 403 and error_code(r) == "guardian_required"  # a child never changes its identities
    assert rows(settings, "SELECT COUNT(*) AS n FROM identities")[0]["n"] == 1
    assert second_client(app).request("DELETE", "/api/account/identities/wechat_mini", json={"password": PW}).status_code == 401


def test_admin_user_list_carries_providers(client: TestClient, settings):
    root = register(client, "root")
    bind(settings, root["id"], "qq", "qq_root")
    items = {u["id"]: u for u in client.get("/api/admin/users").json()["items"]}
    assert items[root["id"]]["providers"] == ["qq"] and to_iso(NOW) == NOW_ISO
