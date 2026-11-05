"""Provider failover state machine (docs/AI_FALLBACK_MODEL.md §4.1–§4.3; CLAUDE_INTEGRATION §10) — the single writer of
the per-provider pauses, the failure streaks and the sticky ``kv.ai.active_provider``.

Two providers exist: ``claude`` (``runner.run_claude``, the ``claude -p`` CLI) and ``fallback`` (the OpenAI-format HTTP
adapter ``ai/providers/openai_http.py``). ``common.claude_call`` asks :func:`choose` which one takes a group, reports the
outcome through :func:`record_success` / :func:`record_failure` and reruns the group on the provider the returned
:class:`Decision` names; ``ClaudeWorker.housekeeping`` calls :func:`maybe_probe` while the fallback is active (the probe
is the way back); the admin pause/resume endpoints call :func:`set_manual_pause` / :func:`clear_pauses`; the user-facing
gates ask :func:`availability` ("any provider can take this kind now").

Failure → action (§4.2, MVP subset; ``result.error`` prefixes are the adapter ↔ failover contract of the spec §0):

* **hard** — status ``auth`` / ``spawn_error`` or an error starting with ``balance:`` / ``quota:`` / ``not_found:`` →
  the failing provider is paused (``balance:`` 24 h; ``quota:`` until its ``retry_at=`` or the cooldown; otherwise
  ``WD_AI_FAILOVER_COOLDOWN_MIN``), ``<provider>.available='0'`` on ``spawn_error`` / ``not_found:``; the ``claude``
  branch writes exactly what ``common.handle_failure`` wrote before (``claude.paused_until``, ``claude.available``, one
  ``claude_auth`` event per 30 minutes with ``banner_zh`` — the banner names the fix for the reason: login, top-up,
  the binary; :func:`banner_for`).
* **soft** — ``overloaded`` (its own streak, ``WD_AI_FAILOVER_OVERLOADED_AFTER``; a ``network:`` error uses the network
  streak and ``_NETWORK_AFTER``) and ``timeout`` (``_TIMEOUT_AFTER``); six ``overloaded`` in a row still pause the
  provider 15 minutes (``claude_overloaded`` / ``ai_fallback_paused``) and reset that streak, as today.
* **never** — ``budget``, ``invalid_output``, ``error`` (``content_filter:`` / ``truncated:`` / ``schema:`` …): the
  handler's backoff → bisect → dead path is untouched and the group is never rerun on the other provider. On the
  fallback an unusable answer (:func:`is_quality_failure`: ``invalid_output`` — the handler's post-validation rejecting
  every item of an HTTP-ok answer, reported through ``common.record_invalid_output``; the adapter never emits that
  status, its post-repair schema miss is ``error`` ``schema:`` — or an ``error`` with one of :data:`QUALITY_PREFIXES`)
  counts the quality streak ``ai.fallback.streak.invalid``: the third in a row pauses the fallback for the cooldown
  (``ai_fallback_quality`` event, ``fallback_quality`` notification, ``ai.fallback.pause_reason='quality'``), so a
  silently degraded free model cannot burn every content job to ``dead``. That streak ends only when a handler applies
  a fallback answer (:func:`record_quality_success`), the admin resumes or a new failover episode starts (the claude →
  fallback flip zeroes a stale count) — an HTTP-ok call does not reset it, nor does it lift a quality pause: a fallback
  probe, an applied fallback group or the admin's resume does (an ordinary pause is lifted by any fallback success).

In mode ``auto`` a hard trigger on ``claude`` (the CLI as such is down) flips ``ai.active_provider`` claude → fallback
whenever the fallback is usable, a soft threshold only when the failing kind may rerun there (``WD_AI_FALLBACK_KINDS``:
flipping on a content streak would fail back on the next content success and flap); the flip is a compare-and-swap
(one flip and one ``ai_failover`` event however many threads fail at once), schedules the first fail-back probe and
names ``fallback`` as the provider to rerun the group on; a trigger on the fallback names ``claude`` when it is not
paused. A success on a provider (an ordinary call or a probe, in every mode) is proof it works again: its streaks end,
its ``'0'`` availability mark and its automatic pause are lifted (the fallback's quality pause only by a probe, an
applied group or the resume) and the jobs parked at that pause instant run now (:func:`_release_parked`); a successful
``claude`` call while the fallback is active additionally flips back (``ai_failback``). The other modes only pause.
Switch, fail-back and "both providers down" (a provider just paused
while the other is paused or marked unavailable) are pushed to the admins' webhooks at most once per kind per hour
(:func:`notify`, best effort, and never from inside the caller's open transaction — the outcome hooks are called
outside one). The admin's resume (:func:`clear_pauses`) lifts every pause and every ``'0'`` mark at once.

Claim size (§4.2 "切换期间：例句批大小 5"): while the fallback takes ``content`` a group holds at most
``min(WD_AI_BATCH_SIZE, WD_AI_FALLBACK_BATCH_SIZE)`` words (:func:`group_cap`) — ``worker.process_next`` claims through
:func:`claim_limit`, and ``common.claude_call`` regroups a larger group (claimed for the CLI, then rerouted) before it
runs there. A fail-back — a successful claude call or probe, or the admin's resume while the fallback was active —
requeues the content / lookup jobs that died since ``ai.failover.since`` (:func:`_requeue_outage_dead` →
``worker.requeue_dead_jobs(died_after=…, group_size=None)``: the admin requeue-dead semantics, not the nightly's once-only
``requeued_at`` stamp; the revived jobs carry no ``group_size`` mark and batch like fresh claims, a revived content job's
``failed`` word goes back to ``queued``; ``requeued_dead`` in the ``ai_failback`` detail; §4.5 死词) and ends the episode
(:data:`FAILOVER_KEYS` deleted with the probe schedule). In mode ``auto`` lifting a claude pause that no flip accompanied
(the fallback bridged it — claude failed while the fallback was paused or marked unavailable — or nothing did) requeues
the jobs that died since the pause started (the pause row's ``updated_at``). A start in a non-``auto`` mode ends a stale
episode without a requeue or an event (:func:`reconcile_mode`, log event ``ai_failover_reconciled``).

State keys (§4.3): ``ai.active_provider``, ``ai.paused_until`` (admin manual pause, every provider), ``claude.paused_until``
(existing key: the CLI's automatic pause), ``ai.fallback.paused_until`` and ``ai.fallback.pause_reason`` (``quality`` while
the quality streak wrote that pause, absent otherwise), ``claude.available`` / ``ai.fallback.available``,
``ai.fallback.model_seen``, ``ai.failover.{since,reason,trigger_call_id,next_probe_at,probe_failures,last_probe_at}``, the streaks
``claude.overloaded_streak`` (existing name), ``ai.claude.streak.{timeout,network}``,
``ai.fallback.streak.{overloaded,timeout,network}``, the quality streak ``ai.fallback.streak.invalid`` (not in
``STREAK_KEYS``: a success resets it only through :func:`record_quality_success`) and ``ai.notify.<kind>.last_at``.

This module must not import ``wd.ai.common`` (``common`` imports it); the banner constant lives here for that reason.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Callable, Mapping, Sequence

from .. import db
from ..clock import parse_iso, to_iso, zone
from ..config import Settings
from ..interfaces import ClaudeResult
from . import budget

if TYPE_CHECKING:  # the webhook client type only; httpx is imported lazily with wd.delivery.webhook
    import httpx

log = logging.getLogger("wd.ai.failover")

CLAUDE = "claude"
FALLBACK = "fallback"
PROVIDERS: tuple[str, ...] = (CLAUDE, FALLBACK)
MODES: tuple[str, ...] = ("claude_cli", "openai_http", "auto")

# ---- kv keys (AI_FALLBACK_MODEL §4.3)
KV_ACTIVE = "ai.active_provider"
KV_GLOBAL_PAUSE = budget.KV_GLOBAL_PAUSE  # ai.paused_until
KV_CLAUDE_PAUSE = budget.KV_CLAUDE_PAUSE  # claude.paused_until
KV_FALLBACK_PAUSE = budget.KV_FALLBACK_PAUSE  # ai.fallback.paused_until
KV_CLAUDE_AVAILABLE = "claude.available"
KV_FALLBACK_AVAILABLE = "ai.fallback.available"
KV_FALLBACK_MODEL_SEEN = "ai.fallback.model_seen"
KV_FAILOVER_SINCE = "ai.failover.since"
KV_FAILOVER_REASON = "ai.failover.reason"
KV_FAILOVER_TRIGGER = "ai.failover.trigger_call_id"
KV_NEXT_PROBE = "ai.failover.next_probe_at"
KV_PROBE_FAILURES = "ai.failover.probe_failures"
KV_LAST_PROBE = "ai.failover.last_probe_at"  # when the last fail-back probe started (the forced start-up probe runs once per restart)
PROBE_KEYS: tuple[str, ...] = (KV_NEXT_PROBE, KV_PROBE_FAILURES, KV_LAST_PROBE)  # the schedule a fail-back / resume clears
FAILOVER_KEYS: tuple[str, ...] = (KV_FAILOVER_SINCE, KV_FAILOVER_REASON, KV_FAILOVER_TRIGGER)  # the episode bookkeeping a fail-back / resume / reconcile ends
KV_CLAUDE_ENABLED = "claude.enabled"
AVAILABLE_KEYS: dict[str, str] = {CLAUDE: KV_CLAUDE_AVAILABLE, FALLBACK: KV_FALLBACK_AVAILABLE}
OVERLOAD_STREAK_KEY = "claude.overloaded_streak"  # the legacy name: the worker tests read it; written only here
STREAK_KEYS: dict[tuple[str, str], str] = {
    (CLAUDE, "overloaded"): OVERLOAD_STREAK_KEY,
    (CLAUDE, "timeout"): "ai.claude.streak.timeout",
    (CLAUDE, "network"): "ai.claude.streak.network",
    (FALLBACK, "overloaded"): "ai.fallback.streak.overloaded",
    (FALLBACK, "timeout"): "ai.fallback.streak.timeout",
    (FALLBACK, "network"): "ai.fallback.streak.network",
}
# NOT in STREAK_KEYS: record_success's reset must leave it alone — an HTTP-ok answer may still be rejected whole by the handler
KV_FALLBACK_QUALITY_STREAK = "ai.fallback.streak.invalid"
# "quality" while ai.fallback.paused_until was written by the quality streak; absent for a hard / overload pause. An ordinary
# HTTP-ok fallback call leaves a quality pause alone (its answer may still be rejected whole — with WD_AI_CONCURRENCY > 1 an
# in-flight sibling would otherwise undo the pause seconds after the third strike); a probe, an applied group or the resume lifts it
KV_FALLBACK_PAUSE_REASON = "ai.fallback.pause_reason"

# ---- system_events kinds
EVENT_FAILOVER = "ai_failover"
EVENT_FAILBACK = "ai_failback"
EVENT_FALLBACK_PAUSED = "ai_fallback_paused"
EVENT_FALLBACK_QUALITY = "ai_fallback_quality"  # QUALITY_PAUSE_AFTER unusable fallback answers in a row → quality pause
EVENT_CLAUDE_AUTH = "claude_auth"  # existing kind, existing detail shape (incl. banner_zh)
EVENT_CLAUDE_OVERLOADED = "claude_overloaded"  # existing kind: the 6-streak pause

# ---- numbers (today's values kept: common.OVERLOAD_PAUSE_AFTER / OVERLOAD_PAUSE / the 30-minute claude_auth window)
OVERLOAD_PAUSE_AFTER = 6
OVERLOAD_PAUSE = timedelta(minutes=15)
AUTH_EVENT_WINDOW = timedelta(minutes=30)
BALANCE_PAUSE = timedelta(hours=24)
PROBE_BACKOFF_AFTER = 12  # consecutive failed probes after which the probe interval doubles
PROBE_FORCE_GRACE = timedelta(minutes=5)  # a forced (start-up) probe is skipped this long after any probe started
NOTIFY_WINDOW = timedelta(hours=1)
DISABLED_WAIT = budget.DISABLED_WAIT
QUALITY_PAUSE_AFTER = 3  # consecutive unusable fallback answers that pause it for the cooldown (AI_FALLBACK_MODEL §4.2)
FAILBACK_REQUEUE_TYPES: tuple[str, ...] = ("generate_content", "lookup_word")  # the dead jobs of an outage requeued on fail-back (§4.5)
FAILBACK_REQUEUE_LIMIT = 200
HARD_STATUSES: tuple[str, ...] = ("auth", "spawn_error")
HARD_PREFIXES: tuple[str, ...] = ("balance", "quota", "not_found")
QUALITY_PREFIXES: tuple[str, ...] = ("content_filter", "truncated", "invalid_json", "schema")  # `error` prefixes that are a quality miss
KNOWN_PREFIXES: tuple[str, ...] = (*HARD_PREFIXES, "network", "content_filter", "truncated", "invalid_json", "schema")
PREFIX_RE = re.compile(r"^\s*([a-z_]+):")
RETRY_AT_RE = re.compile(r"retry_at=(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)")
AUTH_BANNER_ZH = "Claude CLI 未登录，请以 sqin 身份运行 claude 完成登录"
BALANCE_BANNER_ZH = "Claude 账户余额不足或配额用尽，请充值后运行 wd claude-check"
QUOTA_BANNER_ZH = "Claude 用量已达当前配额上限，配额重置后运行 wd claude-check 确认恢复"
SPAWN_BANNER_ZH = "Claude CLI 无法启动，请检查 WD_CLAUDE_BIN 指向的可执行文件后运行 wd claude-check"
BANNERS_ZH: dict[str, str] = {
    "auth": AUTH_BANNER_ZH,
    "balance": BALANCE_BANNER_ZH,
    "quota": QUOTA_BANNER_ZH,
    "spawn_error": SPAWN_BANNER_ZH,
    "not_found": SPAWN_BANNER_ZH,
}
ADMIN_WEBHOOKS_SQL = (
    "SELECT s.webhook_url AS webhook_url, s.webhook_format AS webhook_format FROM users u JOIN user_settings s ON s.user_id = u.id "
    "WHERE u.role = 'admin' AND u.is_active = 1 AND s.webhook_enabled = 1 AND s.webhook_url IS NOT NULL AND s.webhook_url != '' ORDER BY u.id"
)

#: test hook: a factory returning the ``httpx.Client`` :func:`notify` posts with (None = ``wd.delivery.webhook``'s own client)
WEBHOOK_CLIENT_FACTORY: Callable[[], "httpx.Client"] | None = None


@dataclass
class Availability:
    """The answer of :func:`availability`: can some provider take ``kind`` right now, and why not otherwise."""

    ok: bool  # some provider can take this kind now
    provider: str | None  # which one `choose` would return
    resumes_at: str | None  # when ok is False: the earliest instant something may run (ISO)
    active: str  # kv ai.active_provider
    claude_paused_until: str | None
    fallback_paused_until: str | None
    global_paused_until: str | None
    reason: str  # "ok" | "disabled" | "paused" | "claude_paused" | "claude_paused_no_fallback" | "both_paused" | "fallback_paused" | "fallback_unavailable" | "unavailable"


@dataclass
class Decision:
    """What :func:`record_failure` did and what the caller should do next."""

    action: str  # "none" | "pause" | "switch"
    paused_until: str | None  # pause applied to `provider` (if any)
    retry_provider: str | None  # provider on which claude_call should rerun the same group immediately (or None)
    event: str | None  # the ai_failover event when this call flipped the active provider


# ------------------------------------------------------------------------------------------ state
def mode(cfg: Settings) -> str:
    """``WD_AI_PROVIDER``: ``claude_cli`` (today), ``openai_http`` (fallback only) or ``auto`` (claude + automatic failover)."""
    m = str(getattr(cfg, "ai_provider", "claude_cli") or "claude_cli")
    return m if m in MODES else "claude_cli"


def active_provider(conn: sqlite3.Connection) -> str:
    """``kv.ai.active_provider`` (absent or unknown = ``claude``)."""
    value = db.kv_get(conn, KV_ACTIVE)
    return value if value in PROVIDERS else CLAUDE


def set_fallback_paused_until(conn: sqlite3.Connection, until: str | None, *, now: str | None = None) -> None:
    """Set (or clear with None) ``ai.fallback.paused_until`` — the sibling of ``budget.set_paused_until`` for the claude key."""
    budget.set_paused_until(conn, until, now=now, provider=FALLBACK)


def fallback_eligible(conn: sqlite3.Connection, cfg: Settings, *, kind: str, priority: int, now: str) -> tuple[bool, str | None]:
    """``(True, None)`` when the fallback may take ``kind`` now, else ``(False, resumes_at)`` (None when nothing is scheduled).

    Eligible = configured (``Settings.fallback_configured``), the kind is routable (``WD_AI_FALLBACK_KINDS``; a probe
    always; a prewarm group — priority ≥ 90 — only with ``WD_AI_FALLBACK_PREWARM``), ``ai.fallback.available`` is not
    ``'0'`` (set by a ``spawn_error`` / ``not_found:`` until a fallback probe or call succeeds) and no fallback pause.
    """
    if not bool(getattr(cfg, "fallback_configured", False)):
        return False, None
    if kind != "probe":
        if kind not in tuple(getattr(cfg, "ai_fallback_kinds", ()) or ()):
            return False, None
        if int(priority) >= budget.PREWARM_PRIORITY and not bool(getattr(cfg, "ai_fallback_prewarm", False)):
            return False, None
    paused = budget.provider_paused_until(conn, FALLBACK, now)
    if db.kv_get(conn, KV_FALLBACK_AVAILABLE) == "0":
        return False, paused
    if paused is not None:
        return False, paused
    return True, None


def choose(conn: sqlite3.Connection, cfg: Settings, *, kind: str, priority: int, now: str) -> tuple[str | None, str | None]:
    """``(provider, None)`` for the provider that takes ``kind`` now, or ``(None, resumes_at)`` (AI_FALLBACK_MODEL §4.1 step 1).

    Kill switch off → ``(None, now + 30 min)``; the admin's global pause → ``(None, until)``. Then by mode: ``claude_cli``
    → claude unless paused; ``openai_http`` → the fallback when eligible; ``auto`` → the sticky active provider first
    (claude when not paused, else the fallback when eligible; the fallback when eligible, else claude when not paused),
    otherwise the earliest instant one of them may run again — in both ``auto`` branches (CLAUDE_INTEGRATION §10.5
    "the earlier of the two pauses"): a group that arrives during the fallback's 15-minute overload pause must not wait
    for a 24-hour ``balance:`` pause of the CLI. The fallback contributes no instant when it is not configured, the kind
    is not routable, a prewarm group lacks ``WD_AI_FALLBACK_PREWARM`` or it is marked unavailable without a pause: those
    groups keep waiting for the claude pause.
    """
    if not budget.ai_enabled(conn, cfg):
        return None, to_iso(parse_iso(now) + DISABLED_WAIT)
    global_pause = budget.global_paused_until(conn, now)
    if global_pause is not None:
        return None, global_pause
    m = mode(cfg)
    claude_pause = budget.provider_paused_until(conn, CLAUDE, now)
    if m == "claude_cli":
        return (CLAUDE, None) if claude_pause is None else (None, claude_pause)
    eligible, resumes = fallback_eligible(conn, cfg, kind=kind, priority=priority, now=now)
    if m == "openai_http":
        return (FALLBACK, None) if eligible else (None, resumes)
    if active_provider(conn) == CLAUDE:
        if claude_pause is None:
            return CLAUDE, None
        if eligible:
            return FALLBACK, None
        return None, min(v for v in (claude_pause, resumes) if v)  # claude_pause is set here: never empty
    if eligible:
        return FALLBACK, None
    if claude_pause is None:
        return CLAUDE, None
    candidates = [v for v in (claude_pause, resumes) if v]
    return None, (min(candidates) if candidates else None)


def availability(conn: sqlite3.Connection, cfg: Settings, *, kind: str, now: str, priority: int = 20) -> Availability:
    """The "any provider" view the user-facing gates use (``bank.ai_paused_until``, the content request route, prefetch)."""
    active = active_provider(conn)
    claude_pause = budget.provider_paused_until(conn, CLAUDE, now)
    fallback_pause = budget.provider_paused_until(conn, FALLBACK, now)
    global_pause = budget.global_paused_until(conn, now)
    provider, resumes = choose(conn, cfg, kind=kind, priority=priority, now=now)
    if provider is not None:
        reason = "ok"
    elif not budget.ai_enabled(conn, cfg):
        reason = "disabled"
    elif global_pause is not None:
        reason = "paused"
    else:
        m = mode(cfg)
        if m == "claude_cli":
            reason = "claude_paused"
        elif m == "openai_http":
            reason = "fallback_paused" if fallback_pause is not None else "fallback_unavailable"
        elif claude_pause is not None and fallback_pause is not None:
            reason = "both_paused"
        elif claude_pause is not None:
            reason = "claude_paused_no_fallback"
        else:
            reason = "unavailable"
    return Availability(
        ok=provider is not None,
        provider=provider,
        resumes_at=None if provider is not None else resumes,
        active=active,
        claude_paused_until=claude_pause,
        fallback_paused_until=fallback_pause,
        global_paused_until=global_pause,
        reason=reason,
    )


# ------------------------------------------------------------------------------------------ claims
def group_cap(cfg: Settings, kind: str, provider: str) -> int | None:
    """Largest group ``provider`` may take for ``kind``: the fallback's content batch (``min(WD_AI_BATCH_SIZE,
    WD_AI_FALLBACK_BATCH_SIZE)``, ≥ 1 — AI_FALLBACK_MODEL §4.2 "切换期间：例句批大小 5") for ``content``; None (no extra cap)
    for everything else and for claude. ``worker.process_next`` claims that many (:func:`claim_limit`) and
    ``common.claude_call`` regroups a larger group before it runs on the fallback."""
    if provider != FALLBACK or kind != "content":
        return None
    batch = int(getattr(cfg, "ai_batch_size", 10) or 10)
    fallback_batch = int(getattr(cfg, "ai_fallback_batch_size", 5) or 5)
    return max(1, min(batch, fallback_batch))


def claim_limit(conn: sqlite3.Connection, cfg: Settings, job_type: str, *, now: str) -> int:
    """Jobs per claim for ``job_type`` right now — what ``worker.process_next`` hands ``queue.claim_batch`` in place of a
    bare ``queue.limit_for``: ``queue.limit_for`` unless ``job_type == 'generate_content'`` and the provider that would
    take the head group now (:func:`choose` for the priority of the head queued content job, 20 when none) is the
    fallback → :func:`group_cap`. ``claim_batch``'s ``payload.group_size`` rule still applies on top (the smaller wins).
    Never raises for a kv / config reason; only sqlite errors escape."""
    from ..jobs.queue import limit_for  # lazy: keep failover free of the jobs package at import time

    limit = limit_for(job_type, cfg)
    if job_type != "generate_content":
        return limit
    row = conn.execute(
        "SELECT priority FROM jobs WHERE status='queued' AND type='generate_content' AND run_after<=? ORDER BY priority, run_after, id LIMIT 1",
        (now,),
    ).fetchone()
    priority = int(row[0]) if row is not None else 20
    provider, _resumes = choose(conn, cfg, kind="content", priority=priority, now=now)
    if provider != FALLBACK:
        return limit
    cap = group_cap(cfg, "content", FALLBACK)
    return limit if cap is None else min(limit, cap)


# --------------------------------------------------------------------------------- classification
def error_prefix(error: str | None) -> str | None:
    """The spec §0 prefix of a non-ok ``ClaudeResult.error`` (``balance`` / ``quota`` / ``network`` / ``not_found`` / …), or None."""
    if not error:
        return None
    m = PREFIX_RE.match(error)
    if m is None:
        return None
    word = m.group(1)
    return word if word in KNOWN_PREFIXES else None


def classify(result: ClaudeResult) -> tuple[str, str | None]:
    """``("hard" | "soft" | "never", reason)`` for a call outcome (§4.2); ``reason`` is the prefix / status (hard) or
    the streak class ``overloaded`` / ``network`` / ``timeout`` (soft)."""
    status = result.status
    if result.ok or status == "success":
        return "never", None
    prefix = error_prefix(result.error)
    if prefix in HARD_PREFIXES:
        return "hard", prefix
    if status in HARD_STATUSES:
        return "hard", status
    if status == "overloaded":
        return "soft", "network" if prefix == "network" else "overloaded"
    if status == "timeout":
        return "soft", "timeout"
    return "never", None


def is_quality_failure(result: ClaudeResult) -> bool:
    """An answer that arrived but was unusable (§4.2 row ``invalid_output`` / 内容过滤): status ``invalid_output`` — the
    handler's post-validation rejecting every item of an ok answer (``common.record_invalid_output``; only the content
    and lookup handlers produce that status, the adapters never do — the HTTP adapter reports its post-repair schema
    miss as status ``error`` with the ``schema:`` prefix, CLAUDE_INTEGRATION §10.3) — or status ``error`` with one of
    :data:`QUALITY_PREFIXES`. Never a switch trigger (:func:`classify` says ``never``); on the fallback it feeds the
    quality streak (:func:`record_failure`)."""
    if result.ok:
        return False
    if result.status == "invalid_output":
        return True
    return result.status == "error" and error_prefix(result.error) in QUALITY_PREFIXES


def retry_at_from_error(error: str | None, now: str) -> str | None:
    """The ``retry_at=<ISO>`` instant a ``quota:`` error carries (Zhipu 1308 ``next_flush_time``) when it lies in the future."""
    if not error:
        return None
    m = RETRY_AT_RE.search(error)
    if m is None:
        return None
    try:
        value = to_iso(parse_iso(m.group(1)))
    except ValueError:
        return None
    return value if value > now else None


def _soft_threshold(cfg: Settings, klass: str) -> int:
    if klass == "timeout":
        return int(getattr(cfg, "ai_failover_timeout_after", 2) or 2)
    if klass == "network":
        return int(getattr(cfg, "ai_failover_network_after", 2) or 2)
    return int(getattr(cfg, "ai_failover_overloaded_after", 3) or 3)


def _cooldown(cfg: Settings) -> timedelta:
    return timedelta(minutes=int(getattr(cfg, "ai_failover_cooldown_min", 30) or 30))


def _probe_every(cfg: Settings) -> timedelta:
    return timedelta(minutes=int(getattr(cfg, "ai_failover_probe_every_min", 30) or 30))


def _hard_pause_until(cfg: Settings, reason: str, error: str | None, now: str) -> str:
    """§4.2 cooldowns: ``balance`` 24 h (someone has to top up), ``quota`` its window reset, everything else the cooldown."""
    if reason == "balance":
        return to_iso(parse_iso(now) + BALANCE_PAUSE)
    if reason == "quota":
        return retry_at_from_error(error, now) or to_iso(parse_iso(now) + _cooldown(cfg))
    return to_iso(parse_iso(now) + _cooldown(cfg))


def banner_for(reason: str) -> str:
    """The ``banner_zh`` of a ``claude_auth`` event by hard reason: ``auth`` → log in, ``balance`` → top up, ``quota`` → wait
    for the window, ``spawn_error`` / ``not_found`` → the binary (the admin page and ``wd diag`` show the latest one)."""
    return BANNERS_ZH.get(reason, AUTH_BANNER_ZH)


def _int(value: str | None, default: int = 0) -> int:
    """A kv counter as an int; a non-numeric value (never written here, but a hand edit happens) counts as ``default``
    instead of a ValueError escaping into the worker."""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _within(since: str | None, window: timedelta, now: str) -> bool:
    """True when ``since`` (ISO; garbage counts as absent) lies less than ``window`` before ``now``."""
    if not since:
        return False
    try:
        return parse_iso(now) - parse_iso(since) < window
    except ValueError:
        return False


def _strip_prefix(error: str) -> str:
    """``balance: API Error: 402 …`` → ``API Error: 402 …`` for notification bodies that already name the reason."""
    if error_prefix(error) is None:
        return error
    return error.split(":", 1)[1].strip()


# ------------------------------------------------------------------------------------- kv helpers
def _insert_event(conn: sqlite3.Connection, kind: str, detail: Mapping[str, Any], *, now: str) -> None:
    with db.maybe_tx(conn):
        conn.execute(
            "INSERT INTO system_events(kind, detail_json, created_at) VALUES (?, ?, ?)",
            (kind, json.dumps(dict(detail), ensure_ascii=False, sort_keys=True), now),
        )


def _cas_active(conn: sqlite3.Connection, expected: str, new: str, *, now: str) -> bool:
    """Compare-and-swap ``kv.ai.active_provider`` ``expected`` → ``new`` inside ``BEGIN IMMEDIATE``; True when THIS call
    flipped it (an absent or unknown value counts as ``claude``), False when another thread already did."""
    with db.maybe_tx(conn):
        if expected == CLAUDE:
            cur = conn.execute(
                "UPDATE kv SET value = ?, updated_at = ? WHERE key = ? AND (value = ? OR value NOT IN ('claude', 'fallback'))",
                (new, now, KV_ACTIVE, expected),
            )
            if cur.rowcount == 1:
                return True
            cur = conn.execute("INSERT OR IGNORE INTO kv(key, value, updated_at) VALUES (?, ?, ?)", (KV_ACTIVE, new, now))
            return cur.rowcount == 1
        cur = conn.execute("UPDATE kv SET value = ?, updated_at = ? WHERE key = ? AND value = ?", (new, now, KV_ACTIVE, expected))
        return cur.rowcount == 1


def _reset_streaks(conn: sqlite3.Connection, provider: str, *, now: str) -> None:
    """A success ends every streak of ``provider`` (written as ``'0'`` only where a streak was counting, like today)."""
    with db.maybe_tx(conn):
        for (p, _klass), key in STREAK_KEYS.items():
            if p == provider and db.kv_get(conn, key) not in (None, "0"):
                db.kv_set(conn, key, "0", now=now)


def _reset_quality_streak(conn: sqlite3.Connection, *, now: str) -> None:
    """End the fallback's quality streak — written as ``'0'`` only when it was counting, like :func:`_reset_streaks`
    (the read happens first so an applied group does not take the write lock for nothing)."""
    if db.kv_get(conn, KV_FALLBACK_QUALITY_STREAK) in (None, "0"):
        return
    with db.maybe_tx(conn):
        db.kv_set(conn, KV_FALLBACK_QUALITY_STREAK, "0", now=now)


def _requeue_outage_dead(conn: sqlite3.Connection, since: str | None, *, now: str) -> int:
    """Fail-back (§4.5 死词): the content / lookup jobs that died at or after ``since`` (the outage start — ``ai.failover.since``
    on a flip, the claude pause start when the fallback bridged a pause without one) go back to ``queued`` with the admin
    requeue-dead semantics (``worker.requeue_dead_jobs``: ``attempts=0``, ``run_after=now``; a dead row whose dedupe key is
    held by a live job is not a candidate and takes no slot; a revived content job's ``failed`` word goes back to
    ``queued``), at most :data:`FAILBACK_REQUEUE_LIMIT` rows — reaching the limit is logged as a warning, the rest waits
    for the nightly. Unlike the nightly and the admin button the revived jobs carry NO ``group_size`` mark
    (``group_size=None`` removes a bisection mark too): they batch like fresh claims, ≤ 10 per CLI call and ≤ 5 on the
    fallback, so a pile of casualties cannot eat the shared hourly call cap one word per call; a poisoned word among
    them meets the ordinary §6.3 ladder. The nightly's once-only ``payload.requeued_at`` stamp is neither set nor
    honoured on purpose: an outage casualty keeps its single nightly retry. Safe inside the caller's transaction:
    ``requeue_dead_jobs`` joins it per row and swallows the dedupe collision per statement. 0 when ``since`` is unknown."""
    if not since:
        return 0
    from ..jobs.worker import requeue_dead_jobs  # lazy: keep failover free of the jobs package at import time

    requeued = requeue_dead_jobs(conn, now=now, types=FAILBACK_REQUEUE_TYPES, died_after=since, limit=FAILBACK_REQUEUE_LIMIT, group_size=None)
    log.info("fail-back: %d dead job(s) of the outage since %s requeued", requeued, since, extra={"event": "ai_failback_requeue", "provider": CLAUDE})
    if requeued == FAILBACK_REQUEUE_LIMIT:
        log.warning(
            "fail-back requeue stopped at its limit of %d rows; the remaining dead jobs of the outage since %s wait for the nightly requeue",
            FAILBACK_REQUEUE_LIMIT,
            since,
            extra={"event": "ai_failback_requeue_limit", "provider": CLAUDE},
        )
    return requeued


def _release_parked(conn: sqlite3.Connection, horizons: Sequence[str | None], *, now: str) -> int:
    """Queued AI jobs parked at a pause instant that was just lifted run now; returns the rows released.

    ``common.claude_call`` defers a refused group to :func:`choose`'s ``resumes_at`` and ``common.handle_failure`` defers
    an ``auth`` / ``spawn_error`` group to the provider's pause end — the pause value verbatim — so an exact-instant match
    on ``run_after`` finds exactly the jobs the pause parked (up to 24 h ahead after a ``balance:`` pause). It is never a
    blanket ``run_after > now`` reset: a backoff, an overload step or a budget deferral (00:05 next day) keeps its own
    schedule, which an automatic fail-back every few minutes would otherwise flap. Only ``queued`` jobs of the Claude
    job types move; instants already in the past need no help (their jobs are runnable), the rest become ``now``.
    """
    from ..jobs.queue import CLAUDE_TYPES  # lazy: keep failover free of the jobs package at import time

    instants = sorted({h for h in horizons if h and h > now})
    if not instants:
        return 0
    with db.maybe_tx(conn):
        cur = conn.execute(
            "UPDATE jobs SET run_after = ?, updated_at = ? WHERE status = 'queued' "
            f"AND type IN ({','.join('?' * len(CLAUDE_TYPES))}) AND run_after IN ({','.join('?' * len(instants))})",
            (now, now, *CLAUDE_TYPES, *instants),
        )
        released = int(cur.rowcount)
    if released:
        log.info("%d parked AI job(s) released from %s", released, ", ".join(instants), extra={"event": "ai_parked_released"})
    return released


# ---------------------------------------------------------------------------------------- outcomes
def record_failure(
    conn: sqlite3.Connection,
    cfg: Settings,
    *,
    provider: str,
    result: ClaudeResult,
    kind: str,
    now: str,
    priority: int,
    attempts: int = 1,
) -> Decision:
    """Apply the §4.2 table to one failed call of ``kind`` on ``provider`` and say what the caller should do next.

    Pauses, streaks and events are written for ``provider`` inside one transaction (this module is the single writer).
    In mode ``auto`` a trigger on ``claude`` flips ``ai.active_provider`` to the fallback (compare-and-swap; the flip, the
    ``ai.failover.*`` keys, the ``ai_failover`` event and the first probe time are written once however many threads fail
    concurrently; the flip also zeroes a stale quality streak so the new episode counts from zero): a hard trigger
    whenever the fallback is usable at all (an outage noticed on a content group must still move lookups and
    consolidates over, schedule the probe and notify), a soft threshold only when ``kind`` itself may rerun there. ``retry_provider`` names the fallback whenever it may take ``kind`` — also when another thread flipped
    first: the group still reruns there. A trigger on the fallback names ``claude`` when it is not paused (no state flip:
    a successful claude call flips back through :func:`record_success`). The other modes only pause. When the provider
    that just got paused was the last one standing (the other is paused or marked unavailable) the admins get the
    "both providers down" notification (§4.5).

    ``priority`` is the group's job priority (``min(j.priority for j in jobs)``) and is required: a prewarm group (≥ 90)
    may rerun on the fallback only with ``WD_AI_FALLBACK_PREWARM``, and an omitted value would silently widen that rule.
    A ``never`` result changes nothing — except an unusable fallback answer (:func:`is_quality_failure`), which counts
    the quality streak and pauses the fallback after :data:`QUALITY_PAUSE_AFTER` in a row (:func:`_record_quality_failure`;
    never on claude); ``retry_provider`` is None in both cases. A hard / overload pause written here for the fallback
    drops ``ai.fallback.pause_reason``: it is an ordinary pause again, lifted by any fallback success.
    Precondition: no open transaction on ``conn`` (the notification is skipped inside one, see :func:`notify`).
    """
    provider = provider if provider in PROVIDERS else CLAUDE
    klass, reason = classify(result)
    if klass == "never" or reason is None:
        if provider == FALLBACK and is_quality_failure(result):
            return _record_quality_failure(conn, cfg, kind=kind, result=result, now=now)
        return Decision("none", None, None, None)
    m = mode(cfg)
    error_text = str(result.error or result.status or "")[:300]
    paused_until: str | None = None
    event: str | None = None
    retry: str | None = None
    action = "none"
    triggered = False
    notice: tuple[str, dict[str, Any]] | None = None
    with db.maybe_tx(conn):
        if klass == "hard":
            paused_until = _hard_pause_until(cfg, reason, result.error, now)
            budget.set_paused_until(conn, paused_until, now=now, provider=provider)
            if result.status == "spawn_error" or reason == "not_found":
                db.kv_set(conn, AVAILABLE_KEYS[provider], "0", now=now)
            if provider == CLAUDE:
                # exactly today's common.handle_failure auth branch: one claude_auth event per 30 minutes, same detail shape;
                # the banner names the fix for the reason (login / top-up / the binary) instead of always "not logged in"
                budget.event_once(
                    conn,
                    EVENT_CLAUDE_AUTH,
                    to_iso(parse_iso(now) - AUTH_EVENT_WINDOW),
                    {"status": result.status, "error": error_text, "paused_until": paused_until, "banner_zh": banner_for(reason)},
                    now=now,
                )
            else:
                db.kv_delete(conn, KV_FALLBACK_PAUSE_REASON)  # an ordinary (hard) pause replaces a quality pause: any fallback success lifts it
                _insert_event(conn, EVENT_FALLBACK_PAUSED, {"status": result.status, "error": error_text, "paused_until": paused_until, "reason": reason}, now=now)
            action = "pause"
            triggered = True
        else:
            key = STREAK_KEYS[(provider, reason)]
            streak = _int(db.kv_get(conn, key)) + 1
            triggered = streak >= _soft_threshold(cfg, reason)
            if reason == "overloaded" and streak >= OVERLOAD_PAUSE_AFTER:
                paused_until = to_iso(parse_iso(now) + OVERLOAD_PAUSE)
                budget.set_paused_until(conn, paused_until, now=now, provider=provider)
                db.kv_set(conn, key, "0", now=now)
                if provider == CLAUDE:
                    _insert_event(conn, EVENT_CLAUDE_OVERLOADED, {"paused_until": paused_until, "consecutive": streak}, now=now)
                else:
                    db.kv_delete(conn, KV_FALLBACK_PAUSE_REASON)  # an ordinary (overload) pause replaces a quality pause
                    _insert_event(
                        conn,
                        EVENT_FALLBACK_PAUSED,
                        {"status": result.status, "error": error_text, "paused_until": paused_until, "reason": reason, "consecutive": streak},
                        now=now,
                    )
                action = "pause"
            else:
                db.kv_set(conn, key, str(streak), now=now)
        if m == "auto" and triggered:
            if provider == CLAUDE:
                # hard: the CLI as such is down — the switch needs only a usable fallback (configured, not paused, not marked
                # unavailable); whether THIS kind may rerun there (WD_AI_FALLBACK_KINDS / prewarm) decides retry_provider alone.
                # soft: switch only when this kind is routable — a flip on a content streak would fail back on the next
                # content success and flap between the providers every few minutes
                eligible, _ = fallback_eligible(conn, cfg, kind=kind, priority=priority, now=now)
                usable = fallback_eligible(conn, cfg, kind="probe", priority=0, now=now)[0] if klass == "hard" else eligible
                if usable:
                    if _cas_active(conn, CLAUDE, FALLBACK, now=now):
                        next_probe = to_iso(parse_iso(now) + _probe_every(cfg))
                        db.kv_set(conn, KV_FAILOVER_SINCE, now, now=now)
                        db.kv_set(conn, KV_FAILOVER_REASON, reason, now=now)
                        db.kv_set(conn, KV_FAILOVER_TRIGGER, str(int(result.call_id or 0)), now=now)
                        db.kv_set(conn, KV_NEXT_PROBE, next_probe, now=now)
                        db.kv_set(conn, KV_PROBE_FAILURES, "0", now=now)
                        _reset_quality_streak(conn, now=now)  # a new episode counts from zero: a stale 2 must not pause the fallback on its first miss
                        detail = {
                            "from": CLAUDE,
                            "to": FALLBACK,
                            "reason": reason,
                            "trigger_call_id": int(result.call_id or 0),
                            "kind": kind,
                            "status": result.status,
                            "error": error_text,
                            "attempts": int(attempts),
                            "claude_paused_until": paused_until,
                            "next_probe_at": next_probe,
                        }
                        _insert_event(conn, EVENT_FAILOVER, detail, now=now)
                        event = EVENT_FAILOVER
                        notice = ("failover", detail)
                    action = "switch"
                    retry = FALLBACK if eligible else None
                elif paused_until is not None:
                    # claude was just paused and the fallback cannot take over: nobody is left (§4.5 两边都挂 — the alert
                    # that ends the unnoticed 8-hour outage); a soft threshold without a pause is not "down"
                    fb_pause = budget.provider_paused_until(conn, FALLBACK, now)
                    fb_unavailable = db.kv_get(conn, KV_FALLBACK_AVAILABLE) == "0"
                    if fb_pause is not None or fb_unavailable:
                        notice = (
                            "both_paused",
                            {
                                "reason": reason,
                                "status": result.status,
                                "error": error_text,
                                "kind": kind,
                                "claude_paused_until": paused_until,
                                "fallback_paused_until": fb_pause,
                                "fallback_unavailable": fb_unavailable,
                            },
                        )
            else:
                claude_pause = budget.provider_paused_until(conn, CLAUDE, now)
                if claude_pause is None:
                    retry = CLAUDE
                elif paused_until is not None:
                    notice = (
                        "both_paused",
                        {
                            "reason": reason,
                            "status": result.status,
                            "error": error_text,
                            "kind": kind,
                            "claude_paused_until": claude_pause,
                            "fallback_paused_until": paused_until,
                            "fallback_unavailable": False,
                        },
                    )
    log.warning(
        "%s on %s (%s/%s): action=%s paused_until=%s retry=%s",
        result.status,
        provider,
        klass,
        reason,
        action,
        paused_until,
        retry,
        extra={"event": "ai_failover_decision", "provider": provider},
    )
    if notice is not None:
        notify(conn, cfg, notice[0], notice[1], now=now)  # after our own transaction: no HTTP under the write lock
    return Decision(action, paused_until, retry, event)


def _record_quality_failure(conn: sqlite3.Connection, cfg: Settings, *, kind: str, result: ClaudeResult, now: str) -> Decision:
    """The fallback answered but the answer was unusable (:func:`is_quality_failure`; AI_FALLBACK_MODEL §4.2 row
    ``invalid_output`` / 内容过滤): count ``ai.fallback.streak.invalid``; the :data:`QUALITY_PAUSE_AFTER`-th in a row pauses
    the fallback for the cooldown (``ai.fallback.paused_until``, one ``ai_fallback_quality`` event, the ``fallback_quality``
    notification) and resets the streak. ``retry_provider`` is always None — an invalid group is never rerun on the other
    provider; the handler's backoff → bisect → dead path (§6.3) decides its fate. The pause is tagged
    ``ai.fallback.pause_reason='quality'``: unlike an ordinary fallback pause it survives an ordinary HTTP-ok fallback call
    (an in-flight sibling's answer is no proof of quality — its items may still be rejected whole) and is lifted only by
    a fallback probe (:func:`record_success` with ``kind='probe'``), an applied fallback group
    (:func:`record_quality_success`) or the admin's resume (:func:`clear_pauses`). The notification's tail names
    Claude's state: paused, unconfirmed (an expired pause while the fallback is still the active provider, or a failed
    probe's ``claude.available='0'``), or back. Only reachable for the fallback (:func:`record_failure`). Precondition:
    no open transaction on ``conn``."""
    error_text = str(result.error or result.status or "")[:300]
    paused_until: str | None = None
    detail: dict[str, Any] | None = None
    with db.maybe_tx(conn):
        streak = _int(db.kv_get(conn, KV_FALLBACK_QUALITY_STREAK)) + 1
        if streak >= QUALITY_PAUSE_AFTER:
            paused_until = to_iso(parse_iso(now) + _cooldown(cfg))
            budget.set_paused_until(conn, paused_until, now=now, provider=FALLBACK)
            db.kv_set(conn, KV_FALLBACK_PAUSE_REASON, "quality", now=now)
            db.kv_set(conn, KV_FALLBACK_QUALITY_STREAK, "0", now=now)
            detail = {
                "consecutive": streak,
                "kind": kind,
                "status": result.status,
                "error": error_text,
                "call_id": None if result.call_id is None else int(result.call_id),
                "paused_until": paused_until,
                "model_seen": result.model_used or db.kv_get(conn, KV_FALLBACK_MODEL_SEEN),
            }
            _insert_event(conn, EVENT_FALLBACK_QUALITY, detail, now=now)
        else:
            db.kv_set(conn, KV_FALLBACK_QUALITY_STREAK, str(streak), now=now)
    action = "pause" if paused_until is not None else "none"
    log.warning(
        "%s on %s (quality %d/%d): action=%s paused_until=%s retry=None",
        result.status,
        FALLBACK,
        streak,
        QUALITY_PAUSE_AFTER,
        action,
        paused_until,
        extra={"event": "ai_failover_decision", "provider": FALLBACK},
    )
    if detail is not None:
        # after our own transaction: no HTTP under the write lock; the body says whether Claude takes the jobs meanwhile —
        # an expired claude pause is not a healthy Claude, so the active provider and claude.available (a failed probe) are read too
        notify(
            conn,
            cfg,
            "fallback_quality",
            {
                **detail,
                "claude_paused_until": budget.provider_paused_until(conn, CLAUDE, now),
                "active": active_provider(conn),
                "claude_available": db.kv_get(conn, KV_CLAUDE_AVAILABLE),
            },
            now=now,
        )
    return Decision(action, paused_until, None, None)


def record_quality_success(conn: sqlite3.Connection, *, provider: str, now: str) -> None:
    """A handler applied an answer of ``provider`` (at least one item stored — ``common.record_applied``): the fallback's
    quality streak ends and a quality pause (``ai.fallback.pause_reason='quality'``) is lifted — the tag and the pause go,
    the jobs parked at that instant run now (:func:`_release_parked`). An applied group is the proof of quality the
    streak is about; :func:`record_success` cannot give it: an HTTP-ok answer may still be rejected whole by the handler's
    post-validation, which is exactly what the streak counts (so an in-flight sibling's ok answer leaves the pause
    alone). Reads first and writes only when the streak is counting or the pause is a quality pause. Claude → no-op (its
    answers never count there)."""
    if provider != FALLBACK:
        return
    counting = db.kv_get(conn, KV_FALLBACK_QUALITY_STREAK) not in (None, "0")
    if not counting and db.kv_get(conn, KV_FALLBACK_PAUSE_REASON) != "quality":
        return
    with db.maybe_tx(conn):
        _reset_quality_streak(conn, now=now)
        if db.kv_get(conn, KV_FALLBACK_PAUSE_REASON) == "quality":  # re-read under the write lock
            paused = db.kv_get(conn, KV_FALLBACK_PAUSE)
            budget.set_paused_until(conn, None, now=now, provider=FALLBACK)
            db.kv_delete(conn, KV_FALLBACK_PAUSE_REASON)
            _release_parked(conn, (paused,), now=now)
            log.info("fallback quality pause (until %s) lifted by an applied group", paused, extra={"event": "ai_fallback_quality_lifted", "provider": FALLBACK})


def record_success(
    conn: sqlite3.Connection,
    cfg: Settings,
    *,
    provider: str,
    kind: str,
    model_used: str | None,
    now: str,
    call_id: int | None = None,
    probe_call_ids: Sequence[int] | None = None,
) -> bool:
    """A successful call on ``provider`` is proof it works again (accepted trade-off: with ``WD_AI_CONCURRENCY`` > 1 an
    in-flight success that lands seconds after a sibling's hard failure lifts that fresh pause too — the next failure
    simply re-pauses, ``claude_auth`` stays deduplicated): its streaks end, a ``'0'`` availability mark is lifted
    and its automatic pause (``claude.paused_until`` / ``ai.fallback.paused_until``) is cleared — on ANY success of that
    provider, an ordinary call or a probe (``wd claude-check``, the admin's 「探测」, :func:`maybe_probe`), in every mode:
    without this a ``balance:`` pause (24 h) in ``claude_cli`` mode had no way back short of the admin's resume once the
    operator had topped up and probed, exactly as the banner tells them to. The jobs parked at the lifted pause instant
    run now (:func:`_release_parked`). The one exception is the fallback's quality pause
    (``ai.fallback.pause_reason='quality'``): an ordinary fallback call (``kind != 'probe'``) leaves it — the trade-off
    above does not transfer there, re-pausing would need three fresh strikes and the ok answer may still be rejected
    whole — and only a fallback probe, an applied group (:func:`record_quality_success`) or the resume lifts it.

    Fallback: remembers the vendor model actually answering (``ai.fallback.model_seen``); the quality streak is NOT
    reset here (:func:`record_quality_success`). Claude while the fallback is active: compare-and-swap back to
    ``claude``, requeue the content / lookup jobs that died since ``ai.failover.since`` (:func:`_requeue_outage_dead`,
    inside the same transaction), write ``ai_failback`` (``outage_min``, the probe's ``probe_call_ids``,
    ``requeued_dead``), end the episode (:data:`FAILOVER_KEYS` and the probe schedule deleted — the detail keeps
    ``since``) and notify; returns True exactly when this call failed back (§4.1 step 4). Claude in mode ``auto`` with a
    configured fallback when NO flip happened but a claude pause was just lifted: the fallback may have bridged that
    pause without a switch (:func:`choose` routes to an eligible fallback while claude is paused; a hard failure while
    the fallback was paused or marked unavailable writes no ``since``), so the jobs that died since the pause started
    (the pause row's ``updated_at`` — ``budget.set_paused_until`` writes it at pause time) are requeued the same way,
    logged only (``ai_failback_requeue``; no event, no notification, returns False).
    Precondition: no open transaction on ``conn`` (the notification is skipped inside one, see :func:`notify`).
    """
    provider = provider if provider in PROVIDERS else CLAUDE
    detail: dict[str, Any] | None = None
    with db.maybe_tx(conn):
        _reset_streaks(conn, provider, now=now)
        if db.kv_get(conn, AVAILABLE_KEYS[provider]) == "0":
            db.kv_set(conn, AVAILABLE_KEYS[provider], "1", now=now)
        # the pause row's updated_at is the pause start (budget.set_paused_until writes it at pause time): the no-flip requeue is keyed on it
        row = conn.execute("SELECT value, updated_at FROM kv WHERE key = ?", (budget.PAUSE_KEYS[provider],)).fetchone()
        paused = None if row is None else str(row[0])
        pause_started = None if row is None or not row[1] else str(row[1])
        lifted = False
        if paused is not None:
            if provider == FALLBACK and kind != "probe" and db.kv_get(conn, KV_FALLBACK_PAUSE_REASON) == "quality":
                log.info("fallback quality pause (until %s) kept: an ordinary %s success is no proof of quality", paused, kind, extra={"event": "ai_fallback_quality_kept", "provider": FALLBACK})
            else:
                budget.set_paused_until(conn, None, now=now, provider=provider)
                if provider == FALLBACK:
                    db.kv_delete(conn, KV_FALLBACK_PAUSE_REASON)
                _release_parked(conn, (paused,), now=now)
                lifted = True
        if provider == FALLBACK:
            if model_used:
                db.kv_set(conn, KV_FALLBACK_MODEL_SEEN, str(model_used), now=now)
            return False
        if active_provider(conn) == FALLBACK and _cas_active(conn, FALLBACK, CLAUDE, now=now):
            since = db.kv_get(conn, KV_FAILOVER_SINCE)
            outage_min: int | None = None
            if since:
                try:
                    outage_min = max(0, int(round((parse_iso(now) - parse_iso(since)).total_seconds() / 60)))
                except ValueError:
                    outage_min = None
            requeued = _requeue_outage_dead(conn, since, now=now)
            detail = {
                "from": FALLBACK,
                "to": CLAUDE,
                "outage_min": outage_min,
                "since": since,
                "probe_call_ids": [int(c) for c in (probe_call_ids or [])],
                "call_id": None if call_id is None else int(call_id),
                "kind": kind,
                "model_used": model_used,
                "requeued_dead": requeued,
            }
            _insert_event(conn, EVENT_FAILBACK, detail, now=now)
            for key in (*FAILOVER_KEYS, *PROBE_KEYS):  # the episode is over: since / reason / trigger go with the probe schedule
                db.kv_delete(conn, key)
        elif lifted and mode(cfg) == "auto" and bool(getattr(cfg, "fallback_configured", False)):
            # no flip, but a claude pause just ended: in mode auto the fallback may have bridged it without a switch
            # (choose routes to an eligible fallback while claude is paused) — its casualties are outage casualties too
            _requeue_outage_dead(conn, pause_started, now=now)
    if detail is None:
        return False
    log.warning("failed back to claude after %s min (%s)", detail["outage_min"], kind, extra={"event": EVENT_FAILBACK, "provider": CLAUDE})
    notify(conn, cfg, "failback", detail, now=now)
    return True


def maybe_probe(conn: sqlite3.Connection, cfg: Settings, *, now: str, probe_claude: Callable[[], Any], force: bool = False) -> str | None:
    """Housekeeping hook: while mode is ``auto`` and the fallback is active, probe claude when ``ai.failover.next_probe_at``
    is due (or ``force``, the first housekeeping after a start). Returns ``"failback"`` / ``"probe_failed"`` / None.

    ``probe_claude`` is ``lambda: probe.check(conn, cfg, now=now)`` (a ``ProbeResult``-like object with ``ok``,
    ``model_used``, ``call_ids``). It runs even while claude is paused for auth — the probe is the only way back. Nothing
    runs under the kill switch or the admin's global pause. The slot is claimed inside ``BEGIN IMMEDIATE`` before the slow
    probe (``next_probe_at`` moves on, ``last_probe_at`` records the start), so sibling workers see it taken. ``force``
    ignores the schedule but not a probe that started less than :data:`PROBE_FORCE_GRACE` ago: ``main.py`` starts up to
    ``WD_AI_CONCURRENCY`` ClaudeWorkers and each forces once, which would otherwise spawn N concurrent probes and count N
    failures per restart. A failed probe schedules the next one ``WD_AI_FAILOVER_PROBE_EVERY_MIN`` later (twice that after
    12 consecutive failures) and counts ``ai.failover.probe_failures``; a probe that succeeds after another path already
    failed back (a successful claude call, the admin's resume) reports None and leaves no stale schedule behind.
    """
    if mode(cfg) != "auto" or active_provider(conn) != FALLBACK:
        return None
    if not budget.ai_enabled(conn, cfg) or budget.global_paused_until(conn, now) is not None:
        return None
    every = _probe_every(cfg)
    with db.maybe_tx(conn):  # BEGIN IMMEDIATE: the due check and the claim are one critical section across workers
        if force:
            if _within(db.kv_get(conn, KV_LAST_PROBE), PROBE_FORCE_GRACE, now):
                return None  # a sibling worker's start-up probe is running or just ran
        else:
            nxt = db.kv_get(conn, KV_NEXT_PROBE)
            if nxt is not None and now < nxt:
                return None
        db.kv_set(conn, KV_NEXT_PROBE, to_iso(parse_iso(now) + every), now=now)  # claim the slot before the slow probe
        db.kv_set(conn, KV_LAST_PROBE, now, now=now)
    result: Any = None
    try:
        result = probe_claude()
    except sqlite3.Error:
        raise
    except Exception as e:  # noqa: BLE001 — a broken probe is a failed probe, never a worker crash
        log.warning("fail-back probe raised %s: %s", e.__class__.__name__, e, extra={"event": "ai_probe_error", "provider": CLAUDE})
    if result is not None and bool(getattr(result, "ok", False)):
        flipped = record_success(
            conn,
            cfg,
            provider=CLAUDE,
            kind="probe",
            model_used=getattr(result, "model_used", None),
            now=now,
            probe_call_ids=list(getattr(result, "call_ids", None) or []),
        )
        if flipped:
            return "failback"
        with db.maybe_tx(conn):  # another path flipped back during the probe: our claim must not outlive the fail-back
            if active_provider(conn) == CLAUDE:
                for key in PROBE_KEYS:
                    db.kv_delete(conn, key)
        return None
    with db.maybe_tx(conn):
        failures = _int(db.kv_get(conn, KV_PROBE_FAILURES)) + 1
        wait = every * (2 if failures >= PROBE_BACKOFF_AFTER else 1)
        db.kv_set(conn, KV_PROBE_FAILURES, str(failures), now=now)
        db.kv_set(conn, KV_NEXT_PROBE, to_iso(parse_iso(now) + wait), now=now)
    log.info("fail-back probe failed (%d in a row); next at +%d min", failures, int(wait.total_seconds() // 60), extra={"event": "ai_probe_failed", "provider": CLAUDE})
    return "probe_failed"


def reconcile_mode(conn: sqlite3.Connection, cfg: Settings, *, now: str) -> bool:
    """Start-up hook (``ClaudeWorker``'s first housekeeping, before the forced probe): end a stale failover episode in a
    non-``auto`` mode. A sticky ``ai.active_provider='fallback'`` left by an earlier ``auto`` tour is invisible to
    :func:`choose` in ``claude_cli`` / ``openai_http``, yet the first successful claude call (a ``wd claude-check`` days
    later in ``openai_http``) would still "fail back" from it: an ``ai_failback`` event with an inflated ``outage_min``,
    the 「已切回 Claude」 webhook and a requeue of everything dead since the stale ``since`` — in ``openai_http`` onto the
    very fallback those jobs died on. When ``mode(cfg) != 'auto'`` and the fallback is the active provider:
    compare-and-swap ``ai.active_provider`` → ``claude`` and delete :data:`FAILOVER_KEYS` and :data:`PROBE_KEYS` in one
    transaction, one info log (event ``ai_failover_reconciled``, naming the dropped ``since``); no requeue, no system
    event, no notification. Returns True when it changed something, False in mode ``auto`` or when claude is already
    the active provider (the read happens first: a normal start takes no write lock)."""
    m = mode(cfg)
    if m == "auto" or active_provider(conn) != FALLBACK:
        return False
    with db.maybe_tx(conn):
        since = db.kv_get(conn, KV_FAILOVER_SINCE)
        if not _cas_active(conn, FALLBACK, CLAUDE, now=now):
            return False  # a sibling worker reconciled first
        for key in (*FAILOVER_KEYS, *PROBE_KEYS):
            db.kv_delete(conn, key)
    log.info("mode %s: stale failover state (active=fallback since %s) reset to claude", m, since, extra={"event": "ai_failover_reconciled", "provider": CLAUDE})
    return True


# ------------------------------------------------------------------------------------------ admin
def set_manual_pause(conn: sqlite3.Connection, until: str, *, now: str) -> None:
    """The admin's pause (``POST /api/admin/ai/pause``): ``kv.ai.paused_until`` holds every provider until ``until``."""
    with db.maybe_tx(conn):
        db.kv_set(conn, KV_GLOBAL_PAUSE, until, now=now)


def clear_pauses(conn: sqlite3.Connection, *, now: str) -> None:
    """Admin resume (``POST /api/admin/ai/pause {paused: false}``, CLAUDE_INTEGRATION §10.5): lift the manual pause and
    every automatic one, reset the streaks and the probe schedule, make claude the active provider again and lift a
    hand-set kill switch (``kv.claude.enabled='1'``).

    The sticky ``'0'`` availability marks (``claude.available`` / ``ai.fallback.available``, written by a failed probe or
    a ``spawn_error`` / ``not_found:``) are deleted too — otherwise a fallback marked ``'0'`` during a vendor hiccup stays
    refused by :func:`fallback_eligible` for ever and the AI tab shows "resumed" while nothing runs. Deleted, not set to
    ``'1'``: the health page's ``claude_bin.ok`` must not pretend a probe passed. The jobs parked at the lifted pause
    instants run now (:func:`_release_parked`); the pause values are read before the keys go. The fallback's quality
    streak and its quality-pause tag (``ai.fallback.pause_reason``) are reset too, the episode bookkeeping
    (:data:`FAILOVER_KEYS`: ``ai.failover.{since,reason,trigger_call_id}``) ends with the probe schedule, and when the
    fallback WAS the active provider the content / lookup jobs that died since ``ai.failover.since`` (read first) are
    requeued like on an automatic fail-back (:func:`_requeue_outage_dead`; the count is only logged — the
    ``claude_resumed`` event stays the router's).
    """
    with db.maybe_tx(conn):
        was_fallback = active_provider(conn) == FALLBACK
        since = db.kv_get(conn, KV_FAILOVER_SINCE)  # read before the keys go: the requeue below is keyed on it
        horizons = [db.kv_get(conn, key) for key in (KV_GLOBAL_PAUSE, KV_CLAUDE_PAUSE, KV_FALLBACK_PAUSE)]
        for key in (KV_GLOBAL_PAUSE, KV_CLAUDE_PAUSE, KV_FALLBACK_PAUSE, KV_FALLBACK_PAUSE_REASON, *FAILOVER_KEYS, *PROBE_KEYS):
            db.kv_delete(conn, key)
        for key in AVAILABLE_KEYS.values():
            if db.kv_get(conn, key) == "0":
                db.kv_delete(conn, key)
        for provider in PROVIDERS:
            _reset_streaks(conn, provider, now=now)
        _reset_quality_streak(conn, now=now)
        db.kv_set(conn, KV_ACTIVE, CLAUDE, now=now)
        db.kv_set(conn, KV_CLAUDE_ENABLED, "1", now=now)
        _release_parked(conn, horizons, now=now)
        if was_fallback:
            _requeue_outage_dead(conn, since, now=now)


# ------------------------------------------------------------------------------------ notifications
def _local_clock(iso: str | None, tz: str) -> str:
    if not iso:
        return "—"
    try:
        return parse_iso(iso).astimezone(zone(tz)).strftime("%m-%d %H:%M")
    except (ValueError, TypeError):
        return str(iso)


def notification_text(kind: str, detail: Mapping[str, Any], cfg: Settings) -> tuple[str, str]:
    """``(title_zh, body_zh)`` of an admin notification (AI_FALLBACK_MODEL §4.5: switch, fail-back, both providers down,
    the fallback's quality pause).

    ``detail["reason"]`` already names the spec §0 prefix, so a ``balance: …`` / ``network: …`` error loses its prefix;
    the quality body keeps it (``schema:`` / ``content_filter:`` is the information). Its tail says who takes the jobs
    meanwhile: a queue while Claude is paused; "Claude 状态未知 … 先尝试 Claude" when its pause merely expired but nothing
    proved it back (``detail["active"]`` is still the fallback, or ``claude_available == '0'`` after a failed probe);
    "Claude 正常" only when claude is the active provider again — and in mode ``openai_http`` the CLI is never spawned,
    so the jobs wait for the fallback's pause whatever Claude's state.
    """
    tz = str(getattr(cfg, "tz", "Asia/Shanghai") or "Asia/Shanghai")
    model = str(getattr(cfg, "ai_fallback_model", "") or "备用模型")
    every = int(getattr(cfg, "ai_failover_probe_every_min", 30) or 30)
    reason = str(detail.get("reason") or detail.get("status") or "?")
    error = _strip_prefix(str(detail.get("error") or ""))[:160]
    cause = f"{reason}：{error}" if error else reason
    if kind == "failover":
        body = f"Claude 调用失败（{cause}），已自动切换到备用模型 {model}。每 {every} 分钟探测一次 Claude，恢复后自动切回。"
        return "word-Dance：AI 已切换到备用模型", body
    if kind == "failback":
        outage = detail.get("outage_min")
        body = f"Claude 已恢复，备用模型顶替了约 {outage} 分钟。" if outage is not None else "Claude 已恢复，已切回主模型。"
        return "word-Dance：AI 已切回 Claude", body
    if kind == "both_paused":
        fb_until = detail.get("fallback_paused_until")
        if fb_until:
            fallback_state = f"备用模型暂停至 {_local_clock(fb_until, tz)}"
        elif detail.get("fallback_unavailable"):
            fallback_state = "备用模型不可用（等待探测恢复）"
        else:
            fallback_state = "备用模型不可用"
        body = f"主模型与备用模型均失败（{cause}），任务已排队等待。Claude 暂停至 {_local_clock(detail.get('claude_paused_until'), tz)}，{fallback_state}。"
        return "word-Dance：AI 暂时不可用", body
    if kind == "fallback_quality":
        raw_error = str(detail.get("error") or detail.get("status") or "")[:160]
        claude_until = detail.get("claude_paused_until")
        if mode(cfg) == "openai_http":
            tail = "当前为仅备用模式，任务排队等待备用模型恢复。"
        elif claude_until:
            tail = f"Claude 暂停至 {_local_clock(claude_until, tz)}，任务排队等待。"
        elif detail.get("active") == FALLBACK or detail.get("claude_available") == "0":
            # an expired claude pause is not a healthy Claude: no fail-back has been proven (the probe failed, or none ran yet)
            tail = "Claude 状态未知（上次探测或调用失败），任务将先尝试 Claude，失败则排队等待。"
        else:
            tail = "Claude 正常，任务已切回 Claude。"
        body = (
            f"备用模型 {model} 连续 {detail.get('consecutive')} 次返回无效结果（{detail.get('kind') or '?'}：{raw_error}），"
            f"已暂停至 {_local_clock(detail.get('paused_until'), tz)}。{tail}"
        )
        return "word-Dance：备用模型输出异常，已暂停", body
    return f"word-Dance：AI {kind}", json.dumps(dict(detail), ensure_ascii=False, sort_keys=True)[:500]


def notify(conn: sqlite3.Connection, cfg: Settings, kind: str, detail: Mapping[str, Any], *, now: str) -> None:
    """Best effort: post ``kind`` (``failover`` / ``failback`` / ``both_paused`` / ``fallback_quality``) to every admin
    webhook (users.role='admin' with ``user_settings.webhook_enabled=1`` and a URL), at most once per kind per hour
    (``kv.ai.notify.<kind>.last_at``).

    Skipped entirely under ``WD_SMOKE_MOCK_HTTP``, when no admin webhook exists, and inside an open transaction on ``conn``
    (``db.maybe_tx`` would join it, and a 10-second webhook timeout per admin must not run under ``BEGIN IMMEDIATE`` — the
    outcome hooks are called outside one); every exception is swallowed (a failed notification must never change a job's
    fate). The request goes through ``wd.delivery.webhook.safe_post`` (SSRF rules, DNS pin, 10 s timeout); tests inject
    a client through :data:`WEBHOOK_CLIENT_FACTORY` or patch ``safe_post``.
    """
    try:
        if bool(getattr(cfg, "smoke_mock_http", False)):
            return
        if conn.in_transaction:
            log.warning("ai notification %s skipped inside an open transaction", kind, extra={"event": "ai_notify_skipped"})
            return
        rows = conn.execute(ADMIN_WEBHOOKS_SQL).fetchall()
        if not rows:
            return
        key = f"ai.notify.{kind}.last_at"
        if _within(db.kv_get(conn, key), NOTIFY_WINDOW, now):
            return
        with db.maybe_tx(conn):
            db.kv_set(conn, key, now, now=now)  # claimed before sending: a failing endpoint is not retried every minute
        from ..delivery import webhook as webhook_mod  # lazy: the delivery package pulls in the job registry

        title, body = notification_text(kind, detail, cfg)
        for row in rows:
            url = str(row["webhook_url"])
            fmt = str(row["webhook_format"] or "generic")
            if fmt not in webhook_mod.FORMATS:
                fmt = "generic"
            payload = webhook_mod.build_payload(fmt, title, body, url=None, date=now[:10], type_="ai_" + kind)
            client = WEBHOOK_CLIENT_FACTORY() if WEBHOOK_CLIENT_FACTORY is not None else None
            try:
                status, error, _reason = webhook_mod.safe_post(url, payload, client=client)
            finally:
                if client is not None:
                    client.close()
            if error is None:
                log.info("ai notification %s sent", kind, extra={"event": "ai_notify_sent", "status": status})
            else:
                log.warning("ai notification %s failed: %s", kind, error, extra={"event": "ai_notify_failed"})
    except Exception:  # noqa: BLE001 — best effort by contract
        log.warning("ai notification %s failed", kind, exc_info=True, extra={"event": "ai_notify_failed"})

__all__ = [
    "AUTH_BANNER_ZH",
    "AVAILABLE_KEYS",
    "Availability",
    "BALANCE_BANNER_ZH",
    "BANNERS_ZH",
    "CLAUDE",
    "Decision",
    "EVENT_CLAUDE_AUTH",
    "EVENT_CLAUDE_OVERLOADED",
    "EVENT_FAILBACK",
    "EVENT_FAILOVER",
    "EVENT_FALLBACK_PAUSED",
    "EVENT_FALLBACK_QUALITY",
    "FAILOVER_KEYS",
    "FALLBACK",
    "KV_ACTIVE",
    "KV_FALLBACK_AVAILABLE",
    "KV_FALLBACK_MODEL_SEEN",
    "KV_FALLBACK_PAUSE_REASON",
    "KV_FALLBACK_QUALITY_STREAK",
    "KV_LAST_PROBE",
    "KV_NEXT_PROBE",
    "KV_PROBE_FAILURES",
    "OVERLOAD_PAUSE",
    "OVERLOAD_PAUSE_AFTER",
    "OVERLOAD_STREAK_KEY",
    "PROBE_FORCE_GRACE",
    "PROBE_KEYS",
    "PROVIDERS",
    "QUALITY_PAUSE_AFTER",
    "QUOTA_BANNER_ZH",
    "SPAWN_BANNER_ZH",
    "STREAK_KEYS",
    "WEBHOOK_CLIENT_FACTORY",
    "active_provider",
    "availability",
    "banner_for",
    "choose",
    "claim_limit",
    "classify",
    "clear_pauses",
    "error_prefix",
    "fallback_eligible",
    "group_cap",
    "is_quality_failure",
    "maybe_probe",
    "mode",
    "notification_text",
    "notify",
    "reconcile_mode",
    "record_failure",
    "record_quality_success",
    "record_success",
    "retry_at_from_error",
    "set_fallback_paused_until",
    "set_manual_pause",
]
