"""Plumbing shared by the Claude job handlers (CLAUDE_INTEGRATION §6.2–§6.4, §10).

* :func:`claude_call` — ask ``ai/failover.py`` which provider takes the group (the ``claude`` CLI or the ``fallback``
  HTTP adapter), split off the prewarm members of a mixed group (parking the whole runnable prewarm backlog of the type
  with them, so an ordinary job is split at most once, §10.5) and regroup a content group larger than the fallback's
  batch before it runs there (``failover.group_cap``: ``min(WD_AI_BATCH_SIZE, WD_AI_FALLBACK_BATCH_SIZE)`` — the jobs
  go back queued in groups of that size, no attempt consumed), reserve budget for it (deferring the jobs when a cap, a pause or the kill switch
  says no — never an attempt consumed), run the call once, and on a hard/soft failover trigger rerun the same group on
  the other provider immediately (§10). The handlers only ever see one ``ClaudeResult`` (``result.provider`` says who
  answered).
* :func:`record_invalid_output` / :func:`record_applied` — the handlers' post-validation verdict on an ok answer,
  forwarded to ``failover`` so the fallback's quality streak counts a group rejected whole and ends on a group applied
  (three unusable fallback answers in a row pause it 30 minutes, §10.4); both are no-ops for a claude answer.
* :func:`handle_failure` — the §6.3 outcome table for a failed group: ``budget`` → bisection, a ``truncated:`` error on
  a group of ≥ 2 → bisection like ``budget`` (a too-long answer is a size signal: no attempt consumed; the fallback's
  quality strike for it is still counted by ``failover``), ``error`` / ``invalid_output`` / ``timeout`` → backoff then
  bisection, ``overloaded`` → deferral (the 15-min pause after six in
  a row is applied by ``failover.record_failure``), ``auth`` / ``spawn_error`` (the binary is missing or unusable — an
  oversized argv is an ordinary ``error``, see ``runner``) → jobs deferred to the provider's pause (written by
  ``failover``, together with ``system_events``) and stay queued.
* text post-validation helpers (control characters and HTML tags stripped; ``http://`` / ``https://`` /
  ``<script`` rejected; CJK / ASCII checks) used by content, lookup and consolidate.
* :func:`record_success` — a deprecated no-op kept for the handlers' call sites; the streaks of the provider that
  answered are reset by ``failover.record_success`` inside :func:`claude_call` (the single writer, §10.4).
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
from . import budget, failover, runner
from .providers import CLAUDE, FALLBACK

log = logging.getLogger("wd.ai")

OVERLOAD_STREAK_KEY = "claude.overloaded_streak"
OVERLOAD_PAUSE_AFTER = 6
OVERLOAD_PAUSE = timedelta(minutes=15)
OVERLOAD_DEFER_STEP = timedelta(minutes=2)
AUTH_PAUSE = timedelta(minutes=30)
AUTH_BANNER_ZH = failover.AUTH_BANNER_ZH

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


def clean_phonetic(value: Any, *, max_len: int | None = 60) -> str | None:
    """``clean_text`` plus the IPA delimiters stripped: Claude writes ``/ˌdʒiː diː ˈpiː/`` or ``[ˈæpl]`` while the seed
    (and the UI, which wraps phonetics in slashes itself) store the bare transcription."""
    s = clean_text(value, max_len=max_len)
    if s is None:
        return None
    s = s.strip().strip("/[]").strip()
    return s or None


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
def run_provider(
    conn: sqlite3.Connection,
    provider: str,
    *,
    kind: str,
    system_prompt: str,
    user_prompt: str,
    schema: dict,
    word_count: int,
    job_ids: list[int],
    cfg: Any,
    now: str,
    call_id: int | None,
) -> ClaudeResult:
    """One call on ``provider`` against an existing ledger row: the CLI (``runner.run_claude``) or the HTTP adapter."""
    if provider == FALLBACK:
        from .providers import openai_http  # local: httpx + jsonschema only matter when a fallback is configured

        return openai_http.run_openai(
            conn,
            kind=kind,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            schema=schema,
            timeout_s=budget.timeout_for(cfg, kind, FALLBACK),
            word_count=word_count,
            job_ids=job_ids,
            cfg=cfg,
            now=now,
            call_id=call_id,
        )
    return runner.run_claude(
        conn,
        kind=kind,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        schema=schema,
        max_budget_usd=budget.budget_for(cfg, kind),
        timeout_s=budget.timeout_for(cfg, kind),
        word_count=word_count,
        job_ids=job_ids,
        cfg=cfg,
        now=now,
        call_id=call_id,
    )


def _park_prewarm_members(
    ctx: JobContext,
    conn: sqlite3.Connection,
    *,
    kind: str,
    jobs: Sequence[Job],
    provider: str,
    job_type: str,
    now: str,
) -> bool:
    """Split a claimed group that mixes prewarm jobs (priority ≥ 90) with ordinary ones before it runs on the fallback;
    True when it was split (the caller returns None, exactly like a deferral).

    ``queue.claim_batch`` groups by type, not by priority, and ``failover.fallback_eligible`` judges a group by its
    lowest priority: without this a prewarm backlog would drain through the free tier a few words at a time behind
    every user request while the CLI is down, which ``WD_AI_FALLBACK_PREWARM=0`` (the default) is meant to prevent. The
    prewarm members are parked at the instant a pure prewarm group would wait for (``failover.choose(priority=90)``:
    the claude pause, which ``_release_parked`` lifts on fail-back; 30 minutes when nothing is scheduled) — or two
    minutes ahead when claude could take them right now — and so is, in the same transaction, every other runnable
    prewarm job of the type (``queued``, priority ≥ 90, ``run_after`` before that instant): one split parks the whole
    runnable prewarm backlog, so the ordinary members are claimed alone at the next claim and an ordinary job is split
    at most once however large the backlog (a split per claim would otherwise walk it a few jobs at a time, the same
    ordinary job riding along). The ordinary members go back to ``queued`` runnable now with the claim's attempt undone
    and ``payload.group_size`` untouched; the prewarm ones become a pure group at the parked instant. Nothing happens
    for claude, with ``WD_AI_FALLBACK_PREWARM`` or for a pure group.
    """
    cfg = ctx.cfg
    if provider != FALLBACK or bool(getattr(cfg, "ai_fallback_prewarm", False)):
        return False
    prewarm = [j.id for j in jobs if int(j.priority) >= budget.PREWARM_PRIORITY]
    if not prewarm or len(prewarm) == len(jobs):
        return False
    others = [j.id for j in jobs if int(j.priority) < budget.PREWARM_PRIORITY]
    taker, resumes_at = failover.choose(conn, cfg, kind=kind, priority=budget.PREWARM_PRIORITY, now=now)
    if taker is None:
        parked_until = resumes_at or to_iso(parse_iso(now) + timedelta(minutes=30))
    else:
        parked_until = to_iso(parse_iso(now) + OVERLOAD_DEFER_STEP)
    with db.maybe_tx(conn):
        queue.defer(conn, prewarm, parked_until, now=now)
        backlog = int(
            conn.execute(
                "UPDATE jobs SET run_after = ?, updated_at = ? WHERE type = ? AND status = 'queued' AND priority >= ? AND run_after < ?",
                (parked_until, now, job_type, budget.PREWARM_PRIORITY, parked_until),
            ).rowcount
        )
        queue.defer(conn, others, now, now=now)
    ctx.log.info(
        "%s: %d prewarm job(s) parked until %s (+%d runnable prewarm job(s) of the backlog parked with them); %d ordinary job(s) requeued to run alone on %s",
        kind,
        len(prewarm),
        parked_until,
        backlog,
        len(others),
        provider,
        extra={"job_type": job_type, "event": "ai_failover_split"},
    )
    return True


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
    """Choose a provider, reserve budget for ``jobs`` and run the call; None when the group was deferred or regrouped instead.

    ``failover.choose`` picks the provider (CLAUDE_INTEGRATION §10: the sticky ``kv.ai.active_provider``, per-provider
    pauses, the kinds the fallback may serve). Before every run — the first and the rerun alike — two shape checks for
    the provider about to run: a group mixing prewarm (priority ≥ 90) and ordinary jobs is split before it runs on the
    fallback (:func:`_park_prewarm_members`), and a group larger than ``failover.group_cap`` allows (content on the
    fallback: ``min(WD_AI_BATCH_SIZE, WD_AI_FALLBACK_BATCH_SIZE)``, §10.5) is ``queue.requeue_group``ed to that size with
    the claim's attempt given back and ``run_after = now`` (``payload.group_size`` + ``failover.claim_limit`` make the
    next claims run it in groups of ≤ cap on the fallback); that covers both the rerun after a CLI failure (a 10-word
    group) and the race where the state flipped between the claim and ``choose``. In both cases the handler gets None,
    exactly like a deferral. The reservation (:func:`wd.ai.budget.reserve`) is the §6.2 ``can_spend``
    step for that provider: kill switch, pauses, its hourly cap, monthly, daily, prewarm and SVG caps. A refused group
    is ``queue.defer``red to ``resumes_at`` (no attempt). After a failure ``failover.record_failure`` applies the
    provider's pause / streak bookkeeping and may name the other provider: the same group is then rerun there at once
    (one retry), so an outage of the CLI costs the learner seconds, not 30 minutes. ``on_disabled`` runs when the kill
    switch is off (lookups flag their bank rows 「暂时无法校验」).
    """
    cfg = ctx.cfg
    ids = [j.id for j in jobs]
    priority = min(j.priority for j in jobs)
    job_type = jobs[0].type if jobs else kind
    if on_disabled is not None and not budget.ai_enabled(conn, cfg):
        on_disabled()
    provider, resumes_at = failover.choose(conn, cfg, kind=kind, priority=priority, now=now)
    if provider is None:
        resumes = resumes_at or to_iso(parse_iso(now) + timedelta(minutes=30))
        queue.defer(conn, ids, resumes, now=now)
        ctx.log.info("%s: %d job(s) deferred until %s (no provider available)", kind, len(ids), resumes, extra={"job_type": job_type, "event": "ai_deferred"})
        return None
    result: ClaudeResult | None = None
    for attempt in (1, 2):
        if _park_prewarm_members(ctx, conn, kind=kind, jobs=jobs, provider=provider, job_type=job_type, now=now):
            return None
        cap = failover.group_cap(cfg, kind, provider)
        if cap is not None and len(ids) > cap:
            queue.requeue_group(conn, ids, cap, consume_attempt=False, error=f"failover: regrouped to {cap} for {provider}", now=now)
            ctx.log.warning("%s: group of %d regrouped to %d for %s", kind, len(ids), cap, provider, extra={"job_type": job_type, "event": "ai_failover_regroup"})
            return None
        reservation = budget.reserve(
            conn,
            kind=kind,
            word_count=word_count,
            priority=priority,
            now=now,
            cfg=cfg,
            flag_tier=int(runner.flag_tier(conn)) if provider == CLAUDE else 0,
            job_ids=ids,
            provider=provider,
        )
        if not reservation.ok:
            if result is not None:
                return result  # the retry provider cannot take the group right now: the handler acts on the first failure
            resumes = reservation.resumes_at or to_iso(parse_iso(now) + timedelta(minutes=30))
            queue.defer(conn, ids, resumes, now=now)
            ctx.log.info("%s: %d job(s) deferred until %s (budget/pause on %s)", kind, len(ids), resumes, provider, extra={"job_type": job_type, "event": "ai_deferred"})
            return None
        result = run_provider(
            conn,
            provider,
            kind=kind,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            schema=schema,
            word_count=word_count,
            job_ids=ids,
            cfg=cfg,
            now=now,
            call_id=reservation.call_id,
        )
        if result.ok:
            failover.record_success(conn, cfg, provider=provider, kind=kind, model_used=result.model_used, now=now, call_id=result.call_id)
            return result
        decision = failover.record_failure(conn, cfg, provider=provider, result=result, kind=kind, now=now, attempts=max([j.attempts for j in jobs] + [1]), priority=priority)
        if attempt == 1 and decision.retry_provider and decision.retry_provider != provider:
            ctx.log.warning(
                "%s: %s failed (%s) — rerunning the group of %d on %s",
                kind,
                provider,
                result.status,
                len(ids),
                decision.retry_provider,
                extra={"job_type": job_type, "event": "ai_failover_retry"},
            )
            provider = decision.retry_provider
            continue
        return result
    return result


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
    """Deprecated no-op, kept for the handlers that still call it after an ok result (lookup, content, consolidate, svg).

    ``failover.record_success`` inside :func:`claude_call` is the single writer of the streaks and resets those of the
    provider that actually answered (CLAUDE_INTEGRATION §10.4). Resetting ``claude.overloaded_streak`` here as well
    would let a fallback success wipe the CLI's own streak — in mode ``auto`` with the fallback active, lookups
    succeeding there every minute would keep a content-only CLI overload from ever reaching the six-streak relief
    pause and its ``claude_overloaded`` event. Mode ``claude_cli`` is unchanged: the same key is reset by ``failover``.
    """
    return None


def record_invalid_output(conn: sqlite3.Connection, cfg: Any, result: ClaudeResult, *, kind: str, priority: int, now: str) -> None:
    """A handler rejected every item of an ok answer and re-classified the group ``invalid_output`` (``result`` is that
    reclassified result, ``result.provider`` the provider that answered): report it to ``failover.record_failure`` so the
    fallback's quality streak counts it — three in a row pause the fallback for the cooldown (CLAUDE_INTEGRATION §10.4).
    A claude result is a Decision ``none``: nothing happens. The group is never rerun on the other provider; the caller
    runs :func:`handle_failure` next, as before (``priority`` = ``min(j.priority for j in jobs)``, like ``claude_call``).
    """
    failover.record_failure(conn, cfg, provider=result.provider, result=result, kind=kind, now=now, priority=priority)


def record_applied(conn: sqlite3.Connection, cfg: Any, result: ClaudeResult, *, now: str) -> None:
    """A handler stored at least one item of ``result``: the answering provider's quality streak ends
    (``failover.record_quality_success``; a no-op for claude). ``cfg`` is unused today and accepted for symmetry with
    :func:`record_invalid_output` (a threshold or kind rule may need it later without touching the handlers)."""
    failover.record_quality_success(conn, provider=result.provider, now=now)


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
    """Apply the §6.3 table to a failed group; returns the action taken (``bisect`` / ``fail`` / ``defer`` / ``pause``).

    A ``truncated:`` error (the answer hit the provider's output limit) on a group of ≥ 2 is a size signal, not a model
    miss: the group is halved exactly like a ``budget`` stop — ``queue.requeue_group(consume_attempt=False)``, runnable
    at once, no attempt spent — so the words reach a smaller group (and finally a solo attempt) before any of them can
    die; a single truncated job follows the ordinary error path. The fallback's quality strike for the call was already
    counted by ``failover.record_failure`` inside :func:`claude_call` (three in a row still pause it, §10.4).
    """
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
    if status == "error" and failover.error_prefix(result.error) == "truncated" and n >= 2:
        half = math.ceil(n / 2)
        queue.requeue_group(conn, ids, half, consume_attempt=False, error=f"truncated answer; bisecting to groups of {half}", now=now)
        ctx.log.warning("%s: truncated answer on %d jobs → group_size %d", kind_label, n, half, extra={"job_type": kind_label, "event": "ai_bisect"})
        return "bisect"
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
    provider = getattr(result, "provider", None) or CLAUDE
    if status == "overloaded":
        # the streak (and the 15-minute pause after six in a row) was recorded by failover.record_failure in claude_call
        attempts = max([j.attempts for j in jobs] + [1])
        until = to_iso(parse_iso(now) + OVERLOAD_DEFER_STEP * attempts)
        paused = budget.provider_paused_until(conn, provider, now)
        if paused is not None:
            until = max(until, paused)
        with db.maybe_tx(conn):
            queue.defer(conn, ids, until, now=now)
        ctx.log.warning("%s: %s overloaded; %d job(s) deferred until %s", kind_label, provider, n, until, extra={"job_type": kind_label, "event": "ai_overloaded"})
        return "defer"
    if status in ("auth", "spawn_error"):
        # the provider's pause, kv.claude.available and the claude_auth event were written by failover.record_failure;
        # the jobs wait for whichever provider frees first (the other one may already be serving new groups)
        pause_until = budget.provider_paused_until(conn, provider, now) or to_iso(parse_iso(now) + AUTH_PAUSE)
        other = FALLBACK if provider == CLAUDE else CLAUDE
        other_pause = budget.provider_paused_until(conn, other, now)
        if other_pause is not None:
            pause_until = min(pause_until, other_pause) if other_pause > now else pause_until
        with db.maybe_tx(conn):
            queue.defer(conn, ids, pause_until, now=now)
        ctx.log.error("%s: %s %s — jobs deferred until %s", kind_label, provider, status, pause_until, extra={"job_type": kind_label, "event": f"claude_{status}" if provider == CLAUDE else f"fallback_{status}"})
        return "pause"
    for j in jobs:  # unknown status: treat as an ordinary error
        fail_job(conn, j, f"{status}: {err}", now=now, on_dead=on_dead)
    return "fail"


__all__ = [
    "AUTH_BANNER_ZH",
    "ascii_ratio",
    "claude_call",
    "run_provider",
    "clean_text",
    "fail_job",
    "handle_failure",
    "has_cjk",
    "item_index",
    "payload_int",
    "record_applied",
    "record_invalid_output",
    "record_success",
    "system_event",
    "validate_target",
]
