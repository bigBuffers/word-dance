"""``/api/account*`` — API.md endpoints 6–11, 85–89 and 108–111 (WP2; slice 1-A docs/AUTH_SIGNUP_DESIGN.md §5.2; slice 1-B §5.1
「家长 + 孩子」 / §5.2 「存量账号」).

* ``PUT /api/account``: display name / e-mail (a changed e-mail clears ``email_verified_at`` and disables the e-mail channel;
  409 ``last_login_method`` when a password-less account would lose its only login method; 409 ``guardian_factors_required`` when a
  password-less guardian with children would lose the verified e-mail that is its second factor — slice 1-B).
* ``POST /api/account/password`` / ``DELETE /api/account`` / ``DELETE /api/account/identities/phone``: re-authentication by
  :func:`_reauthenticate` — the current password for an account that has one, a ``reauth`` code (endpoint 85) for one without;
  both draw on the ``pwcheck:user:<id>`` budget (10 attempts per 15 min → 429) and run OUTSIDE any transaction so a failed
  attempt stays counted. The password change revokes every other session and stamps ``password_set_at``; the deletion keeps the
  last-admin guard and the cascade (``family.delete_user_rows``: ``identities`` / ``login_codes`` / ``family_codes`` included; a
  private word created by the user is deleted only when no other user's ``user_words`` row references it, checked after the cascade
  in the same transaction). A guardian with children must say what happens to them (``delete_children: true``, else 409
  ``has_children`` naming them): a child holding its own phone is set free, the others are deleted with the guardian
  (``system_events('guardian_deleted')``). The unbind refuses a guardian with children (409 ``guardian_factors_required`` — the phone
  is mandatory while children exist).
* ``POST /api/account/email/request-code`` / ``verify``: the e-mail binding code — a ``login_codes`` row (``purpose='bind_email'``,
  10 minutes, 5 attempts) sent through ``app.state.mailer``; the check (10, like 86 / 88) runs behind the §1 code-check windows
  (``auth_codes.verify_code_checked``: ``code_check:target`` 20/h, ``code_check:ip`` 60/h, failed checks counted) so a logged-in
  attacker cannot brute-force a code faster than a stranger.
* ``POST /api/account/code`` (85): a ``bind_phone`` / ``rebind_phone`` / ``reauth`` code through the shared machinery of
  ``routers/auth_codes.py``; 86 / 87 / 88 bind, unbind and replace the phone identity; 89 is the first-time setup of a
  code-created account (nickname, account kind — slice 1-B: ``guardian`` needs the ``adult`` band and a password unless the account
  already holds one or a verified e-mail; a row the claim flow made a guardian keeps that kind whatever the body says —, age band,
  optional username and password — ``User.needs_profile``).
* **The child restriction list** (API.md §1, slice 1-B): 6–10, 85–89 and 108–111 take ``deps.require_not_child`` — a child account
  (``guardian_user_id`` set) gets 403 ``guardian_required`` whatever its session; its guardian does these things in 「我的孩子」 (94–101).
* **Legacy accounts** (slice 1-B, API.md §3.2): ``POST /api/account/guardian/code`` (108) sends a claim code to the guardian's phone —
  a ``family_codes`` row of kind ``claim_guardian`` written by the ``issuer`` hook of ``auth_codes.issue_and_send`` (template 100004,
  the SMS caps and the 1-A failure semantics) — and ``POST /api/account/guardian`` (109) attaches the account to the number's owner,
  turning a learner into a guardian or creating a placeholder guardian account for an unknown number, with ``guardian_consent_at``
  stamped (``system_events('account_claimed')``). ``POST /api/account/declare`` (110) answers the one-time 「补充信息」 prompt (家长 /
  成人学习者 / 学生（已满 14）) while ``age_band`` is NULL; ``POST /api/account/declare/skip`` (111) snoozes it for 30 days
  (``users.profile_prompted_at``). Claim codes never reach a log line.
* ``GET /api/account/export?format=csv|json``: the 14-column bank export (+ 365 days of ``review_logs`` in JSON).
"""

from __future__ import annotations

import csv
import io
import json
import logging
import sqlite3
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response

from .. import db, family, security
from ..ai.common import system_event
from ..clock import local_date, to_iso
from ..config import Settings
from ..deps import client_ip, current_user, get_db, require_not_child
from ..errors import ApiError
from ..schemas import (
    GUARDIAN_ADULT_ZH,
    AccountCodeRequest,
    AccountDeleteRequest,
    AccountUpdateRequest,
    CodeSendResponse,
    DeclareRequest,
    EmailVerifyRequest,
    ExportFormat,
    GuardianClaimCodeRequest,
    GuardianClaimRequest,
    PasswordChangeRequest,
    PhoneBindRequest,
    PhoneRebindRequest,
    PhoneUnbindRequest,
    ProfileRequest,
    UserResponse,
)
from .auth_codes import SENT, code_check_failed, code_check_gate, identity_is_stale, issue_and_send, mailer_of, normalise_target, send_throttles, sms_sender, verify_code_checked

log = logging.getLogger("wd.routers.account")

router = APIRouter()

