"""Install-time probe — ``wd claude-check`` / ``wd ai-check`` and ``POST /api/admin/ai/probe`` (CLAUDE_INTEGRATION §2, §10).

``probe_v1.json`` exercises every JSON-Schema keyword the production schemas rely on, including ``enum`` (integer
and string) and a bounded array. Success ⇔ exit 0 and ``structured_output`` **exactly equal** to
``{"ok":true,"echo":"word-dance","level":2,"mode":"b","tags":["probe"]}``.

1. tier 1 → success ⇒ ``kv.claude.flag_tier='1'``, ``kv.claude.available='1'``
2. else tier 0 → success ⇒ ``flag_tier='0'``, ``available='1'`` + ``system_events('claude_probe_fallback')``
3. else ⇒ ``available='0'`` + ``system_events('claude_unavailable')``; the command exits 2.

Each attempt writes an ``ai_calls`` row (kind ``probe``, ``--max-budget-usd 0.05``, timeout 60 s).

The automatic fail-back probe (``ClaudeWorker.housekeeping`` → ``failover.maybe_probe``, §10.6) calls :func:`check` with
``tier=`` the recorded ``kv.claude.flag_tier``: ONE attempt at that tier, ``available`` / ``last_probe_at`` /
``claude_unavailable`` as above, ``flag_tier`` never rewritten (AI_FALLBACK_MODEL §4.5 「切换期间固定一个 tier」 — a
transient 529 / timeout on a tier-1 attempt during an outage must not downgrade every later production call to the
un-hardened tier-0 argv). Only the untiered form — ``wd claude-check``, the admin button — may change the tier.

:func:`check_fallback` is the tier-less twin for the fallback provider (``wd ai-check --provider fallback``, the admin
button 「探测备用」): one ``probe_v1`` call through ``ai/providers/openai_http.py``, the same exact-match rule, recorded in
``kv.ai.fallback.available`` / ``last_probe_at`` / ``model_seen`` (§10.6); ``available='0'`` is written for a
configuration / endpoint failure only (``spawn_error`` / ``not_found:``), a transient failure keeps the previous value.

Both probes are pure recorders. The entry points — :func:`_run_check` and ``routers/admin_ops.ai_probe`` — report a success
to ``failover.record_success(kind="probe")`` (§10.6): the provider's streaks end, its automatic pause is lifted in every
mode and claude fails back while the fallback is active; ``failover.maybe_probe`` does the same for the automatic probe.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any, Callable

from .. import db
from ..clock import now_iso
from ..config import ConfigError, Settings, ensure_dirs
from ..interfaces import ClaudeResult
from . import budget, failover, ledger, runner

log = logging.getLogger("wd.ai.probe")

PROBE_PROMPT = (
    "Reply with ok set to true, echo set to the exact text word-dance, level set to 2, mode set to b, "
    "and tags set to a one-element list containing probe."
)
PROBE_SYSTEM_PROMPT = (
    "You are the installation probe of word-Dance, a vocabulary app. Follow the user's instruction exactly and answer "
    "only through the JSON schema you were given; write nothing outside it."
)
EXPECTED: dict[str, Any] = {"ok": True, "echo": "word-dance", "level": 2, "mode": "b", "tags": ["probe"]}
PROBE_BUDGET_USD = 0.05
PROBE_TIMEOUT_S = 60
VERSION_TIMEOUT_S = 5
VERSION_RE = re.compile(r"\d+\.\d+\.\d+[\w.-]*")

Run = Callable[..., ClaudeResult]


@dataclass
class ProbeResult:
    ok: bool
    flag_tier: int
    cost_usd: float
    duration_ms: int
    model_used: str | None
    error: str | None
    call_ids: list[int] = field(default_factory=list)
    fallback: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "flag_tier": self.flag_tier,
            "cost_usd": round(self.cost_usd, 6),
            "duration_ms": self.duration_ms,
            "model_used": self.model_used,
            "error": self.error,
        }


def _attempt(conn: sqlite3.Connection, cfg: Settings, tier: str, *, now: str, run: Run) -> ClaudeResult:
    return run(
        conn,
        kind="probe",
        system_prompt=PROBE_SYSTEM_PROMPT,
        user_prompt=PROBE_PROMPT,
        schema=runner.load_schema("probe_v1"),
        max_budget_usd=PROBE_BUDGET_USD,
        timeout_s=PROBE_TIMEOUT_S,
        word_count=1,
        job_ids=[],
        cfg=cfg,
        now=now,
        tier=tier,
        fallback_on_usage_error=False,
    )


def _matches(result: ClaudeResult) -> bool:
    return result.ok and result.structured == EXPECTED


def _duration(conn: sqlite3.Connection, call_ids: list[int]) -> int:
    total = 0
    for cid in call_ids:
        row = ledger.get_call(conn, cid)
        if row and row.get("duration_ms") is not None:
            total += int(row["duration_ms"])
    return total


def _excerpt(conn: sqlite3.Connection, result: ClaudeResult) -> dict[str, Any]:
    row = ledger.get_call(conn, result.call_id) or {}
    return {"exit_code": row.get("exit_code"), "status": result.status, "stderr_excerpt": (row.get("error") or result.error or "")[:300]}


def _mismatch_error(result: ClaudeResult) -> str:
    if result.ok:
        return f"structured_output mismatch: {result.structured!r}"
    return result.error or result.status


def check(
    conn: sqlite3.Connection,
    cfg: Settings,
    *,
    now: str | None = None,
    run: Run = runner.run_claude,
    tier: str | None = None,
) -> ProbeResult:
    """Run the §2 probe, record availability (and, untiered, the tier) in ``kv`` and return the outcome.

    Untiered (``wd claude-check``, ``POST /api/admin/ai/probe``): tier 1, then tier 0 — the install-time rule of the module
    docstring — and the successful tier becomes ``kv.claude.flag_tier``. ``tier`` (``'1'`` / ``'0'``) pins the probe to
    ONE attempt at that tier and never rewrites ``claude.flag_tier``: the fail-back probe passes the recorded
    ``runner.flag_tier`` (CLAUDE_INTEGRATION §10.6, AI_FALLBACK_MODEL §4.5). Both forms write ``claude.available``
    (``'1'`` / ``'0'``) and ``claude.last_probe_at`` and, on failure, ``system_events('claude_unavailable')``.
    """
    now = now or now_iso()
    if tier is not None:
        return _check_pinned(conn, cfg, "1" if str(tier) == "1" else "0", now=now, run=run)
    tier1 = _attempt(conn, cfg, "1", now=now, run=run)
    call_ids = [tier1.call_id]
    cost = tier1.cost_usd
    if _matches(tier1):
        with db.tx(conn):
            db.kv_set(conn, "claude.flag_tier", "1", now=now)
            db.kv_set(conn, "claude.available", "1", now=now)
            db.kv_set(conn, "claude.last_probe_at", now, now=now)
        log.info("claude probe ok at tier 1", extra={"event": "claude_probe", "cost_usd": cost})
        return ProbeResult(True, 1, cost, _duration(conn, call_ids), tier1.model_used, None, call_ids)
    tier0 = _attempt(conn, cfg, "0", now=now, run=run)
    call_ids.append(tier0.call_id)
    cost += tier0.cost_usd
    if _matches(tier0):
        with db.tx(conn):
            db.kv_set(conn, "claude.flag_tier", "0", now=now)
            db.kv_set(conn, "claude.available", "1", now=now)
            db.kv_set(conn, "claude.last_probe_at", now, now=now)
            conn.execute(
                "INSERT INTO system_events(kind, detail_json, created_at) VALUES ('claude_probe_fallback', ?, ?)",
                (db_json({"tier1": _excerpt(conn, tier1)}), now),
            )
        log.warning("claude probe fell back to tier 0: %s", _mismatch_error(tier1), extra={"event": "claude_probe_fallback", "cost_usd": cost})
        return ProbeResult(True, 0, cost, _duration(conn, call_ids), tier0.model_used, None, call_ids, fallback=True)
    with db.tx(conn):
        db.kv_set(conn, "claude.available", "0", now=now)
        db.kv_set(conn, "claude.last_probe_at", now, now=now)
        conn.execute(
            "INSERT INTO system_events(kind, detail_json, created_at) VALUES ('claude_unavailable', ?, ?)",
            (db_json({"tier1": _excerpt(conn, tier1), "tier0": _excerpt(conn, tier0)}), now),
        )
    error = f"tier 1: {_mismatch_error(tier1)}; tier 0: {_mismatch_error(tier0)}"
    log.error("claude probe failed: %s", error, extra={"event": "claude_unavailable", "cost_usd": cost})
    return ProbeResult(False, 1 if db.kv_get(conn, "claude.flag_tier", "0") == "1" else 0, cost, _duration(conn, call_ids), tier0.model_used or tier1.model_used, error[:1000], call_ids)


def _check_pinned(conn: sqlite3.Connection, cfg: Settings, tier: str, *, now: str, run: Run) -> ProbeResult:
    """One attempt at ``tier`` — the fail-back probe's form (§10.6): ``claude.available`` / ``last_probe_at`` and, on
    failure, ``claude_unavailable`` are written exactly like the two-tier probe's; ``claude.flag_tier`` is left alone."""
    result = _attempt(conn, cfg, tier, now=now, run=run)
    call_ids = [result.call_id]
    ok = _matches(result)
    with db.tx(conn):
        db.kv_set(conn, "claude.available", "1" if ok else "0", now=now)
        db.kv_set(conn, "claude.last_probe_at", now, now=now)
        if not ok:
            conn.execute(
                "INSERT INTO system_events(kind, detail_json, created_at) VALUES ('claude_unavailable', ?, ?)",
                (db_json({f"tier{tier}": _excerpt(conn, result), "pinned_tier": int(tier)}), now),
            )
    if ok:
        log.info("claude probe ok at tier %s (pinned)", tier, extra={"event": "claude_probe", "cost_usd": result.cost_usd})
        return ProbeResult(True, int(tier), result.cost_usd, _duration(conn, call_ids), result.model_used, None, call_ids)
    error = f"tier {tier}: {_mismatch_error(result)}"
    log.error("claude probe failed (pinned to tier %s): %s", tier, error, extra={"event": "claude_unavailable", "cost_usd": result.cost_usd})
    return ProbeResult(False, int(tier), result.cost_usd, _duration(conn, call_ids), result.model_used, error[:1000], call_ids)


