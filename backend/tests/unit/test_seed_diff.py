"""seedbuild.diff — PLAN §4.8 / §6 S3: the v1 → v2 matrix and lists on the fixture pair, the invariants (removed
lemma, xs ⊄ zk, stats mismatch → exit 1) and stable Markdown / JSON rendering."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from wd.schemas import STAGE_ORDER
from wd.seedbuild import build as B
from wd.seedbuild import diff as D

TESTS = Path(__file__).resolve().parents[1]
FIXTURES = TESTS / "fixtures" / "lists"
OLD = FIXTURES / "previous_seed.jsonl"  # v1: codes zk gk cet4 cet6, no lemma / seed_v keys


@pytest.fixture(scope="module")
def new_seed(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The v2 seed the builder makes from the fixture (85 records) plus its stats.json, in one directory."""
    out = tmp_path_factory.mktemp("new-seed")
    ec = B.Ecdict.from_sql((FIXTURES / "mini_stardict.sql").read_text(encoding="utf-8"))
    B.build(FIXTURES / "manifest.json", OLD, ecdict=ec, out=out)
    return out / "vocab.jsonl"


def write_seed(path: Path, records: list[dict]) -> Path:
    text = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records)
    if path.suffix == ".gz":
        with gzip.open(path, "wt", encoding="utf-8") as f:
            f.write(text)
    else:
        path.write_text(text, encoding="utf-8")
    return path


def v2(word: str, stages: list[str], **extra) -> dict:
    rec = {"word": word, "lemma": word.lower(), "translation": ["x"], "stages": stages, "sources": ["t"], "seed_v": 2}
    rec.update(extra)
    return rec


def v1(word: str, stages: list[str], **extra) -> dict:
    rec = {"word": word, "translation": ["x"], "stages": stages, "sources": ["t"]}
    rec.update(extra)
    return rec


# ------------------------------------------------------------------------------------------------ alignment helpers
def test_record_lemma_and_versions():
    assert D.record_lemma({"word": "E-MAIL"}) == "e-mail"  # v1: importer lemma
    assert D.record_lemma({"word": "x", "lemma": "custom"}) == "custom"  # v2: the record's own key
    assert D.record_lemma({"word": 3}) is None
    assert D.seed_version({"a": v1("a", ["zk"])}) == 1
    assert D.seed_version({"a": v2("a", ["xs", "zk"])}) == 2
    assert D.seed_version({"a": v1("a", ["xs"])}) == 2  # a file listing xs is already renumbered
    assert D.first_stage(v1("a", ["cet6", "zk"])) == "zk" and D.first_stage(v1("a", [])) is None
    assert D.stage_label("zk", 1) == "1 (zk)" and D.stage_label("zk", 2) == "2 (zk)" and D.stage_label(None, 2) == "∅"
    assert D.stage_label("cet6", 1) == "4 (cet6)" and D.stage_label("cet6", 2) == "5 (cet6)"


def test_load_seed_reads_both_formats_and_refuses_duplicates(tmp_path: Path):
    gz = write_seed(tmp_path / "s.jsonl.gz", [v1("Miss", ["zk"])])
    assert list(D.load_seed(gz)) == ["miss"]
    dup = write_seed(tmp_path / "dup.jsonl", [v1("Miss", ["zk"]), v1("miss", ["gk"])])
    with pytest.raises(D.DiffError, match="duplicate lemma"):
        D.load_seed(dup)
    with pytest.raises(D.DiffError, match="does not exist"):
        D.load_seed(tmp_path / "nope.jsonl")
    bad = tmp_path / "bad.jsonl"
    bad.write_text("{not json\n", encoding="utf-8")
    with pytest.raises(D.DiffError, match="not a JSON record"):
        D.load_seed(bad)


