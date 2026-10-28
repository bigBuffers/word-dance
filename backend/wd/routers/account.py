"""``/api/account*`` — API.md endpoints 6–11 (WP2).

* ``PUT /api/account``: display name / e-mail (a changed e-mail clears ``email_verified_at`` and disables the e-mail channel).
* ``POST /api/account/password``: verifies the current password, applies the policy, revokes every other session.
* ``DELETE /api/account``: password check, last-admin guard, cascade; a private word created by the user is deleted
  only when no other user's ``user_words`` row references it (checked after the cascade, same transaction).
* ``POST /api/account/email/request-code`` / ``verify``: 6-digit HMAC'd codes through ``app.state.mailer``.
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
from ..delivery.mailer import MailerError
from ..deps import current_user, get_db
from ..errors import ApiError
from ..schemas import (
    AccountDeleteRequest,
    AccountUpdateRequest,
    EmailVerifyRequest,
    ExportFormat,
    PasswordChangeRequest,
    RequestCodeResponse,
    UserResponse,
)

log = logging.getLogger("wd.routers.account")

router = APIRouter()

EXPORT_COLUMNS = ("word", "phonetic", "translation", "state", "origin", "note", "times_added", "added_at", "mastered_at", "ease", "interval_days", "repetitions", "lapses", "due_at")
EXPORT_VERSION = 1
REVIEW_LOG_EXPORT_DAYS = 365
EMAIL_CODE_SUBJECT = "【word-Dance】邮箱验证码"
JOB_KEY_PREFIXES = ("lookup", "content", "image", "svg")  # live jobs cancelled with an orphaned private word


def _user_response(conn: sqlite3.Connection, user_id: int) -> dict[str, Any]:
    row = security.load_user(conn, user_id)
    if row is None:  # pragma: no cover - the row was just updated
        raise ApiError("internal_error")
    return {"user": security.user_dto(row)}


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
    now = request.app.state.clock.now_utc()
    if not security.verify_password(body.current_password, user["password_hash"]):
        raise ApiError("invalid_credentials")
    security.check_password(body.new_password, user["username"])
    security.set_password(conn, int(user["id"]), security.hash_password(body.new_password), now, keep_token_hash=user["session_token_hash"])
    log.info("password changed", extra={"event": "password_change", "user_id": user["id"]})
    return Response(status_code=204)


@router.delete("/api/account", status_code=204)
def delete_account(body: AccountDeleteRequest, request: Request, user: dict[str, Any] = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    cfg: Settings = request.app.state.settings
    now_iso = to_iso(request.app.state.clock.now_utc())
    if not security.verify_password(body.password, user["password_hash"]):
        raise ApiError("invalid_credentials")
    user_id = int(user["id"])
    with db.tx(conn):
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


@router.post("/api/account/email/request-code", status_code=202, response_model=RequestCodeResponse)
def request_email_code(request: Request, user: dict[str, Any] = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    cfg: Settings = request.app.state.settings
    now = request.app.state.clock.now_utc()
    email = user["email"]
    if not email:
        raise ApiError("validation_error", message_zh="账号尚未填写邮箱", details={"fields": {"email": "账号尚未填写邮箱"}})
    mailer = getattr(request.app.state, "mailer", None)
    if mailer is None:
        raise ApiError("smtp_unconfigured")
    security.rate_limit(conn, f"email_code:user:{user['id']}", limit=security.EMAIL_CODE_LIMIT, window_s=security.EMAIL_CODE_WINDOW_S, now=now)
    code = security.issue_email_code(conn, int(user["id"]), email, secret_key=cfg.secret_key, now=now)
    text = (
        f"你的 word-Dance 邮箱验证码是：{code}\n\n"
        f"验证码 {security.EMAIL_CODE_TTL_S // 60} 分钟内有效，请在「设置 → 账号」中填写。\n"
        "如果这不是你的操作，请忽略本邮件。"
    )
    try:
        mailer.send(email, EMAIL_CODE_SUBJECT, text)
    except MailerError as e:
        log.warning("verification e-mail failed: %s", e, extra={"event": "email_code_failed", "user_id": user["id"]})
        raise ApiError("email_send_failed") from e
    return {"sent": True, "expires_in_s": security.EMAIL_CODE_TTL_S}


@router.post("/api/account/email/verify", response_model=UserResponse)
def verify_email(body: EmailVerifyRequest, request: Request, user: dict[str, Any] = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    cfg: Settings = request.app.state.settings
    now = request.app.state.clock.now_utc()
    # outside any transaction on purpose: a wrong guess must stay counted even though the request fails
    issued_for = security.verify_email_code(conn, int(user["id"]), body.code, secret_key=cfg.secret_key, now=now)
    if not user["email"] or issued_for.lower() != str(user["email"]).lower():
        raise ApiError("invalid_code", details={"attempts_left": 0})  # the address changed since the code was sent
    conn.execute("UPDATE users SET email_verified_at = ?, updated_at = ? WHERE id = ?", (to_iso(now), to_iso(now), user["id"]))
    return _user_response(conn, int(user["id"]))


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
