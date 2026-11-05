"""seedbuild.diff — compare two seed files and write ``data/seed/DIFF.md`` (PLAN §4.8; ``scripts/seed_diff.py``).

Why a separate report: the importer only ever sees the new seed, and ``wd import-seed --dry-run`` (PLAN §4.7) compares
it with a DATABASE. The diff compares two seed FILES — the committed previous ``vocab.jsonl.gz`` and the freshly built
one — so a rebuild can be reviewed before it is packed and committed (``make seed`` runs it between the build and
``pack_seed.sh``; a failed invariant stops the pipeline before the archive is replaced). ``make seed`` reads the baseline
from a temporary copy of ``git show $(SEED_BASE):data/seed/vocab.jsonl.gz`` and passes ``--old-label`` / ``--new-label``
so the report header names the revision and the tracked archive, never the temporary file.

Records are aligned by lemma: a v2 record's own ``lemma`` key, otherwise ``words.normalise_lemma(word)`` (what the
importer computes for a v1 file). Sections of the Markdown (PLAN §4.8 (a)–(e)):

(a) counts — records, added, removed, stage-set changes, dictionary-field changes, ``sources``-only changes, display changes;
(b) the ``stage_min`` transition matrix (old first stage × new first stage, ``∅`` = no stage, ``new`` = added rows) and
    the per-stage ``+`` / ``−`` of the flags. Row / column labels carry the index of EACH file's numbering: a v1 file
    (no ``seed_v``, codes ``zk gk cet4 cet6``) counts ``zk`` as 1, a v2 file uses ``schemas.STAGE_INDEX`` (xs 1 … cet6 5),
    which is exactly the PLAN §4.8 table;
(c) per-word lists — added, removed, stage changes, field changes (``--only`` restricts the Markdown to one of them);
(d) worth a human look — words that lost every stage, added words whose translation still says ``[网络]``, the
    builder's ``merged_heads`` (from ``stats.json`` when present next to the new file or given with ``--stats``), rows with
    ``aliases``, display changes;
(e) invariants — the new lemma set ⊇ the old one (the seed never deletes), ``xs ⊆ zk``, every code ∈ ``STAGE_ORDER`` in
    ``STAGE_ORDER`` order, unique lemmas, and ``per_stage`` / ``total_words`` / ``first_stage`` equal to ``stats.json``
    when available. Any failure → exit 1 (``--no-invariants`` only reports, for comparing two historical versions).

Output is deterministic (sorted lists, no timestamps), so ``DIFF.md`` is stable across rebuilds of the same inputs.
"""

from __future__ import annotations

import argparse
import gzip
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from ..schemas import STAGE_INDEX, STAGE_ORDER
from ..services import words

log = logging.getLogger("wd.seedbuild.diff")

#: stage numbering of seed files before format v2 / migration 0011 (``stage_min`` 1..4)
V1_ORDER: tuple[str, ...] = ("zk", "gk", "cet4", "cet6")
#: dictionary fields compared for "field changes" (everything the importer writes except the membership keys)
FIELD_KEYS: tuple[str, ...] = (
    "word", "phonetic", "translation", "definition", "pos", "collins", "oxford", "exam_tags", "bnc", "frq", "exchange", "ecdict_id", "cet6_star",
)
NETWORK_MARK = "[网络]"
NONE_LABEL = "∅"
NEW_LABEL = "new"
ONLY_CHOICES: tuple[str, ...] = ("stages", "fields", "added", "removed")


class DiffError(RuntimeError):
    """A seed file cannot be read or aligned (duplicate lemma, malformed record)."""


# ---------------------------------------------------------------------------------------------- loading
def _read_text(path: Path) -> str:
    if path.suffix == ".gz":
        with gzip.open(path, "rb") as f:
            return f.read().decode("utf-8")
    return path.read_text(encoding="utf-8")


def record_lemma(rec: Mapping[str, Any]) -> str | None:
    """The alignment key: a v2 record's ``lemma``, else the importer's ``normalise_lemma(word)``."""
    lemma = rec.get("lemma")
    if isinstance(lemma, str) and lemma.strip():
        return lemma.strip()
    word = rec.get("word")
    return words.normalise_lemma(word) if isinstance(word, str) else None


