"""0012_word_images_meta.sql (PLAN §2.3): four additive columns on word_images — prompt_version / model / text_free /
eval_json — applied on top of a populated database without touching its rows, and the store writing them."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from wd import db

NEW_COLUMNS = ("prompt_version", "model", "text_free", "eval_json")


def _baseline_with_two_images(settings, tmp_path: Path) -> sqlite3.Connection:
    """A database at version 1 (0001 only) holding a photo and a pre-0012 Claude SVG."""
    baseline = tmp_path / "baseline"
    baseline.mkdir()
    shutil.copy(db.MIGRATIONS_DIR / "0001_init.sql", baseline / "0001_init.sql")
    c = db.connect(settings.db_path)
    assert db.run_migrations(c, migrations_dir=baseline).applied == [(1, "init")]
    with db.tx(c):
        c.executemany("INSERT INTO words(id, lemma, display, source) VALUES (?, ?, ?, 'seed')", [(1, "apple", "apple"), (2, "abandon", "abandon")])
        c.executemany(
            "INSERT INTO word_images(id, word_id, provider, file_path, file_bytes, sha256, mime, license, alt_zh) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (7, 1, "wikimedia", "ab/ab12.jpg", 1234, "ab12", "image/jpeg", "CC BY 2.0", "一个红苹果"),
                (9, 2, "claude_svg", "cd/cd34.svg", 2345, "cd34", "image/svg+xml", "generated", "雪地里的汽车"),  # drawn with svg_system v1: it printed the headword
            ],
        )
        c.execute("UPDATE words SET active_image_id = 7, image_state = 'ready' WHERE id = 1")
        c.execute("UPDATE words SET active_image_id = 9, image_state = 'ready' WHERE id = 2")
    return c


def test_0012_adds_word_images_meta_columns_and_keeps_rows(settings, tmp_path: Path):
    c = _baseline_with_two_images(settings, tmp_path)
    try:
        before = [tuple(r) for r in c.execute("SELECT id, word_id, provider, file_path, file_bytes, sha256, mime, license, alt_zh, status FROM word_images ORDER BY id")]
        before_cols = [r["name"] for r in c.execute("PRAGMA table_info(word_images)")]
        assert not any(col in before_cols for col in NEW_COLUMNS)

        result = db.run_migrations(c)  # the same call as `wd migrate` / the service startup

        assert (12, "word_images_meta") in result.applied
        assert not c.in_transaction and c.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        info = {r["name"]: r for r in c.execute("PRAGMA table_info(word_images)")}
        assert [r["name"] for r in c.execute("PRAGMA table_info(word_images)")] == before_cols + list(NEW_COLUMNS)  # appended, nothing rebuilt
        assert info["text_free"]["notnull"] == 1 and info["text_free"]["dflt_value"] == "0" and info["text_free"]["type"] == "INTEGER"
        assert all(info[col]["notnull"] == 0 and info[col]["dflt_value"] is None and info[col]["type"] == "TEXT" for col in ("prompt_version", "model", "eval_json"))
        # the 30 live SVGs drawn before this migration printed the headword: text_free stays 0, prompt_version / model NULL
        after = [tuple(r) for r in c.execute("SELECT id, word_id, provider, file_path, file_bytes, sha256, mime, license, alt_zh, status FROM word_images ORDER BY id")]
        assert after == before and [r["id"] for r in c.execute("SELECT id FROM word_images ORDER BY id")] == [7, 9]
        assert [tuple(r) for r in c.execute("SELECT prompt_version, model, text_free, eval_json FROM word_images ORDER BY id")] == [(None, None, 0, None)] * 2
        assert tuple(c.execute("SELECT COUNT(*), SUM(text_free), SUM(prompt_version IS NULL) FROM word_images").fetchone()) == (2, 0, 2)
        assert [tuple(r) for r in c.execute("SELECT id, active_image_id, image_state FROM words ORDER BY id")] == [(1, 7, "ready"), (2, 9, "ready")]
        assert c.execute("PRAGMA foreign_key_check").fetchall() == [] and c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        # the CHECK: text_free is a flag (superseded rows, so ux_word_images_active cannot be the constraint that fires)
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            c.execute("INSERT INTO word_images(word_id, provider, file_path, file_bytes, sha256, mime, status, text_free) VALUES (1, 'wikimedia', 'ef/ef56.jpg', 1, 'ef56', 'image/jpeg', 'superseded', 2)")
        c.execute(
            "INSERT INTO word_images(id, word_id, provider, file_path, file_bytes, sha256, mime, status, prompt_version, model, text_free, eval_json) "
            "VALUES (11, 2, 'claude_svg', 'ef/ef56.svg', 1, 'ef56', 'image/svg+xml', 'superseded', 'svg-v2', 'claude-sonnet-4-5', 1, '{\"r1\": 2}')"
        )
        assert tuple(c.execute("SELECT prompt_version, model, text_free, eval_json FROM word_images WHERE id = 11").fetchone()) == ("svg-v2", "claude-sonnet-4-5", 1, '{"r1": 2}')
        assert len(db.table_names(c)) == 30 and "word_images" in db.table_names(c)  # no table gained or lost by 0012 (0016 / 0018 / 0019 / 0020 add theirs on the way)
        assert db.run_migrations(c).applied == []  # idempotent: a second run has nothing to do
    finally:
        c.close()


def test_0012_is_additive_and_numbered_after_the_stage_rebuild():
    """The file may land in either order with 0011 (db.pending_migrations applies every unrecorded file): it must be
    nothing but ADD COLUMN statements — no DROP / RENAME / CREATE, no PRAGMA, no COMMIT (DEPLOY §5/§10)."""
    text = (db.MIGRATIONS_DIR / "0012_word_images_meta.sql").read_text(encoding="utf-8")
    statements = [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("--")]
    assert len(statements) == 4 and all(line.startswith("ALTER TABLE word_images ADD COLUMN ") for line in statements)
    assert [line.split()[5] for line in statements] == list(NEW_COLUMNS)
    upper = text.upper()
    for forbidden in ("DROP ", "RENAME", "CREATE ", "PRAGMA", "COMMIT", "ROLLBACK", "INSERT INTO SCHEMA_MIGRATIONS"):
        assert forbidden not in upper, forbidden
    assert (12, "word_images_meta") in [(f.version, f.name) for f in db.list_migration_files()]
