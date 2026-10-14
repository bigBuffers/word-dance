"""wd/seed.py — import_seed on the mini seed (WP1): column mapping, kind derivation, stage flags, cet6_star, word_forms
guards and kind priority, idempotency (second run / --force), user data and content pointers untouched, .jsonl.gz and
.jsonl inputs, atomicity, kv.seed_version, and the `wd import-seed` command."""

from __future__ import annotations

import gzip
import json
import os
import sqlite3
from pathlib import Path

import pytest

from wd import db, seed
from wd.seed import SeedStats, format_stats, import_seed, seed_row, sha256_file

MINI_SEED = Path(__file__).resolve().parents[1] / "fixtures" / "mini_seed.jsonl"
FORM_CODES = ("p", "d", "i", "3", "s", "r", "t")


def records() -> list[dict]:
    return [json.loads(line) for line in MINI_SEED.read_text(encoding="utf-8").splitlines() if line.strip()]


def q(conn: sqlite3.Connection, sql: str, *params):
    return conn.execute(sql, params).fetchone()[0]


def word(conn: sqlite3.Connection, lemma: str) -> dict:
    return db.row_to_dict(conn.execute("SELECT * FROM words WHERE lemma = ?", (lemma,)).fetchone())


def dump(conn: sqlite3.Connection) -> dict:
    return {
        "words": [tuple(r) for r in conn.execute("SELECT * FROM words ORDER BY id")],
        "forms": [tuple(r) for r in conn.execute("SELECT * FROM word_forms ORDER BY form, word_id")],
        "kv": [tuple(r) for r in conn.execute("SELECT key, value FROM kv WHERE key LIKE 'seed%' ORDER BY key")],
    }


def expected_forms(lemmas: set[str]) -> dict[tuple[str, str], str]:
    """Independent re-derivation of the (form, lemma) → kind table from the fixture (same guards, same priority)."""
    out: dict[tuple[str, str], str] = {}
    for rec in records():
        for code in FORM_CODES:
            raw = rec.get("exchange", {}).get(code)
            if raw is None:
                continue
            form = " ".join(raw.split()).lower()
            if not form or form in lemmas:
                continue
            out.setdefault((form, rec["word"].lower()), code)
    return out


# ------------------------------------------------------------------------------------------ basics
def test_import_counts_and_bookkeeping(conn):
    stats = import_seed(conn, str(MINI_SEED))
    assert isinstance(stats, SeedStats)
    assert (stats.records, stats.inserted, stats.updated, stats.skipped_records, stats.up_to_date) == (60, 60, 0, 0, False)
    assert stats.sha256 == sha256_file(MINI_SEED) and stats.path == str(MINI_SEED) and stats.seconds >= 0
    assert q(conn, "SELECT COUNT(*) FROM words") == 60
    assert q(conn, "SELECT COUNT(*) FROM words WHERE source='seed' AND is_public=1 AND is_valid_english=1 AND safe_for_sharing=1") == 60
    assert q(conn, "SELECT COUNT(*) FROM words WHERE created_by_user_id IS NOT NULL OR merged_into_word_id IS NOT NULL OR difficulty IS NOT NULL") == 0
    assert q(conn, "SELECT COUNT(*) FROM words WHERE content_state != 'none' OR image_state != 'none' OR active_content_id IS NOT NULL") == 0
    assert db.kv_get(conn, "seed_version") == stats.sha256
    assert db.kv_get(conn, "seed_imported_at") is not None
    ev = conn.execute("SELECT kind, detail_json FROM system_events").fetchall()
    assert len(ev) == 1 and ev[0][0] == "seed_imported"
    detail = json.loads(ev[0][1])
    assert detail["records"] == 60 and detail["inserted"] == 60 and detail["sha256"] == stats.sha256 and detail["force"] is False
    assert "imported 60 seed records" in format_stats(stats)


