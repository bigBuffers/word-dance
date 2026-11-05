"""seedbuild.build — the seed builder: manifest → official lists → membership → ``vocab.jsonl`` + ``stats.json`` + ``ATTRIBUTION.md``.

Specification: ``docs/analysis/2026-11-05-stages-regions-images/design/PLAN.md`` §4.2 (set algebra and build-time
assertions), §4.4 (``sources`` tokens), §4.5 (package layout, CLI, signatures, seed record v2, determinism), §4.6
(``stats.json`` v2 and the generated ``ATTRIBUTION.md``); worked numbers in ``design/word-lists/SYNTHESIS.md`` §3.4–§3.6.
Entry point: ``scripts/build_seed.py`` (``make seed``); the grammar of the list lines lives in :mod:`.normalise`.

Why a builder that reads the previous seed: the official lists only say which headwords belong to 小学 / 初中 / 高中.
Dictionary data (ECDICT), CET membership (the optional mahavivo lists) and the existing rows come from the previous
``vocab.jsonl.gz`` (the committed seed, ``stats.json.total_words`` rows) — the build is a RELABEL of the previous seed plus
new rows for headwords it did not have.
Nothing is ever deleted (PLAN §4.2 "宇宙 ⊇ 上一版 lemma 集"): a word that left every official list keeps its row with
``stages: []`` and its old membership recorded as ``legacy:zk`` / ``legacy:gk`` tokens.

Pipeline (``build()``)
----------------------
1. :func:`load_manifest` — ``format == 2``, known ``format``/``policy`` values, ``stages ⊆ schemas.STAGE_ORDER``, every
   list file present, ``SHA256SUMS`` matching, ``expect_rows == non-comment line count``; ``aliases.tsv`` (R5) and
   ``overrides.tsv`` (≤ 30 rows, ``field ∈ translation | word | phonetic | definition | drop``) parsed and validated.
2. :func:`load_previous` — lemma (``normalise.lemma_of(word)``, never through the aliases) → record; duplicates refused.
3. :func:`collect_members` — every list line through :func:`normalise.split_head` / :func:`normalise.resolve_phrase`
   (R1–R12), the appendix group policies (``member: false``, ``single_token``), the existence check against ECDICT ∪
   previous (``policy: main`` → failure, ``appendix``/``phrases`` → ``skipped``), :func:`normalise.merge_heads` (R6) and
   :func:`normalise.inherit_forms` (R8, ``official`` = heads ∪ variants); then the assertions of PLAN §4.2:
   ① ``xs ⊆ zk``, ② every code ∈ ``STAGE_ORDER``, ③ the universe contains every previous lemma (an ``overrides.tsv``
   ``drop`` of a previous lemma is refused), ④ every ``main`` head resolves, ⑤ one record per lemma.
4. :func:`make_records` — previous lemmas keep their dictionary fields byte for byte and only get new ``stages`` /
   ``sources`` / ``aliases`` / ``variant_of``; new lemmas are generated from the ECDICT row (field mapping of the
   retired ``scripts/build_seed.py`` ``make_record``); CET flags: previous rows keep theirs, new rows take ECDICT's
   ``cet4``/``cet6`` tags, the external mahavivo lists are unioned in when ``--wordlists`` is given; then
   ``overrides.tsv`` (``translation`` replaces the whole list, ``word`` the display), then the ``[网络] `` prefix is
   stripped from a NEW row's first translation line and counted; ⑥ a new row with an empty first translation line
   fails the build (``stats.empty_translation``).
5. Output — records sorted by ``(stage_to_index(stage_min) if stage_min else 99, lemma)``, one JSON object per line in
   the fixed key order :data:`RECORD_KEYS`, ``ensure_ascii=False``, LF, no timestamp: two builds from the same inputs
   are byte-identical and ``stats.content_sha256`` (sha256 of ``vocab.jsonl``) is what the importer stores as
   ``kv.seed_version``. A rebuild whose ``--previous`` is the output of the previous rebuild gives the same bytes again
   (the relabel is idempotent). ``make seed`` nevertheless always passes the COMMITTED seed (``git show
   $(SEED_BASE):data/seed/vocab.jsonl.gz``, default HEAD) as ``--previous`` — never the working-tree archive that
   ``pack_seed.sh`` has just replaced — so ``stats.json`` (``previous_sha256``, ``new_words``, ``rows_changed_vs_previous``)
   describes the change against the last commit and a second run reproduces it byte for byte (impl-review S3b F1).
6. Before anything is written every record is checked once more the way the importer will see it:
   ``lemma == words.normalise_lemma(word)`` (:func:`check_lemmas`; ``normalise.lemma_of`` folds diacritics, the
   importer's ``normalise_lemma`` does not), so a mismatch is an exit 2 of the build, not a ``lemma_mismatch`` at import.

Exit codes of :func:`main`: 0 built; 2 manifest or build failure (nothing written). ``--no-strict`` downgrades the
list-content checks (a ``main`` head that is missing or fails R12, ``xs ⊄ zk``, an empty translation) to warnings so an
operator can inspect the output while fixing a transcription; the structural guards (format, checksums, row counts,
unknown stage codes, retain, duplicate lemmas) always fail.

Seed record v2 (PLAN §4.5; what ``wd.seed`` imports)
-----------------------------------------------------
``word`` display · ``lemma`` (== ``words.normalise_lemma(word)``) · ``phonetic, translation[], definition[], pos,
collins, oxford, exam_tags[], bnc, frq, exchange{}, ecdict_id, cet6_star`` as v1 · ``stages[]`` codes in ``STAGE_ORDER``
order · ``sources[]`` sorted tokens (PLAN §4.4) · ``aliases[]`` only when present (``["mr"]`` → ``word_forms(kind='alias')``)
· ``variant_of`` only on bracket-variant rows (``color`` → ``"colour"``) · ``seed_v: 2``.
"""

from __future__ import annotations

import argparse
import collections
import gzip
import hashlib
import json
import logging
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from .. import schemas
from ..schemas import STAGE_ORDER, stage_to_index
from ..services import words
from ..services.ecdict import COLUMNS as ECDICT_COLUMNS
from ..services.ecdict import EXAM_TAGS, EcdictEntry
from . import normalise as N

log = logging.getLogger("wd.seedbuild")

SEED_V = 2
#: ECDICT release the dictionary fields come from (``deploy/fetch_ecdict.sh`` pins the same ``ecdict-sqlite-28.zip``);
#: ``--ecdict-release`` overrides it for a build against another release.
ECDICT_RELEASE = "1.0.28"
ECDICT_ASSET = "ecdict-sqlite-28.zip"  # the release asset of ECDICT_RELEASE that deploy/fetch_ecdict.sh downloads
FORMATS: tuple[str, ...] = ("heads", "tsv", "phrases")
POLICIES: tuple[str, ...] = ("main", "appendix", "phrases", "reference")
OVERRIDE_FIELDS: tuple[str, ...] = ("translation", "word", "phonetic", "definition", "drop")
OVERRIDES_MAX = 30  # PLAN §4.1: ≤ 30 hand-written rows
EXTERNAL_MODES: tuple[str, ...] = ("rich", "plain")
NETWORK_PREFIX = "[网络]"
CET_STAGES: tuple[str, ...] = ("cet4", "cet6")
#: tokens copied from a previous record (PLAN §4.4: ``ecdict``/``cet*`` unchanged; ``legacy:*`` once written stay)
CARRIED_TOKENS: frozenset[str] = frozenset({"ecdict", "cet4", "cet6", "cet46"})
LEGACY_PREFIX = "legacy:"
INHERIT_PREFIX = "inherit:"
#: the stage codes of a v1 seed (before migration 0011) whose flags become ``legacy:*`` tokens
LEGACY_CODES: tuple[str, ...] = ("zk", "gk")
#: fixed key order of a v2 record (PLAN §4.5 table); ``aliases`` / ``variant_of`` only when present
RECORD_KEYS: tuple[str, ...] = (
    "word", "lemma", "phonetic", "translation", "definition", "pos", "collins", "oxford", "exam_tags", "bnc", "frq",
    "exchange", "ecdict_id", "cet6_star", "stages", "sources", "aliases", "variant_of", "seed_v",
)
#: dictionary keys copied verbatim from a previous record (test (d) of PLAN §6 S3)
DICT_KEYS: tuple[str, ...] = (
    "phonetic", "translation", "definition", "pos", "collins", "oxford", "exam_tags", "bnc", "frq", "exchange", "ecdict_id",
)
KINDS: tuple[str, ...] = ("word", "phrase", "abbreviation", "proper_noun")
STAGELESS_SORT = 99