def load_seed(path: Path) -> dict[str, dict[str, Any]]:
    """``{lemma: record}`` of a ``.jsonl`` / ``.jsonl.gz`` seed; duplicate lemmas and malformed lines are refused."""
    path = Path(path)
    if not path.is_file():
        raise DiffError(f"{path} does not exist")
    out: dict[str, dict[str, Any]] = {}
    try:
        text = _read_text(path)
    except (OSError, EOFError, gzip.BadGzipFile) as e:
        raise DiffError(f"cannot read {path}: {e}") from None
    for lineno, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except ValueError as e:
            raise DiffError(f"{path.name}:{lineno}: not a JSON record ({e})") from None
        if not isinstance(rec, dict):
            raise DiffError(f"{path.name}:{lineno}: not a JSON object")
        lemma = record_lemma(rec)
        if not lemma:
            raise DiffError(f"{path.name}:{lineno}: record has no lemma / word")
        if lemma in out:
            raise DiffError(f"{path.name}:{lineno}: duplicate lemma {lemma!r}")
        out[lemma] = rec
    return out


def seed_version(records: Mapping[str, Mapping[str, Any]]) -> int:
    """2 when any record says ``seed_v: 2`` (or lists ``xs``), else 1 — decides the index labels of (b)."""
    for rec in records.values():
        v = rec.get("seed_v")
        if isinstance(v, int) and not isinstance(v, bool) and v >= 2:
            return 2
        if STAGE_ORDER[0] in (rec.get("stages") or ()):
            return 2
    return 1


def stages_of(rec: Mapping[str, Any]) -> list[str]:
    raw = rec.get("stages") or []
    return [s for s in raw if isinstance(s, str)] if isinstance(raw, (list, tuple)) else []


def first_stage(rec: Mapping[str, Any]) -> str | None:
    present = set(stages_of(rec))
    for s in STAGE_ORDER:
        if s in present:
            return s
    return None


def stage_label(code: str | None, version: int) -> str:
    """``1 (zk)`` in a v1 file, ``2 (zk)`` in a v2 file, ``∅`` for no stage."""
    if code is None:
        return NONE_LABEL
    index = (V1_ORDER.index(code) + 1) if version == 1 and code in V1_ORDER else STAGE_INDEX.get(code, 0)
    return f"{index} ({code})"


# ---------------------------------------------------------------------------------------------- diff
@dataclass
class Diff:
    old_path: str
    new_path: str
    old_version: int
    new_version: int
    old_total: int
    new_total: int
    added: list[dict[str, Any]] = field(default_factory=list)  # {lemma, stages, sources, translation}
    removed: list[dict[str, Any]] = field(default_factory=list)  # {lemma, stages}
    stage_changes: list[dict[str, Any]] = field(default_factory=list)  # {lemma, old, new}
    field_changes: list[dict[str, Any]] = field(default_factory=list)  # {lemma, fields}
    sources_only: int = 0
    unchanged: int = 0
    display_changes: list[dict[str, Any]] = field(default_factory=list)  # {lemma, old, new}
    matrix: dict[str, dict[str, int]] = field(default_factory=dict)  # old label → new label → count
    per_stage: dict[str, dict[str, int]] = field(default_factory=dict)  # code → {old, new, added, removed}
    lost_all_stages: list[dict[str, Any]] = field(default_factory=list)  # {lemma, old}
    network_new: list[str] = field(default_factory=list)
    merged_heads: dict[str, list[str]] = field(default_factory=dict)
    aliases: list[dict[str, Any]] = field(default_factory=list)  # {lemma, aliases}
    invariants: list[dict[str, Any]] = field(default_factory=list)  # {name, ok, detail}

    @property
    def ok(self) -> bool:
        return all(i["ok"] for i in self.invariants)

    def as_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


