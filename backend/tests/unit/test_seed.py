"""wd/seed.py — import_seed on the mini seed (WP1, PLAN §4.7): column mapping, kind derivation, the five stage flags and
stage_min (incl. the 课标外 NULL), cet6_star, word_forms guards / kind priority / seed aliases, idempotency (second run /
--force), user data and content pointers untouched, .jsonl.gz and .jsonl inputs sharing one content digest, atomicity,
kv.seed_version, --dry-run (zero writes, the plan), unknown stage codes counted, lemma mismatches counted, the in-transaction
learning-order recompute (docs/analysis/2026-11-06-learn-order/DESIGN.md §2.4 / §4.1 item 22: the group-ripple rule, the
event detail, a policy failure is fail-soft), and the `wd import-seed` command."""

from __future__ import annotations

import gzip
import json
import logging
import os
import shutil
import sqlite3
from pathlib import Path

import pytest

from wd import db, seed
from wd.schemas import STAGE_ORDER, stage_to_index
from wd.seed import SeedPlan, SeedStats, format_stats, import_seed, plan_import, seed_digest, seed_row, sha256_file
from wd.services import learn_order

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
MINI_SEED = FIXTURES / "mini_seed.jsonl"
UNKNOWN_CODE_SEED = FIXTURES / "seed_v2" / "unknown_code.jsonl"
BAD_GZIP_SEED = FIXTURES / "seed_v2" / "bad.jsonl.gz"
FORM_CODES = ("p", "d", "i", "3", "s", "r", "t")
N = 62  # records in the mini seed (60 v1 words + the `color` variant row + the stageless `bookshelf`)
XS = stage_to_index("xs")


def records() -> list[dict]:
    return [json.loads(line) for line in MINI_SEED.read_text(encoding="utf-8").splitlines() if line.strip()]


def q(conn: sqlite3.Connection, sql: str, *params):
    return conn.execute(sql, params).fetchone()[0]


def word(conn: sqlite3.Connection, lemma: str) -> dict:
    return db.row_to_dict(conn.execute("SELECT * FROM words WHERE lemma = ?", (lemma,)).fetchone())


def events(conn: sqlite3.Connection) -> list[tuple]:
    """system_events without the migration traces every migrated database carries (0011, test_db.py)."""
    return [tuple(r) for r in conn.execute("SELECT kind, detail_json FROM system_events WHERE kind != 'migration' ORDER BY id")]


def dump(conn: sqlite3.Connection) -> dict:
    return {
        "words": [tuple(r) for r in conn.execute("SELECT * FROM words ORDER BY id")],
        "forms": [tuple(r) for r in conn.execute("SELECT * FROM word_forms ORDER BY form, word_id")],
        "kv": [tuple(r) for r in conn.execute("SELECT key, value FROM kv WHERE key LIKE 'seed%' ORDER BY key")],
        "events": events(conn),
    }


def write_seed(path: Path, recs: list[dict]) -> Path:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs), encoding="utf-8")
    return path


def expected_forms(lemmas: set[str]) -> dict[tuple[str, str], str]:
    """Independent re-derivation of the (form, lemma) → kind table from the fixture (same guards, same priority; the
    record's aliases[] become 'alias' rows unless an exchange code already claims the pair)."""
    out: dict[tuple[str, str], str] = {}
    for rec in records():
        lemma = rec["word"].lower()
        for code in FORM_CODES:
            raw = rec.get("exchange", {}).get(code)
            if raw is None:
                continue
            form = " ".join(raw.split()).lower()
            if not form or form in lemmas:
                continue
            out.setdefault((form, lemma), code)
        for alias in rec.get("aliases", []):
            form = " ".join(alias.split()).lower()
            if form and form != lemma and form not in lemmas:
                out.setdefault((form, lemma), "alias")
    return out


# ------------------------------------------------------------------------------------------ basics
def test_import_counts_and_bookkeeping(conn):
    stats = import_seed(conn, str(MINI_SEED))
    assert isinstance(stats, SeedStats)
    assert (stats.records, stats.inserted, stats.updated, stats.skipped_records, stats.up_to_date, stats.dry_run) == (N, N, 0, 0, False, False)
    assert stats.sha256 == sha256_file(MINI_SEED) and stats.path == str(MINI_SEED) and stats.seconds >= 0
    assert stats.content_sha256 == seed_digest(MINI_SEED) == sha256_file(MINI_SEED)  # a plain file: content digest == file digest
    assert (stats.unknown_stage_codes, stats.lemma_mismatch, stats.duplicate_lemmas) == (0, 0, 0)
    assert stats.stageless_records == 1 and stats.aliases == 1  # bookshelf; TV → t.v.
    assert isinstance(stats.plan, SeedPlan) and stats.plan.inserted == N and stats.plan.orphans == []
    assert q(conn, "SELECT COUNT(*) FROM words") == N
    assert q(conn, "SELECT COUNT(*) FROM words WHERE source='seed' AND is_public=1 AND is_valid_english=1 AND safe_for_sharing=1") == N
    assert q(conn, "SELECT COUNT(*) FROM words WHERE created_by_user_id IS NOT NULL OR merged_into_word_id IS NOT NULL OR difficulty IS NOT NULL") == 0
    assert q(conn, "SELECT COUNT(*) FROM words WHERE content_state != 'none' OR image_state != 'none' OR active_content_id IS NOT NULL") == 0
    assert db.kv_get(conn, "seed_version") == stats.content_sha256
    assert db.kv_get(conn, "seed_imported_at") is not None
    ev = events(conn)
    assert len(ev) == 1 and ev[0][0] == "seed_imported"
    detail = json.loads(ev[0][1])
    assert detail["records"] == N and detail["inserted"] == N and detail["sha256"] == stats.sha256 and detail["force"] is False
    assert detail["content_sha256"] == stats.content_sha256 and detail["unknown_stage_codes"] == 0 and detail["lemma_mismatch"] == 0
    assert detail["aliases"] == 1 and detail["stageless"] == 1 and detail["orphans"] == 0
    assert set(detail["flag_added"]) == set(detail["flag_removed"]) == set(STAGE_ORDER)
    assert f"imported {N} seed records" in format_stats(stats) and "1 aliases" in format_stats(stats)


def test_kind_derivation_and_display_casing(conn):
    import_seed(conn, str(MINI_SEED))
    assert (word(conn, "a.m.")["display"], word(conn, "a.m.")["kind"]) == ("a.m.", "abbreviation")
    assert (word(conn, "tv")["display"], word(conn, "tv")["kind"]) == ("TV", "abbreviation")
    assert (word(conn, "aids")["display"], word(conn, "aids")["kind"]) == ("AIDS", "abbreviation")
    assert q(conn, "SELECT COUNT(*) FROM words WHERE lemma IN ('tv','aids') AND kind='abbreviation'") == 2
    assert (word(conn, "china")["display"], word(conn, "china")["kind"]) == ("China", "proper_noun")
    assert word(conn, "ice cream")["kind"] == "phrase" and word(conn, "ought to")["kind"] == "phrase"
    assert q(conn, "SELECT COUNT(*) FROM words WHERE kind='phrase'") == 2
    assert word(conn, "abandon")["kind"] == "word" and word(conn, "email")["kind"] == "word" and word(conn, "color")["kind"] == "word"
    assert word(conn, "i") is None  # not in the mini seed (kept out so 'I' cannot mask a casing bug)
    assert q(conn, "SELECT COUNT(*) FROM words WHERE lemma != lower(lemma)") == 0