# mahavivo list grammar (the retired scripts/build_seed.py, with the R1 fold applied first and the RICH_RE defect of
# PLAN §4.3 fixed: a relaxed head pattern, ``a (an)`` yields two heads, only a lone CAPITAL letter is a section header)
_MAHAVIVO_PLAIN_RE = re.compile(r"^[A-Za-z][A-Za-z'\-\.]*(?: [A-Za-z][A-Za-z'\-\.]*){0,3}$")
_MAHAVIVO_RICH_RE = re.compile(r"^([A-Za-z][A-Za-z'\-\.]*(?: [A-Za-z][A-Za-z'\-\.]*){0,3})(?:\s*\(([^)]*)\))?(?=\s|\[|/|$)")
_MAHAVIVO_POS_RE = re.compile(r"^(n|v|vt|vi|a|ad|adj|adv|prep|conj|pron|art|num|int|interj|aux|modal|abbr|pl|phr)\.?$", re.I)


# ---------------------------------------------------------------------------------------------- errors
class ManifestError(ValueError):
    """``manifest.json`` / ``SHA256SUMS`` / ``aliases.tsv`` / ``overrides.tsv`` or a list file violates PLAN §4.1."""


class BuildError(RuntimeError):
    """A build-time assertion of PLAN §4.2 failed (exit 2, nothing written)."""


# ---------------------------------------------------------------------------------------------- manifest
@dataclass(frozen=True)
class GroupSpec:
    """One appendix group: the stages it grants, whether only single-token heads count, whether it grants at all."""

    stages: tuple[str, ...] = ()
    single_token: bool = False
    member: bool = True


@dataclass(frozen=True)
class ListSpec:
    id: str
    file: Path
    format: str
    policy: str
    stages: tuple[str, ...]
    expect_rows: int
    columns: tuple[str, ...] = ()
    groups: Mapping[str, GroupSpec] = field(default_factory=dict)
    level_token: str | None = None
    provisional: bool = False
    title: str = ""


@dataclass(frozen=True)
class ExternalSpec:
    """A mahavivo CET file (``manifest.external.lists``): ``stages`` or ``stages_rule`` or ``flag``."""

    id: str
    file: str
    mode: str
    stages: tuple[str, ...] = ()
    stages_rule: str | None = None
    flag: str | None = None


@dataclass(frozen=True)
class Manifest:
    path: Path
    title: str
    lists: tuple[ListSpec, ...]
    external: tuple[ExternalSpec, ...]
    external_note: str
    aliases: Mapping[str, str]
    overrides: Mapping[str, Mapping[str, str]]
    inherit: Mapping[str, tuple[str, ...]]
    member_tags: tuple[str, ...]
    checksums: Mapping[str, str]

    @property
    def dir(self) -> Path:
        return self.path.parent

    @property
    def drops(self) -> frozenset[str]:
        """Lemmas with an ``overrides.tsv`` ``drop`` row: never members, never rows (PLAN §4.1)."""
        return frozenset(lemma for lemma, fields in self.overrides.items() if "drop" in fields)


def read_rows(path: Path) -> list[str]:
    """Non-comment, non-blank lines of a list file (``#`` whole-line comments; UTF-8; LF), trailing newline removed only."""
    out: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        out.append(line.rstrip("\r\n"))
    return out


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_path(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_checksums(path: Path) -> dict[str, str]:
    """``SHA256SUMS`` in ``shasum -a 256`` format (``<hex><two spaces>[*]<name>``) → ``{name: hex}``."""
    out: dict[str, str] = {}
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        parts = s.split(None, 1)
        if len(parts) != 2 or not re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            raise ManifestError(f"{path.name} line {lineno}: expected '<sha256>  <file>', got {line!r}")
        out[parts[1].lstrip("*")] = parts[0].lower()
    return out


def load_overrides(text: str) -> dict[str, dict[str, str]]:
    """``overrides.tsv`` → ``{lemma: {field: value}}`` (PLAN §4.1; ``lemma<TAB>field<TAB>value[<TAB>note]``).

    ``drop`` rows may have an empty value; every other field needs one. A ``word`` override must keep the lemma
    (``normalise_lemma(value) == lemma``), otherwise the importer would key the row under another lemma.
    """
    out: dict[str, dict[str, str]] = {}
    rows = 0
    for lineno, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        cols = line.rstrip("\r\n").split("\t")
        if len(cols) < 3:
            raise ManifestError(f"overrides.tsv line {lineno}: expected lemma<TAB>field<TAB>value, got {line!r}")
        lemma, fld, value = N.lemma_of(cols[0]), cols[1].strip(), cols[2].strip()
        if not lemma:
            raise ManifestError(f"overrides.tsv line {lineno}: empty lemma")
        if fld not in OVERRIDE_FIELDS:
            raise ManifestError(f"overrides.tsv line {lineno}: field {fld!r} not in {OVERRIDE_FIELDS}")
        if fld != "drop" and not value:
            raise ManifestError(f"overrides.tsv line {lineno}: {fld} override of {lemma!r} has no value")
        if fld == "word" and words.normalise_lemma(value) != lemma:
            raise ManifestError(f"overrides.tsv line {lineno}: word override {value!r} does not keep the lemma {lemma!r}")
        fields = out.setdefault(lemma, {})
        if fld in fields:
            raise ManifestError(f"overrides.tsv line {lineno}: duplicate {fld} override for {lemma!r}")
        fields[fld] = value
        rows += 1
    if rows > OVERRIDES_MAX:
        raise ManifestError(f"overrides.tsv has {rows} rows; PLAN §4.1 allows at most {OVERRIDES_MAX}")
    return out


def _stages(raw: Any, where: str) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list) or not all(isinstance(s, str) for s in raw):
        raise ManifestError(f"{where}: stages must be a list of stage codes")
    unknown = [s for s in raw if s not in STAGE_ORDER]
    if unknown:
        raise ManifestError(f"{where}: stage codes {unknown} are not in schemas.STAGE_ORDER {list(STAGE_ORDER)}")
    return tuple(s for s in STAGE_ORDER if s in raw)


def _list_spec(raw: Mapping[str, Any], base: Path) -> ListSpec:
    lid = str(raw.get("id") or "")
    where = f"manifest list {lid or '?'}"
    if not lid or not isinstance(raw.get("file"), str):
        raise ManifestError(f"{where}: id and file are required")
    fmt, policy = str(raw.get("format")), str(raw.get("policy"))
    if fmt not in FORMATS:
        raise ManifestError(f"{where}: format {fmt!r} not in {FORMATS}")
    if policy not in POLICIES:
        raise ManifestError(f"{where}: policy {policy!r} not in {POLICIES}")
    if (fmt == "phrases") != (policy == "phrases"):
        raise ManifestError(f"{where}: format 'phrases' and policy 'phrases' go together")
    columns = tuple(str(c) for c in (raw.get("columns") or ()))
    groups: dict[str, GroupSpec] = {}
    if fmt == "tsv":
        if "word" not in columns and policy != "reference":  # archived tables (country names, printed forms) have their own columns
            raise ManifestError(f"{where}: a tsv list needs a 'word' column")
    elif columns:
        raise ManifestError(f"{where}: columns only apply to format 'tsv'")
    if policy == "appendix":
        raw_groups = raw.get("groups")
        if fmt != "tsv" or "group" not in columns or not isinstance(raw_groups, Mapping) or not raw_groups:
            raise ManifestError(f"{where}: an appendix list needs format 'tsv', a 'group' column and 'groups'")
        for name, g in raw_groups.items():
            if not isinstance(g, Mapping):
                raise ManifestError(f"{where}: group {name!r} must be an object")
            member = bool(g.get("member", True))
            stages = _stages(g.get("stages"), f"{where} group {name!r}") if member else ()
            if member and not stages:
                raise ManifestError(f"{where}: group {name!r} grants no stage")
            groups[str(name)] = GroupSpec(stages=stages, single_token=bool(g.get("single_token", False)), member=member)
    elif raw.get("groups") is not None:
        raise ManifestError(f"{where}: groups only apply to policy 'appendix'")
    stages = _stages(raw.get("stages"), where)
    if policy in ("main", "phrases") and not stages:
        raise ManifestError(f"{where}: policy {policy!r} needs stages")
    if policy in ("appendix", "reference") and stages:
        raise ManifestError(f"{where}: policy {policy!r} takes its stages from groups / grants none")
    level_token = raw.get("level_token")
    if level_token is not None:
        if not isinstance(level_token, str) or "{level}" not in level_token or "level" not in columns:
            raise ManifestError(f"{where}: level_token needs a '{{level}}' placeholder and a 'level' column")
    expect_rows = raw.get("expect_rows")
    if not isinstance(expect_rows, int) or isinstance(expect_rows, bool) or expect_rows < 0:
        raise ManifestError(f"{where}: expect_rows must be a non-negative integer")
    return ListSpec(
        id=lid,
        file=base / raw["file"],
        format=fmt,
        policy=policy,
        stages=stages,
        expect_rows=expect_rows,
        columns=columns,
        groups=groups,
        level_token=level_token,
        provisional=bool(raw.get("provisional", False)),
        title=str(raw.get("title") or ""),
    )


