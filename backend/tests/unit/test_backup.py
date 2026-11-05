"""wd/backup.py (WP9): snapshot pipeline, retention, pre-migrate hook, `wd backup` / `wd restore` CLI (DEPLOY §5)."""

from __future__ import annotations

import errno
import gzip
import io
import json
import os
import shutil
import sqlite3
import stat
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from wd import backup, cli, db
from wd.jobs import lease

UTC = timezone.utc
NOW = datetime(2026, 10, 14, 19, 30, 0, tzinfo=UTC)  # 2026-10-15 03:30 Asia/Shanghai (WD_TZ of the test env)


def _gunzip(archive: Path, dest: Path) -> Path:
    with gzip.open(archive, "rb") as gz, dest.open("wb") as out:
        shutil.copyfileobj(gz, out)
    return dest


def _mode(p: Path) -> int:
    return stat.S_IMODE(os.stat(p).st_mode)


def _touch(d: Path, name: str) -> Path:
    p = d / name
    p.write_bytes(b"x")
    return p


# ------------------------------------------------------------------------------------------ naming
def test_backup_name_uses_operational_timezone():
    assert backup.backup_name(NOW, "Asia/Shanghai") == "word-dance-20261015-0330.db.gz"
    assert backup.backup_name(NOW, "UTC") == "word-dance-20261014-1930.db.gz"
    assert backup.images_tar_name(NOW, "Asia/Shanghai") == "images-20261015.tar"
    assert backup.BACKUP_RE.match("word-dance-20261015-0330.db.gz")
    assert not backup.BACKUP_RE.match("pre-migrate-1-to-2.db.gz")


# ---------------------------------------------------------------------------------------- snapshot
def test_run_backup_writes_archive_kv_and_mode(settings, conn, tmp_path):
    db.kv_set(conn, "marker", "before")
    result = backup.run_backup(settings, keep_daily=14, keep_weekly=8, now=NOW)
    assert result.path == settings.backups_dir / "word-dance-20261015-0330.db.gz"
    assert result.path.is_file() and _mode(result.path) == 0o600
    assert result.bytes == result.path.stat().st_size > 0
    assert result.at == "2026-10-14T19:30:00Z"
    assert result.removed == [] and result.images_tar is None
    # kv.backup.last = {file, at, bytes} (AdminHealth.last_backup)
    last = json.loads(db.kv_get(conn, "backup.last"))
    assert last == {"file": "word-dance-20261015-0330.db.gz", "at": "2026-10-14T19:30:00Z", "bytes": result.bytes}
    # the archive is a complete, consistent copy
    copy = _gunzip(result.path, tmp_path / "copy.db")
    c = sqlite3.connect(copy)
    try:
        assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert len(db.table_names(c)) == 25
        assert c.execute("SELECT value FROM kv WHERE key='marker'").fetchone()[0] == "before"
    finally:
        c.close()
    # no intermediate copy left behind
    assert list(settings.tmp_dir.glob("word-dance-*.db")) == []
    assert not list(settings.backups_dir.glob("*.part"))


def test_run_backup_fails_without_database(settings):
    with pytest.raises(backup.BackupError):
        backup.run_backup(settings, keep_daily=1, keep_weekly=1, now=NOW)


def test_integrity_failure_records_event_and_leaves_nothing(settings, conn, monkeypatch):
    monkeypatch.setattr(backup, "integrity_ok", lambda path: (False, "boom"))
    with pytest.raises(backup.BackupError, match="boom"):
        backup.run_backup(settings, keep_daily=14, keep_weekly=8, now=NOW)
    assert list(settings.backups_dir.iterdir()) == []
    assert list(settings.tmp_dir.glob("word-dance-*.db")) == []
    rows = conn.execute("SELECT kind, detail_json FROM system_events WHERE kind != 'migration'").fetchall()  # 0011 leaves a migration trace (PLAN §2.2)
    assert len(rows) == 1 and rows[0][0] == "backup_failed"
    detail = json.loads(rows[0][1])
    assert "boom" in detail["error"] and detail["file"] == "word-dance-20261015-0330.db.gz"
    assert db.kv_get(conn, "backup.last") is None