EXPORT_COLUMNS = ("word", "phonetic", "translation", "state", "origin", "note", "times_added", "added_at", "mastered_at", "ease", "interval_days", "repetitions", "lapses", "due_at")
EXPORT_VERSION = 1
REVIEW_LOG_EXPORT_DAYS = 365
JOB_KEY_PREFIXES = family.JOB_KEY_PREFIXES  # live jobs cancelled with an orphaned private word (the rule now lives in family.delete_user_rows)
GUARDIAN_PHONE_ZH = "请输入家长的手机号"  # 108 / 109: the number is the caller's own
GUARDIAN_PASSWORD_ZH = "家长账号需要设置密码"  # 89: a guardian without a verified e-mail needs the password as its second factor


def _field_error(field: str, text: str) -> ApiError:
    return ApiError("validation_error", message_zh=text, details={"fields": {field: text}})


def _user_response(conn: sqlite3.Connection, user_id: int, now) -> dict[str, Any]:
    row = security.load_user(conn, user_id)
    if row is None:  # pragma: no cover - the row was just updated
        raise ApiError("internal_error")
    return {"user": security.user_dto_for(conn, row, now=now)}


def _reauthenticate(conn: sqlite3.Connection, user: dict[str, Any], *, password: str | None, code: str | None, password_field: str, now, cfg: Settings) -> int | None:
    """Endpoints 7 / 8 / 87: prove it is the account's owner before a sensitive action.

    An account with a password (``password_set_at`` set) must send its password (``security.verify_account_password``: the
    ``pwcheck:user:<id>`` budget, 401 ``invalid_credentials``); one without must send a ``reauth`` code of endpoint 85 — the same
    budget is spent first (429 ``rate_limited``), then ``security.verify_login_code`` with ``target=None`` finds the newest live
    ``reauth`` row of the user whatever channel it went to (400 ``invalid_code``), and a success clears the budget. The missing
    factor is 400 ``validation_error`` naming the field. Call it OUTSIDE any transaction (a failed attempt must stay counted);
    the returned code row id (None on the password path) is consumed by the caller inside its own transaction.
    """
    if user["password_set_at"] is not None:
        if password is None:
            raise ApiError("validation_error", message_zh="请输入当前密码", details={"fields": {password_field: "必填"}})
        security.verify_account_password(conn, user, password, now=now)
        return None
    if code is None:
        raise ApiError("validation_error", message_zh="请输入验证码", details={"fields": {"code": "必填"}})
    key = security.password_check_key(int(user["id"]))
    retry = security.throttle_hit(conn, key, limit=security.PASSWORD_CHECK_LIMIT, window_s=security.PASSWORD_CHECK_WINDOW_S, now=now)
    if retry is not None:
        log.warning("re-authentication throttled for user %s", user["id"], extra={"event": "password_check_throttled", "user_id": user["id"]})
        raise ApiError("rate_limited", details={"retry_after_s": retry})
    row_id = security.verify_login_code(conn, channel=None, target=None, purpose="reauth", code=code, secret_key=cfg.secret_key, now=now, user_id=int(user["id"]))
    conn.execute("DELETE FROM auth_throttle WHERE key = ?", (key,))
    return row_id


def _consume(conn: sqlite3.Connection, row_id: int | None, now) -> None:
    """Mark a verified code used inside the caller's transaction (400 ``invalid_code`` when a concurrent request got there first)."""
    if row_id is not None and not security.mark_login_code_used(conn, row_id, now):
        raise ApiError("invalid_code", details={"attempts_left": 0})


def _guardian_children(conn: sqlite3.Connection, user: dict[str, Any]) -> list[dict[str, Any]]:
    """The children attached to this account (``[]`` for most) — the two-factor guards of 6 / 87 and the claim pre-checks. Keyed on the
    child rows, not on ``account_kind``, so a row that lost the kind somehow still counts as a guardian here."""
    return family.children_of(conn, int(user["id"]))


@router.put("/api/account", response_model=UserResponse)
def update_account(body: AccountUpdateRequest, request: Request, user: dict[str, Any] = Depends(require_not_child), conn: sqlite3.Connection = Depends(get_db)):
    now = request.app.state.clock.now_utc()
    now_iso = to_iso(now)
    uid = int(user["id"])
    provided = body.model_fields_set
    with db.tx(conn):
        if "display_name" in provided:
            conn.execute("UPDATE users SET display_name = ?, updated_at = ? WHERE id = ?", (body.display_name, now_iso, uid))
        if "email" in provided:
            current = (user["email"] or "").lower()
            new = (body.email or "").lower()
            if new != current:
                if user["password_set_at"] is None and user["email_verified_at"] is not None:
                    if _guardian_children(conn, user):
                        # the verified e-mail is this password-less guardian's second factor while children exist (API.md 6, slice 1-B)
                        raise ApiError("guardian_factors_required", details={"missing": ["second_factor"]})
                    if security.phone_identity(conn, uid) is None:
                        raise ApiError("last_login_method")  # the verified e-mail is this password-less account's only way in (API.md 6)
                if body.email and security.email_taken(conn, body.email, exclude_user_id=uid):
                    raise ApiError("email_taken")
                conn.execute(
                    "UPDATE users SET email = ?, email_verified_at = NULL, updated_at = ? WHERE id = ?",
                    (body.email, now_iso, uid),
                )
                conn.execute("UPDATE user_settings SET email_enabled = 0, updated_at = ? WHERE user_id = ?", (now_iso, uid))
    return _user_response(conn, uid, now)