def load_manifest(path: Path) -> Manifest:
    """Read and validate ``manifest.json`` (``format: 2``) with its sibling ``SHA256SUMS`` / ``aliases.tsv`` / ``overrides.tsv``.

    Every check of PLAN §4.5 is a :class:`ManifestError`: unknown format/policy, a stage code outside
    ``schemas.STAGE_ORDER``, a missing list file, a sha256 that differs from ``SHA256SUMS`` (or a file absent from it),
    ``expect_rows`` ≠ the file's non-comment line count, a duplicate list id.
    """
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ManifestError(f"cannot read {path}: {e}") from None
    if not isinstance(raw, Mapping) or raw.get("format") != 2:
        raise ManifestError(f"{path.name}: expected \"format\": 2 (got {raw.get('format') if isinstance(raw, Mapping) else raw!r})")
    base = path.parent
    checks_name = raw.get("checksums") or "SHA256SUMS"
    checks_path = base / str(checks_name)
    if not checks_path.is_file():
        raise ManifestError(f"{path.name}: checksums file {checks_path} is missing")
    checksums = load_checksums(checks_path)

    aliases_path = base / str(raw.get("aliases") or "aliases.tsv")
    overrides_path = base / str(raw.get("overrides") or "overrides.tsv")
    for p in (aliases_path, overrides_path):
        if not p.is_file():
            raise ManifestError(f"{path.name}: {p.name} is missing")
    try:
        aliases = N.load_aliases(aliases_path.read_text(encoding="utf-8"))
    except ValueError as e:
        raise ManifestError(str(e)) from None
    overrides = load_overrides(overrides_path.read_text(encoding="utf-8"))

    raw_lists = raw.get("lists")
    if not isinstance(raw_lists, list) or not raw_lists:
        raise ManifestError(f"{path.name}: 'lists' must be a non-empty list")
    lists: list[ListSpec] = []
    seen: set[str] = set()
    for item in raw_lists:
        if not isinstance(item, Mapping):
            raise ManifestError(f"{path.name}: every list entry must be an object")
        spec = _list_spec(item, base)
        if spec.id in seen:
            raise ManifestError(f"{path.name}: duplicate list id {spec.id!r}")
        seen.add(spec.id)
        if not spec.file.is_file():
            raise ManifestError(f"{spec.id}: list file {spec.file} is missing")
        expected = checksums.get(spec.file.name)
        if expected is None:
            raise ManifestError(f"{spec.id}: {spec.file.name} is not listed in {checks_path.name}")
        actual = sha256_path(spec.file)
        if actual != expected:
            raise ManifestError(f"{spec.id}: {spec.file.name} sha256 {actual} != {checks_path.name} {expected}")
        rows = len(read_rows(spec.file))
        if rows != spec.expect_rows:
            raise ManifestError(f"{spec.id}: {spec.file.name} has {rows} non-comment rows, manifest expects {spec.expect_rows}")
        lists.append(spec)

    inherit: dict[str, tuple[str, ...]] = {}
    raw_inherit = raw.get("inherit_stages") or {}
    if not isinstance(raw_inherit, Mapping):
        raise ManifestError(f"{path.name}: inherit_stages must be an object")
    for base_word, forms in raw_inherit.items():
        if not isinstance(forms, list) or not all(isinstance(f, str) for f in forms):
            raise ManifestError(f"{path.name}: inherit_stages[{base_word!r}] must be a list of forms")
        inherit[str(base_word)] = tuple(forms)
    member_tags = tuple(str(t) for t in (raw.get("ecdict_member_tags") or CET_STAGES))
    bad_tags = [t for t in member_tags if t not in STAGE_ORDER]
    if bad_tags:
        raise ManifestError(f"{path.name}: ecdict_member_tags {bad_tags} are not stage codes")

    ext_raw = raw.get("external") or {}
    external: list[ExternalSpec] = []
    if ext_raw:
        if not isinstance(ext_raw, Mapping) or not isinstance(ext_raw.get("lists"), list):
            raise ManifestError(f"{path.name}: external must be an object with 'lists'")
        for item in ext_raw["lists"]:
            if not isinstance(item, Mapping) or not item.get("id") or not item.get("file"):
                raise ManifestError(f"{path.name}: every external list needs id and file")
            mode = str(item.get("mode") or "plain")
            if mode not in EXTERNAL_MODES:
                raise ManifestError(f"{path.name}: external {item['id']} mode {mode!r} not in {EXTERNAL_MODES}")
            stages = _stages(item.get("stages"), f"external {item['id']}")
            rule, flag = item.get("stages_rule"), item.get("flag")
            if sum(1 for x in (stages, rule, flag) if x) != 1:
                raise ManifestError(f"{path.name}: external {item['id']} needs exactly one of stages / stages_rule / flag")
            external.append(ExternalSpec(id=str(item["id"]), file=str(item["file"]), mode=mode, stages=stages, stages_rule=rule, flag=flag))
    return Manifest(
        path=path,
        title=str(raw.get("title") or ""),
        lists=tuple(lists),
        external=tuple(external),
        external_note=str(ext_raw.get("note") or "") if isinstance(ext_raw, Mapping) else "",
        aliases=aliases,
        overrides=overrides,
        inherit=inherit,
        member_tags=member_tags,
        checksums=checksums,
    )


# ---------------------------------------------------------------------------------------------- previous seed
def _read_bytes(path: Path) -> bytes:
    """Decompressed bytes of a ``.jsonl`` or ``.jsonl.gz`` file."""
    path = Path(path)
    if path.suffix == ".gz":
        with gzip.open(path, "rb") as f:
            return f.read()
    return path.read_bytes()


def iter_records(path: Path) -> Iterable[dict[str, Any]]:
    """The JSON objects of a seed file (blank lines skipped; a malformed line is a BuildError — the seed is ours)."""
    text = _read_bytes(Path(path)).decode("utf-8")
    for lineno, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except ValueError as e:
            raise BuildError(f"{Path(path).name}:{lineno}: not a JSON record ({e})") from None
        if not isinstance(rec, dict) or not isinstance(rec.get("word"), str):
            raise BuildError(f"{Path(path).name}:{lineno}: a seed record needs a string 'word'")
        yield rec


def load_previous(path: Path) -> dict[str, dict[str, Any]]:
    """Previous seed → ``{lemma: record}`` keyed by ``normalise.lemma_of(word)`` (fold + lower, no aliases; PLAN R5).

    A duplicate lemma is refused: the importer upserts by lemma, so the file could not have been imported as it is.
    """
    out: dict[str, dict[str, Any]] = {}
    for rec in iter_records(Path(path)):
        lemma = N.lemma_of(rec["word"])
        if not lemma:
            raise BuildError(f"previous seed: record {rec['word']!r} has no lemma")
        if lemma in out:
            raise BuildError(f"previous seed: duplicate lemma {lemma!r} ({out[lemma]['word']!r} / {rec['word']!r})")
        out[lemma] = rec
    return out


def record_version(rec: Mapping[str, Any]) -> int:
    """``seed_v`` of a record (1 for the pre-2026-11 files without the key)."""
    v = rec.get("seed_v")
    return int(v) if isinstance(v, int) and not isinstance(v, bool) and v >= 1 else 1


