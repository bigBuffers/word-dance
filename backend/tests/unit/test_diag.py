"""``wd check db`` stage-model invariants (PLAN §6 S6; stage-model SYNTHESIS §3.9 D-13 / D-22).

From schema 0011 on ``diag.check_db`` appends four ``invariant <name>: ok | N violation(s)`` lines — ``stage_min_consistent``,
``xs_subset_zk``, ``stages_json_known``, ``seed_version_matches_file`` — and any violation flips the check to FAIL (exit 1
through ``wd check db``). Each test here breaks exactly one rule on the migrated mini-seed database and reads the count
back; the last ones pin the edge cases the operators rely on: no invariant lines before 0011, a failing query (an SQLite
build without ``json_each``) is reported but neither raised nor counted, a missing seed file is skipped, an unreadable one
(truncated, or a corrupt deflate body — ``zlib.error`` is no ``OSError``) is a violation rather than a traceback, and the
rendered SQL is the literal of PLAN §6 S6 (the enum lives in ``schemas.STAGE_ORDER`` only).
"""

from __future__ import annotations

import gzip
import shutil
import sqlite3
import zlib
from pathlib import Path

import pytest

from wd import cli, db, diag
from wd.config import Settings
from wd.schemas import STAGE_ORDER
from wd.seed import seed_digest

INVARIANT_NAMES = ("stage_min_consistent", "xs_subset_zk", "stages_json_known", "seed_version_matches_file")


def invariant_lines(result: diag.CheckResult) -> dict[str, str]:
    """``{name: rest of the line}`` for every ``invariant …`` line of a ``check_db`` result."""
    out: dict[str, str] = {}
    for line in result.lines:
        if line.startswith("invariant "):
            name, _, rest = line[len("invariant ") :].partition(": ")
            out[name] = rest
    return out


