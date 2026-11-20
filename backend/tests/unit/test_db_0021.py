"""0021_memory_cards.sql — 记忆图卡 (docs/MEMORY_CARDS_DESIGN.md §3.4): user_settings.image_word (NOT NULL DEFAULT 1, CHECK 0/1) and the
nullable word_images.hook_zh / note_zh, applied on top of a populated database without touching its rows; the file is nothing but
those three ADD COLUMNs, and the two DTOs still serialise for a row that predates them."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from wd import db, security
from wd.images import image_meta
from wd.schemas import ImageMeta

STATEMENTS = [
    "ALTER TABLE user_settings ADD COLUMN image_word INTEGER NOT NULL DEFAULT 1 CHECK (image_word IN (0,1));",
    "ALTER TABLE word_images ADD COLUMN hook_zh TEXT;",
    "ALTER TABLE word_images ADD COLUMN note_zh TEXT;",
]


def _database_at_0020(settings, tmp_path: Path) -> sqlite3.Connection:
    """A database migrated with every file up to 0020, holding two users with their settings, a photo, an online Claude drawing and a
    superseded one — the kinds of rows the live Mac holds when the file runs."""
    older = tmp_path / "older"
    older.mkdir()
    for f in db.list_migration_files():
        if f.version < 21:
            shutil.copy(f.path, older / f.path.name)
    c = db.connect(settings.db_path)
    applied = db.run_migrations(c, migrations_dir=older).applied
    assert applied and applied[-1][0] == 20 and all(v < 21 for v, _ in applied)
    with db.tx(c):
        for username, accent, dance in (("alice", "en-GB", "off"), ("bob", "en-US", "full")):
            uid = int(c.execute("INSERT INTO users(username, password_hash) VALUES (?, 'x')", (username,)).lastrowid)
            c.execute("INSERT INTO user_settings(user_id, accent, dance_mode, show_images) VALUES (?, ?, ?, 0)", (uid, accent, dance))
        c.executemany("INSERT INTO words(id, lemma, display, source) VALUES (?, ?, ?, 'seed')", [(1, "apple", "apple"), (2, "moon", "moon")])
        c.executemany(
            "INSERT INTO word_images(id, word_id, provider, file_path, file_bytes, sha256, mime, license, alt_zh, status, prompt_version, model, text_free) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (7, 1, "wikimedia", "ab/" + "ab" * 32 + ".jpg", 1234, "ab" * 32, "image/jpeg", "CC BY 2.0", "一个红苹果", "active", None, None, 0),
                (8, 2, "claude_svg", "cd/" + "cd" * 32 + ".svg", 1800, "cd" * 32, "image/svg+xml", "generated", "夜空里的月亮", "superseded", None, None, 0),
                (9, 2, "claude_svg", "ef/" + "ef" * 32 + ".svg", 1900, "ef" * 32, "image/svg+xml", "generated", "弯弯的月亮", "active", "svg-v2", "claude-sonnet-4-5", 1),
            ],
        )
        c.execute("UPDATE words SET active_image_id = 7, image_state = 'ready' WHERE id = 1")
        c.execute("UPDATE words SET active_image_id = 9, image_state = 'ready' WHERE id = 2")
    return c


def test_0021_adds_three_columns_with_their_defaults_and_keeps_rows(settings, tmp_path: Path):
    c = _database_at_0020(settings, tmp_path)
    try:
        before_settings_cols = [r["name"] for r in c.execute("PRAGMA table_info(user_settings)")]
        before_image_cols = [r["name"] for r in c.execute("PRAGMA table_info(word_images)")]
        assert "image_word" not in before_settings_cols and "hook_zh" not in before_image_cols and "note_zh" not in before_image_cols
        before_settings = [tuple(r) for r in c.execute("SELECT user_id, accent, dance_mode, show_images, stages_json FROM user_settings ORDER BY user_id")]
        before_images = [tuple(r) for r in c.execute("SELECT id, word_id, provider, file_path, sha256, alt_zh, status, prompt_version, model, text_free FROM word_images ORDER BY id")]
        assert len(before_settings) == 2 and len(before_images) == 3
        before_tables = set(db.table_names(c))

        result = db.run_migrations(c)  # the same call as `wd migrate` / the service startup

        assert (21, "memory_cards") in result.applied and db.current_version(c) >= 21
        assert not c.in_transaction and c.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert set(db.table_names(c)) == before_tables | {"assignments", "assignment_words"} and db.view_names(c) == ["v_bank"]  # 0021 gains and loses no table (0022 adds its two on the way)
        assert [r["name"] for r in c.execute("PRAGMA table_info(user_settings)")] == before_settings_cols + ["image_word"]  # appended, nothing rebuilt
        assert [r["name"] for r in c.execute("PRAGMA table_info(word_images)")] == before_image_cols + ["hook_zh", "note_zh"]
        info = {r["name"]: r for r in c.execute("PRAGMA table_info(user_settings)")}
        assert info["image_word"]["type"] == "INTEGER" and info["image_word"]["notnull"] == 1 and info["image_word"]["dflt_value"] == "1"
        image_info = {r["name"]: r for r in c.execute("PRAGMA table_info(word_images)")}
        assert all(image_info[col]["type"] == "TEXT" and image_info[col]["notnull"] == 0 and image_info[col]["dflt_value"] is None for col in ("hook_zh", "note_zh"))
        # every existing row keeps its values; the word stays on the picture for everybody, no image has a caption
        assert [tuple(r) for r in c.execute("SELECT user_id, accent, dance_mode, show_images, stages_json FROM user_settings ORDER BY user_id")] == before_settings
        assert [tuple(r) for r in c.execute("SELECT id, word_id, provider, file_path, sha256, alt_zh, status, prompt_version, model, text_free FROM word_images ORDER BY id")] == before_images
        assert [r[0] for r in c.execute("SELECT image_word FROM user_settings ORDER BY user_id")] == [1, 1]
        assert [tuple(r) for r in c.execute("SELECT hook_zh, note_zh FROM word_images ORDER BY id")] == [(None, None)] * 3
        assert [tuple(r) for r in c.execute("SELECT id, active_image_id, image_state FROM words ORDER BY id")] == [(1, 7, "ready"), (2, 9, "ready")]
        # the DTOs read the columns: Settings.image_word true, and no existing picture turns into a memory card
        cur = c.execute("SELECT s.*, u.email_verified_at FROM user_settings s JOIN users u ON u.id = s.user_id ORDER BY s.user_id")
        row = dict(zip([d[0] for d in cur.description], cur.fetchone()))
        dto = security.settings_row_to_dto(row)
        assert dto["image_word"] is True and dto["dance_mode"] == "off" and dto["show_images"] is False
        for word_id, kind in ((1, "photo"), (2, "svg")):
            meta = image_meta(c, word_id)
            ImageMeta.model_validate(meta)
            assert (meta["kind"], meta["word_layer"], meta["hook_zh"], meta["note_zh"]) == (kind, False, None, None)
        # the flag is a flag, the captions are free text
        with db.tx(c):
            c.execute("UPDATE user_settings SET image_word = 0 WHERE user_id = 1")
            c.execute("UPDATE word_images SET hook_zh = '两个 o 像两轮圆月。', note_zh = NULL WHERE id = 9")
        assert [r[0] for r in c.execute("SELECT image_word FROM user_settings ORDER BY user_id")] == [0, 1]
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            c.execute("UPDATE user_settings SET image_word = 2 WHERE user_id = 1")
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("UPDATE user_settings SET image_word = NULL WHERE user_id = 1")
        uid = int(c.execute("INSERT INTO users(username, password_hash) VALUES ('carol', 'x')").lastrowid)
        c.execute("INSERT INTO user_settings(user_id) VALUES (?)", (uid,))
        assert c.execute("SELECT image_word FROM user_settings WHERE user_id = ?", (uid,)).fetchone()[0] == 1  # a new account starts with the word shown
        assert c.execute("PRAGMA foreign_key_check").fetchall() == [] and c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.run_migrations(c).applied == []  # idempotent
    finally:
        c.close()


def test_0021_is_three_add_columns():
    """Additive like 0012 / 0015: ALTER TABLE … ADD COLUMN only — exactly the three statements of the design §3.4 — no DROP / RENAME /
    CREATE, no PRAGMA, no COMMIT (DEPLOY §5 / §10)."""
    text = (db.MIGRATIONS_DIR / "0021_memory_cards.sql").read_text(encoding="utf-8")
    statements = [line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("--")]
    assert statements == STATEMENTS
    assert db.list_migration_files()[-1].version >= 21 and (21, "memory_cards") in [(f.version, f.name) for f in db.list_migration_files()]


def test_dtos_default_for_rows_without_the_0021_columns(settings, tmp_path: Path):
    """A server reading a database it has not migrated yet still serialises: Settings.image_word is the DDL default, and an
    active drawing whose row has no hook_zh / note_zh columns — even one labelled memo-… by hand — answers null for both."""
    row = {
        "user_id": 1, "timezone": "Asia/Shanghai", "push_time": "08:00", "push_enabled": 1, "daily_new_count": 10, "daily_screen_count": 15,
        "max_reviews": 60, "stages_json": '["xs","zk"]', "current_stage": 1, "show_images": 1, "zh_examples": "tap", "auto_pronounce": 1,
        "accent": "en-US", "dance_mode": "full", "email_enabled": 0, "webhook_enabled": 0, "webhook_url": None, "webhook_format": "generic",
        "next_push_at": None, "updated_at": "2026-11-13T00:00:00Z", "email_verified_at": None,
    }
    assert security.settings_row_to_dto(row)["image_word"] is True
    assert security.settings_row_to_dto({**row, "image_word": 0})["image_word"] is False and security.settings_row_to_dto({**row, "image_word": 1})["image_word"] is True
    assert security.settings_row_to_dto({**row, "image_word": None})["image_word"] is True
    c = _database_at_0020(settings, tmp_path)
    try:
        c.execute("UPDATE word_images SET prompt_version = 'memo-1' WHERE id = 9")
        meta = image_meta(c, 2)
        ImageMeta.model_validate(meta)
        assert meta["word_layer"] is True and meta["hook_zh"] is None and meta["note_zh"] is None and meta["kind"] == "svg"
    finally:
        c.close()