@router.post("/api/account/password", status_code=204)
def change_password(body: PasswordChangeRequest, request: Request, user: dict[str, Any] = Depends(require_not_child), conn: sqlite3.Connection = Depends(get_db)):
    cfg: Settings = request.app.state.settings
    now = request.app.state.clock.now_utc()
    # 429 / 401 / 400; outside any transaction so a wrong guess stays counted
    code_row = _reauthenticate(conn, user, password=body.current_password, code=body.code, password_field="current_password", now=now, cfg=cfg)
    security.check_password(body.new_password, user["username"])
    new_hash = security.hash_password(body.new_password)  # bcrypt work before the write lock
    with db.tx(conn):
        _consume(conn, code_row, now)
        security.set_password(conn, int(user["id"]), new_hash, now, keep_token_hash=user["session_token_hash"])  # stamps password_set_at
    log.info("password changed", extra={"event": "password_change", "user_id": user["id"]})
    return Response(status_code=204)


@router.delete("/api/account", status_code=204)
def delete_account(body: AccountDeleteRequest, request: Request, user: dict[str, Any] = Depends(require_not_child), conn: sqlite3.Connection = Depends(get_db)):
    """API.md 8: delete my account after the re-authentication. A guardian with children (slice 1-B) must send ``delete_children:
    true`` — else 409 ``has_children`` lists them for the confirmation sheet —; a child that holds its own phone is then set free (a
    learner of the 14+ band, its data kept, its login codes void), the others are deleted with the guardian."""
    cfg: Settings = request.app.state.settings
    now = request.app.state.clock.now_utc()
    now_iso = to_iso(now)
    # 429 / 401 / 400; outside any transaction so a wrong guess stays counted
    code_row = _reauthenticate(conn, user, password=body.password, code=body.code, password_field="password", now=now, cfg=cfg)
    user_id = int(user["id"])
    deleted: list[int] = []
    emancipated: list[int] = []
    with db.tx(conn):
        _consume(conn, code_row, now)
        if security.is_last_active_admin(conn, user):
            raise ApiError("last_admin")
        children = family.children_of(conn, user_id)
        if children and body.delete_children is not True:
            raise ApiError("has_children", details={"children": [{"id": int(c["id"]), "display_name": c["display_name"] or c["username"]} for c in children]})
        for child in children:
            cid = int(child["id"])
            if security.phone_identity(conn, cid) is not None:
                # the child can sign in by itself: it stays, as a learner of the 14+ band, with every row it has
                conn.execute("UPDATE users SET guardian_user_id = NULL, account_kind = 'learner', age_band = '14plus', updated_at = ? WHERE id = ?", (now_iso, cid))
                family.void_family_codes(conn, kind="child_login", user_id=cid, now=now)
                emancipated.append(cid)
            else:
                family.delete_user_rows(conn, cid, now_iso)  # the cascade + the private-word rule for each child
                deleted.append(cid)
        private_words = family.delete_user_rows(conn, user_id, now_iso)
        if children:
            system_event(conn, "guardian_deleted", {"guardian_id": user_id, "deleted": deleted, "emancipated": emancipated}, now=now_iso)
    log.info(
        "account deleted",
        extra={"event": "account_delete", "user_id": user_id, "private_words_deleted": private_words, "children_deleted": len(deleted), "children_emancipated": len(emancipated)},
    )
    response = Response(status_code=204)
    security.clear_session_cookie(response, secure=security.cookie_secure(request, cfg))
    return response


@router.post("/api/account/email/request-code", status_code=202, response_model=CodeSendResponse)
def request_email_code(request: Request, user: dict[str, Any] = Depends(require_not_child), conn: sqlite3.Connection = Depends(get_db)):
    cfg: Settings = request.app.state.settings
    now = request.app.state.clock.now_utc()
    email = user["email"]
    if not email:
        raise ApiError("validation_error", message_zh="账号尚未填写邮箱", details={"fields": {"email": "账号尚未填写邮箱"}})
    if mailer_of(request) is None:
        raise ApiError("smtp_unconfigured")
    security.rate_limit(conn, f"email_code:user:{user['id']}", limit=security.EMAIL_CODE_LIMIT, window_s=security.EMAIL_CODE_WINDOW_S, now=now)
    # a login_codes row (channel email, purpose bind_email, target = the account's address); 503 email_send_failed voids it
    issue_and_send(request, conn, cfg, channel="email", target=str(email), purpose="bind_email", user_id=int(user["id"]), ip=client_ip(request), now=now)
    return dict(SENT)


