"""Seed import (WP1): ``import_seed`` and the ``wd import-seed`` command — DESIGN §3.2, TASKS WP1.

The seed is ``data/seed/vocab.jsonl.gz`` (one JSON record per word, built by ``scripts/build_seed.py``). The import is
an idempotent upsert keyed by ``words.lemma``:

* dictionary columns (``display``, ``kind``, ``phonetic``, ``translation``, ``definition``, ``pos``, ``collins``, ``oxford``,
  ``exam_tags``, ``bnc``, ``frq``, ``exchange_json``, the four stage flags, ``stage_min``, ``cet6_star``, ``sources``,
  ``ecdict_id``) are written from the record; ``source='seed'``, ``is_public=1``, ``is_valid_english=1``,
  ``safe_for_sharing=1`` and ``merged_into_word_id=NULL`` (a seed headword stands on its own);
* ``active_content_id``, ``active_image_id``, ``content_state``, ``image_state``, ``difficulty``, ``created_by_user_id``
  and every per-user table are never touched; an unchanged row is not rewritten (``updated_at`` only moves when a
  column really changed);
* ``word_forms`` is rebuilt for the imported words from the exchange codes ``p d i 3 s r t`` (``0 1 f b z`` ignored)
  with the SCHEMA guards: empty forms skipped, a form that is itself a ``words.lemma`` never inserted, one row per
  ``(form, word_id)`` (ambiguous forms keep one row per lemma); ``alt`` rows written by lookup/consolidation survive;
* ``kv.seed_version`` = sha256 of the file (what ``main.seed_check`` compares) and ``kv.seed_imported_at`` are set and a
  ``system_events('seed_imported')`` row is written — all inside one ``BEGIN IMMEDIATE`` transaction.

A second run with the same file is a no-op ("seed up to date") unless ``--force``.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import logging
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping

from . import db
from .clock import now_iso
from .config import ConfigError, Settings, ensure_dirs
from .services.words import derive_kind, normalise_input, normalise_lemma

log = logging.getLogger("wd.seed")

STAGES: tuple[str, ...] = ("zk", "gk", "cet4", "cet6")
EXAM_TAGS: tuple[str, ...] = ("ky", "toefl", "ielts", "gre")
FORM_CODES: tuple[str, ...] = ("p", "d", "i", "3", "s", "r", "t")  # priority order when one (form, word) carries several codes

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
    "stage_zk",
    "stage_gk",
    "stage_cet4",
    "stage_cet6",
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


@dataclass
class SeedStats:
    """What :func:`import_seed` did (``up_to_date`` = nothing was written because ``kv.seed_version`` matched)."""

    path: str
    sha256: str
    records: int = 0
    inserted: int = 0
    updated: int = 0
    skipped_records: int = 0
    duplicate_lemmas: int = 0
    forms: int = 0
    forms_skipped_empty: int = 0
    forms_skipped_headword: int = 0
    up_to_date: bool = False
    seconds: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# ------------------------------------------------------------------------------------------ reading
def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def iter_records(path: str | Path) -> Iterator[dict[str, Any]]:
    """Yield the JSON objects of a ``.jsonl`` or ``.jsonl.gz`` file (blank lines skipped, bad lines logged and skipped)."""
    p = Path(path)
    opener = gzip.open if p.suffix == ".gz" else io.open
    with opener(p, "rt", encoding="utf-8") as f:  # type: ignore[operator]
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
    """Map one seed record onto the ``words`` columns (DESIGN §3.2); None for a record without a usable ``word``.

    ``lemma = normalise(word)`` through :func:`normalise_input`; a record the strict normaliser rejects (none in the
    shipped seed) falls back to the lenient key so dictionary data is never dropped silently. ``_exchange`` carries the
    raw exchange mapping for the ``word_forms`` rebuild (ignored by the named-parameter UPSERT).
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
    stages = [s for s in STAGES if isinstance(raw_stages, (list, tuple)) and s in raw_stages]
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
        "stage_zk": int("zk" in stages),
        "stage_gk": int("gk" in stages),
        "stage_cet4": int("cet4" in stages),
        "stage_cet6": int("cet6" in stages),
        "stage_min": (STAGES.index(stages[0]) + 1) if stages else None,
        "cet6_star": int(bool(rec.get("cet6_star"))),
        "sources": " ".join(sorted({str(s) for s in sources})) if isinstance(sources, (list, tuple)) and sources else None,
        "ecdict_id": _int(rec.get("ecdict_id")),
        "now": now,
        "_exchange": exchange,
    }


