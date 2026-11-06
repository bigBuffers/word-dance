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


def test_images_retry_is_owned_and_registered_by_the_images_handler(settings):
    """PLAN §5.1 C7: `wd images-retry [--limit N] [--dry-run]` joins fetch-image / images-prune under wd.images.handler."""
    from wd.images import handler, service

    assert cli.COMMAND_OWNERS["wd.images.handler"] == ("fetch-image", "images-prune", "images-retry")
    parser = cli.build_parser()
    args = parser.parse_args(["images-retry", "--dry-run", "--limit", "5"])
    assert args.func is handler.cmd_images_retry and args.dry_run is True and args.limit == 5
    args = parser.parse_args(["images-retry"])
    assert args.dry_run is False and args.limit == service.RETRY_NIGHTLY_LIMIT == 50


def test_learn_order_is_owned_and_registered_by_the_learn_order_module(settings):
    """DESIGN §2.5 (docs/analysis/2026-11-06-learn-order/DESIGN.md): `wd learn-order [--dry-run] [--show STAGE [--top N] [--cur STAGE]]
    [--report PATH] [--db PATH]` under wd.services.learn_order — exactly the options DEPLOY §9 lists (test_docs_contract)."""
    from wd.services import learn_order

    assert cli.COMMAND_OWNERS["wd.services.learn_order"] == ("learn-order",) and "wd.services.learn_order" in cli.CLI_MODULES
    parser = cli.build_parser()
    args = parser.parse_args(["learn-order", "--dry-run", "--show", "xs", "--top", "5", "--cur", "zk", "--report", "r.json", "--db", "x.db"])
    assert args.func is learn_order.cmd_learn_order
    assert (args.dry_run, args.show, args.top, args.cur, args.report, args.db) == (True, "xs", 5, "zk", "r.json", "x.db")
    defaults = parser.parse_args(["learn-order"])
    assert (defaults.dry_run, defaults.show, defaults.top, defaults.cur, defaults.report, defaults.db) == (False, None, learn_order.REPORT_FIRST, None, None, None)
    sub = parser._subparsers._group_actions[0].choices["learn-order"]  # type: ignore[union-attr]
    assert {o for o in sub._option_string_actions if o.startswith("--") and o != "--help"} == {"--dry-run", "--show", "--top", "--cur", "--report", "--db"}
    with pytest.raises(SystemExit) as e:  # an unknown stage code is a usage error
        parser.parse_args(["learn-order", "--show", "cet9"])
    assert e.value.code == 2


def test_learn_order_refuses_a_database_behind_schema_14_or_missing(settings, capsys, tmp_path, monkeypatch):
    """The import-seed precedent: one line, exit 1, no traceback — the operator's next step is `wd migrate` either way."""
    import shutil

    old = tmp_path / "migrations"
    old.mkdir()
    for f in db.list_migration_files():
        if f.version <= 13:
            shutil.copy(f.path, old / f.path.name)
    behind = settings.data_dir / "behind.db"
    c = db.connect(behind)
    try:
        db.run_migrations(c, migrations_dir=old)
        assert db.current_version(c) == 13
    finally:
        c.close()
    for argv in (["learn-order", "--db", str(behind)], ["learn-order", "--db", str(behind), "--dry-run"], ["learn-order", "--db", str(behind), "--show", "xs"]):
        assert cli.main(argv) == 1
        captured = capsys.readouterr()
        assert "wd learn-order: schema version 13 has no words.learn_rank" in captured.err and "run `wd migrate` first" in captured.err
        assert "Traceback" not in captured.err and captured.out == ""
    monkeypatch.setenv("WD_DB_PATH", str(behind))
    assert cli.main(["learn-order"]) == 1 and "run `wd migrate` first" in capsys.readouterr().err  # the env path is the default
    assert cli.main(["learn-order", "--db", str(tmp_path / "nowhere.db")]) == 1
    assert "does not exist (run `wd migrate`)" in capsys.readouterr().err
    c = db.connect(behind)
    try:
        assert db.kv_get(c, "learn_order.version") is None  # nothing written
    finally:
        c.close()


