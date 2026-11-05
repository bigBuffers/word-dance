"""Word routes (WP3): ``GET /api/lookup`` (22, deliberately outside ``/api/words/``) and ``/api/words/*`` (23–30).

Route order follows API.md §1: ``POST /api/words/batch-mark`` is registered before the dynamic routes, and
``GET /api/words/{id_or_lemma}`` never matches a path with a ``/``. Every route applies the §1 visibility rule
(404 ``word_not_found`` for an invisible word). The explicit content request checks the Claude budget through
``wd.ai.budget.can_spend`` (WP5); the image report / 换一张 go through ``wd.images`` (WP6).
"""

from __future__ import annotations

import sqlite3
from typing import Any
from urllib.parse import unquote

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from .. import db, images, schemas
from ..ai import budget, failover
from ..clock import Clock, to_iso
from ..config import Settings
from ..deps import current_user, get_clock, get_db, get_settings, visible_word_sql
from ..errors import ApiError
from ..jobs import queue
from ..services import bank, ecdict, words

router = APIRouter()

ETA_PER_JOB_S = 30
LOOKUP_SUGGESTIONS = 5
FETCH_IMAGE_PRIORITY_USER = 10
CONTENT_REQUEST_PRIORITY = 10


def _now(clock: Clock) -> str:
    return to_iso(clock.now_utc())


