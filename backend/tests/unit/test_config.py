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
    assert cfg.image_kid_stages == ()  # the child picture style is off until the pilot (PLAN §5.1 C3)
    assert cfg.ai_daily_budget_usd == 3.0 and cfg.ai_monthly_budget_usd == 40.0 and cfg.ai_svg_daily_budget_usd == 0.5
    assert cfg.ai_dance_daily_budget_usd == 0.5 and cfg.ai_budget_dance == 0.25 and cfg.ai_timeout_dance_sec == 120  # 单词之舞 annotations (P2)
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
        {"WD_IMAGE_KID_STAGES": "xx"},
        {"WD_IMAGE_KID_STAGES": "xs,cet9"},
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
        # sign-in by verification code (docs/AUTH_SIGNUP_DESIGN.md §5.2)
        {"WD_SMS_PROVIDER": "twilio"},
        {"WD_SMS_PROVIDER": "aliyun_verify"},  # no key id / secret file / signature
        {"WD_MAIL_PROVIDER": "tencent_ses"},
        {"WD_MAIL_PROVIDER": "aliyun_dm"},  # no key id / secret file / from-address
        {"WD_CAPTCHA": "1"},
        {"WD_SMS_DAILY_CAP": "-1"},
        {"WD_SMS_HOURLY_CAP": "100001"},
        {"WD_CODE_IP_HOURLY": "0"},
        {"WD_PHONE_STALE_DAYS": "0"},
        {"WD_PHONE_STALE_DAYS": "3651"},
        {"WD_AI_USER_DAILY_WORDS": "-1"},
        {"WD_AI_USER_DAILY_WORDS": "many"},
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


def test_image_kid_stages_parse_as_stage_codes():
    """DEPLOY §4 `WD_IMAGE_KID_STAGES`: a comma list of stage codes (images/style.style_for), empty or blank = off, case and
    duplicates folded, an unknown code is a ConfigError naming the variable and the allowed codes (schemas.STAGE_ORDER)."""
    from wd.schemas import STAGE_ORDER

    assert Settings.from_env({}).image_kid_stages == ()
    for blank in ("", " ", ",", " , "):
        assert Settings.from_env({"WD_IMAGE_KID_STAGES": blank}).image_kid_stages == (), repr(blank)
    assert Settings.from_env({"WD_IMAGE_KID_STAGES": "zk, gk"}).image_kid_stages == ("zk", "gk")
    assert Settings.from_env({"WD_IMAGE_KID_STAGES": "xs"}).image_kid_stages == ("xs",)
    assert Settings.from_env({"WD_IMAGE_KID_STAGES": " XS ,zk,xs,, "}).image_kid_stages == ("xs", "zk")
    assert Settings.from_env({"WD_IMAGE_KID_STAGES": ",".join(STAGE_ORDER)}).image_kid_stages == STAGE_ORDER
    with pytest.raises(ConfigError, match="WD_IMAGE_KID_STAGES") as e:
        Settings.from_env({"WD_IMAGE_KID_STAGES": "xx"})
    assert "xs, zk, gk, cet4, cet6" in str(e.value)
    with pytest.raises(ConfigError, match="WD_IMAGE_KID_STAGES"):
        Settings.from_env({"WD_IMAGE_KID_STAGES": "xs;zk"})
    entries = {e["key"]: e for e in Settings.from_env({"WD_IMAGE_KID_STAGES": "zk, gk"}).entries()}
    assert entries["WD_IMAGE_KID_STAGES"] == {"key": "WD_IMAGE_KID_STAGES", "value": "zk,gk", "source": "env"}
    assert {e["key"]: e for e in Settings.from_env({}).entries()}["WD_IMAGE_KID_STAGES"] == {"key": "WD_IMAGE_KID_STAGES", "value": "", "source": "default"}


