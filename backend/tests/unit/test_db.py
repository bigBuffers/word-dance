"""db.py: migration runner bookkeeping and atomicity, tx(), connect() PRAGMAs, kv helpers (TASKS P0 acceptance)."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from wd import db

EXPECTED_TABLES = {
    "schema_migrations", "kv", "system_events", "users", "sessions", "invite_codes", "auth_throttle", "email_codes", "user_settings",
    "words", "word_forms", "word_contents", "word_images", "user_words", "review_logs", "daily_stats", "push_batches", "push_items",
    "consolidation_runs", "bank_suggestions", "jobs", "ai_calls", "provider_usage", "provider_state", "content_reports",
}


def test_connect_pragmas_and_autocommit(settings):
    c = db.connect(settings.db_path)
    try:
        assert c.autocommit is True
        assert c.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert c.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert c.execute("PRAGMA synchronous").fetchone()[0] == 1  # NORMAL
        assert c.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
        assert c.execute("PRAGMA temp_store").fetchone()[0] == 2  # MEMORY
        assert c.execute("PRAGMA cache_size").fetchone()[0] == -20000
        assert isinstance(c.execute("SELECT 1 AS x").fetchone(), sqlite3.Row)
        assert not c.in_transaction
    finally:
        c.close()


def test_fresh_migration_creates_schema_and_one_bookkeeping_row(settings):
    c = db.connect(settings.db_path)
    try:
        result = db.run_migrations(c)
        assert result.applied == [(1, "init")]
        assert result.from_version == 0 and result.to_version == 1
        tables = set(db.table_names(c))
        assert tables == EXPECTED_TABLES
        assert len(tables) == 25
        assert db.view_names(c) == ["v_bank"]
        rows = c.execute("SELECT version, name FROM schema_migrations").fetchall()
        assert [tuple(r) for r in rows] == [(1, "init")]
        assert db.current_version(c) == 1
        assert db.kv_get(c, "schema.created_at") is not None  # written by the file itself (§10)
        assert not c.in_transaction
    finally:
        c.close()


def test_second_run_has_nothing_pending(conn):
    result = db.run_migrations(conn)
    assert result.applied == [] and result.pending == []
    assert conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 1


def test_dry_run_lists_pending_without_applying(settings):
    c = db.connect(settings.db_path)
    try:
        result = db.run_migrations(c, dry_run=True)
        assert result.pending == [(1, "init")] and result.applied == []
        assert db.table_names(c) == []
    finally:
        c.close()


def test_broken_migration_rolls_back_file_and_bookkeeping(settings, tmp_path: Path):
    mig = tmp_path / "migrations"
    mig.mkdir()
    shutil.copy(db.MIGRATIONS_DIR / "0001_init.sql", mig / "0001_init.sql")
    (mig / "0099_broken.sql").write_text(
        "CREATE TABLE half_done(x INTEGER);\nINSERT INTO half_done VALUES (1);\nINSERT INTO kv(key, value) VALUES ('broken.marker', '1');\nTHIS IS NOT SQL;\n",
        encoding="utf-8",
    )
    calls: list[tuple[int, int]] = []
    c = db.connect(settings.db_path)
    try:
        with pytest.raises(db.MigrationError) as info:
            db.run_migrations(c, pre_hook=lambda a, b: calls.append((a, b)), migrations_dir=mig)
        assert info.value.version == 99 and info.value.name == "broken"
        assert calls == [(0, 99)]  # once, before the first pending file, with (from, to)
        assert not c.in_transaction
        versions = [r[0] for r in c.execute("SELECT version FROM schema_migrations ORDER BY version")]
        assert versions == [1]  # 0001 committed on its own; 0099 left no row
        assert "half_done" not in db.table_names(c)
        assert db.kv_get(c, "broken.marker") is None
        # the connection is still usable and a corrected file applies afterwards
        (mig / "0099_broken.sql").write_text("CREATE TABLE half_done(x INTEGER);\n", encoding="utf-8")
        result = db.run_migrations(c, migrations_dir=mig)
        assert result.applied == [(99, "broken")]
        assert "half_done" in db.table_names(c)
    finally:
        c.close()


def test_migration_file_may_not_commit_itself(settings, tmp_path: Path):
    mig = tmp_path / "migrations"
    mig.mkdir()
    shutil.copy(db.MIGRATIONS_DIR / "0001_init.sql", mig / "0001_init.sql")
    (mig / "0002_selfcommit.sql").write_text("CREATE TABLE sneaky(x); COMMIT;\n", encoding="utf-8")
    c = db.connect(settings.db_path)
    try:
        with pytest.raises(db.MigrationError):
            db.run_migrations(c, migrations_dir=mig)
        assert db.current_version(c) == 1
    finally:
        c.close()


def test_pre_hook_not_called_when_nothing_pending(conn):
    called = []
    db.run_migrations(conn, pre_hook=lambda a, b: called.append((a, b)))
    assert called == []


def test_list_migration_files_rejects_duplicates(tmp_path: Path):
    (tmp_path / "0001_a.sql").write_text("", encoding="utf-8")
    (tmp_path / "0001_b.sql").write_text("", encoding="utf-8")
    with pytest.raises(db.MigrationError):
        db.list_migration_files(tmp_path)


def test_tx_commits_and_rolls_back(conn):
    with db.tx(conn):
        conn.execute("INSERT INTO kv(key, value) VALUES ('a', '1')")
        assert conn.in_transaction
    assert db.kv_get(conn, "a") == "1"
    with pytest.raises(RuntimeError):
        with db.tx(conn):
            conn.execute("INSERT INTO kv(key, value) VALUES ('b', '2')")
            raise RuntimeError("boom")
    assert db.kv_get(conn, "b") is None
    assert not conn.in_transaction


def test_tx_refuses_nesting_but_maybe_tx_joins(conn):
    with db.tx(conn):
        with pytest.raises(sqlite3.ProgrammingError):
            with db.tx(conn):
                pass
        with db.maybe_tx(conn):  # joins the open transaction
            conn.execute("INSERT INTO kv(key, value) VALUES ('joined', '1')")
        assert conn.in_transaction
    assert db.kv_get(conn, "joined") == "1"


def test_kv_helpers(conn):
    assert db.kv_get(conn, "missing") is None
    assert db.kv_get(conn, "missing", "dflt") == "dflt"
    db.kv_set(conn, "k", "v1", now="2026-01-01T00:00:00Z")
    assert db.kv_get(conn, "k") == "v1"
    db.kv_set(conn, "k", "v2", now="2026-01-02T00:00:00Z")
    row = conn.execute("SELECT value, updated_at FROM kv WHERE key='k'").fetchone()
    assert tuple(row) == ("v2", "2026-01-02T00:00:00Z")
    db.kv_delete(conn, "k")
    assert db.kv_get(conn, "k") is None


def test_backup_pre_hook_is_none_while_wp9_is_absent():
    try:
        import wd.backup  # type: ignore[import-not-found]  # noqa: F401
    except ModuleNotFoundError:
        assert db.backup_pre_hook() is None
    else:  # pragma: no cover - after WP9 lands
        assert callable(db.backup_pre_hook())


def test_schema_file_is_byte_identical_to_docs_copy_when_present():
    docs = Path(__file__).resolve().parents[3] / "docs" / "SCHEMA.sql"
    if not docs.is_file():
        pytest.skip("docs/SCHEMA.sql not present in this checkout")
    assert docs.read_bytes() == (db.MIGRATIONS_DIR / "0001_init.sql").read_bytes()
