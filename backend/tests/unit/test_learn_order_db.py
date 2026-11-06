"""services/learn_order.py — the DB half (docs/analysis/2026-11-06-learn-order/DESIGN.md §2.1, §4.1 items 13–18): recompute
writes only the changed rows (never updated_at), the four kv keys and the learn_order_recomputed event (never from the seed
import); it joins an open transaction; ensure_current never raises (learn_order_failed event, fail-soft lists); the seed stamp
makes an old-code import visible to is_current and the next ensure_current repairs it; the stats document round-trips and
stale_count scopes to stage words; show() equals the SQL order and the --dry-run movers report names a hand edit.
Review fixes: a TEXT learn_rank reads as NULL and is rewritten (F-2); a runtime word or form re-deals stage phrases without
flipping the gate — Drift.policy vs Drift.dealt (F-1); a raising policy is `query failed` (F2); the stored keys are re-read under
the write lock (F3); the drift counts are 0 right after a policy-version bump (N-8)."""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

import pytest

from wd import db
from wd.schemas import STAGE_ORDER, stage_to_index
from wd.seed import seed_digest
from wd.services import learn_order as lo
from wd.services import words

from test_learn_order import GOLDEN  # sibling module (pytest prepend import mode, like test_db_0013 imports test_db)

MINI_SEED = Path(__file__).resolve().parents[1] / "fixtures" / "mini_seed.jsonl"
T0, T1 = "2026-11-06T00:00:00Z", "2026-11-06T00:05:00Z"
KV_KEYS = (lo.KV_VERSION, lo.KV_SEED, lo.KV_STATS, lo.KV_AT)


def clear_ranks(conn: sqlite3.Connection) -> None:
    """The state right after 0014 on a database whose seed was imported by the previous version: column present, nothing computed."""
    conn.execute("UPDATE words SET learn_rank = NULL")
    conn.execute("DELETE FROM kv WHERE key LIKE 'learn_order.%'")
    conn.execute("DELETE FROM system_events WHERE kind LIKE 'learn_order_%'")


def stored(conn: sqlite3.Connection) -> dict[str, int | None]:
    return {str(r[0]): r[1] for r in conn.execute("SELECT lemma, learn_rank FROM words")}


def updated_at(conn: sqlite3.Connection) -> dict[str, str]:
    return {str(r[0]): str(r[1]) for r in conn.execute("SELECT lemma, updated_at FROM words")}


def events(conn: sqlite3.Connection, kind: str) -> list[dict]:
    return [json.loads(r[0]) for r in conn.execute("SELECT detail_json FROM system_events WHERE kind = ? ORDER BY id", (kind,))]


def kv(conn: sqlite3.Connection) -> dict[str, str | None]:
    return {key: db.kv_get(conn, key) for key in KV_KEYS}


def sql_order(conn: sqlite3.Connection, where: str, params: dict, *, prefix: str = "", limit: int = 1000) -> list[str]:
    order = f"{prefix}, {lo.ORDER_SQL}" if prefix else lo.ORDER_SQL
    return [str(r[0]) for r in conn.execute(f"SELECT w.lemma FROM words w WHERE {where} ORDER BY {order} LIMIT {limit}", params)]