def test_claude_bin_relative_path_is_made_absolute(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """DEPLOY §4 `WD_CLAUDE_BIN`: the CLI is spawned in `claude_cwd`, not where the service started, so a relative path
    (`backend/tests/fake_claude.py` from the repository root — the PLAN §6 S5 rehearsal and the `make dev` forms) is made
    absolute against the start-up working directory like every other path setting; an absolute path is kept verbatim (no
    symlink resolution — the CLI may locate its install through argv[0]) and a bare command name stays a PATH lookup."""
    monkeypatch.chdir(tmp_path)
    cwd = Path(os.getcwd())
    assert Settings.from_env({"WD_CLAUDE_BIN": "backend/tests/fake_claude.py"}).claude_bin == str(cwd / "backend" / "tests" / "fake_claude.py")
    assert Settings.from_env({"WD_CLAUDE_BIN": "./bin/claude-wrapper"}).claude_bin == str(cwd / "bin" / "claude-wrapper")
    assert Settings.from_env({"WD_CLAUDE_BIN": " ../x/claude "}).claude_bin == str(cwd.parent / "x" / "claude")
    assert Settings.from_env({"WD_CLAUDE_BIN": "/opt/claude/bin/claude"}).claude_bin == "/opt/claude/bin/claude"
    assert Settings.from_env({"WD_CLAUDE_BIN": "~/bin/claude"}).claude_bin == os.path.expanduser("~/bin/claude")
    assert Settings.from_env({"WD_CLAUDE_BIN": "claude"}).claude_bin == "claude"
    assert Settings.from_env({}).claude_bin == "/home/sqin/.local/bin/claude"
    entries = {e["key"]: e for e in Settings.from_env({"WD_CLAUDE_BIN": "bin/claude"}).entries()}
    assert entries["WD_CLAUDE_BIN"] == {"key": "WD_CLAUDE_BIN", "value": str(cwd / "bin" / "claude"), "source": "env"}


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


@pytest.mark.parametrize("mode", ["auto", "openai_http", "split"])
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


# ------------------------------------------------------------- sign-in by verification code (docs/AUTH_SIGNUP_DESIGN.md §5.2, DEPLOY §4)
def _aliyun_env(tmp_path: Path) -> dict[str, str]:
    """A 0600 secret file plus the key id and signature — what `aliyun_verify` needs."""
    secret = tmp_path / "aliyun.secret"
    secret.write_text("sk-aliyun-test\n", encoding="utf-8")
    secret.chmod(0o600)
    return {"WD_ALIYUN_ACCESS_KEY_ID": "LTAI5t-test", "WD_ALIYUN_ACCESS_KEY_SECRET_FILE": str(secret), "WD_ALIYUN_SMS_SIGN_NAME": "速通验证"}


def test_sign_in_by_code_defaults_keep_todays_behaviour():
    """An upgraded .env without the new keys (install.sh appends none) behaves exactly as before 0018: no SMS, SMTP mail, captcha
    only in front of the (not yet offered) public code sends, the design's caps, and the per-user AI quota at 80 words/day.
    (Kept apart from test_defaults_without_environment, whose `/home/...` path assertions are Linux-only.)"""
    cfg = Settings.from_env({})
    assert (cfg.sms_provider, cfg.mail_provider, cfg.captcha) == ("off", "smtp", "on")
    assert (cfg.aliyun_access_key_id, cfg.aliyun_access_key_secret_file, cfg.aliyun_sms_sign_name) == ("", "", "")
    assert (cfg.sms_daily_cap, cfg.sms_hourly_cap, cfg.code_ip_hourly, cfg.phone_stale_days) == (200, 40, 20, 90)
    assert cfg.ai_user_daily_words == 80
    assert cfg.sms_configured is False and cfg.email_configured is False and cfg.registration_mode == "invite"


def test_registration_mode_verified_is_a_choice():
    """DEPLOY §4: `verified` joins open / invite / closed (the code sign-in creates the accounts, docs/AUTH_SIGNUP_DESIGN.md D2)."""
    assert Settings.from_env({"WD_REGISTRATION_MODE": "verified"}).registration_mode == "verified"
    for mode in ("open", "invite", "closed"):
        assert Settings.from_env({"WD_REGISTRATION_MODE": mode}).registration_mode == mode
    with pytest.raises(ConfigError, match="WD_REGISTRATION_MODE"):
        Settings.from_env({"WD_REGISTRATION_MODE": "phone"})


def test_sms_provider_aliyun_verify_needs_the_key_id_secret_file_and_signature(tmp_path: Path):
    """Checked at startup like the fallback provider (a missing key would otherwise be the first learner's 503 sms_send_failed);
    the ConfigError names the three variables; the key id is a secret for GET /api/admin/config, the file path is not."""
    full = _aliyun_env(tmp_path)
    with pytest.raises(ConfigError) as e:
        Settings.from_env({"WD_SMS_PROVIDER": "aliyun_verify"})
    assert all(name in str(e.value) for name in ("WD_SMS_PROVIDER=aliyun_verify", "WD_ALIYUN_ACCESS_KEY_ID", "WD_ALIYUN_ACCESS_KEY_SECRET_FILE", "WD_ALIYUN_SMS_SIGN_NAME"))
    for missing in full:
        env = {k: v for k, v in full.items() if k != missing}
        env["WD_SMS_PROVIDER"] = "aliyun_verify"
        with pytest.raises(ConfigError, match="WD_SMS_PROVIDER=aliyun_verify"):
            Settings.from_env(env)
    cfg = Settings.from_env({**full, "WD_SMS_PROVIDER": "aliyun_verify"})
    assert cfg.sms_configured is True and cfg.sms_provider == "aliyun_verify"
    assert (cfg.aliyun_access_key_id, cfg.aliyun_access_key_secret_file, cfg.aliyun_sms_sign_name) == ("LTAI5t-test", full["WD_ALIYUN_ACCESS_KEY_SECRET_FILE"], "速通验证")
    entries = {e["key"]: e["value"] for e in cfg.entries()}
    assert entries["WD_ALIYUN_ACCESS_KEY_ID"] == "***" and entries["WD_ALIYUN_ACCESS_KEY_SECRET_FILE"] == full["WD_ALIYUN_ACCESS_KEY_SECRET_FILE"]
    assert entries["WD_SMS_PROVIDER"] == "aliyun_verify" and entries["WD_ALIYUN_SMS_SIGN_NAME"] == "速通验证"
    # the keys alone do not switch SMS on
    assert Settings.from_env(full).sms_configured is False and Settings.from_env(full).sms_provider == "off"


def test_aliyun_secret_file_follows_the_key_file_rule(tmp_path: Path, caplog: pytest.LogCaptureFixture):
    """`WD_ALIYUN_ACCESS_KEY_SECRET_FILE` is validated exactly like `WD_AI_FALLBACK_API_KEY_FILE`: an existing readable regular
    file, else a ConfigError naming the path; a group/other-readable mode only warns (`chmod 600`)."""
    missing = tmp_path / "missing.secret"
    with pytest.raises(ConfigError, match=re.escape(str(missing))):
        Settings.from_env({"WD_ALIYUN_ACCESS_KEY_SECRET_FILE": str(missing)})
    with pytest.raises(ConfigError, match="WD_ALIYUN_ACCESS_KEY_SECRET_FILE"):
        Settings.from_env({"WD_ALIYUN_ACCESS_KEY_SECRET_FILE": str(tmp_path)})  # a directory
    locked = tmp_path / "locked.secret"
    locked.write_text("k\n", encoding="utf-8")
    locked.chmod(0o000)
    try:
        if os.geteuid() != 0:
            with pytest.raises(ConfigError, match="not readable"):
                Settings.from_env({"WD_ALIYUN_ACCESS_KEY_SECRET_FILE": str(locked)})
    finally:
        locked.chmod(0o600)
    loose = tmp_path / "loose.secret"
    loose.write_text("k\n", encoding="utf-8")
    loose.chmod(0o644)
    with caplog.at_level(logging.WARNING, logger="wd.config"):
        assert Settings.from_env({"WD_ALIYUN_ACCESS_KEY_SECRET_FILE": str(loose)}).aliyun_access_key_secret_file == str(loose)
    assert any("chmod 600" in r.getMessage() and str(loose) in r.getMessage() for r in caplog.records), caplog.text


def test_mail_provider_aliyun_dm_needs_the_key_and_the_from_address(tmp_path: Path):
    """`aliyun_dm` reuses the Aliyun key and `WD_SMTP_FROM` (the DirectMail sender); `email_configured` follows the provider —
    the SMTP host is irrelevant for DirectMail and the key is irrelevant for SMTP."""
    keys = {k: v for k, v in _aliyun_env(tmp_path).items() if k != "WD_ALIYUN_SMS_SIGN_NAME"}
    with pytest.raises(ConfigError) as e:
        Settings.from_env({"WD_MAIL_PROVIDER": "aliyun_dm"})
    assert all(name in str(e.value) for name in ("WD_MAIL_PROVIDER=aliyun_dm", "WD_ALIYUN_ACCESS_KEY_ID", "WD_ALIYUN_ACCESS_KEY_SECRET_FILE", "WD_SMTP_FROM"))
    with pytest.raises(ConfigError, match="WD_MAIL_PROVIDER=aliyun_dm"):
        Settings.from_env({**keys, "WD_MAIL_PROVIDER": "aliyun_dm"})  # no from-address
    with pytest.raises(ConfigError, match="WD_MAIL_PROVIDER=aliyun_dm"):
        Settings.from_env({"WD_MAIL_PROVIDER": "aliyun_dm", "WD_SMTP_FROM": "wd@example.com", "WD_SMTP_HOST": "smtp.example.com"})  # SMTP does not stand in
    with pytest.raises(ConfigError, match="sender address"):
        Settings.from_env({**keys, "WD_MAIL_PROVIDER": "aliyun_dm", "WD_SMTP_FROM": "word-dance"})  # a display name without an address: the DirectMail AccountName would be empty (create_app used to crash)
    cfg = Settings.from_env({**keys, "WD_MAIL_PROVIDER": "aliyun_dm", "WD_SMTP_FROM": "word-Dance <wd@example.com>"})
    assert cfg.mail_provider == "aliyun_dm" and cfg.email_configured is True and cfg.smtp_host == ""
    assert Settings.from_env({**keys, "WD_MAIL_PROVIDER": "aliyun_dm", "WD_SMTP_FROM": "wd@example.com"}).email_configured is True  # a bare address is fine
    # smtp stays host + from, the Aliyun key does not stand in
    assert Settings.from_env({**keys, "WD_SMTP_FROM": "wd@example.com"}).email_configured is False
    assert Settings.from_env({"WD_SMTP_HOST": "smtp.example.com", "WD_SMTP_FROM": "wd@example.com"}).email_configured is True
    assert Settings.from_env({**keys, "WD_SMTP_HOST": "smtp.example.com", "WD_SMTP_FROM": "wd@example.com"}).mail_provider == "smtp"


def test_sms_caps_and_code_limits_parse_their_ranges():
    cfg = Settings.from_env({"WD_SMS_DAILY_CAP": "0", "WD_SMS_HOURLY_CAP": "0", "WD_CODE_IP_HOURLY": "1", "WD_PHONE_STALE_DAYS": "3650", "WD_AI_USER_DAILY_WORDS": "0"})
    assert (cfg.sms_daily_cap, cfg.sms_hourly_cap, cfg.code_ip_hourly, cfg.phone_stale_days, cfg.ai_user_daily_words) == (0, 0, 1, 3650, 0)
    cfg = Settings.from_env({"WD_SMS_DAILY_CAP": "100000", "WD_SMS_HOURLY_CAP": "100000", "WD_CODE_IP_HOURLY": "100000", "WD_PHONE_STALE_DAYS": "1", "WD_AI_USER_DAILY_WORDS": "100000"})
    assert (cfg.sms_daily_cap, cfg.sms_hourly_cap, cfg.code_ip_hourly, cfg.phone_stale_days, cfg.ai_user_daily_words) == (100000, 100000, 100000, 1, 100000)
    for env in ({"WD_SMS_DAILY_CAP": "100001"}, {"WD_SMS_HOURLY_CAP": "-1"}, {"WD_CODE_IP_HOURLY": "100001"}, {"WD_PHONE_STALE_DAYS": "ninety"}, {"WD_AI_USER_DAILY_WORDS": "100001"}):
        with pytest.raises(ConfigError, match=next(iter(env))):
            Settings.from_env(env)
    assert Settings.from_env({"WD_CAPTCHA": "off"}).captcha == "off" and Settings.from_env({"WD_CAPTCHA": "on"}).captcha == "on"
    with pytest.raises(ConfigError, match="WD_CAPTCHA"):
        Settings.from_env({"WD_CAPTCHA": "true"})
    entries = {e["key"]: e for e in Settings.from_env({}).entries()}
    for key, value in (("WD_SMS_PROVIDER", "off"), ("WD_MAIL_PROVIDER", "smtp"), ("WD_SMS_DAILY_CAP", "200"), ("WD_SMS_HOURLY_CAP", "40"), ("WD_CODE_IP_HOURLY", "20"), ("WD_PHONE_STALE_DAYS", "90"), ("WD_CAPTCHA", "on"), ("WD_AI_USER_DAILY_WORDS", "80")):
        assert entries[key] == {"key": key, "value": value, "source": "default"}, key


def test_split_with_a_learner_kind_removed_warns_that_learner_input_reaches_claude(caplog: pytest.LogCaptureFixture):
    """AI_FALLBACK_MODEL §4.3 / CLAUDE_INTEGRATION §10.1: in mode split a kind outside WD_AI_FALLBACK_KINDS is the operator's work and
    runs on the CLI — for lookup / content / consolidate that is the learners' input, the very thing the mode keeps away."""
    with caplog.at_level(logging.WARNING, logger="wd.config"):
        Settings.from_env({**FALLBACK_ENV, "WD_AI_PROVIDER": "split", "WD_AI_FALLBACK_KINDS": "content,consolidate"})
    warnings = [r.getMessage() for r in caplog.records if r.name == "wd.config" and "learners' input reaches Claude" in r.getMessage()]
    assert len(warnings) == 1 and "lookup" in warnings[0] and "WD_AI_PROVIDER=split" in warnings[0], caplog.text
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="wd.config"):
        Settings.from_env({**FALLBACK_ENV, "WD_AI_PROVIDER": "split"})
    assert not [r for r in caplog.records if "reaches Claude" in r.getMessage()]  # the default list exposes nothing


