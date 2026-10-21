"""Today routes (WP4): ``/api/today*`` (API.md 43–47). All are ``O`` endpoints (409 ``onboarding_required`` before onboarding).

``GET /api/today`` never builds; ``POST /api/today/build`` is idempotent (``UNIQUE(user_id, local_date)``); grades go
through ``services.batches.grade_item`` (final vs intermediate grades, DESIGN §7); ``/more`` answers 409
``batch_not_ready`` only when no batch exists yet for the user's current local date.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends

from .. import schemas
from ..clock import Clock, local_date
from ..config import Settings
from ..deps import get_clock, get_db, get_settings, require_onboarded
from ..errors import ApiError
from ..services import bank, batches

router = APIRouter()


@router.get("/api/today", response_model=schemas.TodayResponse)
def today(
    me: dict[str, Any] = Depends(require_onboarded),
    conn: sqlite3.Connection = Depends(get_db),
    clock: Clock = Depends(get_clock),
    cfg: Settings = Depends(get_settings),
) -> dict[str, Any]:
    return batches.today_response(conn, int(me["id"]), clock.now_utc(), cfg=cfg)


@router.post("/api/today/build", response_model=schemas.TodayResponse)
def build(
    me: dict[str, Any] = Depends(require_onboarded),
    conn: sqlite3.Connection = Depends(get_db),
    clock: Clock = Depends(get_clock),
    cfg: Settings = Depends(get_settings),
) -> dict[str, Any]:
    uid = int(me["id"])
    now = clock.now_utc()
    today_s = local_date(now, bank.user_timezone(conn, uid)).isoformat()
    batches.build_batch(conn, uid, today_s, "manual", now)
    return batches.today_response(conn, uid, now, cfg=cfg)


@router.post("/api/today/items/{item_id}/grade", response_model=schemas.GradeResponse)
def grade(
    item_id: int,
    body: schemas.GradeRequest,
    me: dict[str, Any] = Depends(require_onboarded),
    conn: sqlite3.Connection = Depends(get_db),
    clock: Clock = Depends(get_clock),
    cfg: Settings = Depends(get_settings),
) -> dict[str, Any]:
    return batches.grade_item(
        conn,
        int(me["id"]),
        item_id,
        body.grade,
        client_event_id=body.client_event_id,
        elapsed_ms=body.elapsed_ms,
        now=clock.now_utc(),
        cfg=cfg,
    )


@router.post("/api/today/more", response_model=schemas.TodayResponse)
def more(
    body: schemas.MoreRequest,
    me: dict[str, Any] = Depends(require_onboarded),
    conn: sqlite3.Connection = Depends(get_db),
    clock: Clock = Depends(get_clock),
    cfg: Settings = Depends(get_settings),
) -> dict[str, Any]:
    uid = int(me["id"])
    now = clock.now_utc()
    today_s = local_date(now, bank.user_timezone(conn, uid)).isoformat()
    batch = bank.today_batch(conn, uid, today_s)
    if batch is None:
        raise ApiError("batch_not_ready", details={"local_date": today_s})
    result = batches.add_more(conn, uid, int(batch["id"]), body.source, body.count, now)
    return batches.today_response(conn, uid, now, cfg=cfg, added=result.added)


@router.post("/api/today/complete", response_model=schemas.CompleteResponse)
def complete(
    me: dict[str, Any] = Depends(require_onboarded),
    conn: sqlite3.Connection = Depends(get_db),
    clock: Clock = Depends(get_clock),
    cfg: Settings = Depends(get_settings),
) -> dict[str, Any]:
    return {"summary": batches.complete_session(conn, int(me["id"]), clock.now_utc(), cfg=cfg)}
