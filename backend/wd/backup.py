"""Backups and restore (WP9 — DEPLOY.md §5, DESIGN §11).

* ``wd backup [--keep-daily N] [--keep-weekly M] [--with-images]``: ``VACUUM INTO`` a consistent online snapshot
  (works while the service runs, WAL) → ``PRAGMA integrity_check`` on the copy → gzip →
  ``$DATA/backups/word-dance-YYYYMMDD-HHMM.db.gz`` (0600) → retention (newest N daily + Sunday copies up to M
  weekly) → ``kv.backup.last = {file, at, bytes}`` (shown as ``AdminHealth.last_backup``). An integrity failure
  records ``system_events('backup_failed')``, leaves no file behind and exits non-zero.
* :func:`snapshot_before_migrate` — the ``pre_hook`` that ``cli.py``'s ``migrate`` (and the ``main.py`` lifespan)
  pass through ``db.backup_pre_hook()``: writes ``backups/pre-migrate-<from>-to-<to>.db.gz`` through the same
  pipeline before the first pending migration file runs. A fresh database (``from_version == 0``) has nothing to protect and is skipped.
* ``wd restore <file.db.gz> [--yes]``: refuses while the service runs (``kv.worker_lease`` live or
  ``systemctl is-active word-dance.service``), verifies the archive first (gunzip → ``integrity_check``, into
  ``word-dance.db.restore-<ts>`` **next to the target**, so the final rename never crosses a filesystem even when
  ``WD_DB_PATH`` lives outside ``WD_DATA_DIR``), folds the WAL of the current database with ``wal_checkpoint(TRUNCATE)``
  and refuses (exit 2) when SQLite reports it blocked — another connection holds an open transaction and the frames
  left in the WAL would be the only copy of the newest commits — then keeps the current database as
  ``word-dance.db.bak-<ts>`` (a hard link; a copy where links are unsupported), moves its ``-wal``/``-shm`` next to
  that name (SQLite recovers them when the ``.bak`` is opened, so the kept copy is complete even when the checkpoint
  could not run on a damaged file), swaps the verified copy in with ONE atomic ``os.replace`` — the database path is
  never absent, and a failed swap leaves the current database untouched (exit 1) — sets 0600 and prints
  ``sudo systemctl start word-dance``.

File names use the operational timezone ``WD_TZ`` (the timer fires at 03:30 Asia/Shanghai → ``…-0330.db.gz``);
``kv.backup.last.at`` is UTC like every other timestamp. Images are re-fetchable and not backed up unless
``--with-images`` adds ``images-YYYYMMDD.tar``. Pre-migrate snapshots are never pruned by the retention rule.
"""

from __future__ import annotations

import argparse
import gzip
import json
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tarfile
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import db
from .clock import UTC, SystemClock, to_iso
from .config import Settings

log = logging.getLogger("wd.backup")

BACKUP_RE = re.compile(r"^word-dance-(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})\.db\.gz$")
IMAGES_TAR_RE = re.compile(r"^images-(\d{4})(\d{2})(\d{2})\.tar$")
PRE_MIGRATE_NAME = "pre-migrate-{from_version}-to-{to_version}.db.gz"
SERVICE_NAME = "word-dance.service"
CHUNK = 1 << 20
CHECKPOINT_TIMEOUT_S = 5.0  # busy wait of the wal_checkpoint before a restore (tests lower it)
DB_SIDE_SUFFIXES = ("-wal", "-shm")


class BackupError(RuntimeError):
    """A snapshot could not be produced or verified; nothing was left in ``backups/``."""


@dataclass
class BackupResult:
    path: Path
    bytes: int
    at: str
    removed: list[Path] = field(default_factory=list)
    images_tar: Path | None = None


# ------------------------------------------------------------------------------------------- helpers
def _now(now: datetime | None) -> datetime:
    return (now or SystemClock().now_utc()).astimezone(UTC)


def _local(now: datetime, tz: str) -> datetime:
    return now.astimezone(ZoneInfo(tz))


def backup_name(now: datetime, tz: str) -> str:
    """``word-dance-YYYYMMDD-HHMM.db.gz`` in the operational timezone."""
    return _local(now, tz).strftime("word-dance-%Y%m%d-%H%M.db.gz")


