"""``/api/onboarding*`` — API.md endpoints 12–13, DESIGN §6.2 (WP2).

Step 1 (``POST /api/onboarding``) stores the stage choice, push time and timezone, recomputes ``next_push_at``
and moves ``users.onboarding_state`` to ``screen``; it may be re-posted until the state is ``done``.
``POST /api/onboarding/complete`` reaches ``done`` only from ``screen`` (409 ``invalid_transition`` from
``pending``, idempotent 200 from ``done``) — there is no path that skips step 1.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, Request

from .. import db, security
from ..clock import to_iso
from ..deps import current_user, get_db
from ..errors import ApiError
from ..schemas import OnboardingCompleteResponse, OnboardingRequest, OnboardingResponse, stage_to_index

router = APIRouter()


@router.post("/api/onboarding", response_model=OnboardingResponse)
def save_onboarding(body: OnboardingRequest, request: Request, user: dict[str, Any] = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    if user["onboarding_state"] == "done":
        raise ApiError("invalid_transition", details={"from": "done", "action": "onboarding"})
    now = request.app.state.clock.now_utc()
    now_iso = to_iso(now)
    with db.tx(conn):
        conn.execute(
            "UPDATE user_settings SET stages_json = ?, current_stage = ?, timezone = ?, push_time = ?, next_push_at = ?, updated_at = ? WHERE user_id = ?",
            (
                security.stages_json(body.stages),
                stage_to_index(body.current_stage),
                body.timezone,
                body.push_time,
                security.next_push_iso(now, body.timezone, body.push_time),
                now_iso,
                user["id"],
            ),
        )
        conn.execute("UPDATE users SET onboarding_state = 'screen', updated_at = ? WHERE id = ?", (now_iso, user["id"]))
    return {"settings": security.settings_dto(conn, int(user["id"])), "onboarding_state": "screen"}


@router.post("/api/onboarding/complete", response_model=OnboardingCompleteResponse)
def complete_onboarding(request: Request, user: dict[str, Any] = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    state = user["onboarding_state"]
    if state == "done":
        return {"onboarding_state": "done"}
    if state != "screen":
        raise ApiError("invalid_transition", details={"from": state, "action": "complete"})
    now_iso = to_iso(request.app.state.clock.now_utc())
    conn.execute("UPDATE users SET onboarding_state = 'done', updated_at = ? WHERE id = ? AND onboarding_state = 'screen'", (now_iso, user["id"]))
    return {"onboarding_state": "done"}
