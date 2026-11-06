"""``wd check db`` stage-model invariants (PLAN §6 S6; stage-model SYNTHESIS §3.9 D-13 / D-22) and the learning-order
invariants (docs/analysis/2026-11-06-learn-order/DESIGN.md §2.7, §4.1 item 24).

From schema 0011 on ``diag.check_db`` appends four ``invariant <name>: ok | N violation(s)`` lines — ``stage_min_consistent``,
``xs_subset_zk``, ``stages_json_known``, ``seed_version_matches_file`` — and from schema 0014 four more — ``learn_rank_present``,
``learn_order_current``, ``learn_rank_matches_policy``, ``calendar_words_in_xs`` (rendered by ``learn_order.check_lines``) — and
any violation flips the check to FAIL (exit 1 through ``wd check db``). Each test here breaks exactly one rule on the migrated
mini-seed database and reads the count back; the last ones pin the edge cases the operators rely on: no invariant lines before
0011 and none of the learning-order lines before 0014, a failing query (an SQLite build without ``json_each``) is reported but
neither raised nor counted, a missing seed file is skipped, an unreadable one (truncated, or a corrupt deflate body —
``zlib.error`` is no ``OSError``) is a violation rather than a traceback, and the rendered SQL is the literal of PLAN §6 S6 (the
enum lives in ``schemas.STAGE_ORDER`` only). The kv block carries ``kv.learn_order.version`` and the rendered
``kv.learn_order.stats`` line BEFORE ``kv.backup.last``, so every line after it is an invariant.
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
from wd.services import learn_order

STAGE_INVARIANT_NAMES = ("stage_min_consistent", "xs_subset_zk", "stages_json_known", "seed_version_matches_file")
LEARN_ORDER_INVARIANT_NAMES = ("learn_rank_present", "learn_order_current", "learn_rank_matches_policy", "calendar_words_in_xs")
INVARIANT_NAMES = (*STAGE_INVARIANT_NAMES, *LEARN_ORDER_INVARIANT_NAMES)  # the `diag` order — ops.md / TASKS.md list them so (test_docs_contract)


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
def test_check_db_reports_the_eight_invariants_ok_after_a_seed_import(settings, seeded):
    """The mini seed (62 v2 records) satisfies every rule, ``kv.seed_version`` is the content digest of ``WD_SEED_PATH`` and the
    import ranked every row (``learn_order.recompute`` inside the import transaction)."""
    result = diag.check_db(settings)
    assert result.ok, result.render()
    lines = invariant_lines(result)
    assert tuple(lines) == INVARIANT_NAMES and len(lines) == 8  # four stage + four learning-order lines, in the diag order, after the kv.* lines
    assert all(v == "ok" for v in lines.values()), lines
    kv_index = next(i for i, line in enumerate(result.lines) if line.startswith("kv.backup.last"))
    assert all(line.startswith("invariant ") for line in result.lines[kv_index + 1 :])
    # the learning-order kv lines sit before kv.backup.last (so the rule above holds) and carry the stored stamps
    assert f"kv.learn_order.version: {learn_order.LEARN_ORDER_VERSION}" in result.lines[:kv_index]
    stats_line = next(line for line in result.lines[:kv_index] if line.startswith("kv.learn_order.stats: "))
    assert stats_line == learn_order.stats_line(seeded) and stats_line.startswith("kv.learn_order.stats: xs n=") and "· dealt drift 0 · 课标外 drift 0 · label-pos 0" in stats_line
    assert result.lines.index(stats_line) == kv_index - 1


def test_learn_order_invariants_start_at_schema_14_and_are_exported():
    assert diag.LEARN_ORDER_INVARIANTS_FROM_VERSION == learn_order.LEARN_ORDER_FROM_VERSION == 14
    assert "LEARN_ORDER_INVARIANTS_FROM_VERSION" in diag.__all__ and "STAGE_INVARIANTS_FROM_VERSION" in diag.__all__
    assert [name for name, _ in diag.STAGE_INVARIANTS] == list(INVARIANT_NAMES[:3])  # STAGE_INVARIANTS stays the PLAN literal


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
    learn_order.recompute(seeded)  # the stage move re-groups the word: keep the stored keys equal to the policy (not this test's rule)
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


# ------------------------------------------------------------------------- one broken learning-order rule each (§2.7)
def test_check_db_counts_a_stage_word_without_learn_rank(settings, seeded):
    """NULL = "not computed yet": a stage word without a key is the first learning-order line (the next start fills it); the
    stored column then also differs from the policy, so the matches-policy line counts the same row."""
    seeded.execute("UPDATE words SET learn_rank = NULL WHERE lemma = 'apple'")
    result = diag.check_db(settings)
    assert not result.ok
    lines = invariant_lines(result)
    assert lines["learn_rank_present"] == "1 violation(s) (stage words without learn_rank — the next `wd serve` start or `wd learn-order` fills them)"
    assert lines["learn_rank_matches_policy"] == "1 violation(s) (stored learn_rank of stage words differs from learn_order.rank_rows(); run `wd learn-order`)"
    assert lines["learn_order_current"] == "ok" and lines["calendar_words_in_xs"] == "ok" and all(lines[n] == "ok" for n in STAGE_INVARIANT_NAMES)
    seeded.execute("UPDATE words SET learn_rank = NULL WHERE lemma = 'bookshelf'")  # a 课标外 word is not a stage word
    assert invariant_lines(diag.check_db(settings))["learn_rank_present"].startswith("1 violation(s)")
    learn_order.recompute(seeded)  # the repair every path runs
    assert diag.check_db(settings).ok


def test_check_db_flags_a_stale_policy_version_seed_stamp_or_no_compute(settings, seeded):
    db.kv_set(seeded, learn_order.KV_VERSION, "lo-0")
    result = diag.check_db(settings)
    assert not result.ok
    assert invariant_lines(result)["learn_order_current"] == f"1 violation(s) (kv.learn_order.version lo-0 ≠ code {learn_order.LEARN_ORDER_VERSION}; run `wd learn-order`)"
    db.kv_set(seeded, learn_order.KV_VERSION, learn_order.LEARN_ORDER_VERSION)
    db.kv_set(seeded, "seed_version", "deadbeef" * 8)  # an older server imported another seed: the stamp no longer matches
    rest = invariant_lines(diag.check_db(settings))["learn_order_current"]
    stamp = seed_digest(Path(settings.seed_path))[:12]
    assert rest == f"1 violation(s) (computed for seed {stamp}… ≠ kv.seed_version deadbeefdead…; run `wd learn-order`)"
    db.kv_set(seeded, "seed_version", seed_digest(Path(settings.seed_path)))
    db.kv_delete(seeded, learn_order.KV_VERSION)
    assert invariant_lines(diag.check_db(settings))["learn_order_current"] == "1 violation(s) (never computed; run `wd learn-order`)"
    learn_order.recompute(seeded)
    assert diag.check_db(settings).ok


def test_check_db_counts_a_hand_edited_stage_key_but_only_reports_课标外_drift(settings, seeded):
    seeded.execute("UPDATE words SET learn_rank = learn_rank + 1 WHERE lemma = 'apple'")
    result = diag.check_db(settings)
    assert not result.ok
    lines = invariant_lines(result)
    assert lines["learn_rank_matches_policy"] == "1 violation(s) (stored learn_rank of stage words differs from learn_order.rank_rows(); run `wd learn-order`)"
    assert lines["learn_rank_present"] == "ok" and lines["learn_order_current"] == "ok"
    seeded.execute("UPDATE words SET learn_rank = learn_rank - 1 WHERE lemma = 'apple'")
    seeded.execute("UPDATE words SET learn_rank = 7 WHERE lemma = 'bookshelf'")  # 课标外 drift (A8): informational, in the stats line after the next compare
    result = diag.check_db(settings)
    assert result.ok, result.render()
    learn_order.recompute(seeded)
    assert any(line.endswith("课标外 drift 1 · label-pos 0") for line in diag.check_db(settings).lines)


def test_check_db_counts_a_calendar_word_outside_xs(settings, seeded):
    """The mini seed carries no month / weekday; an inserted one must be a 小学 word (stage_xs = 1, stage_min = 1)."""
    seeded.execute("INSERT INTO words(lemma, display, kind, source, stage_zk, stage_min) VALUES ('january', 'January', 'proper_noun', 'seed', 1, 2)")
    learn_order.recompute(seeded)  # rank it, so only the calendar rule is broken
    result = diag.check_db(settings)
    assert not result.ok
    lines = invariant_lines(result)
    assert lines["calendar_words_in_xs"] == "1 violation(s) (month/weekday rows without stage_xs = 1 / stage_min = 1)"
    assert lines["learn_rank_present"] == "ok" and lines["learn_rank_matches_policy"] == "ok" and lines["stage_min_consistent"] == "ok"
    seeded.execute("UPDATE words SET stage_xs = 1, stage_min = 1 WHERE lemma = 'january'")
    learn_order.recompute(seeded)
    result = diag.check_db(settings)
    assert result.ok, result.render()
    assert learn_order.CALENDAR_INVARIANT_SQL.count("'") == 2 * 19  # rendered from MONTHS / WEEKDAYS


def test_check_db_reports_a_failing_learn_order_query_without_raising(settings, seeded, monkeypatch):
    monkeypatch.setattr(learn_order, "CALENDAR_INVARIANT_SQL", "SELECT COUNT(*) FROM words_gone")
    result = diag.check_db(settings)
    assert result.ok  # unverifiable ≠ violated
    assert invariant_lines(result)["calendar_words_in_xs"].startswith("query failed (no such table: words_gone")


def test_check_db_reports_a_raising_policy_without_a_traceback(settings, seeded, monkeypatch):
    """A bug inside `rank_rows` must not take `wd check db` down: the policy line says `query failed (RuntimeError: …)` and is not
    counted, the seven other lines stand (learn_order.check_lines catches every exception, not only sqlite3.OperationalError)."""

    def boom(rows, forms):
        raise RuntimeError("policy exploded")

    monkeypatch.setattr(learn_order, "rank_rows", boom)
    result = diag.check_db(settings)
    lines = invariant_lines(result)
    assert result.ok and tuple(lines) == INVARIANT_NAMES
    assert lines["learn_rank_matches_policy"] == "query failed (RuntimeError: policy exploded)"
    assert all(lines[name] == "ok" for name in INVARIANT_NAMES if name != "learn_rank_matches_policy")


def test_check_db_stays_ok_when_a_runtime_word_redeals_stage_phrases(settings, seeded):
    """A learner's lookup creates `cream`; R3 now resolves `ice cream`'s token and the 小学 dealt rows swap hosts (F-1). That is
    `Drift.dealt`, informational — the gate stays `ok`, the next recompute settles the rows and reports them as `dealt drift`."""
    cream = {"lemma": "cream", "display": "cream", "kind": "word", "pos": "n:100", "frq": 20000, "source": "ecdict"}
    seeded.execute("INSERT INTO words(lemma, display, kind, pos, frq, source, learn_rank) VALUES (:lemma, :display, :kind, :pos, :frq, :source, :learn_rank)", {**cream, "learn_rank": learn_order.best_effort_rank(cream)})
    assert learn_order.drift(seeded) == learn_order.Drift(policy=0, dealt=2, none=0)
    result = diag.check_db(settings)
    assert result.ok and invariant_lines(result)["learn_rank_matches_policy"] == "ok"
    learn_order.recompute(seeded)
    result = diag.check_db(settings)
    assert result.ok and any("· dealt drift 2 · 课标外 drift 0 ·" in line for line in result.lines)


# ------------------------------------------------------------------------------------------------ edge cases
def test_check_db_has_no_learn_order_invariants_before_schema_0014(settings, tmp_path: Path, monkeypatch):
    """A schema-13 database (the live file before this release) prints the four stage lines and none of the learning-order
    lines; the kv block still shows `kv.learn_order.version: -`."""
    upto13 = tmp_path / "upto13"
    upto13.mkdir()
    for mf in db.list_migration_files():
        if mf.version <= 13:
            shutil.copy(mf.path, upto13 / mf.path.name)
    monkeypatch.setattr(db, "MIGRATIONS_DIR", upto13)
    c = db.connect(settings.db_path)
    try:
        assert db.run_migrations(c).applied[-1] == (13, "word_forms_alias")
        db.kv_set(c, "seed_version", seed_digest(Path(settings.seed_path)))  # as if the seed were imported by the previous version
    finally:
        c.close()
    result = diag.check_db(settings)
    assert result.ok, result.render()
    lines = invariant_lines(result)
    assert tuple(lines) == STAGE_INVARIANT_NAMES and all(v == "ok" for v in lines.values())
    assert "kv.learn_order.version: -" in result.lines and "kv.learn_order.stats: -" in result.lines
    assert any(line.startswith("schema version: 13 (") for line in result.lines)


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
    """Runbook step 8 (PLAN §8; learn-order release §4.3): ``wd check db`` exits 0 with eight ok lines and 1 as soon as one
    invariant is violated."""
    assert cli.main(["check", "db"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("[ok] db") and out.count("\n    invariant ") == 8 and out.count(": ok") >= 8
    assert "\n    kv.learn_order.version: lo-1\n    kv.learn_order.stats: " in out and out.index("kv.learn_order.stats: ") < out.index("kv.backup.last")
    seeded.execute("UPDATE words SET stage_min = 4 WHERE lemma = (SELECT lemma FROM words WHERE stage_xs = 1 ORDER BY lemma LIMIT 1)")
    assert cli.main(["check", "db"]) == 1
    out = capsys.readouterr().out
    assert out.startswith("[FAIL] db") and "invariant stage_min_consistent: 1 violation(s)" in out
    seeded.execute("UPDATE words SET stage_min = 1 WHERE lemma = (SELECT lemma FROM words WHERE stage_xs = 1 ORDER BY lemma LIMIT 1)")
    seeded.execute("UPDATE words SET learn_rank = NULL WHERE stage_min = 1")
    assert cli.main(["check", "db"]) == 1
    out = capsys.readouterr().out
    assert "invariant learn_rank_present: " in out and "violation(s) (stage words without learn_rank" in out