# ------------------------------------------------------------------ third-party sign-in (docs/AUTH_SIGNUP_DESIGN.md §5.3, DEPLOY §4, slice 2-A)
def _secret_file(tmp_path: Path, name: str, mode: int = 0o600) -> str:
    path = tmp_path / name
    path.write_text("not-a-real-secret\n", encoding="utf-8")
    path.chmod(mode)
    return str(path)


def test_third_party_defaults_are_dark():
    """An unchanged .env: no provider configured, the three flags off, the mini-program defaults, no fakes — nothing changes for users."""
    cfg = Settings.from_env({})
    assert (cfg.wechat_appid, cfg.wechat_secret_file, cfg.wechat_env, cfg.wechat_page) == ("", "", "release", "pages/confirm/confirm")
    assert (cfg.qq_appid, cfg.qq_key_file, cfg.qq_callback_url) == ("", "", "")
    assert (cfg.apple_client_id, cfg.apple_app_id, cfg.apple_callback_url) == ("", "", "")
    assert cfg.auth_fake_providers is False
    assert (cfg.wechat_configured, cfg.qq_configured, cfg.apple_configured) == (False, False, False)
    entries = {e["key"]: e for e in cfg.entries()}
    for key, value in (("WD_WECHAT_APPID", ""), ("WD_WECHAT_SECRET_FILE", ""), ("WD_WECHAT_ENV", "release"), ("WD_WECHAT_PAGE", "pages/confirm/confirm"), ("WD_QQ_APPID", ""), ("WD_QQ_KEY_FILE", ""),
                       ("WD_QQ_CALLBACK_URL", ""), ("WD_APPLE_CLIENT_ID", ""), ("WD_APPLE_APP_ID", ""), ("WD_APPLE_CALLBACK_URL", ""), ("WD_AUTH_FAKE_PROVIDERS", "0")):
        assert entries[key] == {"key": key, "value": value, "source": "default"}, key


