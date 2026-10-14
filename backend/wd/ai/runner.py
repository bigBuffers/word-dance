"""The ``claude -p`` runner (CLAUDE_INTEGRATION §1–§3).

* :func:`build_argv` — tier 0 is the verified invocation (``-p <prompt> --output-format json --json-schema <schema>
  --tools "" --no-session-persistence --model <m> --max-budget-usd <usd>``); tier 1 adds ``--system-prompt
  --restricted --strict-mcp-config --disable-slash-commands``. Under tier 0 the system prompt is folded into the
  positional prompt as ``<system_instructions>…</system_instructions>\\n\\n<user prompt>``. Never ``--bare``;
  ``--fallback-model`` only when ``WD_AI_FALLBACK_MODEL`` is set; ``WD_AI_EXTRA_ARGS`` appended verbatim.
* :func:`claude_env` — an allow-list, never a copy of ``os.environ`` (no ``CLAUDECODE``, no ``CLAUDE_CODE_*``,
  no ``WD_*``).
* :func:`run_claude` — ledger row **before** the spawn, ``Popen`` + ``communicate(timeout)`` +
  ``os.killpg(proc.pid, SIGKILL)`` + a second ``communicate()`` (never ``subprocess.run``), ``stdin=DEVNULL``,
  the empty ``WD_DATA_DIR/claude-cwd`` as cwd, raw stdout/stderr saved under ``claude-logs/YYYY-MM-DD/<id>.json``.
* :func:`parse_and_classify` — the §3 status table.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shlex
import signal
import sqlite3
import subprocess
import time
from dataclasses import dataclass, field
from datetime import timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from .. import db
from ..clock import now_iso, parse_iso, to_iso
from ..config import Settings
from ..interfaces import ClaudeResult
from . import budget, ledger

log = logging.getLogger("wd.ai.runner")

SCHEMAS_DIR = Path(__file__).resolve().parent / "schemas"
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

TIER1_FLAGS: tuple[str, ...] = ("--restricted", "--strict-mcp-config", "--disable-slash-commands")
PASSTHROUGH_ENV: tuple[str, ...] = (
    "CLAUDE_CONFIG_DIR",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
    "XDG_CACHE_HOME",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
)
OUTPUT_CAP_BYTES = 10_000_000
STDERR_EXCERPT_CHARS = 1000
FLAG_ERROR_EVENT_WINDOW = timedelta(hours=1)

AUTH_RE = re.compile(r"not logged in|log ?in|authentication|unauthori[sz]ed|\b401\b|invalid api key|credential", re.IGNORECASE)
BUDGET_RE = re.compile(r"max.?budget|budget", re.IGNORECASE)
OVERLOADED_RE = re.compile(r"overloaded|\b529\b|\b503\b|rate.?limit|too many requests", re.IGNORECASE)
USAGE_ERROR_RE = re.compile(r"unknown option|error: option|too many arguments", re.IGNORECASE)

#: test hooks called right before ``Popen`` as ``hook(conn, call_id, argv)`` (the ledger row must already exist)
SPAWN_HOOKS: list[Callable[[sqlite3.Connection, int, list[str]], None]] = []


# ------------------------------------------------------------------------------------- resources
@lru_cache(maxsize=None)
def load_schema(name: str) -> dict:
    """``ai/schemas/<name>.json`` parsed once (``content_v1`` …)."""
    return json.loads((SCHEMAS_DIR / f"{name}.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def load_prompt(name: str) -> str:
    """``ai/prompts/<name>.txt`` read once, trailing newline stripped."""
    return (PROMPTS_DIR / f"{name}.txt").read_text(encoding="utf-8").rstrip("\n")


def schema_arg(schema: dict) -> str:
    """The ``--json-schema`` argument: compact JSON, non-ASCII kept (CLAUDE_INTEGRATION §4)."""
    return json.dumps(schema, separators=(",", ":"), ensure_ascii=False)


def format_budget(usd: float) -> str:
    """``0.25`` → ``'0.25'``, ``2.0`` → ``'2'`` (what the CLI parses as a number)."""
    return f"{float(usd):.6g}"


def flag_tier(conn: sqlite3.Connection) -> str:
    """``kv.claude.flag_tier`` (``'1'`` or ``'0'``; default ``'0'`` until the probe records a tier)."""
    return "1" if db.kv_get(conn, "claude.flag_tier", "0") == "1" else "0"


ITEMS_TAG_RE = re.compile(r"<(/?items)>")


def fold_system_prompt(system_prompt: str, user_prompt: str) -> str:
    """Tier 0 has no ``--system-prompt``: the system prompt is folded into the positional prompt.

    A literal ``<items>`` mention inside the system instructions (the lookup prompt names the data block) is written
    as ``‹items›`` so the one real ``<items>…</items>`` block of the user prompt stays the first and only one — the
    data block must be unambiguous to the model and to anything (such as ``tests/fake_claude.py``) that parses it.
    """
    if not system_prompt:
        return user_prompt
    system = ITEMS_TAG_RE.sub(r"‹\1›", system_prompt)
    return f"<system_instructions>{system}</system_instructions>\n\n{user_prompt}"


def build_argv(cfg: Settings, tier: str, system_prompt: str, user_prompt: str, schema: dict, max_budget_usd: float) -> list[str]:
    """The exact argv for one spawn (CLAUDE_INTEGRATION §1.1): tier 0 verified flags, tier 1 the hardened extras."""
    prompt = user_prompt if tier == "1" else fold_system_prompt(system_prompt, user_prompt)
    argv = [
        cfg.claude_bin,
        "-p",
        prompt,
        "--output-format",
        "json",
        "--json-schema",
        schema_arg(schema),
        "--tools",
        "",
        "--no-session-persistence",
        "--model",
        cfg.ai_model,
        "--max-budget-usd",
        format_budget(max_budget_usd),
    ]
    if tier == "1":
        argv += ["--system-prompt", system_prompt, *TIER1_FLAGS]
    if cfg.ai_fallback_model:
        argv += ["--fallback-model", cfg.ai_fallback_model]
    if cfg.ai_extra_args:
        argv += shlex.split(cfg.ai_extra_args)
    return argv


def claude_env(cfg: Settings, environ: dict[str, str] | None = None) -> dict[str, str]:
    """The child environment, built from the §1.3 allow-list (never a copy of ``os.environ``)."""
    source = os.environ if environ is None else environ
    env = {
        "HOME": cfg.claude_home or source.get("HOME", "/home/sqin"),
        "PATH": cfg.claude_path,
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TERM": "dumb",
        "NO_COLOR": "1",
        "TZ": "UTC",
    }
    for key in PASSTHROUGH_ENV:
        value = source.get(key)
        if value:
            env[key] = value
    return env


# --------------------------------------------------------------------------------------- parsing
@dataclass
class Parsed:
    """The classified outcome of one spawn (CLAUDE_INTEGRATION §3)."""

    status: str
    structured: dict | None = None
    cost_usd: float = 0.0
    model_used: str | None = None
    session_id: str | None = None
    duration_ms: int | None = None
    exit_code: int | None = None
    error: str | None = None
    tokens: dict[str, int | None] = field(default_factory=dict)
    usage_error: bool = False

    @property
    def ok(self) -> bool:
        return self.status == "success"


def _result_object(stdout: str) -> dict | None:
    """``json.loads(stdout)`` when it is a dict, else the last stdout line parsing to a dict with ``type == 'result'``."""
    text = stdout.strip()
    if not text:
        return None
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except ValueError:
        pass
    for line in reversed(text.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("type") == "result":
            return data
    return None


def _int_or_none(v: Any) -> int | None:
    try:
        return None if v is None else int(v)
    except (TypeError, ValueError):
        return None


def parse_and_classify(returncode: int | None, stdout: str, stderr: str, schema: dict | None = None) -> Parsed:
    """The §3 table: success · auth · budget · overloaded · error (``invalid_output`` is decided by the handlers)."""
    out = (stdout or "")[:OUTPUT_CAP_BYTES]
    err = (stderr or "")[:OUTPUT_CAP_BYTES]
    data = _result_object(out)
    usage = (data or {}).get("usage") if isinstance((data or {}).get("usage"), dict) else {}
    model_usage = (data or {}).get("modelUsage")
    model_used = next(iter(model_usage), None) if isinstance(model_usage, dict) and model_usage else None
    cost = 0.0
    if data is not None:
        try:
            cost = float(data.get("total_cost_usd") or 0)
        except (TypeError, ValueError):
            cost = 0.0
    parsed = Parsed(
        status="error",
        cost_usd=cost,
        model_used=str(model_used) if model_used else None,
        session_id=str(data["session_id"]) if data and data.get("session_id") else None,
        duration_ms=_int_or_none((data or {}).get("duration_ms")),
        exit_code=returncode,
        tokens={
            "input_tokens": _int_or_none(usage.get("input_tokens")),
            "output_tokens": _int_or_none(usage.get("output_tokens")),
            "cache_read_tokens": _int_or_none(usage.get("cache_read_input_tokens")),
            "cache_create_tokens": _int_or_none(usage.get("cache_creation_input_tokens")),
        },
    )
    structured = (data or {}).get("structured_output")
    success = (
        returncode == 0
        and data is not None
        and data.get("is_error") is False
        and data.get("subtype") == "success"
        and isinstance(structured, dict)
    )
    if success:
        parsed.status = "success"
        parsed.structured = structured
        return parsed
    subtype = str((data or {}).get("subtype") or "")
    result_text = str((data or {}).get("result") or "")
    text = f"{err}\n{result_text}\n{subtype}"
    if AUTH_RE.search(text):
        parsed.status = "auth"
    elif "budget" in subtype.lower() or BUDGET_RE.search(text):
        parsed.status = "budget"
    elif OVERLOADED_RE.search(text):
        parsed.status = "overloaded"
    else:
        parsed.status = "error"
        parsed.usage_error = returncode == 1 and USAGE_ERROR_RE.search(err) is not None
    detail = err.strip() or result_text.strip() or subtype or ("unparseable stdout" if data is None else "is_error")
    if returncode != 0 and not err.strip():
        detail = f"exit {returncode}: {detail}"
    parsed.error = detail[:STDERR_EXCERPT_CHARS]
    return parsed


# -------------------------------------------------------------------------------------- raw logs
def save_raw(cfg: Settings, call_id: int, argv: list[str], stdout: str, stderr: str, exit_code: int | None, now: str) -> str | None:
    """Write ``claude-logs/YYYY-MM-DD/<call_id>.json`` (0600); returns the path relative to the data dir, None on failure."""
    try:
        day_dir = cfg.claude_logs_dir / now[:10]
        day_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = day_dir / f"{int(call_id)}.json"
        payload = {
            "call_id": int(call_id),
            "started_at": now,
            "exit_code": exit_code,
            "argv": [a if len(a) <= 20_000 else a[:20_000] + "…" for a in argv],
            "stdout": (stdout or "")[:OUTPUT_CAP_BYTES],
            "stderr": (stderr or "")[:OUTPUT_CAP_BYTES],
        }
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        try:
            os.chmod(path, 0o600)
        except OSError:  # pragma: no cover - mode already set at open()
            pass
        return str(path.relative_to(cfg.data_dir)) if path.is_relative_to(cfg.data_dir) else str(path)
    except OSError as e:  # the ledger is what matters; a missing raw log is only logged
        log.warning("could not save the raw claude output of call %s: %s", call_id, e)
        return None


def prune_logs(cfg: Settings, now: str | None = None, keep_days: int | None = None) -> int:
    """Delete ``claude-logs/YYYY-MM-DD`` directories older than ``WD_AI_LOG_KEEP_DAYS`` (default 14); returns the count."""
    now = now or now_iso()
    keep = cfg.ai_log_keep_days if keep_days is None else int(keep_days)
    root = cfg.claude_logs_dir
    if not root.is_dir():
        return 0
    cutoff = (parse_iso(now) - timedelta(days=keep)).date().isoformat()
    removed = 0
    for day_dir in sorted(root.iterdir()):
        if not day_dir.is_dir() or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day_dir.name) or day_dir.name >= cutoff:
            continue
        for f in day_dir.iterdir():
            try:
                f.unlink()
            except OSError:  # pragma: no cover - best effort
                pass
        try:
            day_dir.rmdir()
            removed += 1
        except OSError:  # pragma: no cover - best effort
            pass
    return removed


# ------------------------------------------------------------------------------------------ run
def _finish(conn: sqlite3.Connection, call_id: int, parsed: Parsed, *, stdout_path: str | None, started: float, now: str) -> ClaudeResult:
    duration = parsed.duration_ms if parsed.duration_ms is not None else int((time.perf_counter() - started) * 1000)
    ledger.finish_call(
        conn,
        call_id,
        status=parsed.status,
        cost_usd=parsed.cost_usd,
        duration_ms=duration,
        input_tokens=parsed.tokens.get("input_tokens"),
        output_tokens=parsed.tokens.get("output_tokens"),
        cache_read_tokens=parsed.tokens.get("cache_read_tokens"),
        cache_create_tokens=parsed.tokens.get("cache_create_tokens"),
        model_used=parsed.model_used,
        session_id=parsed.session_id,
        exit_code=parsed.exit_code,
        error=parsed.error,
        stdout_path=stdout_path,
        now=now,
    )
    return ClaudeResult(
        ok=parsed.ok,
        status=parsed.status,
        structured=parsed.structured,
        cost_usd=parsed.cost_usd,
        call_id=int(call_id),
        model_used=parsed.model_used,
        error=parsed.error,
    )


def _flag_error_event(conn: sqlite3.Connection, parsed: Parsed, now: str) -> None:
    since = to_iso(parse_iso(now) - FLAG_ERROR_EVENT_WINDOW)
    budget.event_once(
        conn,
        "claude_flag_error",
        since,
        {"exit_code": parsed.exit_code, "stderr_excerpt": (parsed.error or "")[:300], "hint": "run `wd claude-check` to re-probe the flag tier"},
        now=now,
    )


def run_claude(
    conn: sqlite3.Connection,
    *,
    kind: str,
    system_prompt: str,
    user_prompt: str,
    schema: dict,
    max_budget_usd: float,
    timeout_s: int,
    word_count: int,
    job_ids: list[int],
    cfg: Settings | None = None,
    now: str | None = None,
    tier: str | None = None,
    call_id: int | None = None,
    fallback_on_usage_error: bool = True,
) -> ClaudeResult:
    """Spawn ``claude -p`` once and classify the outcome (TASKS §I signature plus keyword extensions).

    ``cfg`` defaults to the current environment; ``tier`` defaults to ``kv.claude.flag_tier``; ``call_id`` is the
    ledger row of a prior :func:`wd.ai.budget.reserve` (otherwise the row is inserted here — still before the spawn).
    A tier-1 usage error (exit 1 and stderr matching ``unknown option`` …) writes ``system_events('claude_flag_error')``
    and is retried once with the tier-0 argv unless ``fallback_on_usage_error`` is False (the probe handles tiers itself).
    """
    cfg = cfg or Settings.from_env()
    now = now or now_iso()
    tier = flag_tier(conn) if tier is None else ("1" if str(tier) == "1" else "0")
    argv = build_argv(cfg, tier, system_prompt, user_prompt, schema, max_budget_usd)
    if call_id is None:
        call_id = ledger.insert_call(
            conn,
            kind=kind,
            model_requested=cfg.ai_model,
            flag_tier=int(tier),
            word_count=word_count,
            job_ids=job_ids,
            max_budget_usd=max_budget_usd,
            reserved_usd=budget.estimate(kind, word_count),
            now=now,
        )
    env = claude_env(cfg)
    for hook in list(SPAWN_HOOKS):
        hook(conn, call_id, argv)
    started = time.perf_counter()
    try:
        proc = subprocess.Popen(
            argv,
            cwd=str(cfg.claude_cwd),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
    except OSError as e:
        parsed = Parsed(status="spawn_error", error=f"{e.__class__.__name__}: {e}"[:STDERR_EXCERPT_CHARS])
        log.error("claude spawn failed: %s", e, extra={"event": "claude_spawn_error"})
        return _finish(conn, call_id, parsed, stdout_path=None, started=started, now=now)
    try:
        out, err = proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)  # pgid == proc.pid thanks to start_new_session=True
        except ProcessLookupError:  # pragma: no cover - the group vanished between the timeout and the kill
            pass
        out, err = proc.communicate()  # reap + collect the partial output; no second timeout: the group is dead
        stdout_path = save_raw(cfg, call_id, argv, out, err, proc.returncode, now)
        parsed = Parsed(status="timeout", exit_code=proc.returncode, error=f"timeout after {timeout_s}s; killed process group {proc.pid}")
        log.warning("claude call %s timed out after %ss", call_id, timeout_s, extra={"event": "claude_timeout"})
        return _finish(conn, call_id, parsed, stdout_path=stdout_path, started=started, now=now)
    stdout_path = save_raw(cfg, call_id, argv, out, err, proc.returncode, now)
    parsed = parse_and_classify(proc.returncode, out, err, schema)
    result = _finish(conn, call_id, parsed, stdout_path=stdout_path, started=started, now=now)
    log.log(
        logging.INFO if parsed.ok else logging.WARNING,
        "claude %s call %s → %s",
        kind,
        call_id,
        parsed.status,
        extra={"cost_usd": parsed.cost_usd, "event": "claude_call"},
    )
    if tier == "1" and parsed.usage_error:
        _flag_error_event(conn, parsed, now)
        if fallback_on_usage_error:
            log.warning("tier-1 flag rejected by the claude CLI; retrying call %s once with the tier-0 argv", call_id, extra={"event": "claude_flag_error"})
            return run_claude(
                conn,
                kind=kind,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                schema=schema,
                max_budget_usd=max_budget_usd,
                timeout_s=timeout_s,
                word_count=word_count,
                job_ids=job_ids,
                cfg=cfg,
                now=now,
                tier="0",
                fallback_on_usage_error=False,
            )
    return result


class Runner:
    """:class:`wd.interfaces.ClaudeRunner` bound to one settings object (handlers may be given another runner in tests)."""

    def __init__(self, cfg: Settings, *, now: Callable[[], str] | None = None):
        self.cfg = cfg
        self._now = now

    def run(
        self,
        conn: sqlite3.Connection,
        *,
        kind: str,
        system_prompt: str,
        user_prompt: str,
        schema: dict,
        max_budget_usd: float,
        timeout_s: int,
        word_count: int,
        job_ids: list[int],
        call_id: int | None = None,
    ) -> ClaudeResult:
        return run_claude(
            conn,
            kind=kind,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            schema=schema,
            max_budget_usd=max_budget_usd,
            timeout_s=timeout_s,
            word_count=word_count,
            job_ids=job_ids,
            cfg=self.cfg,
            now=self._now() if self._now else None,
            call_id=call_id,
        )


__all__ = [
    "PASSTHROUGH_ENV",
    "Parsed",
    "Runner",
    "SPAWN_HOOKS",
    "TIER1_FLAGS",
    "build_argv",
    "claude_env",
    "flag_tier",
    "fold_system_prompt",
    "format_budget",
    "load_prompt",
    "load_schema",
    "parse_and_classify",
    "prune_logs",
    "run_claude",
    "save_raw",
    "schema_arg",
]