# ---------------------------------------------------------------------------------------------- ECDICT
class Ecdict:
    """``stardict.db`` lookups for the build: ``word = ? COLLATE NOCASE ORDER BY id LIMIT 1`` (the ``sd_1`` index), cached.

    ``Ecdict(None)`` never finds anything (a build without ``--ecdict`` can only relabel previous lemmas);
    :meth:`from_sql` loads a SQL dump into memory for tests (``tests/fixtures/lists/mini_stardict.sql``). The entry
    returned is :class:`wd.services.ecdict.EcdictEntry`, which satisfies :class:`normalise.LexiconEntry` (``word``,
    ``exchange``) and carries every dictionary field the seed record needs.
    """

    def __init__(self, path: Path | None = None, *, connection: sqlite3.Connection | None = None):
        self._conn = connection
        self.path = Path(path) if path is not None else None
        self._cache: dict[str, EcdictEntry | None] = {}
        self.lookups = 0
        if self._conn is None and self.path is not None:
            if not self.path.is_file():
                raise BuildError(f"ECDICT database {self.path} does not exist")
            try:
                self._conn = sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True)
                self._conn.execute("SELECT 1 FROM stardict LIMIT 1").fetchone()
            except sqlite3.Error as e:
                raise BuildError(f"cannot open ECDICT database {self.path}: {e}") from None

    @classmethod
    def from_sql(cls, script: str) -> "Ecdict":
        conn = sqlite3.connect(":memory:")
        conn.executescript(script)
        return cls(None, connection=conn)

    @property
    def available(self) -> bool:
        return self._conn is not None

    def get(self, word: str) -> EcdictEntry | None:
        if self._conn is None:
            return None
        key = (word or "").strip().lower()
        if not key:
            return None
        if key in self._cache:
            return self._cache[key]
        self.lookups += 1
        row = self._conn.execute(
            f"SELECT {ECDICT_COLUMNS} FROM stardict WHERE word = ? COLLATE NOCASE ORDER BY id LIMIT 1", (word.strip(),)
        ).fetchone()
        entry = EcdictEntry.from_row(row) if row is not None else None
        self._cache[key] = entry
        return entry

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None


# ---------------------------------------------------------------------------------------------- external CET lists
def parse_mahavivo(path: Path, mode: str) -> list[str]:
    """Head words of a mahavivo list (``rich`` lines ``word [phonetic] pos. gloss``; ``plain`` one word per line).

    The retired ``scripts/build_seed.py`` grammar with the PLAN §4.3 fixes: R1 fold first (full-width brackets), a head
    followed by a bracket note yields the head AND the note's single word (``a (an)`` → ``a``, ``an``), and only a lone
    CAPITAL letter is skipped as a section header (``a`` / ``I`` are words).
    """
    out: list[str] = []
    seen: set[str] = set()
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = N.fold(raw)
        if not line or (len(line) == 1 and line.isupper()):
            continue
        heads: list[str]
        if mode == "plain":
            if not _MAHAVIVO_PLAIN_RE.match(line):
                continue
            heads = [line]
        else:
            m = _MAHAVIVO_RICH_RE.match(line)
            if not m:
                continue
            toks = m.group(1).split()
            while len(toks) > 1 and _MAHAVIVO_POS_RE.match(toks[-1]):
                toks.pop()
            heads = [" ".join(toks)]
            note = (m.group(2) or "").strip()
            if note and _MAHAVIVO_PLAIN_RE.match(note) and " " not in note:
                heads.append(note)
        for h in heads:
            key = h.lower()
            if key not in seen:
                seen.add(key)
                out.append(h)
    return out


@dataclass
class External:
    """The optional mahavivo inputs: lemma sets per list id (``lemma_of`` keys) and whether any file was used."""

    present: bool = False
    sets: dict[str, frozenset[str]] = field(default_factory=dict)
    sizes: dict[str, int] = field(default_factory=dict)


def load_external(m: Manifest, wordlists: Path | None) -> External:
    if wordlists is None:
        return External()
    wordlists = Path(wordlists)
    if not wordlists.is_dir():
        raise BuildError(f"--wordlists {wordlists} is not a directory")
    missing = [spec.file for spec in m.external if not (wordlists / spec.file).is_file()]
    if missing:
        raise BuildError(f"--wordlists {wordlists} lacks {missing} (manifest.external lists every file it needs)")
    ext = External(present=bool(m.external))
    for spec in m.external:
        heads = parse_mahavivo(wordlists / spec.file, spec.mode)
        ext.sets[spec.id] = frozenset(k for k in (N.lemma_of(h) for h in heads) if k)
        ext.sizes[spec.id] = len(heads)
    return ext


# ---------------------------------------------------------------------------------------------- membership
@dataclass
class ListStats:
    """Per-list counters for ``stats.json.lists[id]`` and the build log."""

    rows: int = 0
    heads: int = 0
    variants: int = 0
    members: set[str] = field(default_factory=set)
    missing: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    unparsed: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "rows": self.rows,
            "heads": self.heads,
            "variants": self.variants,
            "members": len(self.members),
            "missing": sorted(set(self.missing)),
            "skipped": sorted(set(self.skipped)),
        }


@dataclass
class Membership:
    """Result of :func:`collect_members`: merged members (PLAN §4.2 sets) plus everything the stats and assertions need."""

    members: dict[str, N.Member]
    inherited: dict[str, str]
    lists: dict[str, ListStats]
    previous: frozenset[str]
    drops: frozenset[str]
    failures: list[str]
    unparsed_notes: list[str]
    merged_heads: dict[str, list[str]]
    dropped_seen: frozenset[str] = frozenset()  # ``drop`` lemmas that some list actually produced (an applied override)

    @property
    def universe(self) -> set[str]:
        return set(self.previous) | set(self.members)


def _cells(spec: ListSpec, line: str) -> list[str]:
    cells = line.split("\t")
    if len(cells) < len(spec.columns):
        cells += [""] * (len(spec.columns) - len(cells))
    return cells


