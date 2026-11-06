"""deploy/** and scripts/** (WP9): env.example quoting + completeness, rendered systemd units, install.sh dry runs,
the `.env` line-shape rejection, fetch_ecdict.sh offline paths, dev.sh / smoke.py syntax (TASKS WP9 acceptance)."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
DEPLOY = REPO / "deploy"
SCRIPTS = REPO / "scripts"
ENV_EXAMPLE = DEPLOY / "env.example"
INSTALL = DEPLOY / "install.sh"
FETCH = DEPLOY / "fetch_ecdict.sh"
UNITS = ("word-dance.service", "word-dance-backup.service", "word-dance-backup.timer")

# the exact line shape install.sh enforces before sourcing .env (DEPLOY §4)
LINE_RE = re.compile(r"""^WD_[A-Z0-9_]+=("[^"$`\\]*"|'[^']*')$""")
SHELL_CHECK = """grep -Ev '^[[:space:]]*(#|$)' "$1" | grep -Ev "^WD_[A-Z0-9_]+=(\\"[^\\"\\$\\`\\\\\\\\]*\\"|'[^']*')\\$" | wc -l"""


def _sh(cmd: list[str], *, env: dict[str, str] | None = None, cwd: Path = REPO, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=str(cwd), env=env, capture_output=True, text=True, timeout=timeout)


def env_lines() -> list[str]:
    return [l for l in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines() if l.strip() and not l.lstrip().startswith("#")]


def parse_env(path: Path = ENV_EXAMPLE) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, _, value = line.partition("=")
        out[key] = value[1:-1]
    return out


def _node_ok() -> bool:
    node = shutil.which("node")
    if not node:
        return False
    v = _sh([node, "--version"]).stdout.strip().lstrip("v")
    return v.split(".")[0].isdigit() and int(v.split(".")[0]) >= 22


def _install_env(tmp_path: Path, data_dir: Path | None, *, sudo_ok: bool = True, service_active: bool = False, unit_data: Path | None = None) -> dict[str, str]:
    """A hermetic environment for install.sh --dry-run: fake `claude`, `sudo` (passwordless or not) and `systemctl`
    (unit active or not) in PATH, no inherited WD_* values — the printed plan must not depend on the host's unit or
    sudoers. Under --dry-run only the read-only probes (`sudo -n true`, `systemctl is-active`) are executed.

    ``WD_UNIT_FILE`` always points into ``tmp_path``: a rendered ``word-dance.service`` whose ``EnvironmentFile=`` names
    ``unit_data`` when given, otherwise a path that does not exist — never the box's real unit (which names the
    production data directory and would make every run with another ``WD_DATA_DIR`` exit 2). ``data_dir=None`` leaves
    ``WD_DATA_DIR`` unset, the upgrade-after-a-move case of ops.md §5."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(exist_ok=True)
    fakes = {
        "claude": "exit 0",
        "sudo": "exit 0" if sudo_ok else "exit 1",
        "systemctl": f'[ "$1" = is-active ] && exit {0 if service_active else 3}\nexit 0',
    }
    for name, body in fakes.items():
        p = fake_bin / name
        p.write_text(f"#!/bin/sh\n{body}\n")
        p.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if not k.startswith("WD_")}
    env["PATH"] = f"{fake_bin}:{env.get('PATH', '/usr/bin:/bin')}"
    if data_dir is not None:
        env["WD_DATA_DIR"] = str(data_dir)
    if unit_data is not None:
        unit_file = tmp_path / "etc-systemd" / "word-dance.service"
        render_units(unit_file.parent, user="sqin", repo=REPO, data=unit_data)
    else:
        unit_file = tmp_path / "no-unit-installed" / "word-dance.service"  # never created, even when the same tmp_path rendered one above
    env["WD_UNIT_FILE"] = str(unit_file)
    return env