def images_tar_name(now: datetime, tz: str) -> str:
    return _local(now, tz).strftime("images-%Y%m%d.tar")


def _open_private(path: Path) -> int:
    """Create ``path`` 0600 regardless of the umask (never truncating a stranger's file: O_EXCL)."""
    return os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)


def integrity_ok(path: Path) -> tuple[bool, str]:
    """``PRAGMA integrity_check`` on a database file; ``(True, 'ok')`` or ``(False, <first problem>)``."""
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error as e:
        return False, f"cannot open: {e}"
    try:
        rows = conn.execute("PRAGMA integrity_check").fetchall()
    except sqlite3.Error as e:
        return False, str(e)
    finally:
        conn.close()
    if len(rows) == 1 and str(rows[0][0]).lower() == "ok":
        return True, "ok"
    return False, "; ".join(str(r[0]) for r in rows[:5]) or "integrity_check returned nothing"


def _gzip_file(src: Path, dest: Path) -> int:
    """Compress ``src`` into a new ``dest`` (0600, written next to it as ``dest.part`` first); returns the size."""
    part = dest.with_name(dest.name + ".part")
    if part.exists():
        part.unlink()
    fd = _open_private(part)
    try:
        with os.fdopen(fd, "wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=6, mtime=0) as gz, src.open("rb") as f:
            shutil.copyfileobj(f, gz, CHUNK)
            gz.close()
            raw.flush()
            os.fsync(raw.fileno())
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    os.replace(part, dest)
    return dest.stat().st_size


def _gunzip_file(src: Path, dest: Path) -> None:
    fd = _open_private(dest)
    try:
        with os.fdopen(fd, "wb") as out, gzip.open(src, "rb") as gz:
            shutil.copyfileobj(gz, out, CHUNK)
            out.flush()
            os.fsync(out.fileno())
    except BaseException:
        dest.unlink(missing_ok=True)
        raise


def snapshot(db_path: Path, dest: Path, *, tmp_dir: Path, tag: str) -> int:
    """``VACUUM INTO`` → ``integrity_check`` → gzip into ``dest`` (0600). Returns the compressed size.

    The intermediate copy lives in ``tmp_dir`` and is always removed; ``dest`` is replaced atomically, so a reader
    never sees a half-written archive. Raises :class:`BackupError` with the reason on any failure.
    """
    tmp_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    dest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    copy = tmp_dir / f"word-dance-{tag}.db"
    copy.unlink(missing_ok=True)
    try:
        conn = db.connect(db_path)
        try:
            conn.execute("VACUUM INTO ?", (str(copy),))
        finally:
            conn.close()
        try:
            copy.chmod(0o600)
        except OSError:  # pragma: no cover - ownership problems are not fatal for the snapshot itself
            pass
        ok, detail = integrity_ok(copy)
        if not ok:
            raise BackupError(f"integrity_check failed on the snapshot of {db_path}: {detail}")
        return _gzip_file(copy, dest)
    except BackupError:
        raise
    except (sqlite3.Error, OSError) as e:
        raise BackupError(f"snapshot of {db_path} failed: {e}") from e
    finally:
        copy.unlink(missing_ok=True)


def record_failure(db_path: Path, error: str, *, file: str | None = None, now: datetime | None = None) -> None:
    """``system_events('backup_failed')`` — best effort (the database itself may be the problem)."""
    try:
        conn = db.connect(db_path)
        try:
            conn.execute(
                "INSERT INTO system_events(kind, detail_json, created_at) VALUES ('backup_failed', ?, ?)",
                (json.dumps({"error": error, "file": file}, ensure_ascii=False), to_iso(_now(now))),
            )
        finally:
            conn.close()
    except sqlite3.Error as e:
        log.error("could not record backup_failed: %s", e)


# ----------------------------------------------------------------------------------------- retention
def _dated_files(backups_dir: Path, pattern: re.Pattern[str]) -> list[tuple[tuple[int, ...], Path]]:
    out: list[tuple[tuple[int, ...], Path]] = []
    for p in backups_dir.iterdir():
        m = pattern.match(p.name)
        if m and p.is_file():
            out.append((tuple(int(g) for g in m.groups()), p))
    out.sort(reverse=True)  # newest first
    return out


def select_for_removal(files: list[tuple[tuple[int, ...], Path]], *, keep_daily: int, keep_weekly: int) -> list[Path]:
    """Retention rule: the newest ``keep_daily`` files stay; among the older ones a Sunday copy per ISO week stays,
    newest weeks first, up to ``keep_weekly``; everything else is returned for deletion."""
    keep: set[Path] = {p for _, p in files[: max(0, keep_daily)]}
    weeks_kept: set[tuple[int, int]] = set()
    for key, p in files[max(0, keep_daily):]:
        d = date(key[0], key[1], key[2])
        if d.weekday() != 6:  # Sunday
            continue
        week = d.isocalendar()[:2]
        if week in weeks_kept or len(weeks_kept) >= max(0, keep_weekly):
            continue
        weeks_kept.add(week)
        keep.add(p)
    return [p for _, p in files if p not in keep]


def apply_retention(backups_dir: Path, *, keep_daily: int, keep_weekly: int) -> list[Path]:
    """Delete snapshots and image tars outside the retention rule; pre-migrate snapshots are never touched."""
    removed: list[Path] = []
    for pattern in (BACKUP_RE, IMAGES_TAR_RE):
        for p in select_for_removal(_dated_files(backups_dir, pattern), keep_daily=keep_daily, keep_weekly=keep_weekly):
            try:
                p.unlink()
                removed.append(p)
            except OSError as e:
                log.warning("could not remove old backup %s: %s", p, e)
    return removed


# -------------------------------------------------------------------------------------------- backup
def _tar_images(images_dir: Path, dest: Path) -> int:
    part = dest.with_name(dest.name + ".part")
    part.unlink(missing_ok=True)
    fd = _open_private(part)
    try:
        with os.fdopen(fd, "wb") as raw, tarfile.open(fileobj=raw, mode="w") as tar:
            tar.add(str(images_dir), arcname="images", recursive=True)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    os.replace(part, dest)
    return dest.stat().st_size


def run_backup(cfg: Settings, *, keep_daily: int, keep_weekly: int, with_images: bool = False, now: datetime | None = None) -> BackupResult:
    """The ``wd backup`` pipeline (DEPLOY §5). Raises :class:`BackupError` after recording ``backup_failed``."""
    when = _now(now)
    at = to_iso(when)
    name = backup_name(when, cfg.tz)
    dest = cfg.backups_dir / name
    if not cfg.db_path.is_file():
        raise BackupError(f"database {cfg.db_path} does not exist")
    try:
        size = snapshot(cfg.db_path, dest, tmp_dir=cfg.tmp_dir, tag=_local(when, cfg.tz).strftime("%Y%m%d-%H%M%S"))
    except BackupError as e:
        record_failure(cfg.db_path, str(e), file=name, now=when)
        raise
    result = BackupResult(path=dest, bytes=size, at=at)
    if with_images:
        tar_dest = cfg.backups_dir / images_tar_name(when, cfg.tz)
        if cfg.images_dir.is_dir():
            try:
                _tar_images(cfg.images_dir, tar_dest)
                result.images_tar = tar_dest
            except OSError as e:
                record_failure(cfg.db_path, f"images tar failed: {e}", file=tar_dest.name, now=when)
                raise BackupError(f"images tar failed: {e}") from e
        else:
            log.warning("images directory %s does not exist; no images tar", cfg.images_dir)
    result.removed = apply_retention(cfg.backups_dir, keep_daily=keep_daily, keep_weekly=keep_weekly)
    conn = db.connect(cfg.db_path)
    try:
        db.kv_set(conn, "backup.last", json.dumps({"file": name, "at": at, "bytes": size}), now=at)
    finally:
        conn.close()
    log.info("backup written %s (%d bytes), %d old file(s) removed", dest, size, len(result.removed), extra={"event": "backup"})
    return result


def snapshot_before_migrate(from_version: int, to_version: int) -> None:
    """``pre_hook`` of ``db.run_migrations`` (TASKS P0 step 4 / DEPLOY §5): ``backups/pre-migrate-<from>-to-<to>.db.gz``.

    Configuration comes from the environment (the hook has no access to the caller's settings). Nothing is written
    for a fresh database (``from_version == 0``): there is no data to protect yet and install.sh/tests would
    otherwise collect empty archives. A failure raises :class:`BackupError` so the migration does not start.
    """
    if from_version <= 0:
        log.info("fresh database: no pre-migrate snapshot (migrating 0 → %d)", to_version)
        return
    cfg = Settings.from_env()
    if not cfg.db_path.is_file():
        log.info("database %s does not exist yet: no pre-migrate snapshot", cfg.db_path)
        return
    dest = cfg.backups_dir / PRE_MIGRATE_NAME.format(from_version=from_version, to_version=to_version)
    try:
        size = snapshot(cfg.db_path, dest, tmp_dir=cfg.tmp_dir, tag=f"pre-migrate-{from_version}-to-{to_version}")
    except BackupError as e:
        record_failure(cfg.db_path, str(e), file=dest.name)
        log.error("pre-migrate snapshot failed; the migration is NOT run: %s", e)
        raise
    log.info("pre-migrate snapshot %s (%d bytes)", dest, size, extra={"event": "backup"})
    if sys.stdout.isatty():  # `wd migrate` from a terminal (install.sh); the service sees the JSON log line above
        print(f"pre-migrate snapshot written: {dest} ({size} bytes)")


# ------------------------------------------------------------------------------------------- restore
def service_is_active(name: str = SERVICE_NAME) -> bool:
    """``systemctl is-active --quiet <unit>`` (read-only); False when systemctl is unavailable."""
    systemctl = shutil.which("systemctl")
    if not systemctl:
        return False
    try:
        return subprocess.run([systemctl, "is-active", "--quiet", name], check=False, timeout=10, capture_output=True).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def lease_is_live(db_path: Path, now: datetime) -> dict | None:
    """``kv.worker_lease`` when a ``wd serve`` holds it (P0 ``wd.jobs.lease.is_live``); None for a missing database."""
    if not db_path.is_file():
        return None
    from .jobs import lease

    try:
        conn = db.connect(db_path)
    except sqlite3.Error:
        return None
    try:
        return lease.is_live(conn, to_iso(now))
    except sqlite3.Error:  # no kv table (an empty or foreign file) — nothing can be running on it
        return None
    finally:
        conn.close()


@dataclass(frozen=True)
class Checkpoint:
    """The ``(busy, log, checkpointed)`` row of ``PRAGMA wal_checkpoint(TRUNCATE)`` run before a restore."""

    busy: bool = False
    log: int = 0
    checkpointed: int = 0
    error: str | None = None  # the pragma itself failed (a damaged file, which is a reason to restore, not to refuse)

    @property
    def blocked(self) -> bool:
        """Another connection holds an open transaction. SQLite reports a blocked checkpoint in the result row
        (``busy=1``, ``checkpointed < log``), never as an exception; the frames still in the WAL are then the only copy
        of the newest commits, so a ``.bak`` made of the main file alone would silently lose them."""
        return self.error is None and (self.busy or self.checkpointed < self.log)


def _checkpoint(db_path: Path, *, timeout: float | None = None) -> Checkpoint:
    """Fold the WAL into the main file so the ``.bak`` copy is complete; see :class:`Checkpoint`."""
    try:
        conn = sqlite3.connect(str(db_path), timeout=CHECKPOINT_TIMEOUT_S if timeout is None else timeout)
        try:
            row = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        finally:
            conn.close()
    except sqlite3.Error as e:
        log.warning("wal_checkpoint before restore failed: %s", e)
        return Checkpoint(error=str(e))
    if not row:  # pragma: no cover - the pragma always yields one row
        return Checkpoint()
    busy, nlog, nckpt = (int(v) for v in row)  # log/checkpointed are -1 for a database that is not in WAL mode
    return Checkpoint(busy=bool(busy), log=nlog, checkpointed=nckpt)


def _unlink_db_files(path: Path, *, main: bool = True) -> None:
    """Remove ``path`` (optionally) and its ``-wal``/``-shm`` companions."""
    if main:
        path.unlink(missing_ok=True)
    for suffix in DB_SIDE_SUFFIXES:
        Path(f"{path}{suffix}").unlink(missing_ok=True)


def _unique(path: Path) -> Path:
    """``path`` itself, or ``path-1``, ``path-2``, … when it exists already (two restores within one second) — a kept
    copy is never overwritten."""
    if not path.exists():
        return path
    n = 1
    while path.with_name(f"{path.name}-{n}").exists():
        n += 1
    return path.with_name(f"{path.name}-{n}")


def _keep_copy(src: Path, dest: Path) -> None:
    """Give ``src`` the second name ``dest``: a hard link (same inode — instant, no extra space, same 0600 mode);
    a copy on filesystems without hard links."""
    try:
        os.link(src, dest)
    except FileExistsError:
        raise
    except OSError as e:
        log.info("hard link %s -> %s not possible (%s); copying instead", src, dest, e)
        shutil.copy2(src, dest)


def _swap_in(db_path: Path, candidate: Path, backup_path: Path | None) -> None:
    """Put ``candidate`` (already next to ``db_path``, same filesystem) in place of ``db_path`` without a moment in
    which ``db_path`` is absent.

    1. the current file gets its second name ``backup_path`` (:func:`_keep_copy`);
    2. its ``-wal``/``-shm`` move next to that name: SQLite's WAL recovery is file-name independent, so the kept copy
       is complete even when the checkpoint could not run, and an empty or garbage file is ignored on open;
       (without a database to keep, leftover ``-wal``/``-shm`` are orphans and are deleted — they must never be
       recovered into the restored file);
    3. ONE atomic ``os.replace(candidate, db_path)``.
    Any ``OSError`` undoes 1–2 and propagates; the caller removes the candidate. Before this ordering the live file
    was renamed away first and ``os.replace`` from ``tmp/`` could fail afterwards (``EXDEV`` when ``WD_DB_PATH`` is on
    another filesystem), leaving no database at ``db_path`` at all.
    """
    moved: list[tuple[Path, Path]] = []
    kept = False
    try:
        if backup_path is not None:
            _keep_copy(db_path, backup_path)
            kept = True
            for suffix in DB_SIDE_SUFFIXES:
                side = Path(f"{db_path}{suffix}")
                if side.exists():
                    dest = Path(f"{backup_path}{suffix}")
                    os.replace(side, dest)
                    moved.append((side, dest))
        else:
            _unlink_db_files(db_path, main=False)
        os.replace(candidate, db_path)
    except OSError:
        for side, dest in reversed(moved):
            try:
                os.replace(dest, side)
            except OSError as e:  # pragma: no cover - the directory just allowed the opposite rename
                log.error("could not move %s back to %s: %s", dest, side, e)
        if kept and backup_path is not None:
            backup_path.unlink(missing_ok=True)
        raise


def restore(
    cfg: Settings,
    archive: Path,
    *,
    yes: bool,
    now: datetime | None = None,
    confirm: bool | None = None,
) -> int:
    """``wd restore`` (DEPLOY §5). Returns the exit code: 0 restored, 1 bad archive, 2 refused."""
    from .cli import LEASE_HINT

    when = _now(now)
    archive = archive.expanduser().resolve()
    if not archive.is_file():
        print(f"wd restore: {archive} does not exist", file=sys.stderr)
        return 1
    if not (archive.name.endswith(".db.gz") or archive.name.endswith(".db")):
        print(f"wd restore: expected a .db.gz (or .db) file, got {archive.name}", file=sys.stderr)
        return 1
    if lease_is_live(cfg.db_path, when):
        print(f"wd restore: {LEASE_HINT}", file=sys.stderr)
        return 2
    if service_is_active():
        print(f"wd restore: {SERVICE_NAME} is active — stop it first: sudo systemctl stop word-dance", file=sys.stderr)
        return 2
    if not yes:
        if confirm is None:
            if not sys.stdin.isatty():
                print("wd restore: refusing to replace the database without --yes (stdin is not a terminal)", file=sys.stderr)
                return 2
            answer = input(f"Replace {cfg.db_path} with the contents of {archive.name}? [y/N] ").strip().lower()
            confirm = answer in ("y", "yes")
        if not confirm:
            print("wd restore: cancelled", file=sys.stderr)
            return 2

    stamp = _local(when, cfg.tz).strftime("%Y%m%d-%H%M%S")
    # the candidate is built NEXT TO the target (``word-dance.db.restore-<ts>``), not in ``tmp/``: ``WD_DB_PATH`` may
    # live on another filesystem than ``WD_DATA_DIR`` (DEPLOY §4) and the final swap must be a same-device rename
    cfg.db_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    candidate = cfg.db_path.with_name(f"{cfg.db_path.name}.restore-{stamp}")
    _unlink_db_files(candidate)
    try:
        if archive.name.endswith(".gz"):
            _gunzip_file(archive, candidate)
        else:
            fd = _open_private(candidate)
            with os.fdopen(fd, "wb") as out, archive.open("rb") as f:
                shutil.copyfileobj(f, out, CHUNK)
    except (OSError, EOFError, gzip.BadGzipFile) as e:
        _unlink_db_files(candidate)
        print(f"wd restore: cannot read {archive}: {e}", file=sys.stderr)
        return 1
    ok, detail = integrity_ok(candidate)
    _unlink_db_files(candidate, main=False)  # a read-only open leaves no -wal/-shm today; never let one travel along
    if not ok:
        candidate.unlink(missing_ok=True)
        print(f"wd restore: {archive.name} failed integrity_check ({detail}); the current database was left untouched", file=sys.stderr)
        return 1

    backup_path: Path | None = None
    if cfg.db_path.exists():
        ckpt = _checkpoint(cfg.db_path)
        if ckpt.blocked:
            candidate.unlink(missing_ok=True)
            print(
                f"wd restore: another connection holds an open transaction on {cfg.db_path} (wal_checkpoint busy: "
                f"{ckpt.checkpointed} of {ckpt.log} WAL frames folded in) — close sqlite3 shells / DB browsers / "
                "wd stats|check and retry; nothing was changed",
                file=sys.stderr,
            )
            return 2
        if ckpt.error:
            print(f"wd restore: wal_checkpoint on {cfg.db_path} failed ({ckpt.error}); its -wal/-shm files are kept next to the .bak copy", file=sys.stderr)
        backup_path = _unique(cfg.db_path.with_name(f"{cfg.db_path.name}.bak-{stamp}"))
    try:
        _swap_in(cfg.db_path, candidate, backup_path)
    except OSError as e:
        candidate.unlink(missing_ok=True)
        print(f"wd restore: could not replace {cfg.db_path}: {e}; the current database was left untouched", file=sys.stderr)
        return 1
    cfg.db_path.chmod(0o600)
    print(f"restored {cfg.db_path} from {archive}")
    if backup_path is not None:
        print(f"previous database kept at {backup_path}")
    print("start the service again: sudo systemctl start word-dance")
    return 0


# ----------------------------------------------------------------------------------------------- CLI
def _settings() -> Settings:
    from .cli import settings_or_exit

    return settings_or_exit()


def cmd_backup(args: argparse.Namespace) -> int:
    cfg = _settings()
    keep_daily = cfg.backup_keep_daily if args.keep_daily is None else args.keep_daily
    keep_weekly = cfg.backup_keep_weekly if args.keep_weekly is None else args.keep_weekly
    try:
        result = run_backup(cfg, keep_daily=keep_daily, keep_weekly=keep_weekly, with_images=args.with_images)
    except BackupError as e:
        print(f"wd backup: FAILED — {e}", file=sys.stderr)
        return 1
    print(f"backup written: {result.path} ({result.bytes} bytes)")
    if result.images_tar is not None:
        print(f"images archived: {result.images_tar}")
    print(f"retention: keep {keep_daily} daily + {keep_weekly} weekly; removed {len(result.removed)} old file(s)")
    for p in result.removed:
        print(f"  removed {p.name}")
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    cfg = _settings()
    return restore(cfg, Path(args.file), yes=args.yes)


def register_cli(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("backup", help="snapshot the database (VACUUM INTO + integrity_check + gzip) with retention")
    p.add_argument("--keep-daily", type=int, default=None, metavar="N", help="newest N snapshots to keep (default WD_BACKUP_KEEP_DAILY)")
    p.add_argument("--keep-weekly", type=int, default=None, metavar="M", help="Sunday snapshots to keep beyond the daily ones (default WD_BACKUP_KEEP_WEEKLY)")
    p.add_argument("--with-images", action="store_true", help="also archive the images directory as images-YYYYMMDD.tar")
    p.set_defaults(func=cmd_backup)
    p = sub.add_parser("restore", help="replace the database with a snapshot (service must be stopped)")
    p.add_argument("file", help="backups/word-dance-YYYYMMDD-HHMM.db.gz or pre-migrate-<from>-to-<to>.db.gz")
    p.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    p.set_defaults(func=cmd_restore)
