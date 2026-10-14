"""cli.py: version, migrate (twice + dry-run), stubs for not-yet-landed modules, register_cli dispatch."""

from __future__ import annotations

import os
import stat

import pytest

from wd import __version__, cli, db


def test_version(capsys):
    assert cli.main(["version"]) == 0
    assert capsys.readouterr().out.strip() == f"wd {__version__}"


def test_migrate_twice(settings, capsys):
    assert cli.main(["migrate"]) == 0
    out = capsys.readouterr().out
    assert "applied 0001_init.sql" in out
    assert cli.main(["migrate"]) == 0
    out = capsys.readouterr().out
    assert "0 pending" in out
    c = db.connect(settings.db_path)
    try:
        assert [tuple(r) for r in c.execute("SELECT version, name FROM schema_migrations")] == [(1, "init")]
        assert len(db.table_names(c)) == 25 and db.view_names(c) == ["v_bank"]
    finally:
        c.close()
    # DEPLOY §1: the DB is 0600 even when `wd migrate` created it under a permissive shell umask
    assert stat.S_IMODE(os.stat(settings.db_path).st_mode) == 0o600


def test_migrate_dry_run(settings, capsys):
    assert cli.main(["migrate", "--dry-run"]) == 0
    assert "pending 0001_init.sql" in capsys.readouterr().out
    c = db.connect(settings.db_path)
    try:
        assert db.table_names(c) == []
    finally:
        c.close()
    cli.main(["migrate"])
    capsys.readouterr()
    assert cli.main(["migrate", "--dry-run"]) == 0
    assert "0 pending" in capsys.readouterr().out


def test_stubs_for_missing_modules_exit_2(settings, capsys):
    parser = cli.build_parser()
    commands = set(parser._subparsers._group_actions[0].choices)  # type: ignore[union-attr]
    assert {"serve", "migrate", "version"} <= commands
    for module, owned in cli.COMMAND_OWNERS.items():
        for command in owned:
            assert command in commands, command
    try:
        import wd.seed  # type: ignore[import-not-found]  # noqa: F401
    except ModuleNotFoundError:
        rc = cli.main(["import-seed", "--file", "x"])
        assert rc == 2
        assert "not implemented" in capsys.readouterr().err


def test_register_cli_dispatch(monkeypatch, capsys):
    import types

    fake = types.ModuleType("wd.diag")

    def register_cli(sub):
        p = sub.add_parser("stats")
        p.set_defaults(func=lambda args: print("stats from fake diag") or 0)

    fake.register_cli = register_cli  # type: ignore[attr-defined]
    monkeypatch.setitem(__import__("sys").modules, "wd.diag", fake)
    assert cli.main(["stats"]) == 0
    assert "stats from fake diag" in capsys.readouterr().out


def test_config_error_exits_2(monkeypatch):
    monkeypatch.setenv("WD_TZ", "Mars/Olympus")
    with pytest.raises(SystemExit) as e:
        cli.main(["migrate"])
    assert e.value.code == 2