def test_kind_derivation_and_display_casing(conn):
    import_seed(conn, str(MINI_SEED))
    assert (word(conn, "a.m.")["display"], word(conn, "a.m.")["kind"]) == ("a.m.", "abbreviation")
    assert (word(conn, "tv")["display"], word(conn, "tv")["kind"]) == ("TV", "abbreviation")
    assert (word(conn, "aids")["display"], word(conn, "aids")["kind"]) == ("AIDS", "abbreviation")
    assert q(conn, "SELECT COUNT(*) FROM words WHERE lemma IN ('tv','aids') AND kind='abbreviation'") == 2
    assert (word(conn, "china")["display"], word(conn, "china")["kind"]) == ("China", "proper_noun")
    assert word(conn, "ice cream")["kind"] == "phrase" and word(conn, "ought to")["kind"] == "phrase"
    assert q(conn, "SELECT COUNT(*) FROM words WHERE kind='phrase'") == 2
    assert word(conn, "abandon")["kind"] == "word" and word(conn, "email")["kind"] == "word"
    assert word(conn, "i") is None  # not in the mini seed (kept out so 'I' cannot mask a casing bug)
    assert q(conn, "SELECT COUNT(*) FROM words WHERE lemma != lower(lemma)") == 0


def test_stage_flags_stage_min_and_cet6_star(conn):
    import_seed(conn, str(MINI_SEED))
    ab = word(conn, "abandon")  # stages gk, cet4, cet6
    assert (ab["stage_zk"], ab["stage_gk"], ab["stage_cet4"], ab["stage_cet6"], ab["stage_min"]) == (0, 1, 1, 1, 2)
    assert word(conn, "absolutely")["stage_min"] == 3  # cet4 only
    assert word(conn, "email")["stage_min"] == 1  # zk + cet6 → lowest wins
    assert word(conn, "ought to")["stage_min"] == 4
    assert word(conn, "a")["stage_min"] == 1 and word(conn, "a")["stage_cet6"] == 0
    assert q(conn, "SELECT COUNT(*) FROM words WHERE stage_min IS NULL") == 0
    assert q(conn, "SELECT COUNT(*) FROM words WHERE cet6_star=1") == 3
    assert {r[0] for r in conn.execute("SELECT lemma FROM words WHERE cet6_star=1")} == {"abnormal", "abrupt", "absurd"}
    recs = records()
    assert q(conn, "SELECT COUNT(*) FROM words WHERE stage_zk=1") == sum("zk" in r["stages"] for r in recs)
    assert q(conn, "SELECT COUNT(*) FROM words WHERE stage_cet6=1") == sum("cet6" in r["stages"] for r in recs)


def test_dictionary_column_mapping(conn):
    import_seed(conn, str(MINI_SEED))
    a = word(conn, "a")
    assert a["translation"] == "第一个字母 A; 一个; 第一的\nart. [计] 累加器, 加法器, 地址, 振幅, 模拟, 区域, 面积, 汇编, 组件, 异步"
    assert a["definition"].startswith("n. the 1st letter") and "\n" in a["definition"]
    assert (a["pos"], a["collins"], a["oxford"], a["bnc"], a["frq"], a["ecdict_id"]) == ("a:99/t:1", 5, 1, 5, 5, 7909)
    assert json.loads(a["exchange_json"]) == {"s": "some"}
    assert a["sources"] == "cet4 ecdict zk" and a["exam_tags"] is None
    am = word(conn, "a.m.")
    assert am["phonetic"] is None and am["bnc"] is None and am["frq"] is None and am["exchange_json"] is None and am["pos"] is None
    ability = word(conn, "ability")
    assert ability["exam_tags"] == "ky toefl ielts" and ability["phonetic"] == "ə'biliti" and ability["sources"] == "cet4 cet46 ecdict gk zk"
    assert word(conn, "abnormal")["cet6_star"] == 1


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
    assert q(conn, "SELECT COUNT(*) FROM word_forms WHERE kind NOT IN ('p','d','i','3','s','r','t')") == 0
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