def collect_members(m: Manifest, prev: Mapping[str, Mapping[str, Any]], ec: N.Lexicon | None) -> Membership:
    """PLAN §4.2: lists → lemma members with stages / tokens / variant_of / aliases, merged (R6) and inherited (R8).

    Existence (``ECDICT ∪ previous``) is checked per member lemma (the lemma first, then the printed spelling — the
    alias rewrite ``Mr`` → ``mr.`` is what makes ``Mr.`` rather than ECDICT's ``Mr`` the row); a ``policy: main`` head
    that resolves nowhere is a build failure, an appendix / phrase candidate is logged in ``skipped``. The returned
    ``failures`` hold the assertion messages (①③④ and ``main`` R12 rejections); :func:`build` turns them into a
    :class:`BuildError` unless it runs with ``strict=False`` (the decision is made there, not here).
    """
    previous = frozenset(prev)
    drops = m.drops
    raw_members: list[N.Member] = []
    lists: dict[str, ListStats] = {}
    failures: list[str] = []
    unparsed_notes: list[str] = []
    printed_by_lemma: dict[str, set[str]] = collections.defaultdict(set)
    dropped_seen: set[str] = set()

    def known(lemma: str, printed: str) -> bool:
        return lemma in previous or N.lookup(ec, lemma) is not None or (printed != lemma and N.lookup(ec, printed) is not None)

    for spec in m.lists:
        rows = read_rows(spec.file)
        ls = lists[spec.id] = ListStats(rows=len(rows))
        if spec.policy == "reference":
            continue
        for line in rows:
            if spec.format == "phrases":
                res = N.resolve_phrase(line, lexicon=ec, aliases=m.aliases, previous=previous)
                for lemma in res.members:
                    if lemma in drops:
                        ls.skipped.append(f"{lemma} (dropped by overrides.tsv)")
                        dropped_seen.add(lemma)
                        continue
                    ls.heads += 1
                    ls.members.add(lemma)
                    printed = next((c for c in res.candidates if N.canon(c, m.aliases) == lemma), lemma)
                    raw_members.append(N.Member(lemma, stages=frozenset(spec.stages), tokens=frozenset({spec.id}), printed=printed, lists=frozenset({spec.id})))
                for r in res.rejected:
                    ls.skipped.append(f"{r.text} (strict: {r.reason})")
                if res.skipped:
                    ls.skipped.append(f"{line} ({res.skipped})")
                continue

            # heads / tsv lines
            group: GroupSpec | None = None
            token = spec.id
            stages = spec.stages
            if spec.format == "tsv":
                cells = _cells(spec, line)
                word = cells[spec.columns.index("word")].strip()
                if spec.policy == "appendix":
                    gname = cells[spec.columns.index("group")].strip()
                    group = spec.groups.get(gname) or spec.groups.get("*")
                    if group is None:
                        raise BuildError(f"{spec.id}: group {gname!r} ({word!r}) is not in the manifest groups and there is no '*' group")
                    if not group.member:
                        continue
                    stages = group.stages
                    if group.single_token and not N.is_single_token(word):
                        ls.skipped.append(f"{word} (compositional)")
                        continue
                if spec.level_token:
                    token = spec.level_token.format(level=cells[spec.columns.index("level")].strip())
            else:
                word = line.strip()
            if not word:
                continue
            parsed = N.split_head(word, lexicon=ec, aliases=m.aliases, previous=previous, drop=drops)
            alias_forms: dict[str, set[str]] = collections.defaultdict(set)
            for form, lemma in parsed.aliases:
                alias_forms[lemma].add(form)
            admitted: set[str] = set()
            for lemma in parsed.heads:
                printed = parsed.printed.get(lemma, N.fold(word))
                ls.heads += 1
                if not known(lemma, printed):
                    if spec.policy == "main":
                        ls.missing.append(printed)
                        failures.append(f"{spec.id}: head {printed!r} ({lemma}) is in neither ECDICT nor the previous seed")
                    else:
                        ls.skipped.append(f"{printed} (missing)")
                    continue
                admitted.add(lemma)
                ls.members.add(lemma)
                printed_by_lemma[lemma].add(printed)
                raw_members.append(N.Member(lemma, stages=frozenset(stages), tokens=frozenset({token}), printed=printed, aliases=frozenset(alias_forms.get(lemma, ())), lists=frozenset({spec.id})))
            for lemma, head in parsed.variants:
                printed = parsed.printed.get(lemma, lemma)
                ls.variants += 1
                if not known(lemma, printed):
                    ls.skipped.append(f"{printed} (variant missing)")
                    continue
                admitted.add(lemma)
                ls.members.add(lemma)
                # a variant whose head was not admitted (missing) stands on its own: variant_of must name a member
                raw_members.append(N.Member(lemma, stages=frozenset(stages), tokens=frozenset({token}), printed=printed, variant_of=head if head in admitted else None, aliases=frozenset(alias_forms.get(lemma, ())), lists=frozenset({spec.id})))
            for r in parsed.rejected:
                if spec.policy == "main" and r.role == "head":
                    failures.append(f"{spec.id}: head {r.text!r} fails the strict gate (R12): {r.reason}")
                ls.skipped.append(f"{r.text} (strict: {r.reason})")
            for u in parsed.unparsed:
                ls.unparsed.append(u)
                unparsed_notes.append(f"{spec.id}: {word} → {u}")
            for d in parsed.dropped:
                dl = N.canon(d, m.aliases)
                if dl in drops:
                    dropped_seen.add(dl)

    merged = N.merge_heads(raw_members)
    for lemma, mem in list(merged.items()):
        if mem.variant_of is not None and mem.variant_of not in merged:
            merged[lemma] = N.Member(lemma, stages=mem.stages, tokens=mem.tokens, printed=mem.printed, variant_of=None, aliases=mem.aliases, lists=mem.lists)
    inherited = N.inherit_forms(m.inherit, previous, frozenset(merged))
    for form, base in sorted(inherited.items()):
        b = merged.get(base)
        if b is None:
            continue
        merged[form] = N.Member(form, stages=b.stages, tokens=frozenset({f"{INHERIT_PREFIX}{base}"}), printed=str(prev[form].get("word") or form), lists=frozenset())
    inherited = {f: b for f, b in inherited.items() if f in merged}

    not_cumulative = sorted(l for l, mem in merged.items() if STAGE_ORDER[0] in mem.stages and STAGE_ORDER[1] not in mem.stages)
    if not_cumulative:
        failures.append(f"xs ⊄ zk: {len(not_cumulative)} lemma(s) have xs without zk: {not_cumulative[:20]}")
    unknown_codes = sorted({s for mem in merged.values() for s in mem.stages if s not in STAGE_ORDER})
    if unknown_codes:
        raise BuildError(f"stage codes {unknown_codes} are not in schemas.STAGE_ORDER")
    dropped_previous = sorted(drops & previous)
    if dropped_previous:
        raise BuildError(f"overrides.tsv drops previous lemma(s) {dropped_previous}: the seed never deletes a row (PLAN §4.2 retain)")

    merged_heads = {l: sorted(p) for l, p in printed_by_lemma.items() if len(p) > 1}
    return Membership(
        members=merged,
        inherited=inherited,
        lists=lists,
        previous=previous,
        drops=drops,
        failures=failures,
        unparsed_notes=unparsed_notes,
        merged_heads=merged_heads,
        dropped_seen=frozenset(dropped_seen),
    )


# ---------------------------------------------------------------------------------------------- records
@dataclass
class RecordStats:
    new_words: int = 0
    network_translations: int = 0
    empty_translation: list[str] = field(default_factory=list)
    overrides_applied: int = 0
    overrides_unused: list[str] = field(default_factory=list)
    rows_stage_set: int = 0
    rows_sources_only: int = 0


def _lines(text: str | None) -> list[str]:
    return [s.strip() for s in (text or "").replace("\r", "").split("\n") if s.strip()]


def record_from_entry(entry: EcdictEntry) -> dict[str, Any]:
    """Dictionary fields of a NEW row from an ECDICT row — the retired ``build_seed.py`` ``make_record`` mapping
    (``collins``/``oxford`` 0 when empty, ``bnc``/``frq`` None when 0 or empty, exam tags in row order)."""
    return {
        "word": " ".join(entry.word.split()),
        "phonetic": entry.phonetic,
        "translation": _lines(entry.translation),
        "definition": _lines(entry.definition),
        "pos": entry.pos or "",
        "collins": int(entry.collins or 0),
        "oxford": int(entry.oxford or 0),
        "exam_tags": [t for t in entry.tags if t in EXAM_TAGS],
        "bnc": int(entry.bnc) if entry.bnc else None,
        "frq": int(entry.frq) if entry.frq else None,
        "exchange": dict(entry.exchange),
        "ecdict_id": entry.ecdict_id,
        "cet6_star": False,
    }


def _display(lemma: str, *candidates: str | None) -> str:
    """The first candidate whose importer lemma is ``lemma`` (``words.normalise_lemma``), else the lemma itself."""
    for cand in candidates:
        if not cand:
            continue
        d = " ".join(str(cand).split())
        if d and words.normalise_lemma(d) == lemma:
            return d
    return lemma


def make_records(
    membership: Membership,
    prev: Mapping[str, Mapping[str, Any]],
    ec: N.Lexicon | None,
    m: Manifest,
    external: External | None = None,
) -> tuple[list[dict[str, Any]], RecordStats]:
    """Seed records v2 for the universe (previous ∪ members, minus ``drop`` lemmas), sorted (PLAN §4.5).

    Previous rows: dictionary fields copied verbatim, ``stages`` = CET flags of the previous record ∪ official stages,
    ``sources`` = carried ``ecdict``/``cet*`` tokens ∪ ``legacy:*`` (from the v1 flags, or carried from a v2 record) ∪
    the membership tokens. New rows: ECDICT fields, CET flags from ECDICT's member tags, ``ecdict`` token when the row
    carries any tag. Both: external CET lists unioned in when present, then ``overrides.tsv``, then the ``[网络] ``
    strip on new rows.
    """
    ext = external or External()
    rs = RecordStats()
    members = membership.members
    used_overrides: set[tuple[str, str]] = set()
    records: list[dict[str, Any]] = []
    used_overrides.update((lemma, "drop") for lemma in membership.dropped_seen)
    for lemma in sorted(membership.universe):
        if lemma in membership.drops:
            used_overrides.add((lemma, "drop"))
            continue
        mem = members.get(lemma)
        official = set(mem.stages) if mem else set()
        tokens = set(mem.tokens) if mem else set()
        old = prev.get(lemma)
        if old is not None:
            is_new = False
            rec: dict[str, Any] = {k: old.get(k) for k in DICT_KEYS}
            rec["word"] = old["word"]
            rec["cet6_star"] = bool(old.get("cet6_star"))
            old_stages = [s for s in (old.get("stages") or []) if isinstance(s, str)]
            old_sources = {str(t) for t in (old.get("sources") or [])}
            cet = {s for s in old_stages if s in CET_STAGES}
            if record_version(old) >= 2:
                legacy = {t for t in old_sources if t.startswith(LEGACY_PREFIX)}
            else:
                legacy = {f"{LEGACY_PREFIX}{s}" for s in LEGACY_CODES if s in old_stages}
            tokens |= {t for t in old_sources if t in CARRIED_TOKENS} | legacy
        else:
            is_new = True
            entry = N.lookup(ec, lemma) or (N.lookup(ec, mem.printed) if mem and mem.printed else None)
            if entry is None:
                raise BuildError(f"new lemma {lemma!r} has no ECDICT row (membership admitted it, so this is a bug)")
            rec = record_from_entry(entry)
            rec["word"] = _display(lemma, entry.word, mem.printed if mem else None)
            cet = {s for s in m.member_tags if s in entry.tags}
            if entry.tags:
                tokens.add("ecdict")
            rs.new_words += 1
        if ext.present:
            for spec in m.external:
                hit = lemma in ext.sets.get(spec.id, frozenset())
                if not hit:
                    continue
                if spec.flag:
                    rec["cet6_star"] = True
                    continue
                tokens.add(spec.id)
                if spec.stages:
                    cet |= set(spec.stages)
                elif spec.stages_rule:
                    cet.add("cet4" if lemma in ext.sets.get("cet4", frozenset()) else "cet6")
        for fld, value in m.overrides.get(lemma, {}).items():
            if fld == "drop":
                continue
            if fld == "translation":
                rec["translation"] = [value]
            elif fld == "definition":
                rec["definition"] = [value]
            elif fld == "phonetic":
                rec["phonetic"] = value
            elif fld == "word":
                rec["word"] = _display(lemma, value, rec["word"])
            used_overrides.add((lemma, fld))
        if is_new:
            tr = list(rec.get("translation") or [])
            if tr and str(tr[0]).startswith(NETWORK_PREFIX):
                first = str(tr[0])[len(NETWORK_PREFIX):].strip()
                tr = ([first] if first else []) + tr[1:]
                rec["translation"] = tr
                rs.network_translations += 1
            if not tr or not str(tr[0]).strip():
                rs.empty_translation.append(lemma)
        stages = [s for s in STAGE_ORDER if s in official or s in cet]
        out: dict[str, Any] = {
            "word": rec["word"],
            "lemma": lemma,
            **{k: rec.get(k) for k in DICT_KEYS},
            "cet6_star": bool(rec.get("cet6_star")),
            "stages": stages,
            "sources": sorted(tokens),
        }
        if mem and mem.aliases:
            out["aliases"] = sorted(mem.aliases)
        if mem and mem.variant_of and mem.variant_of != lemma:
            out["variant_of"] = mem.variant_of
        out["seed_v"] = SEED_V
        if old is not None:
            old_set = {s for s in (old.get("stages") or []) if s in STAGE_ORDER}
            if old_set != set(stages):
                rs.rows_stage_set += 1
            elif {str(t) for t in (old.get("sources") or [])} != set(out["sources"]):
                rs.rows_sources_only += 1
        records.append(out)
    for lemma, fields in m.overrides.items():
        for fld in fields:
            if (lemma, fld) not in used_overrides:
                rs.overrides_unused.append(f"{lemma} {fld}")
    rs.overrides_applied = len(used_overrides)
    records.sort(key=lambda r: (stage_to_index(r["stages"][0]) if r["stages"] else STAGELESS_SORT, r["lemma"]))
    return records, rs


