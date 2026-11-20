"""0022_assignments.sql (布置词汇, docs/releases/2026-11-assignments.md): two tables and their indexes, nothing else — additive like 0020,
statement shape pinned; existing rows of every other table are untouched and the ON DELETE rules hold."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from wd import db

ALLOWED_PREFIXES = ("CREATE TABLE ", "CREATE INDEX ", "CREATE UNIQUE INDEX ")
INDEXES_0022 = {"ix_assignments_learner", "ix_assignments_assigner", "ux_assignment_words_word", "ix_assignment_words_item", "ix_assignment_words_open"}


def test_0022_is_additive_and_only_creates_tables_and_indexes():
    file = next(f for f in db.list_migration_files() if f.version == 22)
    assert file.path.name == "0022_assignments.sql"
    body = "\n".join(line for line in file.path.read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith("--"))
    statements = [" ".join(s.split()) for s in body.split(";") if s.strip()]
    assert len(statements) == 7 and all(s.startswith(ALLOWED_PREFIXES) for s in statements)


def test_0022_adds_two_tables_keeps_rows_and_cascades(settings, tmp_path: Path):
    older = tmp_path / "older"
    older.mkdir()
    for f in db.list_migration_files():
        if f.version < 22:
            shutil.copy(f.path, older / f.path.name)
    c = db.connect(settings.db_path)
    try:
        assert db.run_migrations(c, migrations_dir=older).applied[-1][0] == 21
        with db.tx(c):
            c.execute("INSERT INTO users(id, username, password_hash) VALUES (1, 'teacher', 'x'), (2, 'kid', 'x')")
            c.execute("INSERT INTO words(id, lemma, display, source) VALUES (1, 'apple', 'apple', 'seed')")
            c.execute("INSERT INTO push_batches(id, user_id, local_date, timezone, trigger) VALUES (1, 2, '2026-10-14', 'Asia/Shanghai', 'manual')")
            c.execute("INSERT INTO push_items(id, batch_id, word_id, kind, position) VALUES (1, 1, 1, 'new', 0)")
        before_tables = set(db.table_names(c))
        before = {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("users", "words", "push_batches", "push_items")}
        assert [v for v, _ in db.run_migrations(c).applied] == [22]
        assert set(db.table_names(c)) == before_tables | {"assignments", "assignment_words"}
        assert before == {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in before}
        assert {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name IN ('assignments', 'assignment_words') AND name NOT LIKE 'sqlite_%'")} == INDEXES_0022
        with db.tx(c):
            c.execute("INSERT INTO assignments(id, assigner_id, learner_id, mode) VALUES (1, 1, 2, 'today')")
            c.execute("INSERT INTO assignment_words(assignment_id, word_id, position, status, push_item_id, scheduled_date) VALUES (1, 1, 0, 'scheduled', 1, '2026-10-14')")
        for bad in ("INSERT INTO assignments(assigner_id, learner_id, mode) VALUES (1, 2, 'weekly')", "INSERT INTO assignment_words(assignment_id, word_id, position, status) VALUES (1, 1, 1, 'done')", "INSERT INTO assignment_words(assignment_id, word_id, position) VALUES (1, 1, 1)"):
            with pytest.raises(sqlite3.IntegrityError):
                c.execute(bad)
        with db.tx(c):
            c.execute("DELETE FROM push_items WHERE id = 1")  # the word stays scheduled, without its item
        assert tuple(c.execute("SELECT status, push_item_id FROM assignment_words").fetchone()) == ("scheduled", None)
        with db.tx(c):
            c.execute("DELETE FROM users WHERE id = 2")  # the learner's lists go with the account
        assert c.execute("SELECT COUNT(*) FROM assignments").fetchone()[0] == 0 and c.execute("SELECT COUNT(*) FROM assignment_words").fetchone()[0] == 0
    finally:
        c.close()