# ------------------------------------------------------------------------------------------------ fixture pair
def test_fixture_pair_counts_matrix_and_invariants(new_seed: Path):
    old, new = D.load_seed(OLD), D.load_seed(new_seed)
    stats = json.loads((new_seed.parent / "stats.json").read_text(encoding="utf-8"))
    d = D.compute(old, new, stats=stats)
    assert (d.old_version, d.new_version) == (1, 2)
    assert (d.old_total, d.new_total) == (53, 85)
    assert len(d.added) == 32 and d.removed == []
    assert {x["lemma"] for x in d.added} >= {"excited", "kung fu", "hot dog", "bund", "a bit of", "usa", "bce"}
    assert len(d.stage_changes) == stats["rows_changed_vs_previous"]["stage_set"] == 49
    assert {x["lemma"] for x in d.field_changes} == {"mum", "p.e.", "e-mail"}  # the overridden previous rows
    assert d.display_changes == [{"lemma": "e-mail", "old": "E-MAIL", "new": "e-mail"}]
    assert d.sources_only == stats["rows_changed_vs_previous"]["sources_only"] == 3
    assert d.unchanged == 53 - 49 - 3 - 0  # mum/p.e. changed stages too; only e-mail's field change overlaps nothing
    # (b) the matrix: v1 rows 1 (zk) … 4 (cet6), ∅, new; v2 columns 1 (xs) … 5 (cet6), ∅
    assert list(d.matrix) == ["1 (zk)", "2 (gk)", "3 (cet4)", "4 (cet6)", "∅", "new"]
    assert list(d.matrix["new"]) == ["1 (xs)", "2 (zk)", "3 (gk)", "4 (cet4)", "5 (cet6)", "∅"]
    assert sum(d.matrix["new"].values()) == 32
    for row_label, code in (("1 (zk)", "zk"), ("2 (gk)", "gk"), ("3 (cet4)", "cet4"), ("4 (cet6)", "cet6")):
        assert sum(d.matrix[row_label].values()) == sum(1 for r in old.values() if D.first_stage(r) == code), row_label
    col_totals = {c: sum(row[c] for row in d.matrix.values()) for c in d.matrix["new"]}
    assert col_totals == {"1 (xs)": 34, "2 (zk)": 44, "3 (gk)": 4, "4 (cet4)": 0, "5 (cet6)": 2, "∅": 1}
    assert d.per_stage["xs"] == {"old": 0, "new": 34, "added": 34, "removed": 0}
    assert d.per_stage["gk"]["removed"] > 0 and d.per_stage["cet4"] == {"old": 28, "new": 28, "added": 0, "removed": 0}
    # (d) worth a look
    assert [x["lemma"] for x in d.lost_all_stages] == ["bookshelf"]
    assert d.network_new == []  # the builder stripped the two [网络] prefixes
    assert d.merged_heads == {"miss": ["Miss", "miss"], "p.e.": ["P.E.", "PE"]}
    assert {x["lemma"] for x in d.aliases} == {"mr.", "p.e.", "hot dog", "humorous"}
    # (e)
    assert d.ok and [i["name"] for i in d.invariants][:2] == ["new lemma set ⊇ old lemma set", "xs ⊆ zk"]


