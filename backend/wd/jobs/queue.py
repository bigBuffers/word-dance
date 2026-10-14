"""Durable SQLite job queue (Phase 0, frozen contract — TASKS §I, SCHEMA.sql `jobs` comment, CLAUDE_INTEGRATION §6.2–6.3).

Every queue-state function lives here; the worker (WP5), the scheduler (WP4) and the handlers call
them as ``queue.*``. Each function joins the caller's open transaction when there is one and
otherwise runs in its own ``BEGIN IMMEDIATE`` (``db.maybe_tx``). Functions whose §I signature has
no ``now`` take an optional keyword ``now`` (ISO) so tests can drive them with a frozen clock; it
defaults to the system clock.

Attempt accounting (CLAUDE_INTEGRATION §6.3): ``claim_batch`` increments ``attempts``; ``fail``
keeps that increment and backs off 2 / 10 / 60 min, going ``dead`` once ``attempts >= max_attempts``;
``defer`` and ``requeue_group(consume_attempt=False)`` undo the claim's increment ("no attempt consumed").
"""

from __future__ import annotations

import json
import sqlite3
from datetime import timedelta
from typing import TYPE_CHECKING, Iterable, Sequence

from ..clock import now_iso, parse_iso, to_iso
from ..db import maybe_tx
from ..interfaces import Job
from . import registry
from .registry import JOB_TYPES

if TYPE_CHECKING:
    from ..config import Settings
    from .registry import JobContext

BACKOFF_MINUTES: tuple[int, ...] = (2, 10, 60)
STALE_LOCK_MINUTES = 15
CLAUDE_TYPES: tuple[str, ...] = ("generate_content", "lookup_word", "consolidate_bank", "generate_svg", "prewarm_plan")
IO_TYPES: tuple[str, ...] = ("fetch_image", "send_email", "send_webhook")
MAX_RUN_ONCE_CLAIMS = 10_000


def limit_for(type: str, cfg: "Settings") -> int:
    """Jobs per claim: content ``WD_AI_BATCH_SIZE`` · lookup 20 · everything else 1 (CLAUDE_INTEGRATION §6.2)."""
    if type == "generate_content":
        return max(1, int(cfg.ai_batch_size))
    if type == "lookup_word":
        return 20
    return 1


def backoff_minutes(attempts: int) -> int:
    """Backoff after the ``attempts``-th failed attempt: 2, 10, then 60 minutes."""
    idx = max(1, attempts) - 1
    return BACKOFF_MINUTES[min(idx, len(BACKOFF_MINUTES) - 1)]


def _plus_minutes(now: str, minutes: int) -> str:
    return to_iso(parse_iso(now) + timedelta(minutes=minutes))


def _ids(job_ids: Iterable[int]) -> list[int]:
    return [int(i) for i in job_ids]


def _placeholders(n: int) -> str:
    return ",".join("?" * n)


def dump_payload(payload: dict | None) -> str:
    return json.dumps(payload or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def get_job(conn: sqlite3.Connection, job_id: int) -> Job | None:
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (int(job_id),)).fetchone()
    return None if row is None else Job.from_row(row)


# ------------------------------------------------------------------------------------- enqueue
def enqueue(
    conn: sqlite3.Connection,
    type: str,
    payload: dict,
    *,
    dedupe_key: str | None,
    priority: int = 50,
    run_after: str | None = None,
    max_attempts: int = 3,
    now: str | None = None,
) -> int:
    """Insert a job or fold it into the LIVE job with the same ``dedupe_key`` (``queued``/``running``).

    The exact verified UPSERT from the SCHEMA.sql ``jobs`` comment: the conflict target repeats the
    partial unique index predicate verbatim (a plain ``ON CONFLICT(dedupe_key)`` is rejected by SQLite);
    on conflict the live job keeps the lower ``priority`` and the earlier ``run_after`` and its id is
    returned. A ``done``/``dead``/``cancelled`` job never conflicts, so callers wanting a re-run use a
    fresh key suffix (``content:<id>:r<n>``). Returns the live job id.
    """
    if type not in JOB_TYPES:
        raise ValueError(f"unknown job type {type!r}")
    now = now or now_iso()
    run_after = run_after or now
    with maybe_tx(conn):
        row = conn.execute(
            "INSERT INTO jobs(type, payload_json, dedupe_key, priority, run_after, max_attempts, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?) "
            "ON CONFLICT(dedupe_key) WHERE dedupe_key IS NOT NULL AND status IN ('queued','running') "
            "DO UPDATE SET priority = min(priority, excluded.priority), run_after = min(run_after, excluded.run_after), "
            "updated_at = excluded.updated_at "
            "RETURNING id",
            (type, dump_payload(payload), dedupe_key, int(priority), run_after, int(max_attempts), now, now),
        ).fetchone()
        return int(row[0])


