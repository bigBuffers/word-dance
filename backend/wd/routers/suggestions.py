"""整理建议 routes (WP3): ``GET /api/suggestions`` and accept / reject / undo (API.md 39–42)."""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, Request

from .. import schemas
from ..clock import Clock
from ..deps import current_user, get_clock, get_db
from ..services import bank, suggestions

router = APIRouter()


@router.get("/api/suggestions", response_model=schemas.SuggestionsResponse)
def list_suggestions(
    request: Request,
    me: dict[str, Any] = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict[str, Any]:
    q = bank.query_model(schemas.SuggestionsQuery, request.query_params)
    items, open_count = suggestions.list_suggestions(conn, int(me["id"]), q.status, now=clock.now_utc())
    return {"items": items, "open_count": open_count}


@router.post("/api/suggestions/{suggestion_id}/accept", response_model=schemas.SuggestionActionResponse)
def accept(
    suggestion_id: int,
    me: dict[str, Any] = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict[str, Any]:
    return {"result": suggestions.apply_suggestion(conn, int(me["id"]), suggestion_id, "accept", now=clock.now_utc())}


@router.post("/api/suggestions/{suggestion_id}/reject", response_model=schemas.EmptyResponse)
def reject(
    suggestion_id: int,
    me: dict[str, Any] = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict[str, Any]:
    suggestions.apply_suggestion(conn, int(me["id"]), suggestion_id, "reject", now=clock.now_utc())
    return {}


@router.post("/api/suggestions/{suggestion_id}/undo", response_model=schemas.SuggestionActionResponse)
def undo(
    suggestion_id: int,
    me: dict[str, Any] = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict[str, Any]:
    return {"result": suggestions.apply_suggestion(conn, int(me["id"]), suggestion_id, "undo", now=clock.now_utc())}
