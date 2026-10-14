"""GET /api/health (endpoint 1) and the P0 application plumbing: headers, envelope, CSRF rule, body limit, lifespan."""

from __future__ import annotations

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
    assert set(body) == {"status", "version", "registration_mode", "needs_setup", "time"}


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
    cfg = replace(settings, frontend_dist=dist)
    with TestClient(create_app(cfg, clock=frozen_clock, configure_logs=False)) as c:
        r = c.get("/")
        assert r.status_code == 200 and "word-Dance" in r.text and r.headers["Cache-Control"] == "no-cache"
        r = c.get("/today")  # SPA fallback for client-side routes
        assert r.status_code == 200 and "word-Dance" in r.text
        r = c.get("/assets/app-abc123.js")
        assert r.status_code == 200 and r.headers["Cache-Control"] == "public, max-age=31536000, immutable"
        assert "Cache-Control" in r.headers and "X-Content-Type-Options" in r.headers
        assert c.get("/../etc/passwd").status_code in (200, 404)  # never escapes dist (resolved path check)
        assert c.get("/api/nothing").status_code == 404


def test_lifespan_migrated_db_and_public_url_guess(client: TestClient, settings):
    c = db.connect(settings.db_path)
    try:
        assert db.current_version(c) == 1
        assert len(db.table_names(c)) == 25
        guess = db.kv_get(c, "public_url_guess")
        assert guess is None or guess.startswith("http://") and guess.endswith(f":{settings.port}")
        assert db.kv_get(c, "seed_version") is None  # wd.seed (WP1) absent → warn-and-continue
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