def test_stage_flags_stage_min_and_cet6_star(conn):
    """Flags follow the record's stage codes; stage_min is the lowest flagged stage's index (schemas.stage_to_index), never a
    hard-coded number — 0011 renumbered the index when 小学 became stage 1."""
    import_seed(conn, str(MINI_SEED))
    ab = word(conn, "abandon")  # stages gk, cet4, cet6
    assert (ab["stage_xs"], ab["stage_zk"], ab["stage_gk"], ab["stage_cet4"], ab["stage_cet6"], ab["stage_min"]) == (0, 0, 1, 1, 1, stage_to_index("gk"))
    assert word(conn, "absolutely")["stage_min"] == stage_to_index("cet4")  # cet4 only
    assert word(conn, "email")["stage_min"] == stage_to_index("xs")  # xs + zk + cet6 → lowest wins
    assert word(conn, "ought to")["stage_min"] == stage_to_index("cet6")
    assert word(conn, "a")["stage_min"] == stage_to_index("xs") and word(conn, "a")["stage_cet6"] == 0  # xs + zk + … (the PLAN §6 S2 小学 list)
    cn = word(conn, "china")
    assert (cn["stage_xs"], cn["stage_zk"], cn["stage_min"]) == (1, 1, XS)
    assert q(conn, "SELECT COUNT(*) FROM words WHERE stage_min IS NULL") == 1  # bookshelf: outside every official list
    assert q(conn, "SELECT COUNT(*) FROM words WHERE cet6_star=1") == 3
    assert {r[0] for r in conn.execute("SELECT lemma FROM words WHERE cet6_star=1")} == {"abnormal", "abrupt", "absurd"}
    recs = records()
    for s in STAGE_ORDER:
        assert q(conn, f"SELECT COUNT(*) FROM words WHERE stage_{s}=1") == sum(s in r["stages"] for r in recs), s
    assert q(conn, "SELECT COUNT(*) FROM words WHERE stage_xs=1 AND stage_zk=0") == 0  # xs ⊆ zk by construction
    # the stored stage_min is consistent with the flags for every row (the wd check db invariant, PLAN §2.1)
    case = " ".join(f"WHEN stage_{s}=1 THEN {stage_to_index(s)}" for s in STAGE_ORDER)
    assert q(conn, f"SELECT COUNT(*) FROM words WHERE stage_min IS NOT (CASE {case} END)") == 0


def test_stage_xs_record_gets_stage_min_1(conn):
    r = seed_row({"word": "pen", "stages": ["zk", "xs"]}, "2026-10-14T08:00:00Z")
    assert r is not None and (r["stage_xs"], r["stage_zk"], r["stage_gk"], r["stage_min"]) == (1, 1, 0, XS) and XS == 1
    import_seed(conn, str(MINI_SEED))
    assert q(conn, "SELECT COUNT(*) FROM words WHERE stage_xs=1 AND stage_min=1") == q(conn, "SELECT COUNT(*) FROM words WHERE stage_xs=1") > 0
    assert word(conn, "is")["stage_min"] == XS and "inherit:be" in word(conn, "is")["sources"].split()


def test_empty_stages_gives_null_stage_min(conn):
    r = seed_row({"word": "bungalow", "stages": []}, "2026-10-14T08:00:00Z")
    assert r is not None and r["stage_min"] is None and all(r[f"stage_{s}"] == 0 for s in STAGE_ORDER)
    stats = import_seed(conn, str(MINI_SEED))
    shelf = word(conn, "bookshelf")
    assert shelf["stage_min"] is None and all(shelf[f"stage_{s}"] == 0 for s in STAGE_ORDER)
    assert (shelf["source"], shelf["is_public"], shelf["is_valid_english"], shelf["sources"]) == ("seed", 1, 1, "ecdict legacy:gk")  # kept, visible, not deleted
    assert stats.stageless_records == 1 and stats.plan is not None and stats.plan.stageless == 1


def test_dictionary_column_mapping(conn):
    import_seed(conn, str(MINI_SEED))
    a = word(conn, "a")
    assert a["translation"] == "第一个字母 A; 一个; 第一的\nart. [计] 累加器, 加法器, 地址, 振幅, 模拟, 区域, 面积, 汇编, 组件, 异步"
    assert a["definition"].startswith("n. the 1st letter") and "\n" in a["definition"]
    assert (a["pos"], a["collins"], a["oxford"], a["bnc"], a["frq"], a["ecdict_id"]) == ("a:99/t:1", 5, 1, 5, 5, 7909)
    assert json.loads(a["exchange_json"]) == {"s": "some"}
    assert a["sources"] == "cet4 ecdict hs20:0 hs25:0 legacy:zk moe22:l3" and a["exam_tags"] is None  # PLAN §4.4 tokens, sorted
    am = word(conn, "a.m.")
    assert am["phonetic"] is None and am["bnc"] is None and am["frq"] is None and am["exchange_json"] is None and am["pos"] is None
    ability = word(conn, "ability")
    assert ability["exam_tags"] == "ky toefl ielts" and ability["phonetic"] == "ə'biliti"
    assert ability["sources"] == "cet4 cet46 ecdict hs20:0 hs25:0 legacy:gk legacy:zk moe22:l3 shmeea20"
    assert word(conn, "abnormal")["cet6_star"] == 1
    assert q(conn, "SELECT COUNT(*) FROM words WHERE sources LIKE '% zk%' OR sources LIKE 'zk %' OR sources LIKE '% gk%' OR sources LIKE 'gk %'") == 0  # the bare zk/gk tokens are gone
    color = word(conn, "color")  # a variant record: variant_of / seed_v are builder bookkeeping the importer ignores
    assert (color["display"], color["ecdict_id"], color["frq"], color["stage_min"]) == ("color", 600656, 697, stage_to_index("zk"))
    assert "variant_of" not in color and json.loads(color["exchange_json"])["s"] == "colors"


# -------------------------------------------------------------------------------------- word_forms
def test_word_forms_guards_and_ambiguity(conn):
    stats = import_seed(conn, str(MINI_SEED))
    lemmas = {r[0] for r in conn.execute("SELECT lemma FROM words")}
    rows = {(r[0], r[1]): r[2] for r in conn.execute("SELECT wf.form, w.lemma, wf.kind FROM word_forms wf JOIN words w ON w.id = wf.word_id")}
    assert rows == expected_forms(lemmas)
    assert stats.forms == len(rows) > 0
    assert q(conn, "SELECT COUNT(*) FROM word_forms WHERE form=''") == 0
    assert q(conn, "SELECT COUNT(*) FROM word_forms wf JOIN words w ON w.lemma = wf.form") == 0  # headword guard
    for headword_form in ("better", "running", "is", "some", "clothes", "data"):
        assert q(conn, "SELECT COUNT(*) FROM word_forms WHERE form=?", headword_form) == 0
    for pointer in ("aid", "clothe", "datum", "an"):  # exchange codes 0/1 are lemma pointers, never forms
        assert q(conn, "SELECT COUNT(*) FROM word_forms WHERE form=?", pointer) == 0
    assert q(conn, "SELECT COUNT(DISTINCT word_id) FROM word_forms WHERE form='bases'") == 2
    assert {r[0] for r in conn.execute("SELECT w.lemma FROM word_forms wf JOIN words w ON w.id=wf.word_id WHERE wf.form='axes'")} == {"ax", "axe", "axis"}
    assert q(conn, "SELECT COUNT(*) FROM word_forms WHERE kind NOT IN ('p','d','i','3','s','r','t','alias')") == 0
    assert rows[("t.v.", "tv")] == "alias" and q(conn, "SELECT COUNT(*) FROM word_forms WHERE kind='alias'") == stats.aliases == 1
    assert q(conn, "SELECT COUNT(*) FROM word_forms WHERE form LIKE '% %'") == 1  # 'ice creams'
    assert stats.forms_skipped_empty == 0 and stats.forms_skipped_headword > 0


