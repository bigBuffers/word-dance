"""``prewarm_plan`` handler and plan creation (CLAUDE_INTEGRATION §6.1 "prewarm_plan mechanics", API.md 67).

Admin only, never automatic. A plan job (``{"plan_id","stage","limit","max_budget_usd"}``, dedupe ``prewarm:<plan_id>``,
priority 90) runs in passes: each pass selects up to ``5 × WD_AI_BATCH_SIZE`` candidate words of the stage (public,
valid, ``content_state IN ('none','failed')``, not yet enqueued, by frequency), enqueues ``generate_content
{"word_id","plan_id"}`` at priority 90 (dedupe ``content:<word_id>``) and defers itself two minutes. The content
handler credits ``cost_usd / items_returned`` to ``kv prewarm:<plan_id>:spent``; the plan finishes (``done``,
``result_json = {planned, spent, stopped}``) when ``spent ≥ max_budget_usd``, ``planned ≥ limit`` or no candidates
remain, cancelling the content jobs it enqueued that are still queued. The global prewarm sub-cap applies on top.
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from datetime import timedelta
from typing import Any

from .. import db
from ..clock import parse_iso, to_iso
from ..config import Settings
from ..interfaces import Job
from ..jobs import queue
from ..jobs.registry import JobContext, register
from ..schemas import STAGE_ORDER

log = logging.getLogger("wd.ai.prewarm")

PRIORITY = 90
PASS_MULTIPLIER = 5
PASS_INTERVAL = timedelta(minutes=2)
# derived from the one stage enum (schemas.py, PLAN R-1): the flag column per code, plus "all" = every word in some list
STAGE_COLUMNS: dict[str, str] = {s: f"stage_{s}" for s in STAGE_ORDER}
STAGES: tuple[str, ...] = (*STAGE_ORDER, "all")


def _stage_sql(stage: str) -> str:
    if stage == "all":
        return "w.stage_min IS NOT NULL"
    return f"w.{STAGE_COLUMNS[stage]} = 1"


def candidates(conn: sqlite3.Connection, stage: str, limit: int) -> list[int]:
    """Words of ``stage`` still lacking content and not already queued, most frequent first."""
    if stage not in STAGES:
        raise ValueError(f"unknown stage {stage!r}")
    rows = conn.execute(
        "SELECT w.id FROM words w "
        f"WHERE w.is_public = 1 AND w.is_valid_english = 1 AND w.merged_into_word_id IS NULL AND w.content_state IN ('none','failed') AND {_stage_sql(stage)} "
        "  AND NOT EXISTS (SELECT 1 FROM jobs j WHERE j.dedupe_key = 'content:' || w.id AND j.status IN ('queued','running')) "
        "ORDER BY (w.frq IS NULL OR w.frq = 0), w.frq, w.lemma LIMIT ?",
        (max(0, int(limit)),),
    ).fetchall()
    return [int(r[0]) for r in rows]


def count_candidates(conn: sqlite3.Connection, stage: str) -> int:
    if stage not in STAGES:
        raise ValueError(f"unknown stage {stage!r}")
    row = conn.execute(
        "SELECT COUNT(*) FROM words w "
        f"WHERE w.is_public = 1 AND w.is_valid_english = 1 AND w.merged_into_word_id IS NULL AND w.content_state IN ('none','failed') AND {_stage_sql(stage)} "
        "  AND NOT EXISTS (SELECT 1 FROM jobs j WHERE j.dedupe_key = 'content:' || w.id AND j.status IN ('queued','running'))"
    ).fetchone()
    return int(row[0] or 0)


def _kv_key(plan_id: str, suffix: str) -> str:
    return f"prewarm:{plan_id}:{suffix}"


def plan_state(conn: sqlite3.Connection, plan_id: str) -> tuple[int, float]:
    """``(planned, spent)`` from ``kv prewarm:<plan_id>:planned`` / ``:spent``."""
    try:
        planned = int(db.kv_get(conn, _kv_key(plan_id, "planned"), "0") or 0)
    except ValueError:
        planned = 0
    try:
        spent = float(db.kv_get(conn, _kv_key(plan_id, "spent"), "0") or 0)
    except ValueError:
        spent = 0.0
    return planned, spent


def create_plan(conn: sqlite3.Connection, *, stage: str, limit: int, max_budget_usd: float, now: str, plan_id: str | None = None) -> tuple[int, int, str]:
    """Enqueue a plan job; returns ``(job_id, planned, plan_id)`` where ``planned`` is how many words the plan can cover."""
    if stage not in STAGES:
        raise ValueError(f"unknown stage {stage!r}")
    plan_id = plan_id or uuid.uuid4().hex
    planned = min(int(limit), count_candidates(conn, stage))
    with db.maybe_tx(conn):
        job_id = queue.enqueue(
            conn,
            "prewarm_plan",
            {"plan_id": plan_id, "stage": stage, "limit": int(limit), "max_budget_usd": float(max_budget_usd)},
            dedupe_key=f"prewarm:{plan_id}",
            priority=PRIORITY,
            max_attempts=10,
            now=now,
        )
        db.kv_set(conn, _kv_key(plan_id, "planned"), "0", now=now)
        db.kv_set(conn, _kv_key(plan_id, "spent"), "0", now=now)
    return job_id, planned, plan_id


def queued_plan_jobs(conn: sqlite3.Connection, plan_id: str) -> list[int]:
    rows = conn.execute(
        "SELECT id FROM jobs WHERE type = 'generate_content' AND status = 'queued' AND json_extract(payload_json, '$.plan_id') = ?",
        (plan_id,),
    ).fetchall()
    return [int(r[0]) for r in rows]


def cancel_leftovers(conn: sqlite3.Connection, plan_id: str, *, now: str) -> int:
    """Cancel the plan's content jobs that are still queued and reset their words to ``content_state='none'``."""
    ids = queued_plan_jobs(conn, plan_id)
    if not ids:
        return 0
    marks = ",".join("?" * len(ids))
    with db.maybe_tx(conn):
        word_ids = [int(r[0]) for r in conn.execute(f"SELECT json_extract(payload_json, '$.word_id') FROM jobs WHERE id IN ({marks})", ids)]
        cancelled = queue.cancel(conn, ids, now=now)
        if word_ids:
            wmarks = ",".join("?" * len(word_ids))
            conn.execute(f"UPDATE words SET content_state = 'none', updated_at = ? WHERE id IN ({wmarks}) AND content_state = 'queued'", (now, *word_ids))
    return cancelled


