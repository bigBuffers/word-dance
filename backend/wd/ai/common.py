"""Plumbing shared by the Claude job handlers (CLAUDE_INTEGRATION §6.2–§6.4).

* :func:`claude_call` — reserve budget for a group of jobs (deferring them when a cap, the pause or the kill switch
  says no — never an attempt consumed) and run ``claude`` once for the group.
* :func:`handle_failure` — the §6.3 outcome table for a failed group: ``budget`` → bisection, ``error`` /
  ``invalid_output`` / ``timeout`` → backoff then bisection, ``overloaded`` → deferral (+ 15-min pause after six
  in a row), ``auth`` / ``spawn_error`` → 30-min pause + ``system_events`` + jobs stay queued.
* text post-validation helpers (control characters and HTML tags stripped; ``http://`` / ``https://`` /
  ``<script`` rejected; CJK / ASCII checks) used by content, lookup and consolidate.
"""

from __future__ import annotations

import json
import logging
import math
import re
import sqlite3
from datetime import timedelta
from typing import Any, Callable, Sequence

from .. import db
from ..clock import parse_iso, to_iso
from ..interfaces import ClaudeResult, Job
from ..jobs import queue
from ..jobs.registry import JobContext
from . import budget, runner

log = logging.getLogger("wd.ai")

OVERLOAD_STREAK_KEY = "claude.overloaded_streak"
OVERLOAD_PAUSE_AFTER = 6
OVERLOAD_PAUSE = timedelta(minutes=15)
OVERLOAD_DEFER_STEP = timedelta(minutes=2)
AUTH_PAUSE = timedelta(minutes=30)
AUTH_BANNER_ZH = "Claude CLI 未登录，请以 sqin 身份运行 claude 完成登录"

CJK_RE = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
TAG_RE = re.compile(r"<[^<>]{0,300}>")
FORBIDDEN_RE = re.compile(r"https?://|<script", re.IGNORECASE)
SPACE_RE = re.compile(r"[ \t\r\f\v]+")

OnDead = Callable[[sqlite3.Connection, Job], None]


# ------------------------------------------------------------------------------------------ text
def clean_text(value: Any, *, max_len: int | None = None) -> str | None:
    """Strip control characters and HTML tags; None when ``value`` is not a string or carries a URL / ``<script``."""
    if not isinstance(value, str):
        return None
    if FORBIDDEN_RE.search(value):
        return None
    s = TAG_RE.sub("", CONTROL_RE.sub("", value))
    s = SPACE_RE.sub(" ", s).strip()
    if max_len is not None and len(s) > max_len:
        s = s[:max_len].rstrip()
    return s


def has_cjk(text: str | None) -> bool:
    return bool(text) and CJK_RE.search(text) is not None


def ascii_ratio(text: str) -> float:
    if not text:
        return 0.0
    return sum(1 for ch in text if ord(ch) < 128) / len(text)


def item_index(items: Any, key: str) -> dict[str, dict]:
    """Index a response's ``items`` list by the lower-cased value of ``key`` (first occurrence wins)."""
    out: dict[str, dict] = {}
    if not isinstance(items, list):
        return out
    for it in items:
        if isinstance(it, dict) and isinstance(it.get(key), str):
            out.setdefault(it[key].strip().lower(), it)
    return out


def validate_target(conn: sqlite3.Connection, proposed: Any, input_lemma: str) -> "words.Normalised | None":
    """``words.validate_headword`` for a Claude-proposed headword, tolerating hyphenation / spacing variants of the
    same word (``e-mail`` ↔ ``email``) that the first-three-letters relatedness rule alone would reject."""
    from ..services import words

    if not isinstance(proposed, str) or not proposed.strip():
        return None
    norm = words.validate_headword(proposed, input_lemma, conn)
    if norm is not None:
        return norm
    compact = input_lemma.replace("-", "").replace(" ", "")
    if compact != input_lemma:
        norm = words.validate_headword(proposed, compact, conn)
        if norm is not None:
            return norm
    candidate = words.normalise_input(proposed)
    if candidate.ok and isinstance(candidate, words.Normalised) and candidate.lemma.replace("-", "").replace(" ", "") == compact:
        return candidate
    return None


