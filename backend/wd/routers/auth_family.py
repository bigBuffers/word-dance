"""``/api/auth/switch/*`` and ``/api/auth/child-login`` — API.md §3.2 endpoints 104–107 (slice 1-B, docs/AUTH_SIGNUP_DESIGN.md §5.2
「切换与边界」 / 「未成年人」).

* ``POST /api/auth/switch/{child_id}`` (104, ``G``): the shared tablet becomes the child's — this device's guardian session is deleted
  and a child session with ``actor_user_id = the guardian`` is issued in ONE transaction (other devices keep the guardian; readiness
  required; a disabled child → 403 ``account_disabled``). No gate: 「一键切换到孩子账号学习，切回要过家长门」. A child account calling it
  (a switched session included) gets 403 ``guardian_required`` — the restriction list of API.md §1; other non-guardians 403 ``forbidden``.
* ``POST /api/auth/switch/back`` (105, a switched child session): the 家长门 (``family.gate_check`` — PIN / password / ``reauth`` code
  of 106, the ``gate:user:<guardian id>`` lockout) outside the transaction, then the child session is replaced by a fresh guardian
  session that already carries the gate stamp (the guardian lands on 我的孩子 without a second prompt). A self session → 409
  ``invalid_transition`` ``reason:'not_switched'``.
* ``POST /api/auth/switch/code`` (106): a ``reauth`` code to the guardian's live phone or verified e-mail for 105 (the shared send
  machinery of ``routers/auth_codes.py``; no captcha — a session exists).
* ``POST /api/auth/child-login`` (107, public): the 8-digit code of endpoint 99 signs the child's own device in for
  ``family.CHILD_SESSION_DAYS`` (90 days; the cookie's ``Max-Age`` says so and ``deps.current_user`` never shortens it). The per-IP
  window ``child_login:ip:<ip>`` (10/h) counts FAILURES only and is read BEFORE the lookup (the ``login:ip`` rule); a miss, a code of a
  child set free meanwhile → 400 ``invalid_code`` ``attempts_left: 0``; a disabled child → 403 ``account_disabled``.

The static paths ``/api/auth/switch/back`` and ``/api/auth/switch/code`` are registered BEFORE ``/api/auth/switch/{child_id}`` (and
``child_id`` is an ``int``), so they can never be read as a child id. Every ``{user}`` DTO here passes ``now`` (``needs_profile_prompt``).
Codes never reach a log line.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, Request, Response

from .. import db, family, security
from ..clock import to_iso
from ..config import Settings
from ..deps import client_ip, current_user, get_db, hash_token, require_guardian, require_not_child
from ..errors import ApiError
from ..schemas import AuthResponse, ChildLoginRequest, CodeSendResponse, SwitchBackRequest, SwitchCodeRequest
from .auth_codes import SENT, issue_and_send, mailer_of, send_throttles, sms_sender

log = logging.getLogger("wd.routers.auth_family")

router = APIRouter()

GUARDIAN_NO_PHONE_ZH = "家长账号尚未绑定手机号"
GUARDIAN_NO_EMAIL_ZH = "家长账号尚未验证邮箱"


def _guardian_not_child(user: dict[str, Any] = Depends(require_not_child)) -> dict[str, Any]:
    """Endpoint 104 sits on the child restriction list (API.md §1): a child account — a switched session included — gets 403
    ``guardian_required`` before the ``G`` check answers 403 ``forbidden`` to every other non-guardian."""
    return require_guardian(user)


def _payload(conn: sqlite3.Connection, user_id: int, now) -> dict[str, Any]:
    """API.md §9 ``AuthResponse`` for ``user_id`` (``needs_profile_prompt`` computed against ``now``)."""
    row = security.load_user(conn, int(user_id))
    if row is None:  # pragma: no cover - the row was just read inside the transaction
        raise ApiError("internal_error")
    return {"user": security.user_dto_for(conn, row, now=now), "settings": security.settings_dto(conn, int(user_id))}


def _switched_guardian(conn: sqlite3.Connection, user: dict[str, Any]) -> dict[str, Any]:
    """The guardian behind a switched child session (105 / 106): 409 ``not_switched`` for a self session; a guardian row that vanished
    → the session is dead (401), a disabled guardian → 403."""
    actor = user.get("session_actor_user_id")
    if actor is None:
        raise ApiError("invalid_transition", details={"reason": "not_switched"})
    guardian = security.load_user(conn, int(actor))
    if guardian is None:
        with db.maybe_tx(conn):
            security.delete_session(conn, user["session_token_hash"])
        raise ApiError("unauthorized")
    if not int(guardian["is_active"]):
        raise ApiError("account_disabled")
    return guardian


# ------------------------------------------------------------------------------------------------ 105
@router.post("/api/auth/switch/back", response_model=AuthResponse)
def switch_back(body: SwitchBackRequest, request: Request, response: Response, user: dict[str, Any] = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    cfg: Settings = request.app.state.settings
    now = request.app.state.clock.now_utc()
    now_iso = to_iso(now)
    ip = client_ip(request)
    guardian = _switched_guardian(conn, user)
    guardian_id = int(guardian["id"])
    # 423 / 401 / 400 / 429; outside any transaction so a wrong factor stays counted on gate:user:<guardian id>
    code_row = family.gate_check(conn, guardian, pin=body.pin, password=body.password, code=body.code, now=now, cfg=cfg, ip=ip)
    with db.tx(conn):
        if code_row is not None and not security.mark_login_code_used(conn, code_row, now):
            raise ApiError("invalid_code", details={"attempts_left": 0})
        security.delete_session(conn, user["session_token_hash"])  # this device leaves the child's account
        security.gc_sessions(conn, now_iso)
        token = security.create_session(conn, guardian_id, now, session_days=cfg.session_days, user_agent=request.headers.get("user-agent"), ip=ip, actor_user_id=None)
        family.stamp_gate(conn, hash_token(token), now)  # the guardian lands on 我的孩子 without a second prompt
        conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (now_iso, guardian_id))
    security.set_session_cookie(response, token, cfg, secure=security.cookie_secure(request, cfg))
    log.info("guardian switched back", extra={"event": "guardian_switch_back", "user_id": guardian_id, "child_id": int(user["id"])})
    return _payload(conn, guardian_id, now)


# ------------------------------------------------------------------------------------------------ 106
@router.post("/api/auth/switch/code", status_code=202, response_model=CodeSendResponse)
def switch_code(body: SwitchCodeRequest, request: Request, user: dict[str, Any] = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    cfg: Settings = request.app.state.settings
    now = request.app.state.clock.now_utc()
    guardian = _switched_guardian(conn, user)
    guardian_id = int(guardian["id"])
    if body.channel == "phone":
        identity = security.phone_identity(conn, guardian_id)
        if identity is None:
            raise ApiError("validation_error", message_zh=GUARDIAN_NO_PHONE_ZH, details={"fields": {"channel": GUARDIAN_NO_PHONE_ZH}})
        if sms_sender(request) is None:
            raise ApiError("sms_unconfigured")
        target = str(identity["subject"])
    else:
        if guardian.get("email_verified_at") is None or not guardian.get("email"):
            raise ApiError("validation_error", message_zh=GUARDIAN_NO_EMAIL_ZH, details={"fields": {"channel": GUARDIAN_NO_EMAIL_ZH}})
        if mailer_of(request) is None:
            raise ApiError("smtp_unconfigured")
        target = str(guardian["email"])
    ip = client_ip(request)
    send_throttles(conn, cfg, channel=body.channel, target=target, ip=ip, now=now)
    issue_and_send(request, conn, cfg, channel=body.channel, target=target, purpose="reauth", user_id=guardian_id, ip=ip, now=now)
    log.info("switch-back code sent", extra={"event": "guardian_switch_code_sent", "user_id": guardian_id, "child_id": int(user["id"]), "channel": body.channel})
    return dict(SENT)


# ------------------------------------------------------------------------------------------------ 104
@router.post("/api/auth/switch/{child_id}", response_model=AuthResponse)
def switch_to_child(child_id: int, request: Request, response: Response, user: dict[str, Any] = Depends(_guardian_not_child), conn: sqlite3.Connection = Depends(get_db)):
    cfg: Settings = request.app.state.settings
    now = request.app.state.clock.now_utc()
    now_iso = to_iso(now)
    me = int(user["id"])
    ip = client_ip(request)
    family.require_ready(conn, user)
    child = family.child_of(conn, me, child_id)
    if not int(child["is_active"]):
        raise ApiError("account_disabled")
    with db.tx(conn):
        family.child_of(conn, me, child_id)  # still mine inside the lock
        security.delete_session(conn, user["session_token_hash"])  # this device only — other devices keep the guardian
        security.gc_sessions(conn, now_iso)
        token = security.create_session(conn, int(child_id), now, session_days=cfg.session_days, user_agent=request.headers.get("user-agent"), ip=ip, actor_user_id=me)
        conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (now_iso, int(child_id)))
    security.set_session_cookie(response, token, cfg, secure=security.cookie_secure(request, cfg))
    log.info("guardian switched to a child", extra={"event": "guardian_switch", "user_id": me, "child_id": int(child_id)})
    return _payload(conn, int(child_id), now)


# ------------------------------------------------------------------------------------------------ 107
@router.post("/api/auth/child-login", response_model=AuthResponse)
def child_login(body: ChildLoginRequest, request: Request, response: Response, conn: sqlite3.Connection = Depends(get_db)):
    cfg: Settings = request.app.state.settings
    now = request.app.state.clock.now_utc()
    now_iso = to_iso(now)
    ip = client_ip(request)
    ip_key = f"child_login:ip:{ip}"
    retry = security.throttle_check(conn, ip_key, limit=family.CHILD_LOGIN_IP_LIMIT, window_s=family.CHILD_LOGIN_IP_WINDOW_S, now=now)  # failures only: read here, counted below
    if retry is not None:
        raise ApiError("rate_limited", details={"retry_after_s": retry})
    child_id: int | None = None
    disabled = False
    token: str | None = None
    with db.tx(conn):
        row = family.consume_child_code(conn, code=body.code, secret_key=cfg.secret_key, now=now)
        child = security.load_user(conn, int(row["user_id"])) if row is not None else None
        if child is not None and child.get("guardian_user_id") is not None:  # a code of a child set free meanwhile is a miss (the row stays spent)
            child_id = int(child["id"])
            if not int(child["is_active"]):
                disabled = True
            else:
                security.gc_sessions(conn, now_iso)
                token = security.create_session(conn, child_id, now, session_days=family.CHILD_SESSION_DAYS, user_agent=request.headers.get("user-agent"), ip=ip, actor_user_id=None)
                conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (now_iso, child_id))
    if child_id is None:
        security.throttle_hit(conn, ip_key, limit=family.CHILD_LOGIN_IP_LIMIT, window_s=family.CHILD_LOGIN_IP_WINDOW_S, now=now)  # the miss spends the IP window
        raise ApiError("invalid_code", details={"attempts_left": 0})
    if disabled or token is None:
        raise ApiError("account_disabled")
    security.set_session_cookie(response, token, cfg, secure=security.cookie_secure(request, cfg), max_age_s=family.CHILD_SESSION_DAYS * 86400)
    log.info("child device signed in", extra={"event": "child_login", "user_id": child_id})
    return _payload(conn, child_id, now)