def _matrix_labels(version: int, *, with_new: bool) -> list[str]:
    codes = V1_ORDER if version == 1 else STAGE_ORDER
    labels = [stage_label(c, version) for c in codes] + [NONE_LABEL]
    return labels + [NEW_LABEL] if with_new else labels


def compute(
    old: Mapping[str, Mapping[str, Any]],
    new: Mapping[str, Mapping[str, Any]],
    *,
    old_path: str = "old",
    new_path: str = "new",
    stats: Mapping[str, Any] | None = None,
) -> Diff:
    """All sections of the report over two aligned seeds; ``stats`` is the new seed's ``stats.json`` (optional)."""
    ov, nv = seed_version(old), seed_version(new)
    d = Diff(old_path=old_path, new_path=new_path, old_version=ov, new_version=nv, old_total=len(old), new_total=len(new))
    rows = _matrix_labels(ov, with_new=True)
    cols = _matrix_labels(nv, with_new=False)
    d.matrix = {r: {c: 0 for c in cols} for r in rows}
    for lemma in sorted(new):
        rec = new[lemma]
        col = stage_label(first_stage(rec), nv)
        prev = old.get(lemma)
        if prev is None:
            d.added.append({"lemma": lemma, "stages": stages_of(rec), "sources": list(rec.get("sources") or []), "translation": (rec.get("translation") or [""])[0] if rec.get("translation") else ""})
            d.matrix[NEW_LABEL][col] += 1
            if any(NETWORK_MARK in str(t) for t in (rec.get("translation") or [])):
                d.network_new.append(lemma)
            if rec.get("aliases"):
                d.aliases.append({"lemma": lemma, "aliases": list(rec["aliases"])})
            continue
        d.matrix[stage_label(first_stage(prev), ov)][col] += 1
        old_st, new_st = stages_of(prev), stages_of(rec)
        changed_fields = [k for k in FIELD_KEYS if prev.get(k) != rec.get(k)]
        if set(old_st) != set(new_st):
            d.stage_changes.append({"lemma": lemma, "old": old_st, "new": new_st})
            if old_st and not new_st:
                d.lost_all_stages.append({"lemma": lemma, "old": old_st})
        if changed_fields:
            d.field_changes.append({"lemma": lemma, "fields": changed_fields})
            if "word" in changed_fields:
                d.display_changes.append({"lemma": lemma, "old": prev.get("word"), "new": rec.get("word")})
        if set(old_st) == set(new_st) and not changed_fields:
            if set(prev.get("sources") or []) != set(rec.get("sources") or []):
                d.sources_only += 1
            else:
                d.unchanged += 1
        if rec.get("aliases"):
            d.aliases.append({"lemma": lemma, "aliases": list(rec["aliases"])})
    for lemma in sorted(set(old) - set(new)):
        d.removed.append({"lemma": lemma, "stages": stages_of(old[lemma])})
    for code in STAGE_ORDER:
        old_has = {l for l, r in old.items() if code in stages_of(r)}
        new_has = {l for l, r in new.items() if code in stages_of(r)}
        d.per_stage[code] = {"old": len(old_has), "new": len(new_has), "added": len(new_has - old_has), "removed": len(old_has - new_has)}
    if stats and isinstance(stats.get("merged_heads"), Mapping):
        d.merged_heads = {k: list(v) for k, v in sorted(stats["merged_heads"].items())}
    d.invariants = check_invariants(old, new, stats)
    return d


