"""``GET /api/health`` — API.md endpoint 1 (Phase 0, fully implemented; needs only db + config).

``200 {status:"ok", version, registration_mode, needs_setup, sms_enabled, email_enabled, captcha, wechat_enabled, qq_enabled,
apple_enabled, time}``; ``503 {status:"degraded"}`` when the database is unreachable. ``needs_setup`` is true while the ``users`` table
is empty (no admin exists yet); the channel flags tell the login page which sign-in entries to offer (docs/AUTH_SIGNUP_DESIGN.md §5.2) —
the three third-party flags (slice 2-A, §5.3) are ``Settings.<provider>_configured or auth_fake_providers``, or a client installed on
``app.state`` next to an unconfigured provider (the tests' fakes), exactly as ``routers/auth.server_flags`` computes them.
"""

from __future__ import annotations

import logging
import sqlite3

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .. import __version__, db
from ..clock import now_iso
from ..schemas import HealthResponse

log = logging.getLogger("wd.routers.health")

router = APIRouter()


@router.get("/api/health", response_model=HealthResponse, responses={503: {"description": "database unreachable"}})
def health(request: Request):
    cfg = request.app.state.settings
    clock = request.app.state.clock
    try:
        conn = db.connect(cfg.db_path, check_same_thread=False)
        try:
            conn.execute("SELECT 1").fetchone()
            users = int(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0])
        finally:
            conn.close()
    except sqlite3.Error as e:
        log.error("health check: database unreachable: %s", e, extra={"event": "health_degraded"})
        return JSONResponse(status_code=503, content={"status": "degraded", "version": __version__, "time": now_iso(clock)})
    return HealthResponse(
        status="ok",
        version=__version__,
        registration_mode=cfg.registration_mode,
        needs_setup=users == 0,
        sms_enabled=bool(cfg.sms_configured or getattr(request.app.state, "sms", None) is not None),  # a sender installed next to an `off` provider (tests) counts
        email_enabled=cfg.email_configured,
        captcha=cfg.captcha == "on",
        wechat_enabled=bool(cfg.wechat_configured or cfg.auth_fake_providers or getattr(request.app.state, "wechat", None) is not None),
        qq_enabled=bool(cfg.qq_configured or cfg.auth_fake_providers or getattr(request.app.state, "qq", None) is not None),
        apple_enabled=bool(cfg.apple_configured or cfg.auth_fake_providers or getattr(request.app.state, "apple", None) is not None),
        time=now_iso(clock),
    )
