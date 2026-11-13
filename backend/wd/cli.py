"""``wd`` command-line entry point (Phase 0, frozen contract — TASKS.md P0 step 4, DEPLOY §9).

Implements ``serve``, ``migrate [--dry-run]`` and ``version`` itself, then calls ``register_cli(sub)``
on every module of :data:`CLI_MODULES`. Each module must exist and must register every command it owns
(:data:`COMMAND_OWNERS`, the bracketed list of DEPLOY §9); since the work packages were integrated
(TASKS post-step 1) a missing module or command is a packaging error and raises instead of getting the
Phase-0 "not implemented" stub.

Contract for ``register_cli(sub: argparse._SubParsersAction) -> None``: add sub-parsers with
``p.set_defaults(func=handler)`` where ``handler(args) -> int | None`` returns the exit code.
Commands that must not run next to the service (``worker-once``, ``tick``, ``restore``) check
``wd.jobs.lease.is_live`` themselves and exit 2 with the DEPLOY §9 hint.
"""

from __future__ import annotations

import argparse
import importlib
import logging
import os
import sys
from pathlib import Path
from typing import Sequence

from . import __version__, db
from .config import ConfigError, Settings, ensure_dirs
from .logging_setup import configure_logging

log = logging.getLogger("wd.cli")

CLI_MODULES: tuple[str, ...] = (
    "wd.seed",
    "wd.security",
    "wd.backup",
    "wd.ai.probe",
    "wd.jobs.worker",
    "wd.jobs.scheduler",
    "wd.services.batches",
    "wd.ai.consolidate",
    "wd.images.handler",
    "wd.diag",
    "wd.services.learn_order",
    "wd.ai.dance",
    "wd.audio",
)

# module → the commands it owns (DEPLOY §9); build_parser() verifies every one of them was registered
COMMAND_OWNERS: dict[str, tuple[str, ...]] = {
    "wd.seed": ("import-seed",),
    "wd.security": ("create-admin", "set-password", "promote", "demote", "invite", "unlock", "sms-probe"),
    "wd.backup": ("backup", "restore"),
    "wd.ai.probe": ("claude-check", "ai-check"),
    "wd.jobs.worker": ("worker-once",),
    "wd.jobs.scheduler": ("tick",),
    "wd.services.batches": ("build-batch", "push-now"),
    "wd.ai.consolidate": ("consolidate",),
    "wd.images.handler": ("fetch-image", "images-prune", "images-retry", "images-import"),
    "wd.diag": ("stats", "check", "logs"),
    "wd.services.learn_order": ("learn-order",),
    "wd.ai.dance": ("dance-annotate",),
    "wd.audio": ("audio-voices", "audio-probe", "audio-prewarm", "audio-texts"),
}

LEASE_HINT = "word-dance.service is running — watch `journalctl -u word-dance -f` or GET /api/admin/jobs instead"


def load_dotenv_if_present() -> None:
    """Read ``$WD_DATA_DIR/.env`` (python-dotenv, never overriding real environment variables)."""
    data_dir = os.environ.get("WD_DATA_DIR") or "/home/sqin/word-dance-data"
    env_file = Path(data_dir).expanduser() / ".env"
    if env_file.is_file():
        try:
            from dotenv import load_dotenv
        except ImportError:  # pragma: no cover - dependency is pinned
            return
        load_dotenv(env_file, override=False)


def settings_or_exit() -> Settings:
    try:
        return Settings.from_env()
    except ConfigError as e:
        print(f"wd: configuration error: {e}", file=sys.stderr)
        raise SystemExit(2)


# ------------------------------------------------------------------------------- own commands
def cmd_version(args: argparse.Namespace) -> int:
    print(f"wd {__version__}")
    return 0