def test_word_forms_kind_priority_for_pairs_with_several_codes(conn):
    import_seed(conn, str(MINI_SEED))
    kind = lambda form, lemma: q(conn, "SELECT wf.kind FROM word_forms wf JOIN words w ON w.id=wf.word_id WHERE wf.form=? AND w.lemma=?", form, lemma)
    assert kind("based", "base") == "p"  # p before d
    assert kind("bases", "base") == "3"  # 3 before s
    assert kind("bases", "basis") == "s"
    assert kind("goes", "go") == "3"
    assert kind("went", "go") == "p" and kind("gone", "go") == "d" and kind("going", "go") == "i"
    assert kind("happier", "happy") == "r" and kind("happiest", "happy") == "t"


def test_alias_rows_written_with_headword_guard(conn, tmp_path):
    """aliases[] → word_forms(kind='alias') under the same guards as exchange forms: never a headword, never the record's own
    lemma, an exchange code wins the pair, an existing `alt` row keeps the pair; aliases are rebuilt on every import."""
    import_seed(conn, str(MINI_SEED))
    tv = word(conn, "tv")["id"]
    assert [tuple(r) for r in conn.execute("SELECT form, word_id, kind FROM word_forms WHERE kind='alias'")] == [("t.v.", tv, "alias")]
    recs = records()
    for r in recs:
        if r["word"] == "TV":
            r["aliases"] = ["t.v.", "TV", "cat", " Tele  Vision ", "tvs", "", 7]  # own lemma / headword / exchange-claimed / blank / non-string
        if r["word"] == "China":
            r["aliases"] = ["the PRC"]
    modified = write_seed(tmp_path / "aliases.jsonl", recs)
    conn.execute("INSERT INTO word_forms(form, word_id, kind) VALUES ('tele vision', ?, 'alt')", (tv,))  # a lookup-written alt row on the same pair
    stats = import_seed(conn, str(modified))
    rows = {(r[0], r[1]): r[2] for r in conn.execute("SELECT form, word_id, kind FROM word_forms WHERE word_id IN (?, ?)", (tv, word(conn, "china")["id"]))}
    assert rows[("t.v.", tv)] == "alias" and rows[("the prc", word(conn, "china")["id"])] == "alias"
    assert rows[("tvs", tv)] == "s"  # the exchange code claims the pair
    assert rows[("tele vision", tv)] == "alt"  # the alt row survived; no second row for the pair
    assert ("cat", tv) not in rows and ("tv", tv) not in rows and ("", tv) not in rows
    assert q(conn, "SELECT COUNT(*) FROM word_forms wf JOIN words w ON w.lemma = wf.form") == 0
    assert stats.aliases == 2 and stats.forms_skipped_headword > 0
    again = import_seed(conn, str(modified), force=True)
    assert again.aliases == 2 and q(conn, "SELECT COUNT(*) FROM word_forms WHERE kind='alias'") == 2  # rebuilt, not duplicated


# ---------------------------------------------------------------------------------------- idempotency
def test_second_run_is_a_noop_and_force_changes_nothing(conn):
    import_seed(conn, str(MINI_SEED))
    before = dump(conn)
    again = import_seed(conn, str(MINI_SEED))
    assert again.up_to_date is True and again.records == 0 and again.inserted == 0 and again.plan is None
    assert "seed up to date" in format_stats(again)
    assert dump(conn) == before
    assert len(events(conn)) == 1
    forced = import_seed(conn, str(MINI_SEED), force=True)
    assert forced.up_to_date is False and (forced.records, forced.inserted, forced.updated) == (N, 0, 0)
    assert forced.plan is not None and (forced.plan.inserted, forced.plan.updated, forced.plan.unchanged) == (0, 0, N)
    assert forced.forms == len(before["forms"])
    after = dump(conn)
    assert after["words"] == before["words"]  # incl. updated_at: unchanged rows are not rewritten
    assert after["forms"] == before["forms"]
    assert dict(after["kv"])["seed_version"] == dict(before["kv"])["seed_version"]
    assert len(events(conn)) == 2


def test_never_touches_user_data_content_pointers_or_alt_forms(conn):
    import_seed(conn, str(MINI_SEED))
    ab = word(conn, "abandon")
    user = conn.execute("INSERT INTO users(username, password_hash) VALUES ('alice','x')").lastrowid
    conn.execute("UPDATE words SET difficulty=3, content_state='ready', active_content_id=42, image_state='queued', active_image_id=7, updated_at='2020-01-01T00:00:00Z' WHERE id=?", (ab["id"],))
    conn.execute("INSERT INTO user_words(user_id, word_id, state, origin, note) VALUES (?, ?, 'learning', 'browse', 'my note')", (user, ab["id"]))
    conn.execute("INSERT INTO word_forms(form, word_id, kind) VALUES ('abandonned', ?, 'alt')", (ab["id"],))
    conn.execute("DELETE FROM word_forms WHERE form='abandoning'")  # a damaged non-alt form is rebuilt
    stats = import_seed(conn, str(MINI_SEED), force=True)
    after = word(conn, "abandon")
    assert (after["difficulty"], after["content_state"], after["active_content_id"], after["image_state"], after["active_image_id"]) == (3, "ready", 42, "queued", 7)
    assert after["updated_at"] == "2020-01-01T00:00:00Z"  # unchanged dictionary data → the row is not rewritten
    assert stats.updated == 0
    uw = conn.execute("SELECT state, note FROM user_words WHERE word_id=?", (ab["id"],)).fetchone()
    assert tuple(uw) == ("learning", "my note")
    assert q(conn, "SELECT COUNT(*) FROM word_forms WHERE form='abandonned' AND kind='alt'") == 1
    assert q(conn, "SELECT COUNT(*) FROM word_forms WHERE form='abandoning'") == 1


def test_changed_record_updates_only_that_row(conn, tmp_path):
    import_seed(conn, str(MINI_SEED))
    apple_before = word(conn, "apple")
    recs = records()
    for r in recs:
        if r["word"] == "abandon":
            r["translation"] = ["vt. 新释义"]
            r["stages"] = ["zk", "gk", "cet4", "cet6"]
            r["cet6_star"] = True
    modified = write_seed(tmp_path / "modified.jsonl", recs)
    stats = import_seed(conn, str(modified))
    assert (stats.inserted, stats.updated, stats.up_to_date) == (0, 1, False)
    assert stats.plan is not None and (stats.plan.updated, stats.plan.unchanged, stats.plan.flag_added["zk"], stats.plan.min_lowered) == (1, N - 1, 1, 1)
    ab = word(conn, "abandon")
    assert ab["translation"] == "vt. 新释义" and ab["stage_zk"] == 1 and ab["stage_min"] == stage_to_index("zk") and ab["cet6_star"] == 1
    assert word(conn, "apple") == apple_before
    assert db.kv_get(conn, "seed_version") == seed_digest(modified) != seed_digest(MINI_SEED)


