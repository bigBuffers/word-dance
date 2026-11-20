"""db.py: migration runner bookkeeping and atomicity, tx(), connect() PRAGMAs, kv helpers (TASKS P0 acceptance)."""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from wd import db

EXPECTED_TABLES = {
    "schema_migrations", "kv", "system_events", "users", "sessions", "invite_codes", "auth_throttle", "email_codes", "user_settings",
    "words", "word_forms", "word_contents", "word_images", "user_words", "review_logs", "daily_stats", "push_batches", "push_items",
    "consolidation_runs", "bank_suggestions", "jobs", "ai_calls", "provider_usage", "provider_state", "content_reports", "word_dances",
    "identities", "login_codes",  # 0018 (docs/AUTH_SIGNUP_DESIGN.md §5.1)
    "family_codes",  # 0019 (docs/AUTH_SIGNUP_DESIGN.md §5.1–5.2: child login codes + claim codes, slice 1-B)
    "wechat_tickets",  # 0020 (docs/AUTH_SIGNUP_DESIGN.md §5.3: the WeChat login bridge, slice 2-A)
    "assignments", "assignment_words",  # 0022 (布置词汇, docs/releases/2026-11-assignments.md)
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
        assert len(tables) == 32
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


# ----------------------------------------------------------------------------------- 0009: phonetic delimiters
def test_upgrade_strips_ipa_delimiters_from_stored_phonetics(settings, tmp_path: Path):
    """Before ai/common.clean_phonetic a Claude lookup could store "/…/" or "[…]"; the UI adds its own slashes, so those rows
    rendered as //…//. 0009 repairs them once and leaves ECDICT-style values ("ə'biliti") alone."""
    baseline = tmp_path / "baseline"
    baseline.mkdir()
    shutil.copy(db.MIGRATIONS_DIR / "0001_init.sql", baseline / "0001_init.sql")
    c = db.connect(settings.db_path)
    try:
        assert db.run_migrations(c, migrations_dir=baseline).applied == [(1, "init")]
        c.executemany(
            "INSERT INTO words(id, lemma, display, source, phonetic) VALUES (?, ?, ?, ?, ?)",
            [
                (1, "gdp", "GDP", "claude", "/ˌdʒiː diː ˈpiː/"),
                (2, "abandon", "abandon", "claude", "[əˈbændən]"),
                (3, "ability", "ability", "seed", "ə'biliti"),
                (4, "blank", "blank", "claude", "/ /"),
                (5, "none", "none", "seed", None),
                (6, "slash", "slash", "seed", "a/b"),  # an inner slash is not a delimiter
            ],
        )
        result = db.run_migrations(c)
        assert (9, "strip_phonetic_delimiters") in result.applied
        rows = {r["id"]: r["phonetic"] for r in c.execute("SELECT id, phonetic FROM words ORDER BY id")}
        assert rows == {1: "ˌdʒiː diː ˈpiː", 2: "əˈbændən", 3: "ə'biliti", 4: None, 5: None, 6: "a/b"}
        assert db.run_migrations(c).applied == []  # idempotent: a second run matches nothing
        assert not c.in_transaction
    finally:
        c.close()


# ----------------------------------------------------------------------------------- 0011: primary stage (小学, index 1..5)
# Tables whose rows must survive the rebuild of words / user_settings: FK children of the two tables plus the user history
# that the account-deletion cascade would wipe if DROP TABLE ran with enforcement on (the runner disables it, see above).
PRE_0011_ROW_TABLES = ("users", "user_settings", "words", "sessions", "user_words", "review_logs", "push_batches", "push_items", "word_contents", "word_images", "content_reports", "bank_suggestions")


def _seed_pre_0011_data(conn: sqlite3.Connection) -> None:
    """A database at the OLD stage index (1=zk 2=gk 3=cet4 4=cet6): the two live users' settings shapes (sqin: four stages, 主攻 3=cet4;
    kimi: ["zk"], 主攻 1=zk), one seed word per old stage_min plus a 课标外 one (NULL) and a private user word that references
    another word and a user, and one row in every child table so the rebuild's DROP TABLE can be shown not to cascade."""
    with db.tx(conn):
        conn.executemany("INSERT INTO users(id, username, password_hash) VALUES (?, ?, '$2b$12$x')", [(1, "sqin"), (2, "kimi")])
        conn.executemany(
            "INSERT INTO user_settings(user_id, stages_json, current_stage, next_push_at) VALUES (?, ?, ?, '2026-11-07T00:00:00Z')",
            [(1, '["zk","gk","cet4","cet6"]', 3), (2, '["zk"]', 1)],
        )
        conn.executemany(
            "INSERT INTO words(id, lemma, display, source, stage_zk, stage_gk, stage_cet4, stage_cet6, stage_min, difficulty, sources)"
            " VALUES (?, ?, ?, 'seed', ?, ?, ?, ?, ?, ?, ?)",
            [
                (1, "a", "a", 1, 1, 1, 1, 1, 1, "cet4 cet46 ecdict gk zk"),  # old 1 = zk; Claude difficulty 1 = stage_min (old scale)
                (2, "abandon", "abandon", 0, 1, 1, 1, 2, 2, "cet4 cet46 ecdict gk"),  # old 2 = gk
                (3, "absolutely", "absolutely", 0, 0, 1, 1, 3, None, "cet4 cet46 ecdict"),  # old 3 = cet4, no AI content yet
                (4, "ought to", "ought to", 0, 0, 0, 1, 4, 4, "cet6 ecdict"),  # old 4 = cet6
                (5, "bungalow", "bungalow", 0, 0, 0, 0, None, 5, None),  # outside every list: stays NULL
            ],
        )
        conn.execute("INSERT INTO words(id, lemma, display, source, merged_into_word_id, created_by_user_id, is_public) VALUES (6, 'abandonned', 'abandonned', 'user', 2, 1, 0)")
        conn.execute("INSERT INTO sessions(token_hash, user_id, expires_at) VALUES ('tok', 1, '2026-12-01T00:00:00Z')")
        conn.executemany("INSERT INTO user_words(id, user_id, word_id, state, origin) VALUES (?, ?, ?, ?, ?)", [(1, 1, 2, "learning", "browse"), (2, 2, 1, "new", "screen")])
        conn.execute("INSERT INTO review_logs(user_id, word_id, user_word_id, action, context, local_date) VALUES (1, 2, 1, 'good', 'today', '2026-11-05')")
        conn.execute(
            "INSERT INTO push_batches(id, user_id, local_date, timezone, trigger, settings_json) VALUES (1, 1, '2026-11-05', 'Asia/Shanghai', 'scheduled', ?)",
            ('{"stages": ["zk", "gk", "cet4", "cet6"], "current_stage": 3}',),  # snapshot written at the OLD index (write-only column)
        )
        conn.execute("INSERT INTO push_items(batch_id, word_id, user_word_id, kind, position) VALUES (1, 2, 1, 'review', 1)")
        conn.execute("INSERT INTO word_contents(id, word_id, version, prompt_version, model, content_json) VALUES (1, 2, 1, 'content-v1', 'claude-sonnet-4-5', '{}')")
        conn.execute("INSERT INTO word_images(id, word_id, provider, file_path, file_bytes, sha256, mime) VALUES (1, 2, 'wikimedia', 'ab/ab12.jpg', 1, 'sha', 'image/jpeg')")
        conn.execute("UPDATE words SET active_content_id = 1, active_image_id = 1, content_state = 'ready', image_state = 'ready' WHERE id = 2")
        conn.execute("INSERT INTO content_reports(user_id, word_id, target, reason) VALUES (1, 2, 'content', 'other')")
        conn.execute("INSERT INTO bank_suggestions(user_id, type, user_word_id, target_word_id, payload_json) VALUES (1, 'fix_spelling', 1, 2, '{}')")
        conn.execute("INSERT INTO kv(key, value) VALUES ('seed_version', 'deadbeef')")


def _row_counts(conn: sqlite3.Connection, tables: tuple[str, ...]) -> dict[str, int]:
    return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}


