#!/usr/bin/env python3
"""Rehearse the pending migrations on a PRIVATE COPY of a word-Dance database and verify the result.

    .venv/bin/python -I scripts/rehearse_migration.py <copy-of-word-dance.db> [--keep-empty-db]

The runbook step this implements is PLAN §2.5 (docs/analysis/2026-11-05-stages-regions-images/design/PLAN.md) step 3
and §6 S6 — the operator copies the live database to a private directory (never ``/Users/sqin/word-dance-data`` or the
systemd data directory itself), runs this script on the copy, and only when it exits 0 repeats ``wd migrate`` for real
(docs/releases/2026-11-k12-stages.md, DEPLOY §5/§10, ops.md §4). It applies every migration file the installed ``wd``
package ships and the copy has not recorded yet through ``wd.db.run_migrations`` — the same runner ``wd migrate`` and the
``wd serve`` lifespan use — **never through the sqlite3 CLI**, whose ``legacy_alter_table=1`` default would hide the
``RENAME`` error a missing ``DROP VIEW`` causes under the service's settings (PLAN §2.2). Then it prints one line per
check of PLAN §2.2's rehearsal list and exits with the number of failed checks (0 = the copy migrated exactly as
designed):

* the copy opens as a word-Dance database (an empty or foreign file fails this first check and exits 1 — no traceback);
* the pending list is contiguous and exactly what ``wd migrate --dry-run`` would list; every pending file applied;
* only ``schema_migrations`` / ``kv`` / ``system_events`` changed row counts; ``integrity_check`` ok, ``foreign_key_check``
  empty, the connection is out of the transaction with ``foreign_keys`` back on;
* 0011 (when it ran here): ``stage_min`` and ``current_stage`` moved exactly +1 per row (NULL stays), ``stage_xs`` is 0
  everywhere while the other flag sums are unchanged, ``difficulty + 1 = stage_min`` holds for exactly the rows where
  ``difficulty = stage_min`` held before, ``v_bank`` has the same rows, ``kv.seed_version`` is gone, the last
  ``system_events`` row is the migration trace, the DDL carries the 1..5 CHECKs / the K-12 defaults / the stage column
  order, the CHECK and FK probes are rejected, a new settings row defaults to ``('["xs","zk"]', 1)``;
* 0012 (whenever ``schema_migrations`` holds 12): ``word_images`` has the four new columns, ``text_free`` defaults to 0 with
  its CHECK, existing rows keep ``text_free = 0`` / ``prompt_version NULL`` when the file ran here;
* 0013 (whenever ``schema_migrations`` holds 13): ``word_forms`` admits ``'alias'`` and still rejects an unknown kind, keeps
  every row, its index and ``WITHOUT ROWID``;
* 0014 (whenever ``schema_migrations`` holds 14; docs/analysis/2026-11-06-learn-order/DESIGN.md §2.9): ``words.learn_rank`` is a
  nullable INTEGER without default or index, ``words`` / ``v_bank`` keep their rows, the column is all NULL right after the file;
  then the learning order is RECOMPUTED ON THE COPY (``learn_order.recompute``): 0 stage words unranked, ``kv.learn_order.version``
  is the code's policy, ``stale_count`` 0, a second recompute changes 0 rows, ``MAX(updated_at)`` is unchanged, every stage's
  first 30 words hold 0 FACTS-closed words (the §1.6 acceptance count, computed here); ``[info]`` prints the 小学 and 初中新增
  first 15 and a per-stage summary — the operator sees the order before touching production; ``UPDATE words SET learn_rank = NULL``
  is accepted (NULL is a legal state);
* 0018 (whenever ``schema_migrations`` holds 18; docs/AUTH_SIGNUP_DESIGN.md §5.1): ``users`` carries the eight account columns in
  file order, ``sessions.actor_user_id`` is last, ``identities`` / ``login_codes`` exist with their indexes (``ux_identities_live``,
  ``ux_identities_user_provider`` …), ``email_codes`` stays; when the file ran here ``password_set_at = created_at`` on every row,
  ``account_kind`` is ``learner`` everywhere and the two new tables are empty; the CHECK / FK / partial-unique probes are rejected;
* the ``wd check db`` stage invariants hold on the migrated copy and, from 0014, the four learning-order lines
  (``learn_order.check_lines`` — the same code ``wd check db`` runs); a second run applies nothing; an empty database
  migrates from 0001 to the same version with 28 tables and the ``v_bank`` view;
* informational: elapsed time, page / freelist counts and file size (PLAN §8 step 9 runs ``ANALYZE`` + ``VACUUM`` afterwards).

The script is self-contained apart from the ``wd`` package (``.venv/bin/python -I`` keeps the script directory off
``sys.path``; ``wd`` is the editable install of ``backend/``), needs no ``WD_*`` environment and never touches the
network or the live data directory. It is portable: the same command runs on the Lighthouse / Ubuntu box before
``deploy/install.sh`` (SQLite ≥ 3.26 is required for the ``RENAME`` semantics the rebuilds rely on; ``json_each`` for
the ``stages_json_known`` invariant is built in from 3.38 — on an older build that one invariant is reported as
``query failed`` and does not count, exactly as in ``wd check db``).
"""

from __future__ import annotations

import argparse
import hashlib
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Callable

from wd import db
from wd.diag import LEARN_ORDER_INVARIANTS_FROM_VERSION, STAGE_INVARIANTS, STAGE_INVARIANTS_FROM_VERSION
from wd.schemas import STAGE_ORDER
from wd.services import learn_order

