"""Admin content reports (API.md endpoints 70–71, WP6).

* ``GET /api/admin/reports?status=open|resolved|dismissed&page&page_size`` → ``Page<Report>``
* ``POST /api/admin/reports/{id} {status, regenerate?, refetch_image?}`` → ``Report``: ``refetch_image`` runs the
  report flow (:func:`wd.images.reject_active_image` — active image ``rejected`` + ``fetch_image`` excluding it),
  ``regenerate`` enqueues ``generate_content {word_id, force:true}`` on a fresh ``content:<id>:r<n>`` key
  (validated words only); ``resolution`` records what happened (``regenerated`` / ``image_replaced`` / ``dismissed``).
"""

from __future__ import annotations

import sqlite3
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from .. import db
from ..clock import Clock, now_iso
from ..deps import get_clock, get_db, require_admin
from ..errors import ApiError
from ..images import reject_active_image
from ..jobs import queue
from ..schemas import AdminReportsQuery, Page, Report, ReportResolveRequest
from ..services.words import word_brief

router = APIRouter()


def _report_dto(conn: sqlite3.Connection, report_row: sqlite3.Row, admin: dict[str, Any]) -> dict[str, Any]:
    word_row = conn.execute("SELECT * FROM words WHERE id = ?", (report_row["word_id"],)).fetchone()
    user_row = conn.execute("SELECT id, username FROM users WHERE id = ?", (report_row["user_id"],)).fetchone()
    if word_row is None or user_row is None:
        raise ApiError("not_found")
    return {
        "id": int(report_row["id"]),
        "user": {"id": int(user_row["id"]), "username": user_row["username"]},
        "word": word_brief(conn, word_row, int(admin["id"])),
        "target": report_row["target"],
        "reason": report_row["reason"],
        "note": report_row["note"],
        "status": report_row["status"],
        "resolution": report_row["resolution"],
        "created_at": report_row["created_at"],
        "resolved_at": report_row["resolved_at"],
    }


def _enqueue_regenerate(conn: sqlite3.Connection, word_id: int, now: str) -> int | None:
    """``generate_content {word_id, force:true}`` on ``content:<id>:r<n>`` (priority 10); None for an unvalidated word."""
    row = conn.execute("SELECT is_valid_english FROM words WHERE id = ?", (int(word_id),)).fetchone()
    if row is None or row[0] != 1:
        return None
    n = 1 + int(conn.execute("SELECT COUNT(*) FROM jobs WHERE dedupe_key LIKE ?", (f"content:{int(word_id)}:r%",)).fetchone()[0])
    return queue.enqueue(conn, "generate_content", {"word_id": int(word_id), "force": True}, dedupe_key=f"content:{int(word_id)}:r{n}", priority=10, now=now)


@router.get("/api/admin/reports", response_model=Page[Report])
def list_reports(
    q: Annotated[AdminReportsQuery, Query()],
    admin: dict[str, Any] = Depends(require_admin),
    conn: sqlite3.Connection = Depends(get_db),
):
    total = int(conn.execute("SELECT COUNT(*) FROM content_reports WHERE status = ?", (q.status,)).fetchone()[0])
    rows = conn.execute(
        "SELECT * FROM content_reports WHERE status = ? ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
        (q.status, q.page_size, (q.page - 1) * q.page_size),
    ).fetchall()
    return {"items": [_report_dto(conn, r, admin) for r in rows], "page": q.page, "page_size": q.page_size, "total": total}


@router.post("/api/admin/reports/{report_id}", response_model=Report)
def resolve_report(
    report_id: int,
    body: ReportResolveRequest,
    admin: dict[str, Any] = Depends(require_admin),
    conn: sqlite3.Connection = Depends(get_db),
    clock: Clock = Depends(get_clock),
):
    now = now_iso(clock)
    with db.tx(conn):
        row = conn.execute("SELECT * FROM content_reports WHERE id = ?", (report_id,)).fetchone()
        if row is None:
            raise ApiError("not_found")
        actions: list[str] = []
        if body.status == "resolved":
            if body.regenerate and _enqueue_regenerate(conn, int(row["word_id"]), now) is not None:
                actions.append("regenerated")
            if body.refetch_image and reject_active_image(conn, int(row["word_id"]), reason=f"report:{row['reason']}", now=now) is not None:
                actions.append("image_replaced")
            resolution = "+".join(actions) if actions else "resolved"
        else:
            resolution = "dismissed"
        conn.execute(
            "UPDATE content_reports SET status = ?, resolution = ?, resolved_at = ? WHERE id = ?",
            (body.status, resolution, now, report_id),
        )
    updated = conn.execute("SELECT * FROM content_reports WHERE id = ?", (report_id,)).fetchone()
    return _report_dto(conn, updated, admin)
