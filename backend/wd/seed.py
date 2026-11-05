"""Seed import (WP1): ``import_seed`` and the ``wd import-seed`` command — DESIGN §3.2, TASKS WP1, PLAN §4.7.

The seed is ``data/seed/vocab.jsonl.gz`` (one JSON record per word, built by ``wd.seedbuild`` through
``scripts/build_seed.py``; record format v2, PLAN §4.5 — v1 files without ``lemma``/``seed_v``/``aliases`` import
unchanged). The import is an idempotent upsert keyed by ``words.lemma``:

* dictionary columns (``display``, ``kind``, ``phonetic``, ``translation``, ``definition``, ``pos``, ``collins``, ``oxford``,
  ``exam_tags``, ``bnc``, ``frq``, ``exchange_json``, the five stage flags ``stage_xs … stage_cet6`` — one per code of
  ``schemas.STAGE_ORDER``, the only place the stage enum lives —, ``stage_min``, ``cet6_star``, ``sources``, ``ecdict_id``)
  are written from the record; ``source='seed'``, ``is_public=1``, ``is_valid_english=1``, ``safe_for_sharing=1`` and
  ``merged_into_word_id=NULL`` (a seed headword stands on its own);
* ``stage_min`` is the index (``schemas.stage_to_index``) of the lowest listed stage, NULL when the record lists no
  stage at all: such a word left every official list and stays in the dictionary as a 课标外 word — the seed never
  deletes a row and never lowers a word's visibility;
* a stage code outside ``STAGE_ORDER`` is ignored and counted (``SeedStats.unknown_stage_codes``, one WARNING naming the
  first few codes, the count repeated in ``system_events('seed_imported')``); the hard gate against unknown codes sits
  in the builder so that an old server can still read a newer seed (PLAN R-8);
* a record's own ``lemma`` is informational: the importer recomputes it from ``word`` and only counts a disagreement
  (``SeedStats.lemma_mismatch``) — the computed key wins, exactly as for v1 files;
* ``active_content_id``, ``active_image_id``, ``content_state``, ``image_state``, ``difficulty``, ``created_by_user_id``
  and every per-user table are never touched; an unchanged row is not rewritten (``updated_at`` only moves when a
  column really changed);
* ``word_forms`` is rebuilt for the imported words from the exchange codes ``p d i 3 s r t`` (``0 1 f b z`` ignored)
  plus the record's ``aliases[]`` (official spellings that differ from the lemma — ``t.v.``, ``mr`` …; migration 0013
  admits ``kind='alias'``) with the SCHEMA guards: empty forms skipped, a form that is itself a ``words.lemma`` never
  inserted, one row per ``(form, word_id)`` (an exchange code wins over an alias for the same pair; ambiguous forms keep
  one row per lemma); ``alt`` rows written by lookup/consolidation survive;
* ``kv.seed_version`` = sha256 of the DECOMPRESSED content (:func:`seed_digest`, what ``main.seed_check`` compares) and
  ``kv.seed_imported_at`` are set and a ``system_events('seed_imported')`` row is written — all inside one
  ``BEGIN IMMEDIATE`` transaction. Hashing the content rather than the ``.gz`` bytes means a seed re-packed by another
  gzip implementation (``gzip -9 -n`` on a Mac vs. Linux) is still "up to date" (PLAN R-9).

A second run with the same content is a no-op ("seed up to date") unless ``--force``. ``--dry-run`` (``dry_run=True``)
reads the file and the ``words`` table, returns the :class:`SeedPlan` an import would carry out — inserts, updates,
orphans (seed rows absent from the file), per-stage flag changes, the ``stage_min`` transition matrix — and writes
nothing: no transaction is opened, ``kv`` and ``system_events`` stay untouched. The plan only reports; it never
refuses an import (operators compare it against the rehearsal in PLAN §7.3 before running for real).
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import logging
import sqlite3
import sys
import zlib
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterator, Mapping

from . import db
from .clock import now_iso
from .config import ConfigError, Settings, ensure_dirs
from .schemas import STAGE_ORDER, stage_to_index
from .services.words import derive_kind, normalise_input, normalise_lemma

log = logging.getLogger("wd.seed")

EXAM_TAGS: tuple[str, ...] = ("ky", "toefl", "ielts", "gre")
FORM_CODES: tuple[str, ...] = ("p", "d", "i", "3", "s", "r", "t")  # priority order when one (form, word) carries several codes
# one flag column per stage code, in the DDL order of 0011_primary_stage.sql (stage_xs, stage_zk, stage_gk, stage_cet4, stage_cet6)
STAGE_COLUMNS: tuple[str, ...] = tuple(f"stage_{s}" for s in STAGE_ORDER)
PLAN_SAMPLES = 30  # (lemma, old stages, new stages) examples kept in a SeedPlan
UNKNOWN_CODES_SHOWN = 5

SEED_COLUMNS: tuple[str, ...] = (
    "display",
    "kind",
    "phonetic",
    "translation",
    "definition",
    "pos",
    "collins",
    "oxford",
    "exam_tags",
    "bnc",
    "frq",
    "exchange_json",
    *STAGE_COLUMNS,
    "stage_min",
    "cet6_star",
    "sources",
    "ecdict_id",
)

# the DO UPDATE fires only when a seed-managed column (or one of the trust flags) differs, so a re-import of an
# unchanged seed rewrites nothing and updated_at stays put
_UPSERT_SQL = (
    f"INSERT INTO words(lemma, {', '.join(SEED_COLUMNS)}, source, is_public, is_valid_english, safe_for_sharing, created_at, updated_at) "
    f"VALUES (:lemma, {', '.join(':' + c for c in SEED_COLUMNS)}, 'seed', 1, 1, 1, :now, :now) "
    "ON CONFLICT(lemma) DO UPDATE SET "
    + ", ".join(f"{c} = excluded.{c}" for c in SEED_COLUMNS)
    + ", source = 'seed', is_public = 1, is_valid_english = 1, safe_for_sharing = 1, merged_into_word_id = NULL, updated_at = excluded.updated_at "
    "WHERE "
    + " OR ".join(f"words.{c} IS NOT excluded.{c}" for c in SEED_COLUMNS)
    + " OR words.source IS NOT 'seed' OR words.is_public IS NOT 1 OR words.is_valid_english IS NOT 1 "
    "OR words.safe_for_sharing IS NOT 1 OR words.merged_into_word_id IS NOT NULL"
)
# the columns plan_import compares — the same set the UPSERT's WHERE clause looks at
_PLAN_COLUMNS: tuple[str, ...] = ("lemma", *SEED_COLUMNS, "source", "is_public", "is_valid_english", "safe_for_sharing", "merged_into_word_id")


@dataclass
class SeedPlan:
    """What an import of a given file would do to the ``words`` table (``import_seed(dry_run=True)`` / ``--dry-run``).

    ``inserted`` / ``updated`` / ``unchanged`` mirror the UPSERT's outcome per record; ``orphans`` are ``source='seed'``
    lemmas absent from the file (reported, never deleted); ``flag_added`` / ``flag_removed`` count rows per stage code
    whose flag flips; ``min_lowered`` / ``min_raised`` count rows whose ``stage_min`` moves between two indexes;
    ``stageless`` counts records that list no stage; ``matrix`` holds ``"<old>→<new>"`` transition counts of ``stage_min``
    (``none`` for NULL, ``new`` for a row the import would insert); ``samples`` are the first stage-set changes.
    """

    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    orphans: list[str] = field(default_factory=list)
    flag_added: dict[str, int] = field(default_factory=lambda: {s: 0 for s in STAGE_ORDER})
    flag_removed: dict[str, int] = field(default_factory=lambda: {s: 0 for s in STAGE_ORDER})
    min_lowered: int = 0
    min_raised: int = 0
    stageless: int = 0
    matrix: dict[str, int] = field(default_factory=dict)
    samples: list[tuple[str, list[str], list[str]]] = field(default_factory=list)


@dataclass
class SeedStats:
    """What :func:`import_seed` did (``up_to_date`` = nothing was written because ``kv.seed_version`` matched).

    ``sha256`` is the file's digest (informational), ``content_sha256`` the decompressed content's — the value stored in
    ``kv.seed_version``. ``plan`` is filled by every run that reads the file (a dry run returns nothing else).
    """

    path: str
    sha256: str
    content_sha256: str = ""
    records: int = 0
    inserted: int = 0
    updated: int = 0
    skipped_records: int = 0
    duplicate_lemmas: int = 0
    unknown_stage_codes: int = 0
    lemma_mismatch: int = 0
    stageless_records: int = 0
    forms: int = 0
    aliases: int = 0
    forms_skipped_empty: int = 0
    forms_skipped_headword: int = 0
    up_to_date: bool = False
    dry_run: bool = False
    seconds: float = 0.0
    plan: SeedPlan | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# ------------------------------------------------------------------------------------------ reading
def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _opener(p: Path):
    return gzip.open if p.suffix == ".gz" else io.open


def seed_digest(path: str | Path) -> str:
    """sha256 of the seed's DECOMPRESSED bytes — the ``kv.seed_version`` value (PLAN R-9).

    Streams through ``gzip.open`` for ``.gz`` files, so the same records packed by different gzip implementations (or
    not packed at all) share one digest. A truncated or corrupt archive raises (``gzip.BadGzipFile`` / ``EOFError``):
    callers that must not fail — ``main.seed_check`` — catch it and record ``system_events('seed_import_failed')``.
    """
    p = Path(path)
    h = hashlib.sha256()
    with _opener(p)(p, "rb") as f:  # type: ignore[operator]
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def iter_records(path: str | Path) -> Iterator[dict[str, Any]]:
    """Yield the JSON objects of a ``.jsonl`` or ``.jsonl.gz`` file (blank lines skipped, bad lines logged and skipped)."""
    p = Path(path)
    with _opener(p)(p, "rt", encoding="utf-8") as f:  # type: ignore[operator]
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError as e:
                log.warning("%s:%d: skipping unparsable seed line (%s)", p.name, lineno, e)
                continue
            if isinstance(rec, dict):
                yield rec
            else:
                log.warning("%s:%d: skipping non-object seed line", p.name, lineno)


def _text(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _lines(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, str):
        parts = v.replace("\r", "").split("\n")
    elif isinstance(v, (list, tuple)):
        parts = [str(x) for x in v]
    else:
        return None
    lines = [s.strip() for s in parts if str(s).strip()]
    return "\n".join(lines) or None


def _int(v: Any) -> int | None:
    """Integer column value: None for None/'' and for anything that is not an integer (bools count as 0/1)."""
    if isinstance(v, bool):
        return int(v)
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def seed_row(rec: Mapping[str, Any], now: str) -> dict[str, Any] | None:
    """Map one seed record onto the ``words`` columns (DESIGN §3.2 / PLAN §4.5); None for a record without a usable ``word``.

    ``lemma = normalise(word)`` through :func:`normalise_input`; a record the strict normaliser rejects (none in the
    shipped seed) falls back to the lenient key so dictionary data is never dropped silently. The underscore keys are
    side channels for :func:`import_seed` and are ignored by the named-parameter UPSERT: ``_exchange`` (raw exchange
    mapping for the ``word_forms`` rebuild), ``_aliases`` (normalised ``aliases[]`` spellings), ``_unknown_stages``
    (codes outside ``STAGE_ORDER``, counted rather than refused — PLAN R-8) and ``_lemma_declared`` (the record's own
    ``lemma``, compared against the computed key). ``variant_of`` and ``seed_v`` are builder bookkeeping and ignored.
    """
    word = rec.get("word")
    if not isinstance(word, str):
        return None
    display = " ".join(word.split())
    if not display:
        return None
    norm = normalise_input(display)
    lemma = norm.lemma if norm.ok else normalise_lemma(display)  # type: ignore[union-attr]
    if not lemma:
        return None
    raw_stages = rec.get("stages") or []
    if not isinstance(raw_stages, (list, tuple)):
        raw_stages = []
    stages = [s for s in STAGE_ORDER if s in raw_stages]
    unknown = [str(s) for s in raw_stages if s not in STAGE_ORDER]
    raw_aliases = rec.get("aliases") or []
    aliases: list[str] = []
    if isinstance(raw_aliases, (list, tuple)):
        aliases = sorted({key for key in (normalise_lemma(a) for a in raw_aliases if isinstance(a, str)) if key})
    declared = rec.get("lemma")
    exchange_raw = rec.get("exchange") or {}
    exchange = {str(k): str(v) for k, v in exchange_raw.items()} if isinstance(exchange_raw, Mapping) else {}
    exam_tags = rec.get("exam_tags") or []
    sources = rec.get("sources") or []
    return {
        "lemma": lemma,
        "display": display,
        "kind": derive_kind(display),
        "phonetic": _text(rec.get("phonetic")),
        "translation": _lines(rec.get("translation")),
        "definition": _lines(rec.get("definition")),
        "pos": _text(rec.get("pos")),
        "collins": _int(rec.get("collins")),
        "oxford": _int(rec.get("oxford")),
        "exam_tags": " ".join(t for t in EXAM_TAGS if isinstance(exam_tags, (list, tuple)) and t in exam_tags) or None,
        "bnc": _int(rec.get("bnc")),
        "frq": _int(rec.get("frq")),
        "exchange_json": json.dumps(exchange, ensure_ascii=False, sort_keys=True) if exchange else None,
        **{f"stage_{s}": int(s in stages) for s in STAGE_ORDER},
        "stage_min": min(stage_to_index(s) for s in stages) if stages else None,
        "cet6_star": int(bool(rec.get("cet6_star"))),
        "sources": " ".join(sorted({str(s) for s in sources})) if isinstance(sources, (list, tuple)) and sources else None,
        "ecdict_id": _int(rec.get("ecdict_id")),
        "now": now,
        "_exchange": exchange,
        "_aliases": aliases,
        "_unknown_stages": unknown,
        "_lemma_declared": declared if isinstance(declared, str) and declared.strip() else None,
    }


def _stages_of(row: Mapping[str, Any]) -> list[str]:
    return [s for s in STAGE_ORDER if int(row.get(f"stage_{s}") or 0)]


def _cell(stage_min: Any) -> str:
    return "none" if stage_min is None else str(int(stage_min))


# ------------------------------------------------------------------------------------------ planning
def plan_import(conn, rows: Mapping[str, Mapping[str, Any]]) -> SeedPlan:
    """Compare the parsed records (``lemma → seed_row``) with the ``words`` table — read-only, no transaction needed.

    A row counts as ``updated`` under the same condition that fires the UPSERT's ``DO UPDATE`` (a seed-managed column or
    a trust flag differs), so the plan predicts what :func:`import_seed` will rewrite. Nothing here refuses anything:
    ``flag_removed`` / ``orphans`` are facts for the operator (PLAN §4.7 ⑦), not errors.
    """
    plan = SeedPlan()
    existing: dict[str, dict[str, Any]] = {}
    for r in conn.execute(f"SELECT {', '.join(_PLAN_COLUMNS)} FROM words"):
        d = dict(zip(_PLAN_COLUMNS, tuple(r)))
        existing[str(d["lemma"])] = d
    for lemma, row in rows.items():
        new_stages = _stages_of(row)
        if row["stage_min"] is None:
            plan.stageless += 1
        old = existing.get(lemma)
        if old is None:
            plan.inserted += 1
            key = f"new→{_cell(row['stage_min'])}"
            plan.matrix[key] = plan.matrix.get(key, 0) + 1
            continue
        changed = any(old[c] != row[c] for c in SEED_COLUMNS) or old["source"] != "seed" or old["is_public"] != 1
        changed = changed or old["is_valid_english"] != 1 or old["safe_for_sharing"] != 1 or old["merged_into_word_id"] is not None
        if changed:
            plan.updated += 1
        else:
            plan.unchanged += 1
        old_stages = _stages_of(old)
        for s in STAGE_ORDER:
            if s in new_stages and s not in old_stages:
                plan.flag_added[s] += 1
            elif s in old_stages and s not in new_stages:
                plan.flag_removed[s] += 1
        old_min, new_min = old["stage_min"], row["stage_min"]
        if old_min is not None and new_min is not None:
            if new_min < old_min:
                plan.min_lowered += 1
            elif new_min > old_min:
                plan.min_raised += 1
        key = f"{_cell(old_min)}→{_cell(new_min)}"
        plan.matrix[key] = plan.matrix.get(key, 0) + 1
        if old_stages != new_stages and len(plan.samples) < PLAN_SAMPLES:
            plan.samples.append((lemma, old_stages, new_stages))
    plan.orphans = sorted(lemma for lemma, d in existing.items() if d["source"] == "seed" and lemma not in rows)
    return plan


# ------------------------------------------------------------------------------------------ importing
def _rebuild_forms(conn, rows: Mapping[str, dict[str, Any]], stats: SeedStats) -> None:
    """Delete the non-``alt`` forms of the imported words and re-insert them from the exchange codes, then the aliases.

    Both kinds go through the same guards; for one ``(form, word_id)`` pair an exchange code wins over ``alias``, and an
    ``alt`` row that already occupies the pair is left alone (``INSERT OR IGNORE`` on the primary key).
    """
    ids: dict[str, int] = {str(r[0]): int(r[1]) for r in conn.execute("SELECT lemma, id FROM words WHERE source = 'seed'")}
    conn.executemany(
        "DELETE FROM word_forms WHERE word_id = ? AND kind != 'alt'",
        [(ids[lemma],) for lemma in rows if lemma in ids],
    )
    lemmas = {str(r[0]) for r in conn.execute("SELECT lemma FROM words")}
    pairs: dict[tuple[str, int], str] = {}
    alias_pairs: dict[tuple[str, int], str] = {}
    for lemma, row in rows.items():
        wid = ids.get(lemma)
        if wid is None:  # pragma: no cover - every imported lemma is a seed row after the upsert
            continue
        for code in FORM_CODES:
            raw = row["_exchange"].get(code)
            if raw is None:
                continue
            form = normalise_lemma(raw)
            if not form:
                stats.forms_skipped_empty += 1
                continue
            if form in lemmas:
                stats.forms_skipped_headword += 1
                continue
            pairs.setdefault((form, wid), code)
        for form in row["_aliases"]:
            if form == lemma:
                continue  # an alias spelled like its own lemma says nothing
            if form in lemmas:
                stats.forms_skipped_headword += 1  # the official spelling is a headword of its own (humourous / humorous)
                continue
            if (form, wid) not in pairs:
                alias_pairs.setdefault((form, wid), "alias")
    before = conn.total_changes
    conn.executemany("INSERT OR IGNORE INTO word_forms(form, word_id, kind) VALUES (?, ?, ?)", [(f, w, k) for (f, w), k in pairs.items()])
    exchange_forms = conn.total_changes - before
    conn.executemany("INSERT OR IGNORE INTO word_forms(form, word_id, kind) VALUES (?, ?, ?)", [(f, w, k) for (f, w), k in alias_pairs.items()])
    stats.aliases = conn.total_changes - before - exchange_forms
    stats.forms = exchange_forms + stats.aliases


def import_seed(conn, path: str, *, force: bool = False, dry_run: bool = False) -> SeedStats:
    """Import or refresh the seed at ``path`` (``.jsonl`` / ``.jsonl.gz``) — see the module docstring for the rules.

    Returns :class:`SeedStats`; ``up_to_date`` is True (and nothing is written) when ``kv.seed_version`` already equals
    the content sha256 and ``force`` is False. With ``dry_run`` the file and the table are read, ``stats.plan`` is
    filled and nothing is written — also when the seed is up to date (the plan then shows what ``--force`` would do).
    Raises ``FileNotFoundError`` for a missing file and the ``gzip``/``OSError`` of a corrupt archive.
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"seed file not found: {p}")
    t0 = time.monotonic()
    digest = seed_digest(p)
    stats = SeedStats(path=str(p), sha256=sha256_file(p), content_sha256=digest, dry_run=dry_run)
    stats.up_to_date = not force and db.kv_get(conn, "seed_version") == digest
    if stats.up_to_date and not dry_run:
        stats.seconds = time.monotonic() - t0
        return stats

    now = now_iso()
    rows: dict[str, dict[str, Any]] = {}
    unknown_codes: list[str] = []
    mismatches: list[str] = []
    for rec in iter_records(p):
        stats.records += 1
        row = seed_row(rec, now)
        if row is None:
            stats.skipped_records += 1
            log.warning("skipping seed record without a usable word: %r", rec.get("word"))
            continue
        if row["lemma"] in rows:
            stats.duplicate_lemmas += 1
            log.warning("duplicate lemma %r in the seed; keeping the first record", row["lemma"])
            continue
        rows[row["lemma"]] = row
        if row["_unknown_stages"]:
            stats.unknown_stage_codes += len(row["_unknown_stages"])
            unknown_codes.extend(row["_unknown_stages"])
        if row["_lemma_declared"] is not None and row["_lemma_declared"] != row["lemma"]:
            stats.lemma_mismatch += 1
            mismatches.append(f"{row['_lemma_declared']}≠{row['lemma']}")
        if row["stage_min"] is None:
            stats.stageless_records += 1
    if stats.unknown_stage_codes:
        shown = sorted(set(unknown_codes))[:UNKNOWN_CODES_SHOWN]
        log.warning(
            "%s: %d unknown stage code(s) ignored (not in %s): %s — the seed is newer than this server; words keep their known stages",
            p.name,
            stats.unknown_stage_codes,
            "/".join(STAGE_ORDER),
            ", ".join(shown),
            extra={"event": "seed_unknown_stage_codes"},
        )
    if stats.lemma_mismatch:
        log.warning("%s: %d record(s) declare a lemma that differs from the computed key (first: %s); the computed key is used", p.name, stats.lemma_mismatch, ", ".join(mismatches[:UNKNOWN_CODES_SHOWN]))

    if dry_run:
        stats.plan = plan_import(conn, rows)
        stats.seconds = time.monotonic() - t0
        return stats

    with db.maybe_tx(conn):
        stats.plan = plan_import(conn, rows)
        existing = {str(r[0]) for r in conn.execute("SELECT lemma FROM words")}
        stats.inserted = sum(1 for lemma in rows if lemma not in existing)
        before = conn.total_changes
        conn.executemany(_UPSERT_SQL, list(rows.values()))
        stats.updated = max(0, conn.total_changes - before - stats.inserted)
        _rebuild_forms(conn, rows, stats)
        db.kv_set(conn, "seed_version", digest, now=now)
        db.kv_set(conn, "seed_imported_at", now, now=now)
        conn.execute(
            "INSERT INTO system_events(kind, detail_json, created_at) VALUES ('seed_imported', ?, ?)",
            (
                json.dumps(
                    {
                        "file": p.name,
                        "sha256": stats.sha256,
                        "content_sha256": digest,
                        "records": stats.records,
                        "inserted": stats.inserted,
                        "updated": stats.updated,
                        "forms": stats.forms,
                        "aliases": stats.aliases,
                        "unknown_stage_codes": stats.unknown_stage_codes,
                        "lemma_mismatch": stats.lemma_mismatch,
                        "stageless": stats.stageless_records,
                        "orphans": len(stats.plan.orphans),
                        "flag_added": stats.plan.flag_added,
                        "flag_removed": stats.plan.flag_removed,
                        "force": bool(force),
                    }
                ),
                now,
            ),
        )
    stats.seconds = time.monotonic() - t0
    log.info(
        "seed imported: %d records, %d inserted, %d updated, %d forms (%d aliases), %d stageless (%.1f s)",
        stats.records,
        stats.inserted,
        stats.updated,
        stats.forms,
        stats.aliases,
        stats.stageless_records,
        stats.seconds,
        extra={"event": "seed_imported"},
    )
    return stats


