"""0017_word_dances_corrected.sql (docs/WORD_DANCE_DESIGN.md §13, releases/2026-11-word-dance-p3b.md): `word_dances` gains the nullable
`corrected` flag (CHECK 0/1) and nothing else — every existing row is left NULL and `wd.dance.backfill_corrected` (the service start)
computes it from the stored spec and the ordinary rules, comparing the stress with the one the model was given. Additive like
0012 / 0014 / 0015."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from wd import dance, db

SPEC = '{"version": 1, "letters": %s, "stress": %s, "marks": {"double": [], "silent": []}, "semantic": null, "source": "claude"}'


def _database_at_0016(settings, tmp_path: Path) -> sqlite3.Connection:
    older = tmp_path / "older"
    older.mkdir()
    for f in db.list_migration_files():
        if f.version < 17:
            shutil.copy(f.path, older / f.path.name)
    c = db.connect(settings.db_path)
    applied = db.run_migrations(c, migrations_dir=older).applied
    assert applied and applied[-1][0] == 16
    with db.tx(c):
        words = [
            (1, "worker", "worker", "'wɜːkə"),
            (2, "teacher", "teacher", "'tiːtʃə"),
            (3, "up", "up", "ʌp"),
            (4, "ok", "OK", None),  # no phonetic: no rule spec today
            (5, "happy", "happy", "'hæpi"),
            (6, "abandon", "abandon", "ə'bændən"),
            (7, "rhythm", "rhythm", "'riðəm"),  # the rules keep it one chunk with stress None; the prompt says rule_stress 0
        ]
        c.executemany("INSERT INTO words(id, lemma, display, source, phonetic, is_valid_english) VALUES (?, ?, ?, 'seed', ?, 1)", words)
        rows = [  # (id, word_id, status, spec_json, prompt_version)
            (1, 1, "superseded", SPEC % ('["wor", "ker"]', 0), "dance-v1"),
            (2, 1, "active", SPEC % ('["wor", "ker"]', 0), "dance-v2"),  # confirmed the rule cut
            (3, 2, "active", SPEC % ('["teach", "er"]', 0), "dance-v1"),  # corrected the chunks (tea·cher)
            (4, 3, "active", SPEC % ('["up"]', 0), "dance-v1"),  # confirmed
            (5, 4, "active", SPEC % ('["O", "K"]', 1), "dance-v1"),  # no rule spec → counts as corrected
            (6, 5, "active", SPEC % ('["happ", "y"]', 0), "dance-v1"),  # corrected the chunks
            (7, 6, "active", SPEC % ('["a", "ban", "don"]', 0), "dance-v1"),  # corrected the stress alone (rule: 1)
            (8, 7, "active", SPEC % ('["rhythm"]', 0), "dance-v1"),  # echoed the degraded suggestion (stress 0 for None): confirmed
            (9, 7, "superseded", "null", "dance-v1"),  # a non-object spec_json never stops the backfill
        ]
        c.executemany("INSERT INTO word_dances(id, word_id, status, spec_json, model, prompt_version, created_at) VALUES (?, ?, ?, ?, 'm', ?, '2026-11-08T06:00:00Z')", rows)
        for word_id, dance_id in ((1, 2), (2, 3), (3, 4), (4, 5), (5, 6), (6, 7), (7, 8)):
            c.execute("UPDATE words SET active_dance_id = ?, dance_state = 'ready' WHERE id = ?", (dance_id, word_id))
    return c


def test_0017_adds_the_nullable_flag_and_the_startup_backfill_computes_it(settings, tmp_path: Path):
    c = _database_at_0016(settings, tmp_path)
    try:
        before = [tuple(r) for r in c.execute("SELECT id, word_id, status, spec_json, model, prompt_version, reason, created_at FROM word_dances ORDER BY id")]
        with pytest.raises(sqlite3.OperationalError):
            c.execute("SELECT corrected FROM word_dances").fetchall()

        result = db.run_migrations(c)  # the same call as `wd migrate` / the service startup

        assert (17, "word_dances_corrected") in result.applied and db.current_version(c) >= 17
        assert not c.in_transaction and c.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert [r["name"] for r in c.execute("PRAGMA table_info(word_dances)")][-1] == "corrected"
        assert [tuple(r) for r in c.execute("SELECT id, word_id, status, spec_json, model, prompt_version, reason, created_at FROM word_dances ORDER BY id")] == before
        assert [r[0] for r in c.execute("SELECT corrected FROM word_dances")] == [None] * 9  # the file fills nothing
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            c.execute("UPDATE word_dances SET corrected = 2 WHERE id = 1")
        # the old INSERT shape (no column named) still works and leaves NULL — what a rolled-back binary would write
        c.execute("INSERT INTO word_dances(word_id, status, spec_json) VALUES (3, 'superseded', '{}')")
        assert c.execute("SELECT corrected FROM word_dances WHERE word_id = 3 AND status = 'superseded'").fetchone()[0] is None
        c.execute("DELETE FROM word_dances WHERE word_id = 3 AND status = 'superseded'")
        # a NULL row serves its stored chunks until the backfill has run (the conservative reading)
        worker = dict(c.execute("SELECT * FROM words WHERE id = 1").fetchone())
        assert dance.active_record(c, worker) == (dance.active_spec(c, worker), None) and dance.spec_for_word(c, worker)["letters"] == ["wor", "ker"]

        # the startup backfill: stored chunks / stress vs the ordinary rules, the stress as the model was given it
        assert dance.backfill_corrected(c) == 9 and dance.backfill_corrected(c) == 0
        assert [tuple(r) for r in c.execute("SELECT id, corrected FROM word_dances ORDER BY id")] == [(1, 0), (2, 0), (3, 1), (4, 0), (5, 1), (6, 1), (7, 1), (8, 0), (9, 1)]

        # what the card gets afterwards
        worker = dict(c.execute("SELECT * FROM words WHERE id = 1").fetchone())
        assert dance.active_record(c, worker) == (dance.active_spec(c, worker), 0)
        assert dance.spec_for_word(c, worker)["letters"] == ["wor", "ker"] and dance.spec_for_word(c, worker)["source"] == "claude"  # no `work` in this bank yet
        c.execute("INSERT INTO words(id, lemma, display, source, phonetic, translation, pos, is_valid_english) VALUES (9, 'work', 'work', 'seed', 'wɜːk', 'n. 工作', 'n:38/v:62', 1)")
        c.execute("UPDATE words SET definition = 'a person who works', pos = 'n:100' WHERE id = 1")
        worker = dict(c.execute("SELECT * FROM words WHERE id = 1").fetchone())
        assert dance.spec_for_word(c, worker)["letters"] == ["work", "er"] and dance.spec_for_word(c, worker)["source"] == "claude"
        for word_id, letters, stress in ((2, ["teach", "er"], 0), (5, ["happ", "y"], 0), (6, ["a", "ban", "don"], 0)):
            w = dict(c.execute("SELECT * FROM words WHERE id = ?", (word_id,)).fetchone())
            served = dance.spec_for_word(c, w)
            assert served["letters"] == letters and served["stress"] == stress and served["source"] == "claude"
        rhythm = dict(c.execute("SELECT * FROM words WHERE id = 7").fetchone())
        assert dance.spec_for_word(c, rhythm)["letters"] == ["rhythm"] and dance.spec_for_word(c, rhythm)["stress"] is None  # confirmed → the rule spec, stress null per the contract
        ok = dict(c.execute("SELECT * FROM words WHERE id = 4").fetchone())
        assert dance.spec_for_word(c, ok)["letters"] == ["O", "K"]  # no rule spec: the stored one as it is
        assert c.execute("PRAGMA foreign_key_check").fetchall() == [] and c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.run_migrations(c).applied == []  # idempotent
    finally:
        c.close()


def test_0017_is_one_additive_statement_without_pragma_or_commit():
    text = (db.MIGRATIONS_DIR / "0017_word_dances_corrected.sql").read_text(encoding="utf-8")
    statements = [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("--")]
    assert statements == ["ALTER TABLE word_dances ADD COLUMN corrected INTEGER CHECK (corrected IN (0,1));"]