def payload_int(job: Job, key: str) -> int | None:
    v = job.payload.get(key)
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def system_event(conn: sqlite3.Connection, kind: str, detail: dict, *, now: str) -> None:
    with db.maybe_tx(conn):
        conn.execute(
            "INSERT INTO system_events(kind, detail_json, created_at) VALUES (?, ?, ?)",
            (kind, json.dumps(detail, ensure_ascii=False, sort_keys=True), now),
        )


# ------------------------------------------------------------------------------------------ call
def claude_call(
    ctx: JobContext,
    conn: sqlite3.Connection,
    *,
    kind: str,
    jobs: Sequence[Job],
    system_prompt: str,
    user_prompt: str,
    schema: dict,
    word_count: int,
    now: str,
    on_disabled: Callable[[], None] | None = None,
) -> ClaudeResult | None:
    """Reserve budget for ``jobs`` and run one ``claude`` call; None when the group was deferred instead.

    The reservation (:func:`wd.ai.budget.reserve`) is the §6.2 ``can_spend`` step: kill switch, pause, hourly,
    monthly, daily, prewarm and SVG caps. A refused group is ``queue.defer``red to ``resumes_at`` (no attempt).
    ``on_disabled`` runs when the refusal came from the kill switch (lookups flag their bank rows 「暂时无法校验」).
    """
    cfg = ctx.cfg
    ids = [j.id for j in jobs]
    if on_disabled is not None and not budget.ai_enabled(conn, cfg):
        on_disabled()
    reservation = budget.reserve(
        conn,
        kind=kind,
        word_count=word_count,
        priority=min(j.priority for j in jobs),
        now=now,
        cfg=cfg,
        flag_tier=int(runner.flag_tier(conn)),
        job_ids=ids,
    )
    if not reservation.ok:
        resumes = reservation.resumes_at or to_iso(parse_iso(now) + timedelta(minutes=30))
        queue.defer(conn, ids, resumes, now=now)
        ctx.log.info("%s: %d job(s) deferred until %s (budget/pause)", kind, len(ids), resumes, extra={"job_type": jobs[0].type, "event": "ai_deferred"})
        return None
    return runner.run_claude(
        conn,
        kind=kind,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        schema=schema,
        max_budget_usd=budget.budget_for(cfg, kind),
        timeout_s=budget.timeout_for(cfg, kind),
        word_count=word_count,
        job_ids=ids,
        cfg=cfg,
        now=now,
        call_id=reservation.call_id,
    )


# -------------------------------------------------------------------------------------- outcomes
def fail_job(conn: sqlite3.Connection, job: Job, error: str, *, now: str, on_dead: OnDead | None = None) -> str:
    """``queue.fail`` (backoff or dead) plus the handler's dead-job side effect; returns the resulting status."""
    status = queue.fail(conn, job.id, error, now=now)
    if status == "dead" and on_dead is not None:
        on_dead(conn, job)
    return status


def _dead_members(conn: sqlite3.Connection, ids: Sequence[int]) -> set[int]:
    if not ids:
        return set()
    marks = ",".join("?" * len(ids))
    return {int(r[0]) for r in conn.execute(f"SELECT id FROM jobs WHERE status = 'dead' AND id IN ({marks})", list(ids))}


def record_success(conn: sqlite3.Connection, *, now: str) -> None:
    """A successful call ends an ``overloaded`` streak."""
    if db.kv_get(conn, OVERLOAD_STREAK_KEY) not in (None, "0"):
        with db.maybe_tx(conn):
            db.kv_set(conn, OVERLOAD_STREAK_KEY, "0", now=now)


