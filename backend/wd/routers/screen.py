"""Screening routes (WP3): ``GET /api/screen/next`` (31) and ``POST /api/screen/verdict`` (32)."""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, Request

from .. import schemas
from ..clock import Clock
from ..config import Settings
from ..deps import current_user, get_clock, get_db, get_settings
from ..services import bank, screen

router = APIRouter()


@router.get("/api/screen/next", response_model=schemas.ScreenNextResponse)
def screen_next(request: Request, me: dict[str, Any] = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    q = bank.query_model(schemas.ScreenNextQuery, request.query_params)
    items, remaining = screen.screen_next(conn, int(me["id"]), q.stage, q.count)
    return {"items": items, "remaining": remaining}


@router.post("/api/screen/verdict", response_model=schemas.ScreenResponse)
def screen_verdict(
    body: schemas.ScreenVerdictRequest,
    me: dict[str, Any] = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
    clock: Clock = Depends(get_clock),
    cfg: Settings = Depends(get_settings),
) -> dict[str, Any]:
    uid = int(me["id"])
    word = bank.visible_word(conn, me, body.word_id)
    return screen.apply_verdict(
        conn,
        uid,
        int(word["id"]),
        body.verdict,
        client_event_id=body.client_event_id,
        context=body.context,
        push_item_id=None,
        now=clock.now_utc(),
        tz=bank.user_timezone(conn, uid),
        cfg=cfg,
    )
