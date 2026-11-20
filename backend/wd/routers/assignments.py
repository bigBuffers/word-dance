"""布置词汇 routes (API.md 124–129): the admin (every learner) or a guardian (their children) hands a learner a word list.

All are ``U`` endpoints; what a caller may do is decided per learner by ``services.assignments.may_assign`` (403 ``forbidden``)
and per list by its assigner (404 ``not_found`` for someone else's list; the admin reads every list). The learner's side needs no
route of its own: assigned words arrive in ``GET /api/today`` (``Batch.assigned_item_ids``) and in the 磨耳朵 playlist.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, Query

from .. import schemas
from ..clock import Clock
from ..deps import current_user, get_clock, get_db
from ..services import assignments

router = APIRouter()


@router.get("/api/assign/learners", response_model=schemas.AssignLearners)
def learners(me: dict[str, Any] = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    return {"items": assignments.learners(conn, me)}


@router.post("/api/assign/preview", response_model=schemas.AssignPreview)
def preview(body: schemas.AssignPreviewRequest, me: dict[str, Any] = Depends(current_user), conn: sqlite3.Connection = Depends(get_db), clock: Clock = Depends(get_clock)) -> dict[str, Any]:
    return {"items": assignments.preview(conn, me, body.learner_id, body.text, clock.now_utc())}


@router.post("/api/assignments", response_model=schemas.AssignCreated, status_code=201)
def create(body: schemas.AssignCreateRequest, me: dict[str, Any] = Depends(current_user), conn: sqlite3.Connection = Depends(get_db), clock: Clock = Depends(get_clock)) -> dict[str, Any]:
    return assignments.create(conn, me, body.learner_id, body.text, body.mode, body.title, clock.now_utc())


@router.get("/api/assignments", response_model=schemas.AssignmentList)
def list_mine(learner_id: int | None = Query(default=None), me: dict[str, Any] = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    return {"items": assignments.list_mine(conn, me, learner_id)}


@router.get("/api/assignments/{assignment_id}", response_model=schemas.AssignmentDetail)
def detail(assignment_id: int, me: dict[str, Any] = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    return assignments.detail(conn, me, assignment_id)


@router.post("/api/assignments/{assignment_id}/withdraw", response_model=schemas.AssignmentDetail)
def withdraw(assignment_id: int, me: dict[str, Any] = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    return assignments.withdraw(conn, me, assignment_id)
