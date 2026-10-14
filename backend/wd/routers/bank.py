"""Bank routes (WP3): ``/api/bank*`` (API.md 33–38, 75).

Static paths are registered before ``/api/bank/{word_id}`` (API.md §1 route order). Quotas: custom adds 200/day
(``auth_throttle`` key ``custom:user:<id>``, shared with imports), consolidate-now once per 60 minutes.
"""

from __future__ import annotations

import sqlite3
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from .. import db, schemas
from ..clock import Clock, parse_iso, to_iso
from ..config import Settings
from ..deps import current_user, get_clock, get_db, get_settings
from ..errors import ApiError
from ..jobs import queue
from ..services import bank, words

router = APIRouter()

CONSOLIDATE_MANUAL_PRIORITY = 10
CONSOLIDATE_COOLDOWN = timedelta(minutes=60)

_BANK_STATE_FILTER = {
    "active": "uw.state IN ('new','learning')",
    "new": "uw.state = 'new'",
    "learning": "uw.state = 'learning'",
    "mastered": "uw.state = 'mastered'",
    "known": "uw.state = 'known'",
    "removed": "uw.state = 'removed'",
    "attention": "uw.state IN ('new','learning') AND uw.needs_attention = 1",
}
_BANK_ORDER = {
    "added": "uw.added_at DESC, uw.id DESC",
    "due": "(uw.due_at IS NULL), uw.due_at ASC, uw.id ASC",
    "alpha": "w.lemma ASC, uw.id ASC",
    "ease": "uw.ease ASC, uw.id ASC",
    "times_added": "uw.times_added DESC, uw.added_at DESC, uw.id DESC",
}