# ------------------------------------------------------------------------------------------- 13 recompute
def test_recompute_writes_only_changed_rows_never_updated_at_and_is_idempotent(seeded):
    conn = seeded
    clear_ranks(conn)  # the seeded fixture already ranked the rows through the import hook
    before = updated_at(conn)
    r1 = lo.recompute(conn, now=T0)
    assert (r1.version, r1.rows, r1.changed, r1.unranked_stage_words, r1.trigger, r1.dry_run, r1.movers) == (lo.LEARN_ORDER_VERSION, 62, 62, 0, "cli", False, None)
    assert r1.seconds >= 0
    assert stored(conn) == GOLDEN  # the lo-1 golden table, now in the column
    assert updated_at(conn) == before  # a rank change never moves updated_at (the template-card LRU key)
    keys = kv(conn)
    assert keys[lo.KV_VERSION] == lo.LEARN_ORDER_VERSION == "lo-1" and keys[lo.KV_AT] == T0
    assert keys[lo.KV_SEED] == db.kv_get(conn, "seed_version") == seed_digest(MINI_SEED)  # the seed stamp defaults to kv.seed_version
    stats = json.loads(keys[lo.KV_STATS] or "")
    assert set(stats) == set(STAGE_ORDER) | {lo.STATS_NONE, "label_pos_stage_words", "drift_dealt", "drift_none"}
    assert stats == r1.stats and stats["label_pos_stage_words"] == 0 and stats["drift_dealt"] == 0 and stats["drift_none"] == 0 and len(keys[lo.KV_STATS] or "") < 2048
    assert stats["xs"]["n"] == conn.execute("SELECT COUNT(*) FROM words WHERE stage_min = 1").fetchone()[0]
    recomputed = events(conn, lo.EVENT_RECOMPUTED)
    assert len(recomputed) == 1 and recomputed[0]["changed"] == 62 and recomputed[0]["trigger"] == "cli" and recomputed[0]["version"] == "lo-1"
    assert recomputed[0]["rows"] == 62 and recomputed[0]["unranked_stage_words"] == 0 and "seconds" in recomputed[0]
    # idempotent: nothing to write, no second event, the kv instant moves (computed_at is the last compare)
    r2 = lo.recompute(conn, now=T1)
    assert (r2.changed, r2.rows, r2.unranked_stage_words) == (0, 62, 0)
    assert stored(conn) == GOLDEN and updated_at(conn) == before and len(events(conn, lo.EVENT_RECOMPUTED)) == 1
    assert kv(conn)[lo.KV_AT] == T1 and kv(conn)[lo.KV_VERSION] == "lo-1"
    # the seed import's trigger writes no event (seed_imported carries the count) and stamps the digest it was given
    clear_ranks(conn)
    r3 = lo.recompute(conn, now=T1, seed_version="stamp-from-the-importer", trigger=lo.TRIGGER_SEED_IMPORT)
    assert r3.changed == 62 and events(conn, lo.EVENT_RECOMPUTED) == [] and kv(conn)[lo.KV_SEED] == "stamp-from-the-importer"
    assert not conn.in_transaction


def test_recompute_writes_null_for_a_row_that_lost_its_rank(seeded):
    """The change set includes rows whose key becomes NULL (R4): a hand-ranked frequency-less closed word in a group without hosts."""
    conn = seeded
    conn.execute("INSERT INTO words(lemma, display, kind, pos, source, stage_zk, stage_min, learn_rank) VALUES ('ghostly', 'ghostly', 'word', 'i:100', 'seed', 1, 2, 123)")
    r = lo.recompute(conn, now=T0)
    assert r.changed == 1 and r.unranked_stage_words == 1 and r.stats["zk"]["n"] == 13
    assert conn.execute("SELECT learn_rank FROM words WHERE lemma = 'ghostly'").fetchone()[0] is None
    assert lo.unranked_stage_words(conn) == 1


# ------------------------------------------------------------------------------------- 14 transactions
def test_recompute_joins_an_open_transaction_and_rolls_back_with_it(seeded):
    conn = seeded
    clear_ranks(conn)
    with pytest.raises(RuntimeError, match="abort"):
        with db.tx(conn):
            r = lo.recompute(conn, now=T0)
            assert conn.in_transaction and r.changed == 62
            assert conn.execute("SELECT COUNT(*) FROM words WHERE learn_rank IS NOT NULL").fetchone()[0] == 62  # visible inside
            raise RuntimeError("abort")
    assert not conn.in_transaction
    assert conn.execute("SELECT COUNT(*) FROM words WHERE learn_rank IS NOT NULL").fetchone()[0] == 0
    assert kv(conn) == {key: None for key in KV_KEYS} and events(conn, lo.EVENT_RECOMPUTED) == []
    # on its own it is atomic: BEGIN IMMEDIATE … COMMIT
    r = lo.recompute(conn, now=T0)
    assert r.changed == 62 and not conn.in_transaction and stored(conn) == GOLDEN