def test_wechat_needs_appid_and_secret_file(tmp_path: Path):
    """`WD_WECHAT_APPID` without `WD_WECHAT_SECRET_FILE` refuses to start (the `aliyun_verify` rule); the file alone switches nothing on; the
    pair sets `wechat_configured`; the path is shown by GET /api/admin/config (not a secret), the content never read into Settings."""
    secret = _secret_file(tmp_path, "wechat.secret")
    with pytest.raises(ConfigError, match="WD_WECHAT_APPID needs WD_WECHAT_SECRET_FILE"):
        Settings.from_env({"WD_WECHAT_APPID": "wx0000000000000000"})
    alone = Settings.from_env({"WD_WECHAT_SECRET_FILE": secret})
    assert alone.wechat_configured is False and alone.wechat_secret_file == secret
    cfg = Settings.from_env({"WD_WECHAT_APPID": "wx0000000000000000", "WD_WECHAT_SECRET_FILE": secret, "WD_WECHAT_ENV": "trial", "WD_WECHAT_PAGE": "pages/x/x"})
    assert cfg.wechat_configured is True and (cfg.wechat_appid, cfg.wechat_env, cfg.wechat_page) == ("wx0000000000000000", "trial", "pages/x/x")
    assert cfg.qq_configured is False and cfg.apple_configured is False
    entries = {e["key"]: e["value"] for e in cfg.entries()}
    assert entries["WD_WECHAT_SECRET_FILE"] == secret and entries["WD_WECHAT_APPID"] == "wx0000000000000000"
    assert "not-a-real-secret" not in repr(cfg)
    for env in (["release"], ["trial"], ["develop"]):
        assert Settings.from_env({"WD_WECHAT_ENV": env[0]}).wechat_env == env[0]
    with pytest.raises(ConfigError, match="WD_WECHAT_ENV"):
        Settings.from_env({"WD_WECHAT_ENV": "production"})


