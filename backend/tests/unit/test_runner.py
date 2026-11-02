"""ai/runner.py against the REAL fake_claude.py subprocess: exact argv per tier, env allow-list, cwd, ledger-before-spawn,
every FAKE_CLAUDE_MODE classification, the 2-second timeout with a process-group kill, the tier-1 usage-error fallback,
cost recorded on budget failures, raw logs and their pruning."""

from __future__ import annotations

import errno
import json
import os
import signal
import stat
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest

from wd import db
from wd.ai import content, ledger, runner
from wd.ai.probe import EXPECTED, PROBE_PROMPT, PROBE_SYSTEM_PROMPT

NOW = "2026-10-14T00:00:00Z"
FAKE = Path(__file__).resolve().parents[1] / "fake_claude.py"
WORDS = [
    {"word": "abandon", "dictionary_hint": "vt. 放弃, 抛弃", "pos_hint": "v:96", "stages": ["高中", "四级"]},
    {"word": "GDP", "dictionary_hint": "国内生产总值", "pos_hint": "", "stages": [], "kind": "abbreviation"},
]
CONTENT_PROMPT = content.build_user_prompt(WORDS)


def make_wrapper(directory: Path, mode: str) -> Path:
    """A ``claude`` stand-in that records cwd + env and runs fake_claude.py in ``mode`` (the runner's env allow-list never
    passes FAKE_CLAUDE_MODE through, so the mode is baked into the wrapper)."""
    directory.mkdir(parents=True, exist_ok=True)
    script = directory / f"claude-{mode}"
    script.write_text(
        "#!/usr/bin/env bash\n"
        f"pwd > '{directory}/cwd.txt'\n"
        f"env > '{directory}/env.txt'\n"
        f"FAKE_CLAUDE_MODE='{mode}' exec '{sys.executable}' -I '{FAKE}' \"$@\"\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


@pytest.fixture
def cfg_for(settings, tmp_path):
    def _cfg(mode: str = "ok", **overrides):
        wrapper = make_wrapper(tmp_path / "bin", mode)
        return replace(settings, claude_bin=str(wrapper), **overrides)

    return _cfg


def run(conn, cfg, *, kind="content", prompt=CONTENT_PROMPT, schema="content_v1", timeout_s=30, tier=None, system_prompt="SYSTEM", budget=0.25, fallback=True):
    return runner.run_claude(
        conn,
        kind=kind,
        system_prompt=system_prompt,
        user_prompt=prompt,
        schema=runner.load_schema(schema),
        max_budget_usd=budget,
        timeout_s=timeout_s,
        word_count=len(WORDS),
        job_ids=[1, 2],
        cfg=cfg,
        now=NOW,
        tier=tier,
        fallback_on_usage_error=fallback,
    )


# -------------------------------------------------------------------------------------------- argv / env
def test_tier0_argv_is_exactly_the_verified_invocation(settings):
    schema = runner.load_schema("content_v1")
    argv = runner.build_argv(settings, "0", "SYS", "Generate x", schema, 0.25)
    assert argv == [
        settings.claude_bin,
        "-p",
        "<system_instructions>SYS</system_instructions>\n\nGenerate x",
        "--output-format",
        "json",
        "--json-schema",
        json.dumps(schema, separators=(",", ":"), ensure_ascii=False),
        "--tools",
        "",
        "--no-session-persistence",
        "--model",
        "sonnet",
        "--max-budget-usd",
        "0.25",
    ]
    assert "--bare" not in argv and "--fallback-model" not in argv and "--permission-mode" not in argv


def test_tier1_argv_adds_the_four_hardened_flags_and_the_escape_hatches(settings):
    schema = runner.load_schema("lookup_v1")
    argv = runner.build_argv(settings, "1", "SYS", "Look up", schema, 0.15)
    tier0 = runner.build_argv(settings, "0", "", "Look up", schema, 0.15)
    assert argv[:14] == tier0 and argv[2] == "Look up"  # the user prompt stays positional; no folding under tier 1
    assert argv[14:] == ["--system-prompt", "SYS", "--restricted", "--strict-mcp-config", "--disable-slash-commands"]
    cfg = replace(settings, ai_fallback_model="haiku", ai_extra_args="--effort low")
    assert runner.build_argv(cfg, "0", "S", "U", schema, 0.4)[-4:] == ["--fallback-model", "haiku", "--effort", "low"]
    assert runner.format_budget(0.4) == "0.4" and runner.format_budget(2.0) == "2" and runner.format_budget(0.05) == "0.05"


def test_tier0_folding_keeps_the_items_block_unambiguous():
    system = runner.load_prompt("lookup_system")
    assert "<items>" in system
    folded = runner.fold_system_prompt(system, 'Look up.\n<items>\n{"items": ["GDP"]}\n</items>')
    head, _, tail = folded.partition("</system_instructions>")
    assert "<items>" not in head and "‹items›" in head and tail.count("<items>") == 1 and tail.count("</items>") == 1
    assert runner.fold_system_prompt("", "U") == "U"


def test_claude_env_is_an_allow_list(settings, monkeypatch):
    environ = {
        "HOME": "/home/sqin",
        "CLAUDECODE": "1",
        "CLAUDE_CODE_ENTRYPOINT": "cli",
        "WD_SECRET_KEY": "s3cret",
        "ANTHROPIC_API_KEY": "k",
        "HTTPS_PROXY": "http://proxy:3128",
        "PATH": "/evil:/usr/bin",
        "LANG": "zh_CN.UTF-8",
        "SHELL": "/bin/zsh",
    }
    env = runner.claude_env(settings, environ)
    assert env["HOME"] == "/home/sqin" and env["PATH"] == settings.claude_path
    assert env["LANG"] == "C.UTF-8" and env["LC_ALL"] == "C.UTF-8" and env["TERM"] == "dumb" and env["NO_COLOR"] == "1" and env["TZ"] == "UTC"
    assert env["ANTHROPIC_API_KEY"] == "k" and env["HTTPS_PROXY"] == "http://proxy:3128"
    assert "CLAUDECODE" not in env and not any(k.startswith("CLAUDE_CODE_") or k.startswith("WD_") for k in env) and "SHELL" not in env
    assert replace(settings, claude_home="/srv/claude-home") and runner.claude_env(replace(settings, claude_home="/srv/h"), environ)["HOME"] == "/srv/h"
    monkeypatch.setenv("CLAUDECODE", "1")
    assert "CLAUDECODE" not in runner.claude_env(settings)


# -------------------------------------------------------------------------------------------- real calls
def test_ok_call_records_ledger_cost_tokens_raw_log_cwd_and_env(conn, cfg_for, tmp_path):
    cfg = cfg_for("ok")
    result = run(conn, cfg)
    assert result.ok and result.status == "success"
    assert [it["word"] for it in result.structured["items"]] == ["abandon", "GDP"]
    assert result.cost_usd == pytest.approx(0.008) and result.model_used == "claude-sonnet-fake"
    row = ledger.get_call(conn, result.call_id)
    assert row["status"] == "success" and row["kind"] == "content" and row["flag_tier"] == 0 and row["word_count"] == 2
    assert json.loads(row["job_ids_json"]) == [1, 2] and row["max_budget_usd"] == 0.25 and row["reserved_usd"] == pytest.approx(0.014)
    assert row["cost_usd"] == pytest.approx(0.008) and row["input_tokens"] == 2 and row["output_tokens"] == 660 and row["cache_create_tokens"] == 1691
    assert row["model_used"] == "claude-sonnet-fake" and row["session_id"] == "fake" and row["exit_code"] == 0 and row["duration_ms"] == 1200
    assert row["started_at"] == NOW and row["finished_at"] == NOW
    raw = cfg.data_dir / row["stdout_path"]
    assert raw.is_file() and raw.parent.name == "2026-10-14" and stat.S_IMODE(raw.stat().st_mode) == 0o600
    saved = json.loads(raw.read_text(encoding="utf-8"))
    assert saved["call_id"] == result.call_id and json.loads(saved["stdout"])["structured_output"] == result.structured
    # cwd is the empty claude-cwd directory; the child env is the allow-list (no CLAUDECODE, HOME present)
    assert (tmp_path / "bin" / "cwd.txt").read_text().strip() == str(cfg.claude_cwd)
    assert not any(cfg.claude_cwd.iterdir())
    env_lines = dict(line.split("=", 1) for line in (tmp_path / "bin" / "env.txt").read_text().splitlines() if "=" in line)
    assert "CLAUDECODE" not in env_lines and env_lines["HOME"] == cfg.claude_home_effective and env_lines["TERM"] == "dumb"
    assert not any(k.startswith("WD_") for k in env_lines)


def test_ledger_row_exists_before_the_spawn(conn, cfg_for):
    seen: list[dict] = []

    def hook(c, call_id, argv):
        row = ledger.get_call(c, call_id)
        seen.append({"status": row["status"], "reserved": row["reserved_usd"], "argv0": argv[0], "finished": row["finished_at"]})

    runner.SPAWN_HOOKS.append(hook)
    try:
        result = run(conn, cfg_for("ok"))
    finally:
        runner.SPAWN_HOOKS.remove(hook)
    assert seen == [{"status": "running", "reserved": pytest.approx(0.014), "argv0": cfg_for("ok").claude_bin, "finished": None}]
    assert ledger.get_call(conn, result.call_id)["status"] == "success"


@pytest.mark.parametrize(
    "mode,status,ok",
    [("invalid_json", "error", False), ("auth", "auth", False), ("overloaded", "overloaded", False), ("budget", "budget", False), ("partial", "success", True), ("invalid_word", "success", True), ("stdin_hang", "success", True), ("schema_mismatch", "success", True)],
)
def test_every_fake_mode_is_classified(conn, cfg_for, mode, status, ok):
    result = run(conn, cfg_for(mode), prompt=content.build_user_prompt([*WORDS, {"word": "zzzq", "dictionary_hint": "", "pos_hint": "", "stages": []}]))
    assert result.status == status and result.ok is ok
    row = ledger.get_call(conn, result.call_id)
    assert row["status"] == status and row["finished_at"] == NOW
    if mode == "partial":
        assert [it["word"] for it in result.structured["items"]] == ["abandon", "GDP"]  # the last item is missing → `partial` at the handler
    if mode == "invalid_word":
        assert [it["valid"] for it in result.structured["items"]] == [True, True, False]
    if mode == "schema_mismatch":
        assert all("meaning_zh" not in it for it in result.structured["items"])  # post-validation → invalid_output at the handler
    if mode == "budget":
        assert result.cost_usd == pytest.approx(0.25) and row["cost_usd"] == pytest.approx(0.25)  # cost recorded on the failure
        assert "budget" in (row["error"] or "").lower()
    if mode == "auth":
        assert "Not logged in" in row["error"]
    if mode == "overloaded":
        assert "529" in row["error"]
    if mode == "invalid_json":
        assert row["exit_code"] == 0 and "unparseable" in row["error"]


def test_timeout_kills_the_process_group_and_records_timeout(conn, cfg_for, monkeypatch):
    killed: list[tuple[int, int]] = []
    real_killpg = os.killpg
    pids: list[int] = []
    real_popen = runner.subprocess.Popen

    def spy_popen(*args, **kwargs):
        proc = real_popen(*args, **kwargs)
        pids.append(proc.pid)
        return proc

    def spy_killpg(pgid, sig):
        killed.append((pgid, sig))
        return real_killpg(pgid, sig)

    monkeypatch.setattr(runner.os, "killpg", spy_killpg)
    monkeypatch.setattr(runner.subprocess, "Popen", spy_popen)
    started = time.monotonic()
    result = run(conn, cfg_for("timeout"), timeout_s=2)
    elapsed = time.monotonic() - started
    assert result.status == "timeout" and not result.ok and elapsed < 15
    assert killed == [(pids[0], signal.SIGKILL)]  # pgid == pid thanks to start_new_session
    with pytest.raises(ProcessLookupError):
        os.kill(pids[0], 0)  # reaped by the second communicate()
    row = ledger.get_call(conn, result.call_id)
    assert row["status"] == "timeout" and row["exit_code"] == -signal.SIGKILL and "timeout after 2s" in row["error"] and row["stdout_path"]


def test_tier1_usage_error_falls_back_to_tier0_once_and_records_the_event(conn, cfg_for):
    result = run(conn, cfg_for("usage_error"), tier="1")
    assert result.ok and result.status == "success"
    rows = conn.execute("SELECT status, flag_tier, error FROM ai_calls ORDER BY id").fetchall()
    assert [(r[0], r[1]) for r in rows] == [("error", 1), ("success", 0)] and "unknown option" in rows[0][2]
    events = conn.execute("SELECT kind FROM system_events").fetchall()
    assert [e[0] for e in events] == ["claude_flag_error"]
    # the probe handles tiers itself: with the fallback disabled the usage error is simply classified `error`
    conn.execute("DELETE FROM system_events")
    result = run(conn, cfg_for("usage_error"), tier="1", fallback=False)
    assert result.status == "error" and conn.execute("SELECT COUNT(*) FROM ai_calls").fetchone()[0] == 3
    # the recorded kv tier drives the argv when no tier is given
    db.kv_set(conn, "claude.flag_tier", "1")
    assert runner.flag_tier(conn) == "1"
    ok = run(conn, cfg_for("ok"), tier=None)
    assert ok.ok and ledger.get_call(conn, ok.call_id)["flag_tier"] == 1


def test_probe_prompt_round_trip_through_the_fake(conn, cfg_for):
    result = run(conn, cfg_for("ok"), kind="probe", prompt=PROBE_PROMPT, schema="probe_v1", tier="1", system_prompt=PROBE_SYSTEM_PROMPT, budget=0.05)
    assert result.ok and result.structured == EXPECTED
    assert ledger.get_call(conn, result.call_id)["max_budget_usd"] == 0.05


def test_spawn_error_when_the_binary_is_missing(conn, settings, tmp_path):
    cfg = replace(settings, claude_bin=str(tmp_path / "missing-claude"))
    result = run(conn, cfg)
    assert result.status == "spawn_error" and not result.ok
    row = ledger.get_call(conn, result.call_id)
    assert row["status"] == "spawn_error" and "FileNotFoundError" in row["error"]


def test_an_oversized_argv_is_a_per_call_error_not_a_spawn_error(conn, cfg_for, monkeypatch):
    """A ≥ 128 KiB argv element makes ``execve`` fail with E2BIG. Classifying that ``spawn_error`` paused AI for every
    user (30-min pause + ``claude.available='0'`` + 「Claude CLI 未登录」) and re-armed for ever, since the same prompt
    came back each time; it is the prompt's fault, so it is an ordinary ``error`` for that job only."""
    huge = content.build_user_prompt([{"word": "x" * runner.MAX_ARG_BYTES, "dictionary_hint": "", "pos_hint": "", "stages": []}])
    spawned: list[list[str]] = []
    real_popen = runner.subprocess.Popen
    monkeypatch.setattr(runner.subprocess, "Popen", lambda argv, **kw: spawned.append(argv) or real_popen(argv, **kw))
    result = run(conn, cfg_for("ok"), prompt=huge)
    assert result.status == "error" and not result.ok and spawned == []  # refused before any spawn
    row = ledger.get_call(conn, result.call_id)
    assert row["status"] == "error" and "argument too long" in row["error"] and str(runner.MAX_ARG_BYTES) in row["error"] and row["finished_at"] == NOW
    # the kernel's own refusal (E2BIG / ENAMETOOLONG) is classified the same way …
    def e2big(argv, **kw):
        raise OSError(errno.E2BIG, "Argument list too long", argv[0])

    monkeypatch.setattr(runner.subprocess, "Popen", e2big)
    result = run(conn, cfg_for("ok"))
    assert result.status == "error" and "Argument list too long" in ledger.get_call(conn, result.call_id)["error"]
    # … while a missing / unusable binary stays a spawn_error
    def enoent(argv, **kw):
        raise FileNotFoundError(errno.ENOENT, "No such file or directory", argv[0])

    monkeypatch.setattr(runner.subprocess, "Popen", enoent)
    assert run(conn, cfg_for("ok")).status == "spawn_error"
    assert [r[0] for r in conn.execute("SELECT status FROM ai_calls ORDER BY id")] == ["error", "error", "spawn_error"]
    # the limit itself: one byte under passes, the limit fails (Linux MAX_ARG_STRLEN = 32 pages, NUL included)
    assert runner.oversized_arg(["x" * (runner.MAX_ARG_BYTES - 1), "-p"]) is None
    assert runner.oversized_arg(["-p", "x" * runner.MAX_ARG_BYTES]) == runner.MAX_ARG_BYTES
    assert runner.oversized_arg(["中" * (runner.MAX_ARG_BYTES // 3 + 1)]) == 3 * (runner.MAX_ARG_BYTES // 3 + 1)  # bytes, not characters


# ------------------------------------------------------------------------------------------- parsing
def envelope(**over):
    base = {"type": "result", "subtype": "success", "is_error": False, "structured_output": {"a": 1}, "total_cost_usd": 0.01, "duration_ms": 5, "usage": {"input_tokens": 1, "output_tokens": 2, "cache_read_input_tokens": 3, "cache_creation_input_tokens": 4}, "modelUsage": {"claude-sonnet-5-5": {}}, "session_id": "s"}
    base.update(over)
    return json.dumps(base)


def test_parse_and_classify_table():
    p = runner.parse_and_classify(0, envelope(), "")
    assert p.status == "success" and p.structured == {"a": 1} and p.model_used == "claude-sonnet-5-5" and p.tokens["cache_read_tokens"] == 3 and p.session_id == "s"
    assert runner.parse_and_classify(0, "noise\n" + envelope(), "").status == "success"  # last result line wins
    assert runner.parse_and_classify(1, envelope(subtype="error_max_budget_usd", is_error=True, total_cost_usd=0.25), "").status == "budget"
    assert runner.parse_and_classify(1, "", "Not logged in. Please run claude login").status == "auth"
    assert runner.parse_and_classify(1, "", "API overloaded (529)").status == "overloaded"
    assert runner.parse_and_classify(1, "", "rate limit exceeded").status == "overloaded"
    assert runner.parse_and_classify(0, "garbage {{{", "").status == "error"
    assert runner.parse_and_classify(0, envelope(structured_output="not a dict"), "").status == "error"
    assert runner.parse_and_classify(0, envelope(is_error=True), "").status == "error"
    assert runner.parse_and_classify(2, envelope(), "").status == "error"
    usage = runner.parse_and_classify(1, "", "error: unknown option '--restricted'")
    assert usage.status == "error" and usage.usage_error
    assert runner.parse_and_classify(1, envelope(subtype="error_during_execution", is_error=True, total_cost_usd=0.03), "x" * 5000).cost_usd == 0.03
    assert len(runner.parse_and_classify(1, "", "x" * 5000).error) == 1000
    assert runner.parse_and_classify(0, envelope(modelUsage={}), "").model_used is None  # modelUsage absent → None (model_requested is stored)


def test_prune_logs_removes_old_day_directories(settings):
    logs = settings.claude_logs_dir
    for day in ("2026-09-01", "2026-09-29", "2026-09-30", "2026-10-14"):
        (logs / day).mkdir(parents=True, exist_ok=True)
        (logs / day / "1.json").write_text("{}")
    (logs / "not-a-day").mkdir(exist_ok=True)
    assert runner.prune_logs(settings, NOW) == 2  # keep 14 days: 2026-09-30 is the cutoff (kept), 09-29 and 09-01 go
    assert sorted(p.name for p in logs.iterdir()) == ["2026-09-30", "2026-10-14", "not-a-day"]
    assert runner.prune_logs(settings, NOW) == 0
