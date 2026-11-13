"""Operator diagnostics (DEPLOY §6/§9, WP5): ``wd check [db|claude|smtp|providers|all] [--db PATH]``, ``wd logs --tail N``,
``wd stats``.

``check`` exits 1 when any selected check fails (0 otherwise); it never spends money (the claude check inspects the
binary and the recorded probe state — ``wd claude-check`` is the paid probe). ``logs`` prints the in-process ring
buffer (empty in a fresh CLI process) or, when ``WD_LOG_FILE`` is set, the tail of that file; the running service's
lines live in ``journalctl -u word-dance``.

From schema 0011 on, ``check db`` also verifies the stage-model data invariants (:data:`STAGE_INVARIANTS` plus the
seed-version check; DESIGN §3.1, PLAN §2.1 / §6 S6): one ``invariant <name>: ok | N violation(s)`` line each, any
violation flips the check to FAIL. They are the operator's post-migration / post-import gate (release notes
``docs/releases/2026-11-k12-stages.md``) and the same SQL ``scripts/rehearse_migration.py`` runs on a rehearsal copy.
From schema 0014 on (:data:`LEARN_ORDER_INVARIANTS_FROM_VERSION`) four learning-order lines follow —
``learn_rank_present`` / ``learn_order_current`` / ``learn_rank_matches_policy`` / ``calendar_words_in_xs``, rendered by
``services.learn_order.check_lines`` (docs/analysis/2026-11-06-learn-order/DESIGN.md §2.7; ``wd learn-order`` repairs the
first three) — and the kv block carries ``kv.learn_order.version`` and the rendered ``kv.learn_order.stats`` line before
``kv.backup.last``: eight ``invariant`` lines after an import (``docs/releases/2026-11-learn-order.md``).
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
from .schemas import STAGE_ORDER, stage_to_index

CHECK_TARGETS: tuple[str, ...] = ("db", "claude", "smtp", "providers", "all")
SMTP_CONNECT_TIMEOUT_S = 3.0

# Stage-model data invariants (PLAN §2.1 / §6 S6; stage-model SYNTHESIS §3.9, D-13 / D-22). Each query counts the rows that
# violate one rule, so 0 means ok. They only make sense from migration 0011 on (five flags, indexes 1..5), hence
# STAGE_INVARIANTS_FROM_VERSION. The SQL is rendered from schemas.STAGE_ORDER — the single home of the stage enum — and
# test_diag.py pins the rendered text to the literal of PLAN §6 S6, so a change to the enum shows up there first.
#
# * stage_min_consistent — stage_min is the index of the lowest set flag and NULL (课标外) when no flag is set; the seed
#   import and services/words / ecdict write both sides, this catches a hand edit or a future writer that forgets one.
# * xs_subset_zk — the national chain is cumulative by construction (xs ⊆ zk; zk ⊄ gk is deliberate and NOT checked).
# * stages_json_known — every code a user holds is a known stage; bank.user_settings_row falls back to the default with
#   a `stage_fallback` warning at request time, this makes the stale row visible before a user hits it. json_each is a
#   built-in only from SQLite 3.38 (older builds may lack the JSON functions): the query then fails and the line says
#   `query failed` — reported, never raised, and it does not flip the check (unverifiable ≠ violated).
_STAGE_MIN_CASE = " ".join(f"WHEN stage_{code}=1 THEN {stage_to_index(code)}" for code in STAGE_ORDER)
STAGE_INVARIANTS: tuple[tuple[str, str], ...] = (
    ("stage_min_consistent", f"SELECT COUNT(*) FROM words WHERE stage_min IS NOT (CASE {_STAGE_MIN_CASE} END)"),
    ("xs_subset_zk", "SELECT COUNT(*) FROM words WHERE stage_xs = 1 AND stage_zk = 0"),
    (
        "stages_json_known",
        "SELECT COUNT(*) FROM user_settings us, json_each(us.stages_json) j WHERE j.value NOT IN (" + ",".join(f"'{code}'" for code in STAGE_ORDER) + ")",
    ),
)
STAGE_INVARIANTS_FROM_VERSION = 11  # 0011_primary_stage.sql: stage_xs exists, stage_min / current_stage are 1..5
LEARN_ORDER_INVARIANTS_FROM_VERSION = 14  # 0014_learn_rank.sql: words.learn_rank exists (== learn_order.LEARN_ORDER_FROM_VERSION, pinned by test_diag)


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
        for key in ("seed_version", "last_tick_at", "worker_lease", "learn_order.version"):
            lines.append(_kv_line(conn, key))
        lines.append(_learn_order_stats_line(conn))  # informational; before kv.backup.last so every later line is an invariant
        lines.append(_kv_line(conn, "backup.last"))
        if version >= STAGE_INVARIANTS_FROM_VERSION:
            for name, sql in STAGE_INVARIANTS:
                line, violated = _invariant_line(conn, name, sql)
                lines.append(line)
                ok = ok and not violated
            line, violated = _seed_version_line(conn, cfg)
            lines.append(line)
            ok = ok and not violated
        if version >= LEARN_ORDER_INVARIANTS_FROM_VERSION:
            for line, violated in _learn_order_lines(conn):
                lines.append(line)
                ok = ok and not violated
        return CheckResult("db", ok, lines)
    except sqlite3.Error as e:
        return CheckResult("db", False, [*lines, f"query failed: {e}"])
    finally:
        conn.close()


def _kv_line(conn: sqlite3.Connection, key: str) -> str:
    value = db.kv_get(conn, key)
    return f"kv.{key}: {value if value is not None else '-'}"


def _learn_order_stats_line(conn: sqlite3.Connection) -> str:
    """``kv.learn_order.stats: …`` rendered by the learning-order module (``-`` before the first recompute); never flips ok."""
    from .services.learn_order import stats_line  # late import: the `_seed_version_line` pattern (diag stays light for `wd logs`)

    return stats_line(conn)


def _learn_order_lines(conn: sqlite3.Connection) -> list[tuple[str, bool]]:
    """The four ``invariant learn_* / calendar_words_in_xs`` lines of DESIGN §2.7 (``learn_order.check_lines``): stage words
    without a key, a stale policy version / seed stamp / never computed, stored keys that differ from ``rank_rows()`` (the stage
    words placed by seed-only rules — ``learn_order.Drift.policy``; re-dealt stage phrases and 课标外 drift are informational
    counts of the stats line) and calendar words outside 小学; a failing query or a raising policy is ``query failed (…)`` and not
    counted, like :func:`_invariant_line`."""
    from .services.learn_order import check_lines  # late import, see _learn_order_stats_line

    return check_lines(conn)


def _invariant_line(conn: sqlite3.Connection, name: str, sql: str) -> tuple[str, bool]:
    """``invariant <name>: ok | N violation(s) | query failed (…)`` and whether it counts as a violation.

    A failing query (an SQLite build without ``json_each``, a schema this build does not know) is reported in place and
    leaves the other invariants and the check's verdict alone: ``wd check`` is a diagnostic, not a gate on the SQLite
    version (PLAN §2.5 item 5).
    """
    try:
        n = int(conn.execute(sql).fetchone()[0])
    except sqlite3.OperationalError as e:
        return f"invariant {name}: query failed ({e})", False
    return (f"invariant {name}: ok", False) if n == 0 else (f"invariant {name}: {n} violation(s)", True)


def _seed_version_line(conn: sqlite3.Connection, cfg: Settings) -> tuple[str, bool]:
    """``invariant seed_version_matches_file`` — ``kv.seed_version`` equals the content digest of ``WD_SEED_PATH``.

    The digest is :func:`wd.seed.seed_digest` (the decompressed content, what ``main.seed_check`` compares, PLAN R-9), so
    a Mac/Linux gzip difference is not a violation while a cleared key (migration 0011) or a changed seed is: both mean
    the next ``wd serve`` start (or ``wd import-seed``) will rewrite the vocabulary, and the release runbook wants that
    done — and verified — while the service is stopped. A missing file is skipped, like ``seed_check`` skips it; an
    unreadable one is a violation because ``seed_check`` would fail on it at every start — and, like ``seed_check``, this
    catches *everything* the digest can raise, not only ``OSError``: a truncated archive is ``EOFError``, a bad header
    ``gzip.BadGzipFile`` (an ``OSError``), but a valid header over a corrupt deflate body is ``zlib.error``, which derives
    from ``Exception`` directly. A diagnostic that aborts ``wd check all`` with a traceback on the very file it is meant
    to judge would be worse than useless (impl review S6-M2).
    """
    from .seed import seed_digest  # late import: diag is on the `wd logs` / `wd check` path, seed pulls services.words

    name = "seed_version_matches_file"
    path = Path(cfg.seed_path)
    if not path.is_file():
        return f"invariant {name}: skipped (seed file missing: {path})", False
    stored = db.kv_get(conn, "seed_version")
    try:
        digest = seed_digest(path)
    except Exception as e:  # noqa: BLE001 - OSError / EOFError / zlib.error …: the same net main.seed_check casts (docstring)
        return f"invariant {name}: 1 violation(s) (cannot read {path.name}: {e})", True
    if stored == digest:
        return f"invariant {name}: ok", False
    shown = f"{stored[:12]}…" if stored else "-"
    return f"invariant {name}: 1 violation(s) (kv.seed_version {shown} ≠ file {digest[:12]}…; run `wd import-seed`)", True


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
        # fallback provider + failover state (CLAUDE_INTEGRATION §10) — informational, never flips `ok`
        lines.append(f"provider mode: {cfg.ai_provider}; active: {db.kv_get(conn, 'ai.active_provider', 'claude')}; manual pause: {db.kv_get(conn, 'ai.paused_until') or '-'}")
        if cfg.fallback_configured:
            fb_avail = db.kv_get(conn, "ai.fallback.available")
            lines.append(
                f"fallback: {cfg.ai_fallback_kind} {cfg.ai_fallback_model} @ {cfg.ai_fallback_base_url} kinds={','.join(cfg.ai_fallback_kinds) or '-'} "
                f"available={fb_avail if fb_avail is not None else 'never probed'} paused_until={db.kv_get(conn, 'ai.fallback.paused_until') or '-'} "
                f"model_seen={db.kv_get(conn, 'ai.fallback.model_seen') or '-'}"
            )
            if fb_avail == "0":
                lines.append("hint: the fallback probe failed — check WD_AI_FALLBACK_* and run `wd ai-check --provider fallback`")
        else:
            lines.append("fallback: not configured (WD_AI_FALLBACK_KIND=none)")
    else:
        lines.append("probe state: (no database)")
    return CheckResult("claude", ok, lines)


def check_smtp(cfg: Settings, connect: Callable[[str, int, float], None] | None = None) -> CheckResult:
    """The e-mail channel: ``WD_MAIL_PROVIDER=smtp`` gets a TCP probe of the SMTP host; ``aliyun_dm`` (DirectMail over HTTPS with the
    ``WD_ALIYUN_*`` key) reports the provider and the sender instead — no socket probe, the key is only read when a mail is sent."""
    if cfg.mail_provider == "aliyun_dm":
        if not cfg.email_configured:
            return CheckResult("smtp", True, ["not configured (WD_MAIL_PROVIDER=aliyun_dm needs WD_ALIYUN_ACCESS_KEY_ID / WD_ALIYUN_ACCESS_KEY_SECRET_FILE / WD_SMTP_FROM) — e-mail channel off"])
        return CheckResult("smtp", True, ["provider: aliyun_dm (DirectMail SingleSendMail over https, no socket probe)", f"from: {cfg.smtp_from}", f"key id: {cfg.aliyun_access_key_id[:4]}… (secret file {cfg.aliyun_access_key_secret_file})"])
    if not cfg.email_configured:
        return CheckResult("smtp", True, ["not configured (WD_SMTP_HOST / WD_SMTP_FROM empty) — e-mail channel off"])
    lines = ["provider: smtp", f"host: {cfg.smtp_host}:{cfg.smtp_port} ({cfg.smtp_tls})", f"from: {cfg.smtp_from}", f"auth: {'user set' if cfg.smtp_user else 'anonymous'}"]

    def _connect(host: str, port: int, timeout: float) -> None:
        with socket.create_connection((host, port), timeout=timeout):
            pass

    try:
        (connect or _connect)(cfg.smtp_host, cfg.smtp_port, SMTP_CONNECT_TIMEOUT_S)
    except OSError as e:
        return CheckResult("smtp", False, [*lines, f"TCP connect failed: {e}"])
    return CheckResult("smtp", True, [*lines, "TCP connect: ok"])


def third_party_state(cfg: Settings, configured: bool) -> str:
    """``on`` / ``off`` for a third-party sign-in provider (slice 2-A), ``fake`` when the dev fakes stand in for an unconfigured one
    (``WD_AUTH_FAKE_PROVIDERS=1`` — the same word ``main.startup``'s ``sign-in channels:`` line uses)."""
    if configured:
        return "on"
    return "fake" if cfg.auth_fake_providers else "off"


def audio_lines(cfg: Settings) -> tuple[list[str], bool]:
    """The pronunciation provider in force (``WD_AUDIO_PROVIDER`` with ``auto`` resolved, API.md 76) and, for ``bailian``, the model,
    the region, both voices and whether the API key FILE is readable (``ok`` / ``missing`` — never the key itself); a missing key file
    under ``bailian`` is a failure (every tap would answer 503 ``failed``). One more line says where the Chinese clips of 磨耳朵
    (``accent=zh-CN``, API.md 123) come from: ``say`` — by configuration only, this check spawns nothing; ``wd audio-voices`` probes
    the voice — or nowhere yet under the other providers. Never a failure: without a Chinese voice 磨耳朵 reads the English only."""
    provider = cfg.audio_provider_effective
    lines = [f"audio: {provider} (WD_AUDIO_PROVIDER={cfg.audio_provider})"]
    if provider == "say":
        voice = f"WD_AUDIO_SAY_VOICE_ZH={cfg.audio_say_voice_zh}" if cfg.audio_say_voice_zh else "the best installed zh_CN voice (WD_AUDIO_SAY_VOICE_ZH unset)"
        lines.append(f"audio zh-CN: say, {voice} — `wd audio-voices` shows whether it speaks; none = 磨耳朵 reads the English only")
    elif provider != "off":
        lines.append(f"audio zh-CN: none — {provider} has no Chinese clips yet (only say speaks Chinese; 磨耳朵 uses the device's own Chinese voice)")
    if provider != "bailian":
        return lines, True
    path = Path(cfg.bailian_api_key_file).expanduser() if cfg.bailian_api_key_file else None
    readable = path is not None and path.is_file() and os.access(path, os.R_OK)
    voices = cfg.bailian_voice_map
    lines.append(f"bailian: model {cfg.bailian_tts_model}, region {cfg.bailian_region}, en-US → {voices.get('en-US', '?')}, en-GB → {voices.get('en-GB', '?')}, key file {'ok' if readable else 'missing'}" + (f" ({path})" if path is not None else " (WD_BAILIAN_API_KEY_FILE unset)"))
    if not readable:
        lines.append("hint: put the 百炼 API key (sk-…) on the first line of a 0600 file named by WD_BAILIAN_API_KEY_FILE, then `wd audio-probe`")
    return lines, readable


def check_providers(cfg: Settings, conn: sqlite3.Connection | None) -> CheckResult:
    audio, audio_ok = audio_lines(cfg)
    lines = [
        f"images: {'enabled' if cfg.images_enabled else 'disabled'}",
        f"chain: {', '.join(cfg.image_providers) or '-'}",
        f"svg via claude: {'1' if cfg.svg_via_claude else '0'} (sub-cap ${cfg.ai_svg_daily_budget_usd:.2f}/day)",
        # third-party sign-in (API.md §3.3, DEPLOY §4 WD_WECHAT_* / WD_QQ_* / WD_APPLE_*): what the login page offers; `on` needs the variables set
        f"third-party sign-in: wechat {third_party_state(cfg, cfg.wechat_configured)}, qq {third_party_state(cfg, cfg.qq_configured)}, apple {third_party_state(cfg, cfg.apple_configured)}",
        # pronunciation clips (API.md 76, DEPLOY §4 WD_AUDIO_PROVIDER / WD_BAILIAN_*): the provider in force; bailian's model, voices and key file
        *audio,
    ]
    ok = audio_ok
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


__all__ = [
    "LEARN_ORDER_INVARIANTS_FROM_VERSION",
    "STAGE_INVARIANTS",
    "STAGE_INVARIANTS_FROM_VERSION",
    "CheckResult",
    "audio_lines",
    "check_claude",
    "check_db",
    "check_providers",
    "third_party_state",
    "check_smtp",
    "collect_stats",
    "register_cli",
    "run_checks",
    "tail_lines",
]
