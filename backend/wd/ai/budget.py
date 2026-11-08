"""Cost model and guardrails (CLAUDE_INTEGRATION §7; TASKS §I ``can_spend``).

Estimates used for reservations: content ``0.005 + 0.0045 × words``, lookup ``0.004 + 0.002 × strings``,
consolidate ``0.05``, svg ``0.03`` (probe ``0.01``). Before every call the caller checks, in this order, the kill
switch, ``kv.claude.paused_until``, the hourly call cap (``WD_AI_HOURLY_CALL_CAP``), the monthly cap, the daily cap
(``spent_today = SUM(cost_usd) over the current WD_TZ day + SUM(reserved_usd) of running calls``), the prewarm
sub-cap for priority-≥ 90 jobs and the SVG sub-cap for ``generate_svg`` — and defers instead of failing:
:func:`can_spend` returns ``(False, resumes_at_iso)`` with ``resumes_at`` = the next ``WD_TZ`` day 00:05
(daily / prewarm / svg), the 1st of next month 00:05 (monthly) or the next hour boundary + 1 min (hourly).

:func:`reserve` is the atomic form the handlers use: check **and** insert the ``running`` ledger row (the
reservation) inside one ``BEGIN IMMEDIATE``, so two concurrent workers respect the caps together.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Sequence

from .. import db
from ..clock import day_start, local_date, now_iso, parse_iso, to_iso, zone
from ..config import Settings
from . import ledger

# kind → (fixed, per word) USD
ESTIMATES: dict[str, tuple[float, float]] = {
    "content": (0.005, 0.0045),
    "lookup": (0.004, 0.002),
    "consolidate": (0.05, 0.0),
    "svg": (0.03, 0.0),
    "probe": (0.01, 0.0),
    "dance": (0.01, 0.003),  # 20 words per call ≈ $0.07 (dance_v1 items are short)
}
PROVIDERS: tuple[str, ...] = ("claude", "fallback")
KV_GLOBAL_PAUSE = "ai.paused_until"  # the admin's manual pause: every provider (POST /api/admin/ai/pause)
KV_CLAUDE_PAUSE = "claude.paused_until"  # automatic pause of the CLI provider (auth / spawn_error / overload streak)
KV_FALLBACK_PAUSE = "ai.fallback.paused_until"  # automatic pause of the fallback provider
PAUSE_KEYS: dict[str, str] = {"claude": KV_CLAUDE_PAUSE, "fallback": KV_FALLBACK_PAUSE}
PREWARM_PRIORITY = 90
PREWARM_DAILY_SHARE = 0.5  # prewarm additionally requires spent_today < 0.5 × daily cap
RESUME_MINUTE = 5  # deferrals resume at 00:05 local
DISABLED_WAIT = timedelta(minutes=30)
EVENT_DAILY = "budget_daily"
EVENT_MONTHLY = "budget_monthly"
EVENT_SVG = "budget_svg"
EVENT_DANCE = "budget_dance"


def estimate(kind: str, word_count: int = 1, provider: str = "claude") -> float:
    """Reservation estimate in USD for a call of ``kind`` over ``word_count`` words/strings.

    The fallback provider reserves nothing (its free tier costs 0; a paid price table is charged post hoc through
    ``cost_usd`` and still counts in ``spent_today`` / ``spent_month``, CLAUDE_INTEGRATION §10).
    """
    if provider != "claude":
        return 0.0
    fixed, per = ESTIMATES.get(kind, ESTIMATES["content"])
    return round(fixed + per * max(0, int(word_count)), 6)


def budget_for(cfg: Settings, kind: str) -> float:
    """The per-call ``--max-budget-usd`` (DEPLOY §4 ``WD_AI_BUDGET_*``; probe 0.05)."""
    return {
        "content": cfg.ai_budget_content,
        "lookup": cfg.ai_budget_lookup,
        "consolidate": cfg.ai_budget_consolidate,
        "svg": cfg.ai_budget_svg,
        "dance": cfg.ai_budget_dance,
        "probe": 0.05,
    }[kind]


def timeout_for(cfg: Settings, kind: str, provider: str = "claude") -> int:
    """Per-kind timeout in seconds (CLAUDE_INTEGRATION §1.2: content 180 · lookup 120 · consolidate 240 · svg 120 · probe 60);
    the fallback provider gets the same figure × ``WD_AI_FALLBACK_TIMEOUT_SCALE`` (slower free-tier models, §10)."""
    base = {
        "content": cfg.ai_timeout_content_sec,
        "lookup": cfg.ai_timeout_lookup_sec,
        "consolidate": cfg.ai_timeout_consolidate_sec,
        "svg": cfg.ai_timeout_svg_sec,
        "dance": cfg.ai_timeout_dance_sec,
        "probe": 60,
    }[kind]
    if provider != "claude":
        return max(5, int(round(base * float(getattr(cfg, "ai_fallback_timeout_scale", 1.5) or 1.5))))
    return int(base)


# --------------------------------------------------------------------------------------- windows
def day_window(now: str, tz: str) -> tuple[str, str]:
    """``[start, next_start)`` UTC instants of the ``tz`` local day containing ``now``."""
    d = local_date(parse_iso(now), tz)
    return to_iso(day_start(d, tz)), to_iso(day_start(d + timedelta(days=1), tz))


def month_window(now: str, tz: str) -> tuple[str, str]:
    """``[start, next_start)`` UTC instants of the ``tz`` local month containing ``now``."""
    d = local_date(parse_iso(now), tz)
    first = d.replace(day=1)
    nxt = (first.replace(year=first.year + 1, month=1) if first.month == 12 else first.replace(month=first.month + 1))
    return to_iso(day_start(first, tz)), to_iso(day_start(nxt, tz))


def _local_resume(day: datetime, tz: str) -> str:
    """00:05 local of the given date as a UTC ISO string."""
    z = zone(tz)
    return to_iso(datetime(day.year, day.month, day.day, 0, RESUME_MINUTE, tzinfo=z))


def next_day_resume(now: str, tz: str) -> str:
    """Next ``tz`` day 00:05 (daily / prewarm / svg deferrals)."""
    d = local_date(parse_iso(now), tz) + timedelta(days=1)
    return _local_resume(datetime(d.year, d.month, d.day), tz)


def next_month_resume(now: str, tz: str) -> str:
    """The 1st of next ``tz`` month 00:05 (monthly deferral)."""
    d = local_date(parse_iso(now), tz).replace(day=1)
    nxt = d.replace(year=d.year + 1, month=1) if d.month == 12 else d.replace(month=d.month + 1)
    return _local_resume(datetime(nxt.year, nxt.month, nxt.day), tz)


def next_hour_resume(now: str) -> str:
    """Next hour boundary + 1 minute (hourly call cap)."""
    dt = parse_iso(now).replace(minute=0, second=0, microsecond=0) + timedelta(hours=1, minutes=1)
    return to_iso(dt)


# ------------------------------------------------------------------------------------------ state
def ai_enabled(conn: sqlite3.Connection, cfg: Settings | None = None) -> bool:
    """The kill switch: ``WD_AI_ENABLED`` and ``kv.claude.enabled`` (``'0'`` = off). ``cfg`` defaults to the environment."""
    cfg = cfg or Settings.from_env()
    if not cfg.ai_enabled:
        return False
    return db.kv_get(conn, "claude.enabled") != "0"


def _future(value: str | None, now: str) -> str | None:
    return value if value and value > now else None


def global_paused_until(conn: sqlite3.Connection, now: str) -> str | None:
    """The admin's manual pause (``kv.ai.paused_until``, every provider) while it lies in the future, else None."""
    return _future(db.kv_get(conn, KV_GLOBAL_PAUSE), now)


