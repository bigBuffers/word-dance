"""cli.py: version, migrate (twice + dry-run), every DEPLOY §9 command registered by its owning module, register_cli dispatch."""

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
        shipped = [(f.version, f.name) for f in db.list_migration_files()]
        assert [tuple(r) for r in c.execute("SELECT version, name FROM schema_migrations ORDER BY version")] == shipped  # one row per file, runner-written
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


def test_every_owned_command_is_registered_by_its_module(settings):
    """TASKS post-step 1: every CLI_MODULES module exists and registers the DEPLOY §9 commands it owns (no stubs)."""
    parser = cli.build_parser()
    choices = parser._subparsers._group_actions[0].choices  # type: ignore[union-attr]
    commands = set(choices)
    assert {"serve", "migrate", "version"} <= commands
    owned = {c for cmds in cli.COMMAND_OWNERS.values() for c in cmds}
    assert owned <= commands, owned - commands
    assert set(cli.COMMAND_OWNERS) == set(cli.CLI_MODULES)
    for command in owned:
        sub = choices[command]
        assert callable(sub.get_default("func")) and sub.get_default("_stub") is None, command
        assert "not implemented" not in (sub.description or "") + (sub.format_help() or ""), command
    # an unknown argument is a usage error (exit 2), no stub swallows it
    with pytest.raises(SystemExit) as e:
        cli.main(["version", "--bogus"])
    assert e.value.code == 2


def test_module_without_its_commands_is_a_packaging_error(monkeypatch):
    import sys
    import types

    silent = types.ModuleType("wd.diag")  # exists, has no register_cli
    monkeypatch.setitem(sys.modules, "wd.diag", silent)
    with pytest.raises(RuntimeError, match="register_cli"):
        cli.build_parser()

    partial = types.ModuleType("wd.diag")

    def register_cli(sub):  # registers only one of its three commands
        p = sub.add_parser("stats")
        p.set_defaults(func=lambda args: 0)

    partial.register_cli = register_cli  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "wd.diag", partial)
    with pytest.raises(RuntimeError, match="check, logs"):
        cli.build_parser()


def test_register_cli_dispatch(monkeypatch, capsys):
    import sys
    import types

    fake = types.ModuleType("wd.diag")

    def register_cli(sub):
        for command in cli.COMMAND_OWNERS["wd.diag"]:
            p = sub.add_parser(command)
            p.set_defaults(func=lambda args, c=command: print(f"{c} from fake diag") or 0)

    fake.register_cli = register_cli  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "wd.diag", fake)
    assert cli.main(["stats"]) == 0
    assert "stats from fake diag" in capsys.readouterr().out


def test_config_error_exits_2(monkeypatch):
    monkeypatch.setenv("WD_TZ", "Mars/Olympus")
    with pytest.raises(SystemExit) as e:
        cli.main(["migrate"])
    assert e.value.code == 2