def test_dry_run_writes_nothing(seeded):
    conn = seeded
    clear_ranks(conn)
    changes = conn.total_changes
    r = lo.recompute(conn, now=T0, dry_run=True, movers=True)
    assert r.dry_run is True and r.changed == 62 and r.rows == 62 and r.unranked_stage_words == 0 and r.movers is not None
    assert conn.total_changes == changes and not conn.in_transaction
    assert all(v is None for v in stored(conn).values()) and kv(conn) == {key: None for key in KV_KEYS} and events(conn, lo.EVENT_RECOMPUTED) == []


# ---------------------------------------------------------------------------------- 15 ensure_current
def test_ensure_current_never_raises(seeded, monkeypatch, caplog):
    conn = seeded
    before = stored(conn)

    def boom(rows, forms):
        raise RuntimeError("policy exploded")

    monkeypatch.setattr(lo, "rank_rows", boom)
    caplog.set_level(logging.ERROR, logger="wd.learn_order")
    assert lo.ensure_current(conn, now=T0) is None
    assert not conn.in_transaction and stored(conn) == before  # the stored keys are untouched
    failed = events(conn, lo.EVENT_FAILED)
    assert failed == [{"trigger": "startup", "error": "RuntimeError: policy exploded"}]
    records = [r for r in caplog.records if getattr(r, "event", None) == lo.EVENT_FAILED]
    assert len(records) == 1 and records[0].exc_info is not None  # logged with the traceback
    # the lists still serve: the ORDER_SQL fragment reads the stored keys, NULL or not
    assert sql_order(conn, "w.stage_min = :idx", {"idx": 1}, limit=3) == ["take", "good", "child"]
    monkeypatch.undo()
    r = lo.ensure_current(conn, now=T1, trigger="maintenance")
    assert r is not None and r.changed == 0 and r.trigger == "maintenance"


def test_ensure_current_survives_a_write_phase_fault_and_rolls_it_back(seeded, monkeypatch):
    """A database fault inside the write phase: the transaction is rolled back (no half-written ranks), the failure is recorded."""
    conn = seeded
    clear_ranks(conn)

    def broken_kv_set(c, key, value, *, now=None):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(lo.db, "kv_set", broken_kv_set)
    assert lo.ensure_current(conn, now=T0) is None
    assert not conn.in_transaction
    assert all(v is None for v in stored(conn).values())  # the UPDATEs of the same transaction were rolled back
    assert events(conn, lo.EVENT_FAILED) == [{"trigger": "startup", "error": "OperationalError: disk I/O error"}]
    monkeypatch.undo()
    assert lo.ensure_current(conn, now=T1).changed == 62  # type: ignore[union-attr]


# ------------------------------------------------------------------------------------- 16 seed stamp
def test_seed_stamp_trigger(seeded):
    conn = seeded
    assert lo.is_current(conn) == (True, "ok")
    assert kv(conn)[lo.KV_SEED] == db.kv_get(conn, "seed_version") == seed_digest(MINI_SEED)
    # an older server imported another seed while the column existed: kv.seed_version moved, one row's frq changed, ranks stale
    db.kv_set(conn, "seed_version", "other-seed-digest")
    conn.execute("UPDATE words SET frq = 1 WHERE lemma = 'apple'")
    ok, reason = lo.is_current(conn)
    assert ok is False and reason.startswith("seed ") and "≠ kv.seed_version other-seed-d…" in reason
    lines = dict(lo.check_lines(conn))
    assert f"invariant learn_order_current: 1 violation(s) (computed for {reason}; run `wd learn-order`)" in lines
    before = stored(conn)
    r = lo.ensure_current(conn, now=T0)
    assert r is not None and r.changed >= 1
    after = stored(conn)
    assert after["apple"] == lo.pack(False, 1, lo.SUB_NATIVE) == 100 != before["apple"]
    rows, forms = lo.load_inputs(conn)
    result = lo.rank_rows(rows, forms)
    apple_group = (1, False)
    ripple = {rr.lemma for rr in result.rows.values() if (rr.stage_min, rr.closed) == apple_group and rr.how != lo.HOW_NATIVE}
    assert {lemma for lemma in before if before[lemma] != after[lemma]} <= {"apple"} | ripple  # the dealt rows of apple's group may follow their hosts
    assert lo.is_current(conn) == (True, "ok") and kv(conn)[lo.KV_SEED] == "other-seed-digest"
    # the other two reasons
    db.kv_set(conn, lo.KV_VERSION, "lo-0")
    assert lo.is_current(conn) == (False, "kv.learn_order.version lo-0 ≠ code lo-1")
    assert "invariant learn_order_current: 1 violation(s) (kv.learn_order.version lo-0 ≠ code lo-1; run `wd learn-order`)" in dict(lo.check_lines(conn))
    db.kv_delete(conn, lo.KV_VERSION)
    assert lo.is_current(conn) == (False, "never computed")
    assert "invariant learn_order_current: 1 violation(s) (never computed; run `wd learn-order`)" in dict(lo.check_lines(conn))