# ---------------------------------------------------------------------------------------- idempotency
def test_second_run_is_a_noop_and_force_changes_nothing(conn):
    import_seed(conn, str(MINI_SEED))
    before = dump(conn)
    again = import_seed(conn, str(MINI_SEED))
    assert again.up_to_date is True and again.records == 0 and again.inserted == 0
    assert "seed up to date" in format_stats(again)
    assert dump(conn) == before
    assert q(conn, "SELECT COUNT(*) FROM system_events") == 1
    forced = import_seed(conn, str(MINI_SEED), force=True)
    assert forced.up_to_date is False and (forced.records, forced.inserted, forced.updated) == (60, 0, 0)
    assert forced.forms == len(before["forms"])
    after = dump(conn)
    assert after["words"] == before["words"]  # incl. updated_at: unchanged rows are not rewritten
    assert after["forms"] == before["forms"]
    assert dict(after["kv"])["seed_version"] == dict(before["kv"])["seed_version"]
    assert q(conn, "SELECT COUNT(*) FROM system_events") == 2


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
    modified = tmp_path / "modified.jsonl"
    modified.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs), encoding="utf-8")
    stats = import_seed(conn, str(modified))
    assert (stats.inserted, stats.updated, stats.up_to_date) == (0, 1, False)
    ab = word(conn, "abandon")
    assert ab["translation"] == "vt. 新释义" and ab["stage_zk"] == 1 and ab["stage_min"] == 1 and ab["cet6_star"] == 1
    assert word(conn, "apple") == apple_before
    assert db.kv_get(conn, "seed_version") == sha256_file(modified)


def test_provisional_user_word_is_promoted_to_a_seed_word(conn):
    user = conn.execute("INSERT INTO users(username, password_hash) VALUES ('alice','x')").lastrowid
    conn.execute("INSERT INTO words(lemma, display, kind, source, is_public, created_by_user_id) VALUES ('apple','Apple','proper_noun','user',0,?)", (user,))
    stats = import_seed(conn, str(MINI_SEED))
    assert (stats.inserted, stats.updated) == (59, 1)
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


# ------------------------------------------------------------------------------------- file formats
def test_gzip_and_plain_inputs_are_equivalent(conn, tmp_path):
    gz = tmp_path / "mini.jsonl.gz"
    with gzip.open(gz, "wb") as f:
        f.write(MINI_SEED.read_bytes())
    stats = import_seed(conn, str(gz))
    assert (stats.records, stats.inserted) == (60, 60) and stats.sha256 == sha256_file(gz) != sha256_file(MINI_SEED)
    assert db.kv_get(conn, "seed_version") == sha256_file(gz)
    plain = import_seed(conn, str(MINI_SEED))
    assert plain.up_to_date is False and (plain.inserted, plain.updated) == (0, 0)  # a different file, identical content
    assert db.kv_get(conn, "seed_version") == sha256_file(MINI_SEED)


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
    assert q(conn, "SELECT COUNT(*) FROM system_events") == 0 and not conn.in_transaction
    monkeypatch.undo()
    assert import_seed(conn, str(MINI_SEED)).inserted == 60  # the connection is usable afterwards


def test_import_joins_an_open_transaction(conn):
    with db.tx(conn):
        stats = import_seed(conn, str(MINI_SEED))
        assert conn.in_transaction and stats.inserted == 60
    assert q(conn, "SELECT COUNT(*) FROM words") == 60


# ------------------------------------------------------------------------------------------ seed_row
def test_seed_row_mapping_and_validation():
    now = "2026-10-14T08:00:00Z"
    assert seed_row({"nope": 1}, now) is None and seed_row({"word": 5}, now) is None and seed_row({"word": " "}, now) is None
    r = seed_row({"word": "  Ice   Cream ", "stages": ["cet6", "zk"], "exchange": "bad", "cet6_star": 1, "translation": "a\n\nb", "sources": ["zk", "ecdict", "zk"]}, now)
    assert r is not None
    assert (r["lemma"], r["display"], r["kind"]) == ("ice cream", "Ice Cream", "phrase")
    assert (r["stage_zk"], r["stage_gk"], r["stage_cet4"], r["stage_cet6"], r["stage_min"], r["cet6_star"]) == (1, 0, 0, 1, 1, 1)
    assert r["exchange_json"] is None and r["_exchange"] == {} and r["translation"] == "a\nb" and r["sources"] == "ecdict zk"
    assert r["now"] == now and r["collins"] is None and r["phonetic"] is None
    r2 = seed_row({"word": "x", "stages": "cet6", "exam_tags": ["gre", "bogus"], "collins": "4", "oxford": True, "frq": "", "bnc": None}, now)
    assert r2["stage_min"] is None and r2["exam_tags"] == "gre" and r2["collins"] == 4 and r2["oxford"] == 1 and r2["frq"] is None
    r3 = seed_row({"word": "x" * 60}, now)  # rejected by the strict normaliser → lenient key, never dropped
    assert r3 is not None and r3["lemma"] == "x" * 60


