"""``/api/admin/users*`` and ``/api/admin/invites`` — API.md endpoints 56–59 (WP2, admin only).

``POST /api/admin/users/{id}`` applies ``is_active`` / ``role`` / ``new_password``; disabling or demoting the last
active admin is refused (409 ``last_admin``); a disabled user and a user whose password was reset lose every session.
Invite codes are created hashed and shown once (``POST /api/admin/invites``); the list carries metadata only.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Request

from .. import db, security
from ..clock import local_date, to_iso
from ..deps import get_db, require_admin
from ..errors import ApiError
from ..schemas import AdminUser, AdminUsersQuery, AdminUserUpdateRequest, InviteCreatedResponse, InviteCreateRequest, InvitesResponse, Page

log = logging.getLogger("wd.routers.admin_users")

router = APIRouter()


def streak_days(conn: sqlite3.Connection, user_id: int, tz: str, now: datetime) -> int:
    """Consecutive ``daily_stats`` days with ``graded >= 1`` ending today or yesterday (DESIGN §7 streak rule)."""
    today = local_date(now, tz)
    dates = [str(r[0]) for r in conn.execute("SELECT local_date FROM daily_stats WHERE user_id = ? AND graded > 0 ORDER BY local_date DESC", (user_id,))]
    if not dates:
        return 0
    try:
        cursor = date.fromisoformat(dates[0])
    except ValueError:
        return 0
    if cursor < today - timedelta(days=1):
        return 0
    streak = 1
    for raw in dates[1:]:
        d = date.fromisoformat(raw)
        if d == cursor:
            continue
        if d != cursor - timedelta(days=1):
            break
        streak += 1
        cursor = d
    return streak


def _admin_user(conn: sqlite3.Connection, row: dict[str, Any], now: datetime) -> dict[str, Any]:
    uid = int(row["id"])
    bank_size = int(conn.execute("SELECT COUNT(*) FROM user_words WHERE user_id = ? AND state IN ('new','learning')", (uid,)).fetchone()[0])
    tz_row = conn.execute("SELECT timezone FROM user_settings WHERE user_id = ?", (uid,)).fetchone()
    tz = str(tz_row[0]) if tz_row else security.DEFAULT_TIMEZONE
    return security.admin_user_dto(row, bank_size=bank_size, streak_days=streak_days(conn, uid, tz, now))


def _like(q: str) -> str:
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


@router.get("/api/admin/users", response_model=Page[AdminUser])
def list_users(request: Request, query: AdminUsersQuery = Depends(), admin: dict[str, Any] = Depends(require_admin), conn: sqlite3.Connection = Depends(get_db)):
    now = request.app.state.clock.now_utc()
    where = ""
    params: list[Any] = []
    if query.q:
        where = "WHERE username LIKE ? ESCAPE '\\' OR display_name LIKE ? ESCAPE '\\' OR email LIKE ? ESCAPE '\\'"
        params = [_like(query.q.strip())] * 3
    total = int(conn.execute(f"SELECT COUNT(*) FROM users {where}", params).fetchone()[0])
    rows = conn.execute(
        f"SELECT * FROM users {where} ORDER BY id LIMIT ? OFFSET ?",
        [*params, query.page_size, (query.page - 1) * query.page_size],
    ).fetchall()
    items = [_admin_user(conn, security.row_dict(r) or {}, now) for r in rows]
    return {"items": items, "page": query.page, "page_size": query.page_size, "total": total}


@router.post("/api/admin/users/{user_id}", response_model=AdminUser)
def update_user(user_id: int, body: AdminUserUpdateRequest, request: Request, admin: dict[str, Any] = Depends(require_admin), conn: sqlite3.Connection = Depends(get_db)):
    now = request.app.state.clock.now_utc()
    now_iso = to_iso(now)
    target = security.load_user(conn, user_id)
    if target is None:
        raise ApiError("not_found", details={"user_id": user_id})
    new_hash: str | None = None
    if body.new_password is not None:
        security.check_password(body.new_password, target["username"])
        new_hash = security.hash_password(body.new_password)  # bcrypt work before the write lock is taken
    with db.tx(conn):
        target = security.load_user(conn, user_id)
        if target is None:
            raise ApiError("not_found", details={"user_id": user_id})
        deactivating = body.is_active is False and bool(int(target["is_active"]))
        demoting = body.role == "user" and target["role"] == "admin"
        if (deactivating or demoting) and security.is_last_active_admin(conn, target):
            raise ApiError("last_admin")
        if new_hash is not None:
            security.set_password(conn, user_id, new_hash, now)
        assignments: dict[str, Any] = {}
        if body.is_active is not None:
            assignments["is_active"] = 1 if body.is_active else 0
        if body.role is not None:
            assignments["role"] = body.role
        if assignments:
            assignments["updated_at"] = now_iso
            sets = ", ".join(f"{k} = ?" for k in assignments)
            conn.execute(f"UPDATE users SET {sets} WHERE id = ?", [*assignments.values(), user_id])
        if deactivating:
            security.delete_sessions(conn, user_id)
        updated = security.load_user(conn, user_id) or target
    log.info(
        "admin updated user",
        extra={"event": "admin_user_update", "user_id": admin["id"], "target_user_id": user_id, "fields": sorted(body.model_fields_set)},
    )
    return _admin_user(conn, updated, now)


@router.get("/api/admin/invites", response_model=InvitesResponse)
def list_invites(admin: dict[str, Any] = Depends(require_admin), conn: sqlite3.Connection = Depends(get_db)):
    return {"items": security.list_invites(conn)}


@router.post("/api/admin/invites", status_code=201, response_model=InviteCreatedResponse)
def create_invite(body: InviteCreateRequest, request: Request, admin: dict[str, Any] = Depends(require_admin), conn: sqlite3.Connection = Depends(get_db)):
    now = request.app.state.clock.now_utc()
    with db.tx(conn):
        invite_id, code, expires_at = security.create_invite(
            conn,
            created_by=int(admin["id"]),
            max_uses=body.max_uses,
            expires_in_days=body.expires_in_days,
            note=body.note,
            now=now,
        )
    log.info("invite created", extra={"event": "invite_create", "user_id": admin["id"], "invite_id": invite_id})
    return {"id": invite_id, "code": code, "expires_at": expires_at}
