"""config.Settings.from_env: defaults, validation, clamps, derived values, admin config entries."""

from __future__ import annotations

from pathlib import Path

import pytest

from wd.config import DEFAULT_SEED_PATH, REPO_ROOT, ConfigError, Settings


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