# ----------------------------------------------------------------------------------------------- CLI
def run_cli(argv: list[str]) -> int:
    from wd.cli import main

    return main(argv)


def test_cli_import_seed(conn, capsys, settings, monkeypatch):
    assert run_cli(["import-seed", "--file", str(MINI_SEED)]) == 0
    out = capsys.readouterr().out
    assert "imported 60 seed records" in out and "60 inserted" in out
    assert q(conn, "SELECT COUNT(*) FROM words") == 60
    assert run_cli(["import-seed"]) == 0  # default --file is WD_SEED_PATH (= the mini seed in the test env)
    assert "seed up to date" in capsys.readouterr().out
    assert run_cli(["import-seed", "--force"]) == 0
    out = capsys.readouterr().out
    assert "0 inserted, 0 updated" in out
    assert run_cli(["import-seed", "--file", str(settings.data_dir / "missing.jsonl")]) == 1
    assert "seed file not found" in capsys.readouterr().err
    monkeypatch.setenv("WD_DB_PATH", str(settings.data_dir / "fresh.db"))
    assert run_cli(["import-seed", "--file", str(MINI_SEED)]) == 1  # unmigrated database
    assert "wd migrate" in capsys.readouterr().err
    assert os.path.exists(settings.data_dir / "fresh.db")


def test_cli_parser_registers_import_seed_with_its_flags():
    from wd.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(["import-seed", "--file", "x.jsonl", "--force"])
    assert args.file == "x.jsonl" and args.force is True and args.func is seed.cmd_import_seed
    assert parser.parse_args(["import-seed"]).file is None


# ---------------------------------------------------------------------------------------- full seed
@pytest.mark.full_seed
def test_full_seed_acceptance_numbers():
    """The TASKS WP1 acceptance script against a database that imported the real 9,162-word seed (WD_FULL_SEED_DB)."""
    c = sqlite3.connect(os.environ["WD_FULL_SEED_DB"])
    g = lambda s: c.execute(s).fetchone()[0]
    assert g("select count(*) from words where source='seed'") == 9162
    assert (g("select count(*) from words where stage_zk=1"), g("select count(*) from words where stage_gk=1"), g("select count(*) from words where stage_cet4=1"), g("select count(*) from words where stage_cet6=1")) == (2099, 3829, 4722, 7671)
    assert (g("select count(*) from words where stage_min=1"), g("select count(*) from words where stage_min=2"), g("select count(*) from words where stage_min=3"), g("select count(*) from words where stage_min=4")) == (2099, 1792, 1577, 3694)
    assert g("select count(*) from words where kind='phrase'") == 13 and g("select count(*) from words where cet6_star=1") == 1714
    assert g("select count(*) from words where lemma in ('tv','aids') and kind='abbreviation'") == 2
    assert 14000 <= g("select count(*) from word_forms") <= 14300
    assert g("select count(*) from word_forms wf join words w on w.lemma=wf.form") == 0
    assert g("select count(*) from word_forms where form=''") == 0
    assert g("select count(distinct word_id) from word_forms where form='bases'") == 2
    assert g("select count(*) from word_forms where kind not in ('p','d','i','3','s','r','t')") == 0
    assert g("select lemma from words where display='a.m.'") == "a.m." and g("select kind from words where lemma='a.m.'") == "abbreviation"
