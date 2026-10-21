"""History routes (WP4): ``/api/history`` (48), ``/api/history/batches`` (49), ``/api/batches/{id}`` (50), ``/api/stats`` (51).

All are ``O`` endpoints. ``GET /api/batches/{id}`` returns a ``TodayResponse`` for one of the user's batches
(404 ``batch_not_found`` otherwise); ``Batch.gradable`` is true for today's batch and for yesterday's while it has
ungraded items, false for older batches (replay only).
"""

from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Request

from .. import schemas
from ..clock import Clock
from ..config import Settings
from ..deps import get_clock, get_db, get_settings, require_onboarded
from ..errors import ApiError
from ..services import bank, batches, stats

router = APIRouter()


@router.get("/api/history", response_model=schemas.HistoryResponse)
def history(
    request: Request,
    me: dict[str, Any] = Depends(require_onboarded),
    conn: sqlite3.Connection = Depends(get_db),
    clock: Clock = Depends(get_clock),
    cfg: Settings = Depends(get_settings),
) -> dict[str, Any]:
    q = bank.query_model(schemas.HistoryQuery, request.query_params)
    try:
        from_date = date.fromisoformat(q.from_)
        to_date = date.fromisoformat(q.to)
    except ValueError:
        raise ApiError("validation_error", details={"fields": {"from": "invalid date"}}) from None
    if to_date < from_date:
        raise ApiError("validation_error", details={"fields": {"to": "to must not precede from"}})
    if (to_date - from_date).days + 1 > stats.HISTORY_MAX_DAYS:
        raise ApiError("validation_error", details={"fields": {"to": f"range exceeds {stats.HISTORY_MAX_DAYS} days"}})
    return stats.history(conn, int(me["id"]), from_date, to_date, clock.now_utc(), cfg=cfg)


@router.get("/api/history/batches", response_model=schemas.Page[schemas.BatchSummary])
def history_batches(
    request: Request,
    me: dict[str, Any] = Depends(require_onboarded),
    conn: sqlite3.Connection = Depends(get_db),
    clock: Clock = Depends(get_clock),
    cfg: Settings = Depends(get_settings),
) -> dict[str, Any]:
    q = bank.query_model(schemas.PageQuery, request.query_params, int_fields=("page", "page_size"))
    return stats.batch_summaries(conn, int(me["id"]), q.page, q.page_size, clock.now_utc(), cfg=cfg)


@router.get("/api/batches/{batch_id}", response_model=schemas.TodayResponse)
def batch(
    batch_id: int,
    me: dict[str, Any] = Depends(require_onboarded),
    conn: sqlite3.Connection = Depends(get_db),
    clock: Clock = Depends(get_clock),
    cfg: Settings = Depends(get_settings),
) -> dict[str, Any]:
    return batches.today_response(conn, int(me["id"]), clock.now_utc(), batch_id=batch_id, cfg=cfg)


@router.get("/api/stats", response_model=schemas.Stats)
def get_stats(
    me: dict[str, Any] = Depends(require_onboarded),
    conn: sqlite3.Connection = Depends(get_db),
    clock: Clock = Depends(get_clock),
    cfg: Settings = Depends(get_settings),
) -> dict[str, Any]:
    return stats.overview(conn, int(me["id"]), clock.now_utc(), cfg=cfg)
