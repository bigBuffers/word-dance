"""``/api/guardian/*`` — API.md §3.2 endpoints 94–103 (slice 1-B, docs/AUTH_SIGNUP_DESIGN.md §5.1 「家长 + 孩子」 / §5.2).

* ``GET /api/guardian/children`` (94): my children (``ChildAccount`` with progress and signed-in devices), whether the 家长 PIN is set,
  the two-factor readiness (``family.guardian_ready``) and the session's gate state. ``G`` (``deps.require_guardian``).
* ``POST /api/guardian/children`` (95): a child account — nickname, the 6-digit 家长 PIN the first time (required while none is set,
  refused afterwards), an optional simple login (username + password, both or neither); ``family.create_child`` writes the child
  columns (``guardian_user_id``, ``age_band='u14'``, the consent stamp) in one transaction with the PIN; ≤ ``MAX_CHILDREN``.
* ``PATCH`` / ``DELETE /api/guardian/children/{id}`` (96 / 97): rename, set or replace the simple login (a password revokes every
  session of the child), delete with the cascade (``family.delete_user_rows``). ``POST …/sessions/revoke`` (98): sign the child out
  everywhere. ``POST …/login-code`` (99): the 8-digit one-time code for the child's own device (``family.issue_child_code``, 5 per hour
  per child, returned once, never logged). ``POST …/code`` + ``…/emancipate`` (100 / 101): the 独立 flow — a ``bind_phone`` code to the
  phone the child will own (the shared machinery of ``routers/auth_codes.py``, the SMS caps apply), then the code + a new password
  bind the phone, set the password and detach the child (``guardian_user_id`` NULL, ``age_band='14plus'``; irreversible).
* ``POST /api/guardian/gate`` (102): the 家长门 for this session — ``family.gate_check`` (PIN / password / ``reauth`` code, the
  ``gate:user:<id>`` lockout) outside the transaction, then the 10-minute stamp (``family.stamp_gate``). ``PUT /api/guardian/pin`` (103):
  set or change the PIN behind the gate (a guardian without a PIN passes 102 with the password or a code; a forgotten PIN is replaced
  the same way) — the first PIN is gated too, so the holder of a signed-in tablet cannot plant one and open the gate with it.

Every mutating endpoint but 102 is ``G+gate`` (``deps.require_gate``: 403 ``guardian_gate_required`` without a fresh stamp). The
two-factor rule (``family.require_ready``: a live phone AND a password or a verified e-mail → else 409 ``guardian_factors_required``)
guards 95, 99, 100 and 101. bcrypt work (PIN, password, the unusable hash) always runs BEFORE the write transaction. Codes, PINs and
phone numbers never reach a log line or a ``system_events`` detail (ids only).
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, Request, Response

from .. import db, family, security
from ..ai.common import system_event
from ..clock import to_iso
from ..config import Settings
from ..deps import client_ip, get_db, require_gate, require_guardian
from ..errors import ApiError
from ..schemas import (
    ChildCreateRequest,
    ChildEmancipateRequest,
    ChildLoginCode,
    ChildPhoneCodeRequest,
    ChildrenResponse,
    ChildResponse,
    ChildUpdateRequest,
    CodeSendResponse,
    GateRequest,
    GateResponse,
    PinRequest,
)
from .auth_codes import SENT, issue_and_send, normalise_target, send_throttles, sms_sender, verify_code_checked

log = logging.getLogger("wd.routers.guardian")

router = APIRouter()

PIN_REQUIRED_ZH = "请设置 6 位家长 PIN"
PIN_ALREADY_SET_ZH = "PIN 已设置，请在「家长 PIN」中修改"
LOGIN_PAIR_ZH = "用户名和密码需要一起设置"
USERNAME_FIRST_ZH = "请先为孩子设置用户名"


def _field_error(field: str, text: str) -> ApiError:
    return ApiError("validation_error", message_zh=text, details={"fields": {field: text}})


def _fresh(conn: sqlite3.Connection, user_id: int) -> dict[str, Any]:
    """The full ``users`` row (``deps.USER_COLUMNS`` leaves ``guardian_pin_hash`` out on purpose)."""
    row = security.load_user(conn, int(user_id))
    if row is None:  # pragma: no cover - the session just resolved this account
        raise ApiError("unauthorized")
    return row


def _child_response(conn: sqlite3.Connection, child_id: int, now) -> dict[str, Any]:
    row = security.load_user(conn, int(child_id))
    if row is None:  # pragma: no cover - the row was just written
        raise ApiError("internal_error")
    return {"child": family.child_dto(conn, row, now=now)}


# ------------------------------------------------------------------------------------------------- 94
@router.get("/api/guardian/children", response_model=ChildrenResponse)
def list_children(request: Request, user: dict[str, Any] = Depends(require_guardian), conn: sqlite3.Connection = Depends(get_db)):
    now = request.app.state.clock.now_utc()
    me = int(user["id"])
    ready = family.guardian_ready(conn, user)
    return {
        "items": [family.child_dto(conn, row, now=now) for row in family.children_of(conn, me)],
        "pin_set": _fresh(conn, me).get("guardian_pin_hash") is not None,
        "ready": ready["ready"],
        "missing": ready["missing"],
        "gate_until": family.gate_until(user, now),
    }


# ------------------------------------------------------------------------------------------------- 95
@router.post("/api/guardian/children", status_code=201, response_model=ChildResponse)
def create_child(body: ChildCreateRequest, request: Request, user: dict[str, Any] = Depends(require_gate), conn: sqlite3.Connection = Depends(get_db)):
    now = request.app.state.clock.now_utc()
    now_iso = to_iso(now)
    me = int(user["id"])
    ip = client_ip(request)
    family.require_ready(conn, user)
    if len(family.children_of(conn, me)) >= family.MAX_CHILDREN:
        raise ApiError("invalid_transition", details={"reason": "too_many_children"})
    has_pin = _fresh(conn, me).get("guardian_pin_hash") is not None
    if body.pin is None and not has_pin:
        raise _field_error("pin", PIN_REQUIRED_ZH)
    if body.pin is not None and has_pin:
        raise _field_error("pin", PIN_ALREADY_SET_ZH)
    if body.pin is not None:
        problem = family.pin_problem(body.pin)
        if problem:
            raise _field_error("pin", problem)
    if (body.username is None) != (body.password is None):
        raise _field_error("password" if body.password is None else "username", LOGIN_PAIR_ZH)
    if body.username is not None and security.username_taken(conn, body.username):
        raise ApiError("username_taken")
    if body.password is not None:
        security.check_password(body.password, body.username)
    # bcrypt work before the write lock: the PIN hash and the password (or unusable) hash
    pin_hash = family.hash_pin(body.pin) if body.pin is not None else None
    password_hash = security.hash_password(body.password) if body.password is not None else security.unusable_password_hash()
    try:
        with db.tx(conn):
            fresh = _fresh(conn, me)
            if fresh.get("guardian_user_id") is not None or fresh.get("account_kind") != "guardian":
                raise ApiError("forbidden")  # claimed as a child meanwhile (109 on another device of mine): a child never gets a child
            if len(family.children_of(conn, me)) >= family.MAX_CHILDREN:
                raise ApiError("invalid_transition", details={"reason": "too_many_children"})
            username = body.username if body.username is not None else security.placeholder_username(conn)
            if body.username is not None and security.username_taken(conn, username):
                raise ApiError("username_taken")
            child_id = family.create_child(
                conn,
                guardian_id=me,
                display_name=body.display_name,
                username=username,
                password_hash=password_hash,
                password_set_at=now_iso if body.password is not None else None,
                now=now,
                ip=ip,
            )
            if pin_hash is not None:
                conn.execute("UPDATE users SET guardian_pin_hash = ?, updated_at = ? WHERE id = ?", (pin_hash, now_iso, me))
            system_event(conn, "child_created", {"child_id": child_id, "guardian_id": me}, now=now_iso)
    except sqlite3.IntegrityError as e:  # a racing registration took the username
        raise ApiError("username_taken") from e
    log.info("child account created", extra={"event": "child_created", "user_id": me, "child_id": child_id, "pin_set": pin_hash is not None})
    return _child_response(conn, child_id, now)


# ------------------------------------------------------------------------------------------------- 96
@router.patch("/api/guardian/children/{child_id}", response_model=ChildResponse)
def update_child(child_id: int, body: ChildUpdateRequest, request: Request, user: dict[str, Any] = Depends(require_gate), conn: sqlite3.Connection = Depends(get_db)):
    now = request.app.state.clock.now_utc()
    now_iso = to_iso(now)
    me = int(user["id"])
    child = family.child_of(conn, me, child_id)
    current = str(child["username"])
    username = body.username if body.username is not None and body.username.lower() != current.lower() else None
    if username is not None and security.username_taken(conn, username):
        raise ApiError("username_taken")
    new_hash: str | None = None
    if body.password is not None:
        final = body.username if body.username is not None else current
        if security.PLACEHOLDER_USERNAME_RE.match(final):
            raise _field_error("username", USERNAME_FIRST_ZH)  # the child must be able to type its login: a username first
        security.check_password(body.password, final)
        new_hash = security.hash_password(body.password)  # bcrypt work before the write lock
    try:
        with db.tx(conn):
            family.child_of(conn, me, child_id)  # still mine
            if username is not None and security.username_taken(conn, username):
                raise ApiError("username_taken")
            assignments: dict[str, Any] = {"updated_at": now_iso}
            if body.display_name is not None:
                assignments["display_name"] = body.display_name
            if username is not None:
                assignments["username"] = username
            sets = ", ".join(f"{k} = ?" for k in assignments)
            conn.execute(f"UPDATE users SET {sets} WHERE id = ?", [*assignments.values(), int(child_id)])
            if new_hash is not None:
                security.set_password(conn, int(child_id), new_hash, now)  # every session of the child revoked — its devices sign in again
    except sqlite3.IntegrityError as e:
        raise ApiError("username_taken") from e
    log.info(
        "child account updated",
        extra={"event": "child_updated", "user_id": me, "child_id": int(child_id), "renamed": body.display_name is not None, "username_set": username is not None, "password_set": new_hash is not None},
    )
    return _child_response(conn, int(child_id), now)


# ------------------------------------------------------------------------------------------------- 97
@router.delete("/api/guardian/children/{child_id}", status_code=204)
def delete_child(child_id: int, request: Request, user: dict[str, Any] = Depends(require_gate), conn: sqlite3.Connection = Depends(get_db)):
    now_iso = to_iso(request.app.state.clock.now_utc())
    me = int(user["id"])
    family.child_of(conn, me, child_id)
    with db.tx(conn):
        family.child_of(conn, me, child_id)  # still mine inside the lock
        private_words = family.delete_user_rows(conn, int(child_id), now_iso)  # cascade: sessions, identities, login_codes, family_codes, the bank …
        system_event(conn, "child_deleted", {"child_id": int(child_id), "guardian_id": me}, now=now_iso)
    log.info("child account deleted", extra={"event": "child_deleted", "user_id": me, "child_id": int(child_id), "private_words_deleted": private_words})
    return Response(status_code=204)


# ------------------------------------------------------------------------------------------------- 98
@router.post("/api/guardian/children/{child_id}/sessions/revoke", status_code=204)
def revoke_child_sessions(child_id: int, request: Request, user: dict[str, Any] = Depends(require_gate), conn: sqlite3.Connection = Depends(get_db)):
    me = int(user["id"])
    family.child_of(conn, me, child_id)
    with db.tx(conn):
        revoked = security.delete_sessions(conn, int(child_id))  # every session, the guardian-issued ones included
    log.info("child sessions revoked", extra={"event": "child_sessions_revoked", "user_id": me, "child_id": int(child_id), "revoked": revoked})
    return Response(status_code=204)


# ------------------------------------------------------------------------------------------------- 99
@router.post("/api/guardian/children/{child_id}/login-code", status_code=201, response_model=ChildLoginCode)
def child_login_code(child_id: int, request: Request, user: dict[str, Any] = Depends(require_gate), conn: sqlite3.Connection = Depends(get_db)):
    cfg: Settings = request.app.state.settings
    now = request.app.state.clock.now_utc()
    me = int(user["id"])
    family.child_of(conn, me, child_id)
    family.require_ready(conn, user)
    security.rate_limit(conn, f"child_code:user:{int(child_id)}", limit=family.CHILD_CODE_ISSUE_LIMIT, window_s=family.CHILD_CODE_ISSUE_WINDOW_S, now=now)
    code = family.issue_child_code(conn, child_id=int(child_id), ip=client_ip(request), secret_key=cfg.secret_key, now=now)
    log.info("child login code issued", extra={"event": "child_code_issued", "user_id": me, "child_id": int(child_id)})  # the code itself is shown once, never logged
    return {"code": code, "expires_in_s": family.FAMILY_CODE_TTL_S}


# ------------------------------------------------------------------------------------------------ 100
@router.post("/api/guardian/children/{child_id}/code", status_code=202, response_model=CodeSendResponse)
def child_phone_code(child_id: int, body: ChildPhoneCodeRequest, request: Request, user: dict[str, Any] = Depends(require_gate), conn: sqlite3.Connection = Depends(get_db)):
    """API.md 100: a ``bind_phone`` code to the phone the child will own (the 独立 flow); the row belongs to the CHILD, so only 101 can spend it."""
    cfg: Settings = request.app.state.settings
    now = request.app.state.clock.now_utc()
    me = int(user["id"])
    family.child_of(conn, me, child_id)
    family.require_ready(conn, user)
    target = normalise_target("phone", body.target)
    holder = security.identity_by_subject(conn, "phone", target)
    if holder is not None and int(holder["user_id"]) != int(child_id):
        raise ApiError("identity_taken")  # the child's own number (a claimed legacy account that kept it) is fine: 101 re-verifies and keeps it
    if sms_sender(request) is None:
        raise ApiError("sms_unconfigured")
    ip = client_ip(request)
    send_throttles(conn, cfg, channel="phone", target=target, ip=ip, now=now)
    issue_and_send(request, conn, cfg, channel="phone", target=target, purpose="bind_phone", user_id=int(child_id), ip=ip, now=now)
    log.info("child phone code sent", extra={"event": "child_phone_code_sent", "user_id": me, "child_id": int(child_id)})
    return dict(SENT)


# ------------------------------------------------------------------------------------------------ 101
@router.post("/api/guardian/children/{child_id}/emancipate", response_model=ChildResponse)
def emancipate_child(child_id: int, body: ChildEmancipateRequest, request: Request, user: dict[str, Any] = Depends(require_gate), conn: sqlite3.Connection = Depends(get_db)):
    """API.md 101 独立: the child's own phone (its ``bind_phone`` code of 100) + a new password → the account is no longer a child
    (``guardian_user_id`` NULL, ``age_band='14plus'``, every child session revoked, its login codes void). Irreversible."""
    cfg: Settings = request.app.state.settings
    now = request.app.state.clock.now_utc()
    now_iso = to_iso(now)
    me = int(user["id"])
    ip = client_ip(request)
    child = family.child_of(conn, me, child_id)
    family.require_ready(conn, user)
    target = normalise_target("phone", body.target)
    # outside any transaction: the code-check windows of the number and the IP gate the check and count a failure
    row_id = verify_code_checked(conn, cfg, channel="phone", target=target, purpose="bind_phone", code=body.code, ip=ip, now=now, user_id=int(child_id))
    security.check_password(body.password, str(child["username"]))
    new_hash = security.hash_password(body.password)  # bcrypt work before the write lock
    try:
        with db.tx(conn):
            if not security.mark_login_code_used(conn, row_id, now):
                raise ApiError("invalid_code", details={"attempts_left": 0})  # consumed by a concurrent request
            family.child_of(conn, me, child_id)  # still mine
            holder = security.identity_by_subject(conn, "phone", target)
            if holder is not None and int(holder["user_id"]) != int(child_id):
                raise ApiError("identity_taken")
            mine = security.phone_identity(conn, int(child_id))
            if mine is None:
                conn.execute(
                    "INSERT INTO identities(user_id, provider, subject, verified_at, last_login_at, created_at) VALUES (?, 'phone', ?, ?, ?, ?)",
                    (int(child_id), target, now_iso, now_iso, now_iso),
                )
            else:
                # a claimed legacy account that kept a number (14plus claims keep it): the number it already held is re-verified now,
                # another number it held is replaced by the verified one (the 88 shape)
                conn.execute("UPDATE identities SET subject = ?, verified_at = ?, last_login_at = ? WHERE id = ?", (target, now_iso, now_iso, mine["id"]))
            security.set_password(conn, int(child_id), new_hash, now)  # every child session revoked — the shared tablet signs out of the child
            updated = conn.execute(
                "UPDATE users SET guardian_user_id = NULL, account_kind = 'learner', age_band = '14plus', age_declared_at = ?, age_declared_ip = ?, updated_at = ? "
                "WHERE id = ? AND guardian_user_id = ?",
                (now_iso, ip, now_iso, int(child_id), me),
            ).rowcount
            if updated != 1:  # pragma: no cover - child_of just confirmed the row inside the same lock
                raise ApiError("not_found", details={"child_id": int(child_id)})
            family.void_family_codes(conn, kind="child_login", user_id=int(child_id), now=now)
            system_event(conn, "child_emancipated", {"child_id": int(child_id), "guardian_id": me}, now=now_iso)
    except sqlite3.IntegrityError as e:  # a racing bind of the same number
        raise ApiError("identity_taken") from e
    log.info("child emancipated", extra={"event": "child_emancipated", "user_id": me, "child_id": int(child_id)})
    return _child_response(conn, int(child_id), now)


# ------------------------------------------------------------------------------------------------ 102
@router.post("/api/guardian/gate", response_model=GateResponse)
def pass_gate(body: GateRequest, request: Request, user: dict[str, Any] = Depends(require_guardian), conn: sqlite3.Connection = Depends(get_db)):
    cfg: Settings = request.app.state.settings
    now = request.app.state.clock.now_utc()
    me = int(user["id"])
    guardian = _fresh(conn, me)
    # 423 / 401 / 400 / 429; outside any transaction so a wrong factor stays counted on gate:user:<id>
    code_row = family.gate_check(conn, guardian, pin=body.pin, password=body.password, code=body.code, now=now, cfg=cfg, ip=client_ip(request))
    with db.tx(conn):
        if code_row is not None and not security.mark_login_code_used(conn, code_row, now):
            raise ApiError("invalid_code", details={"attempts_left": 0})
        family.stamp_gate(conn, user["session_token_hash"], now)
    log.info("guardian gate passed", extra={"event": "gate_passed", "user_id": me, "factor": "pin" if body.pin is not None else "password" if body.password is not None else "code"})
    return {"gate_until": to_iso(now + timedelta(seconds=family.GATE_TTL_S))}


# ------------------------------------------------------------------------------------------------ 103
@router.put("/api/guardian/pin", status_code=204)
def set_pin(body: PinRequest, request: Request, user: dict[str, Any] = Depends(require_gate), conn: sqlite3.Connection = Depends(get_db)):
    """API.md 103, ``G+gate`` like every other write: the first PIN too — a guardian without one passes 102 with the password or a
    code (whoever merely holds the guardian's signed-in tablet must not be able to plant a PIN and open the gate with it)."""
    now = request.app.state.clock.now_utc()
    me = int(user["id"])
    problem = family.pin_problem(body.pin)
    if problem:
        raise _field_error("pin", problem)
    had_pin = _fresh(conn, me).get("guardian_pin_hash") is not None
    pin_hash = family.hash_pin(body.pin)  # bcrypt work before the write lock
    with db.tx(conn):
        conn.execute("UPDATE users SET guardian_pin_hash = ?, updated_at = ? WHERE id = ?", (pin_hash, to_iso(now), me))
    log.info("guardian PIN set", extra={"event": "guardian_pin_set", "user_id": me, "changed": had_pin})
    return Response(status_code=204)
