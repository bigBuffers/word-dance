"""GET /api/health (endpoint 1) and the P0 application plumbing: headers, envelope, CSRF rule, body limit, lifespan."""

from __future__ import annotations

import hashlib
import json
import uuid

from fastapi.testclient import TestClient

from wd import __version__, db
from wd.schemas import LoginRequest  # module level: with postponed annotations FastAPI resolves names in module globals


def test_health_ok_needs_setup_true_on_empty_users(client: TestClient):
    r = client.get("/api/health")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok" and body["needs_setup"] is True
    assert body["version"] == __version__ and body["registration_mode"] == "open"
    assert body["time"] == "2026-10-14T00:00:00Z"  # frozen clock
    assert set(body) == {"status", "version", "registration_mode", "needs_setup", "sms_enabled", "email_enabled", "captcha", "wechat_enabled", "qq_enabled", "apple_enabled", "time"}
    assert body["sms_enabled"] is False and body["email_enabled"] is False and body["captcha"] is False  # the test env: no providers, WD_CAPTCHA=off
    assert (body["wechat_enabled"], body["qq_enabled"], body["apple_enabled"]) == (False, False, False)  # slice 2-A ships dark: no WD_WECHAT_* / WD_QQ_* / WD_APPLE_*, no fakes


def test_health_third_party_flags_follow_the_fakes_and_installed_clients(settings, frozen_clock):
    """The three slice 2-A flags are `Settings.<provider>_configured or auth_fake_providers` — or, like `sms_enabled`, a client installed on
    `app.state` next to an unconfigured provider (the tests' fakes); `/api/auth/me` reports the same values (routers/auth.server_flags)."""
    from dataclasses import replace

    from wd.delivery.apple import FakeAppleKeys
    from wd.delivery.qq import FakeQQClient
    from wd.delivery.wechat import FakeWechatClient
    from wd.main import create_app

    app = create_app(replace(settings, dev=True, auth_fake_providers=True), clock=frozen_clock, configure_logs=False)
    assert isinstance(app.state.wechat, FakeWechatClient) and isinstance(app.state.qq, FakeQQClient) and isinstance(app.state.apple, FakeAppleKeys)
    with TestClient(app) as c:
        body = c.get("/api/health").json()
        assert (body["wechat_enabled"], body["qq_enabled"], body["apple_enabled"]) == (True, True, True)
    app = create_app(settings, clock=frozen_clock, configure_logs=False)
    assert app.state.wechat is None and app.state.qq is None and app.state.apple is None  # the factories return None while the providers are off
    app.state.qq = FakeQQClient()  # the integration-test pattern: swap a fake in next to an `off` provider
    with TestClient(app) as c:
        c.headers["X-WD-Request"] = "1"
        body = c.get("/api/health").json()
        assert (body["wechat_enabled"], body["qq_enabled"], body["apple_enabled"]) == (False, True, False)
        assert c.post("/api/auth/register", json={"username": "alice", "password": "Passw0rd!xyz"}).status_code == 201
        server = c.get("/api/auth/me").json()["server"]
        assert (server["wechat_enabled"], server["qq_enabled"], server["apple_enabled"]) == (False, True, False)


def test_health_needs_setup_false_once_a_user_exists(client: TestClient, settings):
    c = db.connect(settings.db_path)
    try:
        c.execute("INSERT INTO users(username, password_hash, role) VALUES ('alice', 'x', 'admin')")
    finally:
        c.close()
    assert client.get("/api/health").json()["needs_setup"] is False


def test_health_degraded_when_db_unreachable(client: TestClient, monkeypatch):
    import sqlite3

    def broken(*a, **k):
        raise sqlite3.OperationalError("unable to open database file")

    monkeypatch.setattr("wd.routers.health.db.connect", broken)
    r = client.get("/api/health")
    assert r.status_code == 503 and r.json()["status"] == "degraded"


def test_every_response_carries_request_id_and_security_headers(client: TestClient):
    r = client.get("/api/health")
    uuid.UUID(r.headers["X-Request-Id"])
    assert r.headers["Cache-Control"] == "no-store"
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["Referrer-Policy"] == "same-origin"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["Permissions-Policy"] == "camera=(), microphone=(), geolocation=()"
    assert r.headers["Content-Security-Policy"].startswith("default-src 'self'; img-src 'self' data:;")
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]
    assert "Strict-Transport-Security" not in r.headers  # plain http deployment
    r2 = client.get("/api/health")
    assert r2.headers["X-Request-Id"] != r.headers["X-Request-Id"]


