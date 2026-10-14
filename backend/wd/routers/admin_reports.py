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

router = APIRouter()

STAGE_COLUMNS = (("zk", "stage_zk"), ("gk", "stage_gk"), ("cet4", "stage_cet4"), ("cet6", "stage_cet6"))


def _first_line(text: str | None, limit: int = 60) -> str:
    if not text:
        return ""
    for line in str(text).splitlines():
        if line.strip():
            return line.strip()[:limit]
    return ""


def _local_word_brief(row: sqlite3.Row, my_state: str | None) -> dict[str, Any]:
    """``WordBrief`` straight from a ``words`` row (used until WP1's ``services.words.word_brief`` is importable)."""
    return {
        "id": int(row["id"]),
        "lemma": row["lemma"],
        "display": row["display"],
        "kind": row["kind"],
        "phonetic": row["phonetic"],
        "translation_short": _first_line(row["translation"]),
        "stages": [stage for stage, col in STAGE_COLUMNS if row[col]],
        "stage_min": row["stage_min"],
        "cet6_star": bool(row["cet6_star"]),
        "frq": row["frq"],
        "collins": row["collins"],
        "oxford": None if row["oxford"] is None else bool(row["oxford"]),
        "difficulty": row["difficulty"],
        "is_public": bool(row["is_public"]),
        "is_valid_english": None if row["is_valid_english"] is None else bool(row["is_valid_english"]),
        "my_state": my_state,
        "content_state": row["content_state"],
        "image_state": row["image_state"],
    }


def word_brief(conn: sqlite3.Connection, row: sqlite3.Row, user_id: int) -> dict[str, Any]:
    try:
        from ..services.words import word_brief as wp1_word_brief  # type: ignore[import-not-found]  # WP1
    except ModuleNotFoundError as e:
        if e.name != "wd.services.words":
            raise
        state_row = conn.execute("SELECT state FROM user_words WHERE user_id = ? AND word_id = ?", (int(user_id), int(row["id"]))).fetchone()
        return _local_word_brief(row, None if state_row is None else state_row["state"])
    return wp1_word_brief(conn, row, user_id)


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