@router.post("/api/account/email/verify", response_model=UserResponse)
def verify_email(body: EmailVerifyRequest, request: Request, user: dict[str, Any] = Depends(require_not_child), conn: sqlite3.Connection = Depends(get_db)):
    cfg: Settings = request.app.state.settings
    now = request.app.state.clock.now_utc()
    now_iso = to_iso(now)
    email = user["email"]
    if not email:
        raise ApiError("invalid_code", details={"attempts_left": 0})  # the address was removed since the code was sent
    # outside any transaction on purpose: a wrong guess must stay counted even though the request fails; a code sent to an
    # earlier address finds no live row for the current one (attempts_left 0); the code-check windows gate and count it
    row_id = verify_code_checked(conn, cfg, channel="email", target=str(email), purpose="bind_email", code=body.code, ip=client_ip(request), now=now, user_id=int(user["id"]))
    with db.tx(conn):
        _consume(conn, row_id, now)
        # the verified channel wins the address: an UNVERIFIED holder of the same e-mail loses it first so ux_users_email cannot
        # fire (the partial unique index already forbids a second holder today; this is the documented guard, API.md 10)
        conn.execute("UPDATE users SET email = NULL, updated_at = ? WHERE email = ? AND id != ? AND email_verified_at IS NULL", (now_iso, str(email), user["id"]))
        conn.execute("UPDATE users SET email_verified_at = ?, updated_at = ? WHERE id = ?", (now_iso, now_iso, user["id"]))
    return _user_response(conn, int(user["id"]), now)


# ------------------------------------------------------------------------------- phone identity (85–88)
@router.post("/api/account/code", status_code=202, response_model=CodeSendResponse)
def request_account_code(body: AccountCodeRequest, request: Request, user: dict[str, Any] = Depends(require_not_child), conn: sqlite3.Connection = Depends(get_db)):
    """API.md 85: a ``bind_phone`` code to a new number, a ``rebind_phone`` code to the bound number, or a ``reauth`` code to the
    bound phone / the verified e-mail; the §1 send throttles and the SMS caps apply, no captcha (the user is logged in)."""
    cfg: Settings = request.app.state.settings
    now = request.app.state.clock.now_utc()
    uid = int(user["id"])
    mine = security.phone_identity(conn, uid)
    if body.purpose == "bind_phone":
        if body.channel != "phone" or not body.target:
            raise ApiError("validation_error", message_zh="请输入要绑定的手机号", details={"fields": {"target": "必填"}})
        target = normalise_target("phone", body.target)
        holder = security.identity_by_subject(conn, "phone", target)
        if holder is not None:
            if int(holder["user_id"]) == uid:
                raise ApiError("invalid_transition", details={"reason": "already_bound"})
            raise ApiError("identity_taken")  # the user is authenticated: revealing this is acceptable (PLAN §5 85)
    elif body.purpose == "rebind_phone":
        if body.channel != "phone":
            raise ApiError("validation_error", message_zh="更换手机号的验证码只能发送到已绑定的手机", details={"fields": {"channel": "取值无效"}})
        if mine is None:
            raise ApiError("validation_error", message_zh="账号尚未绑定手机号", details={"fields": {"target": "账号尚未绑定手机号"}})
        target = str(mine["subject"])
    else:  # reauth
        if body.channel == "phone":
            if mine is None:
                raise ApiError("validation_error", message_zh="账号尚未绑定手机号", details={"fields": {"channel": "账号尚未绑定手机号"}})
            target = str(mine["subject"])
        else:
            if user["email_verified_at"] is None or not user["email"]:
                raise ApiError("validation_error", message_zh="账号尚未验证邮箱", details={"fields": {"channel": "账号尚未验证邮箱"}})
            target = str(user["email"])
    if body.channel == "phone" and sms_sender(request) is None:
        raise ApiError("sms_unconfigured")
    if body.channel == "email" and mailer_of(request) is None:
        raise ApiError("smtp_unconfigured")
    ip = client_ip(request)
    send_throttles(conn, cfg, channel=body.channel, target=target, ip=ip, now=now)
    issue_and_send(request, conn, cfg, channel=body.channel, target=target, purpose=body.purpose, user_id=uid, ip=ip, now=now)
    return dict(SENT)


@router.post("/api/account/identities/phone", response_model=UserResponse)
def bind_phone(body: PhoneBindRequest, request: Request, user: dict[str, Any] = Depends(require_not_child), conn: sqlite3.Connection = Depends(get_db)):
    """API.md 86: bind the phone a ``bind_phone`` code of 85 was sent to (``verified_at = last_login_at = now``)."""
    cfg: Settings = request.app.state.settings
    now = request.app.state.clock.now_utc()
    now_iso = to_iso(now)
    uid = int(user["id"])
    target = normalise_target("phone", body.target)
    # outside any transaction; the code-check windows of the number and the IP gate the check and count a failure
    row_id = verify_code_checked(conn, cfg, channel="phone", target=target, purpose="bind_phone", code=body.code, ip=client_ip(request), now=now, user_id=uid)
    try:
        with db.tx(conn):
            _consume(conn, row_id, now)
            if security.phone_identity(conn, uid) is not None:
                raise ApiError("invalid_transition", details={"reason": "already_bound"})  # change the number with 88
            holder = security.identity_by_subject(conn, "phone", target)
            if holder is not None:
                raise ApiError("identity_taken")
            conn.execute(
                "INSERT INTO identities(user_id, provider, subject, verified_at, last_login_at, created_at) VALUES (?, 'phone', ?, ?, ?, ?)",
                (uid, target, now_iso, now_iso, now_iso),
            )
    except sqlite3.IntegrityError as e:  # a racing bind of the same number
        raise ApiError("identity_taken") from e
    log.info("phone bound", extra={"event": "auth_phone_bound", "user_id": uid})
    return _user_response(conn, uid, now)