def test_unknown_api_route_is_an_envelope_404(client: TestClient):
    r = client.get("/api/does-not-exist")
    assert r.status_code == 404
    assert r.json() == {"error": {"code": "not_found", "message": "资源不存在"}}


def test_method_not_allowed_is_an_envelope(client: TestClient):
    r = client.post("/api/health")
    assert r.status_code == 405
    assert r.json()["error"]["code"] == "method_not_allowed"


def test_csrf_header_is_required_on_mutations(raw_client: TestClient):
    r = raw_client.post("/api/health")  # no X-WD-Request → rejected before routing
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "csrf_rejected"
    assert raw_client.get("/api/health").status_code == 200  # GET never needs it
    # the one exemption by path (API.md §1 / 121, deps.CSRF_EXEMPT_PATHS): Apple's form_post lands without the header and with a foreign
    # Origin — the middleware lets exactly that path through (the endpoint itself verifies the signed state); its siblings keep the rule
    from wd.deps import CSRF_EXEMPT_PATHS

    assert CSRF_EXEMPT_PATHS == frozenset({"/api/auth/apple/callback"})
    r = raw_client.post("/api/auth/apple/callback", data={"state": "x", "id_token": "y"}, headers={"Origin": "https://appleid.apple.com"})
    assert r.status_code != 403, r.text
    assert raw_client.post("/api/auth/apple/start", headers={"Origin": "https://appleid.apple.com"}).json()["error"]["code"] == "csrf_rejected"
    assert raw_client.post("/api/auth/apple/callback/x").json()["error"]["code"] == "csrf_rejected"


def test_csrf_origin_must_match_host_or_public_url(client: TestClient):
    assert client.post("/api/health", headers={"Origin": "http://testserver"}).status_code == 405  # passes CSRF, then 405
    assert client.post("/api/health", headers={"Origin": "http://evil.example"}).status_code == 403
    assert client.post("/api/health", headers={"Origin": "null"}).status_code == 403
    assert client.post("/api/health", headers={"X-WD-Request": "yes"}).status_code == 403


def test_csrf_accepts_public_url_and_dev_origins(settings, frozen_clock):
    from dataclasses import replace

    from wd.main import create_app

    cfg = replace(settings, public_url="https://words.example.com", dev=True)
    with TestClient(create_app(cfg, clock=frozen_clock, configure_logs=False)) as c:
        c.headers["X-WD-Request"] = "1"
        assert c.post("/api/health", headers={"Origin": "https://words.example.com"}).status_code == 405
        assert c.post("/api/health", headers={"Origin": "http://localhost:5173"}).status_code == 405
        assert c.post("/api/health", headers={"Origin": "http://localhost:3000"}).status_code == 403
        r = c.get("/api/health")
        assert r.headers["Strict-Transport-Security"].startswith("max-age=")


def test_body_limit(client: TestClient, settings):
    big = "x" * (settings.max_body_bytes + 1)
    r = client.post("/api/health", content=big, headers={"Content-Type": "text/plain"})
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "payload_too_large"