# ------------------------------------------------------------------------------- 17 stats / stale_count
def test_stats_round_trip_and_stale_count_scope(seeded):
    conn = seeded
    rows, forms = lo.load_inputs(conn)
    result = lo.rank_rows(rows, forms)
    stats = json.loads(db.kv_get(conn, lo.KV_STATS) or "")
    assert stats == {**result.stats, "label_pos_stage_words": lo.label_pos_count(rows), "drift_dealt": 0, "drift_none": 0}
    assert json.loads(json.dumps(stats)) == stats
    line = lo.stats_line(conn)
    assert line.startswith(f"kv.{lo.KV_STATS}: xs n=") and " · zk n=" in line and " · none n=" in line
    assert line.endswith(" · dealt drift 0 · 课标外 drift 0 · label-pos 0")
    assert lo.stale_count(conn) == 0 == lo.stale_count(conn, stage_only=False) and lo.drift(conn) == lo.Drift(0, 0, 0)
    assert [violated for _, violated in lo.check_lines(conn)] == [False] * 4
    # a hand edit of a stage word's key
    conn.execute("UPDATE words SET learn_rank = learn_rank + 1 WHERE lemma = 'apple'")
    assert lo.stale_count(conn) == 1 and lo.stale_count(conn, stage_only=False) == 1 and lo.drift(conn) == lo.Drift(policy=1, dealt=0, none=0)
    lines = dict(lo.check_lines(conn))
    assert lines["invariant learn_rank_matches_policy: 1 violation(s) (stored learn_rank of stage words differs from learn_order.rank_rows(); run `wd learn-order`)"] is True
    assert lo.recompute(conn, now=T0).changed == 1 and lo.stale_count(conn) == 0
    # a 课标外 word: informational drift, never the invariant
    conn.execute("UPDATE words SET learn_rank = 5 WHERE lemma = 'bookshelf'")
    assert lo.stale_count(conn) == 0 and lo.stale_count(conn, stage_only=False) == 1 and lo.drift(conn) == lo.Drift(0, 0, 1)
    assert [violated for _, violated in lo.check_lines(conn)] == [False] * 4
    r = lo.recompute(conn, now=T1)
    assert r.changed == 1 and r.stats["drift_none"] == 1 and r.stats["drift_dealt"] == 0
    assert json.loads(db.kv_get(conn, lo.KV_STATS) or "")["drift_none"] == 1 and lo.stats_line(conn).endswith(" · dealt drift 0 · 课标外 drift 1 · label-pos 0")
    # the line never flips ok: an absent or unreadable document is reported as such
    db.kv_delete(conn, lo.KV_STATS)
    assert lo.stats_line(conn) == f"kv.{lo.KV_STATS}: -"
    db.kv_set(conn, lo.KV_STATS, "{not json")
    assert lo.stats_line(conn).startswith(f"kv.{lo.KV_STATS}: unreadable")


def test_check_lines_report_a_failing_query_without_raising(seeded, monkeypatch):
    conn = seeded
    monkeypatch.setattr(lo, "CALENDAR_INVARIANT_SQL", "SELECT COUNT(*) FROM no_such_table")
    lines = lo.check_lines(conn)
    assert len(lines) == 4 and lines[3][1] is False and lines[3][0].startswith("invariant calendar_words_in_xs: query failed (no such table")
    assert [name.split(":")[0] for name, _ in lines] == ["invariant learn_rank_present", "invariant learn_order_current", "invariant learn_rank_matches_policy", "invariant calendar_words_in_xs"]