@router.delete("/api/account/identities/phone", response_model=UserResponse)
def unbind_phone(body: PhoneUnbindRequest, request: Request, user: dict[str, Any] = Depends(require_not_child), conn: sqlite3.Connection = Depends(get_db)):
    """API.md 87: unbind the phone after the endpoint-7 re-authentication; the account must keep a password or a verified e-mail
    (409 ``last_login_method``), and a guardian with children keeps its phone (409 ``guardian_factors_required``, slice 1-B)."""
    cfg: Settings = request.app.state.settings
    now = request.app.state.clock.now_utc()
    uid = int(user["id"])
    code_row = _reauthenticate(conn, user, password=body.password, code=body.code, password_field="password", now=now, cfg=cfg)  # outside any transaction
    with db.tx(conn):
        _consume(conn, code_row, now)
        mine = security.phone_identity(conn, uid)
        if mine is None:
            raise ApiError("invalid_transition", details={"reason": "no_phone"})
        fresh = security.load_user(conn, uid) or user
        if _guardian_children(conn, fresh):
            raise ApiError("guardian_factors_required", details={"missing": ["phone"]})  # the phone is mandatory while children exist (API.md 87)
        if fresh["password_set_at"] is None and fresh["email_verified_at"] is None:
            raise ApiError("last_login_method")
        conn.execute("DELETE FROM identities WHERE id = ?", (mine["id"],))
    log.info("phone unbound", extra={"event": "auth_phone_unbound", "user_id": uid})
    return _user_response(conn, uid, now)


@router.post("/api/account/identities/phone/rebind", response_model=UserResponse)
def rebind_phone(body: PhoneRebindRequest, request: Request, user: dict[str, Any] = Depends(require_not_child), conn: sqlite3.Connection = Depends(get_db)):
    """API.md 88: replace the bound phone — a ``rebind_phone`` code on the old number and a ``bind_phone`` code on the new one."""
    cfg: Settings = request.app.state.settings
    now = request.app.state.clock.now_utc()
    now_iso = to_iso(now)
    uid = int(user["id"])
    new_target = normalise_target("phone", body.target_new)
    mine = security.phone_identity(conn, uid)
    if mine is None:
        raise ApiError("invalid_transition", details={"reason": "no_phone"})
    if str(mine["subject"]) == new_target:
        raise ApiError("invalid_transition", details={"reason": "already_bound"})
    # both checks outside any transaction (each failure 400 invalid_code, counted on its number's code-check window)
    ip = client_ip(request)
    old_row = verify_code_checked(conn, cfg, channel="phone", target=str(mine["subject"]), purpose="rebind_phone", code=body.code_old, ip=ip, now=now, user_id=uid)
    new_row = verify_code_checked(conn, cfg, channel="phone", target=new_target, purpose="bind_phone", code=body.code_new, ip=ip, now=now, user_id=uid)
    try:
        with db.tx(conn):
            _consume(conn, old_row, now)
            _consume(conn, new_row, now)
            holder = security.identity_by_subject(conn, "phone", new_target)
            if holder is not None:
                raise ApiError("identity_taken")
            updated = conn.execute(
                "UPDATE identities SET subject = ?, verified_at = ?, last_login_at = ? WHERE id = ? AND user_id = ? AND disputed_at IS NULL",
                (new_target, now_iso, now_iso, mine["id"], uid),
            ).rowcount
            if updated != 1:
                raise ApiError("invalid_transition", details={"reason": "no_phone"})  # unbound meanwhile
    except sqlite3.IntegrityError as e:
        raise ApiError("identity_taken") from e
    log.info("phone rebound", extra={"event": "auth_phone_rebound", "user_id": uid})
    return _user_response(conn, uid, now)


# ------------------------------------------------------------------------------------ first-time setup (89)
@router.post("/api/account/profile", response_model=UserResponse)
def save_profile(body: ProfileRequest, request: Request, user: dict[str, Any] = Depends(require_not_child), conn: sqlite3.Connection = Depends(get_db)):
    """API.md 89: a code-created account saves its nickname, account kind and age band once (optionally a username and a password);
    allowed only while ``User.needs_profile`` (409 ``invalid_transition``, ``details.reason:'profile_done'``). Slice 1-B: ``guardian``
    needs the ``adult`` band and a second factor — a password in this body unless the account already has one or a verified e-mail;
    a row the claim flow (109) already made a guardian ignores the body's ``account_kind`` and follows the guardian rules."""
    now = request.app.state.clock.now_utc()
    now_iso = to_iso(now)
    uid = int(user["id"])
    if not security.user_dto(user)["needs_profile"]:
        raise ApiError("invalid_transition", details={"reason": "profile_done"})
    kind = "guardian" if family.is_guardian(user) else body.account_kind
    if kind == "guardian":
        if body.age_band != "adult":
            raise _field_error("age_band", GUARDIAN_ADULT_ZH)  # the schema checks the body's kind; the claim-created guardian's row is checked here
        if body.password is None and user["password_set_at"] is None and user["email_verified_at"] is None:
            raise _field_error("password", GUARDIAN_PASSWORD_ZH)  # the two-factor rule: the phone plus a password or a verified e-mail
    username = body.username if body.username and body.username.lower() != str(user["username"]).lower() else None
    if username is not None and security.username_taken(conn, username):
        raise ApiError("username_taken")
    new_hash: str | None = None
    if body.password is not None:
        security.check_password(body.password, username or user["username"])
        new_hash = security.hash_password(body.password)  # bcrypt work before the write lock
    try:
        with db.tx(conn):
            if username is not None and security.username_taken(conn, username):
                raise ApiError("username_taken")
            assignments: dict[str, Any] = {
                "display_name": body.display_name,
                "account_kind": kind,
                "age_band": body.age_band,
                "age_declared_at": now_iso,
                "age_declared_ip": client_ip(request),
                "updated_at": now_iso,
            }
            if username is not None:
                assignments["username"] = username
            sets = ", ".join(f"{k} = ?" for k in assignments)
            conn.execute(f"UPDATE users SET {sets} WHERE id = ?", [*assignments.values(), uid])
            if new_hash is not None:
                security.set_password(conn, uid, new_hash, now, keep_token_hash=user["session_token_hash"])  # stamps password_set_at
    except sqlite3.IntegrityError as e:  # a racing registration took the username
        raise ApiError("username_taken") from e
    log.info("profile saved", extra={"event": "account_profile", "user_id": uid, "age_band": body.age_band, "account_kind": kind})
    return _user_response(conn, uid, now)


