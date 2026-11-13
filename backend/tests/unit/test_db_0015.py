"""0015_dance_mode.sql — user_settings.dance_mode (docs/WORD_DANCE_DESIGN.md §6.3): one additive column with its default and
CHECK, applied on top of a populated database without touching its rows; the file is nothing but that ADD COLUMN."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from wd import db, security


def _database_at_0014(settings, tmp_path: Path) -> sqlite3.Connection:
    """A database migrated with every file up to 0014, holding two users with pre-0015 settings rows."""
    older = tmp_path / "older"
    older.mkdir()
    for f in db.list_migration_files():
        if f.version < 15:
            shutil.copy(f.path, older / f.path.name)
    c = db.connect(settings.db_path)
    applied = db.run_migrations(c, migrations_dir=older).applied
    assert applied and applied[-1][0] == 14 and all(v < 15 for v, _ in applied)
    with db.tx(c):
        for username, accent, zh in (("alice", "en-GB", "always"), ("bob", "en-US", "tap")):
            uid = int(c.execute("INSERT INTO users(username, password_hash) VALUES (?, 'x')", (username,)).lastrowid)
            c.execute("INSERT INTO user_settings(user_id, accent, zh_examples) VALUES (?, ?, ?)", (uid, accent, zh))
    return c


def test_0015_adds_dance_mode_with_its_default_and_keeps_rows(settings, tmp_path: Path):
    c = _database_at_0014(settings, tmp_path)
    try:
        before_cols = [r["name"] for r in c.execute("PRAGMA table_info(user_settings)")]
        assert "dance_mode" not in before_cols
        before = [tuple(r) for r in c.execute("SELECT user_id, accent, zh_examples, auto_pronounce, stages_json FROM user_settings ORDER BY user_id")]
        assert len(before) == 2

        result = db.run_migrations(c)  # the same call as `wd migrate` / the service startup

        assert (15, "dance_mode") in result.applied and db.current_version(c) >= 15
        assert not c.in_transaction and c.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        info = {r["name"]: r for r in c.execute("PRAGMA table_info(user_settings)")}
        assert [r["name"] for r in c.execute("PRAGMA table_info(user_settings)")] == before_cols + ["dance_mode", "image_word"]  # appended, nothing rebuilt (0021's image_word rides along, test_db_0021.py)
        assert info["dance_mode"]["type"] == "TEXT" and info["dance_mode"]["notnull"] == 1 and info["dance_mode"]["dflt_value"] == "'full'"
        assert [tuple(r) for r in c.execute("SELECT user_id, accent, zh_examples, auto_pronounce, stages_json FROM user_settings ORDER BY user_id")] == before
        assert [r[0] for r in c.execute("SELECT dance_mode FROM user_settings")] == ["full", "full"]
        # the DTO reads the column, and the CHECK list is the API's DanceMode
        cur = c.execute("SELECT s.*, u.email_verified_at FROM user_settings s JOIN users u ON u.id = s.user_id ORDER BY s.user_id")
        row = dict(zip([d[0] for d in cur.description], cur.fetchone()))
        assert security.settings_row_to_dto(row)["dance_mode"] == "full" and security.settings_row_to_dto(row)["accent"] == "en-GB"
        with db.tx(c):
            c.execute("UPDATE user_settings SET dance_mode = 'off' WHERE user_id = 1")
            c.execute("UPDATE user_settings SET dance_mode = 'form_only' WHERE user_id = 2")
        assert [r[0] for r in c.execute("SELECT dance_mode FROM user_settings ORDER BY user_id")] == ["off", "form_only"]
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            c.execute("UPDATE user_settings SET dance_mode = 'loud' WHERE user_id = 1")
        assert c.execute("PRAGMA foreign_key_check").fetchall() == [] and c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.run_migrations(c).applied == []  # idempotent
    finally:
        c.close()


def test_0015_is_a_single_add_column():
    """Additive like 0012 / 0014: one ALTER TABLE … ADD COLUMN, no DROP / RENAME / CREATE, no PRAGMA, no COMMIT (DEPLOY §5 / §10)."""
    text = (db.MIGRATIONS_DIR / "0015_dance_mode.sql").read_text(encoding="utf-8")
    statements = [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("--")]
    assert len(statements) == 1
    assert statements[0].startswith("ALTER TABLE user_settings ADD COLUMN dance_mode TEXT NOT NULL DEFAULT 'full' CHECK (dance_mode IN ('full','form_only','off'))")


def test_settings_dto_defaults_dance_mode_for_a_row_without_the_column():
    """An older row dict (a server reading a database it has not migrated yet) still serialises."""
    row = {
        "user_id": 1, "timezone": "Asia/Shanghai", "push_time": "08:00", "push_enabled": 1, "daily_new_count": 10, "daily_screen_count": 15,
        "max_reviews": 60, "stages_json": '["xs","zk"]', "current_stage": 1, "show_images": 1, "zh_examples": "tap", "auto_pronounce": 1,
        "accent": "en-US", "email_enabled": 0, "webhook_enabled": 0, "webhook_url": None, "webhook_format": "generic", "next_push_at": None,
        "updated_at": "2026-11-08T00:00:00Z", "email_verified_at": None,
    }
    assert security.settings_row_to_dto(row)["dance_mode"] == "full"