def test_main_on_the_fixture_pair_writes_md_and_json_and_exits_0(new_seed: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    md, js = tmp_path / "DIFF.md", tmp_path / "diff.json"
    rc = D.main([str(OLD), str(new_seed), "--md", str(md), "--json", str(js)])
    assert rc == 0
    err = capsys.readouterr().err
    assert "seed_diff: 53 → 85 records; +32 −0" in err and err.count("PASS") == 5 and "FAIL" not in err
    text = md.read_text(encoding="utf-8")
    for heading in ("## (a) Counts", "## (b) `stage_min` transition matrix", "## (e) Invariants", "## (d) Worth a human look", "## (c) Per-word lists"):
        assert heading in text
    assert "| old \\ new | 1 (xs) | 2 (zk) | 3 (gk) | 4 (cet4) | 5 (cet6) | ∅ | row total |" in text
    assert "| new | 2 | 29 | 1 | — | — | — | 32 |" in text
    assert "| **column total** | **34** | **44** | **4** | **0** | **2** | **1** | **85** |" in text
    assert text.index("## (e) Invariants") < text.index("## (c) Per-word lists")  # the invariants are in the first screen
    assert "| bookshelf | gk |" in text and "| e-mail | E-MAIL | e-mail |" in text
    data = json.loads(js.read_text(encoding="utf-8"))
    assert data["new_total"] == 85 and len(data["added"]) == 32 and all(i["ok"] for i in data["invariants"])


def test_rendering_is_stable_and_only_restricts_section_c(new_seed: Path):
    old, new = D.load_seed(OLD), D.load_seed(new_seed)
    d1, d2 = D.compute(old, new), D.compute(old, new)
    assert D.render_md(d1) == D.render_md(d2) and json.dumps(d1.as_dict()) == json.dumps(d2.as_dict())
    full = D.render_md(d1)
    added_only = D.render_md(d1, only="added")
    assert "### Added (32)" in full and "### Stage changes (49)" in full and "### Removed (0)" in full
    assert "### Added (32)" in added_only and "### Stage changes" not in added_only and "### Removed" not in added_only
    assert "## (e) Invariants" in added_only  # (a)/(b)/(d)/(e) are never dropped


def test_stats_default_is_the_sibling_file(new_seed: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    rc = D.main([str(OLD), str(new_seed)])
    assert rc == 0 and "match the file: PASS — ok" in capsys.readouterr().err
    alone = tmp_path / "alone.jsonl"
    alone.write_bytes(new_seed.read_bytes())
    rc = D.main([str(OLD), str(alone)])
    assert rc == 0 and "skipped (no stats.json)" in capsys.readouterr().err


# ------------------------------------------------------------------------------------------------ invariants → exit 1
def test_removed_lemma_fails_the_superset_invariant(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    old = write_seed(tmp_path / "old.jsonl", [v1("a", ["zk"]), v1("gone", ["gk"])])
    new = write_seed(tmp_path / "new.jsonl", [v2("a", ["xs", "zk"])])
    rc = D.main([str(old), str(new), "--md", str(tmp_path / "d.md")])
    assert rc == 1
    err = capsys.readouterr().err
    assert "new lemma set ⊇ old lemma set: FAIL" in err and "gone" in err
    assert "| gone | gk |" in (tmp_path / "d.md").read_text(encoding="utf-8")
    assert D.main([str(old), str(new), "--no-invariants"]) == 0


def test_xs_without_zk_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    old = write_seed(tmp_path / "old.jsonl", [v1("a", ["zk"])])
    new = write_seed(tmp_path / "new.jsonl", [v2("a", ["xs"])])
    assert D.main([str(old), str(new)]) == 1
    assert "xs ⊆ zk: FAIL — 1 violation(s): ['a']" in capsys.readouterr().err


def test_unknown_or_unordered_codes_and_lemma_mismatch_fail(tmp_path: Path):
    old = write_seed(tmp_path / "old.jsonl", [v1("a", ["zk"])])
    bad = write_seed(tmp_path / "bad.jsonl", [v2("a", ["zk", "xs"]), v2("b", ["cet9"]), {"word": "C word", "lemma": "c", "stages": [], "sources": [], "seed_v": 2}])
    d = D.compute(D.load_seed(old), D.load_seed(bad))
    by = {i["name"]: i for i in d.invariants}
    assert not by["stage codes ∈ STAGE_ORDER, in STAGE_ORDER order"]["ok"] and "cet9" in by["stage codes ∈ STAGE_ORDER, in STAGE_ORDER order"]["detail"]
    assert not by["lemma == normalise_lemma(word)"]["ok"] and "'c'" in by["lemma == normalise_lemma(word)"]["detail"]
    assert D.main([str(old), str(bad)]) == 1


def test_stats_mismatch_fails(new_seed: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    wrong = tmp_path / "stats.json"
    stats = json.loads((new_seed.parent / "stats.json").read_text(encoding="utf-8"))
    stats["per_stage"]["xs"] += 1
    wrong.write_text(json.dumps(stats), encoding="utf-8")
    assert D.main([str(OLD), str(new_seed), "--stats", str(wrong)]) == 1
    assert "match the file: FAIL — per_stage" in capsys.readouterr().err


def test_unreadable_input_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    assert D.main([str(tmp_path / "missing.jsonl"), str(OLD)]) == 2
    assert capsys.readouterr().err.startswith("seed_diff: ")


# ------------------------------------------------------------------------------------------------ matrix on a v2 → v2 pair
def test_v2_to_v2_matrix_uses_the_new_numbering_on_both_axes(tmp_path: Path):
    old = write_seed(tmp_path / "old.jsonl", [v2("a", ["xs", "zk"]), v2("b", ["gk"]), v2("c", [])])
    new = write_seed(tmp_path / "new.jsonl", [v2("a", ["xs", "zk"]), v2("b", ["zk", "gk"]), v2("c", []), v2("d", ["cet6"])])
    d = D.compute(D.load_seed(old), D.load_seed(new))
    assert list(d.matrix) == ["1 (xs)", "2 (zk)", "3 (gk)", "4 (cet4)", "5 (cet6)", "∅", "new"]
    assert d.matrix["3 (gk)"]["2 (zk)"] == 1 and d.matrix["∅"]["∅"] == 1 and d.matrix["new"]["5 (cet6)"] == 1
    assert d.stage_changes == [{"lemma": "b", "old": ["gk"], "new": ["zk", "gk"]}] and d.lost_all_stages == []
    assert [i["ok"] for i in d.invariants] == [True] * 5 and d.ok


def test_md_to_stdout(new_seed: Path, capsys: pytest.CaptureFixture[str]):
    assert D.main([str(OLD), str(new_seed), "--md", "-"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("# Seed diff") and "## (b)" in out


def test_labels_replace_the_paths_in_the_header(new_seed: Path, tmp_path: Path):
    """``make seed`` reads the baseline from a temporary copy of ``git show HEAD:…`` and labels both sides, so DIFF.md
    never names the temporary file (review S3b F5); without labels the paths are printed."""
    md = tmp_path / "DIFF.md"
    rc = D.main([str(OLD), str(new_seed), "--md", str(md), "--old-label", "HEAD:data/seed/vocab.jsonl.gz", "--new-label", "data/seed/vocab.jsonl.gz"])
    assert rc == 0
    text = md.read_text(encoding="utf-8")
    assert text.splitlines()[2].startswith("`HEAD:data/seed/vocab.jsonl.gz` (format v1, 53 records) → `data/seed/vocab.jsonl.gz` (format v2, 85 records).")
    assert str(OLD) not in text and str(new_seed) not in text
    assert D.main([str(OLD), str(new_seed), "--md", str(md)]) == 0
    assert md.read_text(encoding="utf-8").splitlines()[2].startswith(f"`{OLD}` (format v1, 53 records) → `{new_seed}` (format v2, 85 records).")