def test_third_party_secret_files_follow_the_key_file_rule(tmp_path: Path, caplog: pytest.LogCaptureFixture):
    """`WD_WECHAT_SECRET_FILE` / `WD_QQ_KEY_FILE` are validated like `WD_ALIYUN_ACCESS_KEY_SECRET_FILE`: an existing readable regular file at
    startup (a ConfigError naming the variable and the path otherwise); a group/other-readable mode only warns (`chmod 600`)."""
    for name in ("WD_WECHAT_SECRET_FILE", "WD_QQ_KEY_FILE"):
        missing = tmp_path / f"{name}.missing"
        with pytest.raises(ConfigError, match=re.escape(str(missing))):
            Settings.from_env({name: str(missing)})
        with pytest.raises(ConfigError, match=name):
            Settings.from_env({name: str(tmp_path)})  # a directory
        locked = tmp_path / f"{name}.locked"
        locked.write_text("k\n", encoding="utf-8")
        locked.chmod(0o000)
        try:
            if os.geteuid() != 0:
                with pytest.raises(ConfigError, match="not readable"):
                    Settings.from_env({name: str(locked)})
        finally:
            locked.chmod(0o600)
        loose = _secret_file(tmp_path, f"{name}.loose", 0o644)
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="wd.config"):
            assert getattr(Settings.from_env({name: loose}), name[len("WD_") :].lower()) == loose
        assert any("chmod 600" in r.getMessage() and loose in r.getMessage() and name in r.getMessage() for r in caplog.records), caplog.text


def test_qq_needs_appid_key_file_and_callback(tmp_path: Path):
    key = _secret_file(tmp_path, "qq.key")
    full = {"WD_QQ_APPID": "101000000", "WD_QQ_KEY_FILE": key, "WD_QQ_CALLBACK_URL": "https://relay.example.cn/api/auth/qq/callback"}
    with pytest.raises(ConfigError) as e:
        Settings.from_env({"WD_QQ_APPID": "101000000"})
    assert all(name in str(e.value) for name in ("WD_QQ_APPID", "WD_QQ_KEY_FILE", "WD_QQ_CALLBACK_URL"))
    for missing in ("WD_QQ_KEY_FILE", "WD_QQ_CALLBACK_URL"):
        with pytest.raises(ConfigError, match="WD_QQ_APPID needs"):
            Settings.from_env({k: v for k, v in full.items() if k != missing})
    cfg = Settings.from_env(full)
    assert cfg.qq_configured is True and (cfg.qq_appid, cfg.qq_key_file, cfg.qq_callback_url) == ("101000000", key, full["WD_QQ_CALLBACK_URL"])
    assert cfg.wechat_configured is False and cfg.apple_configured is False
    # the key file and the callback alone switch nothing on
    assert Settings.from_env({k: v for k, v in full.items() if k != "WD_QQ_APPID"}).qq_configured is False


def test_apple_needs_client_id_and_callback():
    with pytest.raises(ConfigError, match="WD_APPLE_CLIENT_ID needs WD_APPLE_CALLBACK_URL"):
        Settings.from_env({"WD_APPLE_CLIENT_ID": "com.worddance.web"})
    cfg = Settings.from_env({"WD_APPLE_CLIENT_ID": "com.worddance.web", "WD_APPLE_CALLBACK_URL": "https://words.example.com/api/auth/apple/callback", "WD_APPLE_APP_ID": "com.worddance.app"})
    assert cfg.apple_configured is True and cfg.apple_app_id == "com.worddance.app"
    assert Settings.from_env({"WD_APPLE_CALLBACK_URL": "https://words.example.com/api/auth/apple/callback"}).apple_configured is False  # the callback alone
    assert Settings.from_env({"WD_APPLE_APP_ID": "com.worddance.app"}).apple_configured is False  # the bundle id is read but unused until the iOS plugin