def _flags(counts: Mapping[str, int]) -> str:
    return "{" + ", ".join(f"{s}:{n}" for s, n in counts.items() if n) + "}"


def format_stats(stats: SeedStats) -> str:
    extra = ""
    if stats.skipped_records or stats.duplicate_lemmas:
        extra += f", {stats.skipped_records} skipped, {stats.duplicate_lemmas} duplicate lemmas"
    if stats.unknown_stage_codes:
        extra += f", {stats.unknown_stage_codes} unknown stage codes ignored"
    if stats.lemma_mismatch:
        extra += f", {stats.lemma_mismatch} lemma mismatches"
    if stats.dry_run and stats.plan is not None:
        p = stats.plan
        head = "dry run: "
        if stats.up_to_date:
            head += "seed up to date (kv.seed_version matches the content sha256); --force would "
        lines = [
            head
            + f"insert {p.inserted} / update {p.updated} / unchanged {p.unchanged}; orphans {len(p.orphans)}; "
            f"flags +{_flags(p.flag_added)} −{_flags(p.flag_removed)}; stage_min lowered {p.min_lowered} / raised {p.min_raised}; "
            f"stageless {p.stageless} ({stats.records} records from {stats.path}{extra}; {stats.seconds:.1f} s)"
        ]
        lines.extend(f"  stage_min {k}: {v}" for k, v in sorted(p.matrix.items()))
        if p.orphans:
            lines.append(f"  orphans (seed rows not in the file, kept): {', '.join(p.orphans[:10])}{' …' if len(p.orphans) > 10 else ''}")
        return "\n".join(lines)
    if stats.up_to_date:
        return f"seed up to date (content sha256 {stats.content_sha256[:12]}…, {stats.path})"
    return (
        f"imported {stats.records} seed records from {stats.path}: {stats.inserted} inserted, {stats.updated} updated{extra}; "
        f"{stats.forms} word forms incl. {stats.aliases} aliases ({stats.forms_skipped_empty} empty and {stats.forms_skipped_headword} headword forms skipped); "
        f"{stats.stageless_records} stageless; {stats.seconds:.1f} s"
    )