# ------------------------------------------------------------------- legacy accounts: the claim flow (108 / 109)
def _claim_allowed(conn: sqlite3.Connection, user: dict[str, Any]) -> None:
    """The pre-checks of 108 / 109: an admin never becomes a child (409 ``reason:'admin'``), nor does a guardian with children
    (409 ``reason:'has_children'`` — the ``has_children`` code is endpoint 8's)."""
    if user["role"] == "admin":
        raise ApiError("invalid_transition", details={"reason": "admin"})
    if _guardian_children(conn, user):
        raise ApiError("invalid_transition", details={"reason": "has_children"})


@router.post("/api/account/guardian/code", status_code=202, response_model=CodeSendResponse)
def request_claim_code(body: GuardianClaimCodeRequest, request: Request, user: dict[str, Any] = Depends(require_not_child), conn: sqlite3.Connection = Depends(get_db)):
    """API.md 108 「这是孩子的账号」: a claim code to the guardian's phone — a ``family_codes`` row of kind ``claim_guardian`` bound to
    (me, the number), sent like a ``bind_phone`` code (template 100004, the §1 send throttles, the SMS caps). The answer is the same
    whether or not the number has an account."""
    cfg: Settings = request.app.state.settings
    now = request.app.state.clock.now_utc()
    me = int(user["id"])
    ip = client_ip(request)
    _claim_allowed(conn, user)
    target = normalise_target("phone", body.target)
    holder = security.identity_by_subject(conn, "phone", target)
    if holder is not None and int(holder["user_id"]) == me:
        raise _field_error("target", GUARDIAN_PHONE_ZH)
    if sms_sender(request) is None:
        raise ApiError("sms_unconfigured")
    send_throttles(conn, cfg, channel="phone", target=target, ip=ip, now=now)
    issue_and_send(
        request,
        conn,
        cfg,
        channel="phone",
        target=target,
        purpose="bind_phone",
        user_id=me,
        ip=ip,
        now=now,
        issuer=lambda c: family.issue_claim_code(c, user_id=me, target=target, ip=ip, secret_key=cfg.secret_key, now=now),
        voider=lambda c: family.void_family_codes(c, kind="claim_guardian", user_id=me, now=now),
    )
    log.info("claim code sent", extra={"event": "claim_code_sent", "user_id": me})
    return dict(SENT)


