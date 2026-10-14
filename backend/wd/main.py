"""ASGI application factory (Phase 0 — TASKS.md P0 step 6, DESIGN §10, DEPLOY §3).

``create_app()`` wires: the health router + every (stub) router, the static SPA (``frontend/dist`` with an
SPA fallback, ``/assets`` immutable), one pure-ASGI middleware (``X-Request-Id``, security headers,
``Cache-Control: no-store`` on ``/api``, body limit ``WD_MAX_BODY_BYTES``, the API.md §1 CSRF rule, one JSON
log line per request) and the lifespan:

    migrate → seed import when kv.seed_version ≠ sha256(WD_SEED_PATH) (wd.seed late import; warn-and-continue
    while WP1 has not landed or the file is missing) → kv.public_url_guess → registry.load_handlers() →
    take kv.worker_lease and start worker/scheduler threads when WD_WORKER_ENABLED (late imports; skipped
    while the classes do not exist yet).

It refuses to run under more than one uvicorn worker (the single-process invariant, DESIGN §0.2).
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import os
import socket
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from . import __version__, db
from .clock import Clock, SystemClock
from .config import Settings, ensure_dirs
from .delivery.mailer import mailer_from_settings
from .deps import csrf_violation
from .errors import ApiError, error_response, install_handlers
from .jobs import lease, queue, registry
from .jobs.registry import JobContext
from .logging_setup import configure_logging
from .routers import (
    account,
    admin_ops,
    admin_reports,
    admin_users,
    auth,
    bank,
    health,
    history,
    media,
    onboarding,
    screen,
    settings as settings_router,
    suggestions,
    today,
    vocab,
    words,
)

log = logging.getLogger("wd.main")
http_log = logging.getLogger("wd.http")

ROUTERS = (
    health,
    auth,
    account,
    onboarding,
    settings_router,
    vocab,
    words,
    screen,
    bank,
    suggestions,
    today,
    history,
    media,
    admin_users,
    admin_ops,
    admin_reports,
)

# DESIGN §10 "Headers" row; HSTS is added only when the deployment is https
SECURITY_HEADERS: dict[str, str] = {
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}
HSTS_VALUE = "max-age=31536000; includeSubDomains"

# (module, class, role) — constructed as Cls(ctx) and driven through start()/stop()/join() (interfaces.BackgroundThread)
THREAD_CLASSES: tuple[tuple[str, str, str], ...] = (
    ("wd.jobs.worker", "ClaudeWorker", "claude"),
    ("wd.jobs.worker", "IoWorker", "io"),
    ("wd.jobs.scheduler", "Scheduler", "scheduler"),
)
THREAD_JOIN_SECONDS = 250.0  # < systemd TimeoutStopSec=300 (an in-flight claude call may take up to 240 s)


class BodyTooLarge(Exception):
    pass


class WdMiddleware:
    """Request id, security headers, cache policy, body limit, CSRF rule and the per-request log line."""

    def __init__(self, app: ASGIApp, *, appstate: Any):
        self.app = app
        self.state = appstate

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        cfg: Settings = self.state.settings
        request_id = str(uuid.uuid4())
        state = scope.setdefault("state", {})
        state["request_id"] = request_id
        path: str = scope.get("path", "")
        method: str = scope.get("method", "GET")
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        is_api = path == "/api" or path.startswith("/api/")
        is_https = scope.get("scheme") == "https" or (cfg.trust_proxy and headers.get("x-forwarded-proto", "").split(",")[0].strip() == "https")
        started = time.perf_counter()
        status_seen: dict[str, int | None] = {"status": None}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_seen["status"] = message["status"]
                h = MutableHeaders(scope=message)
                h["X-Request-Id"] = request_id
                for name, value in SECURITY_HEADERS.items():
                    if name not in h:
                        h[name] = value
                if is_https or cfg.public_url_is_https:
                    h.setdefault("Strict-Transport-Security", HSTS_VALUE)
                if is_api:
                    h["Cache-Control"] = "no-store"
            await send(message)

        async def respond(response) -> None:
            await response(scope, receive, send_wrapper)

        try:
            content_length = headers.get("content-length")
            if content_length and content_length.isdigit() and int(content_length) > cfg.max_body_bytes:
                await respond(error_response("payload_too_large", details={"max_bytes": cfg.max_body_bytes}))
                return
            if is_api:
                reason = csrf_violation(method, scope.get("scheme", "http"), headers, cfg)
                if reason:
                    await respond(error_response("csrf_rejected", details={"reason": reason}))
                    return

            received = 0

            async def receive_wrapper() -> Message:
                nonlocal received
                message = await receive()
                if message["type"] == "http.request":
                    received += len(message.get("body", b""))
                    if received > cfg.max_body_bytes:
                        raise BodyTooLarge()
                return message

            try:
                await self.app(scope, receive_wrapper, send_wrapper)
            except BodyTooLarge:
                if status_seen["status"] is None:
                    await respond(error_response("payload_too_large", details={"max_bytes": cfg.max_body_bytes}))
                else:
                    raise
        finally:
            duration_ms = int((time.perf_counter() - started) * 1000)
            level = logging.DEBUG if path == "/api/health" else logging.INFO
            http_log.log(
                level,
                "request",
                extra={
                    "request_id": request_id,
                    "method": method,
                    "path": path,
                    "status": status_seen["status"],
                    "duration_ms": duration_ms,
                    "user_id": state.get("user_id"),
                },
            )


# ------------------------------------------------------------------------------------------- SPA
def _mount_spa(app: FastAPI, cfg: Settings) -> None:
    dist = cfg.frontend_dist

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path == "api" or path.startswith("api/") or path == "media" or path.startswith("media/"):
            raise ApiError("not_found")
        if path:
            candidate = (dist / path).resolve()
            try:
                candidate.relative_to(dist.resolve())
            except ValueError:
                raise ApiError("not_found") from None
            if candidate.is_file():
                if path.startswith("assets/"):
                    cache = "public, max-age=31536000, immutable"
                else:
                    cache = "public, max-age=3600"
                return FileResponse(candidate, headers={"Cache-Control": cache})
        index = dist / "index.html"
        if index.is_file():
            return FileResponse(index, headers={"Cache-Control": "no-cache"})
        return HTMLResponse(
            "<!doctype html><meta charset='utf-8'><title>word-Dance</title>"
            "<p>前端尚未构建 — run <code>cd frontend &amp;&amp; npm ci &amp;&amp; npm run build</code>; the API is up at <code>/api/health</code>.</p>",
            status_code=503,
            headers={"Cache-Control": "no-store"},
        )


# -------------------------------------------------------------------------------------- startup
def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def first_non_loopback_ipv4() -> str | None:
    """Python equivalent of ``hostname -I | awk '{print $1}'`` (DESIGN §6.5); None when the host has none."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("10.255.255.255", 1))  # no packet is sent for UDP connect; picks the default-route interface
            ip = s.getsockname()[0]
        finally:
            s.close()
        if ip and not ip.startswith("127."):
            return ip
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip and not ip.startswith("127."):
                return ip
    except OSError:
        pass
    return None