EXPECTED_TABLE_COUNT = 28  # TASKS P0 acceptance: 25 tables + the v_bank view, unchanged by 0008–0015 (rebuilds in place, 0014 / 0015 add columns); 0016 adds word_dances → 26; 0018 adds identities + login_codes → 28
USERS_0018_COLUMNS = ("password_set_at", "account_kind", "guardian_user_id", "age_band", "age_declared_at", "age_declared_ip", "guardian_consent_at", "guardian_pin_hash")  # 0018, file order
INDEXES_0018 = frozenset({"ux_identities_live", "ux_identities_user_provider", "ix_identities_user", "ix_login_codes_live", "ix_login_codes_user", "ix_login_codes_expires", "ix_sessions_actor"})
BOOKKEEPING_TABLES = frozenset({"schema_migrations", "kv", "system_events"})  # the only tables a migration may grow/shrink
STAGE_COLUMNS = tuple(f"stage_{code}" for code in STAGE_ORDER)  # the 0011 column order (seed.SEED_COLUMNS order)
WORD_IMAGES_META_COLUMNS = ("prompt_version", "model", "text_free", "eval_json")  # 0012
WORD_FORMS_KINDS_0013 = ("p", "d", "i", "3", "s", "r", "t", "alt", "alias")  # the 0013 CHECK list


class Report:
    """Collects ``[ok]`` / ``[FAIL]`` lines; the exit status is the number of failures."""

    def __init__(self) -> None:
        self.failed = 0
        self.passed = 0

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        tag = "ok" if ok else "FAIL"
        if ok:
            self.passed += 1
        else:
            self.failed += 1
        print(f"[{tag}] {name}" + (f": {detail}" if detail else ""))
        return ok

    @staticmethod
    def info(name: str, detail: str) -> None:
        print(f"[info] {name}: {detail}")

    @staticmethod
    def skip(name: str, why: str) -> None:
        print(f"[skip] {name}: {why}")


# ------------------------------------------------------------------------------------------- helpers
def row_counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {t: int(conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]) for t in db.table_names(conn)}


def columns(conn: sqlite3.Connection, table: str) -> list[sqlite3.Row]:
    return conn.execute(f"PRAGMA table_info({table})").fetchall()


def table_sql(conn: sqlite3.Connection, table: str) -> str:
    row = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone()
    return str(row[0]) if row else ""