def test_calendar_invariant_counts_present_calendar_rows_outside_xs(seeded):
    conn = seeded
    assert lo.CALENDAR_INVARIANT_SQL.count("'") == 2 * (len(lo.MONTHS) + len(lo.WEEKDAYS)) and "stage_xs IS NOT 1 OR stage_min IS NOT 1" in lo.CALENDAR_INVARIANT_SQL
    assert dict(lo.check_lines(conn))["invariant calendar_words_in_xs: ok"] is False  # the mini seed has no calendar word: nothing to violate
    conn.execute("INSERT INTO words(lemma, display, kind, source, stage_zk, stage_min) VALUES ('monday', 'Monday', 'proper_noun', 'seed', 1, 2)")
    assert "invariant calendar_words_in_xs: 1 violation(s) (month/weekday rows without stage_xs = 1 / stage_min = 1)" in dict(lo.check_lines(conn))
    conn.execute("UPDATE words SET stage_xs = 1, stage_min = 1 WHERE lemma = 'monday'")
    assert "invariant calendar_words_in_xs: ok" in dict(lo.check_lines(conn))


# ------------------------------------------------------------------------------------ 18 show / movers
def test_show_and_movers_report(seeded):
    conn = seeded
    rows = lo.show(conn, "xs", 5)
    assert [r.position for r in rows] == [1, 2, 3, 4, 5]
    assert [r.lemma for r in rows] == sql_order(conn, "w.stage_min = :idx", {"idx": stage_to_index("xs")}, limit=5)
    keys = stored(conn)
    for r in rows:
        assert r.learn_rank == keys[r.lemma] == GOLDEN[r.lemma]
        assert r.learn_rank is not None and r.eff is not None
        assert (r.learn_rank - (lo.CLOSED_BASE if r.closed else 0)) // lo.RANK_SCALE == r.eff  # eff = the rank the key encodes
        assert r.how in {lo.HOW_NATIVE, lo.HOW_DEALT} and (r.frq is None) == (r.how == lo.HOW_DEALT)
    assert {r.how for r in lo.show(conn, "xs", 100)} >= {lo.HOW_NATIVE, lo.HOW_DEALT, f"{lo.CLS_GLUED}:be"} and any(r.closed for r in lo.show(conn, "xs", 100))
    # the tab / 筛词 order of a 主攻 stage: distance first, then the key
    cur = lo.default_cur("zk")
    tab = lo.show(conn, "zk", 50, cur=cur)
    assert [r.lemma for r in tab] == sql_order(conn, "w.stage_zk = 1 AND w.merged_into_word_id IS NULL", {"cur": cur}, prefix=lo.stage_distance_sql(), limit=50)
    assert len(tab) == conn.execute("SELECT COUNT(*) FROM words WHERE stage_zk = 1").fetchone()[0] > len(lo.show(conn, "zk", 50))
    text = lo.format_show(rows)
    assert text.splitlines()[0].split() == list(lo.SHOW_COLUMNS) and len(text.splitlines()) == 6 and "take" in text.splitlines()[1]
    with pytest.raises(ValueError):
        lo.show(conn, "cet9", 5)
    # the movers report: a hand edit puts apple first in 小学; the dry run names it as the one drop and writes nothing
    conn.execute("UPDATE words SET learn_rank = 1 WHERE lemma = 'apple'")
    at = db.kv_get(conn, lo.KV_AT)
    r = lo.recompute(conn, dry_run=True, movers=True)
    assert r.changed == 1 and r.movers is not None
    xs = r.movers["stages"]["xs"]
    assert set(r.movers["stages"]) == set(STAGE_ORDER) | {lo.STATS_NONE} and r.movers["shift_threshold"] == lo.MOVERS_SHIFT == 50
    assert xs["records"] == 24 and xs["rank_changed"] == 1 and xs["moved"] == 0 and xs["max_shift"] >= 1
    assert xs["first_old"][0] == "apple" and xs["first_new"][0] == "take" and "apple" not in xs["first_new"]
    assert r.movers["drops"][0]["lemma"] == "apple" and r.movers["drops"][0]["stage"] == "xs" and r.movers["drops"][0]["old"] == 1 and r.movers["drops"][0]["shift"] < 0
    assert all(m["shift"] > 0 for m in r.movers["climbs"]) and len(r.movers["climbs"]) <= lo.MOVERS_TOP
    assert all(r.movers["stages"][code]["rank_changed"] == 0 for code in STAGE_ORDER[1:])
    assert conn.execute("SELECT learn_rank FROM words WHERE lemma = 'apple'").fetchone()[0] == 1 and db.kv_get(conn, lo.KV_AT) == at  # nothing written
    text = lo.format_movers(r)
    assert text.startswith("dry run: learn order lo-1 over 62 rows — 1 would change, nothing written") and "xs: 24 records · 1 rank changed · 0 moved ≥ 50 places" in text
    assert "biggest drops: apple (xs 1→" in text and "first 10 old: apple take" in text