def seed_check(conn, cfg: Settings) -> None:
    """Import the seed when ``kv.seed_version`` differs from the sha256 of ``WD_SEED_PATH`` (warn-and-continue otherwise)."""
    path = cfg.seed_path
    if not path.is_file():
        log.warning("seed file %s does not exist; skipping the seed check (set WD_SEED_PATH or run `wd import-seed --file`)", path)
        return
    digest = sha256_file(path)
    if db.kv_get(conn, "seed_version") == digest:
        return
    try:
        from .seed import import_seed  # type: ignore[import-not-found]  # WP1
    except ModuleNotFoundError as e:
        if e.name == "wd.seed":
            log.warning("wd.seed is not available yet; seed %s not imported", path.name)
            return
        raise
    log.info("seed version changed; importing %s", path, extra={"event": "seed_import"})
    import_seed(conn, str(path))
    if db.kv_get(conn, "seed_version") != digest:  # the importer records it (WP1); be defensive
        db.kv_set(conn, "seed_version", digest)


def _late_class(module: str, name: str):
    import importlib

    try:
        mod = importlib.import_module(module)
    except ModuleNotFoundError as e:
        if e.name == module or module.startswith((e.name or "") + "."):
            return None
        raise
    return getattr(mod, name, None)


def start_background(app: FastAPI, conn) -> None:
    """Take the worker lease and start the lease keeper + worker/scheduler threads (those that exist)."""
    cfg: Settings = app.state.settings
    clock: Clock = app.state.clock
    boot_id: str = app.state.boot_id
    instance = f"{socket.gethostname()}:{os.getpid()}:{boot_id[:8]}"
    if not lease.acquire(conn, instance, clock.now_utc()):
        holder = lease.read(conn)
        log.warning("another word-Dance instance holds the worker lease (%s); this process serves requests only", holder, extra={"event": "lease_busy"})
        return
    app.state.lease_instance = instance
    swept = queue.requeue_stale(conn, boot_id, now=clock.now_utc().strftime("%Y-%m-%dT%H:%M:%SZ"))
    if swept:
        log.info("requeued %d stale running job(s) from a previous boot", swept, extra={"event": "stale_sweep"})

    def connect():
        return db.connect(cfg.db_path)

    threads: list[Any] = []
    keeper = lease.LeaseKeeper(connect, instance, clock.now_utc)
    keeper.start()
    threads.append(keeper)
    ctx = JobContext(db=connect, cfg=cfg, clock=clock, enqueue=queue.enqueue, log=logging.getLogger("wd.jobs"), worker_id="main", boot_id=boot_id)
    for module, cls_name, role in THREAD_CLASSES:
        cls = _late_class(module, cls_name)
        if cls is None:
            log.info("%s.%s is not available yet; not started", module, cls_name)
            continue
        count = cfg.ai_concurrency if role == "claude" else 1
        for i in range(count):
            worker_id = "scheduler" if role == "scheduler" else f"{role}-{i + 1}"
            thread = cls(ctx.for_worker(worker_id))
            thread.start()
            threads.append(thread)
            log.info("started %s (%s)", cls_name, worker_id, extra={"worker": worker_id})
    app.state.threads = threads