@pytest.mark.parametrize("name", ["WD_QQ_CALLBACK_URL", "WD_APPLE_CALLBACK_URL"])
def test_callback_urls_must_be_https_outside_dev(name: str):
    """The registered callbacks are `https://` with a host; `http://` is accepted only with WD_DEV=1 (the fake consent flow on a laptop)."""
    with pytest.raises(ConfigError, match=f"{name} must start with https://"):
        Settings.from_env({name: "http://relay.example.cn/api/auth/x/callback"})
    for bad in ("relay.example.cn/api/auth/x/callback", "ftp://relay.example.cn/x", "https://", "https:///api/auth/x"):
        with pytest.raises(ConfigError, match=name):
            Settings.from_env({name: bad})
    assert getattr(Settings.from_env({name: "https://relay.example.cn/api/auth/x/callback"}), name[len("WD_") :].lower()) == "https://relay.example.cn/api/auth/x/callback"
    assert getattr(Settings.from_env({name: "http://localhost:8010/api/auth/x/callback", "WD_DEV": "1"}), name[len("WD_") :].lower()) == "http://localhost:8010/api/auth/x/callback"
    assert getattr(Settings.from_env({name: " https://relay.example.cn/cb "}), name[len("WD_") :].lower()) == "https://relay.example.cn/cb"  # trimmed


def test_auth_fake_providers_need_dev():
    """`WD_AUTH_FAKE_PROVIDERS=1` without `WD_DEV=1` is a ConfigError (not a silent ignore like WD_SMOKE_MOCK_HTTP: the fake consent pages
    would sign anyone in as anyone); with WD_DEV=1 the flag is set while the three `*_configured` stay false — ServerFlags adds the fakes."""
    with pytest.raises(ConfigError, match="WD_AUTH_FAKE_PROVIDERS=1 needs WD_DEV=1"):
        Settings.from_env({"WD_AUTH_FAKE_PROVIDERS": "1"})
    assert Settings.from_env({"WD_AUTH_FAKE_PROVIDERS": "0"}).auth_fake_providers is False
    cfg = Settings.from_env({"WD_AUTH_FAKE_PROVIDERS": "1", "WD_DEV": "1"})
    assert cfg.auth_fake_providers is True and cfg.dev is True
    assert (cfg.wechat_configured, cfg.qq_configured, cfg.apple_configured) == (False, False, False)
    assert {e["key"]: e["value"] for e in cfg.entries()}["WD_AUTH_FAKE_PROVIDERS"] == "1"
    with pytest.raises(ConfigError, match="WD_AUTH_FAKE_PROVIDERS"):
        Settings.from_env({"WD_AUTH_FAKE_PROVIDERS": "maybe", "WD_DEV": "1"})


def test_third_party_variables_are_not_secret_keys():
    """Only the files' CONTENTS are secrets, which never enter Settings; every 2-A variable is shown verbatim by GET /api/admin/config."""
    from wd.config import SECRET_KEYS

    assert not {k for k in SECRET_KEYS if k.startswith(("WD_WECHAT_", "WD_QQ_", "WD_APPLE_", "WD_AUTH_FAKE"))}


# ------------------------------------------------------- pronunciation: 百炼 cloud TTS (provider bailian, DEPLOY §4 WD_BAILIAN_*, slice server-audio-2)
BAILIAN_ENDPOINT = "https://llm-ws1.cn-beijing.maas.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer"


def _bailian_env(tmp_path: Path, **extra: str) -> dict[str, str]:
    """A 0600 key file, the workspace id and the provider — what `bailian` needs to start."""
    key = tmp_path / "bailian.key"
    key.write_text("sk-test\n", encoding="utf-8")
    key.chmod(0o600)
    return {"WD_AUDIO_PROVIDER": "bailian", "WD_BAILIAN_API_KEY_FILE": str(key), "WD_BAILIAN_WORKSPACE_ID": "llm-ws1", **extra}


def test_bailian_defaults_are_dark():
    """An unchanged .env: provider `auto` (never bailian), every WD_BAILIAN_* at its default, nothing required, nothing secret."""
    from wd.config import AUDIO_PROVIDERS, SECRET_KEYS

    cfg = Settings.from_env({})
    assert cfg.audio_provider == "auto" and cfg.audio_provider_effective in ("say", "off")
    assert (cfg.bailian_api_key_file, cfg.bailian_workspace_id, cfg.bailian_region, cfg.bailian_tts_url) == ("", "", "cn-beijing", "")
    assert cfg.bailian_tts_model == "cosyvoice-v3-flash" and cfg.bailian_tts_voices == "en-US=loongabby_v3;en-GB=loongemily_v3"
    assert cfg.bailian_voice_map == {"en-US": "loongabby_v3", "en-GB": "loongemily_v3"}
    entries = {e["key"]: e for e in cfg.entries()}
    for key, value in (
        ("WD_BAILIAN_API_KEY_FILE", ""),
        ("WD_BAILIAN_WORKSPACE_ID", ""),
        ("WD_BAILIAN_REGION", "cn-beijing"),
        ("WD_BAILIAN_TTS_URL", ""),
        ("WD_BAILIAN_TTS_MODEL", "cosyvoice-v3-flash"),
        ("WD_BAILIAN_TTS_VOICES", "en-US=loongabby_v3;en-GB=loongemily_v3"),
    ):
        assert entries[key] == {"key": key, "value": value, "source": "default"}, key
    assert AUDIO_PROVIDERS == ("auto", "say", "youdao", "bailian", "cache", "off")
    assert not {k for k in SECRET_KEYS if k.startswith("WD_BAILIAN_")}  # the key FILE path is shown; the key itself never enters Settings


