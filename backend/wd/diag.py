"""Operator diagnostics (DEPLOY §6/§9, WP5): ``wd check [db|claude|smtp|providers|all] [--db PATH]``, ``wd logs --tail N``,
``wd stats``.

``check`` exits 1 when any selected check fails (0 otherwise); it never spends money (the claude check inspects the
binary and the recorded probe state — ``wd claude-check`` is the paid probe). ``logs`` prints the in-process ring
buffer (empty in a fresh CLI process) or, when ``WD_LOG_FILE`` is set, the tail of that file; the running service's
lines live in ``journalctl -u word-dance``.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sqlite3
import sys
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import db
from .clock import now_iso
from .config import ConfigError, Settings
from .logging_setup import RING

CHECK_TARGETS: tuple[str, ...] = ("db", "claude", "smtp", "providers", "all")
SMTP_CONNECT_TIMEOUT_S = 3.0


@dataclass
class CheckResult:
    name: str
    ok: bool
    lines: list[str] = field(default_factory=list)

    def render(self) -> str:
        head = f"[{'ok' if self.ok else 'FAIL'}] {self.name}"
        return "\n".join([head, *(f"    {line}" for line in self.lines)])


def _settings() -> Settings | None:
    try:
        return Settings.from_env()
    except ConfigError as e:
        print(f"wd: configuration error: {e}", file=sys.stderr)
        return None


# ------------------------------------------------------------------------------------------ checks
def check_db(cfg: Settings, db_path: Path | None = None) -> CheckResult:
    path = Path(db_path) if db_path else cfg.db_path
    lines: list[str] = [f"path: {path}"]
    if not path.is_file():
        return CheckResult("db", False, [*lines, "database file does not exist (run `wd migrate`)"])
    try:
        conn = db.connect(path)
    except sqlite3.Error as e:
        return CheckResult("db", False, [*lines, f"cannot open: {e}"])
    try:
        quick = str(conn.execute("PRAGMA quick_check").fetchone()[0])
        version = db.current_version(conn)
        pending = db.pending_migrations(conn)
        tables = len(db.table_names(conn))
        lines += [f"quick_check: {quick}", f"schema version: {version} ({tables} tables, {len(pending)} pending migration(s))"]
        ok = quick == "ok" and version >= 1 and not pending
        for key in ("seed_version", "last_tick_at", "worker_lease", "backup.last"):
            value = db.kv_get(conn, key)
            lines.append(f"kv.{key}: {value if value is not None else '-'}")
        return CheckResult("db", ok, lines)
    except sqlite3.Error as e:
        return CheckResult("db", False, [*lines, f"query failed: {e}"])
    finally:
        conn.close()


def check_claude(cfg: Settings, conn: sqlite3.Connection | None) -> CheckResult:
    lines = [f"binary: {cfg.claude_bin}"]
    exists = os.path.isfile(cfg.claude_bin) and os.access(cfg.claude_bin, os.X_OK)
    lines.append("executable: yes" if exists else "executable: NO")
    lines.append(f"cwd: {cfg.claude_cwd} ({'exists' if cfg.claude_cwd.is_dir() else 'missing'})")
    ok = exists and cfg.ai_enabled
    lines.append(f"WD_AI_ENABLED: {'1' if cfg.ai_enabled else '0'}")
    if conn is not None:
        available = db.kv_get(conn, "claude.available")
        tier = db.kv_get(conn, "claude.flag_tier", "0")
        last = db.kv_get(conn, "claude.last_probe_at")
        paused = db.kv_get(conn, "claude.paused_until")
        enabled = db.kv_get(conn, "claude.enabled")
        version = db.kv_get(conn, "claude.version")
        lines += [
            f"probe: available={available if available is not None else 'never probed'} tier={tier} last_probe_at={last or '-'}" + (f" version={version}" if version else ""),
            f"kv.claude.enabled: {enabled if enabled is not None else '1 (default)'}",
            f"paused_until: {paused or '-'}",
        ]
        if available == "0":
            ok = False
            lines.append("hint: run `claude` once as sqin to log in, then `wd claude-check`")
        if enabled == "0":
            lines.append("hint: AI is paused by the admin (POST /api/admin/ai/pause {paused:false} to resume)")
    else:
        lines.append("probe state: (no database)")
    return CheckResult("claude", ok, lines)


def check_smtp(cfg: Settings, connect: Callable[[str, int, float], None] | None = None) -> CheckResult:
    if not cfg.email_configured:
        return CheckResult("smtp", True, ["not configured (WD_SMTP_HOST / WD_SMTP_FROM empty) — e-mail channel off"])
    lines = [f"host: {cfg.smtp_host}:{cfg.smtp_port} ({cfg.smtp_tls})", f"from: {cfg.smtp_from}", f"auth: {'user set' if cfg.smtp_user else 'anonymous'}"]

    def _connect(host: str, port: int, timeout: float) -> None:
        with socket.create_connection((host, port), timeout=timeout):
            pass

    try:
        (connect or _connect)(cfg.smtp_host, cfg.smtp_port, SMTP_CONNECT_TIMEOUT_S)
    except OSError as e:
        return CheckResult("smtp", False, [*lines, f"TCP connect failed: {e}"])
    return CheckResult("smtp", True, [*lines, "TCP connect: ok"])


def check_providers(cfg: Settings, conn: sqlite3.Connection | None) -> CheckResult:
    lines = [f"images: {'enabled' if cfg.images_enabled else 'disabled'}", f"chain: {', '.join(cfg.image_providers) or '-'}", f"svg via claude: {'1' if cfg.svg_via_claude else '0'} (sub-cap ${cfg.ai_svg_daily_budget_usd:.2f}/day)"]
    ok = True
    if conn is not None:
        for provider in cfg.image_providers:
            row = conn.execute("SELECT cooldown_until, last_ok_at, last_error, consecutive_errors FROM provider_state WHERE provider = ?", (provider,)).fetchone()
            if row is None:
                lines.append(f"{provider}: no requests yet")
                continue
            cooldown = row["cooldown_until"]
            lines.append(f"{provider}: last_ok={row['last_ok_at'] or '-'} errors={row['consecutive_errors']} cooldown_until={cooldown or '-'}" + (f" last_error={row['last_error']}" if row["last_error"] else ""))
            if cooldown and cooldown > now_iso():
                ok = False
    return CheckResult("providers", ok, lines)


def run_checks(cfg: Settings, target: str, *, db_path: Path | None = None) -> list[CheckResult]:
    targets = ("db", "claude", "smtp", "providers") if target == "all" else (target,)
    results: list[CheckResult] = []
    conn: sqlite3.Connection | None = None
    path = Path(db_path) if db_path else cfg.db_path
    if path.is_file():
        try:
            conn = db.connect(path)
        except sqlite3.Error:
            conn = None
    try:
        for t in targets:
            if t == "db":
                results.append(check_db(cfg, db_path))
            elif t == "claude":
                results.append(check_claude(cfg, conn))
            elif t == "smtp":
                results.append(check_smtp(cfg))
            elif t == "providers":
                results.append(check_providers(cfg, conn))
    finally:
        if conn is not None:
            conn.close()
    return results


def cmd_check(args: argparse.Namespace) -> int:
    cfg = _settings()
    if cfg is None:
        return 2
    results = run_checks(cfg, args.target, db_path=Path(args.db) if args.db else None)
    for r in results:
        print(r.render())
    return 0 if all(r.ok for r in results) else 1


# ------------------------------------------------------------------------------------------- stats
def collect_stats(conn: sqlite3.Connection, cfg: Settings, now: str | None = None) -> dict:
    from .ai import budget

    now = now or now_iso()
    words_row = conn.execute(
        "SELECT COUNT(*), SUM(content_state = 'ready'), SUM(image_state = 'ready'), SUM(source = 'user'), SUM(is_valid_english IS NULL) FROM words WHERE merged_into_word_id IS NULL"
    ).fetchone()
    jobs = {str(r[0]): int(r[1]) for r in conn.execute("SELECT status, COUNT(*) FROM jobs GROUP BY status ORDER BY status")}
    live_by_type = {str(r[0]): int(r[1]) for r in conn.execute("SELECT type, COUNT(*) FROM jobs WHERE status IN ('queued','running') GROUP BY type ORDER BY type")}
    spend = budget.spend_summary(conn, cfg, now)
    return {
        "users": int(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]),
        "bank_entries": int(conn.execute("SELECT COUNT(*) FROM user_words WHERE state IN ('new','learning')").fetchone()[0]),
        "words": {
            "total": int(words_row[0] or 0),
            "with_content": int(words_row[1] or 0),
            "with_image": int(words_row[2] or 0),
            "user_added": int(words_row[3] or 0),
            "pending_validation": int(words_row[4] or 0),
        },
        "batches": int(conn.execute("SELECT COUNT(*) FROM push_batches").fetchone()[0]),
        "jobs": jobs,
        "jobs_live_by_type": live_by_type,
        "ai": {k: spend[k] for k in ("enabled", "paused_until", "flag_tier", "today_usd", "month_usd", "svg_today_usd", "calls_today", "avg_cost_per_word_7d", "last_error")},
        "suggestions_open": int(conn.execute("SELECT COUNT(*) FROM bank_suggestions WHERE status = 'open'").fetchone()[0]),
    }


def cmd_stats(args: argparse.Namespace) -> int:
    cfg = _settings()
    if cfg is None:
        return 2
    if not cfg.db_path.is_file():
        print(f"wd stats: database {cfg.db_path} does not exist (run `wd migrate`)", file=sys.stderr)
        return 1
    conn = db.connect(cfg.db_path)
    try:
        stats = collect_stats(conn, cfg)
    finally:
        conn.close()
    if args.json:
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        return 0
    print(f"users: {stats['users']}   bank entries: {stats['bank_entries']}   batches: {stats['batches']}   open suggestions: {stats['suggestions_open']}")
    w = stats["words"]
    print(f"words: {w['total']} total, {w['with_content']} with content, {w['with_image']} with image, {w['user_added']} user-added, {w['pending_validation']} pending validation")
    print("jobs: " + (", ".join(f"{k} {v}" for k, v in stats["jobs"].items()) or "none") + ("; live by type: " + ", ".join(f"{k} {v}" for k, v in stats["jobs_live_by_type"].items()) if stats["jobs_live_by_type"] else ""))
    ai = stats["ai"]
    avg = "-" if ai["avg_cost_per_word_7d"] is None else f"${ai['avg_cost_per_word_7d']:.4f}"
    print(f"ai: {'enabled' if ai['enabled'] else 'DISABLED'} tier {ai['flag_tier']}; today ${ai['today_usd']:.4f} (svg ${ai['svg_today_usd']:.4f}), month ${ai['month_usd']:.4f}, calls today {ai['calls_today']}, 7d $/word {avg}" + (f"; paused until {ai['paused_until']}" if ai["paused_until"] else "") + (f"; last error: {ai['last_error']}" if ai["last_error"] else ""))
    return 0


# -------------------------------------------------------------------------------------------- logs
def tail_lines(cfg: Settings, n: int) -> list[str]:
    """The last ``n`` log lines: the in-process ring buffer, else the tail of ``WD_LOG_FILE`` when configured."""
    if RING:
        return list(RING)[-n:]
    if cfg.log_file and Path(cfg.log_file).is_file():
        with open(cfg.log_file, "r", encoding="utf-8", errors="replace") as f:
            return [line.rstrip("\n") for line in deque(f, maxlen=n)]
    return []


def cmd_logs(args: argparse.Namespace) -> int:
    cfg = _settings()
    if cfg is None:
        return 2
    n = max(1, int(args.tail))
    lines = tail_lines(cfg, n)
    if not lines:
        print("no log lines in this process" + (f" and {cfg.log_file} is empty or missing" if cfg.log_file else " (set WD_LOG_FILE for a file tail; the service logs to journalctl -u word-dance)"))
        return 0
    for line in lines:
        print(line)
    return 0


def register_cli(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("check", help="health checks: db | claude | smtp | providers | all (exit 1 on failure)")
    p.add_argument("target", nargs="?", choices=CHECK_TARGETS, default="all")
    p.add_argument("--db", default=None, help="check this database file instead of WD_DB_PATH (restore drills)")
    p.set_defaults(func=cmd_check)
    p = sub.add_parser("stats", help="print counts: users, words, bank, jobs, AI spend")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.set_defaults(func=cmd_stats)
    p = sub.add_parser("logs", help="print the last N lines of the in-memory log ring (or WD_LOG_FILE)")
    p.add_argument("--tail", type=int, default=200)
    p.set_defaults(func=cmd_logs)


__all__ = ["CheckResult", "check_claude", "check_db", "check_providers", "check_smtp", "collect_stats", "register_cli", "run_checks", "tail_lines"]
