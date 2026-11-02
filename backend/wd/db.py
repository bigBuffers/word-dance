"""SQLite access (Phase 0, frozen contract — TASKS.md P0 step 4, SCHEMA.sql header, DESIGN §3).

* :func:`connect` opens ``sqlite3.connect(path, autocommit=True, timeout=5)`` — the Python 3.12
  API in which the module never opens implicit transactions, so ``conn.executescript()`` cannot
  issue an implicit ``COMMIT`` behind the runner's back (verified on this box: in the legacy mode
  ``executescript`` commits first and the atomicity guarantee silently fails) — and applies the
  per-connection PRAGMAs. One connection per request/job; never shared across threads.
* :func:`tx` issues explicit ``BEGIN IMMEDIATE`` / ``COMMIT`` / ``ROLLBACK`` with ``SQLITE_BUSY``
  retries (3×, 50/100/200 ms).
* :func:`run_migrations` implements THE bookkeeping rule: pending = ``migrations/NNNN_*.sql`` whose
  ``NNNN`` is not in ``schema_migrations``; ``pre_hook(from_version, to_version)`` runs once before
  the first pending file; each file is executed inside one explicit ``BEGIN IMMEDIATE`` and the
  runner itself inserts ``schema_migrations(version, name)`` in that transaction, ``COMMIT``s, and
  ``ROLLBACK``s everything on any error. Migration files never self-register.
  The runner also owns foreign-key enforcement around each file: ``PRAGMA foreign_keys=OFF`` *before*
  ``BEGIN`` (the PRAGMA is a silent no-op inside a transaction), ``PRAGMA foreign_key_check`` before the
  bookkeeping row (any violation fails the file), ``PRAGMA foreign_keys=ON`` again afterwards on both
  paths. That is SQLite's own table-rebuild recipe (`ALTER TABLE` cannot change a CHECK list; the
  parent table is re-created and the old one dropped) — with enforcement ON, ``DROP TABLE users``
  would cascade-delete every child row and the runner would commit the loss as a successful
  migration. A file must therefore not toggle ``PRAGMA foreign_keys`` itself, must delete child rows
  explicitly when it deletes parents (there are no ON DELETE actions during a migration), and
  ``PRAGMA defer_foreign_keys`` / rename-first orderings are not alternatives (see test_db.py).
* :func:`kv_get` / :func:`kv_set` wrap the ``kv`` table.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator

log = logging.getLogger("wd.db")

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
MIGRATION_FILE_RE = re.compile(r"^(\d{4})_([A-Za-z0-9][A-Za-z0-9_-]*)\.sql$")

# journal_mode is persistent in the file; the others are per connection (SCHEMA.sql header)
PRAGMAS = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA foreign_keys=ON",
    "PRAGMA busy_timeout=5000",
    "PRAGMA temp_store=MEMORY",
    "PRAGMA cache_size=-20000",
)

BUSY_RETRIES_MS = (50, 100, 200)

PreHook = Callable[[int, int], None]


class MigrationError(RuntimeError):
    """A migration file failed; everything it did was rolled back together with its bookkeeping row."""

    def __init__(self, version: int, name: str, cause: BaseException):
        super().__init__(f"migration {version:04d}_{name}.sql failed and was rolled back: {cause}")
        self.version = version
        self.name = name
        self.cause = cause


@dataclass(frozen=True)
class MigrationFile:
    version: int
    name: str
    path: Path


@dataclass
class MigrationResult:
    from_version: int
    to_version: int
    applied: list[tuple[int, str]] = field(default_factory=list)
    pending: list[tuple[int, str]] = field(default_factory=list)  # files that were pending before this run (== applied unless dry_run)

    @property
    def dry_run(self) -> bool:
        return bool(self.pending) and not self.applied


# ----------------------------------------------------------------------------- connections
def connect(path: str | Path, *, timeout: float = 5.0, check_same_thread: bool = True) -> sqlite3.Connection:
    """Open one connection with ``autocommit=True`` and the DESIGN §3 PRAGMAs.

    ``row_factory`` is :class:`sqlite3.Row`. ``check_same_thread`` stays at its default for job and
    CLI connections; request connections (``deps.get_db``) pass ``False`` because FastAPI runs a
    sync dependency and its endpoint on arbitrary threadpool threads *sequentially* — safe with
    this build's serialized SQLite (``sqlite3.threadsafety == 3``), and the connection is still
    never used by two threads at once.
    """
    conn = sqlite3.connect(str(path), timeout=timeout, autocommit=True, check_same_thread=check_same_thread)
    conn.row_factory = sqlite3.Row
    for pragma in PRAGMAS:
        conn.execute(pragma)
    return conn


def _is_busy(e: sqlite3.OperationalError) -> bool:
    msg = str(e).lower()
    return "locked" in msg or "busy" in msg


def begin(conn: sqlite3.Connection, immediate: bool = True) -> None:
    """``BEGIN [IMMEDIATE]`` with SQLITE_BUSY retries (busy_timeout already waits up to 5 s per attempt)."""
    stmt = "BEGIN IMMEDIATE" if immediate else "BEGIN"
    for attempt, pause_ms in enumerate((*BUSY_RETRIES_MS, None)):
        try:
            conn.execute(stmt)
            return
        except sqlite3.OperationalError as e:
            if pause_ms is None or not _is_busy(e):
                raise
            log.debug("BEGIN busy (attempt %d): %s", attempt + 1, e)
            time.sleep(pause_ms / 1000)


@contextmanager
def tx(conn: sqlite3.Connection, immediate: bool = True) -> Iterator[sqlite3.Connection]:
    """Explicit transaction: ``BEGIN IMMEDIATE`` (default) … ``COMMIT``, ``ROLLBACK`` on any exception.

    Nested use is a programming error (SQLite has no nested transactions; use savepoints explicitly
    if ever needed) and raises :class:`sqlite3.ProgrammingError`.
    """
    if conn.in_transaction:
        raise sqlite3.ProgrammingError("tx(): a transaction is already open on this connection")
    begin(conn, immediate)
    try:
        yield conn
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    else:
        if conn.in_transaction:
            conn.execute("COMMIT")


@contextmanager
def maybe_tx(conn: sqlite3.Connection, immediate: bool = True) -> Iterator[sqlite3.Connection]:
    """Join the caller's open transaction if there is one, otherwise run inside :func:`tx`.

    Lets queue/stats helpers be composed into a caller's ``BEGIN IMMEDIATE`` (e.g. ``build_batch``
    enqueueing content jobs) while remaining atomic when called on their own.
    """
    if conn.in_transaction:
        yield conn
    else:
        with tx(conn, immediate):
            yield conn


# ----------------------------------------------------------------------------- migrations
def list_migration_files(migrations_dir: str | Path | None = None) -> list[MigrationFile]:
    """All ``NNNN_name.sql`` files sorted by version; duplicate versions are an error."""
    d = Path(migrations_dir) if migrations_dir is not None else MIGRATIONS_DIR
    files: dict[int, MigrationFile] = {}
    for p in sorted(d.glob("*.sql")):
        m = MIGRATION_FILE_RE.match(p.name)
        if not m:
            log.warning("ignoring migration file with an unexpected name: %s", p.name)
            continue
        version, name = int(m.group(1)), m.group(2)
        if version in files:
            raise MigrationError(version, name, ValueError(f"duplicate migration version {version:04d} ({files[version].path.name} and {p.name})"))
        files[version] = MigrationFile(version, name, p)
    return [files[v] for v in sorted(files)]


def applied_versions(conn: sqlite3.Connection) -> set[int]:
    """Versions recorded in ``schema_migrations`` (empty on a fresh database)."""
    try:
        return {int(r[0]) for r in conn.execute("SELECT version FROM schema_migrations")}
    except sqlite3.OperationalError as e:
        if "no such table" in str(e):
            return set()
        raise


def current_version(conn: sqlite3.Connection) -> int:
    """Highest applied migration version (0 on a fresh database)."""
    return max(applied_versions(conn), default=0)


def pending_migrations(conn: sqlite3.Connection, migrations_dir: str | Path | None = None) -> list[MigrationFile]:
    done = applied_versions(conn)
    return [f for f in list_migration_files(migrations_dir) if f.version not in done]


def run_migrations(
    conn: sqlite3.Connection,
    *,
    pre_hook: PreHook | None = None,
    migrations_dir: str | Path | None = None,
    dry_run: bool = False,
) -> MigrationResult:
    """Apply every pending migration file atomically; see the module docstring for the rule.

    ``pre_hook(from_version, to_version)`` (e.g. ``wd.backup.snapshot_before_migrate``) is called
    exactly once, before the first pending file, and only when something is pending.
    With ``dry_run=True`` nothing is executed and ``result.pending`` lists what would run.
    """
    if conn.in_transaction:
        raise sqlite3.ProgrammingError("run_migrations(): the connection must not be inside a transaction")
    pending = pending_migrations(conn, migrations_dir)
    from_version = current_version(conn)
    to_version = pending[-1].version if pending else from_version
    result = MigrationResult(from_version=from_version, to_version=to_version, pending=[(f.version, f.name) for f in pending])
    if not pending or dry_run:
        return result

    if pre_hook is not None:
        pre_hook(from_version, to_version)

    for mf in pending:
        sql = mf.path.read_text(encoding="utf-8")
        # Foreign-key enforcement is switched off OUTSIDE the transaction (inside one the PRAGMA is a silent no-op):
        # SQLite's table-rebuild recipe (CREATE new → INSERT … SELECT → DROP old → RENAME) is the only way to change a
        # CHECK list, and with enforcement ON the DROP runs an implicit DELETE whose ON DELETE CASCADE / SET NULL
        # actions empty every child table — committed below as a successful migration. foreign_key_check rejects a
        # file that leaves real orphans instead, so a data migration deleting parents must delete their children too.
        conn.execute("PRAGMA foreign_keys=OFF")
        try:
            begin(conn, immediate=True)
            try:
                conn.executescript(sql)  # runs inside OUR transaction: autocommit=True ⇒ no implicit COMMIT
                if not conn.in_transaction:
                    # a file that COMMITs itself breaks the atomicity rule; refuse loudly rather than record it
                    raise sqlite3.IntegrityError(f"{mf.path.name} ended the transaction itself (COMMIT/ROLLBACK inside a migration file is forbidden)")
                violations = conn.execute("PRAGMA foreign_key_check").fetchall()
                if violations:
                    shown = "; ".join(f"{r[0]} rowid {r[1]} → {r[2]}" for r in violations[:5])
                    raise sqlite3.IntegrityError(f"{mf.path.name} leaves {len(violations)} foreign-key violation(s): {shown}")
                conn.execute("INSERT INTO schema_migrations(version, name) VALUES (?, ?)", (mf.version, mf.name))
                conn.execute("COMMIT")
            except BaseException as e:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise MigrationError(mf.version, mf.name, e) from e
        finally:
            conn.execute("PRAGMA foreign_keys=ON")  # the transaction is over on both paths; the connection is reused by cli/main/worker
        result.applied.append((mf.version, mf.name))
        log.info("applied migration %04d_%s", mf.version, mf.name, extra={"event": "migration"})
    return result


def backup_pre_hook() -> PreHook:
    """``wd.backup.snapshot_before_migrate`` — the pre-migrate snapshot hook for :func:`run_migrations`.

    Imported here rather than at module level because ``wd.backup`` imports this module (DEPLOY §5: the hook
    writes ``backups/pre-migrate-<from>-to-<to>.db.gz`` through the same VACUUM INTO → integrity_check → gzip
    pipeline as ``wd backup``).
    """
    from .backup import snapshot_before_migrate

    return snapshot_before_migrate


# ----------------------------------------------------------------------------- kv + introspection
def kv_get(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
    return default if row is None else str(row[0])


def kv_set(conn: sqlite3.Connection, key: str, value: str, *, now: str | None = None) -> None:
    """Upsert ``kv(key, value)``; ``updated_at`` is ``now`` (ISO) or the SQL clock."""
    if now is None:
        conn.execute(
            "INSERT INTO kv(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ','now')",
            (key, value),
        )
    else:
        conn.execute(
            "INSERT INTO kv(key, value, updated_at) VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (key, value, now),
        )


def kv_delete(conn: sqlite3.Connection, key: str) -> None:
    conn.execute("DELETE FROM kv WHERE key = ?", (key,))


def table_names(conn: sqlite3.Connection) -> list[str]:
    """User tables (excluding SQLite's internal ``sqlite_*`` tables)."""
    return [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]


def view_names(conn: sqlite3.Connection) -> list[str]:
    return [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='view' ORDER BY name")]


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return None if row is None else {k: row[k] for k in row.keys()}
