"""wd/backup.py (WP9): snapshot pipeline, retention, pre-migrate hook, `wd backup` / `wd restore` CLI (DEPLOY §5)."""

from __future__ import annotations

import gzip
import io
import json
import os
import shutil
import sqlite3
import stat
import tarfile
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
    rows = conn.execute("SELECT kind, detail_json FROM system_events").fetchall()
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
    assert list(settings.tmp_dir.glob("restore-*.db")) == []


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
    assert list(settings.tmp_dir.glob("restore-*.db")) == []


def test_restore_rejects_missing_or_odd_files(settings, conn, no_service, tmp_path, capsys):
    assert cli.main(["restore", str(tmp_path / "nope.db.gz"), "--yes"]) == 1
    odd = tmp_path / "x.txt"
    odd.write_text("x")
    assert cli.main(["restore", str(odd), "--yes"]) == 1


def test_cli_registers_backup_and_restore_without_stubs():
    parser = cli.build_parser()
    choices = parser._subparsers._group_actions[0].choices  # type: ignore[union-attr]
    for command in ("backup", "restore"):
        assert command in choices
        assert not getattr(choices[command].parse_known_args([] if command == "backup" else ["f"])[0], "_stub", False)
