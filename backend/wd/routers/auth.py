"""``/api/auth/*`` — API.md endpoints 2–5 (WP2).

* ``POST /api/auth/register`` (201): bootstrap rule (empty ``users`` → accepted in any mode, no invite code,
  role ``admin``), otherwise ``WD_REGISTRATION_MODE`` (``open`` / ``invite`` with atomic code consumption /
  ``closed``); user + ``user_settings`` (``next_push_at`` from the defaults) + session in one ``BEGIN IMMEDIATE``.
* ``POST /api/auth/login``: IP throttle 20/10 min, persistent username lockout (423), constant-time verify,
  ``account_disabled`` only after a correct password, a brand-new session every time (no fixation).
* ``POST /api/auth/logout`` (204) and ``GET /api/auth/me`` (user, settings, server flags, badge counters).
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, Request, Response

from .. import __version__, db, security
from ..clock import to_iso
from ..config import Settings
from ..deps import client_ip, current_user, get_db
from ..errors import ApiError
from ..schemas import AuthResponse, LoginRequest, MeResponse, RegisterRequest

log = logging.getLogger("wd.routers.auth")

router = APIRouter()


def _issue_session(request: Request, response: Response, conn: sqlite3.Connection, user_id: int, now) -> None:
    cfg: Settings = request.app.state.settings
    token = security.create_session(
        conn,
        user_id,
        now,
        session_days=cfg.session_days,
        user_agent=request.headers.get("user-agent"),
        ip=client_ip(request),
    )
    security.set_session_cookie(response, token, cfg, secure=security.cookie_secure(request, cfg))


def _auth_payload(conn: sqlite3.Connection, user_id: int) -> dict[str, Any]:
    user = security.load_user(conn, user_id)
    if user is None:  # pragma: no cover - the row was just written/read
        raise ApiError("internal_error")
    return {"user": security.user_dto(user), "settings": security.settings_dto(conn, user_id)}


def server_flags(conn: sqlite3.Connection, cfg: Settings) -> dict[str, Any]:
    """API.md §9 ``ServerFlags`` (``needs_setup`` mirrors ``GET /api/health``)."""
    users = int(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0])
    ai_enabled = cfg.ai_enabled and db.kv_get(conn, "claude.enabled", "1") != "0"
    return {
        "version": __version__,
        "registration_mode": cfg.registration_mode,
        "email_configured": cfg.email_configured,
        "ai_enabled": bool(ai_enabled),
        "images_enabled": cfg.images_enabled,
        "dev": cfg.dev,
        "needs_setup": users == 0,
    }


def counters(conn: sqlite3.Connection, user_id: int) -> dict[str, int]:
    """API.md endpoint 5: open 整理建议 and 待处理 bank rows (the tab-bar badges)."""
    suggestions_open = int(conn.execute("SELECT COUNT(*) FROM bank_suggestions WHERE user_id = ? AND status = 'open'", (user_id,)).fetchone()[0])
    attention = int(
        conn.execute(
            "SELECT COUNT(*) FROM user_words WHERE user_id = ? AND needs_attention = 1 AND state IN ('new','learning')",
            (user_id,),
        ).fetchone()[0]
    )
    return {"suggestions_open": suggestions_open, "attention": attention}


@router.post("/api/auth/register", status_code=201, response_model=AuthResponse)
def register(body: RegisterRequest, request: Request, response: Response, conn: sqlite3.Connection = Depends(get_db)):
    cfg: Settings = request.app.state.settings
    now = request.app.state.clock.now_utc()
    ip = client_ip(request)
    security.rate_limit(conn, f"register:ip:{ip}", limit=security.REGISTER_IP_LIMIT, window_s=security.REGISTER_IP_WINDOW_S, now=now)
    security.check_password(body.password, body.username)
    password_hash = security.hash_password(body.password)  # bcrypt work before the write lock is taken

    with db.tx(conn):
        bootstrap = int(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]) == 0
        if bootstrap:
            role = "admin"  # the first user ever is always admin (API.md 2, DESIGN §10)
        else:
            role = "user"
            if cfg.registration_mode == "closed":
                raise ApiError("registration_closed")
            if cfg.registration_mode == "invite":
                if not body.invite_code or not security.consume_invite(conn, body.invite_code, now):
                    raise ApiError("invalid_invite")
        if security.username_taken(conn, body.username):
            raise ApiError("username_taken")
        if body.email and security.email_taken(conn, body.email):
            raise ApiError("email_taken")
        try:
            user_id = security.create_user(
                conn,
                username=body.username,
                password_hash=password_hash,
                now=now,
                role=role,
                display_name=body.display_name,
                email=body.email,
            )
        except sqlite3.IntegrityError as e:  # a racing duplicate slipped past the pre-checks
            raise ApiError("email_taken" if "email" in str(e).lower() else "username_taken") from e
        _issue_session(request, response, conn, user_id, now)
    log.info("user registered", extra={"event": "register", "user_id": user_id, "role": role, "bootstrap": bootstrap})
    return _auth_payload(conn, user_id)


@router.post("/api/auth/login", response_model=AuthResponse)
def login(body: LoginRequest, request: Request, response: Response, conn: sqlite3.Connection = Depends(get_db)):
    now = request.app.state.clock.now_utc()
    ip = client_ip(request)
    username = body.username.strip()
    security.rate_limit(conn, f"login:ip:{ip}", limit=security.LOGIN_IP_LIMIT, window_s=security.LOGIN_IP_WINDOW_S, now=now)
    security.check_lockout(conn, username, now)

    user = security.load_user_by_name(conn, username)
    if not security.verify_password(body.password, user["password_hash"] if user else None):
        security.record_login_failure(conn, username, now)
        raise ApiError("invalid_credentials")
    assert user is not None
    if not int(user["is_active"]):
        raise ApiError("account_disabled")

    with db.tx(conn):
        security.clear_login_failures(conn, username)
        security.gc_sessions(conn, to_iso(now))
        conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (to_iso(now), user["id"]))
        _issue_session(request, response, conn, int(user["id"]), now)
    log.info("login", extra={"event": "login", "user_id": user["id"]})
    return _auth_payload(conn, int(user["id"]))


@router.post("/api/auth/logout", status_code=204)
def logout(request: Request, user: dict[str, Any] = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    cfg: Settings = request.app.state.settings
    security.delete_session(conn, user["session_token_hash"])
    response = Response(status_code=204)
    security.clear_session_cookie(response, secure=security.cookie_secure(request, cfg))
    return response


@router.get("/api/auth/me", response_model=MeResponse)
def me(request: Request, user: dict[str, Any] = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    cfg: Settings = request.app.state.settings
    return {
        "user": security.user_dto(user),
        "settings": security.settings_dto(conn, int(user["id"])),
        "server": server_flags(conn, cfg),
        "counters": counters(conn, int(user["id"])),
    }