def check_lemmas(records: Iterable[Mapping[str, Any]]) -> list[str]:
    """Records whose ``lemma`` is not ``words.normalise_lemma(word)`` — what ``wd.seed.seed_row`` recomputes on import.

    Why a second check when every lemma came out of :func:`normalise.lemma_of`: that function's R1 fold also strips
    diacritics while the importer's ``normalise_lemma`` keeps them, so a display such as ``café`` (possible in a
    previous row or an ECDICT headword) would import as a ``SeedStats.lemma_mismatch``. One pass over the records keeps
    the exit-2-writes-nothing contract instead of leaving the catch to ``seed_diff.py`` (impl-review S3b F8).
    """
    return [f"{r.get('word')!r} → {r.get('lemma')!r}" for r in records if words.normalise_lemma(str(r.get("word") or "")) != r.get("lemma")]


def dumps_records(records: Iterable[Mapping[str, Any]]) -> bytes:
    """``vocab.jsonl`` bytes: one object per line in :data:`RECORD_KEYS` order, ``ensure_ascii=False``, LF."""
    lines = []
    for r in records:
        ordered = {k: r[k] for k in RECORD_KEYS if k in r}
        lines.append(json.dumps(ordered, ensure_ascii=False))
    return ("\n".join(lines) + "\n").encode("utf-8") if lines else b""


# ---------------------------------------------------------------------------------------------- stats
@dataclass
class BuildStats:
    """``stats.json`` v2 (PLAN §4.6 key list, in that order; ``built_at`` only with ``--built-at``)."""

    seed_v: int
    content_sha256: str
    total_words: int
    previous_sha256: str
    ecdict_release: str
    external_lists: str
    per_stage: dict[str, int]
    first_stage: dict[str, int]
    only_stage: dict[str, int]
    per_kind: dict[str, int]
    lists: dict[str, dict[str, Any]]
    tokens: dict[str, int]
    variants: int
    aliases: int
    inherited: list[str]
    overrides_applied: int
    network_translations: int
    new_words: int
    stageless: int
    rows_changed_vs_previous: dict[str, int]
    with_phonetic: int
    with_translation: int
    with_definition: int
    with_exchange: int
    multiword: int
    uppercase: int
    file_bytes: int
    # beyond the PLAN §4.6 list (referenced by PLAN §4.2 ⑥ / §4.3 R2 / §4.8 (d)):
    empty_translation: int
    unparsed_notes: list[str]
    merged_heads: dict[str, list[str]]
    overrides_unused: list[str]
    built_at: str | None = None

    def as_dict(self) -> dict[str, Any]:
        d = {k: getattr(self, k) for k in self.__dataclass_fields__ if k != "built_at"}
        if self.built_at:
            d["built_at"] = self.built_at
        return d


def compute_stats(
    records: list[dict[str, Any]],
    content: bytes,
    *,
    membership: Membership,
    rs: RecordStats,
    previous_sha256: str,
    ecdict_release: str,
    external: External,
    built_at: str | None,
) -> BuildStats:
    per_stage = {s: sum(1 for r in records if s in r["stages"]) for s in STAGE_ORDER}
    first_stage = {s: sum(1 for r in records if r["stages"] and r["stages"][0] == s) for s in STAGE_ORDER}
    first_stage["none"] = sum(1 for r in records if not r["stages"])
    only_stage = {s: sum(1 for r in records if r["stages"] == [s]) for s in STAGE_ORDER}
    per_kind = {k: 0 for k in KINDS}
    for r in records:
        per_kind[words.derive_kind(r["word"])] = per_kind.get(words.derive_kind(r["word"]), 0) + 1
    tokens = collections.Counter(t for r in records for t in r["sources"])
    return BuildStats(
        seed_v=SEED_V,
        content_sha256=sha256_bytes(content),
        total_words=len(records),
        previous_sha256=previous_sha256,
        ecdict_release=ecdict_release,
        external_lists="present" if external.present else "absent",
        per_stage=per_stage,
        first_stage=first_stage,
        only_stage=only_stage,
        per_kind=per_kind,
        lists={lid: ls.as_dict() for lid, ls in membership.lists.items()},
        tokens={t: tokens[t] for t in sorted(tokens)},
        variants=sum(1 for r in records if r.get("variant_of")),
        aliases=sum(len(r.get("aliases") or ()) for r in records),
        inherited=sorted(membership.inherited),
        overrides_applied=rs.overrides_applied,
        network_translations=rs.network_translations,
        new_words=rs.new_words,
        stageless=first_stage["none"],
        rows_changed_vs_previous={"stage_set": rs.rows_stage_set, "sources_only": rs.rows_sources_only},
        with_phonetic=sum(1 for r in records if r.get("phonetic")),
        with_translation=sum(1 for r in records if r.get("translation")),
        with_definition=sum(1 for r in records if r.get("definition")),
        with_exchange=sum(1 for r in records if r.get("exchange")),
        multiword=sum(1 for r in records if " " in r["word"]),
        uppercase=sum(1 for r in records if r["word"] != r["word"].lower()),
        file_bytes=len(content),
        empty_translation=len(rs.empty_translation),
        unparsed_notes=sorted(membership.unparsed_notes),
        merged_heads={l: membership.merged_heads[l] for l in sorted(membership.merged_heads)},
        overrides_unused=sorted(rs.overrides_unused),
        built_at=built_at,
    )


# ---------------------------------------------------------------------------------------------- attribution
#: PLAN §4.4 token families → meaning (the per-list titles come from the manifest)
_TOKEN_FAMILIES: tuple[tuple[str, str, str], ...] = (
    ("ecdict", "ECDICT row carries any exam tag (zk gk cet4 cet6 ky toefl ielts gre)", "—"),
    ("cet4 / cet6 / cet46", "mahavivo CET-4 / CET-6 / combined CET-4+6 list membership (optional input; kept from the previous seed when the lists are absent)", "cet4 / cet6"),
    ("legacy:zk / legacy:gk", "the word carried `stage_zk` / `stage_gk` in the seed before the official lists (mahavivo 中考 / Highschool lists ∪ ECDICT zk / gk tags); provenance only", "—"),
    ("inherit:<base>", "person form of be / have / do listed in `manifest.inherit_stages`, already a seed lemma and not an official headword (`am, is, are` ← `be`; `does` ← `do`)", "the base's stages"),
)


