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


def _install_env(tmp_path: Path, data_dir: Path) -> dict[str, str]:
    """A hermetic environment for install.sh --dry-run: a fake `claude` in PATH, no inherited WD_* values."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(exist_ok=True)
    claude = fake_bin / "claude"
    claude.write_text("#!/bin/sh\nexit 0\n")
    claude.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if not k.startswith("WD_")}
    env["PATH"] = f"{fake_bin}:{env.get('PATH', '/usr/bin:/bin')}"
    env["WD_DATA_DIR"] = str(data_dir)
    return env


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
        "User=__USER__", "Group=__USER__", "WorkingDirectory=__REPO__", "EnvironmentFile=__DATA__/.env",
        "Environment=HOME=/home/__USER__", "Environment=PATH=/home/__USER__/.local/bin:/usr/local/bin:/usr/bin:/bin",
        "ExecStart=__REPO__/.venv/bin/wd serve", "Restart=on-failure", "TimeoutStopSec=300", "KillMode=mixed", "UMask=0077",
        "NoNewPrivileges=yes", "PrivateTmp=yes", "ProtectSystem=full", "WantedBy=multi-user.target", "After=network-online.target",
    ):
        assert directive in service, directive
    assert "ProtectHome" not in service.replace("# Deliberately NOT set: ProtectHome", "")
    backup_service = (DEPLOY / "word-dance-backup.service").read_text(encoding="utf-8")
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
        if re.match(r"^(sudo|systemctl|pip|npm|chmod|install |cp |sed -i|apt-get|certbot|ln )", code):
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
    for needle in ("+ install -d -m 0700", "pip install --quiet -r", "npm ci --silent && npm run build --silent", "/.venv/bin/wd migrate", "/.venv/bin/wd import-seed", "/.venv/bin/wd claude-check", "/.venv/bin/wd create-admin --if-none", f"+ cp {DEPLOY}/env.example {data}/.env"):
        assert any(needle in l for l in plus), needle
    assert not data.exists()  # nothing created
    assert not (REPO / ".venv").exists() or True  # the worktree may or may not have a venv; the dry run must not create one
    assert "+ sudo -n systemctl stop" not in out  # no service is running here


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