def test_backup_with_images_tar(settings, conn):
    img = settings.images_dir / "ab" / "ab12.jpg"
    img.parent.mkdir(parents=True)
    img.write_bytes(b"\xff\xd8\xff\xe0jpeg")
    result = backup.run_backup(settings, keep_daily=14, keep_weekly=8, with_images=True, now=NOW)
    assert result.images_tar == settings.backups_dir / "images-20261015.tar"
    assert _mode(result.images_tar) == 0o600
    with tarfile.open(result.images_tar) as tar:
        assert "images/ab/ab12.jpg" in tar.getnames()


# --------------------------------------------------------------------------------------- retention
def _daily_files(d: Path, start: datetime, days: int) -> list[Path]:
    from datetime import timedelta

    out = []
    for i in range(days):
        day = start + timedelta(days=i)
        out.append(_touch(d, day.strftime("word-dance-%Y%m%d-0330.db.gz")))
    return out


def test_retention_keeps_newest_daily_and_sunday_weeklies(tmp_path):
    # 2026-09-01 … 2026-10-14 (44 daily snapshots); Sundays in that range: 09-06, 09-13, 09-20, 09-27, 10-04, 10-11
    _daily_files(tmp_path, datetime(2026, 9, 1), 44)
    untouched = [_touch(tmp_path, "pre-migrate-1-to-2.db.gz"), _touch(tmp_path, "notes.txt")]
    removed = backup.apply_retention(tmp_path, keep_daily=14, keep_weekly=8)
    remaining = sorted(p.name for p in tmp_path.iterdir())
    newest14 = [f"word-dance-2026100{d}-0330.db.gz" for d in range(1, 10)] + [f"word-dance-202610{d}-0330.db.gz" for d in range(10, 15)]
    weeklies = ["word-dance-20260906-0330.db.gz", "word-dance-20260913-0330.db.gz", "word-dance-20260920-0330.db.gz", "word-dance-20260927-0330.db.gz"]
    assert remaining == sorted(newest14 + weeklies + [p.name for p in untouched])
    assert len(removed) == 44 - 14 - 4
    assert all(p.name.startswith("word-dance-") for p in removed)
    # a second pass removes nothing (idempotent)
    assert backup.apply_retention(tmp_path, keep_daily=14, keep_weekly=8) == []


def test_retention_weekly_cap_and_one_per_week(tmp_path):
    _daily_files(tmp_path, datetime(2026, 9, 1), 44)
    _touch(tmp_path, "word-dance-20260927-1200.db.gz")  # a second Sunday copy in the same ISO week → only the newest stays
    backup.apply_retention(tmp_path, keep_daily=14, keep_weekly=2)
    older = sorted(p.name for p in tmp_path.iterdir() if p.name < "word-dance-20261001")
    assert older == ["word-dance-20260920-0330.db.gz", "word-dance-20260927-1200.db.gz"]


def test_retention_zero_keeps_nothing_but_pre_migrate(tmp_path):
    _daily_files(tmp_path, datetime(2026, 9, 1), 10)
    _touch(tmp_path, "pre-migrate-1-to-2.db.gz")
    backup.apply_retention(tmp_path, keep_daily=0, keep_weekly=0)
    assert [p.name for p in tmp_path.iterdir()] == ["pre-migrate-1-to-2.db.gz"]


def test_retention_applies_to_image_tars(tmp_path):
    for d in range(1, 6):
        _touch(tmp_path, f"images-2026100{d}.tar")
    removed = backup.apply_retention(tmp_path, keep_daily=2, keep_weekly=0)
    assert sorted(p.name for p in removed) == ["images-20261001.tar", "images-20261002.tar", "images-20261003.tar"]


# ---------------------------------------------------------------------------------- pre-migrate hook
def test_backup_pre_hook_is_the_snapshot_function():
    assert db.backup_pre_hook() is backup.snapshot_before_migrate


def test_snapshot_before_migrate_skips_fresh_database(settings, conn):
    backup.snapshot_before_migrate(0, 1)
    assert list(settings.backups_dir.iterdir()) == []


def test_snapshot_before_migrate_writes_named_archive(settings, conn, tmp_path):
    db.kv_set(conn, "marker", "v1")
    backup.snapshot_before_migrate(1, 2)
    archive = settings.backups_dir / "pre-migrate-1-to-2.db.gz"
    assert archive.is_file() and _mode(archive) == 0o600
    copy = _gunzip(archive, tmp_path / "pre.db")
    c = sqlite3.connect(copy)
    try:
        assert c.execute("SELECT value FROM kv WHERE key='marker'").fetchone()[0] == "v1"
    finally:
        c.close()
    # the same upgrade attempted again simply refreshes the archive (no error, no duplicate names)
    backup.snapshot_before_migrate(1, 2)
    assert [p.name for p in settings.backups_dir.iterdir()] == ["pre-migrate-1-to-2.db.gz"]