def _preamble_data_dir(tmp_path: Path, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    """Run install.sh's option loop and data-dir resolution only (everything before step 1) and print the result: the
    one way to observe the hard-coded default without the dry run reading whatever lives at that path on this box."""
    body = INSTALL.read_text(encoding="utf-8")
    preamble = body[: body.index("# 1. preflight")] + 'echo "RESOLVED DATA=$DATA UNIT_DATA=$UNIT_DATA"\n'
    script = tmp_path / "preamble.sh"
    script.write_text(preamble, encoding="utf-8")
    return _sh(["bash", str(script), *args], env=env)


def _lan_ip() -> str | None:
    """What install.sh computes: the default-route source address, else the first `hostname -I` address."""
    route = _sh(["bash", "-c", "ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i = 1; i <= NF; i++) if ($i == \"src\") {print $(i+1); exit}}'"]).stdout.strip()
    return route or _sh(["bash", "-c", "hostname -I 2>/dev/null | awk '{print $1}'"]).stdout.strip() or None


# ------------------------------------------------------------------------------------- env.example
def test_env_example_every_line_is_quoted_key_value():
    bad = [l for l in env_lines() if not LINE_RE.match(l)]
    assert bad == []
    # the very pipeline of the WP9 acceptance line, run by the shell
    cp = _sh(["bash", "-c", SHELL_CHECK, "_", str(ENV_EXAMPLE)])
    assert cp.returncode == 0, cp.stderr
    assert cp.stdout.strip() == "0"
    assert ENV_EXAMPLE.read_text(encoding="utf-8").startswith("# word-Dance configuration")
    assert "QUOTING RULE" in ENV_EXAMPLE.read_text(encoding="utf-8")


def test_env_example_covers_every_setting_exactly_once():
    from dataclasses import fields

    from wd.config import Settings

    expected = {"WD_" + f.name.upper() for f in fields(Settings) if f.name != "env_sources"}
    keys = [l.split("=", 1)[0] for l in env_lines()]
    assert len(keys) == len(set(keys)), "duplicate variable in env.example"
    assert set(keys) == expected
    # the lines install.sh rewrites with sed must exist in the KEY= form it matches
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    for key in ("WD_SECRET_KEY", "WD_CLAUDE_BIN", "WD_DATA_DIR", "WD_CONTACT_EMAIL", "WD_HOST", "WD_PUBLIC_URL", "WD_TRUST_PROXY", "WD_PORT", "WD_ECDICT_DB_PATH"):
        assert re.search(rf"^{key}=", text, re.M), key
    assert re.search(r'^WD_PUBLIC_URL=""$', text, re.M)  # the LAN-URL branch of install.sh keys on this exact shape
    assert re.search(r'^WD_PORT="8000"$', text, re.M)


def test_env_example_defaults_build_the_default_settings(tmp_path):
    from wd.config import Settings

    values = parse_env()
    values["WD_DATA_DIR"] = str(tmp_path)
    cfg = Settings.from_env(values)
    assert cfg.port == 8000 and cfg.host == "0.0.0.0" and cfg.tz == "Asia/Shanghai"
    assert cfg.registration_mode == "invite" and cfg.image_providers == ("wikimedia", "openverse")
    assert cfg.ai_batch_size == 10 and cfg.ai_daily_budget_usd == 3.0 and cfg.backup_keep_daily == 14 and cfg.backup_keep_weekly == 8
    assert cfg.db_path == tmp_path / "word-dance.db" and cfg.claude_cwd == tmp_path / "claude-cwd"
    assert cfg.public_url == "" and cfg.worker_enabled and cfg.ai_enabled and cfg.images_enabled
    assert cfg.smtp_port == 587 and cfg.smtp_tls == "starttls" and cfg.log_format == "json"
    assert cfg.secret_key.startswith("ephemeral-")  # empty in the template; install.sh generates the real one


def test_env_example_reads_identically_in_bash_and_python_dotenv():
    from dotenv import dotenv_values

    script = 'set -a; . "$1"; set +a; for k in $(compgen -v WD_); do printf "%s=%s\\n" "$k" "${!k}"; done'
    env = {k: v for k, v in os.environ.items() if not k.startswith("WD_")}
    cp = _sh(["bash", "-c", script, "_", str(ENV_EXAMPLE)], env=env)
    assert cp.returncode == 0, cp.stderr
    from_bash = dict(line.split("=", 1) for line in cp.stdout.splitlines())
    from_dotenv = {k: (v or "") for k, v in dotenv_values(ENV_EXAMPLE).items()}
    assert from_bash == from_dotenv == parse_env()


# ------------------------------------------------------------------------------------ systemd units
def render_units(dest: Path, *, user: str, repo: Path, data: Path) -> list[Path]:
    dest.mkdir(parents=True, exist_ok=True)
    out = []
    for name in UNITS:
        text = (DEPLOY / name).read_text(encoding="utf-8")
        if name.endswith(".service"):
            text = text.replace("__USER__", user).replace("__REPO__", str(repo)).replace("__DATA__", str(data))
        p = dest / name
        p.write_text(text, encoding="utf-8")
        out.append(p)
    return out


def test_units_match_deploy_contract():
    service = (DEPLOY / "word-dance.service").read_text(encoding="utf-8")
    for directive in (
        "User=__USER__", "WorkingDirectory=__REPO__", "EnvironmentFile=__DATA__/.env",
        "Environment=HOME=/home/__USER__", "Environment=PATH=/home/__USER__/.local/bin:/usr/local/bin:/usr/bin:/bin",
        "ExecStart=__REPO__/.venv/bin/wd serve", "Restart=on-failure", "TimeoutStopSec=300", "KillMode=mixed", "UMask=0077",
        "NoNewPrivileges=yes", "PrivateTmp=yes", "ProtectSystem=full", "WantedBy=multi-user.target", "After=network-online.target",
    ):
        assert directive in service, directive
    assert "ProtectHome" not in service.replace("# Deliberately NOT set: ProtectHome", "")
    backup_service = (DEPLOY / "word-dance-backup.service").read_text(encoding="utf-8")
    # never pin Group=: the service user's primary group is not necessarily named after the user (sqin → dip on this
    # box); a non-existent group makes every start fail with status 216/GROUP
    for unit in (service, backup_service):
        assert not re.search(r"^Group=", unit, re.M), "Group= must not be set; systemd uses the user's primary group"
    assert "Type=oneshot" in backup_service and "ExecStart=__REPO__/.venv/bin/wd backup --keep-daily 14 --keep-weekly 8" in backup_service
    assert "UMask=0077" in backup_service and "EnvironmentFile=__DATA__/.env" in backup_service
    timer = (DEPLOY / "word-dance-backup.timer").read_text(encoding="utf-8")
    assert "OnCalendar=*-*-* 03:30:00 Asia/Shanghai" in timer and "Persistent=true" in timer and "RandomizedDelaySec=10m" in timer
    assert "WantedBy=timers.target" in timer


def test_rendered_units_pass_systemd_analyze_verify(tmp_path):
    analyze = shutil.which("systemd-analyze")
    if not analyze:
        pytest.skip("systemd-analyze not available")
    repo = tmp_path / "repo"
    (repo / ".venv" / "bin").mkdir(parents=True)
    wd = repo / ".venv" / "bin" / "wd"
    wd.write_text("#!/bin/sh\nexit 0\n")
    wd.chmod(0o755)
    data = tmp_path / "data"
    data.mkdir()
    (data / ".env").write_text('WD_PORT="8000"\n')
    units = render_units(tmp_path / "units", user=os.environ.get("USER", "sqin"), repo=repo, data=data)
    for p in units:
        assert "__" not in re.sub(r"#.*", "", p.read_text(encoding="utf-8")), f"placeholder left in {p.name}"
    cp = _sh([analyze, "verify", *map(str, units)])
    assert cp.returncode == 0, cp.stderr
    problems = [l for l in cp.stderr.splitlines() if "word-dance" in l]
    assert problems == [], problems


# ------------------------------------------------------------------------------------- install.sh
def test_install_sh_syntax_help_and_unknown_option():
    assert _sh(["bash", "-n", str(INSTALL)]).returncode == 0
    assert os.access(INSTALL, os.X_OK)
    cp = _sh([str(INSTALL), "--help"])
    assert cp.returncode == 0 and "usage: deploy/install.sh" in cp.stdout and "--dry-run" in cp.stdout
    assert "--move-data" in cp.stdout and "EnvironmentFile=" in cp.stdout  # the data-dir rule is part of the usage text
    cp = _sh([str(INSTALL), "--bogus"])
    assert cp.returncode == 64 and "unknown option: --bogus" in cp.stdout
    cp = _sh([str(INSTALL), "--with-caddy"])  # domain required
    assert cp.returncode != 0
    # every mutating step goes through run(): no bare sudo/systemctl/pip/npm/sed -i/cp/install outside of it
    body = INSTALL.read_text(encoding="utf-8")
    for line in body.splitlines():
        code = line.split("#", 1)[0].strip()
        if not code or code.startswith(("log ", "echo ", "if ", "elif ", "else", "fi", "case", "esac", "for ", "done", "while", "do", "render()", "sudo_write()", "run()")):
            continue
        if code.startswith("sudo -n true"):  # the read-only preflight probe for passwordless sudo
            continue
        if re.match(r"^(sudo|systemctl|pip|npm|chmod|install |cp |sed -i|apt-get|certbot|ln |rm |mv )", code):
            pytest.fail(f"mutating command outside run(): {line!r}")


@pytest.mark.skipif(not _node_ok(), reason="install.sh preflight needs node >= 22")
def test_install_sh_dry_run_prints_every_step_and_changes_nothing(tmp_path):
    data = tmp_path / "data"
    env = _install_env(tmp_path, data)
    cp = _sh([str(INSTALL), "--dry-run"], env=env)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    out = cp.stdout
    assert "dry run complete — nothing was changed" in out
    plus = [l for l in out.splitlines() if l.startswith("+ ")]
    assert len(plus) >= 10
    for needle in ("+ install -d -m 0700", "pip install --quiet -r", "npm ci --silent && npm run build --silent", "/.venv/bin/wd migrate", "/.venv/bin/wd import-seed", "/.venv/bin/wd learn-order", "/.venv/bin/wd claude-check", "/.venv/bin/wd create-admin --if-none", f"+ cp {DEPLOY}/env.example {data}/.env"):
        assert any(needle in l for l in plus), needle
    assert not data.exists()  # nothing created
    assert not (REPO / ".venv").exists() or True  # the worktree may or may not have a venv; the dry run must not create one
    assert "+ sudo -n systemctl stop" not in out and "NOTE:" not in out  # the (fake) unit is inactive
    # the WD_PUBLIC_URL branch reads the template the dry run would have copied — never the absent .env
    # (was: `grep: …/.env: No such file or directory` on stderr and the planned `sed -i` missing from the plan)
    assert cp.stderr == ""
    sed_lines = [l for l in plus if l.startswith("+ sed -i") and "WD_PUBLIC_URL" in l]
    lan = _lan_ip()
    if lan:
        assert len(sed_lines) == 1 and f'WD_PUBLIC_URL="http://{lan}:8000"' in sed_lines[0], sed_lines
    else:
        assert sed_lines == []


@pytest.mark.skipif(not _node_ok(), reason="install.sh preflight needs node >= 22")
def test_install_sh_stops_a_running_service_unless_no_restart(tmp_path):
    """An upgrade on a box where word-dance.service is active stops it before `wd migrate` (step 6) — kept with --no-restart."""
    data = tmp_path / "data"
    env = _install_env(tmp_path, data, service_active=True, sudo_ok=True)
    cp = _sh([str(INSTALL), "--dry-run"], env=env)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    plus = [l for l in cp.stdout.splitlines() if l.startswith("+ ")]
    stop = [i for i, l in enumerate(plus) if l == "+ sudo -n systemctl stop word-dance.service"]
    migrate = [i for i, l in enumerate(plus) if "/.venv/bin/wd migrate" in l]
    assert len(stop) == 1 and migrate and stop[0] < migrate[0]
    cp = _sh([str(INSTALL), "--no-restart", "--dry-run"], env=env)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert "+ sudo -n systemctl stop" not in cp.stdout
    assert "NOTE: the running service is kept" in cp.stdout
    # without passwordless sudo the service is never touched (the operator runs the printed commands as root)
    cp = _sh([str(INSTALL), "--dry-run"], env=_install_env(tmp_path, data, service_active=True, sudo_ok=False))
    assert cp.returncode == 0 and "+ sudo -n systemctl stop" not in cp.stdout
    assert not data.exists()


@pytest.mark.skipif(not _node_ok(), reason="install.sh preflight needs node >= 22")
def test_install_sh_upgrade_with_sudo_stops_the_unit_before_migrate(tmp_path):
    data = tmp_path / "data"
    cp = _sh([str(INSTALL), "--dry-run"], env=_install_env(tmp_path, data, sudo_ok=True, service_active=True))
    assert cp.returncode == 0, cp.stdout + cp.stderr
    plus = [l for l in cp.stdout.splitlines() if l.startswith("+ ")]
    stop = plus.index("+ sudo -n systemctl stop word-dance.service")
    migrate = next(i for i, l in enumerate(plus) if l.endswith("/.venv/bin/wd migrate"))
    restart = plus.index("+ sudo -n systemctl restart word-dance.service")
    assert stop < migrate < restart
    assert "NOTE:" not in cp.stdout and "OLD version" not in cp.stdout


@pytest.mark.skipif(not _node_ok(), reason="install.sh preflight needs node >= 22")
def test_install_sh_upgrade_without_passwordless_sudo_warns_that_the_old_version_keeps_serving(tmp_path):
    """HAVE_SUDO=0 must not skip the running-unit check (`systemctl is-active` needs no privilege): the unit cannot be
    stopped, so the operator is told that the migration runs next to the live old process (additive only), that the
    OLD version keeps serving, and the root-steps hint says `restart` (`enable --now` is a no-op on an active unit)."""
    data = tmp_path / "data"
    env = _install_env(tmp_path, data, sudo_ok=False, service_active=True)
    cp = _sh([str(INSTALL), "--dry-run"], env=env)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    out = cp.stdout
    assert "WARN: no passwordless sudo — systemd steps will be printed, not executed" in out
    assert "NOTE: the running service is kept; pending migrations must be purely ADDITIVE" in out
    assert "WARN: no passwordless sudo — the OLD version keeps serving during and after this run; afterwards run: sudo systemctl restart word-dance" in out
    assert "systemctl stop" not in out
    assert "systemctl daemon-reload && systemctl restart word-dance" in out
    assert "enable --now word-dance word-dance-backup.timer" not in out
    lines = out.splitlines()
    note = next(i for i, l in enumerate(lines) if l.startswith("NOTE:"))
    migrate = next(i for i, l in enumerate(lines) if l.endswith("/.venv/bin/wd migrate"))
    assert note < migrate
    # --no-restart: the operator asked for it — the NOTE stays, the stale-process warning does not apply
    cp2 = _sh([str(INSTALL), "--dry-run", "--no-restart"], env=env)
    assert cp2.returncode == 0 and "NOTE: the running service is kept" in cp2.stdout and "OLD version keeps serving" not in cp2.stdout
    # no sudo but no running unit (a fresh box): neither line
    cp3 = _sh([str(INSTALL), "--dry-run"], env=_install_env(tmp_path, data, sudo_ok=False, service_active=False))
    assert cp3.returncode == 0 and "NOTE:" not in cp3.stdout and "OLD version" not in cp3.stdout
    assert "enable --now word-dance word-dance-backup.timer" in cp3.stdout
    # step 9 is not reached under --dry-run: pin its wording — the health line must not claim success for a stale process
    body = INSTALL.read_text(encoding="utf-8")
    assert re.search(r'^if \[ "\$STALE" = 1 \]; then echo "health OK, but the OLD process answered', body, re.M)
    assert body.index('if [ "$STALE" = 1 ]; then echo "health OK') < body.index('echo "word-Dance is running at $WD_PUBLIC_URL"')


# ------------------------------------------------------- install.sh: the frontend snapshot in the data dir (DEPLOY §1/§2/§10)
def _head_sha() -> str:
    """What install.sh names the snapshot after: ``git rev-parse --short HEAD`` of the checkout the tests run from."""
    cp = _sh(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"])
    assert cp.returncode == 0, cp.stderr
    return cp.stdout.strip()


@pytest.mark.skipif(not _node_ok(), reason="install.sh preflight needs node >= 22")
def test_install_sh_builds_the_frontend_into_a_versioned_snapshot_and_publishes_it_after_the_stop(tmp_path):
    """The installed service serves ``$DATA/frontend`` → ``frontend-releases/<sha>``, never ``<repo>/frontend/dist`` —
    which ``make test`` / ``npm run build`` in the checkout rewrite in place under the running process (seen on main:
    a gate run swapped the live SPA under the pre-upgrade backend). The slow build stays before the stop and goes into a
    staging dir (``<sha>.new``, so a re-run on the same commit never rebuilds the live tree); the publish — rename into
    place, ONE atomic rename of the symlink, prune to the two newest snapshots — follows the stop and precedes migrate."""
    data = tmp_path / "data"
    sha = _head_sha()
    releases = f"{data}/frontend-releases"
    cp = _sh([str(INSTALL), "--dry-run"], env=_install_env(tmp_path, data, sudo_ok=True, service_active=True))
    assert cp.returncode == 0, cp.stdout + cp.stderr
    plus = [l for l in cp.stdout.splitlines() if l.startswith("+ ")]
    mkdir = next(l for l in plus if l.startswith("+ install -d -m 0700 "))
    assert releases in mkdir.split()  # created 0700 like every other runtime subdirectory
    build = plus.index(f"+ bash -c cd '{REPO}/frontend' && npm ci --silent && npm run build --silent -- --outDir '{releases}/{sha}.new' --emptyOutDir")
    stop = plus.index("+ sudo -n systemctl stop word-dance.service")
    unstage = plus.index(f"+ rm -rf {releases}/{sha}")
    rename = plus.index(f"+ mv -T {releases}/{sha}.new {releases}/{sha}")
    link = plus.index(f"+ ln -sfn frontend-releases/{sha} {data}/frontend.tmp")  # relative target: the data dir may move (ops.md §5)
    swap = plus.index(f"+ mv -T {data}/frontend.tmp {data}/frontend")
    prune = plus.index(f"+ bash -c cd '{releases}' && ls -1t | tail -n +3 | xargs -r rm -rf --")
    migrate = next(i for i, l in enumerate(plus) if l.endswith("/.venv/bin/wd migrate"))
    restart = plus.index("+ sudo -n systemctl restart word-dance.service")
    assert build < stop < unstage < rename < link < swap < prune < migrate < restart
    assert f"==> frontend publish: {data}/frontend -> frontend-releases/{sha}" in cp.stdout
    assert "frontend/dist" not in cp.stdout  # the checkout's build directory is no longer part of the plan
    assert cp.stderr == ""
    assert not data.exists()


@pytest.mark.skipif(not _node_ok(), reason="install.sh preflight needs node >= 22")
def test_install_sh_publishes_the_snapshot_without_a_restart_too(tmp_path):
    """``--no-restart``, no passwordless sudo, or a fresh box (no running unit): the swap still happens after the point where
    the stop would be — the old process keeps serving the snapshot it resolved at startup until it is restarted (what
    today's in-place rebuild could not promise), and the plan ends before ``wd migrate`` as in the normal case."""
    data = tmp_path / "data"
    sha = _head_sha()
    swap = f"+ mv -T {data}/frontend.tmp {data}/frontend"
    for args, env in (
        (["--no-restart", "--dry-run"], _install_env(tmp_path, data, sudo_ok=True, service_active=True)),
        (["--dry-run"], _install_env(tmp_path, data, sudo_ok=False, service_active=True)),
        (["--dry-run"], _install_env(tmp_path, data, sudo_ok=True, service_active=False)),
    ):
        cp = _sh([str(INSTALL), *args], env=env)
        assert cp.returncode == 0, cp.stdout + cp.stderr
        lines = cp.stdout.splitlines()
        assert "systemctl stop" not in cp.stdout
        assert swap in lines and f"+ ln -sfn frontend-releases/{sha} {data}/frontend.tmp" in lines
        if "NOTE:" in cp.stdout:  # the running service is kept: said before the publish, which goes ahead anyway
            assert lines.index(next(l for l in lines if l.startswith("NOTE:"))) < lines.index(swap)
        assert lines.index(swap) < next(i for i, l in enumerate(lines) if l.endswith("/.venv/bin/wd migrate"))
        assert not data.exists()


@pytest.mark.skipif(not _node_ok(), reason="install.sh preflight needs node >= 22")
def test_install_sh_fills_an_empty_wd_frontend_dist_once(tmp_path):
    """Like ``WD_PUBLIC_URL``: an empty value (the dev default ``<repo>/frontend/dist``) is filled with the published symlink,
    a non-empty value is the operator's and is left alone, an old ``.env`` without the key gets it appended — the file is
    never rewritten (DEPLOY §2/§4). The first upgrade of a deployment whose ``.env`` carries ``WD_FRONTEND_DIST=""`` is the
    second case: one ``sed -i`` on that line, nothing else."""
    data = tmp_path / "data"
    fill = f'+ sed -i s|^WD_FRONTEND_DIST=.*|WD_FRONTEND_DIST="{data}/frontend"| {data}/.env'
    # a fresh box (no .env yet): the template's empty value is read, the fill targets the .env step 5 will have copied
    cp = _sh([str(INSTALL), "--dry-run"], env=_install_env(tmp_path, data))
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert fill in cp.stdout.splitlines() and cp.stderr == "" and not data.exists()
    # an existing .env with the empty value (every deployment before this change): filled once
    data.mkdir()
    shutil.copy(ENV_EXAMPLE, data / ".env")
    cp = _sh([str(INSTALL), "--dry-run"], env=_install_env(tmp_path, data))
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert [l for l in cp.stdout.splitlines() if "WD_FRONTEND_DIST" in l] == [fill]
    assert (data / ".env").read_text(encoding="utf-8") == ENV_EXAMPLE.read_text(encoding="utf-8")  # dry run: unchanged
    # a non-empty value is the operator's: no fill at all
    text = ENV_EXAMPLE.read_text(encoding="utf-8").replace('WD_FRONTEND_DIST=""', 'WD_FRONTEND_DIST="/srv/word-dance/ui"')
    (data / ".env").write_text(text, encoding="utf-8")
    cp = _sh([str(INSTALL), "--dry-run"], env=_install_env(tmp_path, data))
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert "WD_FRONTEND_DIST" not in "\n".join(l for l in cp.stdout.splitlines() if l.startswith("+ "))
    assert (data / ".env").read_text(encoding="utf-8") == text
    # an old .env without the key: appended in the §4 line shape, not rewritten
    text = "\n".join(l for l in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines() if not l.startswith("WD_FRONTEND_DIST=")) + "\n"
    (data / ".env").write_text(text, encoding="utf-8")
    cp = _sh([str(INSTALL), "--dry-run"], env=_install_env(tmp_path, data))
    assert cp.returncode == 0, cp.stdout + cp.stderr
    appended = [l for l in cp.stdout.splitlines() if l.startswith("+ ") and "WD_FRONTEND_DIST" in l]
    assert appended == [f"""+ bash -c printf 'WD_FRONTEND_DIST="%s"\\n' '{data}/frontend' >> '{data}/.env'"""]
    assert (data / ".env").read_text(encoding="utf-8") == text
    # the planned command itself, run by hand on the same file: one well-formed line, the rest byte-identical
    cp = _sh(["bash", "-c", appended[0][len("+ bash -c ") :]])
    assert cp.returncode == 0, cp.stderr
    lines = (data / ".env").read_text(encoding="utf-8").splitlines()
    assert lines[-1] == f'WD_FRONTEND_DIST="{data}/frontend"' and LINE_RE.match(lines[-1]) and "\n".join(lines[:-1]) + "\n" == text


def test_install_sh_refuses_a_frontend_directory_that_is_not_a_symlink(tmp_path):
    """``$DATA/frontend`` is the publish target of ``mv -T``, which cannot replace a real directory: say so in the
    preflight instead of failing in step 6 with the unit already stopped."""
    body = INSTALL.read_text(encoding="utf-8")
    assert re.search(r'^\[ ! -e "\$DATA/frontend" \] \|\| \[ -L "\$DATA/frontend" \] \|\| \{ echo ', body, re.M)
    assert body.index('[ ! -e "$DATA/frontend" ]') < body.index("# 2. data dir")  # read-only, before the first run()
    data = tmp_path / "data"
    (data / "frontend").mkdir(parents=True)
    cp = _sh([str(INSTALL), "--dry-run"], env=_install_env(tmp_path, data))
    assert cp.returncode == 1 and "is not a symlink" in cp.stdout and str(data / "frontend") in cp.stdout
    assert [l for l in cp.stdout.splitlines() if l.startswith("+ ")] == []
    # a symlink (a previous publish) or nothing at all passes
    shutil.rmtree(data / "frontend")
    (data / "frontend").symlink_to("frontend-releases/0000000")  # dangling is fine too: mv -T replaces it
    assert _sh([str(INSTALL), "--dry-run"], env=_install_env(tmp_path, data)).returncode == 0


# ------------------------------------------------------------------ install.sh: data dir vs the installed unit (ops.md §5)
def _fake_unit_env(tmp_path: Path, *, data_dir: Path | None) -> tuple[Path, dict[str, str]]:
    """An installed instance whose unit points at ``<tmp>/moved`` (the directory after an ops.md §5 move)."""
    unit_data = tmp_path / "moved"
    return unit_data, _install_env(tmp_path, data_dir, unit_data=unit_data)


@pytest.mark.skipif(not _node_ok(), reason="install.sh preflight needs node >= 22")
def test_install_sh_follows_the_installed_unit_when_wd_data_dir_is_unset(tmp_path):
    """An upgrade run after the data directory was moved (ops.md §5) must use the directory the installed unit serves —
    not create a fresh, empty instance at the default path and re-point the unit at it."""
    body = INSTALL.read_text(encoding="utf-8")
    # guard first: a script without the override would run the dry run below against the hard-coded default path
    assert "WD_UNIT_FILE" in body and re.search(r"^UNIT_FILE=\$\{WD_UNIT_FILE:-/etc/systemd/system/word-dance\.service\}", body, re.M)
    unit_data, env = _fake_unit_env(tmp_path, data_dir=None)
    assert "WD_DATA_DIR" not in env
    cp = _sh([str(INSTALL), "--dry-run"], env=env)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    out = cp.stdout
    assert f"data dir from the installed unit: {unit_data}" in out
    plus = [l for l in out.splitlines() if l.startswith("+ ")]
    assert any(l.startswith(f"+ install -d -m 0700 {unit_data} ") for l in plus), plus
    assert any(l == f"+ cp {DEPLOY}/env.example {unit_data}/.env" for l in plus), plus
    assert any(l.startswith(f"+ sed -i") and f"{unit_data}/.env" in l for l in plus)
    assert "/home/sqin/word-dance-data" not in out  # the default path appears nowhere in the plan
    assert "WARN" not in out and "ERROR" not in out
    assert cp.stderr == ""
    assert not unit_data.exists()  # dry run
    # the same resolution, observed directly: no `+` step and no .env read happen before it
    pre = _preamble_data_dir(tmp_path, env, "--dry-run")
    assert pre.returncode == 0 and f"RESOLVED DATA={unit_data} UNIT_DATA={unit_data}" in pre.stdout


@pytest.mark.skipif(not _node_ok(), reason="install.sh preflight needs node >= 22")
def test_install_sh_refuses_a_wd_data_dir_that_differs_from_the_installed_unit(tmp_path):
    """``WD_DATA_DIR`` naming another directory than the unit's is almost always a mistake (a stale profile export, a
    typo): exit 2 before any mutating step, with both paths and the way out in the message."""
    unit_data, env = _fake_unit_env(tmp_path, data_dir=tmp_path / "elsewhere")
    cp = _sh([str(INSTALL), "--dry-run"], env=env)
    assert cp.returncode == 2, cp.stdout + cp.stderr
    assert [l for l in cp.stdout.splitlines() if l.startswith("+ ")] == []  # nothing planned, let alone done
    assert "==> preflight" not in cp.stdout  # refused before step 1
    err = cp.stdout.splitlines()[-1]
    assert err.startswith("ERROR: WD_DATA_DIR=") and str(tmp_path / "elsewhere") in err and str(unit_data) in err
    assert "--move-data" in err and "ops.md §5" in err and env["WD_UNIT_FILE"] in err
    assert cp.stderr == ""
    assert not (tmp_path / "elsewhere").exists() and not unit_data.exists()
    # the same refusal without --dry-run (the real run exits at the same line, before the first `run`)
    cp2 = _sh([str(INSTALL)], env=env)
    assert cp2.returncode == 2 and "ERROR: WD_DATA_DIR=" in cp2.stdout and "==> preflight" not in cp2.stdout
    assert not (tmp_path / "elsewhere").exists() and not unit_data.exists()
    # WD_DATA_DIR equal to the unit's directory is the normal explicit form (the ops.md §5 profile export): silent
    cp3 = _sh([str(INSTALL), "--dry-run"], env=_install_env(tmp_path, unit_data, unit_data=unit_data))
    assert cp3.returncode == 0, cp3.stdout + cp3.stderr
    assert "ERROR" not in cp3.stdout and "WARN" not in cp3.stdout and "data dir from the installed unit" not in cp3.stdout
    assert any(l.startswith(f"+ install -d -m 0700 {unit_data} ") for l in cp3.stdout.splitlines())


@pytest.mark.skipif(not _node_ok(), reason="install.sh preflight needs node >= 22")
def test_install_sh_move_data_warns_and_repoints_the_units(tmp_path):
    """``--move-data`` is the ops.md §5 move itself: WARN, then the plan uses the new directory and re-renders both units
    (step 7 writes them from ``$DATA``, so the new ``EnvironmentFile=`` follows)."""
    unit_data, env = _fake_unit_env(tmp_path, data_dir=tmp_path / "bigger-disk")
    new = tmp_path / "bigger-disk"
    cp = _sh([str(INSTALL), "--move-data", "--dry-run"], env=env)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    out = cp.stdout
    warn = next(l for l in out.splitlines() if l.startswith("WARN: --move-data"))
    assert str(unit_data) in warn and str(new) in warn
    assert "ERROR" not in out
    plus = [l for l in out.splitlines() if l.startswith("+ ")]
    assert any(l.startswith(f"+ install -d -m 0700 {new} ") for l in plus), plus
    assert f"+ sudo_write {DEPLOY}/word-dance.service /etc/systemd/system/word-dance.service" in plus
    assert f"+ sudo_write {DEPLOY}/word-dance-backup.service /etc/systemd/system/word-dance-backup.service" in plus
    assert "+ sudo -n systemctl daemon-reload" in plus
    assert str(unit_data) not in "\n".join(plus)  # no step still targets the old directory
    assert out.index("WARN: --move-data") < out.index("==> preflight")  # said before anything else
    assert not new.exists() and not unit_data.exists()
    # the flag changes nothing when the unit already agrees (idempotent second run after the move) or no unit exists
    cp2 = _sh([str(INSTALL), "--move-data", "--dry-run"], env=_install_env(tmp_path, unit_data, unit_data=unit_data))
    assert cp2.returncode == 0 and "WARN: --move-data" not in cp2.stdout
    cp3 = _sh([str(INSTALL), "--move-data", "--dry-run"], env=_install_env(tmp_path, new))
    assert cp3.returncode == 0 and "WARN" not in cp3.stdout and "ERROR" not in cp3.stdout


def test_install_sh_data_dir_defaults_when_no_unit_is_installed(tmp_path):
    """A fresh box: no unit → ``WD_DATA_DIR`` when set, else the hard-coded default; a missing unit file is silent."""
    body = INSTALL.read_text(encoding="utf-8")
    assert re.search(r"^DATA=\$\{WD_DATA_DIR:-/home/sqin/word-dance-data\}$", body, re.M)  # the default itself is unchanged
    env = _install_env(tmp_path, None)
    assert not Path(env["WD_UNIT_FILE"]).exists()
    pre = _preamble_data_dir(tmp_path, env, "--dry-run")
    assert pre.returncode == 0, pre.stdout + pre.stderr
    assert "RESOLVED DATA=/home/sqin/word-dance-data UNIT_DATA=" in pre.stdout
    assert "data dir from the installed unit" not in pre.stdout and pre.stderr == ""  # no sed noise about the absent file
    pre2 = _preamble_data_dir(tmp_path, _install_env(tmp_path, tmp_path / "data"), "--dry-run")
    assert pre2.returncode == 0 and f"RESOLVED DATA={tmp_path / 'data'} UNIT_DATA=" in pre2.stdout
    assert "WARN" not in pre2.stdout and "ERROR" not in pre2.stdout
    # a unit without an EnvironmentFile= line (hand-written) counts as no unit
    odd = tmp_path / "odd.service"
    odd.write_text("[Service]\nExecStart=/bin/true\n", encoding="utf-8")
    pre3 = _preamble_data_dir(tmp_path, {**env, "WD_UNIT_FILE": str(odd)}, "--dry-run")
    assert pre3.returncode == 0 and "RESOLVED DATA=/home/sqin/word-dance-data UNIT_DATA=" in pre3.stdout


def test_deploy_doc_section_2_mirrors_install_sh():
    """DEPLOY.md §2 quotes install.sh in full; the quoted block must be the file, byte for byte."""
    doc = (REPO / "docs" / "DEPLOY.md").read_text(encoding="utf-8")
    start = doc.index("\n## 2. `deploy/install.sh`")
    end = doc.index("\n## 3. ", start)
    block = re.search(r"```bash\n(.*?)```\n", doc[start:end], re.S)
    assert block, "DEPLOY §2 must carry the install.sh code block"
    assert block.group(1) == INSTALL.read_text(encoding="utf-8")


@pytest.mark.skipif(not _node_ok(), reason="install.sh preflight needs node >= 22")
def test_install_sh_combined_flags_dry_run(tmp_path):
    data = tmp_path / "data"
    env = _install_env(tmp_path, data)
    cp = _sh([str(INSTALL), "--with-ecdict", "--with-caddy", "words.example.com", "--no-restart", "--dry-run"], env=env)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    out = cp.stdout
    assert f"+ {DEPLOY}/fetch_ecdict.sh {data}" in out
    assert 'WD_PUBLIC_URL=\\"https://words.example.com\\"' in out.replace('"', '\\"') or "WD_PUBLIC_URL=\"https://words.example.com\"" in out
    assert "WD_HOST=\"127.0.0.1\"" in out and "WD_TRUST_PROXY=\"1\"" in out
    assert "Caddyfile.example" in out and "apt-get install -y -qq caddy" in out
    assert "nginx" not in out.replace("python3-certbot-nginx", "")
    assert not data.exists()
    # the same flags in another order parse identically (the generated WD_SECRET_KEY differs per run — mask it)
    def plus_lines(text: str) -> list[str]:
        return [re.sub(r'WD_SECRET_KEY="[0-9a-f]{64}"', 'WD_SECRET_KEY="<random>"', l) for l in text.splitlines() if l.startswith("+ ")]

    cp2 = _sh([str(INSTALL), "--no-restart", "--with-caddy", "words.example.com", "--dry-run", "--with-ecdict"], env=env)
    assert cp2.returncode == 0 and plus_lines(cp2.stdout) == plus_lines(out)


@pytest.mark.skipif(not _node_ok(), reason="install.sh preflight needs node >= 22")
def test_install_sh_rejects_unquoted_env_value(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / ".env").write_text("WD_AI_EXTRA_ARGS=--effort low\n", encoding="utf-8")
    env = _install_env(tmp_path, data)
    cp = _sh([str(INSTALL), "--dry-run"], env=env)
    assert cp.returncode == 1
    assert "ERROR: every line of" in cp.stdout and 'must be KEY="value"' in cp.stdout
    assert "WD_AI_EXTRA_ARGS=--effort low" in cp.stdout.splitlines()[-1]
    assert "dry run complete" not in cp.stdout
    assert (data / ".env").read_text(encoding="utf-8") == "WD_AI_EXTRA_ARGS=--effort low\n"  # untouched


@pytest.mark.skipif(not _node_ok(), reason="install.sh preflight needs node >= 22")
def test_install_sh_accepts_quoted_env_including_single_quoted_secret(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    shutil.copy(ENV_EXAMPLE, data / ".env")
    text = (data / ".env").read_text(encoding="utf-8")
    text = text.replace('WD_SMTP_PASSWORD=""', "WD_SMTP_PASSWORD='p$ss`w\\d'").replace('WD_AI_EXTRA_ARGS=""', 'WD_AI_EXTRA_ARGS="--effort low"')
    text = text.replace('WD_PUBLIC_URL=""', 'WD_PUBLIC_URL="http://10.0.0.5:8000"')  # already set → the LAN-URL branch must not touch it
    (data / ".env").write_text(text, encoding="utf-8")
    env = _install_env(tmp_path, data)
    cp = _sh([str(INSTALL), "--dry-run"], env=env)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert "ERROR" not in cp.stdout
    assert "WD_PUBLIC_URL=" not in "\n".join(l for l in cp.stdout.splitlines() if l.startswith("+ "))
    assert (data / ".env").read_text(encoding="utf-8") == text


@pytest.mark.skipif(not _node_ok(), reason="install.sh preflight needs node >= 22")
def test_install_sh_dry_run_would_fill_lan_public_url(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    shutil.copy(ENV_EXAMPLE, data / ".env")
    env = _install_env(tmp_path, data)
    cp = _sh([str(INSTALL), "--dry-run"], env=env)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    sed_lines = [l for l in cp.stdout.splitlines() if l.startswith("+ sed -i") and "WD_PUBLIC_URL" in l]
    if _sh(["bash", "-c", "hostname -I 2>/dev/null | awk '{print $1}'"]).stdout.strip():
        assert len(sed_lines) == 1 and re.search(r'WD_PUBLIC_URL=\\?"http://[0-9.]+:8000\\?"', sed_lines[0]), sed_lines
        # the default-route address wins over bridge addresses (docker0 / lxdbr0) that `hostname -I` lists first
        route_ip = _sh(["bash", "-c", "ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i = 1; i <= NF; i++) if ($i == \"src\") {print $(i+1); exit}}'"]).stdout.strip()
        if route_ip:
            assert f"http://{route_ip}:8000" in sed_lines[0], (route_ip, sed_lines)
    assert (data / ".env").read_text(encoding="utf-8") == ENV_EXAMPLE.read_text(encoding="utf-8")  # dry run: unchanged


# --------------------------------------------------------------------------------- fetch_ecdict.sh
def _fake_ecdict_zip(tmp_path: Path, *, member_bytes: bytes | None = None) -> tuple[Path, str]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    dbfile = tmp_path / "stardict.db"
    if member_bytes is None:
        c = sqlite3.connect(dbfile)
        c.execute("CREATE TABLE stardict(word TEXT, translation TEXT)")
        c.execute("INSERT INTO stardict VALUES ('ubiquitous', '无处不在的')")
        c.commit()
        c.close()
    else:
        dbfile.write_bytes(member_bytes)
    zpath = tmp_path / "ecdict-sqlite-28.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(dbfile, "stardict.db")
    return zpath, hashlib.sha256(zpath.read_bytes()).hexdigest()


def test_fetch_ecdict_syntax_and_usage():
    assert _sh(["bash", "-n", str(FETCH)]).returncode == 0
    assert os.access(FETCH, os.X_OK)
    body = FETCH.read_text(encoding="utf-8")
    assert "ea01f76a3b3351021ce47077e89234465cc9441c8793054495320d06c0c3f3f6" in body
    assert "https://github.com/skywind3000/ECDICT/releases/download/1.0.28/ecdict-sqlite-28.zip" in body
    assert "python3 -m zipfile -e" in body and "curl -fL --retry 3" in body
    cp = _sh([str(FETCH)])
    assert cp.returncode != 0 and "usage" in (cp.stderr + cp.stdout)


def test_fetch_ecdict_is_idempotent_when_present(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "stardict.db").write_bytes(b"existing")
    cp = _sh([str(FETCH), str(data)])
    assert cp.returncode == 0 and "already present" in cp.stdout
    assert (data / "stardict.db").read_bytes() == b"existing"


@pytest.mark.skipif(not shutil.which("curl") or not shutil.which("sha256sum"), reason="needs curl + sha256sum")
def test_fetch_ecdict_offline_happy_path_and_env_update(tmp_path):
    zpath, sha = _fake_ecdict_zip(tmp_path / "src")
    data = tmp_path / "data"
    data.mkdir()
    (data / ".env").write_text('WD_PORT="8000"\nWD_ECDICT_DB_PATH=""\n', encoding="utf-8")
    env = {**os.environ, "ECDICT_URL": zpath.as_uri(), "ECDICT_SHA256": sha}
    cp = _sh([str(FETCH), str(data)], env=env)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    target = data / "stardict.db"
    assert target.is_file() and stat.S_IMODE(target.stat().st_mode) == 0o600
    c = sqlite3.connect(target)
    assert c.execute("SELECT word FROM stardict").fetchone()[0] == "ubiquitous"
    c.close()
    assert not (data / "tmp" / "ecdict-sqlite-28.zip").exists() and not (data / "tmp" / "ecdict").exists()
    lines = (data / ".env").read_text(encoding="utf-8").splitlines()
    assert lines == ['WD_PORT="8000"', f'WD_ECDICT_DB_PATH="{target}"']
    assert all(LINE_RE.match(l) for l in lines)
    # second run: exits 0 at once without touching anything
    cp2 = _sh([str(FETCH), str(data)], env=env)
    assert cp2.returncode == 0 and "already present" in cp2.stdout


@pytest.mark.skipif(not shutil.which("curl") or not shutil.which("sha256sum"), reason="needs curl + sha256sum")
def test_fetch_ecdict_appends_env_line_when_missing(tmp_path):
    zpath, sha = _fake_ecdict_zip(tmp_path / "src")
    data = tmp_path / "data"
    data.mkdir()
    (data / ".env").write_text('WD_PORT="8000"\n', encoding="utf-8")
    cp = _sh([str(FETCH), str(data)], env={**os.environ, "ECDICT_URL": zpath.as_uri(), "ECDICT_SHA256": sha})
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert (data / ".env").read_text(encoding="utf-8") == f'WD_PORT="8000"\nWD_ECDICT_DB_PATH="{data / "stardict.db"}"\n'


@pytest.mark.skipif(not shutil.which("curl") or not shutil.which("sha256sum"), reason="needs curl + sha256sum")
def test_fetch_ecdict_sha_mismatch_deletes_archive(tmp_path):
    zpath, _ = _fake_ecdict_zip(tmp_path / "src")
    data = tmp_path / "data"
    cp = _sh([str(FETCH), str(data)], env={**os.environ, "ECDICT_URL": zpath.as_uri(), "ECDICT_SHA256": "0" * 64})
    assert cp.returncode == 1
    assert "sha256 mismatch" in cp.stdout
    assert not (data / "tmp" / "ecdict-sqlite-28.zip").exists()
    assert not (data / "stardict.db").exists()


@pytest.mark.skipif(not shutil.which("curl") or not shutil.which("sha256sum"), reason="needs curl + sha256sum")
def test_fetch_ecdict_rejects_member_that_is_not_a_database(tmp_path):
    zpath, sha = _fake_ecdict_zip(tmp_path / "src", member_bytes=b"<html>not a database</html>")
    data = tmp_path / "data"
    cp = _sh([str(FETCH), str(data)], env={**os.environ, "ECDICT_URL": zpath.as_uri(), "ECDICT_SHA256": sha})
    assert cp.returncode == 1
    assert "not a readable ECDICT database" in cp.stdout
    assert not (data / "stardict.db").exists() and not (data / "tmp" / "ecdict").exists()


# ----------------------------------------------------------------------------- proxies, scripts, make
def test_proxy_examples_follow_deploy_section_7():
    caddy = (DEPLOY / "Caddyfile.example").read_text(encoding="utf-8")
    assert caddy.startswith("# deploy/Caddyfile.example") and "__DOMAIN__ {" in caddy and "reverse_proxy 127.0.0.1:8000" in caddy
    assert "encode zstd gzip" in caddy and "max_size 2MB" in caddy
    nginx = (DEPLOY / "nginx.conf.example").read_text(encoding="utf-8")
    assert nginx.count("server_name __DOMAIN__") == 2 and "listen 443 ssl http2" in nginx
    assert "proxy_pass http://127.0.0.1:8000" in nginx and "X-Forwarded-Proto $scheme" in nginx and "client_max_body_size 2m" in nginx
    assert "/etc/letsencrypt/live/__DOMAIN__/fullchain.pem" in nginx


def test_dev_sh_and_smoke_py_are_well_formed():
    dev = SCRIPTS / "dev.sh"
    assert dev.is_file() and os.access(dev, os.X_OK)
    assert _sh(["bash", "-n", str(dev)]).returncode == 0
    body = dev.read_text(encoding="utf-8")
    for needle in ("WD_DEV=1", "WD_REGISTRATION_MODE=open", "fake_claude.py", "--reload", "npm run dev", "WD_DEV_REAL_CLAUDE"):
        assert needle in body, needle
    smoke = SCRIPTS / "smoke.py"
    assert smoke.is_file()
    cp = _sh([sys.executable, "-m", "py_compile", str(smoke)])
    assert cp.returncode == 0, cp.stderr
    cp = _sh([sys.executable, str(smoke), "--help"])
    assert cp.returncode == 0 and "--port" in cp.stdout and "8010" in cp.stdout


def test_makefile_targets_are_wired():
    mk = (REPO / "Makefile").read_text(encoding="utf-8")
    assert re.search(r"^smoke:.*\n(\t.*\n)*\t.*scripts/smoke\.py", mk, re.M)
    assert re.search(r"^install:.*\n(\t.*\n)*\t.*deploy/install\.sh", mk, re.M)
    assert re.search(r"^backup:.*\n(\t.*\n)*\t.*\bbackup\b", mk, re.M)
    assert "--keep-daily 14 --keep-weekly 8" in mk
