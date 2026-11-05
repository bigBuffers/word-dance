"""seedbuild.build on the mini fixture ``tests/fixtures/lists`` — PLAN §6 S3 tests (a)–(i) plus manifest validation,
stats.json v2, the generated ATTRIBUTION.md, the external CET lists and the CLI.

The fixture is a scaled-down ``data/lists`` (six verbatim mini lists, the real ``aliases.tsv``, a subset of
``overrides.tsv``, a 53-record v1 previous seed and a 110-row ECDICT dump); its README states the expected membership
(82 members, 32 new rows, ``bookshelf`` / ``hotdog`` / ``humourous`` retained without an official stage). Failure cases
mutate a copy of the fixture in ``tmp_path`` and re-sync ``SHA256SUMS`` / ``expect_rows`` so that only the intended
check fires.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest

from wd.schemas import STAGE_ORDER, stage_to_index
from wd.seedbuild import build as B
from wd.seedbuild import normalise as N
from wd.services import words

TESTS = Path(__file__).resolve().parents[1]
REPO = TESTS.parents[1]  # the Makefile's `seed` recipe is part of the contract (PLAN §4.5)
FIXTURES = TESTS / "fixtures" / "lists"
MINI_ECDICT_SQL = (FIXTURES / "mini_stardict.sql").read_text(encoding="utf-8")
OVERRIDDEN_PREVIOUS = {"mum", "p.e.", "e-mail"}  # previous lemmas with an overrides.tsv row in the fixture
CET = {"cet4", "cet6"}


# ------------------------------------------------------------------------------------------------ helpers
def copy_fixture(tmp_path: Path) -> Path:
    d = tmp_path / "lists"
    shutil.copytree(FIXTURES, d)
    return d


def resync(d: Path) -> None:
    """Rewrite SHA256SUMS and every ``expect_rows`` after a list file was edited (so only the intended check fires)."""
    manifest = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    sums = []
    for spec in manifest["lists"]:
        f = d / spec["file"]
        spec["expect_rows"] = len(B.read_rows(f))
        sums.append(f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.name}")
    (d / "SHA256SUMS").write_text("\n".join(sorted(sums, key=lambda s: s.split("  ")[1])) + "\n", encoding="utf-8")
    (d / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append_line(path: Path, line: str) -> None:
    text = path.read_text(encoding="utf-8")
    path.write_text(text + ("" if text.endswith("\n") else "\n") + line + "\n", encoding="utf-8")


def ecdict() -> B.Ecdict:
    return B.Ecdict.from_sql(MINI_ECDICT_SQL)


def run_build(d: Path, out: Path, **kw) -> B.BuildStats:
    return B.build(d / "manifest.json", d / "previous_seed.jsonl", ecdict=ecdict(), out=out, **kw)


def load_records(out: Path) -> dict[str, dict]:
    recs = [json.loads(l) for l in (out / "vocab.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    by = {r["lemma"]: r for r in recs}
    assert len(by) == len(recs), "duplicate lemma in the output"
    return by


def previous() -> dict[str, dict]:
    return B.load_previous(FIXTURES / "previous_seed.jsonl")


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> tuple[B.BuildStats, dict[str, dict], Path]:
    out = tmp_path_factory.mktemp("seed-out")
    stats = B.build(FIXTURES / "manifest.json", FIXTURES / "previous_seed.jsonl", ecdict=ecdict(), out=out)
    return stats, load_records(out), out


# ------------------------------------------------------------------------------------------------ (a) determinism
def test_two_builds_are_byte_identical_and_share_content_sha256(tmp_path: Path):
    out1, out2 = tmp_path / "one", tmp_path / "two"
    s1, s2 = run_build(FIXTURES, out1), run_build(FIXTURES, out2)
    assert (out1 / "vocab.jsonl").read_bytes() == (out2 / "vocab.jsonl").read_bytes()
    assert (out1 / "stats.json").read_bytes() == (out2 / "stats.json").read_bytes()
    assert (out1 / "ATTRIBUTION.md").read_bytes() == (out2 / "ATTRIBUTION.md").read_bytes()
    assert s1.content_sha256 == s2.content_sha256 == hashlib.sha256((out1 / "vocab.jsonl").read_bytes()).hexdigest()
    assert s1.file_bytes == len((out1 / "vocab.jsonl").read_bytes())
    assert b"\r" not in (out1 / "vocab.jsonl").read_bytes() and (out1 / "vocab.jsonl").read_bytes().endswith(b"\n")
    assert "built_at" not in json.loads((out1 / "stats.json").read_text(encoding="utf-8"))


def test_rebuild_from_own_output_is_idempotent(tmp_path: Path):
    """``make seed`` twice: the second run's --previous is the first run's output and must give the same bytes."""
    out1, out2 = tmp_path / "one", tmp_path / "two"
    run_build(FIXTURES, out1)
    stats2 = B.build(FIXTURES / "manifest.json", out1 / "vocab.jsonl", ecdict=ecdict(), out=out2)
    assert (out1 / "vocab.jsonl").read_bytes() == (out2 / "vocab.jsonl").read_bytes()
    assert stats2.new_words == 0 and stats2.network_translations == 0
    assert stats2.rows_changed_vs_previous == {"stage_set": 0, "sources_only": 0}


def test_built_at_only_lands_in_stats(tmp_path: Path):
    out1, out2 = tmp_path / "one", tmp_path / "two"
    run_build(FIXTURES, out1)
    stats = run_build(FIXTURES, out2, built_at="2026-11-06T00:00:00Z")
    assert (out1 / "vocab.jsonl").read_bytes() == (out2 / "vocab.jsonl").read_bytes()
    assert stats.built_at == "2026-11-06T00:00:00Z"
    assert json.loads((out2 / "stats.json").read_text(encoding="utf-8"))["built_at"] == "2026-11-06T00:00:00Z"


# ------------------------------------------------------------------------------------------------ membership (fixture README)
def test_membership_matches_the_fixture_readme(built):
    stats, recs, _ = built
    prev = previous()
    assert stats.total_words == 85 == len(prev) + 32
    assert stats.new_words == 32
    with_official = {l for l, r in recs.items() if set(r["stages"]) - CET}
    assert len(with_official) == 82
    assert set(prev) - with_official == {"bookshelf", "hotdog", "humourous"}  # retained, CET flags only
    assert recs["bookshelf"]["stages"] == [] and recs["hotdog"]["stages"] == ["cet6"] and recs["humourous"]["stages"] == ["cet6"]
    assert stats.stageless == 1 and stats.first_stage["none"] == 1
    assert stats.per_stage == {"xs": 34, "zk": 78, "gk": 14, "cet4": 28, "cet6": 18}
    assert stats.inherited == ["am", "are", "being", "does", "is"]
    assert stats.lists["moe22:l2"]["rows"] == 17 and stats.lists["moe22:l2"]["members"] == 25
    assert stats.lists["shmeea20:phr"]["members"] == 11


@pytest.mark.parametrize(
    "lemma,stages,tokens",
    [
        ("a", ["xs", "zk", "gk", "cet4"], {"moe22:l2", "moe22:l3", "hs25:0"}),
        ("an", ["xs", "zk", "gk", "cet6"], {"moe22:l2", "moe22:l3", "hs25:0"}),  # R3 a/an
        ("is", ["xs", "zk", "gk"], {"inherit:be"}),  # R8
        ("does", ["xs", "zk"], {"inherit:do"}),
        ("china", ["xs", "zk", "cet4"], {"moe22:l2", "moe22:l3", "moe22:app"}),  # R6 China/china + appendix
        ("colour", ["xs", "zk", "cet6"], {"moe22:l2", "moe22:l3"}),
        ("color", ["xs", "zk", "cet4"], {"moe22:l2", "moe22:l3"}),  # R2 variant
        ("excited", ["xs", "zk"], {"moe22:l2", "moe22:l3", "shmeea20"}),  # R7 participle head, new row
        ("mr.", ["xs", "zk", "gk"], {"moe22:l2", "moe22:l3", "shmeea20", "hs25:0"}),  # R5 alias Mr → mr.
        ("p.e.", ["xs", "zk"], {"moe22:l2", "moe22:l3", "shmeea20"}),
        ("physical education", ["xs", "zk"], {"moe22:l2", "moe22:l3"}),
        ("according to", ["zk", "gk", "cet6"], {"moe22:l3", "hs25:0"}),  # R2 collocation
        ("kung fu", ["zk"], {"moe22:l3"}),
        ("tofu", ["zk", "gk"], {"moe22:l3", "hs25:0"}),
        ("manner", ["zk", "cet4", "cet6"], {"moe22:l3", "shmeea20"}),  # R4 manner(s)
        ("manners", ["zk"], {"shmeea20"}),
        ("one", ["xs", "zk", "cet4"], {"moe22:app"}),
        ("monday", ["xs", "zk", "cet4"], {"moe22:app"}),
        ("usa", ["zk"], {"moe22:app"}),  # promoted variant of the R12-rejected head
        ("hot dog", ["zk"], {"shmeea20"}),  # alias hot-dog → hot dog
        ("hotdog", ["cet6"], set()),
        ("bund", ["zk"], {"shmeea20"}),
        ("cafe", ["zk", "cet4", "cet6"], {"shmeea20"}),  # R1 café
        ("a bit of", ["zk"], {"shmeea20:phr"}),
        ("catch cold", ["zk"], {"shmeea20:phr"}),
        ("by plane", ["zk"], {"shmeea20:phr"}),
        ("abandon", ["gk", "cet4", "cet6"], {"hs25:2"}),
        ("humorous", ["gk", "cet4", "cet6"], {"hs25:1"}),  # via alias humourous
        ("humourous", ["cet6"], set()),
        ("bean curd", ["gk"], {"hs25:0"}),
        ("bce", ["gk"], {"hs25:2"}),
    ],
)
def test_fixture_rows(built, lemma, stages, tokens):
    _, recs, _ = built
    rec = recs[lemma]
    assert rec["stages"] == stages, rec
    assert tokens <= set(rec["sources"]), rec["sources"]


def test_bare_collocation_head_and_dropped_variant_are_absent(built):
    _, recs, _ = built
    for lemma in ("according", "the bund", "was", "were", "has", "had", "did", "done", "pla day", "mount huangshan"):
        assert lemma not in recs, lemma


def test_variant_of_names_a_member_and_aliases_are_official_spellings(built):
    _, recs, _ = built
    variants = {l: r["variant_of"] for l, r in recs.items() if "variant_of" in r}
    assert variants == {
        "color": "colour", "math": "maths", "mathematics": "maths", "mum": "mother", "mom": "mother", "physical education": "p.e.",
        "television": "tv", "uk": "the united kingdom", "united nations": "un", "peking opera": "beijing opera", "email": "e-mail", "bean curd": "tofu",
    }
    assert all(v in recs for v in variants.values())
    assert "variant_of" not in recs["usa"] and "variant_of" not in recs["an"]  # promoted head / head in another list
    aliases = {l: r["aliases"] for l, r in recs.items() if "aliases" in r}
    assert aliases == {"mr.": ["mr"], "p.e.": ["pe"], "hot dog": ["hot-dog"], "humorous": ["humourous"]}


def test_legacy_tokens_come_from_the_v1_flags_and_old_zk_gk_tokens_vanish(built):
    _, recs, _ = built
    prev = previous()
    for lemma, old in prev.items():
        rec = recs[lemma]
        for code in ("zk", "gk"):
            assert (f"legacy:{code}" in rec["sources"]) == (code in old["stages"]), lemma
        assert "zk" not in rec["sources"] and "gk" not in rec["sources"]
        assert {t for t in old["sources"] if t in B.CARRIED_TOKENS} <= set(rec["sources"])
    assert "legacy:gk" not in recs["kung fu"]["sources"]  # a new row has no legacy


# ------------------------------------------------------------------------------------------------ (b) assertions → exit 2
def test_xs_not_subset_of_zk_fails_with_exit_2_and_writes_nothing(tmp_path: Path):
    d = copy_fixture(tmp_path)
    append_line(d / "mini-moe-2022-level2.txt", "abandon")  # xs head that is not in the level-3 mini list
    resync(d)
    out = tmp_path / "out"
    with pytest.raises(B.BuildError, match="xs ⊄ zk"):
        run_build(d, out)
    assert not out.exists()
    rc = B.main(["--manifest", str(d / "manifest.json"), "--previous", str(d / "previous_seed.jsonl"), "--out", str(out)])
    assert rc == 2 and not out.exists()


def test_dropping_a_previous_lemma_violates_retain(tmp_path: Path):
    d = copy_fixture(tmp_path)
    append_line(d / "overrides.tsv", "bookshelf\tdrop\t\tdeleting a previous lemma is refused")
    with pytest.raises(B.BuildError, match="retain"):
        run_build(d, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_no_strict_downgrades_the_content_checks_but_not_retain(tmp_path: Path, caplog: pytest.LogCaptureFixture):
    d = copy_fixture(tmp_path)
    append_line(d / "mini-moe-2022-level2.txt", "abandon")
    resync(d)
    with caplog.at_level("WARNING", logger="wd.seedbuild"):
        stats = run_build(d, tmp_path / "out", strict=False)
    assert "xs ⊄ zk" in caplog.text and stats.total_words == 85
    d2 = copy_fixture(tmp_path / "second")
    append_line(d2 / "overrides.tsv", "bookshelf\tdrop\t\t")
    with pytest.raises(B.BuildError, match="retain"):
        run_build(d2, tmp_path / "out2", strict=False)


# ------------------------------------------------------------------------------------------------ (c) missing heads
def test_missing_main_head_fails_and_is_listed(tmp_path: Path):
    d = copy_fixture(tmp_path)
    append_line(d / "mini-shmeea-2020-junior.txt", "zzqxv")
    resync(d)
    with pytest.raises(B.BuildError) as ei:
        run_build(d, tmp_path / "out")
    assert "shmeea20" in str(ei.value) and "zzqxv" in str(ei.value)


def test_main_head_failing_the_strict_gate_fails(tmp_path: Path):
    d = copy_fixture(tmp_path)
    append_line(d / "mini-shmeea-2020-junior.txt", "The United States of America")  # 5 tokens, R12
    resync(d)
    with pytest.raises(B.BuildError, match="strict gate"):
        run_build(d, tmp_path / "out")


def test_missing_appendix_head_is_a_warning_in_skipped(built):
    stats, recs, _ = built
    skipped = stats.lists["moe22:app"]["skipped"]
    assert "PLA Day (missing)" in skipped and "Mount Huangshan (missing)" in skipped
    assert any(s.startswith("The United States of America (strict") for s in skipped)
    assert any(s.startswith("United Nations Educational") for s in skipped)
    assert stats.lists["moe22:app"]["missing"] == []
    assert "pla day" not in recs


def test_phrase_skips_and_rejections_are_recorded(built):
    stats, _, _ = built
    skipped = stats.lists["shmeea20:phr"]["skipped"]
    assert "a lot of/lots of (other)" in skipped
    assert "agree with sb. (patterns)" in skipped and "add...to (patterns)" in skipped
    assert any(s.startswith("add ... to (strict") for s in skipped)
    assert stats.unparsed_notes == ["hs25: BCE (Before the Common Era) → Before the Common Era"]


def test_single_token_groups_and_member_false_groups(tmp_path: Path):
    d = copy_fixture(tmp_path)
    append_line(d / "mini-moe-2022-appendix.tsv", "数词-基数词\tone hundred (and) one\t\t")
    append_line(d / "mini-moe-2022-appendix.tsv", "不规则动词\tsee\tsaw\tseen")
    resync(d)
    stats = run_build(d, tmp_path / "out")
    assert "one hundred (and) one (compositional)" in stats.lists["moe22:app"]["skipped"]
    recs = load_records(tmp_path / "out")
    assert "see" not in recs and "saw" not in recs


def test_unknown_appendix_group_without_wildcard_is_a_build_error(tmp_path: Path):
    d = copy_fixture(tmp_path)
    append_line(d / "mini-moe-2022-appendix.tsv", "未知组\tone\t\t")
    resync(d)
    with pytest.raises(B.BuildError, match="未知组"):
        run_build(d, tmp_path / "out")


# ------------------------------------------------------------------------------------------------ (d) previous rows verbatim
def test_previous_rows_keep_their_dictionary_fields_verbatim(built):
    _, recs, _ = built
    for lemma, old in previous().items():
        rec = recs[lemma]
        if lemma in OVERRIDDEN_PREVIOUS:
            continue
        assert rec["word"] == old["word"], lemma
        for key in B.DICT_KEYS + ("cet6_star",):
            assert rec[key] == old[key], (lemma, key)


# ------------------------------------------------------------------------------------------------ (e) inheritance
def test_inherit_stages_only_affects_previous_lemmas_that_are_not_official(built):
    stats, recs, _ = built
    assert stats.inherited == ["am", "are", "being", "does", "is"]
    for form in ("am", "are", "is", "being"):
        assert recs[form]["stages"][:3] == ["xs", "zk", "gk"] and "inherit:be" in recs[form]["sources"], form
    assert recs["does"]["stages"] == ["xs", "zk"] and "inherit:do" in recs["does"]["sources"]
    assert recs["am"]["stages"] == ["xs", "zk", "gk", "cet6"]  # CET flag of the previous row kept
    for form in ("was", "were", "been", "has", "had", "did", "done"):
        assert form not in recs, form  # never created
    assert "inherit:be" not in recs["be"]["sources"]


def test_inheritance_needs_the_base_to_be_a_member(tmp_path: Path):
    d = copy_fixture(tmp_path)
    manifest = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    manifest["inherit_stages"]["have"] = ["humourous"]  # a previous lemma, but `have` is in no mini list
    (d / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    stats = run_build(d, tmp_path / "out")
    assert "humourous" not in stats.inherited
    assert load_records(tmp_path / "out")["humourous"]["stages"] == ["cet6"]


# ------------------------------------------------------------------------------------------------ (f) overrides
def test_overrides_translation_word_and_drop(built):
    stats, recs, _ = built
    assert recs["bund"]["translation"] == ["n. 外滩（the Bund，上海黄浦江西岸）"]
    assert recs["stuck"]["translation"] == ["a. 被卡住的，动不了的（stick 的过去式和过去分词）"]
    assert recs["mum"]["translation"] == ["n. 妈妈（英式口语，= mom）"]  # a previous row with a wrong ECDICT sense
    assert recs["p.e."]["translation"] == ["n. 体育（课）（= physical education）"]
    assert recs["children's day"]["translation"] == ["n. 儿童节（6 月 1 日）"]
    assert recs["e-mail"]["word"] == "e-mail" and previous()["e-mail"]["word"] == "E-MAIL"
    assert words.derive_kind(recs["e-mail"]["word"]) == "word"
    assert "the bund" not in recs
    assert stats.overrides_applied == 9 and stats.overrides_unused == []


def test_unused_override_is_reported(tmp_path: Path, caplog: pytest.LogCaptureFixture):
    d = copy_fixture(tmp_path)
    append_line(d / "overrides.tsv", "zebra\ttranslation\tn. 斑马\tnot in any mini list")
    with caplog.at_level("WARNING", logger="wd.seedbuild"):
        stats = run_build(d, tmp_path / "out")
    assert stats.overrides_unused == ["zebra translation"] and "zebra translation" in caplog.text


# ------------------------------------------------------------------------------------------------ (g) [网络] prefix
def test_network_prefix_is_removed_from_new_rows_and_counted(built):
    stats, recs, _ = built
    assert stats.network_translations == 2
    for lemma in ("in hospital", "save one's life"):
        first = recs[lemma]["translation"][0]
        assert first and not first.startswith("[网络]"), (lemma, first)
    assert stats.empty_translation == 0


def test_new_row_with_only_an_empty_network_translation_fails(tmp_path: Path):
    d = copy_fixture(tmp_path)
    conn = sqlite3.connect(":memory:")
    conn.executescript(MINI_ECDICT_SQL)
    conn.execute("UPDATE stardict SET translation = '[网络]' WHERE word = 'in hospital'")
    with pytest.raises(B.BuildError, match="empty first translation"):
        B.build(d / "manifest.json", d / "previous_seed.jsonl", ecdict=B.Ecdict(None, connection=conn), out=tmp_path / "out")


# ------------------------------------------------------------------------------------------------ (h) external CET lists
def test_external_lists_absent_keeps_previous_cet_flags(built):
    stats, recs, _ = built
    assert stats.external_lists == "absent"
    for lemma, old in previous().items():
        assert set(recs[lemma]["stages"]) & CET == set(old["stages"]) & CET, lemma
        assert recs[lemma]["cet6_star"] == bool(old["cet6_star"])
        assert {t for t in recs[lemma]["sources"] if t in ("cet4", "cet6", "cet46")} == {t for t in old["sources"] if t in ("cet4", "cet6", "cet46")}


def _write_wordlists(d: Path) -> Path:
    w = d / "mahavivo"
    w.mkdir()
    (w / "CET4_edited.txt").write_text("A\nkung fu [kʌŋ'fuː] n. 功夫\na (an) [ə] art. 一个\nOceania n. 大洋洲\n", encoding="utf-8")
    (w / "CET6_edited.txt").write_text("abandon [ə'bændən] vt. 放弃\n", encoding="utf-8")
    (w / "CET_4+6_edited.txt").write_text("kung fu\ntofu\nabandon\n", encoding="utf-8")
    (w / "英语六级词汇（星标，1726）.txt").write_text("tofu\n", encoding="utf-8")
    return w


def test_external_lists_present_add_flags_tokens_and_the_star(tmp_path: Path):
    d = copy_fixture(tmp_path)
    w = _write_wordlists(tmp_path)
    stats = B.build(d / "manifest.json", d / "previous_seed.jsonl", ecdict=ecdict(), wordlists=w, out=tmp_path / "out")
    recs = load_records(tmp_path / "out")
    assert stats.external_lists == "present"
    assert recs["kung fu"]["stages"] == ["zk", "cet4"] and {"cet4", "cet46"} <= set(recs["kung fu"]["sources"])
    assert recs["tofu"]["stages"] == ["zk", "gk", "cet6"] and "cet46" in recs["tofu"]["sources"] and recs["tofu"]["cet6_star"] is True
    assert "cet4" not in recs["tofu"]["sources"]
    assert recs["abandon"]["stages"] == ["gk", "cet4", "cet6"] and {"cet6", "cet46"} <= set(recs["abandon"]["sources"])
    assert "oceania" not in recs  # external lists never create rows
    assert "cet4" in recs["an"]["sources"] and "cet4" in recs["an"]["stages"]  # `a (an)` yields both heads


def test_external_dir_must_hold_every_manifest_file(tmp_path: Path):
    d = copy_fixture(tmp_path)
    w = _write_wordlists(tmp_path)
    (w / "CET6_edited.txt").unlink()
    with pytest.raises(B.BuildError, match="CET6_edited.txt"):
        B.build(d / "manifest.json", d / "previous_seed.jsonl", ecdict=ecdict(), wordlists=w, out=tmp_path / "out")


def test_parse_mahavivo_grammar(tmp_path: Path):
    rich = tmp_path / "rich.txt"
    rich.write_text("A\nabandon [ə'bændən] vt. 放弃\na (an) [ə] art.\nOceania n. 大洋洲\nice cream [ais kri:m] n. 冰淇淋\nI [ai] pron.\n中文行\n", encoding="utf-8")
    assert B.parse_mahavivo(rich, "rich") == ["abandon", "a", "an", "Oceania", "ice cream", "I"]
    plain = tmp_path / "plain.txt"
    plain.write_text("﻿abandon\nB\nice cream\nnot a word!\n", encoding="utf-8")
    assert B.parse_mahavivo(plain, "plain") == ["abandon", "ice cream"]


# ------------------------------------------------------------------------------------------------ (i) record shape
def test_every_record_is_a_valid_v2_record(built):
    stats, recs, out = built
    lines = (out / "vocab.jsonl").read_text(encoding="utf-8").splitlines()
    for line in lines:
        rec = json.loads(line)
        keys = list(rec)
        assert keys == [k for k in B.RECORD_KEYS if k in rec], keys  # fixed key order
        assert set(B.RECORD_KEYS) - {"aliases", "variant_of"} <= set(rec)
        assert rec["seed_v"] == 2
        assert set(rec["stages"]) <= set(STAGE_ORDER) and rec["stages"] == [s for s in STAGE_ORDER if s in rec["stages"]]
        assert rec["lemma"] == words.normalise_lemma(rec["word"]) == N.lemma_of(rec["word"])
        assert rec["sources"] == sorted(set(rec["sources"]))
        assert isinstance(rec["translation"], list) and isinstance(rec["exchange"], dict)
        if "aliases" in rec:
            assert rec["aliases"] and all(a != rec["lemma"] for a in rec["aliases"])
    keys = [(stage_to_index(r["stages"][0]) if r["stages"] else 99, r["lemma"]) for r in (json.loads(l) for l in lines)]
    assert keys == sorted(keys)


def test_lemma_self_check_is_what_the_importer_recomputes(built):
    """``check_lemmas`` flags a record whose lemma is not ``words.normalise_lemma(word)`` (review S3b F8); the fixture
    output has none (also asserted record by record above)."""
    _, recs, _ = built
    assert B.check_lemmas(recs.values()) == []
    bad = [{"word": "C word", "lemma": "c"}, {"word": "café", "lemma": "cafe"}, {"word": "ok", "lemma": "ok"}]
    assert B.check_lemmas(bad) == ["'C word' → 'c'", "'café' → 'cafe'"]
    assert words.normalise_lemma("café") != N.lemma_of("café") == "cafe"  # the two normalisations differ on diacritics


def test_build_refuses_a_lemma_mismatch_and_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(B, "check_lemmas", lambda records: ["'café' → 'cafe'"])
    with pytest.raises(B.BuildError, match="lemma is not what the importer computes"):
        run_build(copy_fixture(tmp_path), tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_stats_are_consistent_with_the_records(built):
    stats, recs, out = built
    d = json.loads((out / "stats.json").read_text(encoding="utf-8"))
    assert list(d)[:6] == ["seed_v", "content_sha256", "total_words", "previous_sha256", "ecdict_release", "external_lists"]
    assert list(d["per_stage"]) == list(STAGE_ORDER) and list(d["first_stage"]) == [*STAGE_ORDER, "none"]
    assert sum(d["first_stage"].values()) == d["total_words"] == len(recs)
    assert d["per_stage"] == {s: sum(1 for r in recs.values() if s in r["stages"]) for s in STAGE_ORDER}
    assert d["only_stage"] == {s: sum(1 for r in recs.values() if r["stages"] == [s]) for s in STAGE_ORDER}
    assert sum(d["per_kind"].values()) == d["total_words"] and list(d["per_kind"]) == list(B.KINDS)
    assert d["per_kind"]["phrase"] == sum(1 for r in recs.values() if " " in r["word"]) == d["multiword"]
    assert d["tokens"] == {t: n for t, n in sorted(__import__("collections").Counter(t for r in recs.values() for t in r["sources"]).items())}
    assert d["variants"] == sum(1 for r in recs.values() if "variant_of" in r) == 12
    assert d["aliases"] == sum(len(r.get("aliases", [])) for r in recs.values()) == 4
    assert d["previous_sha256"] == hashlib.sha256((FIXTURES / "previous_seed.jsonl").read_bytes()).hexdigest()
    assert d["ecdict_release"] == B.ECDICT_RELEASE and d["seed_v"] == 2
    assert {lid: ls["rows"] for lid, ls in d["lists"].items()} == {s["id"]: s["expect_rows"] for s in json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))["lists"]}
    assert d["merged_heads"] == {"miss": ["Miss", "miss"], "p.e.": ["P.E.", "PE"]}
    assert d["rows_changed_vs_previous"]["stage_set"] + d["rows_changed_vs_previous"]["sources_only"] <= len(previous())


def test_attribution_is_rendered_from_the_manifest(built):
    stats, _, out = built
    text = (out / "ATTRIBUTION.md").read_text(encoding="utf-8")
    manifest = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
    for spec in manifest["lists"]:
        assert spec["title"] in text and f"`{spec['id']}`" in text
    assert "**absent** in this build" in text and "**provisional**" in text
    assert "9 rows (at most 30; 9 applied in this build)" in text
    assert "| `moe22:l2` | 义务教育英语课程标准（2022 年版）附录 3 二级词汇表（迷你） (`mini-moe-2022-level2.txt`) | xs | 25 |" in text
    assert "| `inherit:be` / `inherit:do` |" in text and "| `legacy:zk` / `legacy:gk` |" in text
    assert "`xs` = 小学 (index 1)" in text and "`cet6` = 六级 (index 5)" in text
    assert text == B.render_attribution(B.load_manifest(FIXTURES / "manifest.json"), stats)
    # §1 names the pinned asset only for the pinned release (review S3b F7)
    assert f"Release used: {B.ECDICT_RELEASE} (`{B.ECDICT_ASSET}` → `stardict.db`" in text
    other = B.render_attribution(B.load_manifest(FIXTURES / "manifest.json"), dataclasses.replace(stats, ecdict_release="1.0.29"))
    assert "Release used: 1.0.29 (its `stardict.db`" in other and f"(`{B.ECDICT_ASSET}` → `stardict.db`" not in other


# ------------------------------------------------------------------------------------------------ manifest validation
def _edit_manifest(d: Path, fn) -> None:
    m = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    fn(m)
    (d / "manifest.json").write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_load_manifest_reads_the_fixture():
    m = B.load_manifest(FIXTURES / "manifest.json")
    assert [s.id for s in m.lists] == ["moe22:l2", "moe22:l3", "moe22:app", "shmeea20", "shmeea20:phr", "hs25"]
    assert m.lists[2].groups["不规则动词"].member is False and m.lists[2].groups["数词-基数词"].single_token is True
    assert m.lists[5].level_token == "hs25:{level}" and m.lists[5].provisional is True
    assert m.aliases["mr"] == "mr." and m.overrides["the bund"] == {"drop": ""} and m.drops == {"the bund"}
    assert m.inherit["be"][:3] == ("am", "is", "are") and m.member_tags == ("cet4", "cet6")
    assert [e.id for e in m.external] == ["cet4", "cet6", "cet46", "cet6star"]


@pytest.mark.parametrize(
    "mutate,message",
    [
        (lambda m: m.__setitem__("format", 1), "format"),
        (lambda m: m["lists"][0].__setitem__("policy", "bogus"), "policy"),
        (lambda m: m["lists"][0].__setitem__("format", "csv"), "format"),
        (lambda m: m["lists"][0].__setitem__("stages", ["xx"]), "STAGE_ORDER"),
        (lambda m: m["lists"][2]["groups"]["月份"].__setitem__("stages", ["cet9"]), "STAGE_ORDER"),
        (lambda m: m["lists"][0].__setitem__("expect_rows", 99), "99"),
        (lambda m: m["lists"][0].__setitem__("file", "nope.txt"), "missing"),
        (lambda m: m["lists"].append(dict(m["lists"][0])), "duplicate list id"),
        (lambda m: m["lists"][5].__setitem__("level_token", "hs25-{lvl}"), "level_token"),
        (lambda m: m["lists"][4].__setitem__("policy", "main"), "phrases"),
        (lambda m: m.__setitem__("ecdict_member_tags", ["toefl"]), "ecdict_member_tags"),
    ],
)
def test_manifest_errors(tmp_path: Path, mutate, message):
    d = copy_fixture(tmp_path)
    _edit_manifest(d, mutate)
    with pytest.raises(B.ManifestError, match=message):
        B.load_manifest(d / "manifest.json")


def test_checksum_mismatch_and_unlisted_file_are_manifest_errors(tmp_path: Path):
    d = copy_fixture(tmp_path)
    append_line(d / "mini-moe-2022-level2.txt", "# a comment keeps expect_rows but changes the bytes")
    with pytest.raises(B.ManifestError, match="sha256"):
        B.load_manifest(d / "manifest.json")
    resync(d)
    B.load_manifest(d / "manifest.json")
    (d / "SHA256SUMS").write_text("", encoding="utf-8")
    with pytest.raises(B.ManifestError, match="not listed"):
        B.load_manifest(d / "manifest.json")


@pytest.mark.parametrize(
    "line,message",
    [
        ("bund\tcolour\tblue\t", "field"),
        ("bund\ttranslation\t\t", "no value"),
        ("e-mail\tword\temail\t", "does not keep the lemma"),
        ("bund\ttranslation\tagain\t", "duplicate"),
        ("\ttranslation\tx\t", "empty lemma"),
        ("bund\ttranslation", "expected lemma"),
    ],
)
def test_overrides_tsv_errors(tmp_path: Path, line, message):
    d = copy_fixture(tmp_path)
    append_line(d / "overrides.tsv", line)
    with pytest.raises(B.ManifestError, match=message):
        B.load_manifest(d / "manifest.json")


def test_overrides_tsv_row_limit(tmp_path: Path):
    d = copy_fixture(tmp_path)
    for i in range(22):
        append_line(d / "overrides.tsv", f"word{i}\ttranslation\tx\t")
    with pytest.raises(B.ManifestError, match="at most 30"):
        B.load_manifest(d / "manifest.json")


def test_alias_chain_is_a_manifest_error(tmp_path: Path):
    d = copy_fixture(tmp_path)
    append_line(d / "aliases.tsv", "mister\tmr\tchain: mister → mr → mr.")
    with pytest.raises(B.ManifestError, match="chain"):
        B.load_manifest(d / "manifest.json")


def test_load_previous_refuses_duplicate_lemmas(tmp_path: Path):
    p = tmp_path / "prev.jsonl"
    p.write_text('{"word": "Miss", "stages": [], "sources": []}\n{"word": "miss", "stages": [], "sources": []}\n', encoding="utf-8")
    with pytest.raises(B.BuildError, match="duplicate lemma"):
        B.load_previous(p)


def test_load_previous_reads_gzip_and_keys_by_lemma_of(tmp_path: Path):
    import gzip

    p = tmp_path / "prev.jsonl.gz"
    with gzip.open(p, "wt", encoding="utf-8") as f:
        f.write('{"word": "E-MAIL", "stages": ["zk"], "sources": ["zk"]}\n\n{"word": "café", "stages": [], "sources": []}\n')
    prev = B.load_previous(p)
    assert set(prev) == {"e-mail", "cafe"} and B.record_version(prev["e-mail"]) == 1


# ------------------------------------------------------------------------------------------------ Ecdict
def test_ecdict_lookups(tmp_path: Path):
    db = tmp_path / "mini.db"
    conn = sqlite3.connect(db)
    conn.executescript(MINI_ECDICT_SQL)
    conn.close()
    ec = B.Ecdict(db)
    assert ec.available and ec.get("mr.").word == "Mr." and ec.get("MR.").word == "Mr."  # COLLATE NOCASE
    assert ec.get("Mr").word == "Mr"  # the alias exists because this row is the wrong sense
    assert N.lookup(ec, "hot-dog").word == "hot-dog" and N.lookup(ec, "hot dog").word == "hot dog"
    assert N.lookup(ec, "break down") is None and ec.get("breakdown") is not None  # R10 never glues
    assert ec.get("") is None and ec.get("zzqxv") is None
    n = ec.lookups
    ec.get("mr.")
    assert ec.lookups == n  # cached
    ec.close()
    assert B.Ecdict(None).get("a") is None and not B.Ecdict(None).available
    with pytest.raises(B.BuildError, match="does not exist"):
        B.Ecdict(tmp_path / "nope.db")


def test_build_without_ecdict_can_only_relabel_previous_lemmas(tmp_path: Path):
    with pytest.raises(B.BuildError, match="neither ECDICT nor the previous seed") as ei:
        B.build(FIXTURES / "manifest.json", FIXTURES / "previous_seed.jsonl", ecdict=None, out=tmp_path / "out")
    msg = str(ei.value)
    # the first line says why (no --ecdict) and how (ECDICT_DB=) before the bare misses are listed (review S3b F3)
    assert "no --ecdict was given and " in msg and "ECDICT_DB=<stardict.db>" in msg
    assert msg.index("no --ecdict was given") < msg.index("neither ECDICT nor the previous seed")
    assert not (tmp_path / "out").exists()


# ------------------------------------------------------------------------------------------------ make seed recipe
@pytest.mark.skipif(shutil.which("make") is None, reason="make is not installed")
def test_make_seed_takes_the_committed_seed_as_the_baseline_of_build_and_diff():
    """``make -n seed`` expands the recipe without running it. The baseline of BOTH ``build_seed.py --previous`` and
    ``seed_diff.py`` is ``git show $(SEED_BASE):data/seed/vocab.jsonl.gz`` (default HEAD), never the working-tree
    archive that ``pack_seed.sh`` replaces — otherwise the second run relabels its own output and stats.json becomes
    self-referential (impl-review S3b F1). A failed ``git show`` exits 2 (F2); DIFF.md is labelled with the revision,
    not the temporary file (F5)."""
    def dry_run(*vars: str) -> str:
        return subprocess.run(["make", "-n", "seed", *vars], cwd=REPO, capture_output=True, text=True, check=True).stdout

    out = dry_run("ECDICT_DB=/x/stardict.db", "SEED_BASE=abc123")
    assert 'git show "abc123:data/seed/vocab.jsonl.gz" > "$prev" || {' in out and "exit 2" in out.split("git show", 1)[1]
    assert '--previous "$prev"' in out and 'seed_diff.py "$prev" data/seed/vocab.jsonl --md data/seed/DIFF.md' in out
    assert "--previous data/seed/vocab.jsonl.gz" not in out  # the F1 bug
    assert '--ecdict "/x/stardict.db"' in out and "--wordlists" not in out
    assert '--old-label "abc123:data/seed/vocab.jsonl.gz" --new-label data/seed/vocab.jsonl.gz' in out
    assert out.index("build_seed.py") < out.index("seed_diff.py") < out.index("pack_seed.sh")  # build → diff → pack
    default = dry_run()
    assert 'git show "HEAD:data/seed/vocab.jsonl.gz"' in default and "--ecdict" not in default and "--wordlists" not in default


# ------------------------------------------------------------------------------------------------ CLI
def test_main_builds_and_prints_a_summary(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    db = tmp_path / "mini.db"
    conn = sqlite3.connect(db)
    conn.executescript(MINI_ECDICT_SQL)
    conn.close()
    out = tmp_path / "out"
    rc = B.main(["--manifest", str(FIXTURES / "manifest.json"), "--previous", str(FIXTURES / "previous_seed.jsonl"), "--ecdict", str(db), "--out", str(out)])
    assert rc == 0
    err = capsys.readouterr().err
    assert "vocab.jsonl: 85 records (32 new, 1 without a stage)" in err and "moe22:app: rows 19" in err
    assert {p.name for p in out.iterdir()} == {"vocab.jsonl", "stats.json", "ATTRIBUTION.md"}


def test_main_returns_2_on_a_manifest_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    d = copy_fixture(tmp_path)
    _edit_manifest(d, lambda m: m.__setitem__("format", 3))
    rc = B.main(["--manifest", str(d / "manifest.json"), "--previous", str(d / "previous_seed.jsonl"), "--out", str(tmp_path / "out")])
    err = capsys.readouterr().err
    assert rc == 2 and err.startswith("build_seed: ") and "format" in err and not (tmp_path / "out").exists()