def test_pre_hook_runs_before_the_first_pending_file(settings, conn, tmp_path):
    mig = tmp_path / "migrations"
    mig.mkdir()
    shutil.copy(db.MIGRATIONS_DIR / "0001_init.sql", mig / "0001_init.sql")
    (mig / "0099_extra.sql").write_text("CREATE TABLE extra(x INTEGER);\n", encoding="utf-8")
    before = db.current_version(conn)  # `conn` is at the latest shipped version
    result = db.run_migrations(conn, pre_hook=db.backup_pre_hook(), migrations_dir=mig)
    assert result.applied == [(99, "extra")]
    archive = settings.backups_dir / f"pre-migrate-{before}-to-99.db.gz"
    assert archive.is_file()
    copy = _gunzip(archive, tmp_path / "pre.db")
    c = sqlite3.connect(copy)
    try:
        assert "extra" not in db.table_names(c)  # taken BEFORE the migration ran
    finally:
        c.close()
    assert "extra" in db.table_names(conn)


def test_pre_hook_failure_blocks_the_migration(settings, conn, tmp_path, monkeypatch):
    mig = tmp_path / "migrations"
    mig.mkdir()
    shutil.copy(db.MIGRATIONS_DIR / "0001_init.sql", mig / "0001_init.sql")
    (mig / "0099_extra.sql").write_text("CREATE TABLE extra(x INTEGER);\n", encoding="utf-8")
    before = db.current_version(conn)
    monkeypatch.setattr(backup, "integrity_ok", lambda path: (False, "corrupt"))
    with pytest.raises(backup.BackupError):
        db.run_migrations(conn, pre_hook=db.backup_pre_hook(), migrations_dir=mig)
    assert "extra" not in db.table_names(conn)
    assert db.current_version(conn) == before
    assert conn.execute("SELECT COUNT(*) FROM system_events WHERE kind='backup_failed'").fetchone()[0] == 1


# --------------------------------------------------------------------------------------------- CLI
@pytest.fixture
def no_service(monkeypatch):
    monkeypatch.setattr(backup, "service_is_active", lambda name=backup.SERVICE_NAME: False)


def test_cli_backup_then_restore_round_trip(settings, no_service, capsys):
    assert cli.main(["migrate"]) == 0
    c = db.connect(settings.db_path)
    db.kv_set(c, "marker", "v1")
    c.close()
    assert cli.main(["backup", "--keep-daily", "14", "--keep-weekly", "8"]) == 0
    out = capsys.readouterr().out
    assert "backup written:" in out and "retention: keep 14 daily + 8 weekly" in out
    archives = list(settings.backups_dir.glob("word-dance-*.db.gz"))
    assert len(archives) == 1
    archive = archives[0]

    # the live database moves on; stale -wal/-shm files are lying around
    c = db.connect(settings.db_path)
    db.kv_set(c, "marker", "v2")
    c.close()
    Path(f"{settings.db_path}-wal").write_bytes(b"stale")
    Path(f"{settings.db_path}-shm").write_bytes(b"stale")

    assert cli.main(["restore", str(archive), "--yes"]) == 0
    out = capsys.readouterr().out
    assert "sudo systemctl start word-dance" in out and "previous database kept at" in out
    c = db.connect(settings.db_path)
    try:
        assert db.kv_get(c, "marker") == "v1"
        assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        c.close()
    assert _mode(settings.db_path) == 0o600
    baks = list(settings.db_path.parent.glob("word-dance.db.bak-*"))
    assert len(baks) == 1
    assert not Path(f"{settings.db_path}-wal").exists() or Path(f"{settings.db_path}-wal").read_bytes() != b"stale"
    assert not Path(f"{settings.db_path}-shm").exists() or Path(f"{settings.db_path}-shm").read_bytes() != b"stale"
    _no_candidate_left(settings)


def test_cli_backup_defaults_come_from_settings(settings, conn, monkeypatch, capsys):
    monkeypatch.setenv("WD_BACKUP_KEEP_DAILY", "3")
    monkeypatch.setenv("WD_BACKUP_KEEP_WEEKLY", "1")
    assert cli.main(["backup"]) == 0
    assert "retention: keep 3 daily + 1 weekly" in capsys.readouterr().out


