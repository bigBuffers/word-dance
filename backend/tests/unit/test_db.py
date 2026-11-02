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


def shipped_migrations() -> list[tuple[int, str]]:
    """``(version, name)`` of every file in ``backend/wd/migrations`` — what a fresh database applies."""
    return [(f.version, f.name) for f in db.list_migration_files()]


def test_fresh_migration_creates_schema_and_one_bookkeeping_row_per_file(settings):
    shipped = shipped_migrations()
    assert shipped[0] == (1, "init") and (8, "fk_child_indexes") in shipped
    c = db.connect(settings.db_path)
    try:
        result = db.run_migrations(c)
        assert result.applied == shipped
        assert result.from_version == 0 and result.to_version == shipped[-1][0]
        tables = set(db.table_names(c))
        assert tables == EXPECTED_TABLES
        assert len(tables) == 25
        assert db.view_names(c) == ["v_bank"]
        rows = c.execute("SELECT version, name FROM schema_migrations ORDER BY version").fetchall()
        assert [tuple(r) for r in rows] == shipped  # one row per file, written by the runner
        assert db.current_version(c) == shipped[-1][0]
        assert db.kv_get(c, "schema.created_at") is not None  # written by the file itself (§10)
        assert not c.in_transaction
    finally:
        c.close()


def test_second_run_has_nothing_pending(conn):
    result = db.run_migrations(conn)
    assert result.applied == [] and result.pending == []
    assert conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == len(shipped_migrations())


def test_dry_run_lists_pending_without_applying(settings):
    c = db.connect(settings.db_path)
    try:
        result = db.run_migrations(c, dry_run=True)
        assert result.pending == shipped_migrations() and result.applied == []
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
        assert c.execute("PRAGMA foreign_keys").fetchone()[0] == 1  # enforcement restored on the error path too
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


# ------------------------------------------------------------------ foreign keys during a migration (table rebuilds)
# SQLite cannot ALTER a CHECK list, so widening e.g. users.role means the official rebuild: new table, copy, DROP the old
# one, RENAME. With foreign_keys=ON the DROP runs an implicit DELETE and every ON DELETE CASCADE / SET NULL child of
# users is wiped — the runner therefore disables enforcement around each file and runs foreign_key_check instead.
REBUILD_USERS_SQL = """
PRAGMA foreign_keys=OFF;  -- a no-op inside the runner's transaction; kept to show a file cannot rely on it
CREATE TABLE users_new (
  id                INTEGER PRIMARY KEY,
  username          TEXT NOT NULL COLLATE NOCASE,
  email             TEXT COLLATE NOCASE,
  email_verified_at TEXT,
  display_name      TEXT,
  password_hash     TEXT NOT NULL,
  role              TEXT NOT NULL DEFAULT 'user'    CHECK (role IN ('user','admin','guest')),
  is_active         INTEGER NOT NULL DEFAULT 1      CHECK (is_active IN (0,1)),
  onboarding_state  TEXT NOT NULL DEFAULT 'pending' CHECK (onboarding_state IN ('pending','screen','done')),
  created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  updated_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  last_login_at     TEXT
);
INSERT INTO users_new SELECT * FROM users;
DROP TABLE users;
ALTER TABLE users_new RENAME TO users;
CREATE UNIQUE INDEX ux_users_username ON users(username);
CREATE UNIQUE INDEX ux_users_email    ON users(email) WHERE email IS NOT NULL;
"""

USER_CHILD_TABLES = ("user_settings", "sessions", "user_words", "review_logs", "daily_stats", "push_batches", "push_items", "email_codes")


def _migrations_dir_with(tmp_path: Path, second_file: str, sql: str) -> Path:
    mig = tmp_path / "migrations"
    mig.mkdir()
    shutil.copy(db.MIGRATIONS_DIR / "0001_init.sql", mig / "0001_init.sql")
    (mig / second_file).write_text(sql, encoding="utf-8")
    return mig


