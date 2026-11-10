"""``/api/account*`` — API.md endpoints 6–11 and 85–89 (WP2; slice 1-A docs/AUTH_SIGNUP_DESIGN.md §5.2).

* ``PUT /api/account``: display name / e-mail (a changed e-mail clears ``email_verified_at`` and disables the e-mail channel;
  409 ``last_login_method`` when a password-less account would lose its only login method).
* ``POST /api/account/password`` / ``DELETE /api/account`` / ``DELETE /api/account/identities/phone``: re-authentication by
  :func:`_reauthenticate` — the current password for an account that has one, a ``reauth`` code (endpoint 85) for one without;
  both draw on the ``pwcheck:user:<id>`` budget (10 attempts per 15 min → 429) and run OUTSIDE any transaction so a failed
  attempt stays counted. The password change revokes every other session and stamps ``password_set_at``; the deletion keeps the
  last-admin guard and the cascade (``identities`` / ``login_codes`` included); a private word created by the user is deleted
  only when no other user's ``user_words`` row references it (checked after the cascade, same transaction).
* ``POST /api/account/email/request-code`` / ``verify``: the e-mail binding code — a ``login_codes`` row (``purpose='bind_email'``,
  10 minutes, 5 attempts) sent through ``app.state.mailer``; the check (10, like 86 / 88) runs behind the §1 code-check windows
  (``auth_codes.verify_code_checked``: ``code_check:target`` 20/h, ``code_check:ip`` 60/h, failed checks counted) so a logged-in
  attacker cannot brute-force a code faster than a stranger.
* ``POST /api/account/code`` (85): a ``bind_phone`` / ``rebind_phone`` / ``reauth`` code through the shared machinery of
  ``routers/auth_codes.py``; 86 / 87 / 88 bind, unbind and replace the phone identity; 89 is the first-time setup of a
  code-created account (nickname, age band, optional username and password — ``User.needs_profile``).
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

from .. import db, security
from ..clock import local_date, to_iso
from ..config import Settings
from ..deps import client_ip, current_user, get_db
from ..errors import ApiError
from ..schemas import (
    AccountCodeRequest,
    AccountDeleteRequest,
    AccountUpdateRequest,
    CodeSendResponse,
    EmailVerifyRequest,
    ExportFormat,
    PasswordChangeRequest,
    PhoneBindRequest,
    PhoneRebindRequest,
    PhoneUnbindRequest,
    ProfileRequest,
    UserResponse,
)
from .auth_codes import SENT, issue_and_send, mailer_of, normalise_target, send_throttles, sms_sender, verify_code_checked

log = logging.getLogger("wd.routers.account")

router = APIRouter()

EXPORT_COLUMNS = ("word", "phonetic", "translation", "state", "origin", "note", "times_added", "added_at", "mastered_at", "ease", "interval_days", "repetitions", "lapses", "due_at")
EXPORT_VERSION = 1
REVIEW_LOG_EXPORT_DAYS = 365
JOB_KEY_PREFIXES = ("lookup", "content", "image", "svg", "dance")  # live jobs cancelled with an orphaned private word


def _user_response(conn: sqlite3.Connection, user_id: int) -> dict[str, Any]:
    row = security.load_user(conn, user_id)
    if row is None:  # pragma: no cover - the row was just updated
        raise ApiError("internal_error")
    return {"user": security.user_dto_for(conn, row)}


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


@router.put("/api/account", response_model=UserResponse)
def update_account(body: AccountUpdateRequest, request: Request, user: dict[str, Any] = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    now_iso = to_iso(request.app.state.clock.now_utc())
    provided = body.model_fields_set
    with db.tx(conn):
        if "display_name" in provided:
            conn.execute("UPDATE users SET display_name = ?, updated_at = ? WHERE id = ?", (body.display_name, now_iso, user["id"]))
        if "email" in provided:
            current = (user["email"] or "").lower()
            new = (body.email or "").lower()
            if new != current:
                if user["password_set_at"] is None and user["email_verified_at"] is not None and security.phone_identity(conn, int(user["id"])) is None:
                    raise ApiError("last_login_method")  # the verified e-mail is this password-less account's only way in (API.md 6)
                if body.email and security.email_taken(conn, body.email, exclude_user_id=int(user["id"])):
                    raise ApiError("email_taken")
                conn.execute(
                    "UPDATE users SET email = ?, email_verified_at = NULL, updated_at = ? WHERE id = ?",
                    (body.email, now_iso, user["id"]),
                )
                conn.execute("UPDATE user_settings SET email_enabled = 0, updated_at = ? WHERE user_id = ?", (now_iso, user["id"]))
    return _user_response(conn, int(user["id"]))


@router.post("/api/account/password", status_code=204)
def change_password(body: PasswordChangeRequest, request: Request, user: dict[str, Any] = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
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
def delete_account(body: AccountDeleteRequest, request: Request, user: dict[str, Any] = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    cfg: Settings = request.app.state.settings
    now = request.app.state.clock.now_utc()
    now_iso = to_iso(now)
    # 429 / 401 / 400; outside any transaction so a wrong guess stays counted
    code_row = _reauthenticate(conn, user, password=body.password, code=body.code, password_field="password", now=now, cfg=cfg)
    user_id = int(user["id"])
    with db.tx(conn):
        _consume(conn, code_row, now)
        if security.is_last_active_admin(conn, user):
            raise ApiError("last_admin")
        private_words = [int(r[0]) for r in conn.execute("SELECT id FROM words WHERE created_by_user_id = ? AND is_public = 0", (user_id,))]
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))  # ON DELETE CASCADE / SET NULL do the rest
        orphaned = [
            wid for wid in private_words if int(conn.execute("SELECT COUNT(*) FROM user_words WHERE word_id = ?", (wid,)).fetchone()[0]) == 0
        ]
        if orphaned:
            keys = [f"{prefix}:{wid}" for wid in orphaned for prefix in JOB_KEY_PREFIXES]
            conn.execute(
                f"UPDATE jobs SET status = 'cancelled', updated_at = ?, finished_at = ? WHERE status IN ('queued','running') AND dedupe_key IN ({','.join('?' * len(keys))})",
                [now_iso, now_iso, *keys],
            )
            conn.execute(f"DELETE FROM words WHERE id IN ({','.join('?' * len(orphaned))})", orphaned)
    log.info("account deleted", extra={"event": "account_delete", "user_id": user_id, "private_words_deleted": len(orphaned)})
    response = Response(status_code=204)
    security.clear_session_cookie(response, secure=security.cookie_secure(request, cfg))
    return response


@router.post("/api/account/email/request-code", status_code=202, response_model=CodeSendResponse)
def request_email_code(request: Request, user: dict[str, Any] = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
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
def verify_email(body: EmailVerifyRequest, request: Request, user: dict[str, Any] = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
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
    return _user_response(conn, int(user["id"]))


# ------------------------------------------------------------------------------- phone identity (85–88)
@router.post("/api/account/code", status_code=202, response_model=CodeSendResponse)
def request_account_code(body: AccountCodeRequest, request: Request, user: dict[str, Any] = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
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
def bind_phone(body: PhoneBindRequest, request: Request, user: dict[str, Any] = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
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
    return _user_response(conn, uid)


@router.delete("/api/account/identities/phone", response_model=UserResponse)
def unbind_phone(body: PhoneUnbindRequest, request: Request, user: dict[str, Any] = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    """API.md 87: unbind the phone after the endpoint-7 re-authentication; the account must keep a password or a verified e-mail
    (409 ``last_login_method``)."""
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
        if fresh["password_set_at"] is None and fresh["email_verified_at"] is None:
            raise ApiError("last_login_method")
        conn.execute("DELETE FROM identities WHERE id = ?", (mine["id"],))
    log.info("phone unbound", extra={"event": "auth_phone_unbound", "user_id": uid})
    return _user_response(conn, uid)


@router.post("/api/account/identities/phone/rebind", response_model=UserResponse)
def rebind_phone(body: PhoneRebindRequest, request: Request, user: dict[str, Any] = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
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
    return _user_response(conn, uid)


# ------------------------------------------------------------------------------------ first-time setup (89)
@router.post("/api/account/profile", response_model=UserResponse)
def save_profile(body: ProfileRequest, request: Request, user: dict[str, Any] = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    """API.md 89: a code-created account saves its nickname and age band once (optionally a username and a password); allowed only
    while ``User.needs_profile`` (409 ``invalid_transition``, ``details.reason:'profile_done'``)."""
    now = request.app.state.clock.now_utc()
    now_iso = to_iso(now)
    uid = int(user["id"])
    if not security.user_dto(user)["needs_profile"]:
        raise ApiError("invalid_transition", details={"reason": "profile_done"})
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
            assignments: dict[str, Any] = {"display_name": body.display_name, "age_band": body.age_band, "age_declared_at": now_iso, "age_declared_ip": client_ip(request), "updated_at": now_iso}
            if username is not None:
                assignments["username"] = username
            sets = ", ".join(f"{k} = ?" for k in assignments)
            conn.execute(f"UPDATE users SET {sets} WHERE id = ?", [*assignments.values(), uid])
            if new_hash is not None:
                security.set_password(conn, uid, new_hash, now, keep_token_hash=user["session_token_hash"])  # stamps password_set_at
    except sqlite3.IntegrityError as e:  # a racing registration took the username
        raise ApiError("username_taken") from e
    log.info("profile saved", extra={"event": "account_profile", "user_id": uid, "age_band": body.age_band})
    return _user_response(conn, uid)


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
