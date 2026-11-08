"""0013_word_forms_alias.sql (PLAN §2.4): word_forms is rebuilt so that kind admits 'alias' (seed spelling aliases from
data/lists/aliases.tsv). Existing rows — including lookup-written 'alt' rows — survive, the primary key and the index come
back, a bogus kind is still rejected, and the table set is unchanged. Also the fresh path (0001 → latest)."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from wd import db

from test_db import EXPECTED_TABLES  # sibling module (pytest prepend import mode, like test_admin_ops imports fake_openai)


def _schema_dir_up_to(tmp_path: Path, last_version: int) -> Path:
    """A migrations directory holding the shipped files up to ``last_version`` (a database frozen at that version)."""
    d = tmp_path / f"upto{last_version}"
    d.mkdir()
    for mf in db.list_migration_files():
        if mf.version <= last_version:
            shutil.copy(mf.path, d / mf.path.name)
    return d


def test_upgrade_0013_keeps_rows_and_admits_alias(settings, tmp_path: Path):
    c = db.connect(settings.db_path)
    try:
        result = db.run_migrations(c, migrations_dir=_schema_dir_up_to(tmp_path, 11))
        assert result.applied[-1] == (11, "primary_stage") and db.current_version(c) == 11
        c.execute("INSERT INTO words(id, lemma, display, source) VALUES (1, 'go', 'go', 'seed')")
        c.execute("INSERT INTO words(id, lemma, display, source) VALUES (2, 'tv', 'TV', 'seed')")
        c.executemany(
            "INSERT INTO word_forms(form, word_id, kind) VALUES (?, ?, ?)",
            [("went", 1, "p"), ("gone", 1, "d"), ("goes", 1, "3"), ("goed", 1, "alt"), ("tvs", 2, "s")],
        )
        with pytest.raises(sqlite3.IntegrityError):  # the v11 CHECK list has no 'alias' yet
            c.execute("INSERT INTO word_forms(form, word_id, kind) VALUES ('t.v.', 2, 'alias')")
        before_tables = set(db.table_names(c))

        result = db.run_migrations(c)  # the same call as `wd migrate` / the service startup

        assert (13, "word_forms_alias") in result.applied and db.current_version(c) >= 13
        assert not c.in_transaction and c.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert set(db.table_names(c)) == before_tables | {"word_dances"} == EXPECTED_TABLES  # 0016 adds word_dances on the way
        rows = [tuple(r) for r in c.execute("SELECT form, word_id, kind FROM word_forms ORDER BY word_id, form")]
        assert rows == [("goed", 1, "alt"), ("goes", 1, "3"), ("gone", 1, "d"), ("went", 1, "p"), ("tvs", 2, "s")]  # every row incl. alt survived
        c.execute("INSERT INTO word_forms(form, word_id, kind) VALUES ('t.v.', 2, 'alias')")
        assert c.execute("SELECT kind FROM word_forms WHERE form = 't.v.'").fetchone()[0] == "alias"
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("INSERT INTO word_forms(form, word_id, kind) VALUES ('tee vee', 2, 'bogus')")
        with pytest.raises(sqlite3.IntegrityError):  # the primary key (form, word_id) is back
            c.execute("INSERT INTO word_forms(form, word_id, kind) VALUES ('t.v.', 2, 'alt')")
        with pytest.raises(sqlite3.IntegrityError):  # still a child of words
            c.execute("INSERT INTO word_forms(form, word_id, kind) VALUES ('x', 999, 'alias')")
        ddl = c.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'word_forms'").fetchone()[0]
        assert "'alt','alias'" in ddl and "WITHOUT ROWID" in ddl
        indexes = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'word_forms'")}
        assert "ix_word_forms_word" in indexes
        plan = " ".join(str(r[-1]) for r in c.execute("EXPLAIN QUERY PLAN SELECT form FROM word_forms WHERE word_id = 1"))
        assert "ix_word_forms_word" in plan
        c.execute("DELETE FROM words WHERE id = 2")  # ON DELETE CASCADE still wired
        assert c.execute("SELECT COUNT(*) FROM word_forms WHERE word_id = 2").fetchone()[0] == 0
        assert c.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.run_migrations(c).applied == []  # idempotent
    finally:
        c.close()


def test_fresh_database_admits_alias_forms(conn):
    assert (13, "word_forms_alias") in [(r[0], r[1]) for r in conn.execute("SELECT version, name FROM schema_migrations")]
    conn.execute("INSERT INTO words(id, lemma, display, source) VALUES (1, 'mr.', 'Mr.', 'seed')")
    conn.execute("INSERT INTO word_forms(form, word_id, kind) VALUES ('mr', 1, 'alias')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO word_forms(form, word_id, kind) VALUES ('mister', 1, 'nickname')")
    assert db.view_names(conn) == ["v_bank"]