def test_changed_record_may_rerank_only_dealt_words_of_its_stage_groups(conn, tmp_path):
    """The group-ripple rule (DESIGN §2.1 / §2.4): a record change re-ranks at most the non-native (dealt / set / adverb /
    interjection / glued) rows of the (stage_min, closed) groups it touches — a natively ranked word's key depends on no other
    row, so `apple` is unchanged INCLUDING learn_rank and `updated_at` moves only for the changed record itself."""

    def ranks() -> dict[str, int | None]:
        return {str(r[0]): r[1] for r in conn.execute("SELECT lemma, learn_rank FROM words")}

    def stamps() -> dict[str, str]:
        return {str(r[0]): str(r[1]) for r in conn.execute("SELECT lemma, updated_at FROM words")}

    def non_native_of(groups: set[tuple[int | None, bool]]) -> set[str]:
        result = learn_order.rank_rows(*learn_order.load_inputs(conn))
        return {rr.lemma for rr in result.rows.values() if (rr.stage_min, rr.closed) in groups and rr.how != learn_order.HOW_NATIVE}

    import_seed(conn, str(MINI_SEED))
    conn.execute("UPDATE words SET updated_at = '2020-01-01T00:00:00Z'")  # so a rewritten row is visible whatever the clock's second
    zk, gk = stage_to_index("zk"), stage_to_index("gk")
    assert word(conn, "abandon")["stage_min"] == gk
    before_ranks, before_stamps, apple_before = ranks(), stamps(), word(conn, "apple")
    # (1) the DESIGN's modification: abandon joins 初中 (gk → zk) — the key encodes no stage, so abandon's own key stays
    recs = records()
    for r in recs:
        if r["word"] == "abandon":
            r["translation"] = ["vt. 新释义"]
            r["stages"] = ["zk", "gk", "cet4", "cet6"]
            r["cet6_star"] = True
    stats = import_seed(conn, str(write_seed(tmp_path / "modified.jsonl", recs)))
    assert (stats.inserted, stats.updated, stats.up_to_date) == (0, 1, False)
    after_ranks, after_stamps = ranks(), stamps()
    changed = {lemma for lemma in before_ranks if before_ranks[lemma] != after_ranks[lemma]}
    assert word(conn, "apple") == apple_before  # unchanged including learn_rank
    assert {lemma for lemma in before_stamps if before_stamps[lemma] != after_stamps[lemma]} == {"abandon"}
    assert after_ranks["abandon"] == before_ranks["abandon"] == learn_order.pack(False, word(conn, "abandon")["frq"], learn_order.SUB_NATIVE)
    assert changed <= non_native_of({(zk, False), (gk, False)}) and stats.learn_rank_changed == len(changed)
    assert json.loads(events(conn)[-1][1])["learn_order"] == {"version": learn_order.LEARN_ORDER_VERSION, "changed": len(changed)}
    # (2) a host change that provably ripples: abandon takes a 初中-sized frequency and becomes an earlier 初中 host, so the dealt
    # 初中 word `a.m.` (frequency-less) lands on another host — nothing outside the touched group moves, updated_at only for abandon
    conn.execute("UPDATE words SET updated_at = '2020-01-01T00:00:00Z'")
    before_ranks, before_stamps = ranks(), stamps()
    for r in recs:
        if r["word"] == "abandon":
            r["frq"] = 400
    stats = import_seed(conn, str(write_seed(tmp_path / "modified2.jsonl", recs)))
    assert (stats.inserted, stats.updated) == (0, 1)
    after_ranks, after_stamps = ranks(), stamps()
    changed = {lemma for lemma in before_ranks if before_ranks[lemma] != after_ranks[lemma]}
    assert "abandon" in changed and "a.m." in changed and after_ranks["abandon"] == learn_order.pack(False, 400, 0)
    assert after_ranks["a.m."] % learn_order.RANK_SCALE == learn_order.SUB_DEALT and after_ranks["a.m."] != before_ranks["a.m."]
    assert changed - {"abandon"} <= non_native_of({(zk, False)}) and stats.learn_rank_changed == len(changed)
    assert {lemma for lemma in before_stamps if before_stamps[lemma] != after_stamps[lemma]} == {"abandon"}
    assert word(conn, "apple") == apple_before
    assert learn_order.stale_count(conn, stage_only=False) == 0  # the stored column equals the policy after every import


def test_seed_import_event_carries_learn_order_detail(conn):
    stats = import_seed(conn, str(MINI_SEED))
    assert stats.learn_rank_changed == N  # the first import ranks every row
    detail = json.loads(events(conn)[-1][1])
    assert detail["learn_order"] == {"version": learn_order.LEARN_ORDER_VERSION, "changed": N}
    assert events(conn) == [("seed_imported", events(conn)[0][1])]  # the import path writes no learn_order_recomputed event
    assert f"{N} learn ranks changed" in format_stats(stats)
    assert db.kv_get(conn, learn_order.KV_SEED) == db.kv_get(conn, "seed_version") == stats.content_sha256
    assert db.kv_get(conn, learn_order.KV_VERSION) == learn_order.LEARN_ORDER_VERSION
    assert q(conn, "SELECT COUNT(*) FROM words WHERE learn_rank IS NULL") == 0
    forced = import_seed(conn, str(MINI_SEED), force=True)
    assert forced.learn_rank_changed == 0 and json.loads(events(conn)[-1][1])["learn_order"] == {"version": learn_order.LEARN_ORDER_VERSION, "changed": 0}
    assert "0 learn ranks changed" in format_stats(forced)


def test_policy_failure_does_not_roll_the_import_back(conn, monkeypatch, caplog):
    """A policy exception is fail-soft: the import commits (words, forms, kv.seed_version), ranks stay as they were (NULL on a
    first import), one learn_order_failed event before the seed_imported event; a database error in the write phase rolls
    the whole import back like any other statement."""

    def boom(rows, forms):
        raise RuntimeError("policy exploded")

    monkeypatch.setattr(learn_order, "rank_rows", boom)
    caplog.set_level(logging.ERROR, logger="wd.seed")
    stats = import_seed(conn, str(MINI_SEED))
    assert (stats.records, stats.inserted, stats.learn_rank_changed) == (N, N, 0) and not conn.in_transaction
    assert q(conn, "SELECT COUNT(*) FROM words") == N and db.kv_get(conn, "seed_version") == stats.content_sha256
    assert q(conn, "SELECT COUNT(*) FROM words WHERE learn_rank IS NOT NULL") == 0
    assert [kind for kind, _ in events(conn)] == ["learn_order_failed", "seed_imported"]
    assert json.loads(events(conn)[0][1]) == {"trigger": "seed_import", "error": "RuntimeError: policy exploded"}
    assert json.loads(events(conn)[1][1])["learn_order"] == {"version": learn_order.LEARN_ORDER_VERSION, "changed": None}
    assert db.kv_get(conn, learn_order.KV_VERSION) is None  # nothing computed, nothing stamped
    assert any(r.levelno == logging.ERROR and getattr(r, "event", None) == "learn_order_failed" and r.exc_info for r in caplog.records)
    assert "0 learn ranks changed" in format_stats(stats)
    monkeypatch.undo()
    assert import_seed(conn, str(MINI_SEED), force=True).learn_rank_changed == N  # the next import fills the column
    # a database fault in the write phase (an UPDATE of learn_rank is refused) propagates and rolls the import back
    conn.execute("UPDATE words SET learn_rank = NULL WHERE lemma = 'apple'")  # so the next import has a rank to write
    conn.execute("CREATE TRIGGER refuse_rank BEFORE UPDATE OF learn_rank ON words BEGIN SELECT RAISE(ABORT, 'no rank writes'); END")
    before = dump(conn)
    with pytest.raises(sqlite3.IntegrityError, match="no rank writes"):
        import_seed(conn, str(MINI_SEED), force=True)
    assert not conn.in_transaction and dump(conn) == before  # the import rolled back with the fault
    conn.execute("DROP TRIGGER refuse_rank")