def test_cli_backup_reports_failure_with_exit_1(settings, conn, monkeypatch, capsys):
    monkeypatch.setattr(backup, "integrity_ok", lambda path: (False, "boom"))
    assert cli.main(["backup"]) == 1
    assert "FAILED" in capsys.readouterr().err


def test_restore_refuses_while_lease_is_live(settings, conn, no_service, capsys):
    result = backup.run_backup(settings, keep_daily=14, keep_weekly=8, now=NOW)
    assert lease.acquire(conn, "wd-serve:1234", datetime.now(UTC))
    assert cli.main(["restore", str(result.path), "--yes"]) == 2
    assert cli.LEASE_HINT in capsys.readouterr().err
    assert db.kv_get(conn, "backup.last") is not None  # nothing was replaced


def test_restore_refuses_when_service_active(settings, conn, monkeypatch, capsys):
    result = backup.run_backup(settings, keep_daily=14, keep_weekly=8, now=NOW)
    monkeypatch.setattr(backup, "service_is_active", lambda name=backup.SERVICE_NAME: True)
    assert cli.main(["restore", str(result.path), "--yes"]) == 2
    assert "sudo systemctl stop word-dance" in capsys.readouterr().err


def test_restore_without_yes_refuses_when_not_interactive(settings, conn, no_service, monkeypatch, capsys):
    result = backup.run_backup(settings, keep_daily=14, keep_weekly=8, now=NOW)
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    assert cli.main(["restore", str(result.path)]) == 2
    assert "--yes" in capsys.readouterr().err


def test_restore_confirmation_answer(settings, conn, no_service):
    result = backup.run_backup(settings, keep_daily=14, keep_weekly=8, now=NOW)
    assert backup.restore(settings, result.path, yes=False, confirm=False) == 2
    assert backup.restore(settings, result.path, yes=False, confirm=True) == 0


def test_restore_rejects_corrupt_archive(settings, conn, no_service, tmp_path, capsys):
    db.kv_set(conn, "marker", "live")
    bad = tmp_path / "word-dance-20260101-0330.db.gz"
    with gzip.open(bad, "wb") as gz:
        gz.write(b"this is not a database")
    assert cli.main(["restore", str(bad), "--yes"]) == 1
    assert "integrity_check" in capsys.readouterr().err
    assert db.kv_get(conn, "marker") == "live"
    assert list(settings.db_path.parent.glob("*.bak-*")) == []
    _no_candidate_left(settings)


def test_restore_rejects_missing_or_odd_files(settings, conn, no_service, tmp_path, capsys):
    assert cli.main(["restore", str(tmp_path / "nope.db.gz"), "--yes"]) == 1
    odd = tmp_path / "x.txt"
    odd.write_text("x")
    assert cli.main(["restore", str(odd), "--yes"]) == 1


# --------------------------------------------------------------- restore: the swap and the kept copy (review fixes)
def _no_candidate_left(cfg) -> None:
    """The verified copy is built next to the target (``word-dance.db.restore-<ts>``); nothing of it may remain."""
    assert list(cfg.db_path.parent.glob("*.restore-*")) == []
    assert list(cfg.tmp_dir.glob("restore-*")) == []


def _settings_with_db(monkeypatch, db_path: Path):
    """Settings whose ``WD_DB_PATH`` is ``db_path`` — DEPLOY §4 allows a database outside ``WD_DATA_DIR``."""
    from wd.config import Settings, ensure_dirs

    monkeypatch.setenv("WD_DB_PATH", str(db_path))
    cfg = Settings.from_env()
    ensure_dirs(cfg)
    return cfg


def _archive_of(cfg, marker: str) -> Path:
    """A migrated database whose ``kv.marker`` is ``marker``, backed up; returns the archive."""
    c = db.connect(cfg.db_path)
    db.run_migrations(c)
    db.kv_set(c, "marker", marker)
    c.close()
    return backup.run_backup(cfg, keep_daily=14, keep_weekly=8, now=NOW).path


def _set_marker(db_path: Path, value: str) -> None:
    c = db.connect(db_path)
    db.kv_set(c, "marker", value)
    c.close()


def _marker_and_integrity(db_path: Path) -> tuple[str | None, str]:
    c = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        row = c.execute("SELECT value FROM kv WHERE key='marker'").fetchone()
        return (row[0] if row else None), c.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        c.close()