def test_chunked_body_over_the_limit_is_413_too(client: TestClient, settings):
    """No Content-Length (Transfer-Encoding: chunked): the limit trips inside FastAPI's body parser on a JSON endpoint and
    must still answer 413 payload_too_large — not the 400 validation_error FastAPI wraps unknown exceptions into."""
    big = b"x" * (settings.max_body_bytes + 1)
    r = client.post("/api/auth/login", content=iter([big[:65536], big[65536:]]), headers={"Content-Type": "application/json"})
    assert r.status_code == 413, r.text
    body = r.json()
    assert body["error"]["code"] == "payload_too_large" and body["error"]["details"]["max_bytes"] == settings.max_body_bytes
    assert "X-Request-Id" in r.headers
    # a small chunked body is parsed normally (and a truncated one is still the usual 400)
    r = client.post("/api/auth/login", content=iter([b'{"username": "al', b'ice", "password": "nope-nope-1"}']), headers={"Content-Type": "application/json"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_credentials"
    r = client.post("/api/auth/login", content=iter([b'{"username": "al']), headers={"Content-Type": "application/json"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "validation_error"


def test_validation_errors_are_400_envelopes(settings, frozen_clock):
    from fastapi import APIRouter

    from wd.main import create_app

    app = create_app(settings, clock=frozen_clock, configure_logs=False)
    router = APIRouter()

    @router.post("/api/_test/validate")
    def validate(body: LoginRequest):  # pragma: no cover - only reached on valid input
        return {"ok": True}

    app.include_router(router)
    with TestClient(app) as c:
        c.headers["X-WD-Request"] = "1"
        r = c.post("/api/_test/validate", json={"username": "a", "password": "b", "extra": 1})
        assert r.status_code == 400
        body = r.json()
        assert body["error"]["code"] == "validation_error"
        assert "extra" in body["error"]["details"]["fields"]
        r = c.post("/api/_test/validate", content="not json", headers={"Content-Type": "application/json"})
        assert r.status_code == 400 and r.json()["error"]["code"] == "validation_error"


def test_validation_field_messages_are_chinese(client: TestClient):
    """details.fields is shown verbatim by the register form: our validators' own zh text (no `Value error, ` prefix),
    short zh phrases for pydantic's structural errors — never English."""
    import re

    english = re.compile(r"^[A-Za-z0-9 ,'.`_-]+$")
    seen: dict[str, str] = {}
    fields = client.post("/api/auth/register", json={"username": "a"}).json()["error"]["details"]["fields"]
    assert fields == {"username": "用户名为 2–32 个字母、数字、下划线或汉字", "password": "必填"}
    seen.update(fields)
    fields = client.post("/api/auth/register", json={"username": 123, "password": "Passw0rd!xyz", "extra": 1}).json()["error"]["details"]["fields"]
    assert fields == {"username": "类型无效", "extra": "未知字段"}
    seen.update(fields)
    fields = client.post("/api/auth/register", json={"username": "alice", "password": "Passw0rd!xyz", "email": "x" * 250 + "@example.com"}).json()["error"]["details"]["fields"]
    assert fields == {"email": "邮箱格式无效"}
    seen.update(fields)
    assert client.post("/api/auth/register", json={"username": "alice", "password": "Passw0rd!xyz"}).status_code == 201
    fields = client.get("/api/suggestions?status=bogus").json()["error"]["details"]["fields"]  # services.bank.query_model path
    assert fields == {"status": "取值无效"}
    seen.update(fields)
    fields = client.get("/api/screen/next?count=0").json()["error"]["details"]["fields"]
    assert fields == {"count": "超出允许范围"}
    seen.update(fields)
    fields = client.get("/api/screen/next?count=abc").json()["error"]["details"]["fields"]
    assert fields == {"count": "类型无效"}
    seen.update(fields)
    assert not [v for v in seen.values() if english.match(v)], seen


def test_spa_fallback_without_a_built_frontend(client: TestClient):
    r = client.get("/")
    assert r.status_code == 503 and "npm run build" in r.text
    assert client.get("/some/deep/link").status_code == 503
    assert client.get("/media/images/zz/notthere.jpg").status_code == 404
    assert client.get("/media/images/zz/notthere.jpg").json()["error"]["code"] == "not_found"


def test_spa_serves_built_files_with_cache_policy(settings, frozen_clock):
    from dataclasses import replace

    from wd.main import create_app

    dist = settings.data_dir / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>word-Dance</title><div id=root></div>", encoding="utf-8")
    (dist / "assets" / "app-abc123.js").write_text("console.log(1)", encoding="utf-8")
    (dist / "icons").mkdir()  # the installability surface Vite copies from frontend/public (FRONTEND §1)
    (dist / "manifest.webmanifest").write_text('{"name": "word-Dance", "start_url": "/today"}', encoding="utf-8")
    (dist / "icons" / "icon-192.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (dist / "apple-touch-icon.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    cfg = replace(settings, frontend_dist=dist)
    with TestClient(create_app(cfg, clock=frozen_clock, configure_logs=False)) as c:
        r = c.get("/")
        assert r.status_code == 200 and "word-Dance" in r.text and r.headers["Cache-Control"] == "no-cache"
        r = c.get("/today")  # SPA fallback for client-side routes
        assert r.status_code == 200 and "word-Dance" in r.text
        r = c.get("/assets/app-abc123.js")
        assert r.status_code == 200 and r.headers["Cache-Control"] == "public, max-age=31536000, immutable"
        assert "Cache-Control" in r.headers and "X-Content-Type-Options" in r.headers
        r = c.get("/manifest.webmanifest")  # revalidated on every install / update check; Chrome wants the manifest MIME
        assert r.status_code == 200 and r.headers["Cache-Control"] == "no-cache"
        assert r.headers["content-type"].startswith("application/manifest+json")
        r = c.get("/icons/icon-192.png")  # icons live outside /assets on purpose: refreshable, not immutable
        assert r.status_code == 200 and r.headers["Cache-Control"] == "public, max-age=3600" and r.headers["content-type"] == "image/png"
        assert c.get("/apple-touch-icon.png").status_code == 200
        r = c.get("/assets/app-old999.js")  # a chunk of a previous snapshot: 404, never index.html served as a script
        assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
        assert c.get("/../etc/passwd").status_code in (200, 404)  # never escapes dist (resolved path check)
        assert c.get("/api/nothing").status_code == 404


def test_lifespan_migrated_db_and_public_url_guess(client: TestClient, settings):
    c = db.connect(settings.db_path)
    try:
        assert db.current_version(c) == db.list_migration_files()[-1].version  # every shipped file applied by the lifespan
        assert len(db.table_names(c)) == 30  # 0019 adds family_codes, 0020 wechat_tickets
        guess = db.kv_get(c, "public_url_guess")
        assert guess is None or guess.startswith("http://") and guess.endswith(f":{settings.port}")
        assert db.kv_get(c, "seed_version") == hashlib.sha256(settings.seed_path.read_bytes()).hexdigest()  # lifespan imported WD_SEED_PATH via wd.seed (WP1)
        assert c.execute("SELECT COUNT(*) FROM words WHERE source='seed'").fetchone()[0] == 62  # mini seed v2: 60 v1 words + the `color` variant row + the stageless `bookshelf` (PLAN §6 S2)
        assert db.kv_get(c, "worker_lease") is None  # WD_WORKER_ENABLED=0
    finally:
        c.close()


def test_worker_enabled_takes_and_releases_the_lease(settings, frozen_clock):
    from dataclasses import replace

    from wd.jobs import lease
    from wd.main import create_app

    cfg = replace(settings, worker_enabled=True)
    app = create_app(cfg, clock=frozen_clock, configure_logs=False)
    with TestClient(app) as c:
        conn = db.connect(cfg.db_path)
        try:
            held = lease.is_live(conn, "2026-10-14T00:00:00Z")
            assert held is not None and held["instance"] == app.state.lease_instance
            assert held["expires_at"] == "2026-10-14T00:01:30Z"
        finally:
            conn.close()
        keeper, *workers = app.state.threads
        assert isinstance(keeper, lease.LeaseKeeper) and len(workers) >= 3  # claude-N, io-1, scheduler
        assert all(t.lease_lost is keeper.lost and not t.fenced for t in workers)  # every thread is fenced by the keeper's flag
        assert c.get("/api/health").status_code == 200
    conn = db.connect(cfg.db_path)
    try:
        assert lease.read(conn) is None  # released on shutdown
    finally:
        conn.close()


def test_second_instance_runs_without_workers_while_lease_is_live(settings, frozen_clock):
    from dataclasses import replace

    from wd.jobs import lease
    from wd.main import create_app

    cfg = replace(settings, worker_enabled=True)
    conn = db.connect(cfg.db_path)
    db.run_migrations(conn)
    assert lease.acquire(conn, "other-host:1:deadbeef", frozen_clock.now_utc())
    conn.close()
    app = create_app(cfg, clock=frozen_clock, configure_logs=False)
    with TestClient(app) as c:
        assert app.state.lease_instance is None and app.state.threads == []
        assert c.get("/api/health").status_code == 200
    conn = db.connect(cfg.db_path)
    try:
        assert lease.read(conn)["instance"] == "other-host:1:deadbeef"  # untouched
    finally:
        conn.close()


def test_restarted_instance_takes_over_once_the_stale_lease_expires(settings, frozen_clock):
    """A crashed predecessor (SIGKILL/OOM) leaves a live lease for up to 90 s while systemd restarts the unit after 5 s: the
    successor must keep retrying and take over — sweeping the dead boot's running jobs — instead of never pushing again."""
    from dataclasses import replace

    from wd.jobs import lease, queue
    from wd.main import create_app

    cfg = replace(settings, worker_enabled=True)
    conn = db.connect(cfg.db_path)
    db.run_migrations(conn)
    assert lease.acquire(conn, "box:4242:deadbeef", frozen_clock.now_utc())  # expires_at = now + 90 s
    job_id = queue.enqueue(conn, "generate_content", {"word_id": 1}, dedupe_key="content:1", run_after="2030-01-01T00:00:00Z")
    with db.tx(conn):
        conn.execute("UPDATE jobs SET status = 'running', locked_by = 'claude-1:deadbeef', locked_at = '2026-10-14T00:00:00Z' WHERE id = ?", (job_id,))
    conn.close()
    app = create_app(cfg, clock=frozen_clock, configure_logs=False)
    with TestClient(app) as c:
        waiter = app.state.lease_waiter
        assert waiter is not None and waiter.is_alive() and waiter.name == "lease-waiter"
        assert app.state.lease_instance is None and app.state.threads == []
        assert waiter.try_acquire() is False  # the predecessor's lease is still live: keep waiting
        frozen_clock.advance(seconds=91)
        assert waiter.try_acquire() is True
        assert app.state.lease_instance is not None
        assert {"lease-keeper", "scheduler", "claude-1", "io-1"} <= {t.name for t in app.state.threads}
        conn = db.connect(cfg.db_path)
        try:
            assert lease.read(conn)["instance"] == app.state.lease_instance
            assert conn.execute("SELECT status, locked_by FROM jobs WHERE id = ?", (job_id,)).fetchone()[0] == "queued"  # the stale sweep ran
        finally:
            conn.close()
        assert c.get("/api/health").status_code == 200
    conn = db.connect(cfg.db_path)
    try:
        assert lease.read(conn) is None  # released on shutdown like a lease taken at startup
    finally:
        conn.close()
    assert app.state.lease_waiter is None and app.state.threads == []


def test_refuses_multiple_uvicorn_workers(settings, frozen_clock, monkeypatch):
    import pytest

    from wd.main import create_app

    monkeypatch.setenv("WEB_CONCURRENCY", "4")
    with pytest.raises(SystemExit):
        create_app(settings, clock=frozen_clock, configure_logs=False)
    monkeypatch.delenv("WEB_CONCURRENCY")
    monkeypatch.setattr("sys.argv", ["uvicorn", "wd.main:create_app", "--factory", "--workers", "2"])
    with pytest.raises(SystemExit):
        create_app(settings, clock=frozen_clock, configure_logs=False)


def test_request_log_line_is_json_when_configured(settings, frozen_clock, capsys):
    import io
    import logging

    from dataclasses import replace

    from wd import logging_setup
    from wd.main import create_app

    buf = io.StringIO()
    cfg = replace(settings, log_level="INFO", log_format="json")
    monkey_root = logging.getLogger()
    saved = list(monkey_root.handlers)
    saved_flag = logging_setup._CONFIGURED
    logging_setup._CONFIGURED = False
    for h in saved:
        monkey_root.removeHandler(h)
    try:
        logging_setup.configure_logging(cfg, stream=buf)
        with TestClient(create_app(cfg, clock=frozen_clock, configure_logs=False)) as c:
            c.get("/api/does-not-exist")
        lines = [json.loads(l) for l in buf.getvalue().splitlines() if l.startswith("{")]
        req = [l for l in lines if l.get("msg") == "request"]
        assert req and req[-1]["path"] == "/api/does-not-exist" and req[-1]["status"] == 404 and "request_id" in req[-1]
    finally:
        for h in list(monkey_root.handlers):
            monkey_root.removeHandler(h)
        for h in saved:
            monkey_root.addHandler(h)
        logging_setup._CONFIGURED = saved_flag