def provider_paused_until(conn: sqlite3.Connection, provider: str, now: str) -> str | None:
    """The automatic pause of one provider (``claude.paused_until`` / ``ai.fallback.paused_until``) while in the future."""
    return _future(db.kv_get(conn, PAUSE_KEYS.get(provider, KV_CLAUDE_PAUSE)), now)


def paused_until(conn: sqlite3.Connection, now: str) -> str | None:
    """When the CLI provider may run again: ``kv.claude.paused_until`` or the admin's global pause, whichever lies
    further in the future (None when neither is set). The legacy readers (routers, scheduler, diag) keep this meaning."""
    candidates = [v for v in (provider_paused_until(conn, "claude", now), global_paused_until(conn, now)) if v]
    return max(candidates) if candidates else None


def set_paused_until(conn: sqlite3.Connection, until: str | None, *, now: str | None = None, provider: str = "claude") -> None:
    """Set (or clear with None) the automatic pause of ``provider``."""
    key = PAUSE_KEYS.get(provider, KV_CLAUDE_PAUSE)
    with db.maybe_tx(conn):
        if until is None:
            db.kv_delete(conn, key)
        else:
            db.kv_set(conn, key, until, now=now)


def spent_today(conn: sqlite3.Connection, cfg: Settings | None = None, now: str | None = None) -> float:
    """``SUM(cost_usd)`` of today's (``WD_TZ``) calls + ``SUM(reserved_usd)`` of the calls still running.

    ``cfg`` defaults to the environment (WP4's ``maintenance.prefetch`` passes its own ``Settings``).
    """
    cfg = cfg or Settings.from_env()
    now = now or now_iso()
    start, end = day_window(now, cfg.tz)
    return ledger.sum_cost(conn, start, end) + ledger.reserved_running(conn)


