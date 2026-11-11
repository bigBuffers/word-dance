"""``/api/auth/*`` — API.md endpoints 2–5 (WP2; the sign-in by verification code of §3.1 lives in ``auth_codes.py``).

* ``POST /api/auth/register`` (201): bootstrap rule (empty ``users`` → accepted in any mode, no invite code,
  role ``admin``), otherwise ``WD_REGISTRATION_MODE`` (``open`` / ``invite`` with atomic code consumption /
  ``closed`` / ``verified`` → 403 ``verification_required``: accounts are created by a phone or e-mail code, endpoints 80 / 81);
  user + ``user_settings`` (``next_push_at`` from the defaults) + session in one ``BEGIN IMMEDIATE``.
* ``POST /api/auth/login``: ``username`` is an *identifier* (:func:`resolve_identifier`: the username, else the live phone
  identity, else the verified e-mail), IP throttle 20/10 min counting **failures only** (``security.throttle_check`` before the
  password, ``throttle_hit`` on the failure path), persistent lockout per identifier **and** client IP (423), constant-time
  verify, ``account_disabled`` only after a correct password, a brand-new session every time (no fixation). Admins sign in here only.
* ``POST /api/auth/logout`` (204) and ``GET /api/auth/me`` (user, settings, server flags, badge counters, and — slice 1-B — the
  ``session`` block: the guardian behind a switched child session, ``sessions.actor_user_id`` of API.md 104, and a guardian's own
  家长门 stamp as ``gate_until``, API.md 102 / 105). Every ``User`` DTO here passes ``now`` so ``needs_profile_prompt`` is computed.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, Request, Response

from .. import __version__, audio, db, family, security
from ..clock import to_iso
from ..config import Settings
from ..deps import client_ip, current_user, get_db
from ..errors import ApiError
from ..schemas import AuthResponse, LoginRequest, MeResponse, RegisterRequest
from ..services import bank, suggestions

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


def _auth_payload(conn: sqlite3.Connection, user_id: int, *, now) -> dict[str, Any]:
    """API.md §9 ``AuthResponse`` for ``user_id`` (``needs_profile_prompt`` computed against ``now``)."""
    user = security.load_user(conn, user_id)
    if user is None:  # pragma: no cover - the row was just written/read
        raise ApiError("internal_error")
    return {"user": security.user_dto_for(conn, user, now=now), "settings": security.settings_dto(conn, user_id)}


def session_info(conn: sqlite3.Connection, user: dict[str, Any], now) -> dict[str, Any]:
    """API.md §9 ``SessionInfo`` (slice 1-B) for the user dict of ``deps.current_user``: ``guardian`` = ``{id, display_name}`` of the
    guardian who switched this device into the child's account (``sessions.actor_user_id``, endpoint 104 — the SPA shows 「切回家长」),
    else None; ``gate_until`` = the session's 家长门 stamp + 10 minutes while the caller is a guardian in its own session and the stamp
    is still valid (``family.gate_until``), else None."""
    guardian = None
    actor = user.get("session_actor_user_id")
    if actor is not None:
        row = security.load_user(conn, int(actor))
        if row is not None:  # a guardian row that vanished leaves the device a plain child session
            guardian = {"id": int(row["id"]), "display_name": row["display_name"] or row["username"]}
    return {"guardian": guardian, "gate_until": family.gate_until(user, now)}


def resolve_identifier(conn: sqlite3.Connection, identifier: str) -> dict[str, Any] | None:
    """The account an identifier names (API.md 3, 90, 91): the exact username (``COLLATE NOCASE``) first; else, when it
    normalises to a mainland mobile number, the account of the live ``identities(provider='phone')`` row; else, when it contains
    ``@``, the account whose ``users.email`` equals it (NFKC, lower-cased) **and** is verified. None for anything else — the caller
    takes the dummy-hash path, so an unresolved identifier costs the same as a wrong password. The phone / e-mail spellings come
    from ``security.canonical_identifier`` — the same function keys the login lockout, so the two can never drift apart."""
    ident = identifier.strip()
    if not ident:
        return None
    user = security.load_user_by_name(conn, ident)
    if user is not None:
        return user
    canonical = security.canonical_identifier(ident)
    if canonical.startswith("+"):  # a mainland mobile number in E.164
        identity = security.identity_by_subject(conn, "phone", canonical)
        if identity is not None:
            return security.load_user(conn, int(identity["user_id"]))
        return None
    if "@" in canonical:
        return security.row_dict(conn.execute("SELECT * FROM users WHERE email = ? AND email_verified_at IS NOT NULL", (canonical,)).fetchone())
    return None


def server_flags(conn: sqlite3.Connection, cfg: Settings, *, sms_sender: object | None = None) -> dict[str, Any]:
    """API.md §9 ``ServerFlags`` (``needs_setup`` mirrors ``GET /api/health``). ``sms_sender`` is ``app.state.sms``: a sender
    installed next to an ``off`` provider (tests) still means phone codes can be sent."""
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
        "audio": cfg.audio_provider_effective != "off",  # GET /media/audio serves clips (API.md 76)
        "audio_key": audio.voice_key(cfg),  # provider + voice fingerprint: a switched voice is a new clip URL for the browser cache
        "sms_enabled": bool(cfg.sms_configured or sms_sender is not None),  # phone verification codes can be sent (endpoints 80, 85)
    }


def counters(conn: sqlite3.Connection, user_id: int, now: str) -> dict[str, int]:
    """API.md endpoint 5: open 整理建议 and 待处理 bank rows (the tab-bar badges).

    The same predicates as ``GET /api/suggestions`` (``open_count``: live open rows, ``confusable_group`` rows
    excluded) and ``GET /api/bank`` (``counts.attention``), so the badges never disagree with the lists (WP3).
    """
    return {
        "suggestions_open": suggestions.open_count(conn, user_id, now),
        "attention": bank.attention_count(conn, user_id),
    }


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
            if cfg.registration_mode == "verified":
                raise ApiError("verification_required")  # accounts come from a phone / e-mail code (endpoints 80 / 81); username + password are added later (89 / 7)
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
                password_set_at=to_iso(now),
            )
        except sqlite3.IntegrityError as e:  # a racing duplicate slipped past the pre-checks
            raise ApiError("email_taken" if "email" in str(e).lower() else "username_taken") from e
        _issue_session(request, response, conn, user_id, now)
    log.info("user registered", extra={"event": "register", "user_id": user_id, "role": role, "bootstrap": bootstrap})
    return _auth_payload(conn, user_id, now=now)


@router.post("/api/auth/login", response_model=AuthResponse)
def login(body: LoginRequest, request: Request, response: Response, conn: sqlite3.Connection = Depends(get_db)):
    now = request.app.state.clock.now_utc()
    ip = client_ip(request)
    identifier = body.username.strip()
    ip_key = f"login:ip:{ip}"
    retry = security.throttle_check(conn, ip_key, limit=security.LOGIN_IP_LIMIT, window_s=security.LOGIN_IP_WINDOW_S, now=now)  # failures only: read here, counted below
    if retry is not None:
        raise ApiError("rate_limited", details={"retry_after_s": retry})
    security.check_lockout(conn, identifier, now, ip=ip)

    user = resolve_identifier(conn, identifier)
    if not security.verify_password(body.password, user["password_hash"] if user else None):
        security.throttle_hit(conn, ip_key, limit=security.LOGIN_IP_LIMIT, window_s=security.LOGIN_IP_WINDOW_S, now=now)  # the failure spends the IP window
        security.record_login_failure(conn, identifier, now, ip=ip)
        raise ApiError("invalid_credentials")
    assert user is not None
    if not int(user["is_active"]):
        raise ApiError("account_disabled")

    with db.tx(conn):
        security.clear_login_failures(conn, identifier, ip=ip)
        security.gc_sessions(conn, to_iso(now))
        conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (to_iso(now), user["id"]))
        _issue_session(request, response, conn, int(user["id"]), now)
    log.info("login", extra={"event": "login", "user_id": user["id"]})
    return _auth_payload(conn, int(user["id"]), now=now)


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
    now = request.app.state.clock.now_utc()
    return {
        "user": security.user_dto_for(conn, user, now=now),
        "settings": security.settings_dto(conn, int(user["id"])),
        "server": server_flags(conn, cfg, sms_sender=getattr(request.app.state, "sms", None)),
        "counters": counters(conn, int(user["id"]), to_iso(now)),
        "session": session_info(conn, user, now),
    }