def handle_failure(
    ctx: JobContext,
    conn: sqlite3.Connection,
    jobs: Sequence[Job],
    result: ClaudeResult,
    *,
    now: str,
    on_dead: OnDead | None = None,
    error: str | None = None,
) -> str:
    """Apply the §6.3 table to a failed group; returns the action taken (``bisect`` / ``fail`` / ``defer`` / ``pause``)."""
    status = result.status
    ids = [j.id for j in jobs]
    n = len(jobs)
    err = (error or result.error or status)[:1000]
    kind_label = jobs[0].type if jobs else "?"
    if status == "budget":
        if n >= 2:
            half = math.ceil(n / 2)
            queue.requeue_group(conn, ids, half, consume_attempt=False, error=f"budget stop; bisecting to groups of {half}", now=now)
            ctx.log.warning("%s: --max-budget-usd stop on %d jobs → group_size %d", kind_label, n, half, extra={"job_type": kind_label, "event": "ai_bisect"})
            return "bisect"
        fail_job(conn, jobs[0], f"budget stop on a single job: {err}", now=now, on_dead=on_dead)
        return "fail"
    if status in ("invalid_output", "error", "timeout"):
        if n >= 2 and max(j.attempts for j in jobs) >= 2:
            half = math.ceil(n / 2)
            queue.requeue_group(conn, ids, half, consume_attempt=True, error=f"{status}: {err}", now=now)
            if on_dead is not None:
                dead = _dead_members(conn, ids)
                for j in jobs:
                    if j.id in dead:
                        on_dead(conn, j)
            ctx.log.warning("%s: second %s on a group of %d → group_size %d", kind_label, status, n, half, extra={"job_type": kind_label, "event": "ai_bisect"})
            return "bisect"
        for j in jobs:
            fail_job(conn, j, f"{status}: {err}", now=now, on_dead=on_dead)
        return "fail"
    if status == "overloaded":
        attempts = max([j.attempts for j in jobs] + [1])
        until = to_iso(parse_iso(now) + OVERLOAD_DEFER_STEP * attempts)
        with db.maybe_tx(conn):
            streak = int(db.kv_get(conn, OVERLOAD_STREAK_KEY, "0") or 0) + 1
            if streak >= OVERLOAD_PAUSE_AFTER:
                pause_until = to_iso(parse_iso(now) + OVERLOAD_PAUSE)
                budget.set_paused_until(conn, pause_until, now=now)
                db.kv_set(conn, OVERLOAD_STREAK_KEY, "0", now=now)
                system_event(conn, "claude_overloaded", {"paused_until": pause_until, "consecutive": streak}, now=now)
                until = max(until, pause_until)
            else:
                db.kv_set(conn, OVERLOAD_STREAK_KEY, str(streak), now=now)
            queue.defer(conn, ids, until, now=now)
        ctx.log.warning("%s: claude overloaded; %d job(s) deferred until %s", kind_label, n, until, extra={"job_type": kind_label, "event": "ai_overloaded"})
        return "defer"
    if status in ("auth", "spawn_error"):
        pause_until = to_iso(parse_iso(now) + AUTH_PAUSE)
        with db.maybe_tx(conn):
            budget.set_paused_until(conn, pause_until, now=now)
            if status == "spawn_error":
                db.kv_set(conn, "claude.available", "0", now=now)
            budget.event_once(
                conn,
                "claude_auth",
                to_iso(parse_iso(now) - AUTH_PAUSE),
                {"status": status, "error": err[:300], "paused_until": pause_until, "banner_zh": AUTH_BANNER_ZH},
                now=now,
            )
            queue.defer(conn, ids, pause_until, now=now)
        ctx.log.error("%s: claude %s — AI paused until %s", kind_label, status, pause_until, extra={"job_type": kind_label, "event": f"claude_{status}"})
        return "pause"
    for j in jobs:  # unknown status: treat as an ordinary error
        fail_job(conn, j, f"{status}: {err}", now=now, on_dead=on_dead)
    return "fail"


__all__ = [
    "AUTH_BANNER_ZH",
    "ascii_ratio",
    "claude_call",
    "clean_text",
    "fail_job",
    "handle_failure",
    "has_cjk",
    "item_index",
    "payload_int",
    "record_success",
    "system_event",
    "validate_target",
]