def spent_month(conn: sqlite3.Connection, cfg: Settings | None = None, now: str | None = None) -> float:
    cfg = cfg or Settings.from_env()
    now = now or now_iso()
    start, end = month_window(now, cfg.tz)
    return ledger.sum_cost(conn, start, end) + ledger.reserved_running(conn)


def svg_spent_today(conn: sqlite3.Connection, cfg: Settings | None = None, now: str | None = None) -> float:
    """Spend of today's ``kind='svg'`` calls (counted inside the daily cap), running reservations included."""
    cfg = cfg or Settings.from_env()
    now = now or now_iso()
    start, end = day_window(now, cfg.tz)
    return ledger.sum_cost(conn, start, end, kind="svg") + ledger.reserved_running(conn, kind="svg")


def dance_spent_today(conn: sqlite3.Connection, cfg: Settings | None = None, now: str | None = None) -> float:
    """Spend of today's ``kind='dance'`` calls (counted inside the daily cap), running reservations included."""
    cfg = cfg or Settings.from_env()
    now = now or now_iso()
    start, end = day_window(now, cfg.tz)
    return ledger.sum_cost(conn, start, end, kind="dance") + ledger.reserved_running(conn, kind="dance")


def prewarm_spent_today(conn: sqlite3.Connection, cfg: Settings | None = None, now: str | None = None) -> float:
    cfg = cfg or Settings.from_env()
    now = now or now_iso()
    start, end = day_window(now, cfg.tz)
    return ledger.prewarm_cost(conn, start, end)


def calls_last_hour(conn: sqlite3.Connection, now: str, provider: str = "claude") -> int:
    """Calls of ``provider`` started in the last 60 minutes (each provider has its own hourly cap)."""
    return ledger.count_started(conn, to_iso(parse_iso(now) - timedelta(hours=1)), provider=provider)


def hourly_cap_for(cfg: Settings, provider: str) -> int:
    return int(cfg.ai_hourly_call_cap if provider == "claude" else getattr(cfg, "ai_fallback_hourly_call_cap", 40))


def event_once(conn: sqlite3.Connection, kind: str, since: str, detail: dict, *, now: str) -> bool:
    """Insert a ``system_events`` row of ``kind`` unless one was written since ``since``; True when inserted."""
    with db.maybe_tx(conn):
        exists = conn.execute("SELECT 1 FROM system_events WHERE kind = ? AND created_at >= ? LIMIT 1", (kind, since)).fetchone()
        if exists:
            return False
        conn.execute(
            "INSERT INTO system_events(kind, detail_json, created_at) VALUES (?, ?, ?)",
            (kind, json.dumps(detail, ensure_ascii=False, sort_keys=True), now),
        )
        return True