def test_upgrade_0011_renumbers_stages_and_rebuilds_two_tables(settings, tmp_path: Path):
    """0011 adds the 小学 stage (code xs). SQLite cannot widen a CHECK list or change a DEFAULT, so words and user_settings are
    rebuilt (CREATE new → INSERT … SELECT → DROP → RENAME → indexes → view): every stored stage_min / current_stage moves +1
    (old 1=zk … 4=cet6 → new 2..5, NULL stays NULL), stage_xs starts at 0 for every row (the seed re-import derives it from the
    official lists), stages_json holds codes and is copied as is — nobody is enrolled in xs automatically —, the new-user
    default becomes K-12 ('["xs","zk"]' / 1), kv.seed_version is cleared so the next start re-imports unconditionally, and
    an operator-visible system_events('migration') row is left behind. The DROP TABLEs must not cascade into the history."""
    baseline = tmp_path / "baseline"
    baseline.mkdir()
    shutil.copy(db.MIGRATIONS_DIR / "0001_init.sql", baseline / "0001_init.sql")
    c = db.connect(settings.db_path)
    try:
        assert db.run_migrations(c, migrations_dir=baseline).applied == [(1, "init")]
        _seed_pre_0011_data(c)
        before_counts = _row_counts(c, PRE_0011_ROW_TABLES)
        before_min = {r["id"]: r["stage_min"] for r in c.execute("SELECT id, stage_min FROM words")}
        assert sorted(sm for sm in before_min.values() if sm is not None) == [1, 2, 3, 4]
        before_settings_cols = [r["name"] for r in c.execute("PRAGMA table_info(user_settings)")]
        before_words_cols = [r["name"] for r in c.execute("PRAGMA table_info(words)")]
        batch_snapshot = c.execute("SELECT settings_json FROM push_batches WHERE id = 1").fetchone()[0]

        result = db.run_migrations(c)  # the same call as `wd migrate` / the service startup

        assert (11, "primary_stage") in result.applied
        assert not c.in_transaction
        assert c.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert set(db.table_names(c)) == EXPECTED_TABLES  # rebuilt in place: no table gained or lost
        assert db.view_names(c) == ["v_bank"]  # dropped before the rebuild and re-created afterwards …
        assert c.execute("SELECT COUNT(*) FROM v_bank").fetchone()[0] == 2  # … and it joins the NEW words table (both bank rows are new/learning)

        # --- renumbering: exactly +1 per row, NULL (课标外) stays NULL, stage_xs is 0 until the seed re-import
        after_min = {r["id"]: r["stage_min"] for r in c.execute("SELECT id, stage_min FROM words")}
        assert after_min == {wid: (None if sm is None else sm + 1) for wid, sm in before_min.items()}
        assert sorted(sm for sm in after_min.values() if sm is not None) == [2, 3, 4, 5]
        assert tuple(c.execute("SELECT SUM(stage_xs), SUM(stage_zk), SUM(stage_gk), SUM(stage_cet4), SUM(stage_cet6) FROM words").fetchone()) == (0, 1, 2, 3, 4)
        # the Claude difficulty scale is NOT renumbered (1 初中 … 5 beyond): where it matched stage_min before, it is now stage_min − 1
        assert c.execute("SELECT COUNT(*) FROM words WHERE difficulty IS NOT NULL AND stage_min IS NOT NULL AND difficulty + 1 != stage_min").fetchone()[0] == 0
        assert {r["user_id"]: (r["stages_json"], r["current_stage"]) for r in c.execute("SELECT user_id, stages_json, current_stage FROM user_settings")} == {
            1: ('["zk","gk","cet4","cet6"]', 4),  # 3 (cet4) → 4 (cet4); the codes are untouched, xs is not added
            2: ('["zk"]', 2),  # 1 (zk) → 2 (zk)
        }
        assert c.execute("SELECT settings_json FROM push_batches WHERE id = 1").fetchone()[0] == batch_snapshot  # old snapshots are not rewritten

        # --- every other column and every child row survived the two DROP TABLEs (no cascade; FK targets still resolve)
        assert _row_counts(c, PRE_0011_ROW_TABLES) == before_counts
        assert c.execute("PRAGMA foreign_key_check").fetchall() == []
        assert tuple(c.execute("SELECT merged_into_word_id, created_by_user_id, is_public, source FROM words WHERE id = 6").fetchone()) == (2, 1, 0, "user")
        assert tuple(c.execute("SELECT active_content_id, active_image_id, content_state, image_state, difficulty, sources FROM words WHERE id = 2").fetchone()) == (1, 1, "ready", "ready", 2, "cet4 cet46 ecdict gk")
        assert tuple(c.execute("SELECT timezone, push_time, daily_new_count, next_push_at FROM user_settings WHERE user_id = 1").fetchone()) == ("Asia/Shanghai", "08:00", 10, "2026-11-07T00:00:00Z")

        # --- the new DDL: stage_xs in front of the other flags (seed.SEED_COLUMNS order), CHECKs 1..5, every index back, K-12 defaults
        words_cols = [r["name"] for r in c.execute("PRAGMA table_info(words)")]
        expected_cols = before_words_cols[: before_words_cols.index("stage_zk")] + ["stage_xs"] + before_words_cols[before_words_cols.index("stage_zk") :]
        if (14, "learn_rank") in result.applied:
            expected_cols.append("learn_rank")  # 0014_learn_rank.sql: one ADD COLUMN, appended after the 0011 layout (test_db_0014.py)
        if (16, "word_dances") in result.applied:
            expected_cols.extend(["active_dance_id", "dance_state"])  # 0016_word_dances.sql: two ADD COLUMNs (test_db_0016.py)
        assert words_cols == expected_cols
        assert [r["name"] for r in c.execute("PRAGMA table_info(user_settings)")] == [*before_settings_cols, "dance_mode", "image_word"]  # 0011 keeps the list; 0015 and 0021 append one column each
        ddl = {r["name"]: r["sql"] for r in c.execute("SELECT name, sql FROM sqlite_master WHERE type = 'table' AND name IN ('words', 'user_settings')")}
        assert "CHECK (stage_min BETWEEN 1 AND 5)" in ddl["words"] and "CHECK (stage_xs   IN (0,1))" in ddl["words"]
        assert "CHECK (difficulty BETWEEN 1 AND 5)" in ddl["words"]  # unchanged scale
        assert "CHECK (current_stage BETWEEN 1 AND 5)" in ddl["user_settings"]
        index_names = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name IN ('words', 'user_settings')")}
        assert {"ux_words_lemma", "ix_words_frq", "ix_words_stage_min", "ix_words_content", "ix_words_created_by", "ix_words_public", "ix_user_settings_next_push"} <= index_names
        defaults = {r["name"]: r["dflt_value"] for r in c.execute("PRAGMA table_info(user_settings)")}
        assert (defaults["stages_json"], defaults["current_stage"]) == ("'[\"xs\",\"zk\"]'", "1")
        c.execute("INSERT INTO users(id, username, password_hash) VALUES (3, 'newbie', '$2b$12$x')")
        c.execute("INSERT INTO user_settings(user_id, next_push_at) VALUES (3, '2026-11-07T00:00:00Z')")
        assert tuple(c.execute("SELECT stages_json, current_stage FROM user_settings WHERE user_id = 3").fetchone()) == ('["xs","zk"]', 1)
        for stmt in (
            "UPDATE words SET stage_min = 0 WHERE id = 1",
            "UPDATE words SET stage_min = 6 WHERE id = 1",
            "UPDATE words SET stage_xs = 2 WHERE id = 1",
            "UPDATE user_settings SET current_stage = 0 WHERE user_id = 1",
            "UPDATE user_settings SET current_stage = 6 WHERE user_id = 1",
        ):
            with pytest.raises(sqlite3.IntegrityError):
                c.execute(stmt)
        c.execute("UPDATE words SET stage_xs = 1, stage_min = 1 WHERE id = 1")  # the new lowest stage is storable
        c.execute("UPDATE user_settings SET stages_json = '[\"xs\",\"zk\"]', current_stage = 1 WHERE user_id = 2")
        with pytest.raises(sqlite3.IntegrityError):  # the rebuilt words table is still the FK parent of user_words
            c.execute("INSERT INTO user_words(user_id, word_id, state, origin) VALUES (1, 999999, 'new', 'browse')")

        # --- forced seed re-import + operator trace
        assert db.kv_get(c, "seed_version") is None
        assert c.execute("SELECT kind FROM system_events ORDER BY id DESC LIMIT 1").fetchone()[0] == "migration"
        events = [json.loads(r["detail_json"]) for r in c.execute("SELECT detail_json FROM system_events WHERE kind = 'migration' ORDER BY id")]
        assert any(e.get("version") == 11 and e.get("name") == "primary_stage" for e in events)

        assert db.run_migrations(c).applied == []  # idempotent
        assert not c.in_transaction
    finally:
        c.close()