def _like_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# --------------------------------------------------------------------------------------------- list (33)
@router.get("/api/bank", response_model=schemas.BankResponse)
def bank_list(
    request: Request,
    me: dict[str, Any] = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict[str, Any]:
    uid = int(me["id"])
    q = bank.query_model(schemas.BankQuery, request.query_params)
    where = ["uw.user_id = :me", _BANK_STATE_FILTER[q.state]]
    params: dict[str, Any] = {"me": uid}
    if q.q:
        s = q.q.strip()
        key = words.normalise_lemma(s) if s.isascii() else None
        if key:
            where.append("(w.lemma >= :q AND w.lemma < :q || '~')")
            params["q"] = key
        elif s:
            where.append("w.translation LIKE :like ESCAPE '\\'")
            params["like"] = "%" + _like_escape(s) + "%"
    if q.origin:
        where.append("uw.origin = :origin")
        params["origin"] = q.origin
    body = "FROM user_words uw JOIN words w ON w.id = uw.word_id WHERE " + " AND ".join(where)
    total = int(conn.execute(f"SELECT COUNT(*) {body}", params).fetchone()[0])
    rows = conn.execute(
        f"SELECT uw.*, w.id AS w_id {body} ORDER BY {_BANK_ORDER[q.sort]} LIMIT :limit OFFSET :offset",
        {**params, "limit": q.page_size, "offset": (q.page - 1) * q.page_size},
    ).fetchall()
    items = []
    for r in rows:
        uw = {k: r[k] for k in r.keys() if k != "w_id"}
        word = words.word_row(conn, int(r["w_id"]))
        if word is None:  # pragma: no cover - FK guarantees the word exists
            continue
        items.append({**words.word_brief(conn, {**word, "my_state": uw["state"]}, uid), "mine": words.user_word_dict(conn, uw, uid)})
    counts = bank.bank_counts(conn, uid, now=clock.now_utc(), tz=bank.user_timezone(conn, uid))
    return {"items": items, "page": q.page, "page_size": q.page_size, "total": total, "counts": counts}


# ---------------------------------------------------------------------------------------- bulk add (34)
@router.post("/api/bank/add", response_model=schemas.AddResponse)
def bank_add(
    body: schemas.BankAddRequest,
    me: dict[str, Any] = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict[str, Any]:
    uid = int(me["id"])
    now = clock.now_utc()
    tokens = bank.split_tokens(body.text)
    if len(tokens) > bank.MAX_ADD_TOKENS:
        raise ApiError("too_many_words", details={"count": len(tokens), "max": bank.MAX_ADD_TOKENS})
    bank.check_daily_quota(conn, f"custom:user:{uid}", bank.CUSTOM_DAILY_CAP, now=to_iso(now), amount=max(1, len(tokens)))
    results = bank.add_custom_words(conn, uid, body.text, body.note, body.study_today, now, bank.user_timezone(conn, uid))
    out = bank.summarise(results)
    out["results"] = [r.as_dict() for r in results]
    return out


# -------------------------------------------------------------------------------------- add by id (35)
@router.post("/api/bank/add-word", response_model=schemas.AddResult)
def bank_add_word(
    body: schemas.BankAddWordRequest,
    me: dict[str, Any] = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> JSONResponse:
    uid = int(me["id"])
    now = to_iso(clock.now_utc())
    word = bank.visible_word(conn, me, body.word_id)
    bank.check_daily_quota(conn, f"custom:user:{uid}", bank.CUSTOM_DAILY_CAP, now=now)
    with db.tx(conn):
        res = bank.add_resolved(
            conn,
            uid,
            int(word["id"]),
            input_text=str(word["display"]),
            note=body.note,
            study_today=body.study_today,
            now=now,
            tz=bank.user_timezone(conn, uid),
        )
    payload = schemas.AddResult.model_validate(res.as_dict()).model_dump()
    return JSONResponse(status_code=200 if res.status == "exists" else 201, content=payload)


# ------------------------------------------------------------------------------------- consolidate (38)
@router.post("/api/bank/consolidate", status_code=202, response_model=schemas.ConsolidateResponse)
def bank_consolidate(
    me: dict[str, Any] = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
    clock: Clock = Depends(get_clock),
    cfg: Settings = Depends(get_settings),
) -> dict[str, Any]:
    uid = int(me["id"])
    now_dt = clock.now_utc()
    now = to_iso(now_dt)
    if not bank.ai_enabled(conn, cfg) or bank.ai_paused_until(conn, now) is not None:
        raise ApiError("ai_disabled")
    recent = conn.execute(
        "SELECT started_at FROM consolidation_runs WHERE user_id = ? AND started_at > ? ORDER BY started_at DESC LIMIT 1",
        (uid, to_iso(now_dt - CONSOLIDATE_COOLDOWN)),
    ).fetchone()
    if recent is not None:
        retry = int((parse_iso(str(recent[0])) + CONSOLIDATE_COOLDOWN - now_dt).total_seconds())
        raise ApiError("rate_limited", details={"retry_after_s": max(1, retry)})
    local_date = bank.local_date_str(now_dt, bank.user_timezone(conn, uid))
    job_id = queue.enqueue(
        conn,
        "consolidate_bank",
        {"user_id": uid, "trigger": "manual"},
        dedupe_key=f"consolidate:{uid}:{local_date}",
        priority=CONSOLIDATE_MANUAL_PRIORITY,
        now=now,
    )
    return {"job_id": job_id}


# ------------------------------------------------------------------------------------------ import (75)
@router.post("/api/bank/import", response_model=schemas.ImportResponse)
def bank_import(
    body: schemas.ImportRequest,
    me: dict[str, Any] = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict[str, Any]:
    uid = int(me["id"])
    now = clock.now_utc()
    key = f"custom:user:{uid}"
    if bank.quota_used(conn, key, to_iso(now)) >= bank.CUSTOM_DAILY_CAP:
        _, retry = bank._day_window(to_iso(now))
        raise ApiError("rate_limited", details={"retry_after_s": retry, "limit": bank.CUSTOM_DAILY_CAP})
    result = bank.import_rows(conn, uid, body.format, body.data, now, bank.user_timezone(conn, uid))
    bank.quota_consume(conn, key, max(1, result.pending_ai_created), to_iso(now))
    return result.as_dict()


# -------------------------------------------------------------------------------------------- patch (36)
@router.patch("/api/bank/{word_id}", response_model=schemas.UserWord)
def bank_patch(
    word_id: int,
    body: schemas.BankPatchRequest,
    me: dict[str, Any] = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict[str, Any]:
    uid = int(me["id"])
    word = bank.visible_word(conn, me, word_id)
    wid = int(word["id"])
    if bank.my_row(conn, uid, wid) is None:
        raise ApiError("word_not_found")
    now = clock.now_utc()
    out: dict[str, Any] | None = None
    if body.attention is not None:
        out = bank.set_attention(conn, uid, wid, body.attention, now)
    if "note" in body.model_fields_set:
        out = bank.update_note(conn, uid, wid, body.note, now)
    if out is None:  # pragma: no cover - the request model requires one of the two keys
        raise ApiError("validation_error", details={"fields": {"body": "至少提供 note 或 attention 之一"}})
    return out


# ------------------------------------------------------------------------------- accept suggestion (37)
@router.post("/api/bank/{word_id}/accept-suggestion", response_model=schemas.AcceptSuggestionResponse)
def bank_accept_suggestion(
    word_id: int,
    me: dict[str, Any] = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict[str, Any]:
    uid = int(me["id"])
    word = bank.visible_word(conn, me, word_id)
    wid = int(word["id"])
    now = clock.now_utc()
    tz = bank.user_timezone(conn, uid)
    with db.tx(conn):
        row = bank.my_row(conn, uid, wid)
        if row is None:
            raise ApiError("word_not_found")
        if row.get("suggested_word_id") is None:
            raise ApiError("invalid_transition", details={"from": row["state"], "action": "accept_suggestion"})
        target = bank.visible_word(conn, me, int(row["suggested_word_id"]))
        added = bank.apply_action(conn, uid, int(target["id"]), "add_custom", origin="custom", context="api", note=row.get("note"), input_text=row.get("input_text"), now=now, tz=tz)
        if str(row["state"]) != "removed":
            bank.apply_action(conn, uid, wid, "remove", origin="browse", context="api", now=now, tz=tz)
        conn.execute(
            "UPDATE user_words SET suggested_word_id = NULL, needs_attention = 0, attention_msg = NULL, updated_at = ? WHERE id = ?",
            (to_iso(now), row["id"]),
        )
    return {"removed_word_id": wid, "mine": added.mine}