def check_invariants(old: Mapping[str, Mapping[str, Any]], new: Mapping[str, Mapping[str, Any]], stats: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """PLAN §4.8 (e): each entry ``{name, ok, detail}``; the caller fails the run when any ``ok`` is False."""
    out: list[dict[str, Any]] = []
    missing = sorted(set(old) - set(new))
    out.append({"name": "new lemma set ⊇ old lemma set", "ok": not missing, "detail": f"{len(missing)} removed: {missing[:20]}" if missing else f"{len(old)} old lemmas all present"})
    xs, zk = STAGE_ORDER[0], STAGE_ORDER[1]
    bad = sorted(l for l, r in new.items() if xs in stages_of(r) and zk not in stages_of(r))
    out.append({"name": f"{xs} ⊆ {zk}", "ok": not bad, "detail": f"{len(bad)} violation(s): {bad[:20]}" if bad else f"{sum(1 for r in new.values() if xs in stages_of(r))} {xs} rows all carry {zk}"})
    unknown = sorted({s for r in new.values() for s in stages_of(r) if s not in STAGE_ORDER})
    unsorted = sorted(l for l, r in new.items() if stages_of(r) != [s for s in STAGE_ORDER if s in stages_of(r)])
    out.append({"name": "stage codes ∈ STAGE_ORDER, in STAGE_ORDER order", "ok": not unknown and not unsorted, "detail": f"unknown {unknown}, unsorted {unsorted[:10]}" if (unknown or unsorted) else "ok"})
    mismatch = sorted(l for l, r in new.items() if words.normalise_lemma(r.get("word") or "") != l)
    out.append({"name": "lemma == normalise_lemma(word)", "ok": not mismatch, "detail": f"{len(mismatch)} mismatch(es): {mismatch[:20]}" if mismatch else "ok"})
    if stats is not None:
        per_stage = {s: sum(1 for r in new.values() if s in stages_of(r)) for s in STAGE_ORDER}
        first = {s: sum(1 for r in new.values() if first_stage(r) == s) for s in STAGE_ORDER}
        first["none"] = sum(1 for r in new.values() if first_stage(r) is None)
        problems = []
        if stats.get("total_words") != len(new):
            problems.append(f"total_words {stats.get('total_words')} != {len(new)}")
        if stats.get("per_stage") != per_stage:
            problems.append(f"per_stage {stats.get('per_stage')} != {per_stage}")
        if stats.get("first_stage") != first:
            problems.append(f"first_stage {stats.get('first_stage')} != {first}")
        out.append({"name": "stats.json total_words / per_stage / first_stage match the file", "ok": not problems, "detail": "; ".join(problems) or "ok"})
    else:
        out.append({"name": "stats.json total_words / per_stage / first_stage match the file", "ok": True, "detail": "skipped (no stats.json)"})
    return out


# ---------------------------------------------------------------------------------------------- rendering
def _cell(v: Any) -> str:
    s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
    return s.replace("|", "\\|").replace("\n", " ")


def _st(stages: Iterable[str]) -> str:
    s = " ".join(stages)
    return s or NONE_LABEL


def render_md(d: Diff, *, only: str | None = None) -> str:
    """The ``DIFF.md`` text (deterministic; ``only`` restricts section (c) to one list)."""
    L: list[str] = []
    L.append("# Seed diff")
    L.append("")
    L.append(f"`{d.old_path}` (format v{d.old_version}, {d.old_total:,} records) → `{d.new_path}` (format v{d.new_version}, {d.new_total:,} records). "
             "Generated by `scripts/seed_diff.py` (`make seed`); PLAN §4.8. Overwritten on every rebuild — history is in git.")
    L.append("")
    L.append("## (a) Counts")
    L.append("")
    L.append("| what | count |")
    L.append("|---|---|")
    L.append(f"| records old → new | {d.old_total:,} → {d.new_total:,} ({d.new_total - d.old_total:+,}) |")
    L.append(f"| added lemmas | {len(d.added):,} |")
    L.append(f"| removed lemmas | {len(d.removed):,} |")
    L.append(f"| stage-set changes (existing lemmas) | {len(d.stage_changes):,} |")
    L.append(f"| dictionary-field changes (existing lemmas) | {len(d.field_changes):,} |")
    L.append(f"| `sources`-only changes | {d.sources_only:,} |")
    L.append(f"| unchanged rows | {d.unchanged:,} |")
    L.append(f"| display (`word`) changes | {len(d.display_changes):,} |")
    L.append("")
    L.append("## (b) `stage_min` transition matrix")
    L.append("")
    L.append(f"Rows: first stage in the old file (v{d.old_version} numbering) and `new` for added lemmas; columns: first stage in the new file (v{d.new_version} numbering); `∅` = no stage.")
    L.append("")
    cols = list(next(iter(d.matrix.values())).keys()) if d.matrix else []
    L.append("| old \\ new | " + " | ".join(cols) + " | row total |")
    L.append("|---|" + "---|" * (len(cols) + 1))
    col_totals = {c: 0 for c in cols}
    for row, cells in d.matrix.items():
        total = sum(cells.values())
        for c in cols:
            col_totals[c] += cells[c]
        L.append(f"| {row} | " + " | ".join(f"{cells[c]:,}" if cells[c] else "—" for c in cols) + f" | {total:,} |")
    L.append("| **column total** | " + " | ".join(f"**{col_totals[c]:,}**" for c in cols) + f" | **{sum(col_totals.values()):,}** |")
    L.append("")
    L.append("Per-stage flags:")
    L.append("")
    L.append("| stage | old rows | new rows | + | − |")
    L.append("|---|---|---|---|---|")
    for code, c in d.per_stage.items():
        L.append(f"| {code} | {c['old']:,} | {c['new']:,} | +{c['added']:,} | −{c['removed']:,} |")
    L.append("")
    L.append("## (e) Invariants")
    L.append("")
    L.append("| invariant | result | detail |")
    L.append("|---|---|---|")
    for inv in d.invariants:
        L.append(f"| {inv['name']} | {'PASS' if inv['ok'] else 'FAIL'} | {_cell(inv['detail'])} |")
    L.append("")
    L.append("## (d) Worth a human look")
    L.append("")
    L.append(f"### Lost every stage ({len(d.lost_all_stages):,})")
    L.append("")
    if d.lost_all_stages:
        L.append("| lemma | old stages |")
        L.append("|---|---|")
        for x in d.lost_all_stages:
            L.append(f"| {_cell(x['lemma'])} | {_st(x['old'])} |")
    else:
        L.append("none")
    L.append("")
    L.append(f"### Added words whose translation still contains `{NETWORK_MARK}` ({len(d.network_new):,})")
    L.append("")
    L.append(", ".join(f"`{_cell(l)}`" for l in d.network_new) if d.network_new else "none")
    L.append("")
    L.append(f"### Merged heads — several official spellings → one lemma ({len(d.merged_heads):,})")
    L.append("")
    if d.merged_heads:
        L.append("| lemma | spellings |")
        L.append("|---|---|")
        for lemma, spellings in d.merged_heads.items():
            L.append(f"| {_cell(lemma)} | {_cell(', '.join(spellings))} |")
    else:
        L.append("none (no stats.json next to the new file, or no merges)")
    L.append("")
    L.append(f"### Rows with `aliases` ({len(d.aliases):,})")
    L.append("")
    if d.aliases:
        L.append("| lemma | aliases |")
        L.append("|---|---|")
        for x in d.aliases:
            L.append(f"| {_cell(x['lemma'])} | {_cell(', '.join(x['aliases']))} |")
    else:
        L.append("none")
    L.append("")
    L.append(f"### Display changes ({len(d.display_changes):,})")
    L.append("")
    if d.display_changes:
        L.append("| lemma | old | new |")
        L.append("|---|---|---|")
        for x in d.display_changes:
            L.append(f"| {_cell(x['lemma'])} | {_cell(x['old'])} | {_cell(x['new'])} |")
    else:
        L.append("none")
    L.append("")
    L.append("## (c) Per-word lists")
    L.append("")
    if only in (None, "added"):
        L.append(f"### Added ({len(d.added):,})")
        L.append("")
        if d.added:
            L.append("| lemma | stages | sources | first translation line |")
            L.append("|---|---|---|---|")
            for x in d.added:
                L.append(f"| {_cell(x['lemma'])} | {_st(x['stages'])} | {_cell(' '.join(x['sources']))} | {_cell(x['translation'])} |")
        else:
            L.append("none")
        L.append("")
    if only in (None, "removed"):
        L.append(f"### Removed ({len(d.removed):,})")
        L.append("")
        if d.removed:
            L.append("| lemma | old stages |")
            L.append("|---|---|")
            for x in d.removed:
                L.append(f"| {_cell(x['lemma'])} | {_st(x['stages'])} |")
        else:
            L.append("none")
        L.append("")
    if only in (None, "stages"):
        L.append(f"### Stage changes ({len(d.stage_changes):,})")
        L.append("")
        if d.stage_changes:
            L.append("| lemma | old | new |")
            L.append("|---|---|---|")
            for x in d.stage_changes:
                L.append(f"| {_cell(x['lemma'])} | {_st(x['old'])} | {_st(x['new'])} |")
        else:
            L.append("none")
        L.append("")
    if only in (None, "fields"):
        L.append(f"### Dictionary-field changes ({len(d.field_changes):,})")
        L.append("")
        if d.field_changes:
            L.append("| lemma | fields |")
            L.append("|---|---|")
            for x in d.field_changes:
                L.append(f"| {_cell(x['lemma'])} | {_cell(', '.join(x['fields']))} |")
        else:
            L.append("none")
        L.append("")
    return "\n".join(L)


def _write(path: str, text: str) -> None:
    """Write a report to a path, ``-`` (stdout) or ``/dev/stdout``; a reader that went away (``| head``) is not an error."""
    try:
        if path == "-":
            sys.stdout.write(text)
            sys.stdout.flush()
            return
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    except BrokenPipeError:
        # ``seed_diff.py … --md /dev/stdout | head -80``: head closed the pipe; park stdout on /dev/null so the
        # interpreter's final flush does not raise again, and carry on with the stderr summary.
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="seed_diff.py", description="Diff two seed files (PLAN §4.8): counts, stage_min matrix, per-word lists, invariants.")
    ap.add_argument("old", type=Path, help="previous seed (.jsonl or .jsonl.gz)")
    ap.add_argument("new", type=Path, help="new seed (.jsonl or .jsonl.gz)")
    ap.add_argument("--md", default=None, help="write the Markdown report here ('-' = stdout)")
    ap.add_argument("--json", default=None, help="write the report as JSON here ('-' = stdout)")
    ap.add_argument("--stats", type=Path, default=None, help="the new seed's stats.json (default: stats.json next to NEW when present)")
    ap.add_argument("--only", choices=ONLY_CHOICES, default=None, help="restrict section (c) of the Markdown to one list")
    ap.add_argument("--no-invariants", action="store_true", help="report failed invariants without exit 1 (comparing historical versions)")
    ap.add_argument("--old-label", default=None, help="name printed for OLD in the report header instead of its path (make seed: '<rev>:data/seed/vocab.jsonl.gz')")
    ap.add_argument("--new-label", default=None, help="name printed for NEW in the report header instead of its path")
    a = ap.parse_args(argv)
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stderr)
    stats_path = a.stats if a.stats is not None else (a.new.parent / "stats.json" if (a.new.parent / "stats.json").is_file() else None)
    try:
        old, new = load_seed(a.old), load_seed(a.new)
        stats = json.loads(Path(stats_path).read_text(encoding="utf-8")) if stats_path else None
    except (DiffError, OSError, ValueError) as e:
        print(f"seed_diff: {e}", file=sys.stderr)  # stderr directly: the CLI must report regardless of logging setup
        return 2
    d = compute(old, new, old_path=a.old_label or str(a.old), new_path=a.new_label or str(a.new), stats=stats)
    if a.md:
        _write(a.md, render_md(d, only=a.only))
    if a.json:
        _write(a.json, json.dumps(d.as_dict(), ensure_ascii=False, indent=1) + "\n")
    summary = (
        f"seed_diff: {d.old_total:,} → {d.new_total:,} records; +{len(d.added):,} −{len(d.removed):,}; "
        f"stage changes {len(d.stage_changes):,}; field changes {len(d.field_changes):,}; sources-only {d.sources_only:,}"
    )
    print(summary, file=sys.stderr)
    for inv in d.invariants:
        print(f"invariant {inv['name']}: {'PASS' if inv['ok'] else 'FAIL'} — {inv['detail']}", file=sys.stderr)
    if not d.ok and not a.no_invariants:
        return 1
    return 0