def scalar(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> Any:
    return conn.execute(sql, params).fetchone()[0]


def rejected(conn: sqlite3.Connection, stmt: str, params: tuple = ()) -> tuple[bool, str]:
    """Run ``stmt`` inside BEGIN … ROLLBACK and tell whether SQLite rejected it (CHECK / FK), with the error text."""
    conn.execute("BEGIN")
    try:
        conn.execute(stmt, params)
    except sqlite3.IntegrityError as e:
        return True, str(e)
    except sqlite3.OperationalError as e:  # a column this schema does not have etc. — a different kind of failure
        return False, f"operational error: {e}"
    else:
        return False, "accepted"
    finally:
        conn.execute("ROLLBACK")


def accepted(conn: sqlite3.Connection, stmt: str, params: tuple = ()) -> tuple[bool, str]:
    ok, detail = rejected(conn, stmt, params)
    return (not ok), detail


def has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return any(r["name"] == column for r in columns(conn, table))


def table_digest(conn: sqlite3.Connection, table: str) -> str:
    """A digest of every row (ordered by id) — equal before and after a rebuild that kept the data."""
    h = hashlib.sha256()
    for row in conn.execute(f'SELECT * FROM "{table}" ORDER BY id'):
        h.update(repr(tuple(row)).encode("utf-8"))
    return h.hexdigest()


def index_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(r[0]) for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = ? AND name NOT LIKE 'sqlite_autoindex%'", (table,))}


# ------------------------------------------------------------------------------------------ snapshots
def snapshot(conn: sqlite3.Connection) -> dict[str, Any]:
    """Everything the post-migration checks compare against, read before ``run_migrations``."""
    version = db.current_version(conn)
    snap: dict[str, Any] = {
        "version": version,
        "counts": row_counts(conn),
        "views": db.view_names(conn),
        "kv_seed_version": db.kv_get(conn, "seed_version"),
    }
    if "words" in snap["counts"]:
        snap["stage_min"] = {int(r[0]): r[1] for r in conn.execute("SELECT id, stage_min FROM words")}
        old_flags = [c for c in ("stage_zk", "stage_gk", "stage_cet4", "stage_cet6") if has_column(conn, "words", c)]
        snap["flag_sums"] = {c: int(scalar(conn, f"SELECT COALESCE(SUM({c}), 0) FROM words")) for c in old_flags}
        # difficulty is Claude's unchanged scale: before 0011 it equals stage_min where it matches, afterwards stage_min − 1
        offset = "" if version < STAGE_INVARIANTS_FROM_VERSION else " + 1"
        snap["difficulty_relation"] = tuple(
            int(x or 0)
            for x in conn.execute(
                f"SELECT SUM(difficulty{offset} = stage_min), SUM(difficulty{offset} < stage_min), SUM(difficulty{offset} > stage_min), COUNT(*) "
                "FROM words WHERE difficulty IS NOT NULL AND stage_min IS NOT NULL"
            ).fetchone()
        )
    if "user_settings" in snap["counts"]:
        snap["current_stage"] = {int(r[0]): int(r[1]) for r in conn.execute("SELECT user_id, current_stage FROM user_settings")}
        snap["stages_json"] = {int(r[0]): str(r[1]) for r in conn.execute("SELECT user_id, stages_json FROM user_settings")}
    if "v_bank" in snap["views"]:
        snap["v_bank"] = int(scalar(conn, "SELECT COUNT(*) FROM v_bank"))
    if "word_forms" in snap["counts"]:
        snap["word_forms_kinds"] = {str(r[0]): int(r[1]) for r in conn.execute("SELECT kind, COUNT(*) FROM word_forms GROUP BY kind")}
    for table in ("jobs", "ai_calls"):  # 0016 rebuilds both: columns, rows and indexes must come out identical
        if table in snap["counts"]:
            snap[f"{table}_cols"] = [c["name"] for c in columns(conn, table)]
            snap[f"{table}_digest"] = table_digest(conn, table)
            snap[f"{table}_indexes"] = index_names(conn, table)
    if "words" in snap["counts"]:
        snap["has_learn_rank"] = has_column(conn, "words", "learn_rank")
        if snap["has_learn_rank"]:
            snap["learn_rank_nonnull"] = int(scalar(conn, "SELECT COUNT(*) FROM words WHERE learn_rank IS NOT NULL"))
    return snap


# --------------------------------------------------------------------------------------------- checks
def check_bookkeeping(rep: Report, conn: sqlite3.Connection, before: dict[str, Any], applied: list[tuple[int, str]]) -> None:
    after = row_counts(conn)
    deltas = {t: (before["counts"].get(t), after.get(t)) for t in set(before["counts"]) | set(after) if before["counts"].get(t) != after.get(t)}
    rep.info("row deltas", str(dict(sorted(deltas.items()))) if deltas else "none")
    if applied:
        created = set(after) - set(before["counts"])  # a table the files create (0016: word_dances) starts empty and is no row change
        rep.check("only bookkeeping tables changed row counts", set(deltas) <= BOOKKEEPING_TABLES | created, ", ".join(sorted(set(deltas) - BOOKKEEPING_TABLES - created)) or "schema_migrations / kv / system_events only" + (f" (+ new tables {sorted(created)})" if created else ""))
        rep.check("schema_migrations grew by the applied files", after.get("schema_migrations", 0) - before["counts"].get("schema_migrations", 0) == len(applied))
    else:
        rep.check("nothing pending: no row count changed", not deltas, str(deltas))
    rep.check("integrity_check", str(scalar(conn, "PRAGMA integrity_check")) == "ok")
    fk = conn.execute("PRAGMA foreign_key_check").fetchall()
    rep.check("foreign_key_check", not fk, f"{len(fk)} violation(s)" if fk else "empty")
    rep.check("connection out of the transaction, foreign_keys back on", not conn.in_transaction and int(scalar(conn, "PRAGMA foreign_keys")) == 1)
    rep.check(f"{EXPECTED_TABLE_COUNT} tables + v_bank", len(db.table_names(conn)) == EXPECTED_TABLE_COUNT and db.view_names(conn) == ["v_bank"], f"{len(db.table_names(conn))} tables, views {db.view_names(conn)}")


def check_0011(rep: Report, conn: sqlite3.Connection, before: dict[str, Any], ran_here: bool) -> None:
    """The stage renumbering (PLAN §2.2). Row-level +1 comparisons only when 0011 ran in this process."""
    if ran_here:
        after_min = {int(r[0]): r[1] for r in conn.execute("SELECT id, stage_min FROM words")}
        expected = {wid: (None if sm is None else sm + 1) for wid, sm in before["stage_min"].items()}
        bad = [wid for wid in expected if after_min.get(wid, "missing") != expected[wid]]
        old_dist = dict(conn.execute("SELECT stage_min, COUNT(*) FROM words GROUP BY 1").fetchall())
        rep.check("stage_min moved exactly +1 per row (NULL stays)", not bad and set(after_min) == set(expected), f"{len(after_min)} rows, {len(bad)} mismatch(es); distribution now {dict(sorted(old_dist.items(), key=lambda kv: (kv[0] is None, kv[0])))}")
        flags_now = {c: int(scalar(conn, f"SELECT COALESCE(SUM({c}), 0) FROM words")) for c in STAGE_COLUMNS}
        rep.check("stage_xs is 0 everywhere until the seed re-import", flags_now["stage_xs"] == 0, f"sum {flags_now['stage_xs']}")
        rep.check("the four old flag sums are unchanged", all(flags_now[c] == before["flag_sums"].get(c) for c in before["flag_sums"]), f"{flags_now}")
        rel_after = tuple(
            int(x or 0)
            for x in conn.execute(
                "SELECT SUM(difficulty + 1 = stage_min), SUM(difficulty + 1 < stage_min), SUM(difficulty + 1 > stage_min), COUNT(*) FROM words WHERE difficulty IS NOT NULL AND stage_min IS NOT NULL"
            ).fetchone()
        )
        rep.check("difficulty + 1 = stage_min for exactly the rows where difficulty = stage_min held", rel_after == before["difficulty_relation"], f"(=, <, >, n) before {before['difficulty_relation']} → after {rel_after}")
        cur_after = {int(r[0]): int(r[1]) for r in conn.execute("SELECT user_id, current_stage FROM user_settings")}
        rep.check("current_stage moved exactly +1 per user", cur_after == {u: v + 1 for u, v in before["current_stage"].items()}, f"{before['current_stage']} → {cur_after}")
        sj_after = {int(r[0]): str(r[1]) for r in conn.execute("SELECT user_id, stages_json FROM user_settings")}
        rep.check("stages_json copied as is (nobody enrolled in xs automatically)", sj_after == before["stages_json"], str(sj_after))
        rep.check("v_bank re-created over the new words table with the same rows", int(scalar(conn, "SELECT COUNT(*) FROM v_bank")) == before.get("v_bank", -1), f"{before.get('v_bank')} rows")
        rep.check("kv.seed_version cleared (forces the seed re-import)", db.kv_get(conn, "seed_version") is None, f"was {before['kv_seed_version']!r}")
        last = conn.execute("SELECT kind, detail_json FROM system_events ORDER BY id DESC LIMIT 1").fetchone()
        rep.check("last system_events row is the 0011 migration trace", last is not None and last[0] == "migration" and '"version": 11' in str(last[1]), str(tuple(last)) if last else "no events")
    else:
        rep.skip("0011 row-level +1 comparisons", "0011 was already recorded before this run")

    ddl_w, ddl_s = table_sql(conn, "words"), table_sql(conn, "user_settings")
    rep.check("words DDL: stage_min CHECK 1..5, stage_xs column, difficulty scale unchanged", "CHECK (stage_min BETWEEN 1 AND 5)" in ddl_w and "stage_xs" in ddl_w and "CHECK (difficulty BETWEEN 1 AND 5)" in ddl_w)
    rep.check("user_settings DDL: current_stage CHECK 1..5", "CHECK (current_stage BETWEEN 1 AND 5)" in ddl_s)
    stage_cols = [r["name"] for r in columns(conn, "words") if r["name"].startswith("stage_")]
    rep.check("words stage column order", stage_cols == [*STAGE_COLUMNS, "stage_min"], str(stage_cols))
    defaults = {r["name"]: r["dflt_value"] for r in columns(conn, "user_settings")}
    rep.check("user_settings defaults '[\"xs\",\"zk\"]' / 1 (pragma)", (defaults.get("stages_json"), defaults.get("current_stage")) == ("'[\"xs\",\"zk\"]'", "1"), f"{defaults.get('stages_json')} / {defaults.get('current_stage')}")
    index_names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name IN ('words', 'user_settings')")}
    wanted = {"ux_words_lemma", "ix_words_frq", "ix_words_stage_min", "ix_words_content", "ix_words_created_by", "ix_words_public", "ix_user_settings_next_push"}
    rep.check("words / user_settings indexes re-created", wanted <= index_names, ", ".join(sorted(wanted - index_names)) or "all present")

    word_id = conn.execute("SELECT MIN(id) FROM words").fetchone()[0]
    user_id = conn.execute("SELECT MIN(user_id) FROM user_settings").fetchone()[0]
    if word_id is None:
        rep.skip("words CHECK probes", "no rows in words")
    else:
        for label, stmt in (
            ("stage_min = 6 rejected", "UPDATE words SET stage_min = 6 WHERE id = ?"),
            ("stage_min = 0 rejected", "UPDATE words SET stage_min = 0 WHERE id = ?"),
            ("stage_xs = 2 rejected", "UPDATE words SET stage_xs = 2 WHERE id = ?"),
        ):
            ok, detail = rejected(conn, stmt, (word_id,))
            rep.check(label, ok, detail[:60])
        ok, detail = accepted(conn, "UPDATE words SET stage_xs = 1, stage_min = 1 WHERE id = ?", (word_id,))
        rep.check("stage_xs = 1 / stage_min = 1 storable", ok, detail[:60])
    if user_id is None:
        rep.skip("user_settings CHECK probes", "no rows in user_settings")
    else:
        for label, stmt in (("current_stage = 6 rejected", "UPDATE user_settings SET current_stage = 6 WHERE user_id = ?"), ("current_stage = 0 rejected", "UPDATE user_settings SET current_stage = 0 WHERE user_id = ?")):
            ok, detail = rejected(conn, stmt, (user_id,))
            rep.check(label, ok, detail[:60])
        ok, detail = rejected(conn, "INSERT INTO user_words(user_id, word_id, state, origin) VALUES (?, 999999, 'new', 'browse')", (user_id,))
        rep.check("user_words FK still points at the rebuilt words table (word_id 999999 rejected)", ok, detail[:60])
    # a fresh settings row inside a rolled-back transaction: the DDL defaults as the service will see them
    conn.execute("BEGIN")
    try:
        conn.execute("INSERT INTO users(username, password_hash) VALUES ('rehearsal-tmp-user', '$2b$12$x')")
        uid = conn.execute("SELECT id FROM users WHERE username = 'rehearsal-tmp-user'").fetchone()[0]
        conn.execute("INSERT INTO user_settings(user_id, next_push_at) VALUES (?, '2026-01-01T00:00:00Z')", (uid,))
        row = conn.execute("SELECT stages_json, current_stage FROM user_settings WHERE user_id = ?", (uid,)).fetchone()
        rep.check("new settings row defaults to ('[\"xs\",\"zk\"]', 1)", tuple(row) == ('["xs","zk"]', 1), str(tuple(row)))
    except sqlite3.Error as e:
        rep.check("new settings row defaults to ('[\"xs\",\"zk\"]', 1)", False, f"insert failed: {e}")
    finally:
        conn.execute("ROLLBACK")


def check_0012(rep: Report, conn: sqlite3.Connection, before: dict[str, Any], ran_here: bool) -> None:
    """word_images meta columns (PLAN §2.3)."""
    cols = {r["name"]: r for r in columns(conn, "word_images")}
    rep.check("word_images has prompt_version / model / text_free / eval_json", all(c in cols for c in WORD_IMAGES_META_COLUMNS), f"{len(cols)} columns")
    tf = cols.get("text_free")
    rep.check("text_free INTEGER NOT NULL DEFAULT 0", tf is not None and tf["notnull"] == 1 and str(tf["dflt_value"]) == "0", str(tuple(tf)) if tf else "missing")
    n_rows = int(scalar(conn, "SELECT COUNT(*) FROM word_images"))
    rep.check("word_images row count unchanged", n_rows == before["counts"].get("word_images", n_rows), f"{n_rows} rows")
    if ran_here and n_rows:
        row = conn.execute("SELECT SUM(text_free), SUM(prompt_version IS NULL), SUM(model IS NULL), SUM(eval_json IS NULL) FROM word_images").fetchone()
        rep.check("existing images: text_free 0, prompt_version / model / eval_json NULL", tuple(int(x or 0) for x in row) == (0, n_rows, n_rows, n_rows), f"(sum text_free, null prompt_version, null model, null eval_json) = {tuple(row)} of {n_rows}")
    if n_rows:
        ok, detail = rejected(conn, "UPDATE word_images SET text_free = 2 WHERE id = (SELECT MIN(id) FROM word_images)")
        rep.check("text_free = 2 rejected", ok, detail[:60])
    else:
        rep.skip("text_free CHECK probe", "no rows in word_images")


def check_0013(rep: Report, conn: sqlite3.Connection, before: dict[str, Any]) -> None:
    """word_forms rebuilt with kind 'alias' (PLAN §2.4)."""
    ddl = table_sql(conn, "word_forms")
    rep.check("word_forms CHECK admits 'alias' and keeps 'alt'", "'alias'" in ddl and "'alt'" in ddl)
    rep.check("word_forms stays WITHOUT ROWID with ix_word_forms_word", "WITHOUT ROWID" in ddl and scalar(conn, "SELECT COUNT(*) FROM sqlite_master WHERE type = 'index' AND name = 'ix_word_forms_word'") == 1)
    kinds_now = {str(r[0]): int(r[1]) for r in conn.execute("SELECT kind, COUNT(*) FROM word_forms GROUP BY kind")}
    rep.check("word_forms rows and kind distribution unchanged", kinds_now == before.get("word_forms_kinds", kinds_now), str(kinds_now))
    word_id = conn.execute("SELECT MIN(id) FROM words").fetchone()[0]
    if word_id is None:
        rep.skip("word_forms kind probes", "no rows in words")
        return
    ok, detail = accepted(conn, "INSERT INTO word_forms(form, word_id, kind) VALUES ('rehearsal-alias-probe', ?, 'alias')", (word_id,))
    rep.check("an 'alias' row is accepted", ok, detail[:60])
    ok, detail = rejected(conn, "INSERT INTO word_forms(form, word_id, kind) VALUES ('rehearsal-bogus-probe', ?, 'bogus')", (word_id,))
    rep.check("an unknown kind is rejected", ok, detail[:60])
    allowed = {str(r[0]) for r in conn.execute("SELECT DISTINCT kind FROM word_forms")}
    rep.check("every stored kind is in the 0013 list", allowed <= set(WORD_FORMS_KINDS_0013), ", ".join(sorted(allowed - set(WORD_FORMS_KINDS_0013))) or "ok")


def check_0016(rep: Report, conn: sqlite3.Connection, before: dict[str, Any], ran_here: bool) -> None:
    """jobs / ai_calls rebuilt with the dance type / kind — every column, row and index kept — plus word_dances and the two words
    columns (docs/releases/2026-11-word-dance-p2.md §4; mirrors backend/tests/unit/test_db_0016.py on the operator's copy)."""
    for table in ("jobs", "ai_calls"):
        cols = [c["name"] for c in columns(conn, table)]
        rep.check(f"{table}: same columns in the same order", cols == before.get(f"{table}_cols", cols), f"{len(cols)} columns")
        rep.check(f"{table}: every row intact (ids and values)", table_digest(conn, table) == before.get(f"{table}_digest"), f"{scalar(conn, f'SELECT COUNT(*) FROM {table}')} rows")
        idx = index_names(conn, table)
        rep.check(f"{table}: indexes re-created", set(before.get(f"{table}_indexes", idx)) <= idx, ", ".join(sorted(idx)))
    ok, detail = accepted(conn, "INSERT INTO jobs(type, payload_json) VALUES ('generate_dance', '{}')")
    rep.check("jobs.type admits generate_dance", ok, detail)
    ok, detail = rejected(conn, "INSERT INTO jobs(type, payload_json) VALUES ('generate_dance2', '{}')")
    rep.check("jobs.type still rejects strangers", ok, detail)
    ok, detail = accepted(conn, "INSERT INTO ai_calls(kind, model_requested, max_budget_usd) VALUES ('dance', 'sonnet', 0.25)")
    rep.check("ai_calls.kind admits dance", ok, detail)
    ok, detail = rejected(conn, "INSERT INTO ai_calls(kind, model_requested, max_budget_usd) VALUES ('tango', 'sonnet', 0.25)")
    rep.check("ai_calls.kind still rejects strangers", ok, detail)
    words_cols = [c["name"] for c in columns(conn, "words")]
    rep.check("words.active_dance_id / dance_state appended last", words_cols[-2:] == ["active_dance_id", "dance_state"], str(words_cols[-2:]))
    rep.check("word_dances + ux_word_dances_active present", "word_dances" in db.table_names(conn) and int(scalar(conn, "SELECT COUNT(*) FROM sqlite_master WHERE type = 'index' AND name = 'ux_word_dances_active'")) == 1)
    ok, detail = rejected(conn, "UPDATE words SET dance_state = 'dancing' WHERE id = (SELECT MIN(id) FROM words)")
    rep.check("words.dance_state CHECK", ok, detail)
    if ran_here:
        rep.check("dance_state 'none' everywhere right after the file", int(scalar(conn, "SELECT COUNT(*) FROM words WHERE dance_state != 'none'")) == 0)
        rep.check("word_dances empty right after the file (the annotations are the job's work)", int(scalar(conn, "SELECT COUNT(*) FROM word_dances")) == 0)


def check_0017(rep: Report, conn: sqlite3.Connection, before: dict[str, Any], ran_here: bool) -> None:
    """word_dances.corrected appended (nullable, CHECK 0/1); the file fills nothing — wd.dance.backfill_corrected does at the next
    service start — so the rehearsal runs that backfill here, on the copy, and reports the split (docs/releases/2026-11-word-dance-p3b.md
    §3 / §4; mirrors backend/tests/unit/test_db_0017.py)."""
    from wd import dance

    cols = [c["name"] for c in columns(conn, "word_dances")]
    rep.check("word_dances.corrected appended last", cols[-1] == "corrected", str(cols[-3:]))
    total = int(scalar(conn, "SELECT COUNT(*) FROM word_dances"))
    if total:
        ok, detail = rejected(conn, "UPDATE word_dances SET corrected = 2 WHERE id = (SELECT MIN(id) FROM word_dances)")
        rep.check("word_dances.corrected CHECK (0/1)", ok, detail)
    else:
        rep.skip("word_dances.corrected CHECK probe", "no word_dances rows")
    if ran_here:
        rep.check("corrected NULL everywhere right after the file (the backfill is the service start's work)", int(scalar(conn, "SELECT COUNT(*) FROM word_dances WHERE corrected IS NULL")) == total, f"{total} rows")
    filled = dance.backfill_corrected(conn)
    nulls = int(scalar(conn, "SELECT COUNT(*) FROM word_dances WHERE corrected IS NULL"))
    ones = int(scalar(conn, "SELECT COUNT(*) FROM word_dances WHERE corrected = 1"))
    rep.check("backfill_corrected (what the next service start does) leaves no NULL", nulls == 0, f"filled {filled}; corrected = 1 on {ones} of {total} rows")
    rep.check("backfill_corrected is idempotent", dance.backfill_corrected(conn) == 0)


def check_0018(rep: Report, conn: sqlite3.Connection, before: dict[str, Any], ran_here: bool) -> None:
    """identities / login_codes created, the eight account columns + sessions.actor_user_id appended, password_set_at backfilled with
    created_at (docs/AUTH_SIGNUP_DESIGN.md §5.1, docs/releases/2026-11-auth-signup-1a.md; mirrors backend/tests/unit/test_db_0018.py on
    the operator's copy)."""
    users_cols = [c["name"] for c in columns(conn, "users")]
    rep.check("users: the eight 0018 columns appended last, in file order", users_cols[-8:] == list(USERS_0018_COLUMNS), str(users_cols[-8:]))
    kind = next((c for c in columns(conn, "users") if c["name"] == "account_kind"), None)
    rep.check("users.account_kind TEXT NOT NULL DEFAULT 'learner'", kind is not None and kind["notnull"] == 1 and str(kind["dflt_value"]) == "'learner'", str(tuple(kind)) if kind else "missing")
    sessions_cols = [c["name"] for c in columns(conn, "sessions")]
    rep.check("sessions.actor_user_id appended last", sessions_cols[-1] == "actor_user_id", str(sessions_cols[-2:]))
    tables = set(db.table_names(conn))
    rep.check("identities + login_codes present, email_codes kept (stop-write only, no DROP)", {"identities", "login_codes", "email_codes"} <= tables)
    idx = index_names(conn, "identities") | index_names(conn, "login_codes") | index_names(conn, "sessions")
    rep.check("0018 indexes present", INDEXES_0018 <= idx, ", ".join(sorted(INDEXES_0018 - idx)) or "all present")
    n_users = int(scalar(conn, "SELECT COUNT(*) FROM users"))
    rep.check("users row count unchanged (no rebuild)", n_users == before["counts"].get("users", n_users), f"{n_users} rows")
    rep.check("sessions row count unchanged (no rebuild)", int(scalar(conn, "SELECT COUNT(*) FROM sessions")) == before["counts"].get("sessions", 0))
    if ran_here:
        rep.check("password_set_at = created_at on every existing account (the backfill)", int(scalar(conn, "SELECT COUNT(*) FROM users WHERE password_set_at IS NULL OR password_set_at != created_at")) == 0, f"{n_users} rows")
        rep.check("account_kind 'learner' everywhere, nothing declared yet", int(scalar(conn, "SELECT COUNT(*) FROM users WHERE account_kind != 'learner' OR age_band IS NOT NULL OR guardian_user_id IS NOT NULL")) == 0)
        rep.check("identities / login_codes empty right after the file", int(scalar(conn, "SELECT COUNT(*) FROM identities")) == 0 and int(scalar(conn, "SELECT COUNT(*) FROM login_codes")) == 0)
        rep.check("sessions.actor_user_id NULL everywhere (every existing session is a self login)", int(scalar(conn, "SELECT COUNT(*) FROM sessions WHERE actor_user_id IS NOT NULL")) == 0)
    if n_users:
        for label, stmt in (
            ("users.account_kind CHECK", "UPDATE users SET account_kind = 'teacher' WHERE id = (SELECT MIN(id) FROM users)"),
            ("users.age_band CHECK", "UPDATE users SET age_band = 'kid' WHERE id = (SELECT MIN(id) FROM users)"),
            ("identities.provider CHECK", "INSERT INTO identities(user_id, provider, subject) VALUES ((SELECT MIN(id) FROM users), 'sms', '+8613800138000')"),
            ("login_codes.channel CHECK", "INSERT INTO login_codes(channel, target, purpose, code_hash, expires_at) VALUES ('fax', 'x', 'login', 'h', '2099-01-01T00:00:00Z')"),
            ("login_codes.purpose CHECK", "INSERT INTO login_codes(channel, target, purpose, code_hash, expires_at) VALUES ('phone', 'x', 'dance', 'h', '2099-01-01T00:00:00Z')"),
            ("users.guardian_user_id FK (unknown guardian rejected)", "UPDATE users SET guardian_user_id = 999999999 WHERE id = (SELECT MIN(id) FROM users)"),
        ):
            ok, detail = rejected(conn, stmt)
            rep.check(label, ok, detail[:60])
        ok, detail = accepted(conn, "INSERT INTO identities(user_id, provider, subject) VALUES ((SELECT MIN(id) FROM users), 'phone', '+8613800138000')")
        rep.check("a live phone identity is storable", ok, detail[:60])
        # the partial unique indexes inside a rolled-back transaction: one live row per number (two users), one live phone per user,
        # and a disputed row frees the number for its new holder
        uids = [int(r[0]) for r in conn.execute("SELECT id FROM users ORDER BY id LIMIT 2")]
        first, second = uids[0], (uids[1] if len(uids) > 1 else None)
        conn.execute("BEGIN")
        try:
            conn.execute("INSERT INTO identities(id, user_id, provider, subject) VALUES (-1, ?, 'phone', '+8613800138000')", (first,))
            try:
                conn.execute("INSERT INTO identities(id, user_id, provider, subject) VALUES (-3, ?, 'phone', '+8613800138001')", (first,))
                rep.check("ux_identities_user_provider: a second live phone on one account is rejected", False, "accepted")
            except sqlite3.IntegrityError as e:
                rep.check("ux_identities_user_provider: a second live phone on one account is rejected", "UNIQUE" in str(e) and "identities.user_id" in str(e), str(e)[:70])
            if second is None:
                rep.skip("ux_identities_live probe", "only one user on the copy")
            else:
                try:
                    conn.execute("INSERT INTO identities(id, user_id, provider, subject) VALUES (-2, ?, 'phone', '+8613800138000')", (second,))
                    rep.check("ux_identities_live: the same live number on two accounts is rejected", False, "accepted")
                except sqlite3.IntegrityError as e:
                    rep.check("ux_identities_live: the same live number on two accounts is rejected", "UNIQUE" in str(e) and "identities.provider, identities.subject" in str(e), str(e)[:70])
                conn.execute("UPDATE identities SET disputed_at = '2026-01-01T00:00:00Z' WHERE id = -1")
                conn.execute("INSERT INTO identities(id, user_id, provider, subject) VALUES (-2, ?, 'phone', '+8613800138000')", (second,))
                rep.check("a disputed row frees the number for its new holder", True)
        except sqlite3.Error as e:
            rep.check("a disputed row frees the number for its new holder", False, f"probe failed: {e}")
        finally:
            conn.execute("ROLLBACK")
    else:
        rep.skip("0018 CHECK / unique probes", "no rows in users")
    ok, detail = rejected(conn, "INSERT INTO identities(user_id, provider, subject) VALUES (999999999, 'phone', '+8613800138001')")
    rep.check("identities.user_id FK (unknown user rejected)", ok, detail[:60])


def check_0014(rep: Report, conn: sqlite3.Connection, before: dict[str, Any], ran_here: bool) -> None:
    """words.learn_rank, the learning order recomputed on the copy (DESIGN §2.9; docs/analysis/2026-11-06-learn-order/DESIGN.md)."""
    cols = {r["name"]: r for r in columns(conn, "words")}
    col = cols.get("learn_rank")
    rep.check("words.learn_rank INTEGER, nullable, no default", col is not None and col["type"] == "INTEGER" and col["notnull"] == 0 and col["dflt_value"] is None, str(tuple(col)) if col else "missing")
    rep.check("no ix_words_learn_rank (the learning-order ORDER BYs sort in a temp B-tree after a CASE / COALESCE term)", scalar(conn, "SELECT COUNT(*) FROM sqlite_master WHERE type = 'index' AND name = 'ix_words_learn_rank'") == 0)
    n_words = int(scalar(conn, "SELECT COUNT(*) FROM words"))
    rep.check("words row count unchanged (no rebuild)", n_words == before["counts"].get("words", n_words), f"{n_words} rows")
    rep.check("v_bank unchanged", int(scalar(conn, "SELECT COUNT(*) FROM v_bank")) == before.get("v_bank", -1), f"{before.get('v_bank')} rows")
    if ran_here:
        nonnull = int(scalar(conn, "SELECT COUNT(*) FROM words WHERE learn_rank IS NOT NULL"))
        rep.check("learn_rank is NULL everywhere right after the file (the fill is the code path's job)", nonnull == 0, f"{nonnull} non-NULL")
    # recompute on the copy — the same code the service start / `wd learn-order` run; nothing here touches production
    max_updated_before = scalar(conn, "SELECT MAX(updated_at) FROM words")
    t0 = time.perf_counter()
    result = learn_order.recompute(conn, trigger="rehearsal")
    rep.info("learn_order.recompute on the copy", f"{learn_order.format_result(result)} ({(time.perf_counter() - t0) * 1000:.0f} ms incl. the write)")
    rep.check("0 stage words unranked after the recompute", learn_order.unranked_stage_words(conn) == 0, f"{learn_order.unranked_stage_words(conn)} unranked")
    rep.check(f"kv.learn_order.version == {learn_order.LEARN_ORDER_VERSION}", db.kv_get(conn, learn_order.KV_VERSION) == learn_order.LEARN_ORDER_VERSION, str(db.kv_get(conn, learn_order.KV_VERSION)))
    stale = learn_order.stale_count(conn)
    rep.check("stored keys equal the policy (stale_count 0)", stale == 0, f"{stale} stale")
    second = learn_order.recompute(conn, trigger="rehearsal")
    rep.check("a second recompute changes 0 rows", second.changed == 0, f"{second.changed} changed")
    rep.check("MAX(updated_at) unchanged by the recompute", scalar(conn, "SELECT MAX(updated_at) FROM words") == max_updated_before, str(max_updated_before))
    report = learn_order.report(conn)
    closed = report["acceptance"]["closed_in_first_30"]
    rep.check("0 FACTS-closed words in every stage's first 30 (DESIGN §1.6)", all(n == 0 for n in closed.values()), str(closed))
    rep.info("acceptance (computed on the copy)", str({k: v for k, v in report["acceptance"].items() if k != "closed_in_first_30"}))
    for code, label in (("xs", "小学"), ("zk", "初中新增")):
        head = learn_order.show(conn, code, 15)
        rep.info(f"{label} order (first 15)", " ".join(f"{r.position}:{r.lemma}" for r in head) or "(no rows)")
    for code, s in report["stages"].items():
        rep.info(f"stage {code}", f"n {s['n']} · ranked {s['ranked']} · dealt {s['dealt']} · closed {s['closed']} · first 8: {' '.join(s['first'][:8]) or '-'}")
    word_id = conn.execute("SELECT MIN(id) FROM words").fetchone()[0]
    if word_id is None:
        rep.skip("learn_rank NULL probe", "no rows in words")
    else:
        ok, detail = accepted(conn, "UPDATE words SET learn_rank = NULL WHERE id = ?", (word_id,))
        rep.check("learn_rank = NULL storable (NULL is a legal state: not computed yet)", ok, detail[:60])


def check_invariants(rep: Report, conn: sqlite3.Connection) -> None:
    """The `wd check db` stage invariants (diag.STAGE_INVARIANTS) hold already before the seed re-import; from 0014 the four
    learning-order lines come from the same function `wd check db` runs (learn_order.check_lines), so script and command agree."""
    for name, sql in STAGE_INVARIANTS:
        try:
            n = int(scalar(conn, sql))
        except sqlite3.OperationalError as e:
            rep.skip(f"invariant {name}", f"query failed ({e}) — this SQLite build lacks the function; `wd check db` reports the same")
            continue
        rep.check(f"invariant {name}", n == 0, "ok" if n == 0 else f"{n} violation(s)")
    if db.current_version(conn) >= LEARN_ORDER_INVARIANTS_FROM_VERSION:
        for line, violated in learn_order.check_lines(conn):
            name, _, rest = line[len("invariant ") :].partition(": ")
            if rest.startswith("query failed"):
                rep.skip(f"invariant {name}", rest)
            else:
                rep.check(f"invariant {name}", not violated, rest)


def check_empty_database(rep: Report, target: Path, keep: bool) -> None:
    """A fresh file migrates 0001 → latest with the same table set (the install.sh path)."""
    empty = target.with_name(target.name + ".empty-rehearsal.db")
    for suffix in ("", "-wal", "-shm"):
        Path(str(empty) + suffix).unlink(missing_ok=True)
    conn = db.connect(empty)
    try:
        result = db.run_migrations(conn)
        shipped = [(f.version, f.name) for f in db.list_migration_files()]
        rep.check("empty database applies every shipped file", result.applied == shipped, f"applied {[v for v, _ in result.applied]}")
        rep.check(f"empty database has {EXPECTED_TABLE_COUNT} tables + v_bank", len(db.table_names(conn)) == EXPECTED_TABLE_COUNT and db.view_names(conn) == ["v_bank"], f"{len(db.table_names(conn))} tables, views {db.view_names(conn)}")
        defaults = {r["name"]: r["dflt_value"] for r in columns(conn, "user_settings")}
        rep.check("empty database: K-12 defaults", (defaults.get("stages_json"), defaults.get("current_stage")) == ("'[\"xs\",\"zk\"]'", "1"))
    finally:
        conn.close()
        if not keep:
            for suffix in ("", "-wal", "-shm"):
                Path(str(empty) + suffix).unlink(missing_ok=True)


# ----------------------------------------------------------------------------------------------- main
def rehearse(target: Path, *, keep_empty_db: bool = False) -> int:
    rep = Report()
    if not target.is_file():
        print(f"rehearse_migration: {target} is not a file (copy the database to a private directory first)", file=sys.stderr)
        return 1
    wal = Path(str(target) + "-wal")
    if wal.is_file() and wal.stat().st_size > 0:
        rep.info("note", f"{wal.name} is non-empty: SQLite folds it into the copy on open; a copy taken while the service ran may miss its newest commits (use `VACUUM INTO` or stop the service first)")
    rep.info("sqlite", f"{sqlite3.sqlite_version} (RENAME semantics need ≥ 3.26; json_each is built in from 3.38)")
    rep.info("migrations", str(db.MIGRATIONS_DIR))

    try:
        conn = db.connect(target)
    except sqlite3.Error as e:  # `file is not a database` and friends — db.connect runs its PRAGMAs on open
        rep.check("the copy is a word-Dance database", False, f"cannot open: {e}")
        return rep.failed
    try:
        try:
            before = snapshot(conn)
        except sqlite3.Error as e:  # an empty file, a foreign database without the kv table: nothing to rehearse
            rep.check("the copy is a word-Dance database", False, f"{e} — copy word-dance.db itself, not an empty or foreign file")
            return rep.failed
        pending = db.pending_migrations(conn)
        shipped = [f.version for f in db.list_migration_files()]
        later = [v for v in shipped if v > before["version"]]
        rep.info("schema before", f"version {before['version']}, pending {[(f.version, f.name) for f in pending]}")
        rep.check("pending = every shipped file newer than the recorded version (what `wd migrate --dry-run` lists)", [f.version for f in pending] == later, f"pending {[f.version for f in pending]} vs newer files {later}")
        if before["version"] < 1:
            rep.check("the copy is a word-Dance database", False, "no schema_migrations rows — an empty file migrates, but there is nothing to rehearse")
            return rep.failed

        t0 = time.perf_counter()
        result = db.run_migrations(conn)
        elapsed = time.perf_counter() - t0
        rep.info("applied", f"{result.applied} in {elapsed:.3f}s")
        rep.check("every pending file applied", result.applied == [(f.version, f.name) for f in pending])
        applied_versions = {v for v, _ in result.applied}
        recorded = db.applied_versions(conn)

        check_bookkeeping(rep, conn, before, result.applied)
        if 11 in recorded:
            check_0011(rep, conn, before, ran_here=11 in applied_versions)
        else:
            rep.skip("0011 checks", "not recorded in schema_migrations")
        if 12 in recorded:
            check_0012(rep, conn, before, ran_here=12 in applied_versions)
        else:
            rep.skip("0012 checks", "not recorded in schema_migrations")
        if 13 in recorded:
            check_0013(rep, conn, before)
        else:
            rep.skip("0013 checks", "not recorded in schema_migrations")
        if 14 in recorded:
            check_0014(rep, conn, before, ran_here=14 in applied_versions)
        else:
            rep.skip("0014 checks", "not recorded in schema_migrations")
        if 16 in recorded:
            check_0016(rep, conn, before, ran_here=16 in applied_versions)
        else:
            rep.skip("0016 checks", "not recorded in schema_migrations")
        if 17 in recorded:
            check_0017(rep, conn, before, ran_here=17 in applied_versions)
        else:
            rep.skip("0017 checks", "not recorded in schema_migrations")
        if 18 in recorded:
            check_0018(rep, conn, before, ran_here=18 in applied_versions)
        else:
            rep.skip("0018 checks", "not recorded in schema_migrations")
        if db.current_version(conn) >= STAGE_INVARIANTS_FROM_VERSION:
            check_invariants(rep, conn)

        second = db.run_migrations(conn)
        rep.check("second run applies nothing", second.applied == [] and not conn.in_transaction, str(second.applied))
        pages, free = int(scalar(conn, "PRAGMA page_count")), int(scalar(conn, "PRAGMA freelist_count"))
        rep.info("file", f"{pages} pages, {free} free, {target.stat().st_size} bytes (PLAN §8 step 9: ANALYZE + VACUUM while the service is stopped)")
    finally:
        conn.close()

    check_empty_database(rep, target, keep_empty_db)
    verdict = "rehearsal OK" if rep.failed == 0 else f"rehearsal FAILED: {rep.failed} check(s)"
    print(f"{verdict} ({rep.passed} passed, {rep.failed} failed)")
    return rep.failed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply the pending migrations to a PRIVATE COPY of word-dance.db and verify the result (exit status = failed checks).")
    parser.add_argument("db", type=Path, help="the copy to migrate (never the live file)")
    parser.add_argument("--keep-empty-db", action="store_true", help="keep <db>.empty-rehearsal.db (the fresh-database check) instead of deleting it")
    args = parser.parse_args(argv)
    return rehearse(args.db.expanduser().resolve(), keep_empty_db=bool(args.keep_empty_db))


if __name__ == "__main__":
    raise SystemExit(main())