def _seed_user_with_history(conn: sqlite3.Connection) -> None:
    with db.tx(conn):
        conn.execute("INSERT INTO users(id, username, password_hash) VALUES (1, 'alice', '$2b$12$x')")
        conn.execute("INSERT INTO user_settings(user_id, next_push_at) VALUES (1, '2026-10-29T00:00:00Z')")
        conn.execute("INSERT INTO sessions(token_hash, user_id, expires_at) VALUES ('tok', 1, '2026-11-27T00:00:00Z')")
        conn.execute("INSERT INTO words(id, lemma, display, source) VALUES (1, 'abandon', 'abandon', 'seed')")
        conn.execute("INSERT INTO user_words(id, user_id, word_id, state, origin) VALUES (1, 1, 1, 'learning', 'browse')")
        conn.execute("INSERT INTO review_logs(user_id, word_id, user_word_id, action, context, local_date) VALUES (1, 1, 1, 'good', 'today', '2026-10-28')")
        conn.execute("INSERT INTO daily_stats(user_id, local_date, graded) VALUES (1, '2026-10-28', 1)")
        conn.execute("INSERT INTO push_batches(id, user_id, local_date, timezone, trigger) VALUES (1, 1, '2026-10-28', 'Asia/Shanghai', 'scheduled')")
        conn.execute("INSERT INTO push_items(batch_id, word_id, user_word_id, kind, position) VALUES (1, 1, 1, 'review', 1)")
        conn.execute("INSERT INTO email_codes(user_id, email, code_hash, expires_at) VALUES (1, 'a@b.c', 'h', '2026-10-28T01:00:00Z')")
        conn.execute("INSERT INTO invite_codes(code_hash, created_by) VALUES ('ic', 1)")


def _counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("users", *USER_CHILD_TABLES)}


def test_migration_rebuilding_a_parent_table_keeps_every_child_row(settings, tmp_path: Path):
    mig = _migrations_dir_with(tmp_path, "0002_rebuild_users.sql", REBUILD_USERS_SQL)
    stash = (mig / "0002_rebuild_users.sql").rename(tmp_path / "stash.sql")  # apply 0001 alone first, then seed data
    c = db.connect(settings.db_path)
    try:
        assert db.run_migrations(c, migrations_dir=mig).applied == [(1, "init")]
        _seed_user_with_history(c)
        before = _counts(c)
        assert set(before.values()) == {1}
        stash.rename(mig / "0002_rebuild_users.sql")

        result = db.run_migrations(c, migrations_dir=mig)  # the same call as `wd migrate` / the service startup

        assert result.applied == [(2, "rebuild_users")]
        assert _counts(c) == before  # DROP TABLE users did not cascade: the learning history survived
        assert c.execute("SELECT created_by FROM invite_codes").fetchone()[0] == 1  # ON DELETE SET NULL did not fire either
        assert "'guest'" in c.execute("SELECT sql FROM sqlite_master WHERE name = 'users'").fetchone()[0]  # the new CHECK is in place
        assert [r[0] for r in c.execute("SELECT version FROM schema_migrations ORDER BY version")] == [1, 2]
        assert not c.in_transaction
        assert c.execute("PRAGMA foreign_keys").fetchone()[0] == 1  # enforcement is back on the (reused) connection …
        with pytest.raises(sqlite3.IntegrityError):  # … and live against the rebuilt table
            with db.tx(c):
                c.execute("INSERT INTO sessions(token_hash, user_id, expires_at) VALUES ('bad', 999, '2026-12-01T00:00:00Z')")
        assert c.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        c.close()