# ---------------------------------------------------------------------------------------- lookup (22)
@router.get("/api/lookup", response_model=schemas.LookupPreview)
def lookup(
    q: str = Query(min_length=1, max_length=200),
    me: dict[str, Any] = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    uid = int(me["id"])
    out: dict[str, Any] = {
        "input": q,
        "normalized": None,
        "valid": False,
        "reason_zh": None,
        "via": "invalid",
        "match": None,
        "lemma_note_zh": None,
        "candidates": [],
        "suggestions": [],
        "mine": None,
    }
    norm = words.normalise_input(q)
    if not norm.ok:
        assert isinstance(norm, words.Invalid)
        out["reason_zh"] = norm.reason_zh
        return out
    assert isinstance(norm, words.Normalised)
    out.update(normalized=norm.lemma, valid=True, via="none")
    vis = visible_word_sql(me, alias="w")
    params = {"q": norm.lemma, "me": uid}
    exclude: int | None = None

    row = conn.execute(f"SELECT w.* FROM words w WHERE w.lemma = :q AND {vis}", params).fetchone()
    if row is not None:
        final, _ = words.follow_merge(conn, row)
        if words.is_visible(conn, final, uid):
            out.update(via="exact", match=words.word_brief(conn, final, uid), mine=words.my_user_word(conn, int(final["id"]), uid))
            exclude = int(final["id"])
    if out["via"] == "none":
        rows = conn.execute(
            f"SELECT w.*, wf.kind AS form_kind FROM word_forms wf JOIN words w ON w.id = wf.word_id WHERE wf.form = :q AND {vis} "
            f"ORDER BY {words._form_kind_order('wf.kind')}, w.lemma",
            params,
        ).fetchall()
        targets: dict[int, tuple[dict[str, Any], str]] = {}
        for r in rows:
            d = {k: r[k] for k in r.keys()}
            form_kind = str(d.pop("form_kind"))
            final, _ = words.follow_merge(conn, d)
            if words.is_visible(conn, final, uid):
                targets.setdefault(int(final["id"]), (final, form_kind))
        if len(targets) == 1:
            final, form_kind = next(iter(targets.values()))
            out.update(
                via="form",
                match=words.word_brief(conn, final, uid),
                lemma_note_zh=words.lemma_note_zh(str(final["display"]), form_kind),
                mine=words.my_user_word(conn, int(final["id"]), uid),
            )
            exclude = int(final["id"])
        elif len(targets) > 1:
            ordered = sorted(targets.values(), key=lambda t: str(t[0]["lemma"]))
            out.update(via="ambiguous", candidates=[words.word_brief(conn, t[0], uid) for t in ordered])
        elif ecdict.lookup(norm.lemma) is not None:
            out["via"] = "ecdict"

    sug = conn.execute(
        f"SELECT w.* FROM words w WHERE w.lemma >= :q AND w.lemma < :q || '~' AND w.merged_into_word_id IS NULL AND {vis} "
        "AND w.id != :exclude ORDER BY (w.frq IS NULL OR w.frq = 0), w.frq, w.lemma LIMIT :limit",
        {**params, "exclude": -1 if exclude is None else exclude, "limit": LOOKUP_SUGGESTIONS},
    ).fetchall()
    out["suggestions"] = words.word_briefs(conn, sug, uid)
    return out


# ------------------------------------------------------------------------------------ batch-mark (27)
@router.post("/api/words/batch-mark", response_model=schemas.BatchMarkResponse)
def batch_mark(
    body: schemas.BatchMarkRequest,
    me: dict[str, Any] = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict[str, Any]:
    uid = int(me["id"])
    tz = bank.user_timezone(conn, uid)
    now = clock.now_utc()
    results: list[dict[str, Any]] = []
    updated = 0
    for item in body.items:
        try:
            word = bank.visible_word(conn, me, item.word_id)
            r = bank.apply_action(conn, uid, int(word["id"]), item.action, origin="browse", context="browse", now=now, tz=tz)
            results.append({"word_id": item.word_id, "ok": True, "state": r.state, "error": None})
            if r.status != "noop":
                updated += 1
        except ApiError as e:
            row = bank.my_row(conn, uid, item.word_id)
            results.append({"word_id": item.word_id, "ok": False, "state": None if row is None else row["state"], "error": e.code})
    return {"updated": updated, "results": results}


# ----------------------------------------------------------------------------------------- detail (23)
def _resolve_path(conn: sqlite3.Connection, me: dict[str, Any], id_or_lemma: str) -> tuple[int, str | None]:
    """``(word_id, redirected_from)`` for the path segment: numeric id, exact lemma, or a unique inflected form."""
    uid = int(me["id"])
    seg = unquote(id_or_lemma).strip()
    if seg.isdigit():
        return int(seg), None
    norm = words.normalise_input(seg)
    if not norm.ok:
        raise ApiError("word_not_found")
    assert isinstance(norm, words.Normalised)
    row = words.word_by_lemma(conn, norm.lemma)
    if row is not None:
        return int(row["id"]), None
    rows = conn.execute(
        "SELECT w.* FROM word_forms wf JOIN words w ON w.id = wf.word_id WHERE wf.form = ? ORDER BY w.lemma",
        (norm.lemma,),
    ).fetchall()
    finals: dict[int, dict[str, Any]] = {}
    for r in rows:
        final, _ = words.follow_merge(conn, r)
        if words.is_visible(conn, final, uid):
            finals.setdefault(int(final["id"]), final)
    if len(finals) == 1:
        return next(iter(finals)), norm.lemma
    if len(finals) > 1:
        ordered = sorted(finals.values(), key=lambda w: str(w["lemma"]))
        raise ApiError("ambiguous_form", details={"form": norm.lemma, "candidates": [words.word_brief(conn, w, uid) for w in ordered]})
    raise ApiError("word_not_found")


@router.get("/api/words/{id_or_lemma}", response_model=schemas.WordDetail)
def detail(
    id_or_lemma: str,
    me: dict[str, Any] = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
    clock: Clock = Depends(get_clock),
    cfg: Settings = Depends(get_settings),
) -> dict[str, Any]:
    uid = int(me["id"])
    now = _now(clock)
    wid, redirected = _resolve_path(conn, me, id_or_lemma)
    data = words.word_detail(conn, wid, uid, now=now)
    if redirected and not data.get("redirected_from"):
        data["redirected_from"] = redirected
    if data["content_state"] == "queued":
        data["content_deferred_until"] = bank.content_deferred_until(conn, int(data["word"]["id"]), now=now, cfg=cfg)
    return data


# --------------------------------------------------------------------------------- content / image (24, 25)
def _eta_s(conn: sqlite3.Connection, word_id: int) -> int | None:
    job = queue.live_job(conn, f"content:{int(word_id)}")
    if job is None:
        return None
    if job.status == "running":
        return ETA_PER_JOB_S
    ahead = int(
        conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE type = 'generate_content' AND status = 'queued' AND (priority, run_after, id) < (?, ?, ?)",
            (job.priority, job.run_after, job.id),
        ).fetchone()[0]
    )
    return (ahead + 1) * ETA_PER_JOB_S


@router.get("/api/words/{word_id}/content", response_model=schemas.ContentResponse)
def content(
    word_id: int,
    me: dict[str, Any] = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
    clock: Clock = Depends(get_clock),
    cfg: Settings = Depends(get_settings),
) -> dict[str, Any]:
    word = bank.visible_word(conn, me, word_id)
    wid = int(word["id"])
    state = word.get("content_state") or "none"
    now = _now(clock)
    deferred: str | None = None
    eta: int | None = None
    if state == "queued":
        deferred = bank.content_deferred_until(conn, wid, now=now, cfg=cfg)
        if deferred is None and bank.ai_enabled(conn, cfg):
            eta = _eta_s(conn, wid)
    return {"state": state, "content": words.active_content(conn, word), "eta_s": eta, "deferred_until": deferred}


@router.get("/api/words/{word_id}/image", response_model=schemas.ImageMeta)
def image(word_id: int, me: dict[str, Any] = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    word = bank.visible_word(conn, me, word_id)
    return words.image_meta_for(conn, int(word["id"]))


# ------------------------------------------------------------------------------------------- mark (26)
@router.post("/api/words/{word_id}/mark", response_model=schemas.MarkResponse)
def mark(
    word_id: int,
    body: schemas.MarkRequest,
    me: dict[str, Any] = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict[str, Any]:
    uid = int(me["id"])
    word = bank.visible_word(conn, me, word_id)
    context = body.context or "api"
    r = bank.apply_action(
        conn,
        uid,
        int(word["id"]),
        body.action,
        origin=bank.origin_for_context(context),
        context=context,
        note=body.note,
        now=clock.now_utc(),
        tz=bank.user_timezone(conn, uid),
    )
    return r.response()


# ----------------------------------------------------------------------------------------- report (28)
@router.post("/api/words/{word_id}/report", status_code=201, response_model=schemas.ReportCreatedResponse)
def report(
    word_id: int,
    body: schemas.ReportRequest,
    me: dict[str, Any] = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict[str, Any]:
    uid = int(me["id"])
    word = bank.visible_word(conn, me, word_id)
    wid = int(word["id"])
    now = _now(clock)
    bank.check_daily_quota(conn, f"report:user:{uid}", bank.REPORTS_DAILY_CAP, now=now)
    with db.tx(conn):
        cur = conn.execute(
            "INSERT INTO content_reports(user_id, word_id, target, reason, note, image_id, content_id, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (uid, wid, body.target, body.reason, body.note, word.get("active_image_id"), word.get("active_content_id"), now),
        )
        report_id = int(cur.lastrowid)
        if body.target == "image" and word.get("active_image_id") is not None:
            # WP6: active image → rejected, system_events('image_rejected'), fetch_image with it excluded
            images.reject_active_image(conn, wid, reason=body.reason, priority=FETCH_IMAGE_PRIORITY_USER, now=now)
    return {"id": report_id}


# ------------------------------------------------------------------------------------ image refresh (29)
@router.post("/api/words/{word_id}/image/refresh", status_code=202, response_model=schemas.ImageRefreshResponse)
def image_refresh(
    word_id: int,
    me: dict[str, Any] = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict[str, Any]:
    uid = int(me["id"])
    word = bank.visible_word(conn, me, word_id)
    wid = int(word["id"])
    now = _now(clock)
    bank.check_daily_quota(conn, f"refresh:user:{uid}", bank.IMAGE_REFRESH_DAILY_CAP, now=now)
    # WP6: the current image stays active until a replacement lands; it and every rejected one are excluded
    job_id = images.request_refresh(conn, wid, priority=FETCH_IMAGE_PRIORITY_USER, now=now)
    if job_id is None:
        raise ApiError("word_not_found")
    return {"job_id": int(job_id), "image_state": "queued"}


# ---------------------------------------------------------------------------------- content request (30)
@router.post("/api/words/{word_id}/content/request", response_model=schemas.ContentRequestResponse)
def content_request(
    word_id: int,
    me: dict[str, Any] = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
    clock: Clock = Depends(get_clock),
    cfg: Settings = Depends(get_settings),
) -> JSONResponse:
    uid = int(me["id"])
    word = bank.visible_word(conn, me, word_id)
    wid = int(word["id"])
    now = _now(clock)
    if word.get("is_valid_english") != 1:
        raise ApiError("invalid_transition", details={"from": "provisional" if word.get("is_valid_english") is None else "invalid", "action": "content_request"})
    state = word.get("content_state") or "none"
    if state in ("ready", "queued"):
        live = queue.live_job(conn, f"content:{wid}")
        body = schemas.ContentRequestResponse(job_id=None if live is None else live.id, state=state)
        return JSONResponse(status_code=200, content=body.model_dump())
    if not bank.ai_enabled(conn, cfg) or bank.ai_paused_until(conn, now, cfg=cfg, kind="content") is not None:
        raise ApiError("ai_disabled")
    bank.check_daily_quota(conn, f"content_req:user:{uid}", bank.CONTENT_REQUESTS_DAILY_CAP, now=now)
    provider, resumes_at = failover.choose(conn, cfg, kind="content", priority=CONTENT_REQUEST_PRIORITY, now=now)
    ok = provider is not None
    if ok:
        ok, resumes_at = budget.can_spend(conn, "content", 1, CONTENT_REQUEST_PRIORITY, now, cfg=cfg, provider=provider)
    if not ok:
        raise ApiError("budget_exhausted", details={"resumes_at": resumes_at})
    with db.tx(conn):
        job_id = queue.enqueue(conn, "generate_content", {"word_id": wid}, dedupe_key=f"content:{wid}", priority=CONTENT_REQUEST_PRIORITY, now=now)
        conn.execute("UPDATE words SET content_state = 'queued', updated_at = ? WHERE id = ?", (now, wid))
    body = schemas.ContentRequestResponse(job_id=job_id, state="queued")
    return JSONResponse(status_code=202, content=body.model_dump())