# --------------------------------------------------------------------------------------- claims
def head_type(conn: sqlite3.Connection, types: Sequence[str], now: str) -> str | None:
    """Type of the head job across ``types`` (``ORDER BY priority, run_after, id``), or None when nothing is runnable.

    Used by the Claude worker so a priority-10 lookup is never stuck behind priority-20/90 content jobs
    (CLAUDE_INTEGRATION §6.2) and by :func:`run_once`.
    """
    types = tuple(types)
    if not types:
        return None
    row = conn.execute(
        f"SELECT type FROM jobs WHERE status='queued' AND run_after <= ? AND type IN ({_placeholders(len(types))}) "
        "ORDER BY priority, run_after, id LIMIT 1",
        (now, *types),
    ).fetchone()
    return None if row is None else str(row[0])


def claim_batch(conn: sqlite3.Connection, type: str, limit: int, worker_id: str, *, now: str | None = None) -> list[Job]:
    """Atomically claim up to ``limit`` runnable jobs of ``type`` (one ``BEGIN IMMEDIATE``).

    Honours ``payload.group_size`` (bisection): ``n = min(limit, head.group_size or limit)`` and only jobs
    whose own ``group_size`` (default 99) is ``>= n`` join the group, exactly as CLAUDE_INTEGRATION §6.2.
    ``attempts`` is incremented at claim time. Returns the claimed jobs ordered ``priority, run_after, id``.
    """
    now = now or now_iso()
    with maybe_tx(conn):
        head = conn.execute(
            "SELECT id, payload_json FROM jobs WHERE status='queued' AND type=? AND run_after<=? ORDER BY priority, run_after, id LIMIT 1",
            (type, now),
        ).fetchone()
        if head is None:
            return []
        try:
            head_group = json.loads(head[1] or "{}").get("group_size")
        except (TypeError, ValueError, AttributeError):
            head_group = None
        head_group = int(head_group) if isinstance(head_group, (int, float)) and not isinstance(head_group, bool) and head_group >= 1 else None
        n = max(1, min(int(limit), head_group or int(limit)))
        rows = conn.execute(
            "UPDATE jobs SET status='running', locked_at=?, locked_by=?, attempts=attempts+1, updated_at=? "
            "WHERE id IN (SELECT id FROM jobs WHERE status='queued' AND type=? AND run_after<=? "
            "             AND COALESCE(json_extract(payload_json,'$.group_size'), 99) >= ? "
            "             ORDER BY priority, run_after, id LIMIT ?) RETURNING *",
            (now, worker_id, now, type, now, n, n),
        ).fetchall()
    jobs = [Job.from_row(r) for r in rows]
    jobs.sort(key=lambda j: (j.priority, j.run_after, j.id))
    return jobs


# ------------------------------------------------------------------------------------- outcomes
def finish(conn: sqlite3.Connection, job_id: int, result: dict | None = None, *, now: str | None = None) -> None:
    """Mark a job ``done`` with an optional ``result_json``."""
    now = now or now_iso()
    with maybe_tx(conn):
        conn.execute(
            "UPDATE jobs SET status='done', result_json=?, finished_at=?, updated_at=?, locked_at=NULL, locked_by=NULL WHERE id=?",
            (None if result is None else json.dumps(result, ensure_ascii=False, sort_keys=True), now, now, int(job_id)),
        )