def has_json_each(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute("SELECT COUNT(*) FROM json_each('[\"xs\"]')").fetchone()
    except sqlite3.OperationalError:
        return False
    return True


# ------------------------------------------------------------------------------------------ the happy path
def test_check_db_reports_the_four_invariants_ok_after_a_seed_import(settings, seeded):
    """The mini seed (62 v2 records) satisfies every rule and ``kv.seed_version`` is the content digest of ``WD_SEED_PATH``."""
    result = diag.check_db(settings)
    assert result.ok, result.render()
    lines = invariant_lines(result)
    assert tuple(lines) == INVARIANT_NAMES  # all four, in the PLAN §6 S6 order, after the kv.* lines
    assert all(v == "ok" for v in lines.values()), lines
    kv_index = next(i for i, line in enumerate(result.lines) if line.startswith("kv.backup.last"))
    assert all(line.startswith("invariant ") for line in result.lines[kv_index + 1 :])


# ------------------------------------------------------------------------------------- one broken rule each
def test_check_db_counts_a_stage_min_that_disagrees_with_the_flags(settings, seeded):
    """PLAN §6 S6 acceptance: one hand-made inconsistent row → ``1 violation(s)`` and ``ok=False``."""
    lemma = seeded.execute("SELECT lemma FROM words WHERE stage_xs = 1 ORDER BY lemma LIMIT 1").fetchone()[0]
    seeded.execute("UPDATE words SET stage_min = 5 WHERE lemma = ?", (lemma,))  # flags say xs (1), the column says cet6 (5)
    result = diag.check_db(settings)
    assert not result.ok
    lines = invariant_lines(result)
    assert lines["stage_min_consistent"] == "1 violation(s)"
    assert lines["xs_subset_zk"] == "ok" and lines["seed_version_matches_file"] == "ok"
    # NULL stage_min on a flagged word, and a stage_min on a flagless word, are the same rule (IS NOT handles NULL both ways)
    seeded.execute("UPDATE words SET stage_min = NULL WHERE lemma = ?", (lemma,))
    flagless = seeded.execute("SELECT lemma FROM words WHERE stage_xs = 0 AND stage_zk = 0 AND stage_gk = 0 AND stage_cet4 = 0 AND stage_cet6 = 0 ORDER BY lemma LIMIT 1").fetchone()
    assert flagless is not None  # the mini seed carries a 课标外 record (bookshelf: stages [])
    seeded.execute("UPDATE words SET stage_min = 2 WHERE lemma = ?", (flagless[0],))
    assert invariant_lines(diag.check_db(settings))["stage_min_consistent"] == "2 violation(s)"


def test_check_db_counts_a_primary_word_missing_from_the_junior_list(settings, seeded):
    """xs ⊆ zk is checked; zk ⊄ gk is by design and not checked (D-22)."""
    lemma = seeded.execute("SELECT lemma FROM words WHERE stage_xs = 0 AND stage_zk = 0 AND stage_cet6 = 1 ORDER BY lemma LIMIT 1").fetchone()[0]
    # a 初中 word the senior lists dropped (the release note's 544 rows) is the designed state: four ok lines, no fifth rule
    seeded.execute("UPDATE words SET stage_zk = 1, stage_gk = 0, stage_min = 2 WHERE lemma = ?", (lemma,))
    result = diag.check_db(settings)
    assert result.ok, result.render()
    assert tuple(invariant_lines(result)) == INVARIANT_NAMES
    # the same word flagged xs but no longer zk: a consistent stage_min, yet xs without zk
    seeded.execute("UPDATE words SET stage_xs = 1, stage_zk = 0, stage_min = 1 WHERE lemma = ?", (lemma,))
    result = diag.check_db(settings)
    assert not result.ok
    lines = invariant_lines(result)
    assert lines["xs_subset_zk"] == "1 violation(s)"
    assert lines["stage_min_consistent"] == "ok"


def test_check_db_counts_unknown_stage_codes_in_user_settings(settings, seeded):
    if not has_json_each(seeded):
        pytest.skip("this SQLite build has no json_each (the check reports `query failed` there, see the next test)")
    seeded.execute("INSERT INTO users(id, username, password_hash) VALUES (7, 'stale', '$2b$12$x')")
    seeded.execute("INSERT INTO user_settings(user_id, next_push_at) VALUES (7, '2026-11-07T00:00:00Z')")
    assert invariant_lines(diag.check_db(settings))["stages_json_known"] == "ok"  # the DDL default '["xs","zk"]'
    seeded.execute("UPDATE user_settings SET stages_json = '[\"xs\",\"cet9\"]' WHERE user_id = 7")  # no CHECK on the codes
    result = diag.check_db(settings)
    assert not result.ok
    assert invariant_lines(result)["stages_json_known"] == "1 violation(s)"


def test_check_db_counts_a_seed_version_that_differs_from_the_file(settings, seeded):
    """Migration 0011 clears ``kv.seed_version``; until ``wd import-seed`` ran, the database does not hold the shipped seed."""
    db.kv_set(seeded, "seed_version", "deadbeef" * 8)
    result = diag.check_db(settings)
    assert not result.ok
    rest = invariant_lines(result)["seed_version_matches_file"]
    assert rest.startswith("1 violation(s)") and "deadbeefdead…" in rest and "wd import-seed" in rest
    db.kv_delete(seeded, "seed_version")  # the post-0011, pre-import state
    assert invariant_lines(diag.check_db(settings))["seed_version_matches_file"].startswith("1 violation(s) (kv.seed_version -")


def test_check_db_skips_the_seed_version_invariant_without_a_seed_file(settings, seeded, tmp_path: Path, test_env):
    """``main.seed_check`` skips a missing WD_SEED_PATH with a warning; the diagnostic says so instead of failing."""
    cfg = Settings.from_env({**test_env, "WD_SEED_PATH": str(tmp_path / "nowhere.jsonl.gz")})
    result = diag.check_db(cfg)
    assert result.ok
    assert invariant_lines(result)["seed_version_matches_file"].startswith("skipped (seed file missing: ")


def test_check_db_flags_an_unreadable_seed_file(settings, seeded, tmp_path: Path, test_env, fixtures_dir: Path):
    """A truncated gzip (the fixture ``seed_v2/bad.jsonl.gz``) would fail ``seed_check`` at every start → a violation, not a crash."""
    cfg = Settings.from_env({**test_env, "WD_SEED_PATH": str(fixtures_dir / "seed_v2" / "bad.jsonl.gz")})
    result = diag.check_db(cfg)
    assert not result.ok
    rest = invariant_lines(result)["seed_version_matches_file"]
    assert rest.startswith("1 violation(s) (cannot read bad.jsonl.gz")


def test_check_db_flags_a_seed_file_with_a_corrupt_gzip_body(settings, seeded, tmp_path: Path, test_env, monkeypatch):
    """A valid gzip header over a corrupt deflate stream raises ``zlib.error`` — neither an ``OSError`` nor an ``EOFError``.

    ``main.seed_check`` catches it with ``except Exception`` and the service starts; the diagnostic must judge that same
    file as a violation instead of dying with a traceback (which also aborted ``wd check all``) — impl review S6-M2.
    """
    corrupt = tmp_path / "corrupt.jsonl.gz"
    corrupt.write_bytes(gzip.compress(b'{"lemma": "apple"}\n')[:10] + b"\x07" + b"\x00" * 32)  # 10-byte header, then BFINAL=1 BTYPE=11 (reserved)
    with pytest.raises(zlib.error):  # the premise: the class the old `except (OSError, EOFError)` let through
        seed_digest(corrupt)
    cfg = Settings.from_env({**test_env, "WD_SEED_PATH": str(corrupt)})
    result = diag.check_db(cfg)
    assert not result.ok
    rest = invariant_lines(result)["seed_version_matches_file"]
    assert rest.startswith("1 violation(s) (cannot read corrupt.jsonl.gz") and "invalid block type" in rest
    monkeypatch.setenv("WD_SEED_PATH", str(corrupt))
    assert cli.main(["check", "db"]) == 1  # exit 1 like any violation, no traceback


# ------------------------------------------------------------------------------------------------ edge cases
def test_check_db_has_no_stage_invariants_before_schema_0011(settings, tmp_path: Path, monkeypatch):
    """A 0001-baseline database (four flags, indexes 1..4) is checked as before: no ``invariant`` line, ok."""
    baseline = tmp_path / "baseline"
    baseline.mkdir()
    shutil.copy(db.MIGRATIONS_DIR / "0001_init.sql", baseline / "0001_init.sql")
    monkeypatch.setattr(db, "MIGRATIONS_DIR", baseline)  # list_migration_files reads the module global at call time
    c = db.connect(settings.db_path)
    try:
        assert db.run_migrations(c).applied == [(1, "init")]
    finally:
        c.close()
    result = diag.check_db(settings)
    assert result.ok, result.render()
    assert invariant_lines(result) == {}
    assert any(line.startswith("schema version: 1 (") for line in result.lines)


def test_check_db_reports_a_failing_invariant_query_without_raising(settings, seeded, monkeypatch):
    """SQLite < 3.38 may lack ``json_each``: the line says ``query failed`` and the other invariants and the verdict stand."""
    monkeypatch.setattr(diag, "STAGE_INVARIANTS", (("stages_json_known", "SELECT COUNT(*) FROM user_settings us, json_each_missing(us.stages_json) j"), *diag.STAGE_INVARIANTS[:2]))
    result = diag.check_db(settings)
    assert result.ok  # unverifiable ≠ violated
    lines = invariant_lines(result)
    assert lines["stages_json_known"].startswith("query failed (no such table: json_each_missing")
    assert lines["stage_min_consistent"] == "ok" and lines["xs_subset_zk"] == "ok" and lines["seed_version_matches_file"] == "ok"


def test_stage_invariant_sql_is_the_plan_literal_rendered_from_the_enum():
    """The enum lives in ``schemas.STAGE_ORDER`` only; the rendered SQL must still read as PLAN §6 S6 wrote it."""
    assert STAGE_ORDER == ("xs", "zk", "gk", "cet4", "cet6")
    assert diag.STAGE_INVARIANTS_FROM_VERSION == 11
    assert dict(diag.STAGE_INVARIANTS) == {
        "stage_min_consistent": "SELECT COUNT(*) FROM words WHERE stage_min IS NOT (CASE WHEN stage_xs=1 THEN 1 WHEN stage_zk=1 THEN 2 WHEN stage_gk=1 THEN 3 WHEN stage_cet4=1 THEN 4 WHEN stage_cet6=1 THEN 5 END)",
        "xs_subset_zk": "SELECT COUNT(*) FROM words WHERE stage_xs = 1 AND stage_zk = 0",
        "stages_json_known": "SELECT COUNT(*) FROM user_settings us, json_each(us.stages_json) j WHERE j.value NOT IN ('xs','zk','gk','cet4','cet6')",
    }
    assert [name for name, _ in diag.STAGE_INVARIANTS] == list(INVARIANT_NAMES[:3])


# ---------------------------------------------------------------------------------------------------- the CLI
def test_wd_check_db_exit_code_follows_the_invariants(settings, seeded, capsys):
    """Runbook step 8 (PLAN §8): ``wd check db`` exits 0 with four ok lines and 1 as soon as one invariant is violated."""
    assert cli.main(["check", "db"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("[ok] db") and out.count("\n    invariant ") == 4
    seeded.execute("UPDATE words SET stage_min = 4 WHERE lemma = (SELECT lemma FROM words WHERE stage_xs = 1 ORDER BY lemma LIMIT 1)")
    assert cli.main(["check", "db"]) == 1
    out = capsys.readouterr().out
    assert out.startswith("[FAIL] db") and "invariant stage_min_consistent: 1 violation(s)" in out