def _md_cell(s: str) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


def render_attribution(m: Manifest, stats: BuildStats) -> str:
    """``data/seed/ATTRIBUTION.md`` from the manifest and the build stats (PLAN §4.6 §1–§5)."""
    stage_line = " · ".join(f"`{s}` = {schemas.STAGE_NAMES_ZH[s]} (index {stage_to_index(s)})" for s in STAGE_ORDER)
    out: list[str] = []
    out.append("# Vocabulary data attribution")
    out.append("")
    out.append(
        f"`vocab.jsonl.gz` — {stats.total_words:,} records (seed record format v{stats.seed_v}; counts in `stats.json`, content sha256 "
        f"`{stats.content_sha256}`) — is built by `backend/wd/seedbuild/build.py` (`make seed`, PLAN §4.5) from the sources below. "
        "This file is generated by `render_attribution`; edit `data/lists/manifest.json` or the builder, not this file."
    )
    out.append("")
    out.append("## 1. ECDICT (MIT) — every dictionary field")
    out.append("")
    out.append("**ECDICT — Free English to Chinese Dictionary Database** by skywind3000, https://github.com/skywind3000/ECDICT — MIT License")
    if stats.ecdict_release == ECDICT_RELEASE:
        release_note = f"Release used: {stats.ecdict_release} (`{ECDICT_ASSET}` → `stardict.db`, the file `deploy/fetch_ecdict.sh` pins)."
    else:  # --ecdict-release named another release: do not attribute the pinned asset to it
        release_note = f"Release used: {stats.ecdict_release} (its `stardict.db`; `deploy/fetch_ecdict.sh` pins {ECDICT_RELEASE} / `{ECDICT_ASSET}`)."
    out.append(f"(`data/licenses/ECDICT-LICENSE`). {release_note}")
    out.append("Fields taken: word, phonetic, definition, translation, pos, collins, oxford, tag (→ `exam_tags`, CET-4/CET-6 flags of new rows), bnc, frq, exchange, id (→ `ecdict_id`).")
    out.append("Phonetics are normalised (`ә→ə`, `:→ː`); a new row whose first translation line starts with `[网络] ` has that prefix removed")
    out.append(f"(`stats.network_translations` = {stats.network_translations}). Rows already present in the previous seed keep their dictionary fields byte for byte.")
    out.append("")
    out.append("## 2. Official word lists — headwords only (小学 / 初中 / 高中 membership)")
    out.append("")
    out.append(
        "The `stages[]` of a record (the `stage_xs … stage_cet6` flags and `stage_min` after import) for 小学, 初中 and 高中 come exclusively from the "
        "**headwords** of the official lists in `data/lists/` (provenance, page numbers and parsing rules in `data/lists/README.md` and the three README files "
        "there). Only the fact that a headword appears in a list is used; no gloss, phonetic, example, numbering or layout of the originals is copied. "
        "The originals are government / examination-authority documents that declare no licence (`data/lists/README.md` §3)."
    )
    out.append("")
    out.append("| id (`sources` token) | file | list | rows | members | policy |")
    out.append("|---|---|---|---|---|---|")
    for spec in m.lists:
        ls = stats.lists.get(spec.id, {})
        policy = {
            "main": "main — every headword must resolve",
            "appendix": "appendix — per-group stages; unresolved heads skipped",
            "phrases": "phrases — expanded forms with an ECDICT entry (`kind='phrase'`)",
            "reference": "reference — archived only, grants no membership",
        }[spec.policy]
        if spec.level_token:
            policy += f"; star level in the token `{spec.level_token}`"
        if spec.provisional:
            policy += "; **provisional** (unofficial mirror, 印发文号待确认)"
        stages = ", ".join(spec.stages) if spec.stages else ("by group" if spec.policy == "appendix" else "—")
        out.append(
            f"| `{spec.id}` | `{spec.file.name}` | {_md_cell(spec.title)} | {ls.get('rows', 0):,} | {ls.get('members', 0):,} ({stages}) | {policy} |"
        )
    out.append("")
    out.append(
        "Bracket variants of a headword (`colour (AmE color)`) become rows of the same stages (`variant_of`); official spellings that differ from the "
        f"dictionary lemma are recorded as `aliases[]` (`data/lists/aliases.tsv`, {stats.aliases} alias forms in this seed) and imported as "
        f"`word_forms(kind='alias')`; the person forms {', '.join(f'`{f}`' for f in stats.inherited) or '—'} inherit the stages of their base verb "
        "(`manifest.inherit_stages`). Appendix heads that are in neither ECDICT nor the previous seed are skipped (`stats.lists[].skipped`)."
    )
    out.append("")
    out.append("## 3. mahavivo/english-wordlists — CET-4 / CET-6 lists (optional input, not redistributed)")
    out.append("")
    out.append(
        f"https://github.com/mahavivo/english-wordlists — plain-text transcriptions of public exam syllabi; **{stats.external_lists}** in this build "
        "(`--wordlists DIR`). When absent, existing rows keep the CET-4 / CET-6 flags, the `cet4` / `cet6` / `cet46` tokens and `cet6_star` of the previous "
        "seed and new rows take ECDICT's `cet4` / `cet6` tags. Only head-word membership is ever used; no list file is shipped. The 中考英语词汇表.txt and "
        "Highschool_edited.txt lists of the same repository are no longer inputs — their former contribution survives as the `legacy:zk` / `legacy:gk` tokens."
    )
    if m.external:
        out.append("")
        out.append("| id | file | mode | grants |")
        out.append("|---|---|---|---|")
        for spec in m.external:
            grants = ", ".join(spec.stages) if spec.stages else (spec.stages_rule or f"flag `{spec.flag}`")
            out.append(f"| `{spec.id}` | `{spec.file}` | {spec.mode} | {grants} |")
    out.append("")
    out.append("## 4. Hand-written glosses — `data/lists/overrides.tsv`")
    out.append("")
    n_rows = sum(len(f) for f in m.overrides.values())
    by_field = collections.Counter(fld for fields in m.overrides.values() for fld in fields)
    out.append(
        f"{n_rows} rows (at most {OVERRIDES_MAX}; {stats.overrides_applied} applied in this build): "
        + ", ".join(f"{by_field[f]} `{f}`" for f in OVERRIDE_FIELDS if by_field[f])
        + ". A `translation` override replaces the whole ECDICT translation of that lemma (wrong sense: `bund`, `mum`, `p.e.`, abbreviations such as `ai`, "
        "`bce`, `un`); `word` fixes the display; `drop` keeps a duplicate out of the seed. These glosses are written for this repository and are MIT-licensed "
        "text of word-Dance, not ECDICT or official-list content."
    )
    out.append("")
    out.append("## 5. `sources` tokens (PLAN §4.4)")
    out.append("")
    out.append("Every record lists the tokens of the sources that mention it; the importer stores them space-joined in `words.sources`. Counts are rows in this seed.")
    out.append("")
    out.append("| token | meaning | grants | rows |")
    out.append("|---|---|---|---|")
    counted: set[str] = set()

    def rows_for(tokens: Iterable[str]) -> str:
        parts = []
        for t in tokens:  # exact tokens only: ``shmeea20`` must not count ``shmeea20:app`` / ``shmeea20:phr``
            counted.add(t)
            parts.append(f"{stats.tokens.get(t, 0):,}")
        return " / ".join(parts)

    out.append(f"| `ecdict` | {_TOKEN_FAMILIES[0][1]} | — | {rows_for(['ecdict'])} |")
    out.append(f"| `cet4` / `cet6` / `cet46` | {_TOKEN_FAMILIES[1][1]} | cet4 / cet6 | {rows_for(['cet4', 'cet6', 'cet46'])} |")
    for spec in m.lists:
        if spec.policy == "reference":
            continue
        grants = ", ".join(spec.stages) if spec.stages else "by group (`manifest.json` groups)"
        if spec.level_token:
            token_label = " / ".join(f"`{spec.level_token.format(level=lvl)}`" for lvl in ("0", "1", "2"))
            hits = sorted((t, n) for t, n in stats.tokens.items() if t.startswith(spec.id + ":"))
            counted.update(t for t, _ in hits)
            rows = " / ".join(f"{n:,}" for _, n in hits) or "0"
        else:
            token_label = f"`{spec.id}`"
            rows = rows_for([spec.id])
        out.append(f"| {token_label} | {_md_cell(spec.title)} (`{spec.file.name}`) | {grants} | {rows} |")
    inh = sorted((t, n) for t, n in stats.tokens.items() if t.startswith(INHERIT_PREFIX))
    counted.update(t for t, _ in inh)
    out.append(f"| {' / '.join(f'`{t}`' for t, _ in inh) or '`inherit:<base>`'} | {_TOKEN_FAMILIES[3][1]} | {_TOKEN_FAMILIES[3][2]} | {' / '.join(f'{n:,}' for _, n in inh) or '0'} |")
    leg = [(f"{LEGACY_PREFIX}{c}", stats.tokens.get(f"{LEGACY_PREFIX}{c}", 0)) for c in LEGACY_CODES]  # PLAN §4.4 order zk, gk
    leg += sorted((t, n) for t, n in stats.tokens.items() if t.startswith(LEGACY_PREFIX) and t not in {t for t, _ in leg})
    counted.update(t for t, _ in leg)
    out.append(f"| {' / '.join(f'`{t}`' for t, _ in leg)} | {_TOKEN_FAMILIES[2][1]} | — | {' / '.join(f'{n:,}' for _, n in leg)} |")
    other = sorted((t, n) for t, n in stats.tokens.items() if t not in counted)
    for t, n in other:
        out.append(f"| `{t}` | (token not described by the manifest) | — | {n:,} |")
    out.append("")
    out.append(f"Stage codes (`backend/wd/schemas.py`, the only place the enum lives): {stage_line}. A record's `stages[]` is the union of its official lists")
    out.append("(cumulative on the national chain by construction: xs ⊆ zk; zk ⊄ gk by design) and its CET membership; `stage_min` = index of the first code,")
    out.append("NULL when the list is empty (课标外 — kept in the dictionary, shown only in 全部 and search). `exam_tags` keeps ECDICT's other tags (ky 考研,")
    out.append("toefl, ielts, gre). `exchange` codes (ECDICT): p=过去式, d=过去分词, i=现在分词, 3=第三人称单数, r=比较级, t=最高级, s=复数, 0=原型, 1=原型的变换形式.")
    out.append("")
    return "\n".join(out)