def test_migration_leaving_dangling_foreign_keys_is_rolled_back(settings, tmp_path: Path):
    mig = _migrations_dir_with(
        tmp_path,
        "0002_orphans.sql",
        "INSERT INTO kv(key, value) VALUES ('orphan.marker', '1');\n"
        "INSERT INTO sessions(token_hash, user_id, expires_at) VALUES ('orphan', 999, '2026-12-01T00:00:00Z');\n",  # no user 999
    )
    c = db.connect(settings.db_path)
    try:
        with pytest.raises(db.MigrationError) as info:
            db.run_migrations(c, migrations_dir=mig)
        assert info.value.version == 2 and info.value.name == "orphans"
        assert "1 foreign-key violation(s): sessions rowid" in str(info.value)  # reported by foreign_key_check, before COMMIT
        assert [r[0] for r in c.execute("SELECT version FROM schema_migrations ORDER BY version")] == [1]
        assert c.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
        assert db.kv_get(c, "orphan.marker") is None  # the whole file rolled back, not just the offending statement
        assert not c.in_transaction
        assert c.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        c.close()


# ----------------------------------------------------------------------------------- 0008: FK child indexes
def test_upgrade_from_the_baseline_schema_applies_the_later_files(settings, tmp_path: Path):
    """An existing deployment sits at version 1 (0001 only): the next `wd migrate` applies 0008 … on top of its data."""
    baseline = tmp_path / "baseline"
    baseline.mkdir()
    shutil.copy(db.MIGRATIONS_DIR / "0001_init.sql", baseline / "0001_init.sql")
    hooks: list[tuple[int, int]] = []
    c = db.connect(settings.db_path)
    try:
        assert db.run_migrations(c, migrations_dir=baseline).applied == [(1, "init")]
        _seed_user_with_history(c)
        before = _counts(c)
        result = db.run_migrations(c, pre_hook=lambda a, b: hooks.append((a, b)))
        shipped = shipped_migrations()
        assert result.applied == shipped[1:] and (8, "fk_child_indexes") in result.applied
        assert hooks == [(1, shipped[-1][0])]  # → backups/pre-migrate-1-to-<latest>.db.gz
        assert _counts(c) == before
        assert {"ix_push_items_user_word", "ix_push_items_word", "ix_bank_suggestions_user_word"} <= {
            r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type = 'index'")
        }
        assert db.run_migrations(c).applied == []  # idempotent
    finally:
        c.close()


def _leading_index_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    cols = set()
    for ix in conn.execute(f"PRAGMA index_list({table})"):
        first = conn.execute(f"PRAGMA index_info({ix['name']})").fetchone()  # seqno 0 = the leading column
        if first is not None:
            cols.add(first["name"])
    return cols


@pytest.mark.parametrize(
    ("table", "column", "action"),
    [("push_items", "user_word_id", "SET NULL"), ("push_items", "word_id", "CASCADE"), ("bank_suggestions", "user_word_id", "CASCADE")],
)
def test_fk_child_columns_of_the_account_deletion_cascade_are_indexed(conn, table, column, action):
    """Without a leading index each deleted user_words/words row scans the child table in full inside `DELETE FROM users`."""
    fks = {r["from"]: r for r in conn.execute(f"PRAGMA foreign_key_list({table})")}
    assert fks[column]["on_delete"] == action
    assert column in _leading_index_columns(conn, table), f"{table}.{column} has no leading index (0008_fk_child_indexes.sql)"
    plan = " ".join(str(r["detail"]) for r in conn.execute(f"EXPLAIN QUERY PLAN SELECT id FROM {table} WHERE {column} = 1"))
    assert "SCAN" not in plan and "INDEX" in plan, plan


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


def test_backup_pre_hook_is_the_pre_migrate_snapshot():
    from wd.backup import snapshot_before_migrate

    assert db.backup_pre_hook() is snapshot_before_migrate


def test_schema_file_is_byte_identical_to_docs_copy_when_present():
    docs = Path(__file__).resolve().parents[3] / "docs" / "SCHEMA.sql"
    if not docs.is_file():
        pytest.skip("docs/SCHEMA.sql not present in this checkout")
    assert docs.read_bytes() == (db.MIGRATIONS_DIR / "0001_init.sql").read_bytes()