def test_report_document_shape_and_acceptance_block(seeded):
    conn = seeded
    rep = lo.report(conn)
    assert list(rep) == ["policy", "seed", "computed_at", "generated_by", "stages", "acceptance"]
    assert rep["policy"] == lo.LEARN_ORDER_VERSION and rep["seed"] == db.kv_get(conn, "seed_version") and rep["computed_at"] == db.kv_get(conn, lo.KV_AT)
    assert rep["generated_by"] == "wd learn-order --report"
    assert list(rep["stages"]) == [*STAGE_ORDER, lo.STATS_NONE]
    for code, s in rep["stages"].items():
        assert list(s) == ["n", "ranked", "dealt", "set", "glued", "adverb", "interj", "closed", "p10", "p50", "p90", "first"]
        where = "w.stage_min IS NULL" if code == lo.STATS_NONE else "w.stage_min = :idx"
        assert s["first"] == sql_order(conn, where, {"idx": stage_to_index(code)} if code != lo.STATS_NONE else {}, limit=lo.REPORT_FIRST)
        assert s["n"] == conn.execute(f"SELECT COUNT(*) FROM words w WHERE {where}", {"idx": stage_to_index(code)} if code != lo.STATS_NONE else {}).fetchone()[0]
    acc = rep["acceptance"]
    assert list(acc) == ["closed_in_first_30", "xs_adverbs_first_30", "xs_months_positions", "zk_phrases_first_200", "longest_frq_null_run"]
    assert set(acc["closed_in_first_30"]) == set(STAGE_ORDER) == set(acc["longest_frq_null_run"])  # the five stage codes, never `none`
    xs_first = rep["stages"]["xs"]["first"][:30]
    closed = {str(r[0]) for r in conn.execute("SELECT lemma FROM words WHERE lemma IN ('be', 'is', 'a', 'an', 'some', 'aboard')")}
    assert acc["closed_in_first_30"]["xs"] == sum(1 for lemma in xs_first if lemma in closed) > 0  # the mini seed's 小学 list is 24 words incl. 4 grammar words
    assert acc["closed_in_first_30"]["zk"] == 0 and acc["xs_adverbs_first_30"] == 0 and acc["zk_phrases_first_200"] == 0
    assert acc["xs_months_positions"] == [None] * 12  # no calendar word in the mini seed
    assert acc["longest_frq_null_run"]["xs"] == 1  # email / ice cream are dealt apart
    assert json.loads(json.dumps(rep, ensure_ascii=False)) == rep
    assert lo.acceptance_closed("is", None, "inherit:be moe22:l2") and lo.acceptance_closed("was", "v:100", None) and lo.acceptance_closed("oh", "u:100", None)
    assert not lo.acceptance_closed("apple", "n:100", None) and not lo.closed_class("oh", "u:100", None)  # the measurement is wider than the policy
    assert len(lo.ACCEPTANCE_AUX_LEMMAS) == 25 and lo.CLOSED_LEMMAS - {"a", "an", "the"} < lo.ACCEPTANCE_AUX_LEMMAS  # the articles are caught by their pos