def test_provisional_user_word_is_promoted_to_a_seed_word(conn):
    user = conn.execute("INSERT INTO users(username, password_hash) VALUES ('alice','x')").lastrowid
    conn.execute("INSERT INTO words(lemma, display, kind, source, is_public, created_by_user_id) VALUES ('apple','Apple','proper_noun','user',0,?)", (user,))
    stats = import_seed(conn, str(MINI_SEED))
    assert (stats.inserted, stats.updated) == (N - 1, 1)
    assert stats.plan is not None and (stats.plan.inserted, stats.plan.updated) == (N - 1, 1)  # the plan predicted the same
    apple = word(conn, "apple")
    assert (apple["source"], apple["is_public"], apple["is_valid_english"], apple["safe_for_sharing"], apple["display"], apple["kind"]) == ("seed", 1, 1, 1, "apple", "word")
    assert apple["created_by_user_id"] == user  # provenance of the original row is kept; the data is now the dictionary's
    assert q(conn, "SELECT COUNT(*) FROM words WHERE lemma='apple'") == 1


def test_merged_seed_headword_is_restored(conn):
    import_seed(conn, str(MINI_SEED))
    go, went = word(conn, "go")["id"], word(conn, "run")["id"]
    conn.execute("UPDATE words SET merged_into_word_id=? WHERE id=?", (go, went))
    stats = import_seed(conn, str(MINI_SEED), force=True)
    assert stats.updated == 1 and word(conn, "run")["merged_into_word_id"] is None


# -------------------------------------------------------------------------------------- dry run / plan
def test_dry_run_writes_nothing(conn):
    before = dump(conn)
    changes = conn.total_changes
    stats = import_seed(conn, str(MINI_SEED), dry_run=True)
    assert stats.dry_run is True and stats.up_to_date is False and stats.records == N
    assert stats.plan is not None and (stats.plan.inserted, stats.plan.updated, stats.plan.unchanged, stats.plan.stageless) == (N, 0, 0, 1)
    assert stats.plan.orphans == [] and stats.plan.matrix[f"new→{XS}"] == sum(1 for r in records() if "xs" in r["stages"]) and stats.plan.matrix["new→none"] == 1
    assert dump(conn) == before and conn.total_changes == changes and not conn.in_transaction
    assert db.kv_get(conn, "seed_version") is None and q(conn, "SELECT COUNT(*) FROM words") == 0 and events(conn) == []
    assert q(conn, "SELECT COUNT(*) FROM kv WHERE key LIKE 'learn_order.%'") == 0  # the learning order is not computed either
    text = format_stats(stats)
    assert text.startswith("dry run: insert 62 / update 0 / unchanged 0; orphans 0;") and f"stage_min new→{XS}" in text and "stageless 1" in text
    # after a real import the dry run of the same file says "up to date" and shows that --force would rewrite nothing
    import_seed(conn, str(MINI_SEED))
    conn.execute("UPDATE words SET learn_rank = NULL WHERE lemma = 'go'")  # a dry run must not touch the learning order either
    snapshot = dump(conn)
    learn_kv = [tuple(r) for r in conn.execute("SELECT key, value FROM kv WHERE key LIKE 'learn_order.%' ORDER BY key")]
    again = import_seed(conn, str(MINI_SEED), dry_run=True)
    assert again.up_to_date is True and again.plan is not None and (again.plan.inserted, again.plan.updated, again.plan.unchanged) == (0, 0, N)
    assert "seed up to date" in format_stats(again) and "--force would insert 0 / update 0 / unchanged 62" in format_stats(again)
    assert dump(conn) == snapshot and again.learn_rank_changed == 0  # dump() carries every words column, learn_rank included
    assert [tuple(r) for r in conn.execute("SELECT key, value FROM kv WHERE key LIKE 'learn_order.%' ORDER BY key")] == learn_kv
    assert q(conn, "SELECT learn_rank FROM words WHERE lemma = 'go'") is None


def test_dry_run_reports_orphans_flag_changes_and_matrix(conn, tmp_path):
    """The plan is a report, never a gate: a seed that drops a word, removes flags or raises stage_min is described and —
    on the real import — applied; the orphaned seed row is kept (the seed never deletes)."""
    import_seed(conn, str(MINI_SEED))
    gk, cet4, cet6 = stage_to_index("gk"), stage_to_index("cet4"), stage_to_index("cet6")
    recs = [r for r in records() if r["word"] != "axe"]  # axe disappears → orphan
    for r in recs:
        if r["word"] == "abandon":
            r["stages"] = ["zk", "gk", "cet4"]  # cet6 removed, zk added → stage_min gk → zk (lowered)
        if r["word"] == "absolutely":
            r["stages"] = ["cet6"]  # cet4 → cet6: flag flips, stage_min raised
        if r["word"] == "aboard":
            r["stages"] = []  # leaves every list → stage_min NULL
    recs.append({"word": "zebra", "lemma": "zebra", "stages": ["xs", "zk"], "translation": ["n. 斑马"], "sources": ["moe22:l2", "moe22:l3"], "seed_v": 2})
    modified = write_seed(tmp_path / "relabelled.jsonl", recs)
    before = dump(conn)
    stats = import_seed(conn, str(modified), dry_run=True)
    p = stats.plan
    assert p is not None and dump(conn) == before
    assert (p.inserted, p.updated, p.unchanged, p.orphans) == (1, 3, N - 4, ["axe"])
    assert p.flag_removed == {"xs": 0, "zk": 0, "gk": 1, "cet4": 2, "cet6": 1} and p.flag_added == {"xs": 0, "zk": 1, "gk": 0, "cet4": 0, "cet6": 1}
    assert (p.min_lowered, p.min_raised, p.stageless) == (1, 1, 2)  # abandon lowered, absolutely raised; aboard + bookshelf stageless
    assert p.matrix[f"{gk}→{stage_to_index('zk')}"] == 1 and p.matrix[f"{cet4}→{cet6}"] == 1 and p.matrix[f"{gk}→none"] == 1 and p.matrix[f"new→{XS}"] == 1
    assert p.matrix["none→none"] == 1 and sum(p.matrix.values()) == N  # bookshelf stays stageless; every record lands in one cell
    assert [s[0] for s in p.samples] == ["abandon", "aboard", "absolutely"]
    assert ("abandon", ["gk", "cet4", "cet6"], ["zk", "gk", "cet4"]) in p.samples
    text = format_stats(stats)
    assert "insert 1 / update 3 / unchanged 58; orphans 1; flags +{zk:1, cet6:1} −{gk:1, cet4:2, cet6:1}; stage_min lowered 1 / raised 1; stageless 2" in text
    assert "orphans (seed rows not in the file, kept): axe" in text
    real = import_seed(conn, str(modified))
    assert (real.inserted, real.updated) == (1, 3) and real.plan is not None and real.plan.orphans == ["axe"]
    assert word(conn, "axe") is not None and word(conn, "axe")["source"] == "seed"  # never deleted
    assert word(conn, "aboard")["stage_min"] is None and word(conn, "zebra")["stage_min"] == XS
    assert json.loads(events(conn)[-1][1])["orphans"] == 1


