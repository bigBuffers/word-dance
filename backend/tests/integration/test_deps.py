"""deps.client_ip behind a trusted proxy (the per-IP throttles key on the hop the proxy appended, never the client-sent
first one) and the sliding session expiry re-issuing the ``wd_session`` cookie (deps.current_user + main.WdMiddleware)."""

from __future__ import annotations

from dataclasses import replace

from fastapi import APIRouter, Request
from fastapi.testclient import TestClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from wd import db
from wd.deps import client_ip
from wd.main import create_app

PW = "Passw0rd!xyz"
REAL = "198.51.100.7"  # the client nginx/Caddy appends to X-Forwarded-For


def _probe_app(settings, frozen_clock, **overrides):
    """create_app plus a POST probe returning client_ip() (POST: the SPA catch-all shadows unknown GET paths)."""
    app = create_app(replace(settings, **overrides), clock=frozen_clock, configure_logs=False)
    router = APIRouter()

    @router.post("/api/_test/ip")
    def ip(request: Request):
        return {"ip": client_ip(request), "peer": request.client.host if request.client else None}

    app.include_router(router)
    return app


def _client(app, peer: str, *, proxy_headers: bool = False) -> TestClient:
    target = ProxyHeadersMiddleware(app, trusted_hosts="127.0.0.1") if proxy_headers else app
    c = TestClient(target, base_url="http://testserver", client=(peer, 40000))
    c.headers["X-WD-Request"] = "1"
    return c


# ----------------------------------------------------------------------------------------- client_ip
def test_client_ip_is_the_proxy_appended_hop_never_the_first(settings, frozen_clock):
    app = _probe_app(settings, frozen_clock, trust_proxy=True)
    xff = {"X-Forwarded-For": f"203.0.113.5, {REAL}"}  # nginx `$proxy_add_x_forwarded_for`: client-sent value, then $remote_addr
    # what `wd serve` runs: uvicorn's ProxyHeadersMiddleware (forwarded_allow_ips=127.0.0.1) rewrote request.client already
    with _client(app, "127.0.0.1", proxy_headers=True) as c:
        assert c.post("/api/_test/ip", headers=xff).json() == {"ip": REAL, "peer": REAL}
        assert c.post("/api/_test/ip", headers={"X-Forwarded-For": REAL}).json()["ip"] == REAL  # Caddy: a single hop
        assert c.post("/api/_test/ip").json()["ip"] == "127.0.0.1"  # no header: the peer itself
    # no proxy middleware in the stack (another ASGI runner): the LAST hop is used as the fallback
    with _client(app, "127.0.0.1") as c:
        assert c.post("/api/_test/ip", headers=xff).json() == {"ip": REAL, "peer": "127.0.0.1"}
    # a peer that is not the local proxy cannot inject the header at all
    with _client(app, "203.0.113.9") as c:
        assert c.post("/api/_test/ip", headers={"X-Forwarded-For": "203.0.113.5"}).json()["ip"] == "203.0.113.9"


def test_client_ip_ignores_the_header_without_trust_proxy(settings, frozen_clock):
    app = _probe_app(settings, frozen_clock, trust_proxy=False)
    with _client(app, "127.0.0.1") as c:
        assert c.post("/api/_test/ip", headers={"X-Forwarded-For": "203.0.113.5"}).json()["ip"] == "127.0.0.1"
    with _client(app, "127.0.0.1", proxy_headers=True) as c:  # uvicorn would not run its middleware either (proxy_headers=WD_TRUST_PROXY)
        assert c.post("/api/_test/ip").json()["ip"] == "127.0.0.1"


def test_rotating_first_hops_do_not_bypass_the_per_ip_throttles(settings, frozen_clock):
    """Password spraying with a fresh client-chosen first hop per request (DESIGN §10: login 20/10 min per IP)."""
    app = create_app(replace(settings, trust_proxy=True), clock=frozen_clock, configure_logs=False)
    with _client(app, "127.0.0.1", proxy_headers=True) as c:
        statuses = []
        for n in range(25):
            r = c.post("/api/auth/login", json={"username": f"ghost{n}", "password": PW}, headers={"X-Forwarded-For": f"203.0.113.{n + 1}, {REAL}"})
            statuses.append(r.status_code)
        assert statuses == [401] * 20 + [429] * 5
        # a different real client behind the same proxy is unaffected
        assert c.post("/api/auth/login", json={"username": "ghost", "password": PW}, headers={"X-Forwarded-For": f"203.0.113.1, 192.0.2.44"}).status_code == 401
        # sessions.ip records the proxy-appended address, not the spoofed one
        r = c.post("/api/auth/register", json={"username": "alice", "password": PW}, headers={"X-Forwarded-For": f"203.0.113.77, {REAL}"})
        assert r.status_code == 201, r.text
    conn = db.connect(settings.db_path)
    try:
        keys = sorted(k for (k,) in conn.execute("SELECT key FROM auth_throttle WHERE key LIKE 'login:ip:%'"))
        assert keys == ["login:ip:192.0.2.44", f"login:ip:{REAL}"]
        assert [ip for (ip,) in conn.execute("SELECT ip FROM sessions")] == [REAL]
    finally:
        conn.close()


# ---------------------------------------------------------------------------------- sliding expiry
def _set_cookies(response) -> list[str]:
    return [v for v in response.headers.get_list("set-cookie") if v.lower().startswith("wd_session=")]


def test_sliding_expiry_reissues_the_cookie_once_a_day(client: TestClient, settings, frozen_clock):
    """The DB row sliding alone changes nothing for the browser, which drops the cookie Max-Age after the Set-Cookie it last
    saw: whenever deps.current_user slides the expiry the response re-sends the cookie with a fresh Max-Age."""
    r = client.post("/api/auth/register", json={"username": "alice", "password": PW})
    assert r.status_code == 201, r.text
    token = client.cookies.get("wd_session")
    assert token and "max-age=2592000" in r.headers["set-cookie"].lower()
    assert _set_cookies(client.get("/api/auth/me")) == []  # same day: nothing slid, nothing re-sent
    frozen_clock.advance(days=2)
    r = client.get("/api/auth/me")
    assert r.status_code == 200
    (cookie,) = _set_cookies(r)
    low = cookie.lower()
    assert low.startswith(f"wd_session={token.lower()};") and "max-age=2592000" in low and "httponly" in low and "path=/" in low and "samesite=lax" in low
    assert "secure" not in low  # same attributes as login (plain http deployment)
    conn = db.connect(settings.db_path)
    try:
        (expires,) = conn.execute("SELECT expires_at FROM sessions").fetchone()
        (word_id,) = conn.execute("SELECT id FROM words WHERE is_public = 1 ORDER BY id LIMIT 1").fetchone()
    finally:
        conn.close()
    assert expires == "2026-11-15T00:00:00Z"  # slid from the day-2 request
    assert _set_cookies(client.get("/api/auth/me")) == []  # once per day
    # a route answering with a raw Response (media) re-issues as well
    frozen_clock.advance(days=2)
    r = client.get(f"/media/card/{word_id}.svg")
    assert r.status_code == 200 and len(_set_cookies(r)) == 1 and _set_cookies(r)[0].lower().startswith(f"wd_session={token.lower()};")
    # logout clears the cookie: exactly one wd_session Set-Cookie, the deletion — never a re-issue next to it
    frozen_clock.advance(days=2)
    r = client.post("/api/auth/logout")
    assert r.status_code == 204
    cookies = _set_cookies(r)
    assert len(cookies) == 1 and "max-age=0" in cookies[0].lower()
