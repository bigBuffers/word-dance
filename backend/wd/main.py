"""ASGI application factory (Phase 0 — TASKS.md P0 step 6, DESIGN §10, DEPLOY §3).

``create_app()`` wires: the health router + every (stub) router, the static SPA (``frontend/dist`` with an
SPA fallback, ``/assets`` immutable), one pure-ASGI middleware (``X-Request-Id``, security headers,
``Cache-Control: no-store`` on ``/api``, body limit ``WD_MAX_BODY_BYTES``, the API.md §1 CSRF rule, one JSON
log line per request) and the lifespan:

    migrate (with the pre-migrate snapshot hook) → seed import when kv.seed_version ≠ content sha256 of WD_SEED_PATH (never fatal)
    (warn-and-continue when the file is missing) → learn_order.ensure_current (the learning-order keys words.learn_rank:
    stored vs computed, changed rows only; never fatal — a `learn_order_failed` event and the lists serve the fail-soft order)
    → dance.backfill_corrected (word_dances.corrected rows 0017 left NULL; never fatal) → kv.public_url_guess → registry.load_handlers() → take kv.worker_lease and start the Claude worker(s), the I/O worker
    and the scheduler when WD_WORKER_ENABLED.

It refuses to run under more than one uvicorn worker (the single-process invariant, DESIGN §0.2).
"""

from __future__ import annotations