# ------------------------------------------------------------------------------------------ importing
def _rebuild_forms(conn, rows: Mapping[str, dict[str, Any]], stats: SeedStats) -> None:
    """Delete the non-``alt`` forms of the imported words and re-insert them from the exchange codes with the guards."""
    ids: dict[str, int] = {str(r[0]): int(r[1]) for r in conn.execute("SELECT lemma, id FROM words WHERE source = 'seed'")}
    conn.executemany(
        "DELETE FROM word_forms WHERE word_id = ? AND kind != 'alt'",
        [(ids[lemma],) for lemma in rows if lemma in ids],
    )
    lemmas = {str(r[0]) for r in conn.execute("SELECT lemma FROM words")}
    pairs: dict[tuple[str, int], str] = {}
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
    before = conn.total_changes
    conn.executemany("INSERT OR IGNORE INTO word_forms(form, word_id, kind) VALUES (?, ?, ?)", [(f, w, k) for (f, w), k in pairs.items()])
    stats.forms = conn.total_changes - before


def import_seed(conn, path: str, *, force: bool = False) -> SeedStats:
    """Import or refresh the seed at ``path`` (``.jsonl`` / ``.jsonl.gz``) — see the module docstring for the rules.

    Returns :class:`SeedStats`; ``up_to_date`` is True (and nothing is written) when ``kv.seed_version`` already equals
    the file's sha256 and ``force`` is False. Raises ``FileNotFoundError`` for a missing file.
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"seed file not found: {p}")
    t0 = time.monotonic()
    digest = sha256_file(p)
    stats = SeedStats(path=str(p), sha256=digest)
    if not force and db.kv_get(conn, "seed_version") == digest:
        stats.up_to_date = True
        stats.seconds = time.monotonic() - t0
        return stats

    now = now_iso()
    rows: dict[str, dict[str, Any]] = {}
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

    with db.maybe_tx(conn):
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
                        "sha256": digest,
                        "records": stats.records,
                        "inserted": stats.inserted,
                        "updated": stats.updated,
                        "forms": stats.forms,
                        "force": bool(force),
                    }
                ),
                now,
            ),
        )
    stats.seconds = time.monotonic() - t0
    log.info(
        "seed imported: %d records, %d inserted, %d updated, %d forms (%.1f s)",
        stats.records,
        stats.inserted,
        stats.updated,
        stats.forms,
        stats.seconds,
        extra={"event": "seed_imported"},
    )
    return stats


def format_stats(stats: SeedStats) -> str:
    if stats.up_to_date:
        return f"seed up to date (sha256 {stats.sha256[:12]}…, {stats.path})"
    extra = ""
    if stats.skipped_records or stats.duplicate_lemmas:
        extra = f", {stats.skipped_records} skipped, {stats.duplicate_lemmas} duplicate lemmas"
    return (
        f"imported {stats.records} seed records from {stats.path}: {stats.inserted} inserted, {stats.updated} updated{extra}; "
        f"{stats.forms} word forms ({stats.forms_skipped_empty} empty and {stats.forms_skipped_headword} headword forms skipped); "
        f"{stats.seconds:.1f} s"
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
        stats = import_seed(conn, str(path), force=bool(args.force))
    finally:
        conn.close()
    print(format_stats(stats))
    return 0


def register_cli(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("import-seed", help="import or refresh the vocabulary seed (idempotent upsert keyed by lemma)")
    p.add_argument("--file", default=None, metavar="PATH", help="seed file, .jsonl or .jsonl.gz (default: WD_SEED_PATH)")
    p.add_argument("--force", action="store_true", help="re-import even when kv.seed_version already matches the file")
    p.set_defaults(func=cmd_import_seed)


__all__ = ["SeedStats", "format_stats", "import_seed", "iter_records", "register_cli", "seed_row", "sha256_file"]