def test_plan_import_compares_like_the_upsert(conn):
    import_seed(conn, str(MINI_SEED))
    now = "2026-10-14T08:00:00Z"
    rows = {r["lemma"]: r for r in (seed_row(rec, now) for rec in records()) if r is not None}
    plan = plan_import(conn, rows)
    assert (plan.inserted, plan.updated, plan.unchanged) == (0, 0, N)
    conn.execute("UPDATE words SET is_public = 0 WHERE lemma = 'apple'")  # a trust flag alone fires the UPSERT → counted as an update
    conn.execute("UPDATE words SET frq = 1 WHERE lemma = 'bank'")
    conn.execute("UPDATE words SET difficulty = 2, content_state = 'ready' WHERE lemma = 'cat'")  # columns the seed never touches: unchanged
    plan = plan_import(conn, rows)
    assert (plan.inserted, plan.updated, plan.unchanged) == (0, 2, N - 2)
    assert plan.flag_added == {s: 0 for s in STAGE_ORDER} and plan.flag_removed == {s: 0 for s in STAGE_ORDER}


# ------------------------------------------------------------------------------------- stage codes / lemma
def test_unknown_stage_code_is_counted_not_dropped_silently(conn, caplog):
    """A code outside STAGE_ORDER (a seed newer than the server) is ignored per record and surfaced three ways: the stats, one
    WARNING naming the codes, and the seed_imported event — never a refusal (PLAN R-8)."""
    caplog.set_level(logging.WARNING, logger="wd.seed")
    stats = import_seed(conn, str(UNKNOWN_CODE_SEED))
    assert (stats.records, stats.inserted, stats.unknown_stage_codes, stats.stageless_records) == (2, 2, 2, 1)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING and "unknown stage code" in r.getMessage()]
    assert len(warnings) == 1 and "cet9" in warnings[0].getMessage() and "xs/zk/gk/cet4/cet6" in warnings[0].getMessage()
    zebra, yak = word(conn, "zebra"), word(conn, "yak")
    assert (zebra["stage_xs"], zebra["stage_min"]) == (1, XS)  # the known code is kept
    assert yak["stage_min"] is None and all(yak[f"stage_{s}"] == 0 for s in STAGE_ORDER)  # only an unknown code → 课标外, still imported
    assert json.loads(events(conn)[-1][1])["unknown_stage_codes"] == 2
    assert "2 unknown stage codes ignored" in format_stats(stats)
    dry = import_seed(conn, str(UNKNOWN_CODE_SEED), dry_run=True)
    assert dry.unknown_stage_codes == 2 and "2 unknown stage codes ignored" in format_stats(dry)


def test_lemma_mismatch_counted(conn, tmp_path, caplog):
    caplog.set_level(logging.WARNING, logger="wd.seed")
    recs = records()[:3]
    recs[0]["lemma"] = "wrong-key"  # the record's lemma disagrees with normalise(word)
    recs[1].pop("lemma", None)  # a v1-style record without the key is not a mismatch
    recs[2]["lemma"] = "  "
    stats = import_seed(conn, str(write_seed(tmp_path / "mismatch.jsonl", recs)))
    assert (stats.records, stats.inserted, stats.lemma_mismatch) == (3, 3, 1)
    assert word(conn, "a") is not None and word(conn, "wrong-key") is None  # the computed key wins
    assert any("lemma that differs" in r.getMessage() and "wrong-key≠a" in r.getMessage() for r in caplog.records)
    assert json.loads(events(conn)[-1][1])["lemma_mismatch"] == 1 and "1 lemma mismatches" in format_stats(stats)


# ------------------------------------------------------------------------------------- file formats
def test_content_digest_up_to_date_across_gz_and_plain(conn, tmp_path):
    gz = tmp_path / "mini.jsonl.gz"
    gz.write_bytes(gzip.compress(MINI_SEED.read_bytes(), mtime=1))
    repacked = tmp_path / "repacked.jsonl.gz"
    repacked.write_bytes(gzip.compress(MINI_SEED.read_bytes(), compresslevel=1, mtime=2))  # another gzip run: different bytes
    assert sha256_file(gz) != sha256_file(repacked) != sha256_file(MINI_SEED)
    assert seed_digest(gz) == seed_digest(repacked) == seed_digest(MINI_SEED) == sha256_file(MINI_SEED)
    stats = import_seed(conn, str(gz))
    assert (stats.records, stats.inserted) == (N, N) and stats.sha256 == sha256_file(gz) and stats.content_sha256 == seed_digest(MINI_SEED)
    assert db.kv_get(conn, "seed_version") == stats.content_sha256
    before = dump(conn)
    for same_content in (MINI_SEED, repacked):
        again = import_seed(conn, str(same_content))
        assert again.up_to_date is True and again.records == 0 and again.sha256 == sha256_file(same_content)  # same content → no-op
        assert dump(conn) == before


def test_corrupt_gzip_raises_before_anything_is_written(conn):
    with pytest.raises(EOFError):
        seed_digest(BAD_GZIP_SEED)
    with pytest.raises(EOFError):
        import_seed(conn, str(BAD_GZIP_SEED))
    assert q(conn, "SELECT COUNT(*) FROM words") == 0 and db.kv_get(conn, "seed_version") is None and not conn.in_transaction


def test_malformed_lines_and_records_are_skipped(conn, tmp_path):
    good = records()[:3]
    text = "\n".join([json.dumps(good[0]), "", "not json at all", "[1,2,3]", json.dumps({"word": 5}), json.dumps({"nope": 1}), json.dumps({"word": "   "}), json.dumps(good[1]), json.dumps(good[2])])
    f = tmp_path / "messy.jsonl"
    f.write_text(text + "\n", encoding="utf-8")
    stats = import_seed(conn, str(f))
    assert (stats.records, stats.inserted, stats.skipped_records) == (6, 3, 3)
    assert q(conn, "SELECT COUNT(*) FROM words") == 3
    assert "3 skipped" in format_stats(stats)


def test_duplicate_lemmas_in_a_file_keep_the_first_record(conn, tmp_path):
    a = dict(records()[3])  # apple
    b = dict(a, word="Apple", translation=["n. 第二个"])
    f = tmp_path / "dup.jsonl"
    f.write_text(json.dumps(a) + "\n" + json.dumps(b) + "\n", encoding="utf-8")
    stats = import_seed(conn, str(f))
    assert (stats.records, stats.inserted, stats.duplicate_lemmas) == (2, 1, 1)
    assert word(conn, "apple")["display"] == "apple"


def test_missing_file_raises(conn, tmp_path):
    with pytest.raises(FileNotFoundError):
        import_seed(conn, str(tmp_path / "nope.jsonl.gz"))