# ---------------------------------------------------------------------------------------------- build
def build(
    manifest: Manifest | Path,
    previous: Path,
    *,
    ecdict: Ecdict | Path | None = None,
    wordlists: Path | None = None,
    out: Path,
    strict: bool = True,
    built_at: str | None = None,
    ecdict_release: str = ECDICT_RELEASE,
) -> BuildStats:
    """Run the whole pipeline (module docstring) and write ``vocab.jsonl``, ``stats.json``, ``ATTRIBUTION.md`` into ``out``.

    Raises :class:`ManifestError` / :class:`BuildError` before writing anything; with ``strict=False`` the list-content
    failures are logged as warnings and the output is still written.
    """
    m = manifest if isinstance(manifest, Manifest) else load_manifest(Path(manifest))
    previous = Path(previous)
    if not previous.is_file():
        raise BuildError(f"--previous {previous} does not exist")
    prev = load_previous(previous)
    previous_sha256 = sha256_bytes(_read_bytes(previous))
    own_ecdict = not isinstance(ecdict, Ecdict)
    ec = ecdict if isinstance(ecdict, Ecdict) else Ecdict(Path(ecdict) if ecdict else None)
    try:
        external = load_external(m, wordlists)
        membership = collect_members(m, prev, ec)
        records, rs = make_records(membership, prev, ec, m, external)
        failures = list(membership.failures)
        if rs.empty_translation:
            failures.append(f"{len(rs.empty_translation)} new row(s) have an empty first translation line: {rs.empty_translation[:20]}")
        if failures and not ec.available:
            # Without --ecdict only previous lemmas can be relabelled; say so first instead of listing N bare misses.
            unresolved = sum(1 for f in failures if f.endswith(" is in neither ECDICT nor the previous seed"))
            if unresolved:
                failures.insert(
                    0,
                    f"no --ecdict was given and {unresolved} main-list head(s) are not in the previous seed: pass "
                    "ECDICT_DB=<stardict.db> to make seed (deploy/fetch_ecdict.sh downloads it); without ECDICT a build can only relabel previous lemmas",
                )
        if failures:
            if strict:
                raise BuildError("build assertions failed:\n  - " + "\n  - ".join(failures))
            for f in failures:
                log.warning("not strict: %s", f)
        for u in rs.overrides_unused:
            log.warning("overrides.tsv row %s matched no lemma of this build", u)
        for note in membership.unparsed_notes:
            log.warning("unparsed bracket note: %s", note)
        missing_prev = sorted(set(prev) - {r["lemma"] for r in records})
        if missing_prev:
            raise BuildError(f"retain violated: previous lemma(s) {missing_prev[:20]} have no record")
        mismatched = check_lemmas(records)
        if mismatched:
            raise BuildError(f"{len(mismatched)} record(s) whose lemma is not what the importer computes (words.normalise_lemma(word)): {mismatched[:20]}")
        content = dumps_records(records)
        stats = compute_stats(
            records, content, membership=membership, rs=rs, previous_sha256=previous_sha256, ecdict_release=ecdict_release,
            external=external, built_at=built_at,
        )
    finally:
        if own_ecdict:
            ec.close()
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "vocab.jsonl").write_bytes(content)
    (out / "stats.json").write_text(json.dumps(stats.as_dict(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (out / "ATTRIBUTION.md").write_text(render_attribution(m, stats), encoding="utf-8")
    return stats


def _summary(stats: BuildStats) -> str:
    lines = [
        f"vocab.jsonl: {stats.total_words:,} records ({stats.new_words} new, {stats.stageless} without a stage), content sha256 {stats.content_sha256}",
        "per_stage: " + ", ".join(f"{s} {n:,}" for s, n in stats.per_stage.items()),
        "first_stage: " + ", ".join(f"{s} {n:,}" for s, n in stats.first_stage.items()),
        f"rows changed vs previous: stage set {stats.rows_changed_vs_previous['stage_set']:,}, sources only {stats.rows_changed_vs_previous['sources_only']:,}",
        f"external CET lists: {stats.external_lists}; overrides applied {stats.overrides_applied}; [网络] prefixes removed {stats.network_translations}; inherited {stats.inherited}",
    ]
    for lid, ls in stats.lists.items():
        line = f"  {lid}: rows {ls['rows']}, heads {ls['heads']}, variants {ls['variants']}, members {ls['members']}"
        if ls["missing"]:
            line += f", MISSING {ls['missing']}"
        if ls["skipped"]:
            line += f", skipped {len(ls['skipped'])}: {ls['skipped'][:6]}{' …' if len(ls['skipped']) > 6 else ''}"
        lines.append(line)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="build_seed.py",
        description="Build data/seed/vocab.jsonl + stats.json + ATTRIBUTION.md from the official word lists, the previous seed and ECDICT (PLAN §4.5).",
    )
    ap.add_argument("--manifest", required=True, type=Path, help="data/lists/manifest.json (format 2)")
    ap.add_argument("--previous", required=True, type=Path, help="the previous seed (vocab.jsonl or vocab.jsonl.gz); every lemma in it is retained")
    ap.add_argument("--ecdict", type=Path, default=None, help="ECDICT stardict.db; needed only when the lists bring headwords the previous seed lacks")
    ap.add_argument("--wordlists", type=Path, default=None, help="directory with the mahavivo CET lists (manifest.external); optional")
    ap.add_argument("--out", required=True, type=Path, help="output directory (data/seed)")
    ap.add_argument("--no-strict", action="store_true", help="log the list-content assertions instead of failing (structural checks still fail)")
    ap.add_argument("--built-at", default=None, help="ISO timestamp written to stats.json (never into vocab.jsonl); omitted = none")
    ap.add_argument("--ecdict-release", default=ECDICT_RELEASE, help=f"ECDICT release recorded in stats.json / ATTRIBUTION.md (default {ECDICT_RELEASE})")
    a = ap.parse_args(argv)
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stderr)
    try:
        stats = build(
            a.manifest, a.previous, ecdict=a.ecdict, wordlists=a.wordlists, out=a.out, strict=not a.no_strict,
            built_at=a.built_at, ecdict_release=a.ecdict_release,
        )
    except (ManifestError, BuildError) as e:
        print(f"build_seed: {e}", file=sys.stderr)  # stderr directly: the CLI must report regardless of logging setup
        return 2
    print(_summary(stats), file=sys.stderr)
    return 0