def fail(conn: sqlite3.Connection, job_id: int, error: str, *, now: str | None = None) -> str:
    """Record a failed attempt: back off (2 / 10 / 60 min) or go ``dead`` once ``attempts >= max_attempts``.

    Returns the resulting status (``'queued'`` or ``'dead'``).
    """
    now = now or now_iso()
    err = (error or "")[:1000]
    with maybe_tx(conn):
        row = conn.execute("SELECT attempts, max_attempts FROM jobs WHERE id=?", (int(job_id),)).fetchone()
        if row is None:
            raise LookupError(f"job {job_id} does not exist")
        attempts, max_attempts = int(row[0]), int(row[1])
        if attempts >= max_attempts:
            conn.execute(
                "UPDATE jobs SET status='dead', last_error=?, finished_at=?, updated_at=?, locked_at=NULL, locked_by=NULL WHERE id=?",
                (err, now, now, int(job_id)),
            )
            return "dead"
        conn.execute(
            "UPDATE jobs SET status='queued', last_error=?, run_after=?, updated_at=?, locked_at=NULL, locked_by=NULL WHERE id=?",
            (err, _plus_minutes(now, backoff_minutes(attempts)), now, int(job_id)),
        )
        return "queued"


def defer(conn: sqlite3.Connection, job_ids: Iterable[int], run_after: str, *, now: str | None = None) -> int:
    """Push jobs to ``run_after`` without consuming an attempt (budget/pause/overload, CLAUDE_INTEGRATION §6.3).

    Running (claimed) jobs return to ``queued`` with the claim's attempt increment undone; already
    queued jobs only have their ``run_after`` moved later (never earlier). Returns the rows changed.
    """
    ids = _ids(job_ids)
    if not ids:
        return 0
    now = now or now_iso()
    ph = _placeholders(len(ids))
    with maybe_tx(conn):
        running = [int(r[0]) for r in conn.execute(f"SELECT id FROM jobs WHERE status='running' AND id IN ({ph})", ids)]
        queued = [int(r[0]) for r in conn.execute(f"SELECT id FROM jobs WHERE status='queued' AND id IN ({ph})", ids)]
        changed = 0
        if running:
            changed += conn.execute(
                f"UPDATE jobs SET status='queued', run_after=?, attempts=MAX(attempts-1, 0), locked_at=NULL, locked_by=NULL, updated_at=? "
                f"WHERE id IN ({_placeholders(len(running))})",
                (run_after, now, *running),
            ).rowcount
        if queued:
            changed += conn.execute(
                f"UPDATE jobs SET run_after=MAX(run_after, ?), updated_at=? WHERE id IN ({_placeholders(len(queued))})",
                (run_after, now, *queued),
            ).rowcount
    return int(changed)


def requeue_group(
    conn: sqlite3.Connection,
    job_ids: Iterable[int],
    group_size: int,
    consume_attempt: bool,
    *,
    error: str | None = None,
    now: str | None = None,
) -> int:
    """Bisection requeue (CLAUDE_INTEGRATION §6.3): set ``payload.group_size`` and put the jobs back to ``queued``.

    ``consume_attempt=False`` (``--max-budget-usd`` stop): the claim's attempt is given back and the jobs are
    runnable at once. ``consume_attempt=True`` (second group failure): the attempt counts — members at
    ``attempts >= max_attempts`` go ``dead``, the others back off like :func:`fail`. Returns the rows touched.
    """
    ids = _ids(job_ids)
    if not ids:
        return 0
    now = now or now_iso()
    gs = max(1, int(group_size))
    err = (error or "")[:1000] or None
    touched = 0
    with maybe_tx(conn):
        rows = conn.execute(f"SELECT id, attempts, max_attempts FROM jobs WHERE id IN ({_placeholders(len(ids))})", ids).fetchall()
        for job_id, attempts, max_attempts in rows:
            if consume_attempt:
                if int(attempts) >= int(max_attempts):
                    conn.execute(
                        "UPDATE jobs SET status='dead', payload_json=json_set(payload_json,'$.group_size',?), last_error=COALESCE(?, last_error), "
                        "finished_at=?, updated_at=?, locked_at=NULL, locked_by=NULL WHERE id=?",
                        (gs, err, now, now, job_id),
                    )
                else:
                    conn.execute(
                        "UPDATE jobs SET status='queued', payload_json=json_set(payload_json,'$.group_size',?), last_error=COALESCE(?, last_error), "
                        "run_after=?, updated_at=?, locked_at=NULL, locked_by=NULL WHERE id=?",
                        (gs, err, _plus_minutes(now, backoff_minutes(int(attempts))), now, job_id),
                    )
            else:
                conn.execute(
                    "UPDATE jobs SET status='queued', payload_json=json_set(payload_json,'$.group_size',?), attempts=MAX(attempts-1,0), "
                    "last_error=COALESCE(?, last_error), run_after=?, updated_at=?, locked_at=NULL, locked_by=NULL WHERE id=?",
                    (gs, err, now, now, job_id),
                )
            touched += 1
    return touched