# -------------------------------------------------------------------------------------- the check
def can_spend(
    conn: sqlite3.Connection,
    kind: str,
    word_count: int,
    priority: int,
    now: str | datetime | None,
    *,
    cfg: Settings | None = None,
    provider: str = "claude",
) -> tuple[bool, str | None]:
    """``(ok, resumes_at_iso)`` — the CLAUDE_INTEGRATION §7 guards for one call of ``kind`` on ``provider`` (TASKS §I signature).

    Order: kill switch → the admin's global pause → the provider's own pause → the provider's hourly cap → monthly →
    daily → prewarm sub-cap → SVG sub-cap. ``cfg`` defaults to the current environment (the WP3 content-request route
    has no settings object at hand). Deferral is never failure: a ``False`` answer carries the instant at which the
    jobs may run again.
    """
    cfg = cfg or Settings.from_env()
    if isinstance(now, datetime):
        now = to_iso(now)
    now = now or now_iso()
    est = estimate(kind, word_count, provider)
    if not ai_enabled(conn, cfg):
        return False, to_iso(parse_iso(now) + DISABLED_WAIT)
    paused = global_paused_until(conn, now)
    if paused is not None:
        return False, paused
    paused = provider_paused_until(conn, provider, now)
    if paused is not None:
        return False, paused
    if calls_last_hour(conn, now, provider) >= hourly_cap_for(cfg, provider):
        return False, next_hour_resume(now)
    day_begin, _ = day_window(now, cfg.tz)
    month_begin, _ = month_window(now, cfg.tz)
    month_spent = spent_month(conn, cfg, now)
    if month_spent + est > cfg.ai_monthly_budget_usd:
        event_once(conn, EVENT_MONTHLY, day_begin, {"spent_usd": round(month_spent, 4), "cap_usd": cfg.ai_monthly_budget_usd, "kind": kind}, now=now)
        return False, next_month_resume(now, cfg.tz)
    today = spent_today(conn, cfg, now)
    if today + est > cfg.ai_daily_budget_usd:
        event_once(conn, EVENT_DAILY, day_begin, {"spent_usd": round(today, 4), "cap_usd": cfg.ai_daily_budget_usd, "kind": kind}, now=now)
        return False, next_day_resume(now, cfg.tz)
    if int(priority) >= PREWARM_PRIORITY:
        # §7: prewarm additionally requires prewarm_spent_today < sub-cap and spent_today < 0.5 × daily cap
        if today >= PREWARM_DAILY_SHARE * cfg.ai_daily_budget_usd:
            return False, next_day_resume(now, cfg.tz)
        if prewarm_spent_today(conn, cfg, now) >= cfg.ai_prewarm_daily_budget_usd:
            return False, next_day_resume(now, cfg.tz)
    if kind == "svg":
        # §7: generate_svg additionally requires SUM(cost_usd) of today's svg calls < sub-cap (0.50 ≈ 35–40 cards at the measured
        # $0.0124/call — $0.0140 per delivered card, 34 live calls on 2026-11-05; ESTIMATES['svg'] stays 0.03 as the reservation margin)
        svg_spent = svg_spent_today(conn, cfg, now)
        if svg_spent >= cfg.ai_svg_daily_budget_usd:
            event_once(conn, EVENT_SVG, day_begin, {"spent_usd": round(svg_spent, 4), "cap_usd": cfg.ai_svg_daily_budget_usd}, now=now)
            return False, next_day_resume(now, cfg.tz)
    if kind == "dance":
        # §7: generate_dance additionally requires today's dance spend < its sub-cap (0.50 ≈ 140 words a day at ≈ $0.0035 per word;
        # the 小学 backfill raises it for one evening, docs/releases/2026-11-word-dance-p2.md)
        dance_spent = dance_spent_today(conn, cfg, now)
        if dance_spent >= cfg.ai_dance_daily_budget_usd:
            event_once(conn, EVENT_DANCE, day_begin, {"spent_usd": round(dance_spent, 4), "cap_usd": cfg.ai_dance_daily_budget_usd}, now=now)
            return False, next_day_resume(now, cfg.tz)
    return True, None


@dataclass
class Reservation:
    """Outcome of :func:`reserve`: a ledger row id when the call may proceed, else when the jobs may run again."""

    call_id: int | None
    resumes_at: str | None
    reserved_usd: float

    @property
    def ok(self) -> bool:
        return self.call_id is not None


def reserve(
    conn: sqlite3.Connection,
    *,
    kind: str,
    word_count: int,
    priority: int,
    now: str,
    cfg: Settings,
    flag_tier: int,
    job_ids: Sequence[int],
    max_budget_usd: float | None = None,
    model_requested: str | None = None,
    provider: str = "claude",
) -> Reservation:
    """Atomically check :func:`can_spend` and insert the ``running`` ledger row (the reservation) for ``provider``.

    The check and the insert run inside one ``BEGIN IMMEDIATE``, so a concurrent reservation on another connection
    waits for this one and then sees its ``reserved_usd`` — two callers can never both squeeze under the cap.
    """
    est = estimate(kind, word_count, provider)
    with db.maybe_tx(conn):
        ok, resumes_at = can_spend(conn, kind, word_count, priority, now, cfg=cfg, provider=provider)
        if not ok:
            return Reservation(None, resumes_at, est)
        call_id = ledger.insert_call(
            conn,
            kind=kind,
            model_requested=model_requested or (cfg.ai_model if provider == "claude" else getattr(cfg, "ai_fallback_model", "") or "fallback"),
            flag_tier=int(flag_tier),
            word_count=word_count,
            job_ids=list(job_ids),
            max_budget_usd=budget_for(cfg, kind) if max_budget_usd is None else float(max_budget_usd),
            reserved_usd=est,
            now=now,
            provider=provider,
        )
    return Reservation(call_id, None, est)