@router.post("/api/account/guardian", response_model=UserResponse)
def claim_guardian(body: GuardianClaimRequest, request: Request, user: dict[str, Any] = Depends(require_not_child), conn: sqlite3.Connection = Depends(get_db)):
    """API.md 109: attach my account to the guardian who owns that phone. The claim code of 108 is verified behind the §1 code-check
    windows and outside the transaction (a wrong guess stays counted; 5 burn the code); then, in ONE transaction, the code is
    consumed, the number's owner becomes a guardian (a learner is converted; an unknown number gets a placeholder guardian account
    with the phone identity, which completes endpoint 89 at its first code login) and my row becomes its child
    (``guardian_user_id``, the band of the body, ``guardian_consent_at``); a ``u14`` claim also drops the account's own phone identity
    and e-mail (children.html §2 — a child under 14 holds no contacts). From the next request on my session is a child session and
    the restriction list applies."""
    cfg: Settings = request.app.state.settings
    now = request.app.state.clock.now_utc()
    now_iso = to_iso(now)
    me = int(user["id"])
    ip = client_ip(request)
    _claim_allowed(conn, user)
    target = normalise_target("phone", body.target)
    # the code-check windows (read first, counted on a failure) and the check itself, outside any transaction
    code_check_gate(conn, ip=ip, targets=(target,), now=now)
    try:
        row_id = family.verify_claim_code(conn, user_id=me, target=target, code=body.code, secret_key=cfg.secret_key, now=now)
    except ApiError as e:
        if e.code == "invalid_code":
            code_check_failed(conn, ip=ip, targets=(target,), now=now)
        raise
    # bcrypt work before the write lock — only a number without an account needs the placeholder guardian's unusable hash
    unusable = security.unusable_password_hash() if security.identity_by_subject(conn, "phone", target) is None else None
    guardian_created = False
    try:
        with db.tx(conn):
            if not family.mark_family_code_used(conn, row_id, now):
                raise ApiError("invalid_code", details={"attempts_left": 0})  # consumed by a concurrent request
            # my own row again, inside the lock: another device of mine may have created a child (95) or finished another claim meanwhile
            fresh_me = security.load_user(conn, me)
            if fresh_me is None:  # pragma: no cover - the session resolved this account a moment ago
                raise ApiError("unauthorized")
            if fresh_me.get("guardian_user_id") is not None:
                raise ApiError("guardian_required")
            if fresh_me["role"] == "admin":
                raise ApiError("invalid_transition", details={"reason": "admin"})
            if family.children_of(conn, me):
                raise ApiError("invalid_transition", details={"reason": "has_children"})  # a child never has children
            holder = security.identity_by_subject(conn, "phone", target)
            if holder is not None:
                guardian = security.load_user(conn, int(holder["user_id"]))
                if guardian is None:  # pragma: no cover - identities cascade with their user
                    raise ApiError("internal_error")
                gid = int(guardian["id"])
                if gid == me:
                    raise _field_error("target", GUARDIAN_PHONE_ZH)
                if not int(guardian["is_active"]):
                    raise ApiError("invalid_transition", details={"reason": "guardian_disabled"})
                if guardian.get("guardian_user_id") is not None:
                    raise ApiError("invalid_transition", details={"reason": "guardian_is_child"})
                if guardian.get("age_band") == "14plus":
                    raise ApiError("invalid_transition", details={"reason": "guardian_minor"})  # a self-declared minor never becomes a guardian (89 / 110 refuse it too)
                if identity_is_stale(holder, cfg, now):
                    # the stale-phone rule of 81 (AUTH_SIGNUP_DESIGN §5.6 invariant 5): a number that may have been re-issued is not
                    # handed a child — the owner signs in with it first (the challenge / dispute of 81 settles who holds it)
                    raise ApiError("invalid_transition", details={"reason": "guardian_stale"})
                if len(family.children_of(conn, gid)) >= family.MAX_CHILDREN:
                    raise ApiError("invalid_transition", details={"reason": "too_many_children"})
                if guardian.get("account_kind") != "guardian":
                    if security.user_dto(guardian)["needs_profile"]:
                        # a code-created owner still in its first-time setup: the kind only — step 0 (89) at its next login shows 我是家长
                        # fixed and asks for the adult band and a password, exactly like the placeholder guardian below
                        conn.execute("UPDATE users SET account_kind = 'guardian', updated_at = ? WHERE id = ?", (now_iso, gid))
                    else:  # a learner (an admin too) becomes a guardian; its own declaration, if any, stands
                        conn.execute(
                            "UPDATE users SET account_kind = 'guardian', age_band = COALESCE(age_band, 'adult'), age_declared_at = COALESCE(age_declared_at, ?), "
                            "age_declared_ip = COALESCE(age_declared_ip, ?), updated_at = ? WHERE id = ?",
                            (now_iso, ip, now_iso, gid),
                        )
            else:
                # nobody owns the number: a placeholder guardian account (unusable password, no band — its first code login shows step 0 with
                # 我是家长 fixed and the password required, endpoint 89) holding the phone identity
                gid = security.create_user(
                    conn,
                    username=security.placeholder_username(conn),
                    password_hash=unusable or security.unusable_password_hash(),
                    now=now,
                    role="user",
                    display_name=None,
                    email=None,
                    password_set_at=None,
                    account_kind="guardian",
                )
                conn.execute(
                    "INSERT INTO identities(user_id, provider, subject, verified_at, last_login_at, created_at) VALUES (?, 'phone', ?, ?, NULL, ?)",
                    (gid, target, now_iso, now_iso),
                )
                guardian_created = True
            attached = conn.execute(
                "UPDATE users SET guardian_user_id = ?, account_kind = 'learner', age_band = ?, age_declared_at = ?, age_declared_ip = ?, guardian_consent_at = ?, updated_at = ? "
                "WHERE id = ? AND guardian_user_id IS NULL",
                (gid, body.age_band, now_iso, ip, now_iso, now_iso, me),
            ).rowcount
            if attached != 1:  # pragma: no cover - fresh_me was read inside the same lock
                raise ApiError("guardian_required")
            detached = 0
            if body.age_band == "u14":
                # the 儿童规则 page (children.html §2): a child under 14 holds no phone or e-mail — the legacy account's own contacts go
                # with the claim (its phone identity, its e-mail and the e-mail reminders); a 14plus claim keeps them
                detached = int(conn.execute("DELETE FROM identities WHERE user_id = ?", (me,)).rowcount)
                if user.get("email"):
                    conn.execute("UPDATE users SET email = NULL, email_verified_at = NULL WHERE id = ?", (me,))
                    conn.execute("UPDATE user_settings SET email_enabled = 0, updated_at = ? WHERE user_id = ?", (now_iso, me))
                    detached += 1
            system_event(conn, "account_claimed", {"child_id": me, "guardian_id": gid, "guardian_created": guardian_created}, now=now_iso)
    except sqlite3.IntegrityError as e:  # a racing registration of the number
        raise ApiError("identity_taken") from e
    log.info("account claimed by a guardian", extra={"event": "account_claimed", "user_id": me, "guardian_id": gid, "guardian_created": guardian_created, "contacts_detached": detached})
    return _user_response(conn, me, now)