def requeue_stale(conn: sqlite3.Connection, boot_id: str, *, now: str | None = None, stale_minutes: int = STALE_LOCK_MINUTES) -> int:
    """Return ``running`` jobs of other boots, or locked longer than 15 min, to ``queued`` (startup + every 5 min)."""
    now = now or now_iso()
    cutoff = to_iso(parse_iso(now) - timedelta(minutes=stale_minutes))
    with maybe_tx(conn):
        cur = conn.execute(
            "UPDATE jobs SET status='queued', locked_at=NULL, locked_by=NULL, updated_at=? "
            "WHERE status='running' AND (locked_by IS NULL OR locked_by NOT LIKE '%:' || ? OR locked_at IS NULL OR locked_at < ?)",
            (now, boot_id, cutoff),
        )
        return int(cur.rowcount)


def cancel(conn: sqlite3.Connection, job_ids: Iterable[int], *, now: str | None = None) -> int:
    """``status='cancelled'`` for live jobs (prewarm leftovers, merged words' content jobs). Returns the count."""
    ids = _ids(job_ids)
    if not ids:
        return 0
    now = now or now_iso()
    with maybe_tx(conn):
        cur = conn.execute(
            f"UPDATE jobs SET status='cancelled', finished_at=?, updated_at=?, locked_at=NULL, locked_by=NULL "
            f"WHERE status IN ('queued','running') AND id IN ({_placeholders(len(ids))})",
            (now, now, *ids),
        )
        return int(cur.rowcount)


def live_job(conn: sqlite3.Connection, dedupe_key: str) -> Job | None:
    """The ``queued``/``running`` job holding ``dedupe_key``, if any (e.g. content `deferred_until`, API.md 24)."""
    row = conn.execute("SELECT * FROM jobs WHERE dedupe_key=? AND status IN ('queued','running') LIMIT 1", (dedupe_key,)).fetchone()
    return None if row is None else Job.from_row(row)


# -------------------------------------------------------------------------------------- draining
def run_once(ctx: "JobContext") -> int:
    """Synchronous drain for tests/smoke/``wd worker-once``: claim and run until nothing is runnable.

    Loads the handlers first. Jobs of a type without a handler are failed (backoff) so the loop
    terminates; a handler that raises, or returns while a job is still ``running``, has those jobs
    failed with the error text. Returns the number of jobs handed to handlers (or failed).
    """
    registry.load_handlers()
    processed = 0
    claims = 0
    while claims < MAX_RUN_ONCE_CLAIMS:
        claims += 1
        conn = ctx.db()
        try:
            now = ctx.now()
            t = head_type(conn, JOB_TYPES, now)
            if t is None:
                return processed
            jobs = claim_batch(conn, t, limit_for(t, ctx.cfg), ctx.locked_by, now=now)
        finally:
            conn.close()
        if not jobs:
            continue
        processed += len(jobs)
        handler = registry.get_handler(t)
        if handler is None:
            conn = ctx.db()
            try:
                for j in jobs:
                    fail(conn, j.id, f"no handler registered for job type {t!r}", now=ctx.now())
            finally:
                conn.close()
            continue
        error: str | None = None
        try:
            handler(ctx, jobs)
        except Exception as e:  # a handler bug must not take the drain down
            ctx.log.exception("handler for %s crashed", t, extra={"job_type": t, "worker": ctx.worker_id})
            error = f"handler crashed: {e!r}"
        conn = ctx.db()
        try:
            ph = _placeholders(len(jobs))
            still_running = [int(r[0]) for r in conn.execute(f"SELECT id FROM jobs WHERE status='running' AND id IN ({ph})", [j.id for j in jobs])]
            for job_id in still_running:
                fail(conn, job_id, error or f"handler for {t!r} returned without finishing the job", now=ctx.now())
        finally:
            conn.close()
    ctx.log.warning("run_once stopped after %d claims", claims)
    return processed