import contextlib
import html
import json
import logging
import os
import socket
import sqlite3
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from starlette.datastructures import MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from . import __version__, audio, dance, db, security
from .ai import ledger
from .clock import Clock, SystemClock, now_iso
from .config import Settings, ensure_dirs
from .delivery.mailer import mailer_from_settings
from .delivery.sms import sms_sender_from_settings
from .deps import SESSION_COOKIE, csrf_violation
from .errors import ApiError, error_response, install_handlers
from .jobs import lease, queue, registry
from .jobs.registry import JobContext
from .jobs.scheduler import Scheduler
from .jobs.worker import ClaudeWorker, IoWorker
from .logging_setup import configure_logging
from .routers import (
    account,
    admin_ops,
    admin_reports,
    admin_users,
    audio as audio_router,
    auth,
    auth_codes,
    auth_family,
    bank,
    demo,
    guardian,
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
from .seed import import_seed, seed_digest
from .services import learn_order

log = logging.getLogger("wd.main")
http_log = logging.getLogger("wd.http")

ROUTERS = (
    health,
    auth,
    auth_codes,
    account,
    guardian,  # 1-B: /api/guardian/* (94–103)
    auth_family,  # 1-B: /api/auth/switch/*, /api/auth/child-login (104–107)
    demo,
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
    audio_router,
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

# (class, role) — constructed as Cls(ctx) and driven through start()/stop()/join() (interfaces.BackgroundThread);
# `claude` is started WD_AI_CONCURRENCY times, the others once
THREAD_CLASSES: tuple[tuple[type, str], ...] = (
    (ClaudeWorker, "claude"),
    (IoWorker, "io"),
    (Scheduler, "scheduler"),
)
THREAD_JOIN_SECONDS = 250.0  # < systemd TimeoutStopSec=300 (an in-flight claude call may take up to 240 s)
LEASE_RETRY_SECONDS = float(lease.RENEW_SECONDS)  # how often a lease-less instance retries lease.acquire


class BodyTooLarge(StarletteHTTPException):
    """Raised by the body-limit ``receive`` wrapper once a chunked body (no ``Content-Length``) exceeds ``WD_MAX_BODY_BYTES``.

    An ``HTTPException`` on purpose: FastAPI's body parser re-raises those untouched and wraps any other exception into a
    400 「请求参数无效」, so a plain ``Exception`` here never reached the 413 handler below; ``errors._http`` passes the
    envelope in ``detail`` through at 413 ``payload_too_large`` exactly like the ``Content-Length`` pre-check.
    """

    def __init__(self, max_bytes: int) -> None:
        super().__init__(status_code=413, detail=ApiError("payload_too_large", details={"max_bytes": int(max_bytes)}).to_body())


def session_cookie_header(scope: Scope, token: str, cfg: Settings, *, max_age_s: int | None = None) -> str:
    """The exact ``Set-Cookie`` value login/register send (``security.set_session_cookie``), for the sliding re-issue; ``max_age_s`` is the
    seconds left on the session row (``deps.current_user`` never shortens a session, so a 90-day child-device cookie keeps its horizon)."""
    tmp = Response()
    security.set_session_cookie(tmp, token, cfg, secure=security.cookie_secure(Request(scope), cfg), max_age_s=max_age_s)
    return tmp.headers["set-cookie"]


def _sets_session_cookie(message: Message) -> bool:
    prefix = f"{SESSION_COOKIE}=".encode("latin-1")
    return any(k.lower() == b"set-cookie" and v.lstrip().lower().startswith(prefix) for k, v in message.get("headers", []))


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
                token = state.get("reissue_session_token")  # deps.current_user slid the expiry: re-send the cookie
                if token and not _sets_session_cookie(message):  # unless the route itself set/cleared it (logout, delete, a switch)
                    h.append("Set-Cookie", session_cookie_header(scope, str(token), cfg, max_age_s=state.get("reissue_session_max_age_s")))
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
                        raise BodyTooLarge(cfg.max_body_bytes)
                return message

            try:
                await self.app(scope, receive_wrapper, send_wrapper)
            except BodyTooLarge:  # a consumer outside FastAPI's exception middleware read the body
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
    # Settings.from_env resolved WD_FRONTEND_DIST, so an installed service serves the snapshot its `$WD_DATA_DIR/frontend`
    # symlink pointed at when it started (DEPLOY §1/§10): install.sh's later publish is picked up at the next restart.
    dist = cfg.frontend_dist
    if not (dist / "index.html").is_file():
        log.warning(
            "frontend not found: %s has no index.html — installed service: deploy/install.sh publishes it under "
            "$WD_DATA_DIR/frontend (restart afterwards); dev checkout: cd frontend && npm ci && npm run build. "
            "The SPA answers 503 until then",
            dist,
        )

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
                elif path in ("sw.js", "registerSW.js", "manifest.webmanifest"):
                    cache = "no-cache"  # an install / update check must see a new manifest or service worker at once (FRONTEND §1)
                else:
                    cache = "public, max-age=3600"  # icons and the other root files of the snapshot: refreshable within the hour
                return FileResponse(candidate, headers={"Cache-Control": cache})
            if path.startswith("assets/"):
                raise ApiError("not_found")  # a hashed chunk of a previous snapshot is a 404, never index.html with status 200
        index = dist / "index.html"
        if index.is_file():
            return FileResponse(index, headers={"Cache-Control": "no-cache"})
        return HTMLResponse(
            "<!doctype html><meta charset='utf-8'><title>word-Dance</title>"
            f"<p>前端尚未构建 — <code>WD_FRONTEND_DIST={html.escape(str(dist))}</code> has no <code>index.html</code>. "
            "Installed service: run <code>deploy/install.sh</code> (it publishes the SPA under <code>$WD_DATA_DIR/frontend</code>) and restart; "
            "dev checkout: <code>cd frontend &amp;&amp; npm ci &amp;&amp; npm run build</code>. The API is up at <code>/api/health</code>.</p>",
            status_code=503,
            headers={"Cache-Control": "no-store"},
        )


# -------------------------------------------------------------------------------------- startup
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
    """Import the seed when ``kv.seed_version`` differs from the content sha256 of ``WD_SEED_PATH``; never fails startup.

    The comparison uses :func:`wd.seed.seed_digest` (the decompressed content, PLAN R-9), so a seed re-packed by another
    gzip implementation does not trigger a re-import, while migration 0011's ``DELETE FROM kv WHERE key='seed_version'``
    still forces one. A corrupt or incompatible seed must not take the service down (WORD_LIBRARY_CURATION §1.2: a
    failing import used to put ``wd serve`` into a restart loop): every exception is logged with its traceback, recorded
    as ``system_events('seed_import_failed')`` for the admin page, and startup continues with the vocabulary already in
    the database. ``import_seed`` rolled its own transaction back, so ``kv.seed_version`` is unchanged and the next start
    retries.
    """
    path = cfg.seed_path
    if not path.is_file():
        log.warning("seed file %s does not exist; skipping the seed check (set WD_SEED_PATH or run `wd import-seed --file`)", path)
        return
    try:
        digest = seed_digest(path)
        if db.kv_get(conn, "seed_version") == digest:
            return
        log.info("seed version changed; importing %s", path, extra={"event": "seed_import"})
        import_seed(conn, str(path))
    except Exception as e:  # noqa: BLE001 - a bad seed must not take the service down (WORD_LIBRARY_CURATION §1.2, PLAN R-9)
        log.exception("seed import failed; continuing with the current vocabulary", extra={"event": "seed_import_failed"})
        with db.maybe_tx(conn):
            conn.execute(
                "INSERT INTO system_events(kind, detail_json, created_at) VALUES ('seed_import_failed', ?, ?)",
                (json.dumps({"file": path.name, "error": f"{type(e).__name__}: {e}"[:500]}), now_iso()),
            )


class LeaseWaiter(threading.Thread):
    """Retries :func:`lease.acquire` every ``interval_s`` while another instance holds ``kv.worker_lease``.

    A crashed ``wd serve`` (SIGKILL, OOM, power loss) cannot release its lease, which then outlives it by up to
    ``lease.TTL_SECONDS`` (90 s) while systemd restarts the unit after 5 s — so the successor *always* meets a live lease.
    Instead of giving up for good it waits here, serving requests meanwhile, and on success runs ``on_acquired`` once
    (the stale-job sweep + worker/scheduler start) and exits. A genuinely live second instance just keeps waiting.
    """

    def __init__(
        self,
        connect: Callable[[], sqlite3.Connection],
        instance: str,
        now_utc: Callable[[], Any],
        on_acquired: Callable[[], None],
        interval_s: float | None = None,
    ):
        super().__init__(name="lease-waiter", daemon=True)
        self._connect = connect
        self._instance = instance
        self._now = now_utc
        self._on_acquired = on_acquired
        self._interval = LEASE_RETRY_SECONDS if interval_s is None else interval_s
        self._stop_event = threading.Event()  # not `_stop`: threading.Thread uses that name internally
        self.acquired = threading.Event()

    def run(self) -> None:
        while not self._stop_event.wait(self._interval):
            if self.try_acquire():
                return

    def try_acquire(self) -> bool:
        """One attempt (the loop body; tests call it directly after advancing the clock)."""
        if self.acquired.is_set():
            return True
        try:
            conn = self._connect()
            try:
                ok = lease.acquire(conn, self._instance, self._now())
            finally:
                conn.close()
        except sqlite3.Error as e:  # transient; try again next round
            log.warning("lease acquisition failed: %s", e)
            return False
        if not ok:
            return False
        self.acquired.set()
        self._on_acquired()
        return True

    def stop(self) -> None:
        self._stop_event.set()


def _start_workers(app: FastAPI, conn, instance: str) -> None:
    """The post-acquire half of :func:`start_background`: stale-job sweep, lease keeper, worker/scheduler threads."""
    cfg: Settings = app.state.settings
    clock: Clock = app.state.clock
    boot_id: str = app.state.boot_id
    app.state.lease_instance = instance
    start_iso = clock.now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")
    swept = queue.requeue_stale(conn, boot_id, now=start_iso)
    if swept:
        log.info("requeued %d stale running job(s) from a previous boot", swept, extra={"event": "stale_sweep"})
    orphans = ledger.close_orphans(conn, now=start_iso)  # a call this process has not started cannot be running: stop its reservation
    if orphans:
        log.info("closed %d ai_calls row(s) left running by a previous boot", orphans, extra={"event": "ledger_sweep"})

    def connect():
        return db.connect(cfg.db_path)

    threads: list[Any] = list(getattr(app.state, "threads", []) or [])
    keeper = lease.LeaseKeeper(connect, instance, clock.now_utc)
    keeper.start()
    threads.append(keeper)
    ctx = JobContext(db=connect, cfg=cfg, clock=clock, enqueue=queue.enqueue, log=logging.getLogger("wd.jobs"), worker_id="main", boot_id=boot_id)
    for cls, role in THREAD_CLASSES:
        count = cfg.ai_concurrency if role == "claude" else 1
        for i in range(count):
            worker_id = "scheduler" if role == "scheduler" else f"{role}-{i + 1}"
            thread = cls(ctx.for_worker(worker_id), lease_lost=keeper.lost)  # fenced while another instance holds the lease
            thread.start()
            threads.append(thread)
            log.info("started %s (%s)", cls.__name__, worker_id, extra={"worker": worker_id})
    app.state.threads = threads


def start_background(app: FastAPI, conn) -> None:
    """Take the worker lease and start the lease keeper + worker/scheduler threads (those that exist).

    When another instance holds the lease this process serves requests only — but keeps retrying through a
    :class:`LeaseWaiter` (``app.state.lease_waiter``), so an auto-restarted service takes over within
    ``lease.TTL_SECONDS + LEASE_RETRY_SECONDS`` of its predecessor's crash instead of never pushing again.
    """
    cfg: Settings = app.state.settings
    clock: Clock = app.state.clock
    boot_id: str = app.state.boot_id
    instance = f"{socket.gethostname()}:{os.getpid()}:{boot_id[:8]}"
    if lease.acquire(conn, instance, clock.now_utc()):
        _start_workers(app, conn, instance)
        return
    holder = lease.read(conn)
    log.warning(
        "another word-Dance instance holds the worker lease (%s); this process serves requests only and retries every %d s",
        holder,
        int(LEASE_RETRY_SECONDS),
        extra={"event": "lease_busy"},
    )

    def connect():
        return db.connect(cfg.db_path)

    def on_acquired() -> None:
        c = connect()
        try:
            _start_workers(app, c, instance)
        finally:
            c.close()
        log.info("took over the worker lease (previous holder %s)", holder, extra={"event": "lease_acquired"})

    waiter = LeaseWaiter(connect, instance, clock.now_utc, on_acquired)
    waiter.start()
    app.state.lease_waiter = waiter


def stop_background(app: FastAPI) -> None:
    warm_up = getattr(app.state, "audio_warm_up", None)
    if warm_up is not None:  # a `say` probe still running must not outlive the process (nor a test's fixtures)
        warm_up.join(timeout=audio.WARM_UP_JOIN_S)
        app.state.audio_warm_up = None
    waiter = getattr(app.state, "lease_waiter", None)
    if waiter is not None:  # first, so a takeover in flight finishes before the thread list is read
        waiter.stop()
        waiter.join(timeout=THREAD_JOIN_SECONDS)
        app.state.lease_waiter = None
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
        learn_order.ensure_current(conn, now=now_iso(app.state.clock))  # fills / repairs words.learn_rank (0014); never raises
        try:
            filled = dance.backfill_corrected(conn)  # word_dances.corrected: every row right after 0017 (the file only adds the column) and any row written without the flag; never fatal
            if filled:
                log.info("word_dances.corrected backfilled for %d row(s)", filled, extra={"event": "dance_corrected_backfill"})
        except Exception:  # noqa: BLE001 — like seed_check: no data shape may stop the service; the NULL rows serve their stored chunks
            log.exception("word_dances.corrected backfill failed; stored chunks keep serving until the next start")
        guess = first_non_loopback_ipv4()
        if guess:
            db.kv_set(conn, "public_url_guess", f"http://{guess}:{cfg.port}")
        registry.load_handlers()
        if cfg.audio_provider_effective == "cache":
            log.info("pronunciation clips: provider cache — a read-only mirror of say clips (%s)", cfg.audio_cache_voices, extra={"event": "audio_provider"})
        else:
            log.info("pronunciation clips: provider %s (WD_AUDIO_PROVIDER=%s, cache cap %d MB)", cfg.audio_provider_effective, cfg.audio_provider, cfg.audio_cache_mb, extra={"event": "audio_provider"})
        app.state.audio_warm_up = audio.warm_up_async(cfg)  # `say -v ?` and the voice probes (1–3 s) on a daemon thread: before the first tap, never on its request
        log.info(
            "sign-in channels: sms %s, mail %s, captcha %s, registration %s",
            cfg.sms_provider,
            cfg.mail_provider if cfg.email_configured else "off",
            cfg.captcha,
            cfg.registration_mode,
            extra={"event": "sms_provider"},
        )
        log.info(
            "AI provider mode %s (fallback: %s)",
            cfg.ai_provider,
            f"{cfg.ai_fallback_kind} {cfg.ai_fallback_model} for {','.join(cfg.ai_fallback_kinds)}" if cfg.fallback_configured else "not configured",
            extra={"event": "ai_provider_mode"},
        )
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
    app.state.lease_waiter = None
    app.state.mailer = mailer_from_settings(cfg)
    app.state.sms = sms_sender_from_settings(cfg)  # None while WD_SMS_PROVIDER=off → 409 sms_unconfigured (API.md 80 / 85); tests swap in RecordingSmsSender
    if cfg.smoke_mock_http:  # WD_SMOKE_MOCK_HTTP=1 (dev only): fixture-backed httpx transport, nothing leaves the box
        from . import smoke_mock

        smoke_mock.install_if_enabled(cfg)
    install_handlers(app)
    for module in ROUTERS:
        app.include_router(module.router)
    _mount_spa(app, cfg)
    app.add_middleware(WdMiddleware, appstate=app.state)
    return app