# ------------------------------------------------------------------------------------ review fixes (F-1 / F-2 / F2 / F3 / N-8)
def test_a_runtime_word_or_form_redeals_stage_phrases_without_flipping_the_gate(seeded):
    """F-1: R3 resolves phrase tokens against every row and every form, so a word a learner's lookup creates (`cream`, 课标外) or a
    form it writes (`ice` → water) makes `ice cream`'s token resolvable and re-deals the 小学 group's frequency-less rows (email and
    ice cream swap hosts). Those rows are stale — `stale_count`, the next recompute — but they are `Drift.dealt`, not `.policy`:
    `learn_rank_matches_policy` stays ok and the recompute reports them as `dealt drift` in the stats line."""
    conn = seeded
    assert lo.drift(conn) == lo.Drift(0, 0, 0)
    result = lo.rank_rows(*lo.load_inputs(conn))
    assert {rr.lemma for rr in result.rows.values() if rr.how == lo.HOW_DEALT and rr.stage_min == 1} == {"email", "ice cream"}
    before = stored(conn)
    # a runtime ECDICT word: no stage flags, a native rank, its own exact key at insert time (words._insert_word's shape)
    cream = {"lemma": "cream", "display": "cream", "kind": "word", "pos": "n:100", "frq": 20000, "source": "ecdict"}
    conn.execute("INSERT INTO words(lemma, display, kind, pos, frq, source, learn_rank) VALUES (:lemma, :display, :kind, :pos, :frq, :source, :learn_rank)", {**cream, "learn_rank": lo.best_effort_rank(cream)})
    d = lo.drift(conn)
    assert d == lo.Drift(policy=0, dealt=2, none=0) and d.stage == 2 == lo.stale_count(conn) and d.total == 2 == lo.stale_count(conn, stage_only=False)
    assert [violated for _, violated in lo.check_lines(conn)] == [False] * 4  # the gate does not flip on a learner's lookup
    assert "invariant learn_rank_matches_policy: ok" in dict(lo.check_lines(conn))
    r = lo.recompute(conn, now=T0)
    assert r.changed == 2 and r.stats["drift_dealt"] == 2 and r.stats["drift_none"] == 0
    after = stored(conn)
    assert {lemma for lemma in before if before[lemma] != after[lemma]} == {"email", "ice cream"}
    assert after["ice cream"] < after["email"] and after["ice cream"] % lo.RANK_SCALE == lo.SUB_DEALT == after["email"] % lo.RANK_SCALE  # the rarer resolvable token is dealt first
    assert lo.stats_line(conn).endswith(" · dealt drift 2 · 课标外 drift 0 · label-pos 0") and lo.drift(conn) == lo.Drift(0, 0, 0)
    # removing the donor moves them back — still dealt drift, still no violation
    conn.execute("DELETE FROM words WHERE lemma = 'cream'")
    assert lo.drift(conn) == lo.Drift(0, 2, 0) and lo.recompute(conn, now=T1).changed == 2 and stored(conn) == before
    # the form path: a lookup's add_form (`ice` → water) resolves the token through word_forms
    water_id = conn.execute("SELECT id FROM words WHERE lemma = 'water'").fetchone()[0]
    assert words.add_form(conn, "ice", water_id, "alt") is True
    assert lo.drift(conn) == lo.Drift(0, 2, 0) and [violated for _, violated in lo.check_lines(conn)] == [False] * 4
    assert lo.recompute(conn, now=T1).changed == 2 and stored(conn)["ice cream"] < stored(conn)["email"]
    # a hand edit of a natively ranked stage word is still the gate's business
    conn.execute("UPDATE words SET learn_rank = learn_rank + 1 WHERE lemma = 'apple'")
    assert lo.drift(conn) == lo.Drift(1, 0, 0) and dict(lo.check_lines(conn))["invariant learn_rank_matches_policy: 1 violation(s) (stored learn_rank of stage words differs from learn_order.rank_rows(); run `wd learn-order`)"] is True


