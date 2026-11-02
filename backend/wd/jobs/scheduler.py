"""Scheduler thread (WP4, DESIGN §6.4): the 60-second tick that builds, publishes and delivers daily batches.

``Scheduler(ctx)`` is constructed by ``main.py`` as ``Cls(ctx.for_worker('scheduler'))`` and driven through
``start()`` / ``stop()`` / ``join()`` (``interfaces.BackgroundThread``). Every step is a module-level function
over an open connection so tests drive :func:`run_tick` with a frozen clock and no thread:

* due users (``next_push_at <= now + WD_PREBUILD_HOURS``): ``build_from = max(next_push_at − WD_PREBUILD_HOURS,
  day_start(target_date))`` — a batch is always built on its own local day (push 01:00 → built from 00:00, never
  the evening before); publish exactly once at push time (conditional UPDATE); deliveries enqueued unless > 6 h
  late (``skipped``); ``next_push_at`` advanced once with the ``WHERE next_push_at = ?`` guard; catch-up after
  downtime builds today only — and when the service comes back on a later local day *before* that day's push
  time, ``next_push_at`` is re-anchored to that instant (guarded) so today's batch is built in its normal window
  and published + delivered at push time instead of being published at once with ``skipped`` deliveries;
* ``finalize_building``; hourly GC (expired sessions, ``auth_throttle``, stale ``running`` jobs);
* nightly 02:30 (per user, local) ``consolidate_bank`` enqueue guarded by ``kv consolidate:<user_id>:last_date``;
* 03:30 ``WD_TZ`` maintenance (``kv maintenance.last_date``): :func:`prefetch`, one requeue of dead
  content/lookup jobs, claude-logs pruning, ``PRAGMA optimize`` + WAL checkpoint;
* ``kv.last_tick_at``; a ``downtime`` event with ``{"from","to"}`` when the gap since the last tick exceeds 10 min.

``prefetch`` reads ``wd.ai.budget.spent_today(conn, cfg, now)`` / ``wd.ai.budget.ai_enabled(conn, cfg)`` (WP5).
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sqlite3
import sys
import threading
import time as _time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Mapping, Sequence

from .. import db
from ..ai import budget
from ..clock import SYSTEM_CLOCK, compute_next_push, day_start, local_date as clock_local_date, parse_iso, parse_push_time, to_iso, zone
from ..services import bank, batches
from . import lease, queue
from .registry import JobContext

log = logging.getLogger("wd.jobs.scheduler")

DOWNTIME_GAP = timedelta(minutes=10)
STALE_DELIVERY = timedelta(hours=6)
HOURLY = timedelta(hours=1)
CONSOLIDATE_AT = time(2, 30)
MAINTENANCE_AT = time(3, 30)
CONSOLIDATE_PRIORITY = 50
PREFETCH_PRIORITY = 30
PREFETCH_LIMIT = 50
PREFETCH_SPEND_SHARE = 0.5
DEAD_REQUEUE_LIMIT = 50
DEAD_REQUEUE_AGE = timedelta(hours=24)
KV_LAST_TICK = "last_tick_at"
KV_HOURLY = "maintenance.hourly_at"
KV_MAINTENANCE = "maintenance.last_date"


@dataclass
class TickResult:
    """What one tick did (for logs, tests and ``wd tick --once``)."""

    built: list[int] = field(default_factory=list)
    published: list[int] = field(default_factory=list)
    finalized: int = 0
    consolidations: int = 0
    prefetched: int = 0
    maintenance: bool = False
    gc: bool = False
    downtime: dict[str, str] | None = None


def _rows(conn: sqlite3.Connection, sql: str, params: Sequence[Any] | Mapping[str, Any] = ()) -> list[dict[str, Any]]:
    return [{k: r[k] for k in r.keys()} for r in conn.execute(sql, params).fetchall()]


# ------------------------------------------------------------------------------------------- window
def build_from(next_push_at: datetime, tz: str, prebuild_hours: int, now: datetime) -> tuple[date, datetime]:
    """DESIGN §6.4: ``(target_date, build_from)`` — the day the batch is for and the instant building may start.

    ``target_date = max(local_date(next_push_at), local_date(now))`` (never a past day);
    ``build_from = max(next_push_at − prebuild, day_start(target_date))`` so the batch is always built on its own
    local day (push 01:00 → window 00:00–01:00, never 22:00 the evening before).
    """
    target = max(clock_local_date(next_push_at, tz), clock_local_date(now, tz))
    start = max(next_push_at - timedelta(hours=int(prebuild_hours)), day_start(target, tz))
    return target, start


def push_instant(local_day: date, tz: str, push_time: str) -> datetime:
    """UTC instant of ``push_time`` on ``local_day`` in ``tz`` — built exactly like ``compute_next_push`` (DST-safe, ``fold=0``)."""
    hour, minute = parse_push_time(push_time)
    return datetime(local_day.year, local_day.month, local_day.day, hour, minute, tzinfo=zone(tz)).astimezone(timezone.utc)


# -------------------------------------------------------------------------------------------- pushes
def due_users(conn: sqlite3.Connection, now: datetime, prebuild_hours: int) -> list[dict[str, Any]]:
    horizon = to_iso(now + timedelta(hours=int(prebuild_hours)))
    return _rows(
        conn,
        "SELECT s.*, u.username FROM user_settings s JOIN users u ON u.id = s.user_id "
        "WHERE u.is_active = 1 AND u.onboarding_state = 'done' AND s.push_enabled = 1 AND s.next_push_at IS NOT NULL AND s.next_push_at <= ? "
        "ORDER BY s.next_push_at, s.user_id",
        (horizon,),
    )


def process_user(conn: sqlite3.Connection, s: Mapping[str, Any], now: datetime, *, prebuild_hours: int, result: TickResult) -> None:
    """Build / publish / deliver / advance for one due user (DESIGN §6.4 loop body)."""
    uid = int(s["user_id"])
    tz = str(s["timezone"] or bank.DEFAULT_TIMEZONE)
    try:
        zone(tz)
    except ValueError:
        log.warning("user %s has an unknown timezone %r; skipped", uid, tz)
        return
    next_push = parse_iso(str(s["next_push_at"]))
    target, start = build_from(next_push, tz, prebuild_hours, now)
    if target > clock_local_date(next_push, tz):
        # Catch-up onto a later local day (an outage covered the previous push). While that day's own push instant is
        # still ahead, re-anchor next_push_at to it (guarded) instead of publishing now with 'skipped' deliveries: the
        # regular path below then builds inside the normal prebuild window and publishes + delivers at push time.
        day_push = push_instant(target, tz, str(s["push_time"]))
        if now < day_push:
            with db.maybe_tx(conn):
                conn.execute(
                    "UPDATE user_settings SET next_push_at = ?, updated_at = ? WHERE user_id = ? AND next_push_at = ?",
                    (to_iso(day_push), to_iso(now), uid, s["next_push_at"]),
                )
            log.info("catch-up re-anchored to today's push time", extra={"event": "catchup_reanchored", "user_id": uid, "next_push_at": to_iso(day_push)})
            s = {**s, "next_push_at": to_iso(day_push)}
            next_push = day_push
            target, start = build_from(next_push, tz, prebuild_hours, now)
    batch: batches.Batch | None = None
    if now >= start:
        trigger = "scheduled" if now < next_push else "catchup"
        batch = batches.build_batch(conn, uid, target, trigger, now)
        if batch.created:
            result.built.append(batch.id)
    if now >= next_push:
        if batch is None:  # cannot happen (start <= next_push), kept for safety
            batch = batches.build_batch(conn, uid, target, "catchup", now)
        with db.maybe_tx(conn):
            if batches.publish_batch(conn, batch.id, now):
                stale = now - next_push > STALE_DELIVERY
                batches.enqueue_deliveries(conn, batch.id, now, stale=stale)
                result.published.append(batch.id)
                log.info("batch published", extra={"event": "batch_published", "user_id": uid, "batch_id": batch.id, "stale": stale})
            conn.execute(
                "UPDATE user_settings SET next_push_at = ?, updated_at = ? WHERE user_id = ? AND next_push_at = ?",
                (to_iso(compute_next_push(now, tz, str(s["push_time"]))), to_iso(now), uid, s["next_push_at"]),
            )


def process_pushes(conn: sqlite3.Connection, now: datetime, *, prebuild_hours: int, result: TickResult) -> None:
    for s in due_users(conn, now, prebuild_hours):
        try:
            process_user(conn, s, now, prebuild_hours=prebuild_hours, result=result)
        except Exception:  # one user's problem must not stop the others
            log.exception("scheduler: push processing failed for user %s", s.get("user_id"), extra={"user_id": s.get("user_id")})


# -------------------------------------------------------------------------------------------- hourly
def hourly_gc(conn: sqlite3.Connection, now: datetime, *, boot_id: str) -> bool:
    """Once per hour: expired sessions, finished throttle rows, stale ``running`` jobs (boot-id sweep)."""
    now_s = to_iso(now)
    last = db.kv_get(conn, KV_HOURLY)
    if last and parse_iso(last) > now - HOURLY:
        return False
    with db.maybe_tx(conn):
        conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (now_s,))
        conn.execute(
            "DELETE FROM auth_throttle WHERE (blocked_until IS NULL OR blocked_until <= ?) AND window_start < ?",
            (now_s, to_iso(now - timedelta(days=1))),
        )
        swept = queue.requeue_stale(conn, boot_id, now=now_s)
        db.kv_set(conn, KV_HOURLY, now_s, now=now_s)
    if swept:
        log.info("requeued %d stale running job(s)", swept, extra={"event": "stale_sweep"})
    return True


# ------------------------------------------------------------------------------------- consolidation
def nightly_consolidation(conn: sqlite3.Connection, now: datetime) -> int:
    """02:30 local per user: enqueue ``consolidate_bank`` once per local day (``kv consolidate:<uid>:last_date`` guard)."""
    enqueued = 0
    for u in _rows(
        conn,
        "SELECT u.id AS user_id, s.timezone FROM users u LEFT JOIN user_settings s ON s.user_id = u.id WHERE u.is_active = 1 AND u.onboarding_state = 'done'",
    ):
        uid = int(u["user_id"])
        tz = str(u["timezone"] or bank.DEFAULT_TIMEZONE)
        try:
            local = now.astimezone(zone(tz))
        except ValueError:
            continue
        if local.time() < CONSOLIDATE_AT:
            continue
        local_day = local.date().isoformat()
        key = f"consolidate:{uid}:last_date"
        if db.kv_get(conn, key) == local_day:
            continue
        with db.maybe_tx(conn):
            db.kv_set(conn, key, local_day, now=to_iso(now))
            if _bank_needs_consolidation(conn, uid):
                queue.enqueue(
                    conn,
                    "consolidate_bank",
                    {"user_id": uid, "trigger": "nightly"},
                    dedupe_key=f"consolidate:{uid}:{local_day}",
                    priority=CONSOLIDATE_PRIORITY,
                    now=to_iso(now),
                )
                enqueued += 1
    return enqueued


def _bank_needs_consolidation(conn: sqlite3.Connection, user_id: int) -> bool:
    """Bank rows changed since the last run, or still unvalidated / without a difficulty (DESIGN §6.4)."""
    last = conn.execute(
        "SELECT MAX(started_at) FROM consolidation_runs WHERE user_id = ? AND status IN ('done','skipped')",
        (int(user_id),),
    ).fetchone()[0]
    row = conn.execute(
        "SELECT 1 FROM user_words uw JOIN words w ON w.id = uw.word_id WHERE uw.user_id = ? AND uw.state IN ('new','learning') "
        "AND (? IS NULL OR uw.updated_at > ? OR w.is_valid_english IS NULL OR w.difficulty IS NULL) LIMIT 1",
        (int(user_id), last, last),
    ).fetchone()
    return row is not None


# --------------------------------------------------------------------------------------- maintenance
def prefetch(conn: sqlite3.Connection, now: datetime | str | None, *, cfg: Any = None) -> int:
    """DESIGN §6.4 ``maintenance.prefetch``: ≤ 50 priority-30 ``generate_content`` jobs per active push-enabled user
    for the words ``preview_selection(tomorrow)`` would pick, skipped entirely when AI is off/paused or
    ``budget.spent_today ≥ 50 %`` of ``WD_AI_DAILY_BUDGET_USD``. Returns the number of jobs enqueued."""
    now_dt, now_s = bank.coerce_now(now)
    if cfg is None:
        from ..config import get_settings

        cfg = get_settings()
    if not budget.ai_enabled(conn, cfg) or bank.ai_paused_until(conn, now_s) is not None:
        return 0
    spent = float(budget.spent_today(conn, cfg, now_s))
    cap = float(getattr(cfg, "ai_daily_budget_usd", 0.0) or 0.0)
    if spent >= PREFETCH_SPEND_SHARE * cap:
        log.info("prefetch skipped: spent %.3f of %.2f today", spent, cap, extra={"event": "prefetch_skipped"})
        return 0
    enqueued = 0
    for s in _rows(
        conn,
        "SELECT s.* FROM user_settings s JOIN users u ON u.id = s.user_id "
        "WHERE u.is_active = 1 AND u.onboarding_state = 'done' AND s.push_enabled = 1 ORDER BY s.user_id",
    ):
        uid = int(s["user_id"])
        tz = str(s["timezone"] or bank.DEFAULT_TIMEZONE)
        try:
            anchor = parse_iso(str(s["next_push_at"])) if s.get("next_push_at") else now_dt
            tomorrow = clock_local_date(anchor, tz)
        except ValueError:
            continue
        ids = batches.preview_selection(conn, uid, tomorrow, now_dt)
        if not ids:
            continue
        marks = ",".join("?" * len(ids))
        by_id = {
            int(r["id"]): r
            for r in _rows(
                conn,
                f"SELECT id, is_valid_english, merged_into_word_id, content_state FROM words WHERE id IN ({marks}) "
                "AND content_state IN ('none','failed') AND is_valid_english = 1 AND merged_into_word_id IS NULL",
                ids,
            )
        }
        candidates = [by_id[w] for w in ids if w in by_id][:PREFETCH_LIMIT]
        count = 0
        with db.maybe_tx(conn):
            for word in candidates:
                if bank.enqueue_content_if_needed(conn, word, priority=PREFETCH_PRIORITY, now=now_s) is not None:
                    count += 1
        enqueued += count
        if count:
            log.info("prefetched %d word(s) for user %s", count, uid, extra={"event": "prefetch", "user_id": uid})
    return enqueued


def requeue_dead_once(conn: sqlite3.Connection, now: datetime) -> int:
    """Nightly: up to 50 ``dead`` content/lookup jobs older than 24 h back to ``queued`` once (``attempts 0``, ``group_size 1``).

    A dead row whose dedupe key is held by a live (``queued``/``running``) job — a 重试, a fresh batch/prefetch enqueue
    of the same word — is not a candidate: its work is already queued, and it must not take one of the 50 slots. Each
    candidate is updated on its own, so a key shared by two dead rows (a dead job and its re-enqueued, also-dead
    successor) or a race with a concurrent enqueue only skips that row (``ux_jobs_dedupe_live``) instead of aborting
    the whole night's requeue; a skipped row keeps ``requeued_at`` NULL and stays eligible. Returns the rows requeued.
    """
    now_s = to_iso(now)
    cutoff = to_iso(now - DEAD_REQUEUE_AGE)
    with db.maybe_tx(conn):
        ids = [
            int(r[0])
            for r in conn.execute(
                "SELECT j.id FROM jobs j WHERE j.status = 'dead' AND j.type IN ('generate_content','lookup_word') "
                "AND COALESCE(j.finished_at, j.updated_at) < ? AND json_extract(j.payload_json, '$.requeued_at') IS NULL "
                "AND NOT EXISTS (SELECT 1 FROM jobs l WHERE l.dedupe_key = j.dedupe_key AND l.status IN ('queued','running')) "
                "ORDER BY j.id LIMIT ?",
                (cutoff, DEAD_REQUEUE_LIMIT),
            )
        ]
        requeued = 0
        for job_id in ids:
            try:
                cur = conn.execute(
                    "UPDATE jobs SET status = 'queued', attempts = 0, payload_json = json_set(payload_json, '$.group_size', 1, '$.requeued_at', ?), "
                    "run_after = ?, updated_at = ?, finished_at = NULL, locked_at = NULL, locked_by = NULL WHERE id = ? AND status = 'dead'",
                    (now_s, now_s, now_s, job_id),
                )
                requeued += int(cur.rowcount)
            except sqlite3.IntegrityError:  # statement-level abort: the transaction stays open
                log.info("dead job %d not requeued: its dedupe key is held by a live job", job_id, extra={"event": "dead_requeue_skipped", "job_id": job_id})
        return requeued


def prune_claude_logs(cfg: Any, now: datetime) -> int:
    """Remove ``claude-logs/YYYY-MM-DD`` directories older than ``WD_AI_LOG_KEEP_DAYS``."""
    keep_days = int(getattr(cfg, "ai_log_keep_days", 14) or 0)
    root = getattr(cfg, "claude_logs_dir", None)
    if root is None or not root.is_dir() or keep_days <= 0:
        return 0
    cutoff = (now.date() - timedelta(days=keep_days)).isoformat()
    removed = 0
    for child in root.iterdir():
        if child.is_dir() and len(child.name) == 10 and child.name < cutoff:
            try:
                date.fromisoformat(child.name)
            except ValueError:
                continue
            shutil.rmtree(child, ignore_errors=True)
            removed += 1
    return removed


def maintenance(conn: sqlite3.Connection, now: datetime, *, cfg: Any, result: TickResult) -> bool:
    """03:30 ``WD_TZ`` once per day (``kv maintenance.last_date``)."""
    local = now.astimezone(zone(cfg.tz))
    if local.time() < MAINTENANCE_AT:
        return False
    local_day = local.date().isoformat()
    if db.kv_get(conn, KV_MAINTENANCE) == local_day:
        return False
    db.kv_set(conn, KV_MAINTENANCE, local_day, now=to_iso(now))
    try:
        result.prefetched = prefetch(conn, now, cfg=cfg)
    except Exception:
        log.exception("maintenance: prefetch failed")
    try:
        requeued = requeue_dead_once(conn, now)
        if requeued:
            log.info("maintenance: requeued %d dead job(s)", requeued, extra={"event": "dead_requeue"})
    except Exception:
        log.exception("maintenance: dead-job requeue failed")
    try:
        prune_claude_logs(cfg, now)
    except Exception:
        log.exception("maintenance: claude-logs pruning failed")
    try:
        conn.execute("PRAGMA optimize")
        conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
    except sqlite3.Error as e:
        log.warning("maintenance: PRAGMA failed: %s", e)
    result.maintenance = True
    log.info("maintenance done", extra={"event": "maintenance"})
    return True


# -------------------------------------------------------------------------------------------- downtime
def check_downtime(conn: sqlite3.Connection, now: datetime) -> dict[str, str] | None:
    """On startup: a ``downtime`` event with ``{"from": kv.last_tick_at, "to": now}`` when the gap exceeds 10 min."""
    last = db.kv_get(conn, KV_LAST_TICK)
    if not last:
        return None
    try:
        last_dt = parse_iso(last)
    except ValueError:
        return None
    if now - last_dt <= DOWNTIME_GAP:
        return None
    detail = {"from": to_iso(last_dt), "to": to_iso(now)}
    with db.maybe_tx(conn):
        conn.execute("INSERT INTO system_events(kind, detail_json, created_at) VALUES ('downtime', ?, ?)", (json.dumps(detail), to_iso(now)))
    log.warning("downtime detected: %s → %s", detail["from"], detail["to"], extra={"event": "downtime"})
    return detail


# ------------------------------------------------------------------------------------------------ tick
def run_tick(conn: sqlite3.Connection, now: datetime, *, cfg: Any, boot_id: str = "", startup: bool = False) -> TickResult:
    """One DESIGN §6.4 tick over an open connection (what :meth:`Scheduler.tick` runs)."""
    result = TickResult()
    if startup:
        result.downtime = check_downtime(conn, now)
    process_pushes(conn, now, prebuild_hours=int(cfg.prebuild_hours), result=result)
    try:
        result.finalized = batches.finalize_building(conn, now, cfg=cfg)
    except Exception:
        log.exception("scheduler: finalize_building failed")
    try:
        result.gc = hourly_gc(conn, now, boot_id=boot_id)
    except Exception:
        log.exception("scheduler: hourly GC failed")
    try:
        result.consolidations = nightly_consolidation(conn, now)
    except Exception:
        log.exception("scheduler: nightly consolidation failed")
    try:
        maintenance(conn, now, cfg=cfg, result=result)
    except Exception:
        log.exception("scheduler: maintenance failed")
    db.kv_set(conn, KV_LAST_TICK, to_iso(now), now=to_iso(now))
    return result


class Scheduler(threading.Thread):
    """The tick thread (``interfaces.BackgroundThread``): ``Scheduler(ctx).start()``, ``stop()``, ``join(timeout)``.

    ``lease_lost`` (the ``LeaseKeeper.lost`` event, see ``jobs.lease``) fences the thread: no tick runs while it is set,
    because another instance holds the worker lease and runs its own scheduler — two tickers would build/publish twice
    (idempotent, but wasteful) and ``hourly_gc``'s stale sweep would requeue the holder's running jobs.
    """

    def __init__(self, ctx: JobContext, *, lease_lost: threading.Event | None = None):
        super().__init__(name=ctx.worker_id or "scheduler", daemon=True)
        self.ctx = ctx
        self.lease_lost = lease_lost
        self._stop_event = threading.Event()
        self._first = True
        self._was_fenced = False
        self.last_result: TickResult | None = None

    @property
    def fenced(self) -> bool:
        """True while the lease keeper reports the worker lease held by another instance."""
        return self.lease_lost is not None and self.lease_lost.is_set()

    def tick(self, now: datetime) -> None:
        conn = self.ctx.db()
        try:
            self.last_result = run_tick(conn, now, cfg=self.ctx.cfg, boot_id=self.ctx.boot_id, startup=self._first)
        finally:
            conn.close()
        self._first = False

    def step(self) -> bool:
        """One loop iteration: a tick unless fenced. Returns True when a tick ran (exceptions are logged, not raised)."""
        if self.fenced:
            if not self._was_fenced:
                self._was_fenced = True
                self.ctx.log.warning("scheduler: worker lease held by another instance; ticks suspended", extra={"worker": self.ctx.worker_id, "event": "lease_fenced"})
            return False
        if self._was_fenced:
            self._was_fenced = False
            self.ctx.log.info("scheduler: worker lease re-acquired; ticks resumed", extra={"worker": self.ctx.worker_id, "event": "lease_resumed"})
        try:
            self.tick(self.ctx.clock.now_utc())
        except Exception:
            self.ctx.log.exception("scheduler tick failed", extra={"worker": self.ctx.worker_id})
        return True

    def run(self) -> None:
        interval = max(1, int(getattr(self.ctx.cfg, "tick_seconds", 60) or 60))
        while not self._stop_event.is_set():
            self.step()
            if self._stop_event.wait(interval):
                break

    def stop(self) -> None:
        self._stop_event.set()


# ------------------------------------------------------------------------------------------------- CLI
def cmd_tick(args: argparse.Namespace) -> int:
    from ..cli import LEASE_HINT
    from ..config import Settings, ensure_dirs

    cfg = Settings.from_env()
    ensure_dirs(cfg)

    def connect() -> sqlite3.Connection:
        return db.connect(cfg.db_path)

    conn = connect()
    try:
        if lease.is_live(conn, to_iso(SYSTEM_CLOCK.now_utc())):
            print(f"wd tick: {LEASE_HINT}", file=sys.stderr)
            return 2
    finally:
        conn.close()
    ctx = JobContext(db=connect, cfg=cfg, clock=SYSTEM_CLOCK, enqueue=queue.enqueue, log=log, worker_id="tick", boot_id=uuid.uuid4().hex)
    sched = Scheduler(ctx)
    if args.once:
        sched.tick(SYSTEM_CLOCK.now_utc())
        r = sched.last_result or TickResult()
        print(f"tick: built {len(r.built)}, published {len(r.published)}, finalized {r.finalized}, consolidations {r.consolidations}, prefetched {r.prefetched}, maintenance {r.maintenance}")
        return 0
    print(f"ticking every {cfg.tick_seconds} s (Ctrl-C to stop)")
    try:
        while True:
            sched.tick(SYSTEM_CLOCK.now_utc())
            _time.sleep(max(1, cfg.tick_seconds))
    except KeyboardInterrupt:
        return 0


def register_cli(sub: argparse._SubParsersAction) -> None:
    """``wd tick [--once]`` (DEPLOY §9): exits 2 with the lease hint while ``word-dance.service`` runs."""
    p = sub.add_parser("tick", help="run the scheduler tick (dev/tests); refuses while the service holds the worker lease")
    p.add_argument("--once", action="store_true", help="run a single tick and exit")
    p.set_defaults(func=cmd_tick)


__all__ = [
    "CONSOLIDATE_AT",
    "DOWNTIME_GAP",
    "MAINTENANCE_AT",
    "PREFETCH_LIMIT",
    "PREFETCH_PRIORITY",
    "STALE_DELIVERY",
    "Scheduler",
    "TickResult",
    "build_from",
    "check_downtime",
    "due_users",
    "hourly_gc",
    "maintenance",
    "nightly_consolidation",
    "prefetch",
    "process_pushes",
    "process_user",
    "prune_claude_logs",
    "push_instant",
    "register_cli",
    "requeue_dead_once",
    "run_tick",
]