# ------------------------------------------------------------------------------------------ CLI
def cmd_import_seed(args: argparse.Namespace) -> int:
    try:
        cfg = Settings.from_env()
    except ConfigError as e:
        print(f"wd: configuration error: {e}", file=sys.stderr)
        return 2
    ensure_dirs(cfg)
    path = Path(args.file).expanduser() if args.file else cfg.seed_path
    if not path.is_file():
        print(f"wd import-seed: seed file not found: {path}", file=sys.stderr)
        return 1
    conn = db.connect(cfg.db_path)
    try:
        if db.current_version(conn) == 0:
            print("wd import-seed: the database has no schema yet — run `wd migrate` first", file=sys.stderr)
            return 1
        pending = db.pending_migrations(conn)
        if pending:
            # a database behind the code's schema (the live copy sits at version 10 until 0011 adds `stage_xs`): the UPSERT and
            # even --dry-run's SELECT would die on `no such column` with a traceback. Same one-line answer as the empty-database
            # branch — the operator's next step is `wd migrate` either way (DEPLOY §9/§10; PLAN §8 steps 6 → 7 in that order).
            names = ", ".join(f.path.name for f in pending)
            print(f"wd import-seed: {len(pending)} pending migration(s) ({names}) — run `wd migrate` first", file=sys.stderr)
            return 1
        try:
            stats = import_seed(conn, str(path), force=bool(args.force), dry_run=bool(getattr(args, "dry_run", False)))
        except (OSError, EOFError, ValueError, zlib.error) as e:
            # a corrupt archive / undecodable file: say so instead of a traceback — a truncated gzip is EOFError, a bad header
            # BadGzipFile (OSError), a valid header over a corrupt deflate body zlib.error (the net main.seed_check casts, R-9)
            print(f"wd import-seed: cannot read {path}: {type(e).__name__}: {e}", file=sys.stderr)
            return 1
        except sqlite3.Error as e:
            # the backstop behind the guard above (a hand-edited table, a foreign database file): the import runs inside one
            # transaction and has rolled back — one line like the cases above, never a traceback
            print(f"wd import-seed: database error: {type(e).__name__}: {e}", file=sys.stderr)
            return 1
    finally:
        conn.close()
    print(format_stats(stats))
    report = getattr(args, "report", None)
    if report:
        out = Path(report).expanduser()
        try:
            out.write_text(json.dumps(stats.as_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except OSError as e:  # the import (or dry run) above is done; only the report is missing — say so, exit non-zero
            print(f"wd import-seed: cannot write report {out}: {e}", file=sys.stderr)
            return 1
    return 0


def register_cli(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("import-seed", help="import or refresh the vocabulary seed (idempotent upsert keyed by lemma)")
    p.add_argument("--file", default=None, metavar="PATH", help="seed file, .jsonl or .jsonl.gz (default: WD_SEED_PATH)")
    p.add_argument("--force", action="store_true", help="re-import even when kv.seed_version already matches the content sha256")
    p.add_argument("--dry-run", action="store_true", help="read the file and report what an import would insert/update/flip — writes nothing")
    p.add_argument("--report", default=None, metavar="PATH", help="also write the stats (incl. the plan) as JSON to PATH")
    p.set_defaults(func=cmd_import_seed)


__all__ = [
    "SEED_COLUMNS",
    "STAGE_COLUMNS",
    "SeedPlan",
    "SeedStats",
    "format_stats",
    "import_seed",
    "iter_records",
    "plan_import",
    "register_cli",
    "seed_digest",
    "seed_row",
    "sha256_file",
]