def run_pass(ctx: JobContext, conn: sqlite3.Connection, job: Job, *, now: str) -> dict[str, Any]:
    """One pass of the plan: finish it, or fan out the next group and defer two minutes."""
    cfg: Settings = ctx.cfg
    payload = job.payload
    plan_id = payload.get("plan_id")
    stage = payload.get("stage") if payload.get("stage") in STAGES else None
    if not isinstance(plan_id, str) or not plan_id or stage is None:
        queue.fail(conn, job.id, "prewarm_plan: payload needs plan_id and stage", now=now)
        return {"error": "bad_payload"}
    try:
        limit = int(payload.get("limit") or 0)
        max_budget = float(payload.get("max_budget_usd") or 0)
    except (TypeError, ValueError):
        queue.fail(conn, job.id, "prewarm_plan: limit / max_budget_usd must be numbers", now=now)
        return {"error": "bad_payload"}
    planned, spent = plan_state(conn, plan_id)
    stopped: str | None = None
    if spent >= max_budget:
        stopped = "budget"
    elif planned >= limit:
        stopped = "limit"
    ids: list[int] = []
    if stopped is None:
        ids = candidates(conn, stage, min(PASS_MULTIPLIER * cfg.ai_batch_size, limit - planned))
        if not ids:
            stopped = "no_candidates"
    if stopped is not None:
        # only a budget stop cancels the jobs still queued (§6.1); a plan that reached its limit lets them run
        cancelled = cancel_leftovers(conn, plan_id, now=now) if stopped == "budget" else 0
        result = {"plan_id": plan_id, "planned": planned, "spent": round(spent, 6), "stopped": stopped, "cancelled": cancelled}
        queue.finish(conn, job.id, result, now=now)
        ctx.log.info("prewarm plan %s finished (%s): planned %d, spent $%.4f, cancelled %d", plan_id, stopped, planned, spent, cancelled, extra={"job_id": job.id, "job_type": job.type, "event": "prewarm_done"})
        return result
    with db.maybe_tx(conn):
        for wid in ids:
            ctx.enqueue(conn, "generate_content", {"word_id": wid, "plan_id": plan_id}, dedupe_key=f"content:{wid}", priority=PRIORITY, now=now)
        marks = ",".join("?" * len(ids))
        conn.execute(f"UPDATE words SET content_state = 'queued', updated_at = ? WHERE id IN ({marks}) AND content_state IN ('none','failed')", (now, *ids))
        planned += len(ids)
        db.kv_set(conn, _kv_key(plan_id, "planned"), str(planned), now=now)
        queue.defer(conn, [job.id], to_iso(parse_iso(now) + PASS_INTERVAL), now=now)
    ctx.log.info("prewarm plan %s: %d content jobs enqueued (planned %d/%d, spent $%.4f)", plan_id, len(ids), planned, limit, spent, extra={"job_id": job.id, "job_type": job.type, "event": "prewarm_pass"})
    return {"plan_id": plan_id, "enqueued": len(ids), "planned": planned, "spent": round(spent, 6)}


@register("prewarm_plan")
def handle_prewarm_plan(ctx: JobContext, jobs: list[Job]) -> None:
    conn = ctx.db()
    try:
        for job in jobs:
            run_pass(ctx, conn, job, now=ctx.now())
    finally:
        conn.close()


__all__ = ["PASS_MULTIPLIER", "PRIORITY", "STAGES", "cancel_leftovers", "candidates", "count_candidates", "create_plan", "handle_prewarm_plan", "plan_state", "run_pass"]