def check_fallback(conn: sqlite3.Connection, cfg: Settings, *, now: str | None = None, run: Any = None) -> ProbeResult:
    """One ``probe_v1`` call on the fallback provider (CLAUDE_INTEGRATION §10.6); ``flag_tier`` is always 0 (no tiers on HTTP).

    Always records ``kv.ai.fallback.last_probe_at``; on success ``ai.fallback.available='1'`` and ``ai.fallback.model_seen``;
    on every failure a ``fallback_unavailable`` event. ``ai.fallback.available='0'`` — the sticky mark that makes
    ``failover.fallback_eligible`` refuse the provider until a probe or call succeeds — is written only for a configuration /
    endpoint failure: status ``spawn_error`` (base URL / model / key missing or unusable) or an error starting with
    ``not_found:`` (404, an unknown model id). A transient failure (5xx, timeout, network, one off-schema answer) keeps the
    previous value: one vendor hiccup during a manual probe must not park every learner gate on 503 ``ai_disabled`` for good.
    """
    now = now or now_iso()
    if not cfg.fallback_configured:
        return ProbeResult(False, 0, 0.0, 0, None, "fallback provider not configured (WD_AI_FALLBACK_KIND / _BASE_URL / _MODEL / _API_KEY)", [])
    if run is None:
        from .providers import openai_http

        run = openai_http.run_openai
    result: ClaudeResult = run(
        conn,
        kind="probe",
        system_prompt=PROBE_SYSTEM_PROMPT,
        user_prompt=PROBE_PROMPT,
        schema=runner.load_schema("probe_v1"),
        timeout_s=budget.timeout_for(cfg, "probe", "fallback"),
        word_count=1,
        job_ids=[],
        cfg=cfg,
        now=now,
    )
    ok = _matches(result)
    configuration_failure = not ok and (result.status == "spawn_error" or str(result.error or "").lstrip().startswith("not_found:"))
    with db.tx(conn):
        if ok:
            db.kv_set(conn, "ai.fallback.available", "1", now=now)
        elif configuration_failure:
            db.kv_set(conn, "ai.fallback.available", "0", now=now)
        db.kv_set(conn, "ai.fallback.last_probe_at", now, now=now)
        if ok and result.model_used:
            db.kv_set(conn, "ai.fallback.model_seen", str(result.model_used), now=now)
        if not ok:
            conn.execute(
                "INSERT INTO system_events(kind, detail_json, created_at) VALUES ('fallback_unavailable', ?, ?)",
                (db_json({"probe": _excerpt(conn, result), "model": cfg.ai_fallback_model, "marked_unavailable": configuration_failure}), now),
            )
    if ok:
        log.info("fallback probe ok (%s)", result.model_used, extra={"event": "fallback_probe", "cost_usd": result.cost_usd})
        return ProbeResult(True, 0, result.cost_usd, _duration(conn, [result.call_id]), result.model_used, None, [result.call_id])
    error = _mismatch_error(result)
    log.error("fallback probe failed: %s", error, extra={"event": "fallback_unavailable", "cost_usd": result.cost_usd})
    return ProbeResult(False, 0, result.cost_usd, _duration(conn, [result.call_id]), result.model_used, error[:1000], [result.call_id])