def test_a_text_learn_rank_reads_as_null_and_is_rewritten(seeded):
    """F-2: INTEGER affinity keeps a hand-written 'abc' as TEXT; it must count as a changed row, never raise (wd check db, wd learn-order)."""
    conn = seeded
    conn.execute("UPDATE words SET learn_rank = 'abc' WHERE lemma = 'apple'")
    assert conn.execute("SELECT typeof(learn_rank) FROM words WHERE lemma = 'apple'").fetchone()[0] == "text"
    assert lo.drift(conn) == lo.Drift(1, 0, 0) and lo.stale_count(conn) == 1
    lines = dict(lo.check_lines(conn))
    assert lines["invariant learn_rank_matches_policy: 1 violation(s) (stored learn_rank of stage words differs from learn_order.rank_rows(); run `wd learn-order`)"] is True
    assert lines["invariant learn_rank_present: ok"] is False  # not NULL, so not "missing"
    assert lo.report(conn)["policy"] == lo.LEARN_ORDER_VERSION and lo.recompute(conn, dry_run=True, movers=True).changed == 1  # report / movers read it as NULL
    assert [r.lemma for r in lo.show(conn, "xs", 100) if r.learn_rank is None] == ["apple"]
    assert lo.recompute(conn, now=T0).changed == 1 and stored(conn)["apple"] == GOLDEN["apple"]
    assert conn.execute("SELECT typeof(learn_rank) FROM words WHERE lemma = 'apple'").fetchone()[0] == "integer"


def test_check_lines_report_a_raising_policy_as_query_failed(seeded, monkeypatch):
    """F2: a policy bug inside rank_rows is `query failed (RuntimeError: …)` on the policy line — reported, not counted, never raised."""
    conn = seeded

    def boom(rows, forms):
        raise RuntimeError("policy exploded")

    monkeypatch.setattr(lo, "rank_rows", boom)
    lines = lo.check_lines(conn)
    assert len(lines) == 4
    assert lines[0] == ("invariant learn_rank_present: ok", False) and lines[1] == ("invariant learn_order_current: ok", False)
    assert lines[2] == ("invariant learn_rank_matches_policy: query failed (RuntimeError: policy exploded)", False)
    assert lines[3] == ("invariant calendar_words_in_xs: ok", False)


def test_recompute_reads_the_stored_keys_under_the_write_lock(seeded, monkeypatch):
    """F3: a writer that commits while the policy runs (a `wd learn-order` next to a restart, a lookup's insert at 03:30) is seen by
    this pass — the stored keys are re-read inside BEGIN IMMEDIATE, so the row it NULLed is rewritten instead of stamped over."""
    conn = seeded
    real = lo.rank_rows

    def racing(rows, forms):
        conn.execute("UPDATE words SET learn_rank = NULL WHERE lemma = 'apple'")  # autocommit: no transaction is open during the compute
        assert not conn.in_transaction
        return real(rows, forms)

    monkeypatch.setattr(lo, "rank_rows", racing)
    r = lo.recompute(conn, now=T0)
    assert r.changed == 1 and stored(conn)["apple"] == GOLDEN["apple"] and not conn.in_transaction
    assert lo.unranked_stage_words(conn) == 0 and len(events(conn, lo.EVENT_RECOMPUTED)) == 1


def test_drift_counts_are_zero_right_after_a_policy_version_bump(seeded):
    """N-8: after a LEARN_ORDER_VERSION bump every key may move — that is the new policy, not drift: both counts stay 0 for that compare."""
    conn = seeded
    conn.execute("UPDATE words SET learn_rank = learn_rank + 1 WHERE lemma = 'bookshelf'")
    db.kv_set(conn, lo.KV_VERSION, "lo-0")
    r = lo.recompute(conn, now=T0)
    assert r.changed == 1 and r.stats["drift_none"] == 0 and r.stats["drift_dealt"] == 0 and kv(conn)[lo.KV_VERSION] == lo.LEARN_ORDER_VERSION
    conn.execute("UPDATE words SET learn_rank = learn_rank + 1 WHERE lemma = 'bookshelf'")
    assert lo.recompute(conn, now=T1).stats["drift_none"] == 1  # with the version current the same edit is drift