def _kept_copies(cfg) -> list[Path]:
    return [p for p in cfg.db_path.parent.glob("word-dance.db.bak-*") if not p.name.endswith(("-wal", "-shm"))]


def _restore_round_trip(cfg, capsys) -> Path:
    archive = _archive_of(cfg, "v1")
    _set_marker(cfg.db_path, "v2")
    assert cli.main(["restore", str(archive), "--yes"]) == 0
    assert "previous database kept at" in capsys.readouterr().out
    assert _marker_and_integrity(cfg.db_path) == ("v1", "ok")
    assert _mode(cfg.db_path) == 0o600
    baks = _kept_copies(cfg)
    assert len(baks) == 1
    assert _marker_and_integrity(baks[0]) == ("v2", "ok")  # the kept copy is complete
    _no_candidate_left(cfg)
    return baks[0]


def test_restore_round_trip_with_db_outside_data_dir(test_env, no_service, monkeypatch, tmp_path, capsys):
    cfg = _settings_with_db(monkeypatch, tmp_path / "elsewhere" / "db" / "word-dance.db")
    assert cfg.db_path.parent != cfg.data_dir
    bak = _restore_round_trip(cfg, capsys)
    assert bak.parent == cfg.db_path.parent
    assert list(cfg.data_dir.glob("*.bak-*")) == []


def _other_device(near: Path) -> Path | None:
    """A writable directory on another filesystem than ``near`` (``/dev/shm`` is tmpfs on the target box)."""
    shm = Path("/dev/shm")
    if shm.is_dir() and os.access(shm, os.W_OK) and os.stat(shm).st_dev != os.stat(near).st_dev:
        return shm
    return None


def test_restore_round_trip_across_filesystems(test_env, no_service, monkeypatch, tmp_path, capsys):
    """``WD_DB_PATH`` on another filesystem than ``WD_DATA_DIR``: the swap must be a same-device rename. The previous
    order (``os.replace`` the live DB to ``.bak`` first, then ``os.replace`` the candidate out of ``tmp/``) failed
    with ``EXDEV`` after the first step and left no database at ``db_path`` at all."""
    other = _other_device(tmp_path)
    if other is None:
        pytest.skip("needs a writable directory on another filesystem than the pytest tmp dir (/dev/shm)")
    base = Path(tempfile.mkdtemp(prefix="wd-test-restore-", dir=other))
    try:
        cfg = _settings_with_db(monkeypatch, base / "word-dance.db")
        assert os.stat(cfg.db_path.parent).st_dev != os.stat(cfg.tmp_dir).st_dev
        _restore_round_trip(cfg, capsys)
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_restore_failed_swap_leaves_the_database_untouched(settings, no_service, monkeypatch, capsys):
    """The final rename fails (an ``EXDEV``-style error): the live DB, its ``-wal``/``-shm`` and the directory are
    exactly as before and the exit code is 1 — there is never a moment without a database at ``db_path``."""
    archive = _archive_of(settings, "v1")
    idle = db.connect(settings.db_path)  # keeps the WAL alive: the newest commit stays in word-dance.db-wal
    idle.execute("SELECT count(*) FROM kv").fetchone()
    _set_marker(settings.db_path, "v2")
    wal, shm = Path(f"{settings.db_path}-wal"), Path(f"{settings.db_path}-shm")
    before_db, before_wal = settings.db_path.read_bytes(), wal.read_bytes()
    assert len(before_wal) > 32 and shm.exists()
    # the checkpoint "fails" (the damaged-file path), so the -wal/-shm travel with the .bak and must be moved back
    monkeypatch.setattr(backup, "_checkpoint", lambda p, **kw: backup.Checkpoint(error="simulated"))
    real_replace = os.replace

    def failing_replace(src, dst, *args, **kwargs):
        if Path(dst) == settings.db_path:
            raise OSError(errno.EXDEV, "Invalid cross-device link", str(src), None, str(dst))
        return real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "replace", failing_replace)
    assert cli.main(["restore", str(archive), "--yes"]) == 1
    err = capsys.readouterr().err
    assert "could not replace" in err and "left untouched" in err
    assert settings.db_path.read_bytes() == before_db and wal.read_bytes() == before_wal and shm.exists()
    names = sorted(p.name for p in settings.db_path.parent.iterdir() if p.name.startswith("word-dance.db"))
    assert names == ["word-dance.db", "word-dance.db-shm", "word-dance.db-wal"]  # no .bak, no candidate
    _no_candidate_left(settings)
    idle.close()  # the last connection folds the WAL back in: nothing was lost
    assert _marker_and_integrity(settings.db_path) == ("v2", "ok")