def test_fresh_database_has_the_five_stage_ddl(conn):
    """The fresh path (the ``conn`` fixture: 0001 → latest on an empty database) lands on the five-stage DDL and the K-12
    defaults as well: 0011 rebuilds words / user_settings from the same file whether or not they hold rows, so this is
    the empty-database counterpart of the upgrade test above (a few DDL fragments, defaults and column order — not a
    comparison of the two DDL texts). It also pins what every other test inherits from the fixture: 0011 leaves a
    system_events('migration') row (PLAN §2.2 / D-3), so a migrated test database is never event-free — tests that count
    the whole table filter ``kind != 'migration'`` the way they already filter the seed import's 'seed_imported'."""
    ddl = {r["name"]: r["sql"] for r in conn.execute("SELECT name, sql FROM sqlite_master WHERE type = 'table' AND name IN ('words', 'user_settings')")}
    assert "CHECK (stage_min BETWEEN 1 AND 5)" in ddl["words"] and "stage_xs" in ddl["words"]
    assert "CHECK (current_stage BETWEEN 1 AND 5)" in ddl["user_settings"]
    defaults = {r["name"]: r["dflt_value"] for r in conn.execute("PRAGMA table_info(user_settings)")}
    assert (defaults["stages_json"], defaults["current_stage"]) == ("'[\"xs\",\"zk\"]'", "1")
    assert [r["name"] for r in conn.execute("PRAGMA table_info(words)") if r["name"].startswith("stage_")] == ["stage_xs", "stage_zk", "stage_gk", "stage_cet4", "stage_cet6", "stage_min"]
    assert (11, "primary_stage") in [(r[0], r[1]) for r in conn.execute("SELECT version, name FROM schema_migrations")]
    kinds = [r[0] for r in conn.execute("SELECT kind FROM system_events ORDER BY id")]
    assert kinds and set(kinds) == {"migration"}  # the fixture's only events are migration traces (0011's; a later rebuild may add its own)
    traces = [json.loads(r[0]) for r in conn.execute("SELECT detail_json FROM system_events WHERE kind = 'migration' ORDER BY id")]
    assert {(t.get("version"), t.get("name")) for t in traces} >= {(11, "primary_stage")}


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