def cmd_migrate(args: argparse.Namespace) -> int:
    cfg = settings_or_exit()
    ensure_dirs(cfg)
    conn = db.connect(cfg.db_path)
    try:
        if args.dry_run:
            result = db.run_migrations(conn, dry_run=True)
            if not result.pending:
                print("0 pending")
            for version, name in result.pending:
                print(f"pending {version:04d}_{name}.sql")
            return 0
        try:
            result = db.run_migrations(conn, pre_hook=db.backup_pre_hook())
        except db.MigrationError as e:
            print(f"wd migrate: {e}", file=sys.stderr)
            return 1
        if not result.applied:
            print("0 pending")
        for version, name in result.applied:
            print(f"applied {version:04d}_{name}.sql")
        print(f"schema version {db.current_version(conn)} at {cfg.db_path}")
        return 0
    finally:
        conn.close()
        _restrict_db_mode(cfg.db_path)


def _restrict_db_mode(db_path: Path) -> None:
    """Keep the database at 0600 (DEPLOY §1 table) whoever created it.

    ``wd serve`` sets ``os.umask(0o077)`` and the systemd units carry ``UMask=0077``, but install.sh
    runs ``wd migrate`` directly from a shell (DEPLOY §2/§5), where the default umask would leave a
    freshly created ``word-dance.db`` at 0644 inside the 0700 data directory. A chmod after the run is
    deterministic and has no process-wide side effect (unlike changing the umask for every command).
    """
    for suffix in ("", "-wal", "-shm"):
        p = Path(f"{db_path}{suffix}")
        try:
            if p.is_file():
                p.chmod(0o600)
        except OSError as e:  # pragma: no cover - ownership problems are reported, never fatal
            log.warning("could not restrict the mode of %s: %s", p, e)


def cmd_serve(args: argparse.Namespace) -> int:
    cfg = settings_or_exit()
    configure_logging(cfg)
    os.umask(0o077)  # DEPLOY §1: DB/WAL/images/backups 0600 regardless of the unit's UMask
    ensure_dirs(cfg)
    import uvicorn

    # exactly DEPLOY §3; access_log=False because main.py's middleware writes the one JSON line per request (DEPLOY §6)
    uvicorn.run(
        "wd.main:create_app",
        factory=True,
        host=cfg.host,
        port=cfg.port,
        workers=1,
        limit_concurrency=200,
        proxy_headers=cfg.trust_proxy,
        forwarded_allow_ips="127.0.0.1",
        log_config=None,
        access_log=False,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wd", description="word-Dance server CLI")
    parser.add_argument("--version", action="version", version=f"wd {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<command>")
    sub.required = True

    p = sub.add_parser("serve", help="run the API + web + scheduler + workers (uvicorn, 1 worker)")
    p.set_defaults(func=cmd_serve)
    p = sub.add_parser("migrate", help="apply pending migrations (pre-migrate snapshot first)")
    p.add_argument("--dry-run", action="store_true", help="list pending migration files only")
    p.set_defaults(func=cmd_migrate)
    p = sub.add_parser("version", help="print the version")
    p.set_defaults(func=cmd_version)

    for module in CLI_MODULES:
        mod = importlib.import_module(module)
        register = getattr(mod, "register_cli", None)
        if not callable(register):
            raise RuntimeError(f"{module} has no register_cli(sub); it owns the commands {', '.join(COMMAND_OWNERS.get(module, ()))}")
        register(sub)
        missing = [c for c in COMMAND_OWNERS.get(module, ()) if c not in sub.choices]
        if missing:
            raise RuntimeError(f"{module}.register_cli did not register its command(s): {', '.join(missing)}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv_if_present()
    # WD_SMOKE_MOCK_HTTP=1 + WD_DEV=1 (a no-op otherwise): `make smoke` drains the queue with `wd worker-once` subprocesses,
    # which must answer provider traffic from the fixtures exactly like `wd serve` (create_app) — local import on purpose
    from .smoke_mock import install_from_env

    install_from_env()
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    func = getattr(args, "func", None)
    if func is None:  # pragma: no cover - argparse enforces a sub-command
        parser.print_help()
        return 2
    rc = func(args)
    return int(rc or 0)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