# ------------------------------------------------------------------- legacy accounts: the 「补充信息」 prompt (110 / 111)
@router.post("/api/account/declare", response_model=UserResponse)
def declare(body: DeclareRequest, request: Request, user: dict[str, Any] = Depends(require_not_child), conn: sqlite3.Connection = Depends(get_db)):
    """API.md 110: the legacy prompt — 家长 (``guardian`` / ``adult``), 成人学习者 or 学生（已满 14）; once, while ``age_band`` is NULL (409
    ``reason:'declared'``); a code-created account still in its first-time setup declares through 89 instead (409 ``reason:'profile_required'``)."""
    now = request.app.state.clock.now_utc()
    now_iso = to_iso(now)
    uid = int(user["id"])
    if security.user_dto(user)["needs_profile"]:
        raise ApiError("invalid_transition", details={"reason": "profile_required"})
    if user.get("age_band") is not None:
        raise ApiError("invalid_transition", details={"reason": "declared"})
    with db.tx(conn):
        updated = conn.execute(
            "UPDATE users SET account_kind = ?, age_band = ?, age_declared_at = ?, age_declared_ip = ?, profile_prompted_at = NULL, updated_at = ? WHERE id = ? AND age_band IS NULL",
            (body.account_kind, body.age_band, now_iso, client_ip(request), now_iso, uid),
        ).rowcount
        if updated != 1:
            raise ApiError("invalid_transition", details={"reason": "declared"})  # a concurrent declaration landed first
    log.info("legacy account declared", extra={"event": "account_declared", "user_id": uid, "age_band": body.age_band, "account_kind": body.account_kind})
    return _user_response(conn, uid, now)


@router.post("/api/account/declare/skip", status_code=204)
def skip_declare(request: Request, user: dict[str, Any] = Depends(require_not_child), conn: sqlite3.Connection = Depends(get_db)):
    """API.md 111: snooze the legacy prompt for 30 days (``users.profile_prompted_at = now``; idempotent, no state check)."""
    now_iso = to_iso(request.app.state.clock.now_utc())
    uid = int(user["id"])
    with db.tx(conn):
        conn.execute("UPDATE users SET profile_prompted_at = ? WHERE id = ?", (now_iso, uid))
    log.info("profile prompt snoozed", extra={"event": "profile_prompt_snoozed", "user_id": uid})
    return Response(status_code=204)


def export_rows(conn: sqlite3.Connection, user_id: int) -> list[dict[str, Any]]:
    """One ``ExportWordRow`` per ``user_words`` row (every state — history and re-add detection need them)."""
    rows = conn.execute(
        "SELECT w.display AS word, w.phonetic, w.translation, uw.state, uw.origin, uw.note, uw.times_added, uw.added_at, uw.mastered_at, "
        "uw.ease, uw.interval_days, uw.repetitions, uw.lapses, uw.due_at "
        "FROM user_words uw JOIN words w ON w.id = uw.word_id WHERE uw.user_id = ? ORDER BY uw.added_at, uw.id",
        (user_id,),
    ).fetchall()
    return [{k: r[k] for k in EXPORT_COLUMNS} for r in rows]


def export_review_logs(conn: sqlite3.Connection, user_id: int, since_iso: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT rl.created_at, w.display AS word, rl.action, rl.context, rl.prev_state, rl.new_state, rl.prev_interval, rl.new_interval "
        "FROM review_logs rl JOIN words w ON w.id = rl.word_id WHERE rl.user_id = ? AND rl.created_at >= ? ORDER BY rl.created_at, rl.id",
        (user_id, since_iso),
    ).fetchall()
    return [{k: r[k] for k in r.keys()} for r in rows]


@router.get("/api/account/export")
def export_account(request: Request, format: ExportFormat = Query("json"), user: dict[str, Any] = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    now = request.app.state.clock.now_utc()
    settings_row = security.load_settings_row(conn, int(user["id"]))
    tz = settings_row["timezone"] if settings_row else security.DEFAULT_TIMEZONE
    stamp = local_date(now, tz).strftime("%Y%m%d")
    words = export_rows(conn, int(user["id"]))
    if format == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        writer.writerow(EXPORT_COLUMNS)
        for row in words:
            writer.writerow(["" if row[c] is None else row[c] for c in EXPORT_COLUMNS])
        content = buf.getvalue().encode("utf-8")
        media_type = "text/csv; charset=utf-8"
        filename = f"word-dance-export-{stamp}.csv"
    else:
        payload = {
            "version": EXPORT_VERSION,
            "exported_at": to_iso(now),
            "username": user["username"],
            "words": words,
            "review_logs": export_review_logs(conn, int(user["id"]), to_iso(now - timedelta(days=REVIEW_LOG_EXPORT_DAYS))),
        }
        content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        media_type = "application/json; charset=utf-8"
        filename = f"word-dance-export-{stamp}.json"
    return Response(content=content, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{filename}"'})