def test_learn_order_fills_previews_and_reports(settings, seeded, capsys, tmp_path):
    """`wd learn-order` on the seeded database: the import hook ranked the rows (0 updated); after a NULL fill 62 updated; exit 1
    while a stage word stays unranked; --dry-run writes nothing; --show prints the table; --report writes the §2.8 document."""
    import json
    import re

    from wd.services import learn_order

    assert cli.main(["learn-order"]) == 0
    out = capsys.readouterr().out
    assert re.fullmatch(r"learn order lo-1: 62 rows, 0 updated in \d+\.\d\d s; 0 stage words unranked\n", out), out
    seeded.execute("UPDATE words SET learn_rank = NULL")
    assert cli.main(["learn-order", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("dry run: learn order lo-1 over 62 rows — 62 would change, nothing written") and "biggest climbs:" in out and "biggest drops:" in out
    assert seeded.execute("SELECT COUNT(*) FROM words WHERE learn_rank IS NOT NULL").fetchone()[0] == 0
    assert cli.main(["learn-order"]) == 0
    assert re.fullmatch(r"learn order lo-1: 62 rows, 62 updated in \d+\.\d\d s; 0 stage words unranked\n", capsys.readouterr().out)
    assert seeded.execute("SELECT COUNT(*) FROM words WHERE learn_rank IS NULL").fetchone()[0] == 0
    assert cli.main(["learn-order", "--show", "xs", "--top", "5"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].split() == list(learn_order.SHOW_COLUMNS) and len(lines) == 6 and lines[1].split()[:2] == ["1", "take"]
    assert cli.main(["learn-order", "--show", "zk", "--top", "3", "--cur", "zk"]) == 0
    assert capsys.readouterr().out.splitlines()[1].split()[:2] == ["1", "go"]
    report = tmp_path / "learn_order.json"
    assert cli.main(["learn-order", "--report", str(report)]) == 0
    out = capsys.readouterr().out
    assert "0 updated" in out and f"report written to {report}" in out
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["policy"] == "lo-1" and data["seed"] == db.kv_get(seeded, "seed_version") and data["generated_by"] == "wd learn-order --report"
    assert set(data["stages"]) == {"xs", "zk", "gk", "cet4", "cet6", "none"} and data["stages"]["xs"]["first"][:2] == ["take", "good"]
    assert set(data["acceptance"]) == {"closed_in_first_30", "xs_adverbs_first_30", "xs_months_positions", "zk_phrases_first_200", "longest_frq_null_run"}
    assert cli.main(["learn-order", "--report", str(tmp_path / "no-such-dir" / "r.json")]) == 1
    assert "cannot write report" in capsys.readouterr().err
    # a stage word the policy cannot rank (a frequency-less closed word in a stage without closed hosts, R4) → exit 1
    seeded.execute("INSERT INTO words(lemma, display, kind, pos, source, stage_zk, stage_min) VALUES ('ghostly', 'ghostly', 'word', 'i:100', 'seed', 1, 2)")
    assert cli.main(["learn-order"]) == 1
    assert re.fullmatch(r"learn order lo-1: 63 rows, 0 updated in \d+\.\d\d s; 1 stage words unranked\n", capsys.readouterr().out)


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


def test_learn_order_report_is_refused_without_a_recompute(settings, seeded, capsys, tmp_path):
    """`--report` describes the ranks the recompute just stored (DESIGN §2.5 / §2.8): with `--dry-run` or `--show` nothing was
    recomputed, so the combination is a usage error (exit 2) and no document is written."""
    report = tmp_path / "learn_order.json"
    for argv in (["learn-order", "--dry-run", "--report", str(report)], ["learn-order", "--show", "xs", "--report", str(report)]):
        assert cli.main(argv) == 2
        captured = capsys.readouterr()
        assert captured.out == "" and "--report" in captured.err and "--dry-run or --show" in captured.err
    assert not report.exists()
    assert cli.main(["learn-order", "--report", str(report)]) == 0 and report.is_file()