# ----------------------------------------------------------------------------------- admin summary
def fallback_available(conn: sqlite3.Connection) -> bool | None:
    """``kv.ai.fallback.available`` as a bool: None when never probed / unknown (key absent), False for the sticky ``'0'``
    mark a failed probe or a ``spawn_error`` / ``not_found:`` wrote, True otherwise (CLAUDE_INTEGRATION §10.6)."""
    value = db.kv_get(conn, "ai.fallback.available")
    if value is None:
        return None
    return value != "0"


def spend_summary(conn: sqlite3.Connection, cfg: Settings | None = None, now: str | None = None) -> dict:
    """The ``AdminOverview.ai`` / ``AiCallsPage`` numbers (today, month, svg today, calls today, 7-day cost per word).

    ``paused_until`` keeps its legacy meaning (the CLI's automatic pause or the admin's global pause, whichever ends
    later — ``diag`` and the ``claude_cli``-mode overview depend on it); ``manual_paused_until`` is the admin's own
    pause alone (``kv.ai.paused_until`` while in the future), so the AI tab can tell 「已暂停 / 恢复 AI」 from "the CLI is
    auto-paused while the fallback serves"; ``fallback_available`` surfaces the sticky ``'0'`` mark (§10.6).
    """
    cfg = cfg or Settings.from_env()
    now = now or now_iso()
    d0, d1 = day_window(now, cfg.tz)
    m0, m1 = month_window(now, cfg.tz)
    week_ago = to_iso(parse_iso(now) - timedelta(days=7))
    active = db.kv_get(conn, "ai.active_provider", "claude")
    return {
        "enabled": ai_enabled(conn, cfg),
        "paused_until": paused_until(conn, now),
        "manual_paused_until": global_paused_until(conn, now),
        "flag_tier": 1 if db.kv_get(conn, "claude.flag_tier", "0") == "1" else 0,
        "active_provider": active if active in PROVIDERS else "claude",
        "fallback_configured": bool(getattr(cfg, "fallback_configured", False)),
        "fallback_available": fallback_available(conn),
        "fallback_paused_until": provider_paused_until(conn, "fallback", now),
        "fallback_calls_today": ledger.count_started(conn, d0, d1, provider="fallback"),
        "today_usd": round(ledger.sum_cost(conn, d0, d1), 6),
        "month_usd": round(ledger.sum_cost(conn, m0, m1), 6),
        "daily_budget_usd": cfg.ai_daily_budget_usd,
        "monthly_budget_usd": cfg.ai_monthly_budget_usd,
        "svg_today_usd": round(ledger.sum_cost(conn, d0, d1, kind="svg"), 6),
        "svg_daily_budget_usd": cfg.ai_svg_daily_budget_usd,
        "dance_today_usd": round(ledger.sum_cost(conn, d0, d1, kind="dance"), 6),
        "dance_daily_budget_usd": cfg.ai_dance_daily_budget_usd,
        "calls_today": ledger.count_started(conn, d0, d1),
        "avg_cost_per_word_7d": ledger.avg_cost_per_word(conn, week_ago, to_iso(parse_iso(now) + timedelta(seconds=1))),
        "last_error": ledger.last_error(conn),
    }


__all__ = [
    "ESTIMATES",
    "KV_CLAUDE_PAUSE",
    "KV_FALLBACK_PAUSE",
    "KV_GLOBAL_PAUSE",
    "PAUSE_KEYS",
    "PROVIDERS",
    "Reservation",
    "ai_enabled",
    "budget_for",
    "calls_last_hour",
    "can_spend",
    "day_window",
    "estimate",
    "event_once",
    "fallback_available",
    "global_paused_until",
    "hourly_cap_for",
    "month_window",
    "next_day_resume",
    "next_hour_resume",
    "next_month_resume",
    "paused_until",
    "prewarm_spent_today",
    "provider_paused_until",
    "reserve",
    "set_paused_until",
    "spend_summary",
    "spent_month",
    "spent_today",
    "svg_spent_today",
    "timeout_for",
]
