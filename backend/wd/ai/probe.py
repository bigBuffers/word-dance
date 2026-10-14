"""Install-time probe — ``wd claude-check`` and ``POST /api/admin/ai/probe`` (CLAUDE_INTEGRATION §2).

``probe_v1.json`` exercises every JSON-Schema keyword the production schemas rely on, including ``enum`` (integer
and string) and a bounded array. Success ⇔ exit 0 and ``structured_output`` **exactly equal** to
``{"ok":true,"echo":"word-dance","level":2,"mode":"b","tags":["probe"]}``.

1. tier 1 → success ⇒ ``kv.claude.flag_tier='1'``, ``kv.claude.available='1'``
2. else tier 0 → success ⇒ ``flag_tier='0'``, ``available='1'`` + ``system_events('claude_probe_fallback')``
3. else ⇒ ``available='0'`` + ``system_events('claude_unavailable')``; the command exits 2.

Each attempt writes an ``ai_calls`` row (kind ``probe``, ``--max-budget-usd 0.05``, timeout 60 s).
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
from . import ledger, runner

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


def check(conn: sqlite3.Connection, cfg: Settings, *, now: str | None = None, run: Run = runner.run_claude) -> ProbeResult:
    """Run the §2 probe (tier 1, then tier 0), record the tier and availability in ``kv`` and return the outcome."""
    now = now or now_iso()
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
    try:
        cfg = Settings.from_env()
    except ConfigError as e:
        print(f"wd: configuration error: {e}", file=sys.stderr)
        return 2
    ensure_dirs(cfg)
    conn = db.connect(cfg.db_path)
    try:
        db.run_migrations(conn, pre_hook=db.backup_pre_hook())
        version = record_version(conn, cfg)
        result = check(conn, cfg)
        if result.ok:
            print(f"claude check OK: tier {result.flag_tier}{' (fell back from tier 1)' if result.fallback else ''}, cost ${result.cost_usd:.4f}, {result.duration_ms} ms, model {result.model_used or '?'}" + (f", claude {version}" if version else ""))
            return 0
        print(f"claude check FAILED: {result.error} (cost ${result.cost_usd:.4f})", file=sys.stderr)
        print("WARN: claude check failed — run `claude` once as sqin to log in, then `wd claude-check`", file=sys.stderr)
        return 2
    finally:
        conn.close()


def register_cli(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("claude-check", help="probe the claude CLI (≤ $0.05): records kv.claude.flag_tier / available")
    p.set_defaults(func=cmd_claude_check)


__all__ = ["EXPECTED", "PROBE_BUDGET_USD", "PROBE_PROMPT", "PROBE_SYSTEM_PROMPT", "ProbeResult", "check", "record_version", "register_cli"]