def test_restore_refuses_while_another_connection_holds_a_transaction(settings, no_service, monkeypatch, capsys):
    """A reader on an older snapshot (a forgotten ``BEGIN;`` in a sqlite3 shell) blocks ``wal_checkpoint(TRUNCATE)``;
    SQLite reports that in the result row, not as an error. Restore must refuse instead of deleting the WAL frames
    that are the only copy of the newest commits (the ``.bak`` would silently lose them)."""
    archive = _archive_of(settings, "v1")
    reader = db.connect(settings.db_path)
    reader.execute("BEGIN")
    reader.execute("SELECT count(*) FROM kv").fetchone()  # the read snapshot predates the next commit
    _set_marker(settings.db_path, "v2")  # lands in the WAL; the writer's close cannot checkpoint past the reader
    wal = Path(f"{settings.db_path}-wal")
    wal_size = wal.stat().st_size
    assert wal_size > 32
    monkeypatch.setattr(backup, "CHECKPOINT_TIMEOUT_S", 0.2)
    try:
        assert cli.main(["restore", str(archive), "--yes"]) == 2
        err = capsys.readouterr().err
        assert "another connection holds an open transaction" in err and "wal_checkpoint busy" in err
        assert wal.stat().st_size == wal_size  # the frames are untouched
        assert list(settings.db_path.parent.glob("*.bak-*")) == []
        _no_candidate_left(settings)
        assert _marker_and_integrity(settings.db_path) == ("v2", "ok")
    finally:
        reader.execute("ROLLBACK")
        reader.close()
    # the reader is gone: the same restore succeeds and the kept copy holds the newest commit
    assert cli.main(["restore", str(archive), "--yes"]) == 0
    assert _marker_and_integrity(settings.db_path) == ("v1", "ok")
    baks = _kept_copies(settings)
    assert len(baks) == 1 and _marker_and_integrity(baks[0]) == ("v2", "ok")


def test_restore_keeps_wal_next_to_bak_when_checkpoint_fails(settings, no_service, monkeypatch, capsys):
    """Damaged-file path: the checkpoint cannot run, yet the frames of the newest commits travel with the ``.bak``
    (``.bak-<ts>-wal``) instead of being deleted, and SQLite recovers them when the ``.bak`` is opened."""
    archive = _archive_of(settings, "v1")
    idle = db.connect(settings.db_path)  # a second connection keeps the WAL alive (no close-time checkpoint)
    idle.execute("SELECT count(*) FROM kv").fetchone()
    _set_marker(settings.db_path, "v2")
    wal = Path(f"{settings.db_path}-wal")
    assert wal.stat().st_size > 32
    monkeypatch.setattr(backup, "_checkpoint", lambda p, **kw: backup.Checkpoint(error="database disk image is malformed"))
    assert cli.main(["restore", str(archive), "--yes"]) == 0
    captured = capsys.readouterr()
    assert "kept next to the .bak copy" in captured.err and "previous database kept at" in captured.out
    idle.close()
    baks = _kept_copies(settings)
    assert len(baks) == 1 and Path(f"{baks[0]}-wal").exists()
    assert not wal.exists()  # nothing of the old database is left next to the restored file
    assert _marker_and_integrity(baks[0]) == ("v2", "ok")
    assert _marker_and_integrity(settings.db_path) == ("v1", "ok")
    _no_candidate_left(settings)


def test_checkpoint_result_blocked_rule():
    assert not backup.Checkpoint().blocked
    assert not backup.Checkpoint(log=-1, checkpointed=-1).blocked  # not a WAL database
    assert backup.Checkpoint(busy=True, log=1, checkpointed=0).blocked
    assert backup.Checkpoint(busy=False, log=5, checkpointed=3).blocked
    assert backup.Checkpoint(busy=True, log=5, checkpointed=5).blocked  # a reader on the latest snapshot: refuse too
    assert not backup.Checkpoint(error="malformed").blocked  # a damaged file is a reason to restore, not to refuse


def test_cli_registers_backup_and_restore_without_stubs():
    parser = cli.build_parser()
    choices = parser._subparsers._group_actions[0].choices  # type: ignore[union-attr]
    for command in ("backup", "restore"):
        assert command in choices
        assert not getattr(choices[command].parse_known_args([] if command == "backup" else ["f"])[0], "_stub", False)