def test_bailian_needs_the_key_file_and_the_workspace_id(tmp_path: Path):
    """`WD_AUDIO_PROVIDER=bailian` refuses to start without the key file and the workspace id (each error names its variable, like
    `aliyun_verify`); the variables alone switch nothing on; `bailian_tts_url` is the endpoint derived from workspace + region."""
    with pytest.raises(ConfigError) as e:
        Settings.from_env({"WD_AUDIO_PROVIDER": "bailian"})
    assert "WD_AUDIO_PROVIDER=bailian" in str(e.value) and "WD_BAILIAN_API_KEY_FILE" in str(e.value)
    env = _bailian_env(tmp_path)
    with pytest.raises(ConfigError, match="WD_BAILIAN_WORKSPACE_ID"):
        Settings.from_env({k: v for k, v in env.items() if k != "WD_BAILIAN_WORKSPACE_ID"})
    cfg = Settings.from_env(env)
    assert cfg.audio_provider == cfg.audio_provider_effective == "bailian"
    assert cfg.bailian_tts_url == BAILIAN_ENDPOINT and cfg.bailian_workspace_id == "llm-ws1"
    entries = {e["key"]: e for e in cfg.entries()}
    assert entries["WD_BAILIAN_API_KEY_FILE"] == {"key": "WD_BAILIAN_API_KEY_FILE", "value": env["WD_BAILIAN_API_KEY_FILE"], "source": "env"}
    assert entries["WD_BAILIAN_TTS_URL"] == {"key": "WD_BAILIAN_TTS_URL", "value": BAILIAN_ENDPOINT, "source": "default"}  # the endpoint in force, like WD_DB_PATH
    assert "sk-test" not in str(cfg.entries())
    quiet = Settings.from_env({k: v for k, v in env.items() if k != "WD_AUDIO_PROVIDER"})
    assert quiet.audio_provider == "auto" and quiet.bailian_tts_url == BAILIAN_ENDPOINT


def test_bailian_key_file_follows_the_secret_file_rule(tmp_path: Path, caplog: pytest.LogCaptureFixture):
    """`WD_BAILIAN_API_KEY_FILE` is validated like `WD_ALIYUN_ACCESS_KEY_SECRET_FILE`: an existing readable regular file at startup —
    whenever it is set, provider or not —, else a ConfigError naming the path; a group/other-readable mode only warns (`chmod 600`)."""
    missing = tmp_path / "missing.key"
    with pytest.raises(ConfigError, match=re.escape(str(missing))):
        Settings.from_env({"WD_BAILIAN_API_KEY_FILE": str(missing)})
    with pytest.raises(ConfigError, match="WD_BAILIAN_API_KEY_FILE"):
        Settings.from_env({"WD_BAILIAN_API_KEY_FILE": str(tmp_path)})  # a directory
    locked = tmp_path / "locked.key"
    locked.write_text("sk-k\n", encoding="utf-8")
    locked.chmod(0o000)
    try:
        if os.geteuid() != 0:
            with pytest.raises(ConfigError, match="not readable"):
                Settings.from_env({"WD_BAILIAN_API_KEY_FILE": str(locked)})
    finally:
        locked.chmod(0o600)
    loose = tmp_path / "loose.key"
    loose.write_text("sk-k\n", encoding="utf-8")
    loose.chmod(0o644)
    with caplog.at_level(logging.WARNING, logger="wd.config"):
        assert Settings.from_env({"WD_BAILIAN_API_KEY_FILE": str(loose)}).bailian_api_key_file == str(loose)
    assert any("chmod 600" in r.getMessage() and str(loose) in r.getMessage() for r in caplog.records), caplog.text
    assert "sk-k" not in caplog.text


