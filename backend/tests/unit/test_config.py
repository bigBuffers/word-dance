"""config.Settings.from_env: defaults, validation, clamps, derived values, admin config entries, and the fallback-provider
keys of docs/AI_FALLBACK_MODEL.md §4.3 (CLAUDE_INTEGRATION §10.1): the WD_AI_FALLBACK_MODEL rename trap, the auto / openai_http
prerequisites, the base URL scheme rule, the key file, the kinds parser, the price table and the ranges / choices."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

import pytest

from wd.config import DEFAULT_SEED_PATH, REPO_ROOT, ConfigError, Settings

# a fully configured fallback provider (kind, base URL, model, key) with the default mode claude_cli
FALLBACK_ENV = {
    "WD_AI_FALLBACK_KIND": "openai_http",
    "WD_AI_FALLBACK_BASE_URL": "https://open.bigmodel.cn/api/paas/v4",
    "WD_AI_FALLBACK_MODEL": "glm-4.7-flash",
    "WD_AI_FALLBACK_API_KEY": "k",
}


def test_defaults_without_environment():
    cfg = Settings.from_env({})
    assert cfg.data_dir == Path("/home/sqin/word-dance-data")
    assert cfg.db_path == cfg.data_dir / "word-dance.db"
    assert cfg.seed_path == DEFAULT_SEED_PATH == REPO_ROOT / "data" / "seed" / "vocab.jsonl.gz"
    assert cfg.claude_cwd == cfg.data_dir / "claude-cwd"
    assert (cfg.host, cfg.port, cfg.tz, cfg.registration_mode) == ("0.0.0.0", 8000, "Asia/Shanghai", "invite")
    assert cfg.ai_batch_size == 10 and cfg.ai_concurrency == 1
    assert cfg.image_providers == ("wikimedia", "openverse")
    assert cfg.ai_daily_budget_usd == 3.0 and cfg.ai_monthly_budget_usd == 40.0 and cfg.ai_svg_daily_budget_usd == 0.5
    assert cfg.max_body_bytes == 1_048_576 and cfg.session_days == 30 and cfg.prebuild_hours == 3
    assert cfg.secret_key.startswith("ephemeral-")  # random per process when unset
    assert cfg.email_configured is False and cfg.public_origin is None and cfg.cookie_secure_effective is False
    assert cfg.contact_email_effective == "admin@localhost"
    assert cfg.env_sources == frozenset()


def test_env_overrides_and_sources(tmp_path: Path):
    cfg = Settings.from_env({"WD_DATA_DIR": str(tmp_path), "WD_PORT": "8010", "WD_PUBLIC_URL": "https://words.example.com/", "WD_SECRET_KEY": "s", "WD_SMTP_HOST": "smtp.example.com", "WD_SMTP_FROM": "wd@example.com"})
    assert cfg.data_dir == tmp_path.resolve() and cfg.db_path == tmp_path.resolve() / "word-dance.db"
    assert cfg.port == 8010 and cfg.public_url == "https://words.example.com"
    assert cfg.public_origin == "https://words.example.com" and cfg.cookie_secure_effective is True
    assert cfg.email_configured is True
    entries = {e["key"]: e for e in cfg.entries()}
    assert entries["WD_PORT"] == {"key": "WD_PORT", "value": "8010", "source": "env"}
    assert entries["WD_HOST"]["source"] == "default"
    assert entries["WD_SECRET_KEY"]["value"] == "***"
    assert entries["WD_SMTP_PASSWORD"]["value"] == ""  # empty secret stays empty, not masked
    assert entries["WD_IMAGE_PROVIDERS"]["value"] == "wikimedia,openverse"
    assert entries["WD_WORKER_ENABLED"]["value"] == "1"


def test_batch_size_and_concurrency_are_clamped_not_rejected():
    assert Settings.from_env({"WD_AI_BATCH_SIZE": "50"}).ai_batch_size == 12
    assert Settings.from_env({"WD_AI_BATCH_SIZE": "0"}).ai_batch_size == 1
    assert Settings.from_env({"WD_AI_CONCURRENCY": "9"}).ai_concurrency == 3


@pytest.mark.parametrize(
    "env",
    [
        {"WD_TZ": "Mars/Olympus"},
        {"WD_PORT": "70000"},
        {"WD_PORT": "abc"},
        {"WD_REGISTRATION_MODE": "anyone"},
        {"WD_SMTP_TLS": "maybe"},
        {"WD_COOKIE_SECURE": "yes"},
        {"WD_WORKER_ENABLED": "maybe"},
        {"WD_IMAGE_PROVIDERS": "wikimedia,unsplash"},
        {"WD_PUBLIC_URL": "words.example.com"},
        {"WD_AI_DAILY_BUDGET_USD": "-1"},
        {"WD_LOG_LEVEL": "LOUD"},
        {"WD_PREBUILD_HOURS": "30"},
        # fallback provider (docs/AI_FALLBACK_MODEL.md §4.3)
        {"WD_AI_FALLBACK_MODEL": "haiku"},  # the pre-0010 CLI key: kind none + a model is the rename trap
        {"WD_AI_PROVIDER": "auto"},
        {"WD_AI_PROVIDER": "openai_http"},
        {"WD_AI_PROVIDER": "auto", "WD_AI_FALLBACK_KIND": "openai_http", "WD_AI_FALLBACK_BASE_URL": "https://x.example/v1", "WD_AI_FALLBACK_MODEL": "m"},  # no key
        {"WD_AI_PROVIDER": "claude"},
        {"WD_AI_FALLBACK_KIND": "anthropic"},
        {"WD_AI_FALLBACK_KINDS": "lookup,svg"},
        {"WD_AI_FALLBACK_BASE_URL": "open.bigmodel.cn/api/paas/v4"},
        {"WD_AI_FALLBACK_PRICE_JSON": "[1]"},
        {"WD_AI_FALLBACK_PRICE_JSON": '{"input": "a"}'},
        {"WD_AI_FALLBACK_TIMEOUT_SCALE": "9"},
        {"WD_AI_CNY_PER_USD": "0"},
        {"WD_AI_FAILOVER_COOLDOWN_MIN": "0"},
        {"WD_AI_FALLBACK_DIALECT": "openai"},
        {"WD_AI_FALLBACK_PREWARM": "maybe"},
    ],
)
def test_invalid_values_raise_config_error(env):
    with pytest.raises(ConfigError):
        Settings.from_env(env)


def test_keyed_providers_are_appended_and_flags_parse():
    cfg = Settings.from_env({"WD_PIXABAY_KEY": "k", "WD_IMAGE_PROVIDERS": "wikimedia"})
    assert cfg.image_providers == ("wikimedia", "pixabay")
    assert Settings.from_env({"WD_DEV": "true"}).dev is True
    assert Settings.from_env({"WD_AI_ENABLED": "off"}).ai_enabled is False
    assert Settings.from_env({"WD_COOKIE_SECURE": "1"}).cookie_secure_effective is True
    assert Settings.from_env({"WD_COOKIE_SECURE": "0", "WD_PUBLIC_URL": "https://x.example"}).cookie_secure_effective is False


def test_test_environment_fixture(settings, data_dir):
    assert settings.data_dir == data_dir.resolve()
    assert settings.worker_enabled is False
    assert settings.seed_path.name == "mini_seed.jsonl"
    for d in settings.runtime_dirs():
        assert d.is_dir()


# ------------------------------------------------------------------------------ fallback provider (AI_FALLBACK_MODEL §4.3)
def test_fallback_defaults_leave_the_cli_path_alone():
    cfg = Settings.from_env({})
    assert cfg.ai_provider == "claude_cli" and cfg.ai_fallback_kind == "none" and cfg.fallback_configured is False
    assert (cfg.ai_fallback_base_url, cfg.ai_fallback_api_key, cfg.ai_fallback_api_key_file, cfg.ai_fallback_model) == ("", "", "", "")
    assert cfg.ai_cli_fallback_model == ""
    assert cfg.ai_fallback_kinds == ("content", "lookup", "consolidate") and cfg.ai_fallback_prewarm is False  # content by default since slice 2
    assert (cfg.ai_fallback_dialect, cfg.ai_fallback_json_mode, cfg.ai_fallback_thinking) == ("auto", "auto", "off")
    assert cfg.ai_fallback_timeout_scale == 1.5 and cfg.ai_fallback_max_output_tokens == 0 and cfg.ai_fallback_hourly_call_cap == 40
    assert cfg.ai_fallback_batch_size == 5
    assert cfg.ai_fallback_price_json == "" and cfg.ai_cny_per_usd == 7.2
    assert (cfg.ai_failover_cooldown_min, cfg.ai_failover_probe_every_min) == (30, 30)
    assert (cfg.ai_failover_overloaded_after, cfg.ai_failover_timeout_after, cfg.ai_failover_network_after) == (3, 2, 2)


def test_fallback_model_rename_trap():
    """DEPLOY §4 / §10: the pre-0010 ``WD_AI_FALLBACK_MODEL`` (the CLI's --fallback-model) refuses to start with a hint
    naming ``WD_AI_CLI_FALLBACK_MODEL``; the new key works, and the old name keeps its new meaning once a fallback
    provider is configured."""
    with pytest.raises(ConfigError, match="WD_AI_CLI_FALLBACK_MODEL"):
        Settings.from_env({"WD_AI_FALLBACK_MODEL": "haiku"})
    cfg = Settings.from_env({"WD_AI_CLI_FALLBACK_MODEL": "haiku"})
    assert cfg.ai_cli_fallback_model == "haiku" and cfg.ai_fallback_model == "" and cfg.fallback_configured is False
    assert {e["key"]: e["value"] for e in cfg.entries()}["WD_AI_CLI_FALLBACK_MODEL"] == "haiku"
    assert Settings.from_env({**FALLBACK_ENV, "WD_AI_FALLBACK_MODEL": "qwen3.7-flash"}).ai_fallback_model == "qwen3.7-flash"


@pytest.mark.parametrize("mode", ["auto", "openai_http"])
def test_auto_and_openai_http_need_a_fully_configured_fallback(mode):
    with pytest.raises(ConfigError, match="WD_AI_FALLBACK_KIND=openai_http"):
        Settings.from_env({"WD_AI_PROVIDER": mode})
    for missing in FALLBACK_ENV:
        env = {k: v for k, v in FALLBACK_ENV.items() if k != missing}
        env["WD_AI_PROVIDER"] = mode
        with pytest.raises(ConfigError):
            Settings.from_env(env)
    cfg = Settings.from_env({**FALLBACK_ENV, "WD_AI_PROVIDER": mode})
    assert cfg.ai_provider == mode and cfg.fallback_configured is True
    assert {e["key"]: e["value"] for e in cfg.entries()}["WD_AI_FALLBACK_API_KEY"] == "***"  # a secret (API.md 73)
    # a configured but unused fallback is fine in the default mode
    assert Settings.from_env(FALLBACK_ENV).ai_provider == "claude_cli"


def test_key_file_alone_satisfies_the_prerequisite(tmp_path: Path):
    key_file = tmp_path / "fallback.key"
    key_file.write_text("sk-test\n", encoding="utf-8")
    key_file.chmod(0o600)
    env = {k: v for k, v in FALLBACK_ENV.items() if k != "WD_AI_FALLBACK_API_KEY"}
    env.update({"WD_AI_PROVIDER": "auto", "WD_AI_FALLBACK_API_KEY_FILE": str(key_file)})
    cfg = Settings.from_env(env)
    assert cfg.fallback_configured is True and cfg.ai_fallback_api_key == "" and cfg.ai_fallback_api_key_file == str(key_file)
    entries = {e["key"]: e["value"] for e in cfg.entries()}
    assert entries["WD_AI_FALLBACK_API_KEY_FILE"] == str(key_file) and entries["WD_AI_FALLBACK_API_KEY"] == ""  # a path, not a secret


def test_key_file_must_exist_and_be_a_readable_regular_file(tmp_path: Path, caplog: pytest.LogCaptureFixture):
    """Checked at startup (the adapter used to discover a typo only at the first fallback call, as spawn_error)."""
    missing = tmp_path / "missing.key"
    with pytest.raises(ConfigError, match=re.escape(str(missing))):
        Settings.from_env({"WD_AI_FALLBACK_API_KEY_FILE": str(missing)})
    with pytest.raises(ConfigError, match=re.escape(str(tmp_path))):
        Settings.from_env({"WD_AI_FALLBACK_API_KEY_FILE": str(tmp_path)})  # a directory
    locked = tmp_path / "locked.key"
    locked.write_text("k\n", encoding="utf-8")
    locked.chmod(0o000)
    try:
        if os.geteuid() != 0:  # root reads everything; os.access says so
            with pytest.raises(ConfigError, match="not readable"):
                Settings.from_env({"WD_AI_FALLBACK_API_KEY_FILE": str(locked)})
    finally:
        locked.chmod(0o600)
    # group/other-readable is a warning, not an error (the adapter repeats it per call)
    loose = tmp_path / "loose.key"
    loose.write_text("k\n", encoding="utf-8")
    loose.chmod(0o644)
    with caplog.at_level(logging.WARNING, logger="wd.config"):
        assert Settings.from_env({"WD_AI_FALLBACK_API_KEY_FILE": str(loose)}).ai_fallback_api_key_file == str(loose)
    assert any("chmod 600" in r.getMessage() and str(loose) in r.getMessage() for r in caplog.records), caplog.text


def test_base_url_scheme_rule_and_trailing_slash(caplog: pytest.LogCaptureFixture):
    """The WD_PUBLIC_URL rule: http(s) with a host (a scheme-less value would fail every call as a soft ``network:``
    error, CLAUDE_INTEGRATION §10.3); plain http:// is fine on loopback (mock server, local gateway) and warns elsewhere."""
    for bad in ("open.bigmodel.cn/api/paas/v4", "ftp://open.bigmodel.cn/v4", "https://", "https:///api/paas/v4", "mailto:x@y"):
        with pytest.raises(ConfigError, match="WD_AI_FALLBACK_BASE_URL"):
            Settings.from_env({"WD_AI_FALLBACK_BASE_URL": bad})
    assert Settings.from_env({"WD_AI_FALLBACK_BASE_URL": "https://open.bigmodel.cn/api/paas/v4/"}).ai_fallback_base_url == "https://open.bigmodel.cn/api/paas/v4"
    assert Settings.from_env({"WD_AI_FALLBACK_BASE_URL": "HTTPS://dashscope.aliyuncs.com/compatible-mode/v1"}).ai_fallback_base_url == "HTTPS://dashscope.aliyuncs.com/compatible-mode/v1"
    with caplog.at_level(logging.WARNING, logger="wd.config"):
        assert Settings.from_env({"WD_AI_FALLBACK_BASE_URL": "http://127.0.0.1:8765/v1/"}).ai_fallback_base_url == "http://127.0.0.1:8765/v1"
        assert Settings.from_env({"WD_AI_FALLBACK_BASE_URL": "http://localhost:8765/v1"}).ai_fallback_base_url == "http://localhost:8765/v1"
        assert Settings.from_env({"WD_AI_FALLBACK_BASE_URL": "http://[::1]:8765/v1"}).ai_fallback_base_url == "http://[::1]:8765/v1"
    assert not [r for r in caplog.records if "cleartext" in r.getMessage()], caplog.text
    with caplog.at_level(logging.WARNING, logger="wd.config"):
        assert Settings.from_env({"WD_AI_FALLBACK_BASE_URL": "http://gateway.lan:8080/v1"}).ai_fallback_base_url == "http://gateway.lan:8080/v1"
    assert [r for r in caplog.records if "cleartext" in r.getMessage() and "gateway.lan" in r.getMessage()], caplog.text


def test_fallback_kinds_parse_case_and_duplicates_and_reject_svg():
    assert Settings.from_env({"WD_AI_FALLBACK_KINDS": " Lookup, CONTENT ,lookup,, "}).ai_fallback_kinds == ("lookup", "content")
    assert Settings.from_env({"WD_AI_FALLBACK_KINDS": "content,lookup,consolidate"}).ai_fallback_kinds == ("content", "lookup", "consolidate")
    for blank in ("", " ", ",", " , ", "\t", ",,"):  # empty or blank = the default (DEPLOY §4); never an empty list that auto mode would switch to
        assert Settings.from_env({"WD_AI_FALLBACK_KINDS": blank}).ai_fallback_kinds == ("content", "lookup", "consolidate"), repr(blank)
    assert Settings.from_env({"WD_AI_FALLBACK_KINDS": "lookup"}).ai_fallback_kinds == ("lookup",)  # a real list is kept as given
    assert Settings.from_env({"WD_AI_FALLBACK_KINDS": "lookup,consolidate"}).ai_fallback_kinds == ("lookup", "consolidate")  # content removed: example generation stays on the CLI
    for bad in ("lookup,svg", "svg", "probe", "lookup;consolidate", "lookups"):
        with pytest.raises(ConfigError, match="WD_AI_FALLBACK_KINDS"):
            Settings.from_env({"WD_AI_FALLBACK_KINDS": bad})
    assert {e["key"]: e["value"] for e in Settings.from_env({"WD_AI_FALLBACK_KINDS": "consolidate"}).entries()}["WD_AI_FALLBACK_KINDS"] == "consolidate"


def test_fallback_batch_size_is_clamped_like_the_cli_batch(caplog: pytest.LogCaptureFixture):
    """DEPLOY §4: ``WD_AI_FALLBACK_BATCH_SIZE`` (words per ``generate_content`` call while the fallback takes the group,
    CLAUDE_INTEGRATION §10.5) follows the ``WD_AI_BATCH_SIZE`` rule — clamped to 1–12 with a warning, never rejected;
    only a non-integer is a ConfigError."""
    with caplog.at_level(logging.WARNING, logger="wd.config"):
        assert Settings.from_env({"WD_AI_FALLBACK_BATCH_SIZE": "0"}).ai_fallback_batch_size == 1
        assert Settings.from_env({"WD_AI_FALLBACK_BATCH_SIZE": "50"}).ai_fallback_batch_size == 12
    clamped = [r.getMessage() for r in caplog.records if "WD_AI_FALLBACK_BATCH_SIZE" in r.getMessage() and "clamped" in r.getMessage()]
    assert len(clamped) == 2, caplog.text
    assert Settings.from_env({"WD_AI_FALLBACK_BATCH_SIZE": "7"}).ai_fallback_batch_size == 7
    assert Settings.from_env({"WD_AI_FALLBACK_BATCH_SIZE": "12"}).ai_fallback_batch_size == 12
    with pytest.raises(ConfigError, match="WD_AI_FALLBACK_BATCH_SIZE"):
        Settings.from_env({"WD_AI_FALLBACK_BATCH_SIZE": "abc"})
    entries = {e["key"]: e for e in Settings.from_env({"WD_AI_FALLBACK_BATCH_SIZE": "7"}).entries()}
    assert entries["WD_AI_FALLBACK_BATCH_SIZE"] == {"key": "WD_AI_FALLBACK_BATCH_SIZE", "value": "7", "source": "env"}
    assert {e["key"]: e["value"] for e in Settings.from_env({}).entries()}["WD_AI_FALLBACK_BATCH_SIZE"] == "5"
    # independent of the CLI batch: the effective fallback group is min(WD_AI_BATCH_SIZE, WD_AI_FALLBACK_BATCH_SIZE) at claim time (failover.group_cap)
    cfg = Settings.from_env({"WD_AI_BATCH_SIZE": "3", "WD_AI_FALLBACK_BATCH_SIZE": "8"})
    assert (cfg.ai_batch_size, cfg.ai_fallback_batch_size) == (3, 8)


def test_price_json_validation():
    """Names exactly input / output (+ optional cache_read): a mis-keyed table would charge nothing for a paid leg
    (the adapter reads the names with .get(…, 0.0)); '' and {} are the documented free tier."""
    for bad in (
        "{",
        "[1]",
        "null",
        '"0.2"',
        '{"input": "a", "output": 1}',
        '{"input": -1, "output": 1}',
        '{"input": true, "output": 1}',
        '{"in": 0.2, "out": 0.8}',
        '{"input": 0.2, "output": 0.8, "cached": 0.04}',
        '{"input": 0.2}',
        '{"output": 0.8, "cache_read": 0.04}',
    ):
        with pytest.raises(ConfigError, match="WD_AI_FALLBACK_PRICE_JSON"):
            Settings.from_env({"WD_AI_FALLBACK_PRICE_JSON": bad})
    assert Settings.from_env({"WD_AI_FALLBACK_PRICE_JSON": ""}).ai_fallback_price_json == ""
    assert Settings.from_env({"WD_AI_FALLBACK_PRICE_JSON": "{}"}).ai_fallback_price_json == "{}"
    for ok in ('{"input": 0.2, "output": 0.8}', '{"input": 0, "output": 2}', '{"input": 0.2, "output": 0.8, "cache_read": 0.04}'):
        assert Settings.from_env({"WD_AI_FALLBACK_PRICE_JSON": ok}).ai_fallback_price_json == ok


def test_fallback_number_ranges():
    assert Settings.from_env({"WD_AI_FALLBACK_TIMEOUT_SCALE": "2"}).ai_fallback_timeout_scale == 2.0
    assert Settings.from_env({"WD_AI_FALLBACK_TIMEOUT_SCALE": "0.5"}).ai_fallback_timeout_scale == 0.5
    assert Settings.from_env({"WD_AI_FALLBACK_TIMEOUT_SCALE": "5"}).ai_fallback_timeout_scale == 5.0
    assert Settings.from_env({"WD_AI_CNY_PER_USD": "7.3"}).ai_cny_per_usd == 7.3
    assert Settings.from_env({"WD_AI_FALLBACK_MAX_OUTPUT_TOKENS": "16384"}).ai_fallback_max_output_tokens == 16384
    assert Settings.from_env({"WD_AI_FAILOVER_COOLDOWN_MIN": "1440", "WD_AI_FAILOVER_TIMEOUT_AFTER": "1"}).ai_failover_cooldown_min == 1440
    for env in (
        {"WD_AI_FALLBACK_TIMEOUT_SCALE": "0.1"},
        {"WD_AI_FALLBACK_TIMEOUT_SCALE": "5.5"},
        {"WD_AI_FALLBACK_TIMEOUT_SCALE": "fast"},
        {"WD_AI_CNY_PER_USD": "-7"},
        {"WD_AI_CNY_PER_USD": "1001"},
        {"WD_AI_CNY_PER_USD": "seven"},
        {"WD_AI_FAILOVER_PROBE_EVERY_MIN": "1441"},
        {"WD_AI_FAILOVER_OVERLOADED_AFTER": "0"},
        {"WD_AI_FAILOVER_TIMEOUT_AFTER": "101"},
        {"WD_AI_FAILOVER_NETWORK_AFTER": "0"},
        {"WD_AI_FALLBACK_HOURLY_CALL_CAP": "0"},
        {"WD_AI_FALLBACK_MAX_OUTPUT_TOKENS": "-1"},
        {"WD_AI_FALLBACK_MAX_OUTPUT_TOKENS": "131073"},
    ):
        with pytest.raises(ConfigError, match=next(iter(env))):
            Settings.from_env(env)


@pytest.mark.parametrize(
    ("name", "allowed"),
    [
        ("WD_AI_FALLBACK_DIALECT", ("auto", "zhipu", "bailian", "deepseek", "generic")),
        ("WD_AI_FALLBACK_JSON_MODE", ("auto", "json_object", "json_schema")),
        ("WD_AI_FALLBACK_THINKING", ("off", "on", "default")),
        ("WD_AI_FALLBACK_KIND", ("none", "openai_http")),
        ("WD_AI_PROVIDER", ("claude_cli",)),
    ],
)
def test_fallback_choices(name: str, allowed: tuple[str, ...]):
    field = name[len("WD_") :].lower()
    for value in allowed:
        assert getattr(Settings.from_env({name: value}), field) == value
    for bad in ("openai", "Auto", "1"):
        with pytest.raises(ConfigError, match=name):
            Settings.from_env({name: bad})


def _idle_kinds(message: str) -> set[str]:
    """The kinds the openai_http startup warning names as waiting (``…: content/consolidate jobs wait indefinitely …``)."""
    m = re.search(r":\s*([a-z_/]+) jobs wait indefinitely", message)
    assert m, message
    return set(m.group(1).split("/"))


def test_openai_http_without_content_in_kinds_warns_that_content_and_svg_wait(caplog: pytest.LogCaptureFixture):
    """CLAUDE_INTEGRATION §10.1: in openai_http mode a kind outside WD_AI_FALLBACK_KINDS is never routable (the CLI is never
    spawned) — a startup warning, never a ConfigError (the mode is the documented emergency switch). The default list names
    every routable kind since slice 2, so the warning fires only when the operator REMOVED one."""
    with caplog.at_level(logging.WARNING, logger="wd.config"):
        cfg = Settings.from_env({**FALLBACK_ENV, "WD_AI_PROVIDER": "openai_http"})  # the default: nothing waits but svg
        Settings.from_env({**FALLBACK_ENV, "WD_AI_PROVIDER": "openai_http", "WD_AI_FALLBACK_KINDS": "consolidate,content,lookup"})
        Settings.from_env({**FALLBACK_ENV, "WD_AI_PROVIDER": "openai_http", "WD_AI_FALLBACK_KINDS": " , "})  # blank = the default: nothing waits either
        Settings.from_env({**FALLBACK_ENV, "WD_AI_PROVIDER": "auto", "WD_AI_FALLBACK_KINDS": "lookup"})  # auto: the CLI still serves the rest
        Settings.from_env({**FALLBACK_ENV, "WD_AI_FALLBACK_KINDS": "lookup"})
    assert cfg.ai_provider == "openai_http" and cfg.ai_fallback_kinds == ("content", "lookup", "consolidate")
    assert not [r for r in caplog.records if "indefinitely" in r.getMessage()], caplog.text
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="wd.config"):
        cfg = Settings.from_env({**FALLBACK_ENV, "WD_AI_PROVIDER": "openai_http", "WD_AI_FALLBACK_KINDS": "lookup,consolidate"})
    assert cfg.ai_fallback_kinds == ("lookup", "consolidate")
    warnings = [r.getMessage() for r in caplog.records if r.name == "wd.config" and "indefinitely" in r.getMessage()]
    assert len(warnings) == 1 and "content" in warnings[0] and "svg" in warnings[0] and "WD_AI_FALLBACK_KINDS" in warnings[0], caplog.text
    assert _idle_kinds(warnings[0]) == {"content"}
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="wd.config"):
        Settings.from_env({**FALLBACK_ENV, "WD_AI_PROVIDER": "openai_http", "WD_AI_FALLBACK_KINDS": "lookup"})
    warnings = [r.getMessage() for r in caplog.records if r.name == "wd.config" and "indefinitely" in r.getMessage()]
    assert len(warnings) == 1 and "svg" in warnings[0] and "WD_AI_FALLBACK_KINDS" in warnings[0], caplog.text
    assert _idle_kinds(warnings[0]) == {"content", "consolidate"}