def test_import_is_atomic(conn, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("forms exploded")

    monkeypatch.setattr(seed, "_rebuild_forms", boom)
    with pytest.raises(RuntimeError):
        import_seed(conn, str(MINI_SEED))
    assert q(conn, "SELECT COUNT(*) FROM words") == 0 and db.kv_get(conn, "seed_version") is None
    assert events(conn) == [] and not conn.in_transaction
    assert q(conn, "SELECT COUNT(*) FROM kv WHERE key LIKE 'learn_order.%'") == 0  # ranks and their stamps roll back with the import
    monkeypatch.undo()
    assert import_seed(conn, str(MINI_SEED)).inserted == N  # the connection is usable afterwards


def test_import_joins_an_open_transaction(conn):
    with db.tx(conn):
        stats = import_seed(conn, str(MINI_SEED))
        assert conn.in_transaction and stats.inserted == N
    assert q(conn, "SELECT COUNT(*) FROM words") == N


# ------------------------------------------------------------------------------------------ seed_row
def test_seed_row_mapping_and_validation():
    now = "2026-10-14T08:00:00Z"
    assert seed_row({"nope": 1}, now) is None and seed_row({"word": 5}, now) is None and seed_row({"word": " "}, now) is None
    r = seed_row({"word": "  Ice   Cream ", "stages": ["cet6", "zk"], "exchange": "bad", "cet6_star": 1, "translation": "a\n\nb", "sources": ["legacy:zk", "ecdict", "legacy:zk"]}, now)
    assert r is not None
    assert (r["lemma"], r["display"], r["kind"]) == ("ice cream", "Ice Cream", "phrase")
    assert (r["stage_xs"], r["stage_zk"], r["stage_gk"], r["stage_cet4"], r["stage_cet6"], r["stage_min"], r["cet6_star"]) == (0, 1, 0, 0, 1, stage_to_index("zk"), 1)
    assert r["exchange_json"] is None and r["_exchange"] == {} and r["translation"] == "a\nb" and r["sources"] == "ecdict legacy:zk"
    assert r["now"] == now and r["collins"] is None and r["phonetic"] is None
    assert (r["_aliases"], r["_unknown_stages"], r["_lemma_declared"]) == ([], [], None)
    r2 = seed_row({"word": "x", "stages": "cet6", "exam_tags": ["gre", "bogus"], "collins": "4", "oxford": True, "frq": "", "bnc": None}, now)
    assert r2["stage_min"] is None and r2["exam_tags"] == "gre" and r2["collins"] == 4 and r2["oxford"] == 1 and r2["frq"] is None
    r3 = seed_row({"word": "x" * 60}, now)  # rejected by the strict normaliser → lenient key, never dropped
    assert r3 is not None and r3["lemma"] == "x" * 60
    v2 = seed_row({"word": "TV", "lemma": "tv", "stages": ["xs", "cet9", "zk"], "aliases": ["T.V.", "  t.v. ", "", 3], "variant_of": "x", "seed_v": 2}, now)
    assert (v2["stage_xs"], v2["stage_zk"], v2["stage_min"]) == (1, 1, XS) and v2["_unknown_stages"] == ["cet9"]
    assert v2["_aliases"] == ["t.v."] and v2["_lemma_declared"] == "tv" and "variant_of" not in v2 and "seed_v" not in v2
    assert set(seed.SEED_COLUMNS) >= set(seed.STAGE_COLUMNS) == {f"stage_{s}" for s in STAGE_ORDER}
    assert seed.STAGE_COLUMNS == ("stage_xs", "stage_zk", "stage_gk", "stage_cet4", "stage_cet6")  # the 0011 DDL order


# ----------------------------------------------------------------------------------------------- CLI
def run_cli(argv: list[str]) -> int:
    from wd.cli import main

    return main(argv)


def test_cli_import_seed(conn, capsys, settings, monkeypatch):
    assert run_cli(["import-seed", "--file", str(MINI_SEED)]) == 0
    out = capsys.readouterr().out
    assert f"imported {N} seed records" in out and f"{N} inserted" in out
    assert q(conn, "SELECT COUNT(*) FROM words") == N
    assert run_cli(["import-seed"]) == 0  # default --file is WD_SEED_PATH (= the mini seed in the test env)
    assert "seed up to date" in capsys.readouterr().out
    assert run_cli(["import-seed", "--force"]) == 0
    out = capsys.readouterr().out
    assert "0 inserted, 0 updated" in out
    assert run_cli(["import-seed", "--file", str(settings.data_dir / "missing.jsonl")]) == 1
    assert "seed file not found" in capsys.readouterr().err
    assert run_cli(["import-seed", "--file", str(BAD_GZIP_SEED)]) == 1  # a corrupt archive is a message, not a traceback
    assert "cannot read" in capsys.readouterr().err
    # a valid gzip header over a corrupt deflate body raises zlib.error (neither OSError nor EOFError) — same clean exit 1
    corrupt = settings.data_dir / "corrupt.jsonl.gz"
    corrupt.write_bytes(gzip.compress(b'{"lemma": "apple"}\n')[:10] + b"\x07" + b"\x00" * 32)  # BFINAL=1 BTYPE=11 (reserved)
    assert run_cli(["import-seed", "--file", str(corrupt)]) == 1
    err = capsys.readouterr().err
    assert "cannot read" in err and "invalid block type" in err  # zlib.error's message, printed instead of a traceback
    # --report into a directory that does not exist: the import itself is done (stats printed), the missing report is exit 1
    assert run_cli(["import-seed", "--file", str(MINI_SEED), "--force", "--report", str(settings.data_dir / "no-such-dir" / "r.json")]) == 1
    captured = capsys.readouterr()
    assert "0 inserted, 0 updated" in captured.out and "cannot write report" in captured.err
    monkeypatch.setenv("WD_DB_PATH", str(settings.data_dir / "fresh.db"))
    assert run_cli(["import-seed", "--file", str(MINI_SEED)]) == 1  # unmigrated database
    assert "wd migrate" in capsys.readouterr().err
    assert os.path.exists(settings.data_dir / "fresh.db")


def test_cli_import_seed_refuses_a_database_behind_the_code_schema(conn, capsys, settings, monkeypatch, tmp_path):
    """The live database sits at schema 10 until `wd migrate` applies 0011–0013: `wd import-seed` and its --dry-run against it
    answer `run wd migrate first` in one line and write nothing — the UPSERT (and the dry run's SELECT) used to die with a
    `no such column: stage_xs` traceback (impl-review final F1; PLAN §8 steps 6 → 7 in that order, DEPLOY §9)."""
    old = tmp_path / "migrations"
    old.mkdir()
    for f in db.list_migration_files():
        if f.version <= 10:
            shutil.copy(f.path, old / f.path.name)
    behind = settings.data_dir / "behind.db"
    c = db.connect(behind)
    try:
        db.run_migrations(c, migrations_dir=old)
        assert db.current_version(c) == 10
    finally:
        c.close()
    monkeypatch.setenv("WD_DB_PATH", str(behind))
    newer = [f.path.name for f in db.list_migration_files() if f.version > 10]  # 0011 … the latest shipped file (0014 since the learning order)
    for argv in (["import-seed", "--file", str(MINI_SEED), "--dry-run"], ["import-seed", "--file", str(MINI_SEED)]):
        assert run_cli(argv) == 1
        captured = capsys.readouterr()
        assert f"{len(newer)} pending migration(s) ({', '.join(newer)})" in captured.err and "0011_primary_stage.sql" in captured.err and "run `wd migrate` first" in captured.err
        assert "Traceback" not in captured.err and captured.out == ""
    c = db.connect(behind)
    try:
        assert q(c, "SELECT COUNT(*) FROM words") == 0 and db.kv_get(c, "seed_version") is None  # nothing written
    finally:
        c.close()


def test_cli_import_seed_reports_a_database_error_in_one_line(conn, capsys, settings, monkeypatch):
    """The backstop behind the pending-migration guard: an sqlite3.Error out of the import (a hand-edited table) is one line
    and exit 1, not a traceback — the import ran in one transaction and has rolled back."""

    def broken(*a, **k):
        raise sqlite3.OperationalError("no such column: stage_xs")

    monkeypatch.setattr(seed, "import_seed", broken)
    assert run_cli(["import-seed", "--file", str(MINI_SEED)]) == 1
    err = capsys.readouterr().err
    assert "wd import-seed: database error: OperationalError: no such column: stage_xs" in err and "Traceback" not in err


def test_cli_dry_run_and_report(conn, capsys, settings, tmp_path):
    report = tmp_path / "dry.json"
    assert run_cli(["import-seed", "--file", str(MINI_SEED), "--dry-run", "--report", str(report)]) == 0
    out = capsys.readouterr().out
    assert out.startswith("dry run: insert 62 / update 0 / unchanged 0; orphans 0;") and f"stage_min new→{XS}:" in out
    assert q(conn, "SELECT COUNT(*) FROM words") == 0 and db.kv_get(conn, "seed_version") is None  # nothing written
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["dry_run"] is True and data["records"] == N and data["content_sha256"] == seed_digest(MINI_SEED)
    assert data["plan"]["inserted"] == N and data["plan"]["orphans"] == [] and data["plan"]["matrix"]["new→none"] == 1
    assert run_cli(["import-seed", "--file", str(MINI_SEED), "--report", str(report)]) == 0  # the real import also writes the report
    assert f"imported {N} seed records" in capsys.readouterr().out
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["dry_run"] is False and data["inserted"] == N and data["plan"]["inserted"] == N


def test_cli_parser_registers_import_seed_with_its_flags():
    from wd.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(["import-seed", "--file", "x.jsonl", "--force", "--dry-run", "--report", "r.json"])
    assert args.file == "x.jsonl" and args.force is True and args.dry_run is True and args.report == "r.json" and args.func is seed.cmd_import_seed
    defaults = parser.parse_args(["import-seed"])
    assert defaults.file is None and defaults.dry_run is False and defaults.report is None


# ---------------------------------------------------------------------------------------- full seed
@pytest.mark.full_seed
def test_full_seed_acceptance_numbers():
    """The acceptance script against a database that imported the real seed (WD_FULL_SEED_DB): the numbers come from the
    builder's data/seed/stats.json (PLAN R-17 — never hand-typed), plus the PLAN §7.3 invariants."""
    stats = json.loads((Path(__file__).resolve().parents[3] / "data" / "seed" / "stats.json").read_text(encoding="utf-8"))
    c = sqlite3.connect(os.environ["WD_FULL_SEED_DB"])
    g = lambda s: c.execute(s).fetchone()[0]
    assert g("select count(*) from words where source='seed'") == stats["total_words"]
    for s in STAGE_ORDER:
        assert g(f"select count(*) from words where stage_{s}=1") == stats["per_stage"][s], s
        assert g(f"select count(*) from words where stage_min={stage_to_index(s)}") == stats["first_stage"][s], s
    assert g("select count(*) from words where stage_min is null and source='seed'") == stats["first_stage"]["none"]
    for kind, n in stats["per_kind"].items():
        assert g(f"select count(*) from words where kind='{kind}' and source='seed'") == n, kind
    case = " ".join(f"WHEN stage_{s}=1 THEN {stage_to_index(s)}" for s in STAGE_ORDER)
    assert g(f"select count(*) from words where stage_min is not (case {case} end)") == 0  # stage_min consistent with the flags
    assert g("select count(*) from words where stage_xs=1 and stage_zk=0") == 0  # xs ⊆ zk
    assert g("select count(*) from words where lemma in ('tv','aids') and kind='abbreviation'") == 2
    assert 14_054 <= g("select count(*) from word_forms") <= 14_338  # 14,196 ± 1 % measured on the 2026-11-06 integration rehearsal (PLAN §6 S2)
    assert g("select count(*) from word_forms where kind='alias'") >= 1
    assert g("select count(*) from word_forms wf join words w on w.lemma=wf.form and w.merged_into_word_id is null") == 0
    assert g("select count(*) from word_forms where form=''") == 0
    assert g("select count(distinct word_id) from word_forms where form='bases'") == 2
    assert g("select count(*) from word_forms where kind not in ('p','d','i','3','s','r','t','alt','alias')") == 0
    assert g("select lemma from words where display='a.m.'") == "a.m." and g("select kind from words where lemma='a.m.'") == "abbreviation"
    assert g("select count(*) from words w, json_each('[\"' || replace(w.sources,' ','\",\"') || '\"]') j where w.sources is not null and j.value in ('zk','gk')") == 0
    # the learning order (docs/analysis/2026-11-06-learn-order/DESIGN.md §4.3): the column is filled and current, the committed
    # report data/seed/learn_order.json (written by `wd learn-order --report` on the rehearsal copy) describes this seed, and the
    # §1.6 acceptance counts hold when computed from the database — the five stage codes only, never the 课标外 group
    report = json.loads((Path(__file__).resolve().parents[3] / "data" / "seed" / "learn_order.json").read_text(encoding="utf-8"))
    assert g("select count(*) from words where stage_min is not null and learn_rank is null and merged_into_word_id is null") == 0
    assert learn_order.stale_count(c) == 0
    assert c.execute("select value from kv where key = ?", (learn_order.KV_VERSION,)).fetchone()[0] == learn_order.LEARN_ORDER_VERSION == report["policy"]
    assert report["seed"] == stats["content_sha256"] == c.execute("select value from kv where key = 'seed_version'").fetchone()[0]
    assert report["generated_by"] == "wd learn-order --report" and set(report["stages"]) == set(STAGE_ORDER) | {"none"}
    calendar = (*learn_order.MONTHS, *learn_order.WEEKDAYS)
    assert g(f"select count(*) from words where stage_xs = 1 and stage_min = 1 and lemma in ({', '.join(repr(l) for l in calendar)})") == len(calendar) == 19
    for form in ("am", "is", "are", "does"):
        assert "inherit:" in (c.execute("select sources from words where lemma = ?", (form,)).fetchone()[0] or ""), form
    live = learn_order.report(c)
    for code in STAGE_ORDER:
        assert live["stages"][code]["first"][:8] == report["stages"][code]["first"][:8], code
        assert live["acceptance"]["closed_in_first_30"][code] == 0 == report["acceptance"]["closed_in_first_30"][code], code
        assert live["acceptance"]["longest_frq_null_run"][code] <= 7, code
        assert live["stages"][code]["n"] == stats["first_stage"][code], code
    assert live["acceptance"]["xs_adverbs_first_30"] <= 2
    months = live["acceptance"]["xs_months_positions"]
    assert None not in months and months == list(range(months[0], months[0] + 12))  # 12 consecutive positions, january first
    assert live["acceptance"]["zk_phrases_first_200"] >= 40
    assert {k: live["acceptance"][k] for k in report["acceptance"]} == report["acceptance"]
