"""Background job workers (CLAUDE_INTEGRATION §6.2, DEPLOY §9) and the ``wd worker-once`` command.

* :class:`ClaudeWorker` (threads ``claude-N``, ``WD_AI_CONCURRENCY`` of them) takes the **head job across all Claude
  job types** (``queue.head_type`` over ``generate_content / lookup_word / consolidate_bank / generate_svg /
  prewarm_plan`` ordered ``priority, run_after, id``), so a priority-10 lookup is never stuck behind priority-20/90
  content jobs; it idles while the kill switch is off (jobs untouched — only the bank rows behind queued lookups are
  flagged 「暂时无法校验」, CLAUDE_INTEGRATION §6.5). The claim size comes from ``failover.claim_limit`` (``queue.limit_for``,
  except that a content group shrinks to ``WD_AI_FALLBACK_BATCH_SIZE`` while the fallback provider takes it, §10.5).
  Budget / pause checks run inside the handlers (``wd.ai.common.claude_call``), so a synchronous drain applies exactly
  the same rules.
* :class:`IoWorker` (``io-1``) drains ``fetch_image / send_email / send_webhook`` one job at a time.
* Both sweep stale ``running`` jobs every five minutes (``queue.requeue_stale(boot_id)``); the Claude worker also
  prunes ``claude-logs`` older than ``WD_AI_LOG_KEEP_DAYS``.
* Both are fenced by the worker lease: constructed with ``lease_lost=keeper.lost`` (``lease.LeaseKeeper``), a worker
  neither claims nor sweeps while that event is set — another instance holds the lease and its sweep would otherwise
  requeue our running jobs (and ours its) so every job runs twice. When the keeper re-acquires the lease the worker
  sweeps once immediately (the other instance may have died with jobs ``running``) and resumes.
* :func:`drain` is the synchronous loop behind ``wd worker-once`` and ``POST /api/admin/jobs/run-once``.
  ``wd worker-once`` refuses to run (exit 2 + the DEPLOY §9 hint) while ``kv.worker_lease`` is live: a second
  claimer next to the service would have its jobs swept and re-run.

Threads follow ``interfaces.BackgroundThread`` (``start() / stop() / join(timeout)``) and are constructed by
``main.start_background`` as ``Cls(ctx.for_worker(worker_id))``.
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
import threading
import time
from datetime import timedelta
from typing import Any, Sequence

from .. import db
from ..clock import SYSTEM_CLOCK, now_iso, parse_iso, to_iso
from ..config import ConfigError, Settings, ensure_dirs
from ..interfaces import Job
from . import lease, queue, registry
from .queue import CLAUDE_TYPES, IO_TYPES
from .registry import JOB_TYPES, JobContext

log = logging.getLogger("wd.jobs.worker")

IDLE_WAIT_S = 5.0
DISABLED_WAIT_S = 30.0
ERROR_WAIT_S = 10.0
SWEEP_INTERVAL_S = 300.0
MAX_DRAIN_CLAIMS = 10_000
DEAD_REQUEUE_LIMIT = 50
DEAD_REQUEUE_AGE = timedelta(hours=24)


# ----------------------------------------------------------------------------------- dispatch
def dispatch(ctx: JobContext, jobs: list[Job]) -> None:
    """Run the registered handler for ``jobs`` (one type); jobs a handler leaves ``running`` are failed with the error."""
    if not jobs:
        return
    job_type = jobs[0].type
    handler = registry.get_handler(job_type)
    error: str | None = None
    if handler is None:
        error = f"no handler registered for job type {job_type!r}"
    else:
        try:
            handler(ctx, jobs)
        except Exception as e:  # noqa: BLE001 — a handler bug must never take the worker down
            ctx.log.exception("handler for %s crashed", job_type, extra={"job_type": job_type, "worker": ctx.worker_id})
            error = f"handler crashed: {e!r}"
    conn = ctx.db()
    try:
        marks = ",".join("?" * len(jobs))
        still_running = [int(r[0]) for r in conn.execute(f"SELECT id FROM jobs WHERE status = 'running' AND id IN ({marks})", [j.id for j in jobs])]
        for job_id in still_running:
            queue.fail(conn, job_id, error or f"handler for {job_type!r} returned without finishing the job", now=ctx.now())
    finally:
        conn.close()


def claim_limit(ctx: JobContext, conn: sqlite3.Connection, job_type: str, *, now: str) -> int:
    """Jobs per claim: ``failover.claim_limit`` (``queue.limit_for``, except content groups of ``WD_AI_FALLBACK_BATCH_SIZE``
    while the fallback takes them, CLAUDE_INTEGRATION §10.5). An unexpected non-sqlite error there must never stop the
    queue: it is logged and the plain ``queue.limit_for`` is used."""
    from ..ai import failover  # local import: ai → jobs must not become a module cycle at import time

    try:
        return failover.claim_limit(conn, ctx.cfg, job_type, now=now)
    except sqlite3.Error:
        raise
    except Exception as e:  # noqa: BLE001 — a kv / config surprise in the claim-size lookup is not a reason to stop claiming
        ctx.log.warning("claim limit for %s fell back to queue.limit_for: %r", job_type, e, extra={"job_type": job_type, "worker": ctx.worker_id, "event": "claim_limit_fallback"})
        return queue.limit_for(job_type, ctx.cfg)


def process_next(ctx: JobContext, types: Sequence[str], *, now: str | None = None) -> tuple[int, bool]:
    """Claim the head group among ``types`` and run its handler; returns ``(jobs handled, something was runnable)``."""
    conn = ctx.db()
    try:
        now = now or ctx.now()
        job_type = queue.head_type(conn, tuple(types), now)
        if job_type is None:
            return 0, False
        jobs = queue.claim_batch(conn, job_type, claim_limit(ctx, conn, job_type, now=now), ctx.locked_by, now=now)
    finally:
        conn.close()
    if not jobs:
        return 0, True  # lost the race to another worker thread; there may be more
    dispatch(ctx, jobs)
    return len(jobs), True


def drain(ctx: JobContext, types: Sequence[str] = JOB_TYPES, *, max_claims: int = MAX_DRAIN_CLAIMS) -> int:
    """Synchronous drain (``wd worker-once`` / admin run-once): claim and run until nothing is runnable."""
    registry.load_handlers()
    processed = 0
    for _ in range(max_claims):
        n, had_head = process_next(ctx, types)
        processed += n
        if not had_head:
            return processed
    ctx.log.warning("drain stopped after %d claims", max_claims, extra={"worker": ctx.worker_id})
    return processed


#: A revived ``generate_content`` job's word goes back from ``failed`` to ``queued`` — the mirror image of ``content.mark_failed``,
#: guarded exactly like every enqueue site (``bank.enqueue_content_if_needed``, the content request route): validated, not
#: merged, no active version (``content.select_jobs`` finishes the job without touching such a word, which an unguarded flip
#: would strand at ``queued``). Parameters: ``(now, payload_json)`` of the revived row. Shared with ``scheduler.requeue_dead_once``.
REVIVE_CONTENT_WORD_SQL = (
    "UPDATE words SET content_state = 'queued', updated_at = ? WHERE id = json_extract(?, '$.word_id') "
    "AND content_state = 'failed' AND is_valid_english = 1 AND merged_into_word_id IS NULL AND active_content_id IS NULL"
)


def requeue_dead_jobs(
    conn: sqlite3.Connection,
    *,
    now: str | None = None,
    types: Sequence[str] | None = None,
    older_than: timedelta | None = None,
    limit: int | None = None,
    died_after: str | None = None,
    group_size: int | None = 1,
) -> int:
    """Put ``dead`` jobs back to ``queued`` (``attempts = 0``, ``run_after = now``, ``payload.group_size = group_size`` — or
    that mark REMOVED with ``json_remove`` when ``group_size`` is None, a bisection mark included, so the revived jobs
    batch like fresh claims: ``failover.claim_limit`` 10 on the CLI / 5 on the fallback).

    Used by ``POST /api/admin/jobs/requeue-dead`` (everything, ``group_size=1``) and by the fail-back
    (``failover._requeue_outage_dead``: ``died_after`` = the outage start, only rows with ``finished_at >= died_after``,
    ``group_size=None``, CLAUDE_INTEGRATION §10.6). The nightly maintenance is NOT a caller: it is
    ``scheduler.requeue_dead_once`` with its own SQL and the once-only ``payload.requeued_at`` stamp (§6.3) — this
    function neither sets nor honours that stamp, on purpose: an outage casualty keeps its single nightly retry, and a
    nightly-revived job that died again during the outage gets its CLI try. A dead job whose dedupe key is held by a
    live (``queued`` / ``running``) job is not a candidate — it never takes one of ``limit``'s slots, exactly like the
    nightly — and the per-row ``IntegrityError`` guard still covers the race with a concurrent enqueue and two dead rows
    sharing one key. A revived ``generate_content`` job's word goes back from ``failed`` to ``queued`` in the same
    transaction (:data:`REVIVE_CONTENT_WORD_SQL`, keyed on the row's ``payload.word_id``), so "a word is ``queued`` ⇔ it
    has a live content job" holds in both directions and the content routes / batches wait for it instead of showing
    生成失败; ``lookup_word`` rows change nothing else. Each row is its own ``db.maybe_tx`` statement group, so the
    function also works inside a caller's open transaction.
    """
    now = now or now_iso()
    where = [
        "status = 'dead'",
        "NOT EXISTS (SELECT 1 FROM jobs l WHERE l.dedupe_key = jobs.dedupe_key AND l.status IN ('queued','running'))",
    ]
    params: list[Any] = []
    if types:
        where.append(f"type IN ({','.join('?' * len(types))})")
        params.extend(types)
    if older_than is not None:
        where.append("finished_at <= ?")
        params.append(to_iso(parse_iso(now) - older_than))
    if died_after is not None:
        where.append("finished_at >= ?")
        params.append(died_after)
    sql = f"SELECT id, type, payload_json FROM jobs WHERE {' AND '.join(where)} ORDER BY finished_at, id"
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    rows = [(int(r[0]), str(r[1]), r[2]) for r in conn.execute(sql, params)]
    if group_size is None:
        mark_sql, mark_params = "json_remove(payload_json, '$.group_size')", ()
    else:
        mark_sql, mark_params = "json_set(payload_json, '$.group_size', ?)", (int(group_size),)
    requeued = 0
    for job_id, job_type, payload_json in rows:
        try:
            with db.maybe_tx(conn):
                cur = conn.execute(
                    "UPDATE jobs SET status = 'queued', attempts = 0, run_after = ?, locked_at = NULL, locked_by = NULL, finished_at = NULL, "
                    f"payload_json = {mark_sql}, updated_at = ? WHERE id = ? AND status = 'dead'",
                    (now, *mark_params, now, job_id),
                )
                if cur.rowcount == 1:
                    requeued += 1
                    if job_type == "generate_content":
                        conn.execute(REVIVE_CONTENT_WORD_SQL, (now, payload_json))
        except sqlite3.IntegrityError:
            log.info("dead job %d not requeued: its dedupe key is held by a live job", job_id)
    return requeued


# ------------------------------------------------------------------------------------- threads
class BaseWorker(threading.Thread):
    """Loop: lease fence → gate → periodic sweep → :func:`process_next`; idles ``idle_wait`` seconds when nothing is runnable.

    ``lease_lost`` is the ``LeaseKeeper.lost`` event of this process (None for ``wd worker-once`` and tests without a
    lease): while it is set the worker is *fenced* — :meth:`step` claims nothing and :meth:`maybe_sweep` is a no-op.
    """

    types: tuple[str, ...] = ()

    def __init__(self, ctx: JobContext, *, idle_wait: float = IDLE_WAIT_S, lease_lost: threading.Event | None = None):
        super().__init__(name=ctx.worker_id, daemon=True)
        self.ctx = ctx
        self.worker_id = ctx.worker_id
        self.idle_wait = idle_wait
        self.lease_lost = lease_lost
        self.processed = 0
        self.last_error: str | None = None
        self.last_active_at: str | None = None
        self._stop_event = threading.Event()
        self._last_sweep = 0.0
        self._was_fenced = False

    def stop(self) -> None:
        self._stop_event.set()

    @property
    def stopping(self) -> bool:
        return self._stop_event.is_set()

    @property
    def fenced(self) -> bool:
        """True while the lease keeper reports the worker lease held by another instance."""
        return self.lease_lost is not None and self.lease_lost.is_set()

    def gate(self) -> float | None:
        """Seconds to idle instead of claiming (None = go ahead)."""
        return None

    def housekeeping(self, conn: sqlite3.Connection, now: str) -> None:
        swept = queue.requeue_stale(conn, self.ctx.boot_id, now=now)
        if swept:
            log.info("requeued %d stale running job(s)", swept, extra={"worker": self.worker_id, "event": "stale_sweep"})

    def maybe_sweep(self) -> None:
        if self.fenced or time.monotonic() - self._last_sweep < SWEEP_INTERVAL_S:
            return  # a fenced instance must never requeue the lease holder's running jobs
        self._last_sweep = time.monotonic()
        conn = self.ctx.db()
        try:
            self.housekeeping(conn, self.ctx.now())
        finally:
            conn.close()

    def step(self) -> bool:
        """One iteration; True when something was handled (no idle wait afterwards)."""
        if self.fenced:
            if not self._was_fenced:
                self._was_fenced = True
                log.warning("%s: worker lease held by another instance; claiming suspended", self.worker_id, extra={"worker": self.worker_id, "event": "lease_fenced"})
            return False  # the run loop idles idle_wait seconds; the keeper clears the event once the lease is ours again
        if self._was_fenced:
            self._was_fenced = False
            self._last_sweep = 0.0  # sweep at once: the instance that held the lease meanwhile may have died with jobs running
            log.info("%s: worker lease re-acquired; claiming resumed", self.worker_id, extra={"worker": self.worker_id, "event": "lease_resumed"})
        wait = self.gate()
        if wait is not None:
            self._stop_event.wait(wait)
            return False
        self.maybe_sweep()
        n, had_head = process_next(self.ctx, self.types)
        if n:
            self.processed += n
            self.last_active_at = self.ctx.now()
        return had_head

    def run(self) -> None:  # pragma: no cover - exercised through start()/stop() in the integration tests
        registry.load_handlers()
        log.info("%s started", self.worker_id, extra={"worker": self.worker_id, "event": "worker_start"})
        while not self._stop_event.is_set():
            try:
                busy = self.step()
            except Exception as e:  # noqa: BLE001 — keep the thread alive through transient DB errors
                self.last_error = f"{e.__class__.__name__}: {e}"
                log.exception("%s: iteration failed", self.worker_id, extra={"worker": self.worker_id})
                self._stop_event.wait(ERROR_WAIT_S)
                continue
            if not busy:
                self._stop_event.wait(self.idle_wait)
        log.info("%s stopped after %d job(s)", self.worker_id, self.processed, extra={"worker": self.worker_id, "event": "worker_stop"})


class ClaudeWorker(BaseWorker):
    """``claude-N``: the five Claude job types, head job across types; idles while AI is disabled (flagging the bank
    rows of queued lookups 「暂时无法校验」 so learners get the 修改 / 重试 / 保留 / 删除 buttons, §6.5). Its five-minute
    housekeeping also runs the fail-back probe while the fallback provider is active (CLAUDE_INTEGRATION §10.6) — once
    immediately after start (a restart must not sit on the fallback for another 30 minutes) — pinned to the recorded
    ``kv.claude.flag_tier`` (one attempt; ``probe.check(tier=…)`` never rewrites the tier, AI_FALLBACK_MODEL §4.5), whereas
    ``wd claude-check`` and the admin button keep the two-tier install probe. That first housekeeping also ends a stale
    failover episode when the mode is not ``auto`` (``failover.reconcile_mode``: ``ai.active_provider`` back to claude, the
    ``ai.failover.*`` keys dropped, log event ``ai_failover_reconciled``; failures are logged, never raised)."""

    types = CLAUDE_TYPES

    def __init__(self, ctx: JobContext, *, idle_wait: float = IDLE_WAIT_S, lease_lost: threading.Event | None = None):
        super().__init__(ctx, idle_wait=idle_wait, lease_lost=lease_lost)
        self._first_housekeeping = True

    def gate(self) -> float | None:
        from ..ai import budget, lookup  # local import: ai → jobs must not become a module cycle at import time

        conn = self.ctx.db()
        try:
            if not budget.ai_enabled(conn, self.ctx.cfg):
                flagged = lookup.flag_queued_lookups(conn, now=self.ctx.now())
                if flagged:
                    log.info("AI disabled: flagged %d bank row(s) of queued lookups as 暂时无法校验", flagged, extra={"worker": self.worker_id, "event": "lookup_flagged_disabled"})
                return DISABLED_WAIT_S
        finally:
            conn.close()
        return None

    def housekeeping(self, conn: sqlite3.Connection, now: str) -> None:
        super().housekeeping(conn, now)
        from ..ai import failover, probe, runner

        try:
            removed = runner.prune_logs(self.ctx.cfg, now)
            if removed:
                log.info("pruned %d day(s) of claude logs", removed, extra={"worker": self.worker_id})
        except OSError as e:  # pragma: no cover - best effort
            log.warning("claude log pruning failed: %s", e)
        force = self._first_housekeeping
        self._first_housekeeping = False
        if force:
            try:  # a stale auto-mode episode means nothing in claude_cli / openai_http: end it before anything can "fail back" from it
                failover.reconcile_mode(conn, self.ctx.cfg, now=now)
            except Exception:  # noqa: BLE001 — bookkeeping must never take the worker down
                log.exception("failover state reconciliation failed", extra={"worker": self.worker_id})
        try:
            outcome = failover.maybe_probe(
                conn,
                self.ctx.cfg,
                now=now,
                probe_claude=lambda: probe.check(conn, self.ctx.cfg, now=now, tier=runner.flag_tier(conn)),
                force=force,
            )
            if outcome:
                log.info("fail-back probe: %s", outcome, extra={"worker": self.worker_id, "event": "ai_failback_probe"})
        except Exception:  # noqa: BLE001 — the probe must never take the worker down
            log.exception("fail-back probe failed", extra={"worker": self.worker_id})


class IoWorker(BaseWorker):
    """``io-1``: image fetches and deliveries, one job at a time."""

    types = IO_TYPES


# ------------------------------------------------------------------------------------------ CLI
TYPE_GROUPS: dict[str, tuple[str, ...]] = {"all": JOB_TYPES, "claude": CLAUDE_TYPES, "io": IO_TYPES}


def cmd_worker_once(args: argparse.Namespace) -> int:
    try:
        cfg = Settings.from_env()
    except ConfigError as e:
        print(f"wd: configuration error: {e}", file=sys.stderr)
        return 2
    ensure_dirs(cfg)
    conn = db.connect(cfg.db_path)
    try:
        db.run_migrations(conn, pre_hook=db.backup_pre_hook())
        now = now_iso()
        if lease.is_live(conn, now):
            from ..cli import LEASE_HINT

            print(f"wd worker-once: {LEASE_HINT}", file=sys.stderr)
            return 2
    finally:
        conn.close()
    ctx = JobContext(db=lambda: db.connect(cfg.db_path), cfg=cfg, clock=SYSTEM_CLOCK, enqueue=queue.enqueue, log=log, worker_id="once", boot_id="cli")
    processed = drain(ctx, TYPE_GROUPS[args.types])
    print(f"worker-once: processed {processed} job(s)")
    return 0


def register_cli(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("worker-once", help="drain the job queue synchronously (dev/smoke only; refused while word-dance.service runs)")
    p.add_argument("--types", choices=sorted(TYPE_GROUPS), default="all", help="which job types to drain (default all)")
    p.set_defaults(func=cmd_worker_once)


__all__ = [
    "BaseWorker",
    "ClaudeWorker",
    "IoWorker",
    "REVIVE_CONTENT_WORD_SQL",
    "claim_limit",
    "dispatch",
    "drain",
    "process_next",
    "register_cli",
    "requeue_dead_jobs",
]