def db_json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def record_version(conn: sqlite3.Connection, cfg: Settings, *, now: str | None = None) -> str | None:
    """Best-effort ``<claude_bin> --version`` (no API call) stored as ``kv.claude.version`` for the admin health page."""
    now = now or now_iso()
    try:
        cp = subprocess.run(
            [cfg.claude_bin, "--version"],
            cwd=str(cfg.claude_cwd) if cfg.claude_cwd.is_dir() else None,
            env=runner.claude_env(cfg),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=VERSION_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if cp.returncode != 0:
        return None
    m = VERSION_RE.search((cp.stdout or "") + " " + (cp.stderr or ""))
    if not m:
        return None
    version = m.group(0)
    with db.tx(conn):
        db.kv_set(conn, "claude.version", version, now=now)
    return version


def cmd_claude_check(args: argparse.Namespace) -> int:
    return _run_check(getattr(args, "provider", "claude") or "claude")


def _run_check(provider: str) -> int:
    """``wd claude-check`` / ``wd ai-check --provider claude|fallback``: run the probe, print the verdict, exit 0 or 2.

    A success is reported to :func:`failover.record_success` exactly like the admin button's (CLAUDE_INTEGRATION §10.6):
    the provider's streaks end, its automatic pause is lifted in every mode — the ``balance:`` / ``quota:`` banners send the
    operator here ("…运行 wd claude-check") — and claude fails back while the fallback is active.
    """
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
        if provider == "fallback":
            result = check_fallback(conn, cfg, now=now)
            if result.ok:
                failover.record_success(conn, cfg, provider=failover.FALLBACK, kind="probe", model_used=result.model_used, now=now, probe_call_ids=result.call_ids)
                print(f"fallback check OK: model {result.model_used or cfg.ai_fallback_model}, cost ${result.cost_usd:.4f}, {result.duration_ms} ms")
                return 0
            print(f"fallback check FAILED: {result.error} (cost ${result.cost_usd:.4f})", file=sys.stderr)
            print("WARN: fallback check failed — verify WD_AI_FALLBACK_BASE_URL / _MODEL / the key file, then `wd ai-check --provider fallback`", file=sys.stderr)
            return 2
        version = record_version(conn, cfg, now=now)
        result = check(conn, cfg, now=now)
        if result.ok:
            failed_back = failover.record_success(conn, cfg, provider=failover.CLAUDE, kind="probe", model_used=result.model_used, now=now, probe_call_ids=result.call_ids)
            print(
                f"claude check OK: tier {result.flag_tier}{' (fell back from tier 1)' if result.fallback else ''}, cost ${result.cost_usd:.4f}, {result.duration_ms} ms, model {result.model_used or '?'}"
                + (f", claude {version}" if version else "")
                + (" — failed back to claude from the fallback provider" if failed_back else "")
            )
            return 0
        print(f"claude check FAILED: {result.error} (cost ${result.cost_usd:.4f})", file=sys.stderr)
        print("WARN: claude check failed — run `claude` once as sqin to log in, then `wd claude-check`", file=sys.stderr)
        return 2
    finally:
        conn.close()


def cmd_ai_check(args: argparse.Namespace) -> int:
    return _run_check(args.provider)


def register_cli(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("claude-check", help="probe the claude CLI (≤ $0.05): records kv.claude.flag_tier / available")
    p.set_defaults(func=cmd_claude_check)
    q = sub.add_parser("ai-check", help="probe one AI provider: claude (= claude-check) or the configured fallback (records kv.ai.fallback.available)")
    q.add_argument("--provider", choices=("claude", "fallback"), default="claude")
    q.set_defaults(func=cmd_ai_check)


__all__ = ["EXPECTED", "PROBE_BUDGET_USD", "PROBE_PROMPT", "PROBE_SYSTEM_PROMPT", "ProbeResult", "check", "check_fallback", "record_version", "register_cli"]