def stop_background(app: FastAPI) -> None:
    threads: list[Any] = list(getattr(app.state, "threads", []) or [])
    for t in threads:
        stop = getattr(t, "stop", None)
        if callable(stop):
            try:
                stop()
            except Exception:  # pragma: no cover - defensive
                log.exception("stop() failed for %r", t)
    deadline = time.monotonic() + THREAD_JOIN_SECONDS
    for t in threads:
        remaining = max(0.1, deadline - time.monotonic())
        join = getattr(t, "join", None)
        if callable(join):
            join(timeout=remaining)
    app.state.threads = []
    instance = getattr(app.state, "lease_instance", None)
    if instance:
        try:
            conn = db.connect(app.state.settings.db_path)
            try:
                lease.release(conn, instance)
            finally:
                conn.close()
        except Exception:  # pragma: no cover - the lease simply expires
            log.exception("could not release the worker lease")
        app.state.lease_instance = None


def startup(app: FastAPI) -> None:
    cfg: Settings = app.state.settings
    ensure_dirs(cfg)
    conn = db.connect(cfg.db_path)
    try:
        result = db.run_migrations(conn, pre_hook=db.backup_pre_hook())
        for version, name in result.applied:
            log.info("applied migration %04d_%s", version, name, extra={"event": "migration"})
        seed_check(conn, cfg)
        guess = first_non_loopback_ipv4()
        if guess:
            db.kv_set(conn, "public_url_guess", f"http://{guess}:{cfg.port}")
        registry.load_handlers()
        if cfg.worker_enabled:
            start_background(app, conn)
        else:
            log.info("WD_WORKER_ENABLED=0: no worker/scheduler threads")
    finally:
        conn.close()
    log.info("word-Dance %s ready (data dir %s)", __version__, cfg.data_dir, extra={"event": "startup"})


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    startup(app)
    try:
        yield
    finally:
        stop_background(app)


def assert_single_worker() -> None:
    """Refuse ``--workers N`` / ``WEB_CONCURRENCY`` > 1: the lease, the scheduler and SQLite assume one process."""
    wc = os.environ.get("WEB_CONCURRENCY", "").strip()
    if wc.isdigit() and int(wc) > 1:
        raise SystemExit(f"word-Dance must run with exactly one uvicorn worker (WEB_CONCURRENCY={wc})")
    argv = sys.argv
    for i, arg in enumerate(argv):
        value = None
        if arg in ("--workers", "-w") and i + 1 < len(argv):
            value = argv[i + 1]
        elif arg.startswith("--workers="):
            value = arg.split("=", 1)[1]
        if value is not None and value.strip().isdigit() and int(value) != 1:
            raise SystemExit(f"word-Dance must run with exactly one uvicorn worker (got --workers {value})")


def create_app(settings: Settings | None = None, *, clock: Clock | None = None, configure_logs: bool = True) -> FastAPI:
    """Build the application. ``settings``/``clock`` overrides exist for tests (frozen clock, temp data dir)."""
    cfg = settings or Settings.from_env()
    assert_single_worker()
    if configure_logs:
        configure_logging(cfg)
    app = FastAPI(
        title="word-Dance",
        version=__version__,
        docs_url="/api/docs" if cfg.dev else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if cfg.dev else None,
        lifespan=lifespan,
    )
    app.state.settings = cfg
    app.state.clock = clock or SystemClock()
    app.state.boot_id = uuid.uuid4().hex
    app.state.threads = []
    app.state.lease_instance = None
    app.state.mailer = mailer_from_settings(cfg)
    install_handlers(app)
    for module in ROUTERS:
        app.include_router(module.router)
    _mount_spa(app, cfg)
    app.add_middleware(WdMiddleware, appstate=app.state)
    return app