def test_bailian_region_url_override_model_and_voices(tmp_path: Path, caplog: pytest.LogCaptureFixture):
    env = _bailian_env(tmp_path)
    assert Settings.from_env({**env, "WD_BAILIAN_REGION": "ap-southeast-1"}).bailian_tts_url == "https://llm-ws1.ap-southeast-1.maas.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer"
    with pytest.raises(ConfigError, match="WD_BAILIAN_REGION"):
        Settings.from_env({**env, "WD_BAILIAN_REGION": "us-east-1"})
    with pytest.raises(ConfigError, match="WD_BAILIAN_REGION"):
        Settings.from_env({"WD_BAILIAN_REGION": "eu-central-1"})  # a choice, validated even while the provider is dark
    # the endpoint override: the WD_AI_FALLBACK_BASE_URL rule (http(s) + host; http:// to a non-loopback host warns), trailing / stripped
    override = Settings.from_env({**env, "WD_BAILIAN_TTS_URL": "https://tts.example.com/v1/tts/"})
    assert override.bailian_tts_url == "https://tts.example.com/v1/tts"
    assert {e["key"]: e["source"] for e in override.entries()}["WD_BAILIAN_TTS_URL"] == "env"
    for bad in ("tts.example.com/v1", "ftp://x/y", "https://", "http:///tts"):
        with pytest.raises(ConfigError, match="WD_BAILIAN_TTS_URL"):
            Settings.from_env({**env, "WD_BAILIAN_TTS_URL": bad})
    with caplog.at_level(logging.WARNING, logger="wd.config"):
        Settings.from_env({**env, "WD_BAILIAN_TTS_URL": "http://10.0.0.5:8080/tts"})
        Settings.from_env({**env, "WD_BAILIAN_TTS_URL": "http://127.0.0.1:8080/tts"})
    warnings = [r.getMessage() for r in caplog.records if "WD_BAILIAN_TTS_URL" in r.getMessage()]
    assert len(warnings) == 1 and "10.0.0.5" in warnings[0] and "cleartext" in warnings[0]
    # the model is free text (the provider validates it), stripped; the voices have the WD_AUDIO_CACHE_VOICES shape and the error names
    # the right variable; both accents only under bailian
    assert Settings.from_env({**env, "WD_BAILIAN_TTS_MODEL": " qwen-audio-3.1-tts-flash "}).bailian_tts_model == "qwen-audio-3.1-tts-flash"
    custom = Settings.from_env({**env, "WD_BAILIAN_TTS_VOICES": "en-GB=loongeric_v3; en-US=loongandy_v3"})
    assert custom.bailian_voice_map == {"en-US": "loongandy_v3", "en-GB": "loongeric_v3"}
    with pytest.raises(ConfigError, match="both accents"):
        Settings.from_env({**env, "WD_BAILIAN_TTS_VOICES": "en-US=loongabby_v3"})
    for bad in ("en-US:loongabby_v3", "fr-FR=x;en-GB=y", "en-US=;en-GB=y", "en-US=a;en-US=b"):
        with pytest.raises(ConfigError, match="WD_BAILIAN_TTS_VOICES") as e:
            Settings.from_env({"WD_BAILIAN_TTS_VOICES": bad})
        assert "WD_AUDIO_CACHE_VOICES" not in str(e.value)
    assert Settings.from_env({"WD_BAILIAN_TTS_VOICES": "en-US=loongabby_v3"}).bailian_voice_map == {"en-US": "loongabby_v3"}  # only bailian needs both
    assert Settings.from_env({"WD_AUDIO_CACHE_VOICES": "en-US=Ava (Premium)"}).audio_cache_voice_map == {"en-US": "Ava (Premium)"}  # the cache rule is untouched


def test_say_voice_zh_is_free_text_next_to_the_english_override():
    """`WD_AUDIO_SAY_VOICE_ZH` (DEPLOY §4): the `say` voice of the Chinese clips (`accent=zh-CN`, 磨耳朵) — empty by default, stripped,
    reported, independent of `WD_AUDIO_SAY_VOICE` (the English accents); `say` itself is asked about the name at run time. Chinese is
    not a third accent: the two-voice rules of `WD_AUDIO_CACHE_VOICES` / `WD_BAILIAN_TTS_VOICES` stay as they are."""
    from wd.config import AUDIO_ACCENTS

    cfg = Settings.from_env({})
    assert cfg.audio_say_voice_zh == "" and {e["key"]: e for e in cfg.entries()}["WD_AUDIO_SAY_VOICE_ZH"] == {"key": "WD_AUDIO_SAY_VOICE_ZH", "value": "", "source": "default"}
    named = Settings.from_env({"WD_AUDIO_SAY_VOICE": "Ava (Premium)", "WD_AUDIO_SAY_VOICE_ZH": " Lili (Premium) "})
    assert (named.audio_say_voice, named.audio_say_voice_zh) == ("Ava (Premium)", "Lili (Premium)")
    assert {e["key"]: e for e in named.entries()}["WD_AUDIO_SAY_VOICE_ZH"] == {"key": "WD_AUDIO_SAY_VOICE_ZH", "value": "Lili (Premium)", "source": "env"}
    assert AUDIO_ACCENTS == ("en-US", "en-GB")
    assert Settings.from_env({"WD_AUDIO_PROVIDER": "cache", "WD_AUDIO_CACHE_VOICES": "en-US=Ava (Premium);en-GB=Serena (Premium)"}).audio_provider_effective == "cache"  # an existing two-voice .env keeps starting
    with pytest.raises(ConfigError, match="WD_AUDIO_CACHE_VOICES"):
        Settings.from_env({"WD_AUDIO_CACHE_VOICES": "en-US=Ava (Premium);en-GB=Serena (Premium);zh-CN=Tingting"})
