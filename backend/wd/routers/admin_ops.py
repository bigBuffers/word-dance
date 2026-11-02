"""Admin operations (WP5) — API.md endpoints 54–55, 60–69, 72–74.

Overview and health numbers come straight from the tables (``jobs``, ``ai_calls``, ``words``, ``word_images``,
``kv``); the queue/AI actions go through ``wd.jobs.queue`` / ``wd.ai.*``, the image tiles / provider quotas /
refetch through ``wd.images`` (WP6) and the manual push through ``wd.services.batches.push_now`` (WP4).
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request

from .. import db, images, schemas
from ..ai import budget, ledger, prewarm, probe
from ..clock import Clock, local_date, parse_iso, to_iso
from ..config import Settings
from ..deps import get_clock, get_db, get_settings, require_admin
from ..errors import ApiError
from ..images import quota as image_quota
from ..jobs import lease, queue
from ..jobs.registry import JobContext
from ..services import bank, batches

router = APIRouter()

EVENTS_24H_LIMIT = 100
REGENERATE_PRIORITY = 10
REFETCH_PRIORITY = 10
PROBE_MIN_INTERVAL = timedelta(minutes=1)
MANUAL_PAUSE = timedelta(hours=24)
SCHEDULER_STALE_TICKS = 3


def _now(clock: Clock) -> str:
    return to_iso(clock.now_utc())


def _threads(request: Request) -> list[Any]:
    return list(getattr(request.app.state, "threads", []) or [])


def _thread_alive(request: Request, prefix: str) -> bool:
    for t in _threads(request):
        name = str(getattr(t, "worker_id", None) or getattr(t, "name", ""))
        if name.startswith(prefix) and callable(getattr(t, "is_alive", None)) and t.is_alive():
            return True
    return False


def _scheduler_alive(request: Request, conn: sqlite3.Connection, cfg: Settings, now: str) -> tuple[bool, str | None]:
    last_tick = db.kv_get(conn, "last_tick_at")
    if _thread_alive(request, "scheduler"):
        return True, last_tick
    if last_tick and parse_iso(last_tick) >= parse_iso(now) - timedelta(seconds=SCHEDULER_STALE_TICKS * cfg.tick_seconds):
        return True, last_tick
    return False, last_tick


def _photo_mix(conn: sqlite3.Connection) -> dict[str, int]:
    return images.photo_mix(conn)


def _provider_status(conn: sqlite3.Connection, cfg: Settings, now: str) -> list[dict[str, Any]]:
    return [dict(r) for r in image_quota.status(conn, cfg, now)]


def _event_dto(row: sqlite3.Row) -> dict[str, Any]:
    try:
        detail = json.loads(row["detail_json"] or "{}")
    except ValueError:
        detail = {"raw": row["detail_json"]}
    return {"id": int(row["id"]), "kind": row["kind"], "detail": detail if isinstance(detail, dict) else {"value": detail}, "created_at": row["created_at"]}


def _job_dto(job) -> dict[str, Any]:
    return {
        "id": job.id,
        "type": job.type,
        "payload": job.payload,
        "dedupe_key": job.dedupe_key,
        "priority": job.priority,
        "status": job.status,
        "attempts": job.attempts,
        "max_attempts": job.max_attempts,
        "run_after": job.run_after,
        "locked_by": job.locked_by,
        "last_error": job.last_error,
        "created_at": job.created_at,
        "finished_at": job.finished_at,
    }


# ------------------------------------------------------------------------------------------ 54
@router.get("/api/admin/overview", response_model=schemas.AdminOverview)
def overview(
    request: Request,
    admin: dict[str, Any] = Depends(require_admin),
    conn: sqlite3.Connection = Depends(get_db),
    clock: Clock = Depends(get_clock),
    cfg: Settings = Depends(get_settings),
) -> dict[str, Any]:
    now = _now(clock)
    week_ago = to_iso(parse_iso(now) - timedelta(days=7))
    day_ago = to_iso(parse_iso(now) - timedelta(hours=24))
    today = local_date(parse_iso(now), cfg.tz).isoformat()
    users_total = int(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0])
    active_7d = int(
        conn.execute(
            "SELECT COUNT(*) FROM users u WHERE (u.last_login_at IS NOT NULL AND u.last_login_at >= ?) "
            "OR EXISTS (SELECT 1 FROM sessions s WHERE s.user_id = u.id AND s.last_seen_at >= ?)",
            (week_ago, week_ago),
        ).fetchone()[0]
    )
    w = conn.execute(
        "SELECT COUNT(*), SUM(content_state = 'ready'), SUM(source = 'user' OR created_by_user_id IS NOT NULL), SUM(is_valid_english IS NULL) "
        "FROM words WHERE merged_into_word_id IS NULL"
    ).fetchone()
    mix = _photo_mix(conn)
    jobs_row = conn.execute("SELECT SUM(status = 'queued'), SUM(status = 'running'), SUM(status = 'dead') FROM jobs").fetchone()
    by_type = {str(r[0]): int(r[1]) for r in conn.execute("SELECT type, COUNT(*) FROM jobs WHERE status IN ('queued','running') GROUP BY type ORDER BY type")}
    sched_alive, last_tick = _scheduler_alive(request, conn, cfg, now)
    events = [_event_dto(r) for r in conn.execute("SELECT * FROM system_events WHERE created_at >= ? ORDER BY created_at DESC, id DESC LIMIT ?", (day_ago, EVENTS_24H_LIMIT))]
    return {
        "users": {"total": users_total, "active_7d": active_7d},
        "words": {
            "total": int(w[0] or 0),
            "with_content": int(w[1] or 0),
            "with_photo": mix["with_photo"],
            "with_claude_svg": mix["with_claude_svg"],
            "card_only": mix["card_only"],
            "user_added": int(w[2] or 0),
            "pending_validation": int(w[3] or 0),
        },
        "bank_entries": int(conn.execute("SELECT COUNT(*) FROM user_words WHERE state IN ('new','learning')").fetchone()[0]),
        "batches_today": int(conn.execute("SELECT COUNT(*) FROM push_batches WHERE local_date = ?", (today,)).fetchone()[0]),
        "jobs": {"queued": int(jobs_row[0] or 0), "running": int(jobs_row[1] or 0), "dead": int(jobs_row[2] or 0), "by_type": by_type},
        "ai": budget.spend_summary(conn, cfg, now),
        "images": {"providers": _provider_status(conn, cfg, now)},
        "scheduler": {"last_tick_at": last_tick, "alive": sched_alive},
        "events_24h": events,
    }


# ------------------------------------------------------------------------------------------ 55
@router.get("/api/admin/health", response_model=schemas.AdminHealth)
def health(
    request: Request,
    admin: dict[str, Any] = Depends(require_admin),
    conn: sqlite3.Connection = Depends(get_db),
    clock: Clock = Depends(get_clock),
    cfg: Settings = Depends(get_settings),
) -> dict[str, Any]:
    now = _now(clock)
    try:
        conn.execute("SELECT 1").fetchone()
        db_ok = True
    except sqlite3.Error:
        db_ok = False
    size = 0
    for suffix in ("", "-wal"):
        p = cfg.db_path.parent / (cfg.db_path.name + suffix)
        if p.is_file():
            size += p.stat().st_size
    try:
        free = int(shutil.disk_usage(cfg.data_dir).free)
    except OSError:
        free = 0
    sched_alive, last_tick = _scheduler_alive(request, conn, cfg, now)
    backup_raw = db.kv_get(conn, "backup.last")
    last_backup = None
    if backup_raw:
        try:
            parsed = json.loads(backup_raw)
            if isinstance(parsed, dict) and {"file", "at", "bytes"} <= set(parsed):
                last_backup = {"file": str(parsed["file"]), "at": str(parsed["at"]), "bytes": int(parsed["bytes"])}
        except (ValueError, TypeError):
            last_backup = None
    held = lease.read(conn)
    return {
        "db_ok": db_ok,
        "db_size_bytes": size,
        "disk_free_bytes": free,
        "data_dir": str(cfg.data_dir),
        "scheduler_alive": sched_alive,
        "scheduler_last_tick_at": last_tick,
        "claude_worker_alive": _thread_alive(request, "claude-"),
        "io_worker_alive": _thread_alive(request, "io-"),
        "claude_bin": {
            "path": cfg.claude_bin,
            "version": db.kv_get(conn, "claude.version"),
            "ok": db.kv_get(conn, "claude.available") == "1",
            "flag_tier": 1 if db.kv_get(conn, "claude.flag_tier", "0") == "1" else 0,
            "last_probe_at": db.kv_get(conn, "claude.last_probe_at"),
        },
        "seed_version": db.kv_get(conn, "seed_version"),
        "migrations_version": db.current_version(conn),
        "worker_lease": None if held is None else {"instance": str(held["instance"]), "expires_at": str(held["expires_at"])},
        "last_backup": last_backup,
    }


# ------------------------------------------------------------------------------------ 60–63 jobs
@router.get("/api/admin/jobs", response_model=schemas.Page[schemas.Job])
def list_jobs(
    q: Annotated[schemas.AdminJobsQuery, Query()],
    admin: dict[str, Any] = Depends(require_admin),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    where: list[str] = []
    params: list[Any] = []
    if q.status:
        where.append("status = ?")
        params.append(q.status)
    if q.type:
        where.append("type = ?")
        params.append(q.type)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    total = int(conn.execute(f"SELECT COUNT(*) FROM jobs {clause}", params).fetchone()[0])
    rows = conn.execute(f"SELECT * FROM jobs {clause} ORDER BY id DESC LIMIT ? OFFSET ?", (*params, q.page_size, (q.page - 1) * q.page_size)).fetchall()
    from ..interfaces import Job as JobRow

    return {"items": [_job_dto(JobRow.from_row(r)) for r in rows], "page": q.page, "page_size": q.page_size, "total": total}


def _retry_job(conn: sqlite3.Connection, job_id: int, now: str):
    job = queue.get_job(conn, job_id)
    if job is None:
        raise ApiError("not_found")
    if job.status == "running":
        raise ApiError("invalid_transition", details={"from": job.status, "action": "retry"})
    try:
        with db.tx(conn):
            conn.execute(
                "UPDATE jobs SET status = 'queued', attempts = 0, run_after = ?, locked_at = NULL, locked_by = NULL, finished_at = NULL, updated_at = ? WHERE id = ?",
                (now, now, job_id),
            )
    except sqlite3.IntegrityError:
        raise ApiError("invalid_transition", details={"from": job.status, "action": "retry", "reason": "a live job holds the same dedupe key"}) from None
    return queue.get_job(conn, job_id)


@router.post("/api/admin/jobs/requeue-dead", response_model=schemas.RequeueDeadResponse)
def requeue_dead(
    admin: dict[str, Any] = Depends(require_admin),
    conn: sqlite3.Connection = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict[str, Any]:
    from ..jobs import worker

    return {"requeued": worker.requeue_dead_jobs(conn, now=_now(clock))}


@router.post("/api/admin/jobs/run-once", response_model=schemas.RunOnceResponse)
def run_once(
    request: Request,
    admin: dict[str, Any] = Depends(require_admin),
    clock: Clock = Depends(get_clock),
    cfg: Settings = Depends(get_settings),
) -> dict[str, Any]:
    if not cfg.dev:
        raise ApiError("forbidden", details={"reason": "run-once is available only with WD_DEV=1"})
    from ..jobs import worker

    ctx = JobContext(
        db=lambda: db.connect(cfg.db_path),
        cfg=cfg,
        clock=clock,
        enqueue=queue.enqueue,
        worker_id="admin-once",
        boot_id=str(getattr(request.app.state, "boot_id", "") or "admin"),
    )
    return {"processed": worker.drain(ctx)}


@router.post("/api/admin/jobs/{job_id}/retry", response_model=schemas.Job)
def retry_job(
    job_id: int,
    admin: dict[str, Any] = Depends(require_admin),
    conn: sqlite3.Connection = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict[str, Any]:
    return _job_dto(_retry_job(conn, job_id, _now(clock)))


# ------------------------------------------------------------------------------------- 64–66 AI
@router.get("/api/admin/ai/calls", response_model=schemas.AiCallsPage)
def ai_calls(
    q: Annotated[schemas.PageQuery, Query()],
    admin: dict[str, Any] = Depends(require_admin),
    conn: sqlite3.Connection = Depends(get_db),
    clock: Clock = Depends(get_clock),
    cfg: Settings = Depends(get_settings),
) -> dict[str, Any]:
    now = _now(clock)
    total = int(conn.execute("SELECT COUNT(*) FROM ai_calls").fetchone()[0])
    rows = conn.execute("SELECT * FROM ai_calls ORDER BY started_at DESC, id DESC LIMIT ? OFFSET ?", (q.page_size, (q.page - 1) * q.page_size)).fetchall()
    summary = budget.spend_summary(conn, cfg, now)
    return {
        "items": [ledger.call_dto(r) for r in rows],
        "page": q.page,
        "page_size": q.page_size,
        "total": total,
        "today_usd": summary["today_usd"],
        "month_usd": summary["month_usd"],
        "avg_cost_per_word_7d": summary["avg_cost_per_word_7d"],
    }


@router.post("/api/admin/ai/pause", response_model=schemas.AiPauseResponse)
def ai_pause(
    body: schemas.AiPauseRequest,
    admin: dict[str, Any] = Depends(require_admin),
    conn: sqlite3.Connection = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict[str, Any]:
    now = _now(clock)
    with db.tx(conn):
        if body.paused:
            # CLAUDE_INTEGRATION §7 "pause": only `kv.claude.paused_until` — jobs defer until then and AI resumes by itself
            # when it elapses. The kill switch (`kv.claude.enabled='0'`, worker idles) is a separate guard and is not set here.
            until = to_iso(parse_iso(now) + MANUAL_PAUSE)
            db.kv_set(conn, "claude.paused_until", until, now=now)
            conn.execute("INSERT INTO system_events(kind, detail_json, created_at) VALUES ('claude_paused', ?, ?)", (json.dumps({"by": admin["username"], "until": until}), now))
            return {"paused": True, "paused_until": until}
        db.kv_set(conn, "claude.enabled", "1", now=now)  # resume also lifts a hand-set kill switch
        db.kv_delete(conn, "claude.paused_until")
        conn.execute("INSERT INTO system_events(kind, detail_json, created_at) VALUES ('claude_resumed', ?, ?)", (json.dumps({"by": admin["username"]}), now))
    return {"paused": False, "paused_until": None}


@router.post("/api/admin/ai/probe", response_model=schemas.ProbeResponse)
def ai_probe(
    admin: dict[str, Any] = Depends(require_admin),
    conn: sqlite3.Connection = Depends(get_db),
    clock: Clock = Depends(get_clock),
    cfg: Settings = Depends(get_settings),
) -> dict[str, Any]:
    now = _now(clock)
    last = db.kv_get(conn, "claude.probe_started_at")
    if last and parse_iso(last) > parse_iso(now) - PROBE_MIN_INTERVAL:
        retry = int((parse_iso(last) + PROBE_MIN_INTERVAL - parse_iso(now)).total_seconds())
        raise ApiError("rate_limited", details={"retry_after_s": max(1, retry)})
    with db.tx(conn):
        db.kv_set(conn, "claude.probe_started_at", now, now=now)
    return probe.check(conn, cfg, now=now).as_dict()


# ------------------------------------------------------------------------------- 67–69 content
@router.post("/api/admin/content/prewarm", status_code=202, response_model=schemas.PrewarmResponse)
def content_prewarm(
    body: schemas.PrewarmRequest,
    admin: dict[str, Any] = Depends(require_admin),
    conn: sqlite3.Connection = Depends(get_db),
    clock: Clock = Depends(get_clock),
    cfg: Settings = Depends(get_settings),
) -> dict[str, Any]:
    now = _now(clock)
    if not budget.ai_enabled(conn, cfg) or budget.paused_until(conn, now) is not None:
        raise ApiError("ai_disabled")
    job_id, planned, _ = prewarm.create_plan(conn, stage=body.stage, limit=body.limit, max_budget_usd=body.max_budget_usd, now=now)
    return {"job_id": job_id, "planned": planned}


def _word_or_404(conn: sqlite3.Connection, word_id: int) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM words WHERE id = ?", (int(word_id),)).fetchone()
    if row is None:
        raise ApiError("word_not_found")
    return {k: row[k] for k in row.keys()}


@router.post("/api/admin/words/{word_id}/regenerate", status_code=202, response_model=schemas.JobIdResponse)
def regenerate(
    word_id: int,
    admin: dict[str, Any] = Depends(require_admin),
    conn: sqlite3.Connection = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict[str, Any]:
    now = _now(clock)
    word = _word_or_404(conn, word_id)
    if word.get("is_valid_english") != 1:
        raise ApiError("invalid_transition", details={"from": "provisional" if word.get("is_valid_english") is None else "invalid", "action": "regenerate"})
    wid = int(word["id"])
    with db.tx(conn):
        n = 1 + int(conn.execute("SELECT COUNT(*) FROM jobs WHERE dedupe_key LIKE ?", (f"content:{wid}:r%",)).fetchone()[0])
        job_id = queue.enqueue(conn, "generate_content", {"word_id": wid, "force": True}, dedupe_key=f"content:{wid}:r{n}", priority=REGENERATE_PRIORITY, now=now)
        # Only a word without content moves to `queued` (the rule of every other enqueue site). A `ready` word keeps its
        # state and its visible version until the forced job stores the next one — `content.select_jobs` honours `force`
        # regardless of the state, and a dead forced job then correctly keeps the old version (`content.mark_failed`).
        conn.execute("UPDATE words SET content_state = 'queued', updated_at = ? WHERE id = ? AND content_state IN ('none','failed')", (now, wid))
    return {"job_id": job_id}


@router.post("/api/admin/words/{word_id}/refetch-image", status_code=202, response_model=schemas.JobIdResponse)
def refetch_image(
    word_id: int,
    body: schemas.RefetchImageRequest,
    admin: dict[str, Any] = Depends(require_admin),
    conn: sqlite3.Connection = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict[str, Any]:
    now = _now(clock)
    word = _word_or_404(conn, word_id)
    wid = int(word["id"])
    job_id = images.admin_refetch(conn, wid, provider=body.provider, query=body.query, priority=REFETCH_PRIORITY, now=now)
    if job_id is None:
        raise ApiError("word_not_found")
    return {"job_id": int(job_id)}


# ----------------------------------------------------------------------------------- 72–74 misc
@router.get("/api/admin/events", response_model=schemas.Page[schemas.SystemEvent])
def events(
    q: Annotated[schemas.PageQuery, Query()],
    admin: dict[str, Any] = Depends(require_admin),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    total = int(conn.execute("SELECT COUNT(*) FROM system_events").fetchone()[0])
    rows = conn.execute("SELECT * FROM system_events ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?", (q.page_size, (q.page - 1) * q.page_size)).fetchall()
    return {"items": [_event_dto(r) for r in rows], "page": q.page, "page_size": q.page_size, "total": total}


@router.get("/api/admin/config", response_model=schemas.ConfigResponse)
def config(admin: dict[str, Any] = Depends(require_admin), cfg: Settings = Depends(get_settings)) -> dict[str, Any]:
    return {"entries": cfg.entries()}


@router.post("/api/admin/push/run", response_model=schemas.PushRunResponse)
def push_run(
    body: schemas.PushRunRequest,
    admin: dict[str, Any] = Depends(require_admin),
    conn: sqlite3.Connection = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict[str, Any]:
    now_dt = clock.now_utc()
    user = conn.execute("SELECT id FROM users WHERE id = ?", (body.user_id,)).fetchone()
    if user is None:
        raise ApiError("not_found")
    # WP4's helper (also behind `wd push-now`): build today's batch if missing, publish once, enqueue the deliveries
    # the user enabled (dedupe email:<id> / webhook:<id>, statuses → 'queued').
    batch_id, status = batches.push_now(conn, int(body.user_id), now_dt, trigger="admin")
    return {"batch_id": int(batch_id), "status": str(status)}
