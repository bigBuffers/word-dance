# word-Dance — Deployment and operations (Ubuntu 24.04, this box)

Facts this relies on (FACTS §1/§3): Ubuntu 24.04.4, Python 3.12.3 with `python3.12-venv` (PEP 668 → venv mandatory), Node 22.22.2 / npm 10.9.7, systemd 255, passwordless `sudo -n`, `loginctl` Linger=**no** (so a `systemctl --user` unit would die at logout → we use a **system** unit running as `sqin`), `claude` 2.1.299 at `/home/sqin/.local/bin/claude` authenticated for `sqin` (credentials in `/home/sqin/.claude*`, no `ANTHROPIC_API_KEY`), ports 8000/80/443 free, 92 GB free on `/home`.

## 1. Layout on the box

| Path | Purpose | Mode / owner |
|---|---|---|
| `/home/sqin/word-Dance` | git checkout (code only; safe to `git pull`) | sqin |
| `/home/sqin/word-Dance/.venv` | Python venv (gitignored) | sqin |
| `/home/sqin/word-Dance/frontend/dist` | dev build of the SPA (gitignored; written by `make test` / `npm run build`) — **not served by the installed service** | sqin |
| `/home/sqin/word-dance-data` (`WD_DATA_DIR`) | **all runtime state**, outside the checkout | 0700 sqin |
| `…/word-dance-data/.env` | config + secrets (`EnvironmentFile`) | 0600 sqin |
| `…/word-dance-data/word-dance.db` (+`-wal`,`-shm`) | SQLite | 0600 |
| `…/word-dance-data/images/<2hex>/<sha>.jpg\|.svg` | cached media | 0600 |
| `…/word-dance-data/claude-cwd/` | empty cwd for `claude -p` | 0700 |
| `…/word-dance-data/claude-logs/YYYY-MM-DD/` | raw CLI stdout/stderr, 14 days | 0600 |
| `…/word-dance-data/backups/` | `word-dance-YYYYMMDD-HHMM.db.gz`, `pre-migrate-<v>.db.gz` | 0600 |
| `…/word-dance-data/tmp/` | downloads in flight (cleared at start) | 0700 |
| `…/word-dance-data/frontend` → `frontend-releases/<sha>` | symlink to the live SPA snapshot (`WD_FRONTEND_DIST`, §4), replaced with one atomic rename by install.sh step 6 after the unit is stopped; `wd serve` resolves it at startup | sqin |
| `…/word-dance-data/frontend-releases/<sha>/` | built SPA snapshots (`index.html`, `assets/`), one per deployed commit; the two newest are kept — the older one is the UI rollback target (§10) | 0700 |
| `/etc/systemd/system/word-dance.service`, `word-dance-backup.{service,timer}` | units (installed with sudo) | root |

`UMask=0077` in the units plus `os.umask(0o077)` in `wd serve` guarantee the modes above. The files inside `frontend-releases/` keep the build's modes (static assets, written by `npm run build` from the operator's shell): the 0700 parent directories keep them private to `sqin`, the user that serves them. `git clean -fdx` in the checkout can never destroy data.

## 2. `deploy/install.sh` (idempotent; run as `sqin` from the checkout; `sudo -n` only for systemd/proxy files)

```bash
#!/usr/bin/env bash
# usage: deploy/install.sh [--with-caddy DOMAIN | --with-nginx DOMAIN] [--with-ecdict] [--no-restart] [--dry-run] [--contact-email ADDR] [--move-data]
#        options may be given in any order and combined, e.g. deploy/install.sh --with-ecdict --with-caddy words.example.com --no-restart
#        data dir: $WD_DATA_DIR when set, else the directory the installed unit's EnvironmentFile= points at, else /home/sqin/word-dance-data;
#        a WD_DATA_DIR that differs from the installed unit's directory is refused (exit 2) unless --move-data re-points the units (ops.md §5)
set -euo pipefail
REPO=$(cd "$(dirname "$0")/.." && pwd)
DATA=${WD_DATA_DIR:-/home/sqin/word-dance-data}
UNIT_FILE=${WD_UNIT_FILE:-/etc/systemd/system/word-dance.service}      # WD_UNIT_FILE: the tests point it at a temp file so the dry runs stay hermetic
UNIT_DATA=$(sed -n 's|^EnvironmentFile=\(.*\)/\.env$|\1|p' "$UNIT_FILE" 2>/dev/null | head -n1 || true)   # data dir of the installed instance ('' when none)
RUN_USER=${RUN_USER:-$(id -un)}            # must be the user whose `claude` CLI is authenticated (sqin)
PY=python3
PROXY=""; DOMAIN=""; ECDICT=0; NO_RESTART=0; DRY=0; MOVE_DATA=0; CONTACT=${WD_CONTACT_EMAIL:-}
while [ $# -gt 0 ]; do
  case "$1" in
    --with-caddy|--with-nginx) PROXY=${1#--with-}; DOMAIN=${2:?domain required after $1}; shift;;
    --with-ecdict)   ECDICT=1;;
    --no-restart)    NO_RESTART=1;;
    --dry-run)       DRY=1;;
    --contact-email) CONTACT=${2:?address required after --contact-email}; shift;;
    --move-data)     MOVE_DATA=1;;
    -h|--help)       sed -n '2,5p' "$0"; exit 0;;
    *) echo "unknown option: $1"; sed -n '2,5p' "$0"; exit 64;;
  esac
  shift
done
log(){ printf '\n==> %s\n' "$*"; }
run(){ if [ "$DRY" = 1 ]; then echo "+ $*"; else "$@"; fi; }     # EVERY mutating step goes through run(); --dry-run prints them and changes nothing

# 0. data dir (read-only, so it also runs under --dry-run) ------------------
# An installed instance owns its data directory: an upgrade run without WD_DATA_DIR follows the unit (a moved directory,
# ops.md §5, no longer gets a fresh empty instance at the default path), and an explicit WD_DATA_DIR that disagrees with the
# unit is refused before anything is changed — --move-data says the disagreement is intended and step 7 re-points both units.
if [ -n "$UNIT_DATA" ]; then
  if [ -z "${WD_DATA_DIR:-}" ]; then
    DATA=$UNIT_DATA; echo "data dir from the installed unit: $DATA"
  elif [ "$WD_DATA_DIR" != "$UNIT_DATA" ]; then
    if [ "$MOVE_DATA" = 1 ]; then echo "WARN: --move-data: the installed unit ($UNIT_FILE) uses $UNIT_DATA; both units will be re-pointed at $DATA"
    else echo "ERROR: WD_DATA_DIR=$WD_DATA_DIR but the installed unit ($UNIT_FILE) uses $UNIT_DATA — unset WD_DATA_DIR to upgrade that instance, or pass --move-data after moving the directory (ops.md §5)"; exit 2; fi
  fi
fi

# 1. preflight (read-only) -------------------------------------------------
log "preflight"
$PY -c 'import sys; assert sys.version_info >= (3,12), sys.version'
$PY -c 'import venv, ensurepip, sqlite3, zoneinfo'          # python3.12-venv present (verified)
node --version | grep -Eq '^v(2[2-9]|[3-9][0-9])' || { echo "Node >= 22 required"; exit 1; }
CLAUDE_BIN=$(command -v claude || true)
[ -n "$CLAUDE_BIN" ] || { echo "claude CLI not found in PATH for $RUN_USER (expected /home/sqin/.local/bin/claude)"; exit 1; }
[ "$(df --output=avail -m /home | tail -1)" -gt 2048 ] || { echo "need > 2 GB free on /home"; exit 1; }
[ -f "$REPO/frontend/package-lock.json" ] || { echo "frontend/package-lock.json missing (npm ci needs it)"; exit 1; }
[ ! -e "$DATA/frontend" ] || [ -L "$DATA/frontend" ] || { echo "$DATA/frontend exists and is not a symlink — move it away; step 6 publishes the SPA there as a symlink into $DATA/frontend-releases/ (DEPLOY §1)"; exit 1; }
sudo -n true 2>/dev/null && HAVE_SUDO=1 || { HAVE_SUDO=0; echo "WARN: no passwordless sudo — systemd steps will be printed, not executed"; }

# 2. data dir -------------------------------------------------------------
log "data dir $DATA"
run install -d -m 0700 "$DATA" "$DATA/images" "$DATA/claude-cwd" "$DATA/claude-logs" "$DATA/backups" "$DATA/tmp" "$DATA/frontend-releases"

# 3. backend venv ---------------------------------------------------------
log "python venv"
[ -d "$REPO/.venv" ] || run $PY -m venv "$REPO/.venv"
run "$REPO/.venv/bin/pip" install --quiet --upgrade pip wheel
run "$REPO/.venv/bin/pip" install --quiet -r "$REPO/backend/requirements.txt"
run "$REPO/.venv/bin/pip" install --quiet -e "$REPO/backend"          # provides the `wd` console script ([build-system] setuptools, TASKS P0)

# 4. frontend build → a versioned snapshot inside the data dir, never <repo>/frontend/dist ------------------------
# The installed service serves $DATA/frontend, a symlink step 6 swaps atomically after the unit is stopped — so a build in
# the checkout (`make test`, `npm run build`) can no longer replace the assets of the running process, and a re-run on the
# same commit builds into a staging dir (<sha>.new) instead of the live tree. The slow part stays here, before the stop.
log "frontend build"
REL=$(git -C "$REPO" rev-parse --short HEAD 2>/dev/null || date +%s)        # one snapshot per deployed commit: frontend-releases/<sha>
run bash -c "cd '$REPO/frontend' && npm ci --silent && npm run build --silent -- --outDir '$DATA/frontend-releases/$REL.new' --emptyOutDir"

# 5. .env (created once; never overwritten) -------------------------------
if [ ! -f "$DATA/.env" ]; then
  log "creating $DATA/.env"
  if [ -z "$CONTACT" ] && [ -t 0 ] && [ "$DRY" = 0 ]; then
    read -r -p "Contact e-mail for the Wikimedia User-Agent (WD_CONTACT_EMAIL) [admin@localhost]: " CONTACT
  fi
  run cp "$REPO/deploy/env.example" "$DATA/.env"
  # every value is written DOUBLE-QUOTED (KEY="value"): the file is parsed by bash (`.` below), systemd EnvironmentFile and python-dotenv (§4)
  run sed -i "s|^WD_SECRET_KEY=.*|WD_SECRET_KEY=\"$(openssl rand -hex 32)\"|; s|^WD_CLAUDE_BIN=.*|WD_CLAUDE_BIN=\"$CLAUDE_BIN\"|; s|^WD_DATA_DIR=.*|WD_DATA_DIR=\"$DATA\"|; s|^WD_CONTACT_EMAIL=.*|WD_CONTACT_EMAIL=\"${CONTACT:-admin@localhost}\"|" "$DATA/.env"
  run chmod 0600 "$DATA/.env"
fi
# under --dry-run step 5 printed the cp but did not create the file: read the template it would have copied
# (WD_PUBLIC_URL / WD_PORT are not among the keys step 5 rewrites); the `run sed -i` below still targets $DATA/.env
ENV_READ=$DATA/.env; [ -f "$ENV_READ" ] || ENV_READ=$REPO/deploy/env.example
if [ -n "$PROXY" ]; then
  run sed -i "s|^WD_HOST=.*|WD_HOST=\"127.0.0.1\"|; s|^WD_PUBLIC_URL=.*|WD_PUBLIC_URL=\"https://$DOMAIN\"|; s|^WD_TRUST_PROXY=.*|WD_TRUST_PROXY=\"1\"|" "$DATA/.env"
elif grep -Eq '^WD_PUBLIC_URL=("")?$' "$ENV_READ"; then
  # no proxy and no public URL yet → the LAN URL, so e-mail buttons / webhook `url` fields have a target (DESIGN §6.5); the CSRF check
  # also accepts the Host-derived origin (API.md §1), so reaching the site by hostname keeps working
  # the address of the default route — `hostname -I` lists bridge addresses (docker0 / lxdbr0, often link-down) first
  LAN_IP=$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i = 1; i <= NF; i++) if ($i == "src") {print $(i+1); exit}}')
  [ -n "$LAN_IP" ] || LAN_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
  PORT=$(sed -n 's/^WD_PORT="\{0,1\}\([0-9][0-9]*\)"\{0,1\}$/\1/p' "$ENV_READ"); PORT=${PORT:-8000}
  [ -n "$LAN_IP" ] && run sed -i "s|^WD_PUBLIC_URL=.*|WD_PUBLIC_URL=\"http://$LAN_IP:$PORT\"|" "$DATA/.env"
fi
# the SPA path, filled once like WD_PUBLIC_URL: an empty WD_FRONTEND_DIST (the dev default <repo>/frontend/dist) becomes the
# symlink step 6 publishes; a non-empty value is the operator's and is left alone; an old .env without the key gets it appended
if grep -Eq '^WD_FRONTEND_DIST=("")?$' "$ENV_READ"; then
  run sed -i "s|^WD_FRONTEND_DIST=.*|WD_FRONTEND_DIST=\"$DATA/frontend\"|" "$DATA/.env"
elif ! grep -q '^WD_FRONTEND_DIST=' "$ENV_READ"; then
  run bash -c "printf 'WD_FRONTEND_DIST=\"%s\"\n' '$DATA/frontend' >> '$DATA/.env'"
fi
if [ -f "$DATA/.env" ]; then
  # the file is sourced by bash below: an unquoted value with a space (WD_AI_EXTRA_ARGS=--effort low) would RUN the command `low`.
  # Rule (§4): every non-comment line is KEY="value" (or KEY='value' for a secret containing $ ` or \). Checked before sourcing.
  bash -n "$DATA/.env" || { echo "ERROR: $DATA/.env is not valid shell"; exit 1; }
  if grep -Ev '^[[:space:]]*(#|$)' "$DATA/.env" | grep -Evq "^WD_[A-Z0-9_]+=(\"[^\"\$\`\\\\]*\"|'[^']*')\$"; then
    echo "ERROR: every line of $DATA/.env must be KEY=\"value\" (double quotes; use single quotes when the value contains \$ \` or \\). Offending line(s):"
    grep -Ev '^[[:space:]]*(#|$)' "$DATA/.env" | grep -Ev "^WD_[A-Z0-9_]+=(\"[^\"\$\`\\\\]*\"|'[^']*')\$"; exit 1
  fi
  set -a; . "$DATA/.env"; set +a
fi

# 6. database: stop the live unit, migrate (pre-migrate backup inside) + seed + probe + admin --------------------
log "migrate + seed"
ACTIVE=0; systemctl is-active --quiet word-dance.service 2>/dev/null && ACTIVE=1   # read-only probe, needs no sudo (same call as wd.backup.service_is_active)
STALE=0                                                                            # 1: the OLD process keeps serving after this run (step 9 must not claim success)
if [ "$ACTIVE" = 1 ]; then
  if [ "$HAVE_SUDO" = 1 ] && [ "$NO_RESTART" = 0 ]; then
    run sudo -n systemctl stop word-dance.service        # an upgrade: the previous version must not keep serving while the schema changes,
  else                                                   # and the pre-migrate `VACUUM INTO` must not race live writes; step 7 starts it again
    if [ "$NO_RESTART" = 0 ]; then STALE=1; fi
    echo "NOTE: the running service is kept; pending migrations must be purely ADDITIVE (new tables/columns/indexes only) — DEPLOY §10"
    if [ "$STALE" = 1 ]; then echo "WARN: no passwordless sudo — the OLD version keeps serving during and after this run; afterwards run: sudo systemctl restart word-dance"; fi
  fi
fi
# publish the snapshot built in step 4: rename the staging dir into place, swap the `frontend` symlink with ONE rename (relative
# target, so a moved data dir keeps working), keep the two newest snapshots (the previous one is the rollback target, ops.md §4).
# After the stop, so the old process never sees a half-published tree; under --no-restart / without sudo it keeps serving the
# snapshot it resolved at startup until it is restarted (never a new SPA on top of the old API).
log "frontend publish: $DATA/frontend -> frontend-releases/$REL"
run rm -rf "$DATA/frontend-releases/$REL"
run mv -T "$DATA/frontend-releases/$REL.new" "$DATA/frontend-releases/$REL"
run ln -sfn "frontend-releases/$REL" "$DATA/frontend.tmp"
run mv -T "$DATA/frontend.tmp" "$DATA/frontend"
run bash -c "cd '$DATA/frontend-releases' && ls -1t | tail -n +3 | xargs -r rm -rf --"
run "$REPO/.venv/bin/wd" migrate                                    # cli.py: db.run_migrations() records each NNNN file itself; snapshots first (§5)
run "$REPO/.venv/bin/wd" import-seed                                # reads WD_SEED_PATH (default <repo>/data/seed/vocab.jsonl.gz); idempotent; no-op when kv.seed_version matches
log "claude probe (<= \$0.05)"
run "$REPO/.venv/bin/wd" claude-check || echo "WARN: claude check failed — run 'claude' once as $RUN_USER to log in, then 'wd claude-check'"
run "$REPO/.venv/bin/wd" create-admin --if-none                     # uses WD_ADMIN_USERNAME/WD_ADMIN_PASSWORD when set; otherwise prints a hint and exits 0 —
                                                                    # the first web registration then becomes admin without an invite code (API.md endpoint 2)
if [ "$ECDICT" = 1 ]; then run "$REPO/deploy/fetch_ecdict.sh" "$DATA"; fi   # optional 216 MB download → $DATA/stardict.db (sha256-checked, stdlib zipfile), sets WD_ECDICT_DB_PATH in .env

# 7. systemd (system units, User=sqin) ------------------------------------
log "systemd"
render(){ sed "s|__USER__|$RUN_USER|g; s|__REPO__|$REPO|g; s|__DATA__|$DATA|g" "$1"; }
sudo_write(){ render "$1" | sudo -n tee "$2" >/dev/null; }
if [ "$HAVE_SUDO" = 1 ]; then
  run sudo_write "$REPO/deploy/word-dance.service"        /etc/systemd/system/word-dance.service
  run sudo_write "$REPO/deploy/word-dance-backup.service" /etc/systemd/system/word-dance-backup.service
  run sudo -n cp "$REPO/deploy/word-dance-backup.timer" /etc/systemd/system/
  run sudo -n systemctl daemon-reload
  run sudo -n systemctl enable word-dance.service word-dance-backup.timer
  if [ "$NO_RESTART" = 1 ]; then run sudo -n systemctl start word-dance.service; else run sudo -n systemctl restart word-dance.service; fi
  run sudo -n systemctl start word-dance-backup.timer
else
  if [ "$ACTIVE" = 1 ]; then ROOT_STEPS="systemctl daemon-reload && systemctl restart word-dance && systemctl enable --now word-dance-backup.timer"   # `enable --now` is a no-op on an active unit
  else ROOT_STEPS="systemctl daemon-reload && systemctl enable --now word-dance word-dance-backup.timer"; fi
  echo "run as root:"; echo "  install units from $REPO/deploy into /etc/systemd/system, then: $ROOT_STEPS"
fi

# 8. optional reverse proxy -----------------------------------------------
case "$PROXY" in
  caddy) run sudo -n apt-get install -y -qq caddy
         run bash -c "sed 's|__DOMAIN__|$DOMAIN|' '$REPO/deploy/Caddyfile.example' | sudo -n tee /etc/caddy/Caddyfile >/dev/null"
         run sudo -n systemctl reload caddy;;
  nginx) run sudo -n apt-get install -y -qq nginx certbot python3-certbot-nginx
         run bash -c "sed 's|__DOMAIN__|$DOMAIN|' '$REPO/deploy/nginx.conf.example' | sudo -n tee /etc/nginx/sites-available/word-dance >/dev/null"
         run sudo -n ln -sf /etc/nginx/sites-available/word-dance /etc/nginx/sites-enabled/word-dance
         run bash -c "sudo -n nginx -t && sudo -n systemctl reload nginx"
         run sudo -n certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "${WD_CONTACT_EMAIL:-admin@$DOMAIN}" || echo "WARN: certbot failed; re-run manually";;
esac

# 9. health (skipped under --dry-run) --------------------------------------
if [ "$DRY" = 1 ]; then log "dry run complete — nothing was changed"; exit 0; fi
log "health"
for i in $(seq 1 30); do curl -fsS "http://127.0.0.1:${WD_PORT:-8000}/api/health" >/dev/null 2>&1 && break; sleep 1; done
curl -fsS "http://127.0.0.1:${WD_PORT:-8000}/api/health"; echo
if [ "$STALE" = 1 ]; then echo "health OK, but the OLD process answered — the new version is not running yet; run: sudo systemctl restart word-dance";
elif [ -n "${WD_PUBLIC_URL:-}" ]; then echo "word-Dance is running at $WD_PUBLIC_URL";
else echo "word-Dance is running at http://${LAN_IP:-$(hostname -I | awk '{print $1}')}:${WD_PORT:-8000}  (bind ${WD_HOST:-0.0.0.0})"; fi
echo "registration mode: ${WD_REGISTRATION_MODE:-invite} — the first account registered becomes admin; afterwards create invite codes with: $REPO/.venv/bin/wd invite --uses 5 --days 7"
```

Behaviour: re-running after `git pull` upgrades dependencies, builds the frontend into a new snapshot `$DATA/frontend-releases/<sha>.new` (step 4 — never `<repo>/frontend/dist`), **stops the running unit** (unless `--no-restart`), publishes the snapshot (step 6: `<sha>.new` → `<sha>`, then the `frontend` symlink is replaced with one atomic `mv -T` — its target is the relative `frontend-releases/<sha>`, so a moved data dir keeps working — and all but the two newest snapshots are pruned), applies new migrations (with a pre-migrate snapshot), starts the unit again, and never touches `.env` (apart from filling an empty `WD_PUBLIC_URL` with the LAN URL on a proxy-less install, and an empty or missing `WD_FRONTEND_DIST` with `$DATA/frontend`, §4), the DB or images. The publish comes after the stop so the old process never serves a half-written tree; with `--no-restart` or without passwordless sudo the swap still happens and the old process keeps serving the snapshot it resolved at startup until it is restarted — a build in the checkout (`make test`, `npm run build`) writes `frontend/dist`, which the installed service no longer reads (§10). The preflight refuses a `$DATA/frontend` that is a real directory rather than a symlink. `.env` is validated before it is sourced: every line must be `KEY="value"` (§4). **Data directory** (step 0, read-only, so it also runs under `--dry-run`): `WD_DATA_DIR` when set; otherwise the directory named by the `EnvironmentFile=<dir>/.env` line of the installed unit (`/etc/systemd/system/word-dance.service`; `WD_UNIT_FILE` overrides that path so the tests stay hermetic), printed as `data dir from the installed unit: …`; otherwise `/home/sqin/word-dance-data`. So an upgrade after the ops.md §5 move needs no variable, and a plain run can no longer create a fresh, empty instance at the default path and re-point the unit at it. A `WD_DATA_DIR` that **differs** from the installed unit's directory is refused — `ERROR: WD_DATA_DIR=… but the installed unit (…) uses …`, exit 2 before step 1, nothing planned or changed — unless `--move-data` is given: that is the move itself (ops.md §5), the script prints `WARN: --move-data: …` and step 7 re-renders both units with the new `EnvironmentFile=`. The running-unit probe (`systemctl is-active`) needs no privilege, so it also runs without passwordless `sudo -n`: the unit is then neither stopped nor restarted, the script prints the additive-only NOTE plus `WARN: no passwordless sudo — the OLD version keeps serving …`, the step-7 fallback says `systemctl restart word-dance` (not `enable --now`, a no-op on an active unit), and step 9 ends with `health OK, but the OLD process answered — … run: sudo systemctl restart word-dance` instead of the success line. Under `--dry-run` on a fresh box the `WD_PUBLIC_URL` branch reads `deploy/env.example` (the file step 5 would have copied) so the planned `sed -i` is printed and nothing is read from the absent `.env`.

`deploy/fetch_ecdict.sh <DATA>` (optional, `--with-ecdict`): downloads `https://github.com/skywind3000/ECDICT/releases/download/1.0.28/ecdict-sqlite-28.zip` (216 MB) with `curl -fL --retry 3 -o "$DATA/tmp/ecdict-sqlite-28.zip"`, verifies `sha256sum` against the pinned `ECDICT_SHA256=ea01f76a3b3351021ce47077e89234465cc9441c8793054495320d06c0c3f3f6` (computed from the verified release asset on this box; mismatch → delete + exit 1), extracts with the **stdlib** `python3 -m zipfile -e "$DATA/tmp/ecdict-sqlite-28.zip" "$DATA/tmp/ecdict"` (the zip's single member is `stardict.db`, 851 MB; no `unzip` binary exists on the box — FACTS §1), moves it to `$DATA/stardict.db` (0600), removes the zip, and writes `WD_ECDICT_DB_PATH="$DATA/stardict.db"` into `.env` (quoted). Idempotent: exits 0 at once when `$DATA/stardict.db` already exists. Needs ≈ 1.1 GB free in `$DATA` during extraction (checked first). Options are parsed by a `while` loop, so they combine in any order (`--with-ecdict --with-caddy DOMAIN --no-restart`). `--dry-run` routes every mutating step through `run()`, which prints `+ <command>` instead of executing it, and exits before the health check — so `deploy/install.sh --dry-run` is safe on a fresh box (WP9 acceptance). `WD_CONTACT_EMAIL` comes from the environment, `--contact-email`, or an interactive prompt when `.env` is first created (falls back to `admin@localhost`). The printed URL is consistent with the bind: default `WD_HOST=0.0.0.0` → LAN URL; with a proxy → `127.0.0.1` + the https URL.

## 3. systemd units (`deploy/`)

```ini
# deploy/word-dance.service  (rendered: __USER__=sqin, __REPO__=/home/sqin/word-Dance, __DATA__=/home/sqin/word-dance-data)
[Unit]
Description=word-Dance vocabulary service (API + web + scheduler + workers)
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=300
StartLimitBurst=10

[Service]
Type=simple
User=__USER__
# no Group=: systemd uses the user's primary group (a group named after the user need not exist — status 216/GROUP otherwise)
WorkingDirectory=__REPO__
EnvironmentFile=__DATA__/.env
Environment=HOME=/home/__USER__
Environment=PATH=/home/__USER__/.local/bin:/usr/local/bin:/usr/bin:/bin
Environment=PYTHONUNBUFFERED=1 LANG=C.UTF-8
ExecStart=__REPO__/.venv/bin/wd serve
Restart=on-failure
RestartSec=5
TimeoutStopSec=300
KillMode=mixed
UMask=0077
LimitNOFILE=8192
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=full
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
LockPersonality=yes
# Deliberately NOT set: ProtectHome / ProtectSystem=strict — the claude CLI must read and write
# /home/sqin/.claude and /home/sqin/.claude.json (OAuth credentials, FACTS §3), and the data dir lives under /home.
StandardOutput=journal
StandardError=journal
SyslogIdentifier=word-dance

[Install]
WantedBy=multi-user.target
```

* `TimeoutStopSec=300` ≥ the longest Claude timeout (240 s consolidate) + grace: a restart lets an in-flight call finish; `KillMode=mixed` then kills the remaining process group.
* `wd serve` = `uvicorn.run("wd.main:create_app", factory=True, host=WD_HOST, port=WD_PORT, workers=1, limit_concurrency=200, proxy_headers=WD_TRUST_PROXY, forwarded_allow_ips="127.0.0.1", log_config=None, access_log=False)` — `access_log=False` because the middleware writes the one JSON line per request (§6); `cli.py` also calls `os.umask(0o077)` before serving (§1); `main.py` refuses `workers != 1` and takes the `kv.worker_lease` (a second `wd serve` idles with a warning and keeps retrying the lease every 30 s, so a service restarted after a crash — whose predecessor could not release its 90-s lease — takes over and resumes pushing within ≈ 2 min).

```ini
# deploy/word-dance-backup.service
[Unit]
Description=word-Dance nightly backup (VACUUM INTO + integrity_check + gzip)
[Service]
Type=oneshot
User=__USER__
EnvironmentFile=__DATA__/.env
Environment=HOME=/home/__USER__
UMask=0077
ExecStart=__REPO__/.venv/bin/wd backup --keep-daily 14 --keep-weekly 8
```

```ini
# deploy/word-dance-backup.timer
[Unit]
Description=word-Dance nightly backup timer
[Timer]
OnCalendar=*-*-* 03:30:00 Asia/Shanghai
Persistent=true
RandomizedDelaySec=10m
[Install]
WantedBy=timers.target
```

The timer is independent of the app process (a wedged service still gets backed up). `systemd-analyze verify deploy/*.service` must pass (WP9 acceptance).

## 4. Configuration — `/home/sqin/word-dance-data/.env` (`deploy/env.example`, prefix `WD_`)

| Variable | Default | Notes |
|---|---|---|
| `WD_DATA_DIR` | `/home/sqin/word-dance-data` | 0700 |
| `WD_DB_PATH` | `$WD_DATA_DIR/word-dance.db` | |
| `WD_HOST` / `WD_PORT` | `0.0.0.0` / `8000` | `127.0.0.1` behind a proxy (set by `--with-caddy/--with-nginx`) |
| `WD_PUBLIC_URL` | (empty; install.sh writes `http://<first LAN IP>:<WD_PORT>` when no proxy is configured, `https://<domain>` with one) | accepted as an Origin for the CSRF check (next to the request's own Host-derived origin, API.md §1); cookie `Secure` when https; **the base of e-mail/webhook links** — delivery runs in the scheduler without a request, so nothing can be derived from `Host` there: when empty the app falls back to `kv.public_url_guess` (first non-loopback IPv4 + `WD_PORT`, computed at startup) and otherwise omits the link (DESIGN §6.5) |
| `WD_SEED_PATH` | `<repo>/data/seed/vocab.jsonl.gz` (= `Path(wd.__file__).parents[2] / 'data/seed/vocab.jsonl.gz'`) | the shipped seed; default of `wd import-seed --file` and of the lifespan seed check (`kv.seed_version` vs the content sha256 of the (gunzipped) file, so re-packing the same records with another gzip does not re-import). Correct for the editable install install.sh performs; a non-editable install must set it |
| `WD_FRONTEND_DIST` | (empty = `<repo>/frontend/dist` (= `Path(wd.__file__).parents[2] / 'frontend/dist'`), the dev build; install.sh fills `$WD_DATA_DIR/frontend`, the symlink to the `frontend-releases/<sha>` snapshot it publishes, when the value is empty or the key is missing — a non-empty value is left alone, §1/§2) | the built SPA served by the catch-all route (`/assets/*` immutable, `index.html` `no-cache`, a 503 「前端尚未构建」 page naming the path while it is missing — also a startup warning); resolved at startup, so a later symlink swap is picked up at the next restart (§10); tests point it at a temporary directory (`conftest.py`) |
| `WD_TRUST_PROXY` | `0` | honour `X-Forwarded-For` / `X-Forwarded-Proto` from the local proxy (uvicorn `forwarded_allow_ips=127.0.0.1`): the client IP is the hop the proxy **appended** (nginx `$proxy_add_x_forwarded_for` / Caddy), never the client-supplied first hop |
| `WD_COOKIE_SECURE` | `auto` | `1` forces `Secure`; `auto` = https `WD_PUBLIC_URL` |
| `WD_DEV` | `0` | `1`: OpenAPI docs at `/api/docs`, `http://localhost:5173` origin allowed, `POST /api/admin/jobs/run-once` |
| `WD_SECRET_KEY` | generated by install.sh | HMAC key for `email_codes.code_hash` (6-digit codes must not be brute-forceable from a DB dump; SCHEMA.sql); must be non-empty; rotating it only invalidates unexpired e-mail codes |
| `WD_TZ` | `Asia/Shanghai` | **operational timezone**: AI budget day, maintenance 03:30, admin views (user pushes use each user's own timezone) |
| `WD_REGISTRATION_MODE` | `invite` | `open` / `invite` / `closed` |
| `WD_SESSION_DAYS` | `30` | |
| `WD_MAX_BODY_BYTES` | `1048576` | |
| `WD_WORKER_ENABLED` | `1` | `0` in tests |
| `WD_TICK_SECONDS` / `WD_PREBUILD_HOURS` | `60` / `3` | scheduler |
| `WD_CONTACT_EMAIL` | (empty → `admin@localhost`) | in the Wikimedia User-Agent; set by `install.sh` from `--contact-email`, the environment, or an interactive prompt when `.env` is first created |
| `WD_CLAUDE_BIN` | `/home/sqin/.local/bin/claude` | absolute path set by install.sh; a relative path containing `/` (such as `backend/tests/fake_claude.py` from the repository root) is made absolute against the start-up working directory, because the CLI is spawned in `WD_CLAUDE_CWD`; a bare name is looked up on `WD_CLAUDE_PATH` |
| `WD_CLAUDE_HOME` / `WD_CLAUDE_PATH` / `WD_CLAUDE_CWD` | `$HOME` / `/home/sqin/.local/bin:/usr/local/bin:/usr/bin:/bin` / `$WD_DATA_DIR/claude-cwd` | child environment (CLAUDE_INTEGRATION.md §1.3) |
| `WD_AI_ENABLED` | `1` | kill switch |
| `WD_AI_MODEL` / `WD_AI_CLI_FALLBACK_MODEL` / `WD_AI_EXTRA_ARGS` | `sonnet` / (empty) / (empty) | `WD_AI_CLI_FALLBACK_MODEL` is the CLI's own `--fallback-model` (Claude ↔ Claude, off when empty) — it was named `WD_AI_FALLBACK_MODEL` before migration 0010; that key now names the fallback *provider's* model (below) and a non-empty value with `WD_AI_FALLBACK_KIND=none` refuses to start with a hint naming the move |
| `WD_AI_BATCH_SIZE` / `WD_AI_CONCURRENCY` | `10` / `1` | **1–12** (clamped in `config.py`: `content_v1.json` has `items.maxItems: 12`, CLAUDE_INTEGRATION §4) — words per `generate_content` call on the CLI; while the fallback provider takes the group the effective size is `min(WD_AI_BATCH_SIZE, WD_AI_FALLBACK_BATCH_SIZE)` (below) / 1–3 |
| `WD_AI_TIMEOUT_CONTENT_SEC` / `_LOOKUP_SEC` / `_CONSOLIDATE_SEC` / `_SVG_SEC` | `180` / `120` / `240` / `120` | |
| `WD_AI_BUDGET_CONTENT` / `_LOOKUP` / `_CONSOLIDATE` / `_SVG` | `0.25` / `0.15` / `0.40` / `0.10` | `--max-budget-usd` per call |
| `WD_AI_DAILY_BUDGET_USD` / `WD_AI_MONTHLY_BUDGET_USD` | `3.00` / `40.00` | measured $0.004/word → ≈ 750 words/day |
| `WD_AI_PREWARM_DAILY_BUDGET_USD` / `WD_AI_HOURLY_CALL_CAP` | `1.00` / `60` | |
| `WD_AI_SVG_DAILY_BUDGET_USD` | `0.50` | daily sub-cap for Claude-drawn SVG concept cards (≈ 35–40 cards/day at the measured $0.0124/call — $0.0140 per delivered card, 2026-11-05), counted inside the daily cap; `0` disables SVG generation without turning the feature off (CLAUDE_INTEGRATION §7) |
| `WD_AI_LOG_KEEP_DAYS` | `14` | raw CLI logs (the fallback's raw responses land there too) |
| `WD_AI_PROVIDER` | `claude_cli` | which provider serves the AI calls (docs/AI_FALLBACK_MODEL.md §4, CLAUDE_INTEGRATION §10): `claude_cli` = the CLI only (today's behaviour) · `openai_http` = the fallback HTTP provider only (the CLI is never spawned) · `auto` = the CLI with automatic failover to the fallback and fail-back by probe. `openai_http` and `auto` refuse to start unless the fallback is fully configured (kind, base URL, model and a key). In `openai_http` mode **only the kinds in `WD_AI_FALLBACK_KINDS` ever run**: with the default list (`content,lookup,consolidate`) only `generate_svg` jobs — which the fallback never serves — and prewarm `generate_content` groups (priority ≥ 90, unless `WD_AI_FALLBACK_PREWARM=1`) wait indefinitely (re-deferred every 30 min; a `prewarm_plan` started before the switch keeps fanning such groups out — finish or cancel it first, or set the flag); a kind removed from the list waits the same way — without `content` every `generate_content` job waits and learners get dictionary data only — and the service then starts with a warning naming only the removed kinds (the prewarm gate is not part of it), not an error (CLAUDE_INTEGRATION §10.1) |
| `WD_AI_FALLBACK_KIND` / `_BASE_URL` / `_API_KEY` / `_API_KEY_FILE` / `_MODEL` | `none` / (empty) / (empty) / (empty) / (empty) | the fallback provider: kind `openai_http` = an OpenAI-format `POST {base}/chat/completions` endpoint (Zhipu `https://open.bigmodel.cn/api/paas/v4`, Alibaba Bailian `https://dashscope.aliyuncs.com/compatible-mode/v1`, DeepSeek, …; a trailing `/` is stripped; it must start with `http://` or `https://` and name a host — `ConfigError` otherwise, since a scheme-less value would fail every call as a soft `network:` error instead of refusing to start — and plain `http://` to a host other than loopback starts with a warning that the key travels in cleartext), the bearer key (masked by `GET /api/admin/config` — prefer the 0600 key **file**, whose first line is read at call time; the file must exist and be a readable regular file at startup, `ConfigError` naming the path otherwise, and a group/other-readable mode logs a warning) and the vendor model id (e.g. `glm-4.7-flash`). `WD_AI_FALLBACK_MODEL` was the CLI's `--fallback-model` before migration 0010 — that setting is now `WD_AI_CLI_FALLBACK_MODEL` above |
| `WD_AI_FALLBACK_DIALECT` / `_JSON_MODE` / `_THINKING` | `auto` / `auto` / `off` | request shape (CLAUDE_INTEGRATION §10.2): dialect `auto` is derived from the host (`zhipu` / `bailian` / `deepseek` / `generic`); JSON mode `auto` = `json_object` with the schema in the system prompt, except `json_schema` (a strict copy of the schema) for Bailian; thinking `off` sends the vendor's disable-thinking field, `on` enables it, `default` sends nothing |
| `WD_AI_FALLBACK_TIMEOUT_SCALE` / `_MAX_OUTPUT_TOKENS` / `_HOURLY_CALL_CAP` | `1.5` / `0` / `40` | the kind's timeout × scale (0.5–5.0; free-tier models are slower); `max_tokens` override (0 = the adapter's per-kind table: content 8192, lookup 8192, consolidate 12288, svg 4096, probe 512); the fallback's own hourly call cap, counted over its own `ai_calls.provider='fallback'` rows (the CLI keeps `WD_AI_HOURLY_CALL_CAP`) |
| `WD_AI_FALLBACK_BATCH_SIZE` | `5` | **1–12** (clamped with a warning, like `WD_AI_BATCH_SIZE`; a non-integer refuses to start): words per `generate_content` call while the fallback takes the group — the effective size is `min(WD_AI_BATCH_SIZE, WD_AI_FALLBACK_BATCH_SIZE)`. The worker already claims content in groups of that size when the fallback would take the head group (`failover.claim_limit`), and a larger group claimed for the CLI is regrouped before it reruns on the fallback (the claim's attempt is given back; CLAUDE_INTEGRATION §10.5); the dead jobs a fail-back revives carry no `group_size` mark, so they batch the same way (§10.6). Lookup groups stay ≤ 20 and consolidate 1 on either provider |
| `WD_AI_FALLBACK_KINDS` / `_PREWARM` | `content,lookup,consolidate` / `0` | the job kinds the fallback may serve — a comma list out of `content`, `lookup`, `consolidate` (`svg` never; remove `content` to keep example generation on the CLI only — the AI_FALLBACK_MODEL §5 eval is still recommended, it just no longer gates the default; an empty or blank value — `""`, `" "`, `","` — means the default) — and whether priority-≥ 90 prewarm groups may use it (`0`: prewarm content waits for the CLI even while ordinary content runs on the fallback — a claim that mixed both is split and the runnable prewarm backlog parked until the CLI pause ends, CLAUDE_INTEGRATION §10.4; in mode `openai_http`, where the CLI is never spawned, that means indefinitely: `POST /api/admin/content/prewarm` refuses new plans there, but the priority-90 jobs of a plan started before the switch stay queued until the mode changes or `_PREWARM=1`). In mode `auto` a kind outside the list stays on the CLI (and waits while the CLI is paused); in mode `openai_http` it never runs — see `WD_AI_PROVIDER` |
| `WD_AI_FALLBACK_PRICE_JSON` / `WD_AI_CNY_PER_USD` | (empty = free) / `7.2` | the fallback's price in CNY per million tokens as a JSON object, e.g. `{"input": 0.2, "output": 0.8, "cache_read": 0.04}` (single-quoted in `.env` because of the double quotes; the names are exactly `input` and `output` — both required when the object is not empty — plus an optional `cache_read`, anything else is a `ConfigError` because a mis-keyed table would record `cost_usd` 0 for a paid leg; empty or `{}` = the free tier), and the CNY → USD rate; the fallback's `cost_usd` is recorded post hoc from it and counted inside the daily / monthly caps (its reservation is 0, CLAUDE_INTEGRATION §7) |
| `WD_AI_FAILOVER_COOLDOWN_MIN` / `_PROBE_EVERY_MIN` | `30` / `30` | minutes (1–1440): the pause applied to a provider after a hard failure (auth, spawn_error, 403 — a balance failure pauses 24 h, a quota window until its reset; in **every** mode) and after the fallback's third consecutive invalid answer (the quality pause, CLAUDE_INTEGRATION §10.4 — in `auto` and `openai_http` alike, retries of the same group included; tagged `kv.ai.fallback.pause_reason='quality'`): a success of that provider, a call or a probe, or the admin's resume lifts a hard-failure pause early and releases the jobs parked at it, while the quality pause is lifted only by a fallback probe, an applied fallback group or the resume — an ordinary HTTP-ok answer may still be rejected by the handler (§10.4–§10.6); and the interval of the CLI fail-back probe while the fallback is active (one attempt pinned to the recorded flag tier; doubled after 12 failed probes) |
| `WD_AI_FAILOVER_OVERLOADED_AFTER` / `_TIMEOUT_AFTER` / `_NETWORK_AFTER` | `3` / `2` / `2` | soft triggers of mode `auto` (1–100): consecutive overloaded / timeout / network failures of the CLI after which the group reruns on the fallback (the 6-streak 15-min overload pause of CLAUDE_INTEGRATION §6.3 stays) |
| `WD_ECDICT_DB_PATH` | (empty) | optional full `stardict.db` (851 MB) for instant lookups of words outside the seed |
| `WD_IMAGES_ENABLED` | `1` | |
| `WD_IMAGE_PROVIDERS` | `wikimedia,openverse` | ordered chain; `pixabay`/`pexels` appended when keys exist |
| `WD_IMAGE_KID_STAGES` | (empty) | stage codes whose words get the child style and the illustration-first round (empty = off; the live instance sets `xs` since 2026-11-06 — the 小学 cards are drawn in the child style, so put that line into every new deployment's `.env`; `zk` is never in the default): a comma list out of `xs`, `zk`, `gk`, `cet4`, `cet6` (an unknown code refuses to start). Read by `images.style.style_for` from the word's `stage_min`: a listed stage gets the `kid` Style line of the Claude SVG prompt (CLAUDE_INTEGRATION §5.5) and the illustration-first provider round; every other word stays `neutral` |
| `WD_SVG_VIA_CLAUDE` | `1` | Claude-drawn SVG concept card when no acceptable photo is found, for words a user actually studies (never prewarm), budgeted by `WD_AI_SVG_DAILY_BUDGET_USD`; the text-only template card is the final fallback. `0` = photos or the template card only (then 配图 is satisfied only when a photo is found — the admin overview shows the `card_only` share) |
| `WD_IMAGE_MAX_BYTES` / `WD_IMAGE_MAX_EDGE` | `8000000` / `800` | |
| `WD_WIKIMEDIA_MIN_INTERVAL_MS` / `WD_WIKIMEDIA_DAILY_LIMIT` | `1000` / `2000` | politeness |
| `WD_OPENVERSE_MINUTE_LIMIT` / `WD_OPENVERSE_DAILY_LIMIT` | `15` / `160` | anonymous limits are 20/min, 200/day |
| `WD_OPENVERSE_CLIENT_ID` / `WD_OPENVERSE_CLIENT_SECRET` | (empty) | optional registered app (raises limits) |
| `WD_PIXABAY_KEY` / `WD_PEXELS_KEY` | (empty) | optional providers |
| `WD_SMTP_HOST` / `WD_SMTP_PORT` / `WD_SMTP_USER` / `WD_SMTP_PASSWORD` / `WD_SMTP_FROM` / `WD_SMTP_TLS` | (empty) / `587` / … / `starttls` | e-mail channel enabled when host + from are set (`starttls` / `ssl` / `none`) |
| `WD_LOG_LEVEL` / `WD_LOG_FORMAT` / `WD_LOG_FILE` | `INFO` / `json` / (empty) | |
| `WD_BACKUP_KEEP_DAILY` / `WD_BACKUP_KEEP_WEEKLY` | `14` / `8` | |
| `WD_ADMIN_USERNAME` / `WD_ADMIN_PASSWORD` | (empty) | unattended `wd create-admin --if-none` — the only command that reads them (`set-password` prompts, or takes an explicit `--password-env VAR`); remove the password afterwards |
| `WD_DEV_REAL_CLAUDE` | `0` | dev only (`scripts/dev.sh`): `1` uses the real CLI instead of `tests/fake_claude.py` |
| `WD_SMOKE_MOCK_HTTP` | `0` | tests/smoke only: `1` (together with `WD_DEV=1`, otherwise ignored) routes every outbound `httpx` request (image providers, downloads, webhooks) through the `wd.smoke_mock` `httpx.MockTransport` fixtures and pins the SSRF DNS step — installed by `create_app` for `wd serve` **and** by `wd.cli.main` for every other `wd` command, so the `wd worker-once` / `wd tick --once` / `wd fetch-image` subprocesses `make smoke` spawns are mocked too (nothing leaves the box) |

Secrets never leave `.env`; `GET /api/admin/config` masks them.

**Quoting rule for `.env` (binding, stated at the top of `deploy/env.example`)**: the same file is read by three parsers — bash (`set -a; . .env` in install.sh), systemd `EnvironmentFile=` and python-dotenv (dev/tests) — whose unquoted-value rules differ (bash would *execute* `low` for `WD_AI_EXTRA_ARGS=--effort low`). Therefore every value is written **double-quoted**, `KEY="value"`, which all three accept identically for ordinary values (`WD_AI_EXTRA_ARGS="--effort low"`); a value containing `"` (`WD_AI_FALLBACK_PRICE_JSON`) or a secret containing `$`, `` ` `` or `\` is written **single-quoted** (`WD_SMTP_PASSWORD='p$ss'`), literal in all three parsers; `#` starts a comment only at the beginning of a line. install.sh runs `bash -n` plus a line-shape check (`^WD_[A-Z0-9_]+=("[^"$`\\]*"|'[^']*')$`) before sourcing and aborts with the offending line(s). `env.example` ships every variable of this table in that form with its default.

## 5. Backups and restore (`backend/wd/backup.py` owns CLI `wd backup|restore` and the `snapshot_before_migrate` hook; `wd migrate` itself lives in `cli.py`, TASKS P0)

* `wd backup --keep-daily N --keep-weekly M`: `VACUUM INTO '$DATA/tmp/word-dance-<ts>.db'` (consistent online snapshot under WAL) → `PRAGMA integrity_check` on the copy (abort + `system_events('backup_failed')` + non-zero exit if not `ok`) → gzip → `$DATA/backups/word-dance-YYYYMMDD-HHMM.db.gz` (0600) → retention: newest N daily + Sunday copies up to M weekly → `kv.backup.last = {file, at, bytes}` (shown in admin health). Images are re-fetchable and not backed up by default; `--with-images` adds `images-YYYYMMDD.tar`. The same flags are used everywhere (timer unit, DESIGN §11, WP9 acceptance).
* `wd migrate [--dry-run]` (`cli.py` → `db.run_migrations(conn, pre_hook=wd.backup.snapshot_before_migrate)`, the hook late-imported and skipped with a warning if `backup.py` is absent during Phase 0): pending = `backend/wd/migrations/NNNN_*.sql` whose `NNNN` is not in `schema_migrations`; before applying the first pending file it writes `backups/pre-migrate-<from>-to-<to>.db.gz` (same pipeline); each file then runs inside one `BEGIN IMMEDIATE` transaction and **the runner inserts `schema_migrations(version, name)` in that same transaction** — migration files never self-register (SCHEMA.sql §1/§10), so a fresh install cannot hit a duplicate-key crash and a half-applied file rolls back together with its bookkeeping row. This atomicity holds only because `db.connect()` opens the connection with `sqlite3.connect(path, autocommit=True)` (Python 3.12) and the runner issues `BEGIN IMMEDIATE`/`COMMIT`/`ROLLBACK` explicitly — in the legacy default mode `conn.executescript()` commits implicitly before running the file (verified on this box), silently ending the transaction (TASKS P0 step 4 + its unit test). The runner also owns foreign-key enforcement around each file: `PRAGMA foreign_keys=OFF` *before* the `BEGIN` (inside a transaction the PRAGMA is a silent no-op), `PRAGMA foreign_key_check` before the bookkeeping row (a file that leaves orphans is rolled back with a `MigrationError` naming them), `PRAGMA foreign_keys=ON` again afterwards — so the SQLite table rebuild a CHECK-list change needs (create new → copy → `DROP` old → `RENAME`) does not cascade-delete the children of the dropped parent table (SCHEMA.sql §1; migration files never toggle `PRAGMA foreign_keys` themselves and must delete child rows explicitly when they delete parents). `--dry-run` lists pending files only. install.sh stops the running unit before `wd migrate` (unless `--no-restart`, §2/§10). Which files are safe while the service runs is a property of each file: `0011_primary_stage.sql` (the 小学 stage: `words` / `user_settings` are rebuilt) and `0013_word_forms_alias.sql` (`word_forms` rebuilt) are **stop-first** — never under `--no-restart`, and the pre-migrate snapshot is the only rollback (`wd restore backups/pre-migrate-<from>-to-<to>.db.gz`, code and database roll back together); `0012_word_images_meta.sql` (four `ADD COLUMN`s on `word_images`) and `0014_learn_rank.sql` (one `ADD COLUMN` on `words`, filled by the service start / `wd learn-order`) are additive. Rehearse on a copy first (`cp` the database to a private directory, `WD_DATA_DIR=<copy> wd migrate --dry-run && wd migrate`).
* `wd restore <file.db.gz> [--yes]`: refuses while the service runs (checks `kv.worker_lease` expiry and `systemctl is-active`); gunzips to `word-dance.db.restore-<ts>` **next to the target** (never into `tmp/`: `WD_DB_PATH` may be on another filesystem and the final rename must not cross devices) and runs `integrity_check` first; runs `PRAGMA wal_checkpoint(TRUNCATE)` on the current DB and **refuses (exit 2) when SQLite reports it blocked** (`busy` / frames not folded in — another connection holds an open transaction, and the `.bak` would otherwise silently lose the newest commits); keeps the current DB as `word-dance.db.bak-<ts>` (hard link; a copy where links are unsupported), moves its `-wal`/`-shm` next to that name (`.bak-<ts>-wal`/`-shm`, recovered by SQLite when the `.bak` is opened — complete even when the checkpoint failed on a damaged file), then swaps the verified copy in with **one atomic `os.replace`** — the database path is never absent and a failed swap leaves the current DB untouched (exit 1); sets 0600, prints `sudo systemctl start word-dance`.
* Off-box copies: `rsync -a --delete /home/sqin/word-dance-data/backups/ user@host:/backups/word-dance/` from any cron on another machine (documented in `docs/ops.md`).
* Monthly drill (ops.md): restore into `$DATA/tmp` and run `wd check --db <path>`.

## 6. Logs

JSON lines to stdout → journald: `journalctl -u word-dance -f`, `--since today`, `-p warning`. Fields: `ts level logger msg request_id user_id method path status duration_ms job_id job_type worker cost_usd provider event`. One line per request at INFO (health checks at DEBUG); bodies never logged; prompts only at DEBUG (word lists). Optional `WD_LOG_FILE` adds a `RotatingFileHandler(50 MB × 5)`. Raw `claude` output under `claude-logs/` for 14 days (pruned by maintenance). `wd logs --tail N` prints the tail of `WD_LOG_FILE` when that is configured; the 2000-line in-memory ring buffer it reads first exists only inside the `wd serve` process (and tests), so from a shell on the box the last N lines of the service are `journalctl -u word-dance -n N -o cat` — without a log file, `wd logs` prints exactly that hint and exits 0.

## 7. Reverse proxy and HTTPS (optional)

LAN/intranet: default `WD_HOST=0.0.0.0:8000`, no proxy, cookies not `Secure`. Public domain: `--with-caddy DOMAIN` (recommended) or `--with-nginx DOMAIN`.

```
# deploy/Caddyfile.example
__DOMAIN__ {
    encode zstd gzip
    request_body { max_size 2MB }
    reverse_proxy 127.0.0.1:8000
}
```

```nginx
# deploy/nginx.conf.example
server { listen 80; server_name __DOMAIN__; location /.well-known/acme-challenge/ { root /var/www/html; } location / { return 301 https://$host$request_uri; } }
server {
    listen 443 ssl http2; server_name __DOMAIN__;
    ssl_certificate /etc/letsencrypt/live/__DOMAIN__/fullchain.pem; ssl_certificate_key /etc/letsencrypt/live/__DOMAIN__/privkey.pem;
    client_max_body_size 2m; gzip on; gzip_types application/json text/css application/javascript image/svg+xml;
    location /assets/ { proxy_pass http://127.0.0.1:8000; expires 1y; add_header Cache-Control "public, immutable"; }
    location / { proxy_pass http://127.0.0.1:8000; proxy_http_version 1.1; proxy_set_header Host $host;
                 proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for; proxy_set_header X-Forwarded-Proto $scheme; proxy_read_timeout 60s; }
}
```

The app itself sets CSP/HSTS/nosniff/Referrer-Policy/frame-ancestors (DESIGN §10); with `WD_TRUST_PROXY=1` the client IP is the `X-Forwarded-For` hop the trusted proxy appended (the right-most one not in `forwarded_allow_ips`, resolved by uvicorn's proxy middleware — never the first hop, which the client itself controls) and `X-Forwarded-Proto=https` makes cookies `Secure`.

## 8. Development workflow

```
make setup   # python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt -r backend/requirements-dev.txt -e backend && (cd frontend && npm ci)
make dev     # scripts/dev.sh: WD_DEV=1 WD_DATA_DIR=./.dev-data WD_REGISTRATION_MODE=open WD_CLAUDE_BIN=./backend/tests/fake_claude.py \
             #   .venv/bin/uvicorn wd.main:create_app --factory --reload --port 8000  &  (cd frontend && npm run dev)   # vite :5173 proxies /api,/media
             #   set WD_DEV_REAL_CLAUDE=1 to use the real CLI while developing (spends money)
make test    # .venv/bin/pytest -q backend/tests && (cd frontend && npm run typecheck && npm test && npm run build)
make smoke   # scripts/smoke.py: throwaway data dir, port 8010, fake claude, mocked image providers (WD_SMOKE_MOCK_HTTP=1 + WD_DEV=1,
             #   honoured by `wd serve` and by the `wd worker-once` / `wd tick --once` subprocesses the script spawns), registration open
make seed    # prev=$(git show $(SEED_BASE):data/seed/vocab.jsonl.gz) — SEED_BASE defaults to HEAD: the baseline is always the COMMITTED seed, never the working-tree .gz that pack_seed.sh rewrites (data/lists/README.md §5)
             #   → .venv/bin/python -I scripts/build_seed.py --manifest data/lists/manifest.json --previous $prev [--ecdict $(ECDICT_DB)] [--wordlists $(WORDLISTS_DIR)] --out data/seed
             #   → scripts/seed_diff.py $prev data/seed/vocab.jsonl (data/seed/DIFF.md + invariants) → scripts/pack_seed.sh (vocab.jsonl.gz, stats.json content_sha256); only when regenerating.
             #   ECDICT_DB=<stardict.db> is needed only when the official lists bring new headwords; WORDLISTS_DIR (the optional CET lists) may be absent; SEED_BASE=<rev> rebuilds against another committed seed
make install # deploy/install.sh
```

Vite binds `localhost` only (`::1` on this box — `vite.config.ts` sets no `server.host`): open `http://localhost:5173`, not `127.0.0.1:5173`. A phone on the LAN cannot reach it; for the 360-px checks run `cd frontend && npm run dev -- --host` (the proxy keeps the browser's Host header, so the backend's Host-derived CSRF origin still matches) or use the built SPA of the installed service on `http://<LAN-ip>:8000` (`qa-frontend.md`).

`WD_DEV=1` relaxes nothing security-relevant except the dev origin and the docs route. The seed build inputs (ECDICT `stardict.db` 851 MB, mahavivo lists) are **not** needed at deploy time; `data/seed/vocab.jsonl.gz` ships in the repo.

## 9. CLI reference (`wd …`, console script from `backend/pyproject.toml`; owning module in brackets — `cli.py` calls `register_cli(sub)` on each module of `CLI_MODULES`, TASKS P0 step 4)

`serve` · `migrate [--dry-run]` · `version` [`wd.cli` itself] · `import-seed [--file PATH (default: WD_SEED_PATH)] [--force] [--dry-run] [--report PATH]` (`--dry-run` writes nothing and prints the plan — inserts / updates / unchanged, orphans, stage-flag changes, the stage_min matrix, unknown stage codes; `--report PATH` saves it as JSON; a database with no schema yet or with pending migrations gets one line — `run wd migrate first` — and exit 1, so the import never runs ahead of the schema, §10) [`wd.seed`, WP1] · `create-admin [--if-none] [--username U] [--password-env VAR]` (the only command that falls back to `WD_ADMIN_PASSWORD`) · `set-password <username> [--password-env VAR]` (prompts twice; never reads `WD_ADMIN_PASSWORD` implicitly — the variable is required when stdin is not a terminal) · `promote|demote <username>` · `invite [--uses N] [--days D] [--note …]` (prints the code once) [`wd.security`, WP2] · `claude-check` · `ai-check [--provider claude|fallback]` (one probe round — CLI: tier 1 then tier 0 as in CLAUDE_INTEGRATION §2, the same code path as `claude-check`; fallback: one `kind='probe'` HTTP call — the same schema and exact-match rule; exit 2 on failure; §10.6) [`wd.ai.probe`, WP5] · `backup [--keep-daily N] [--keep-weekly M] [--with-images]` · `restore <file> [--yes]` [`wd.backup`, WP9] · `worker-once` (drain the queue synchronously; dev/smoke **only** — refuses with exit 2 and the hint 「word-dance.service is running — watch `journalctl -u word-dance -f` or GET /api/admin/jobs」 while `kv.worker_lease` is live, exactly like `restore`, because a second claimer next to the service gets its jobs swept and re-run — CLAUDE_INTEGRATION §6.2) [`wd.jobs.worker`, WP5] · `tick [--once]` (run the scheduler tick; dev/tests; same lease refusal) [`wd.jobs.scheduler`, WP4] · `build-batch <username> [--date YYYY-MM-DD]` · `push-now <username>` [`wd.services.batches`, WP4] · `consolidate <username>` [`wd.ai.consolidate`, WP5] · `fetch-image <word> [--provider P]` (manual image fetch, logs the attribution) · `images-prune --unused-days N` (delete cached files of words in no bank and no batch for N days) · `images-retry [--limit N] [--dry-run]` (requeue `fetch_image` for `failed` words somebody is studying — the nightly 03:30 sweep by hand: ≥ 6 h after the last attempt, ≤ 3 automatic retries per word per 30 days, ≤ N per run (default 50), function words excluded; `--dry-run` lists the words without queueing; safe next to the live service, whose IoWorker runs the jobs) [`wd.images.handler`, WP6] · `stats` · `check [db|claude|smtp|providers|all]` · `logs --tail N` [`wd.diag`, WP5] · `learn-order [--dry-run] [--show STAGE [--top N] [--cur STAGE]] [--report PATH] [--db PATH]` (recompute the learning order `words.learn_rank` — the derived key every 词库 / 筛词 / 推荐词 / prewarm list sorts by — writing only the rows whose key changed; `--dry-run` prints the movers report and writes nothing; `--show` prints the first N words of a stage with the reason for each position; `--report` writes the `data/seed/learn_order.json` document; refuses below schema 14 like `import-seed`; safe next to the live service — `docs/releases/2026-11-learn-order.md`) [`wd.services.learn_order`].

## 10. Upgrade and rollback

Upgrade: `cd /home/sqin/word-Dance && git pull && deploy/install.sh` — deps, frontend (built into `$WD_DATA_DIR/frontend-releases/<sha>.new`), then **the unit is stopped**, the snapshot is published (`frontend` symlink → `frontend-releases/<sha>` with one atomic rename; the two newest snapshots are kept), migrations run with the pre-migrate snapshot, and the unit is started again (downtime ≈ the migration time + 3 s, typically < 30 s; in-flight jobs are recovered by the stale-lock sweep; a `claude` call in flight is allowed up to `TimeoutStopSec=300` to finish). With `--no-restart` the service keeps running during `wd migrate`, which is safe **only for purely additive migrations** (new tables/columns/indexes, e.g. `0008_fk_child_indexes.sql`, `0012_word_images_meta.sql`, `0014_learn_rank.sql`; never `DROP`/`RENAME`/type changes — `0011_primary_stage.sql` and `0013_word_forms_alias.sql` are table rebuilds, §5) — install.sh prints that note. The same applies without passwordless `sudo -n` (§2): the script detects the running unit anyway but cannot stop or restart it, prints the note plus a `WARN` that the OLD version keeps serving, and its last line tells you to run `sudo systemctl restart word-dance` instead of claiming success — stop the unit yourself before re-running when a pending migration is not additive. **Before the upgrade that brings migration 0010** (the fallback provider): a deployment that opted into the CLI's `--fallback-model` must rename `WD_AI_FALLBACK_MODEL="…"` to `WD_AI_CLI_FALLBACK_MODEL="…"` in `.env` first — the old key now names the fallback *provider's* model (§4) and `wd migrate` / `wd serve` refuse to start with a `ConfigError` naming the move otherwise, which would leave the unit stopped at step 7; the shipped empty value needs nothing. A table rebuild (the only way to change a CHECK list in SQLite) is an ordinary stop-first migration: the runner turns foreign-key enforcement off around the file and runs `foreign_key_check` before committing (§5), so the rebuild keeps every child row. Rollback: `git checkout <previous tag> && deploy/install.sh` (stops, migrates nothing new, restarts); if a migration must be undone, `sudo systemctl stop word-dance && wd restore backups/pre-migrate-*.db.gz && sudo systemctl start word-dance`. If the data directory was moved (ops.md §5), every `deploy/install.sh` run here keeps working without a variable: when `WD_DATA_DIR` is unset the script takes the directory from the installed unit's `EnvironmentFile=` line (step 0, §2) and prints `data dir from the installed unit: …` — the older rule (`WD_DATA_DIR=<dir>` required on every run, else a fresh, empty instance at the default path) no longer applies. An explicit `WD_DATA_DIR=<dir>` is fine when it names the unit's directory (the ops.md §5 profile export) and is refused with exit 2 when it does not — a stale export or a typo; only the move procedure passes a different value, and it does so with `--move-data`.

**The live UI is a snapshot in the data directory, not the checkout's build output.** `wd serve` reads `WD_FRONTEND_DIST=$WD_DATA_DIR/frontend` (filled into `.env` once by install.sh, §4), a symlink to `frontend-releases/<sha>` that only step 6 of install.sh replaces — after the unit is stopped, with one atomic rename. Running `make test` or `npm run build` in the checkout writes `<repo>/frontend/dist` and changes nothing the service serves (before this, the service read `<repo>/frontend/dist` directly: a gate run on the checkout hot-swapped the SPA under the running pre-upgrade backend — new UI against the old API — and open tabs lost their lazy chunks whenever the hashed asset names changed under them). A re-run on the same commit builds into `<sha>.new` and swaps it in after the stop, so the live tree is never rebuilt in place either. Rollback of the UI alone (a bad build, API unchanged): `ls -1t /home/sqin/word-dance-data/frontend-releases` (newest first; the second entry is the previous release) → `cd /home/sqin/word-dance-data && ln -sfn frontend-releases/<previous sha> frontend.tmp && mv -T frontend.tmp frontend && sudo systemctl restart word-dance` — the process resolves the symlink at startup, so the restart is part of the rollback (`git checkout <previous tag> && deploy/install.sh` does the same inside a full rollback). The first upgrade of a deployment whose `.env` still has `WD_FRONTEND_DIST=""` fills that one line (`sed -i`, printed by `--dry-run`) and creates `frontend` + `frontend-releases/`; the stale `<repo>/frontend/dist` is no longer read (`make clean` removes it).

## 11. Runbook highlights (`docs/ops.md`)

| Situation | What you see | Action |
|---|---|---|
| Claude not logged in / token expired (`auth`) | admin banner 「Claude CLI 未登录，请以 sqin 身份运行 claude 完成登录」 (`failover.banner_for`), `system_events claude_auth`, CLI paused for `WD_AI_FAILOVER_COOLDOWN_MIN`; mode `claude_cli` — or `auto` while no provider can take content (fallback unconfigured / paused / marked `'0'`, or `content` removed from `WD_AI_FALLBACK_KINDS`): jobs queued until the pause ends, UI runs on dictionary data; mode `auto` with a usable fallback: the group reruns on the fallback at once (`ai_failover` event, content in groups of `WD_AI_FALLBACK_BATCH_SIZE`) and learners get fallback-generated example sentences (`word_contents.model` = the vendor id, e.g. `glm-4.7-flash`; ledger 「来源」 = fallback); prewarm groups (priority ≥ 90) and `svg` keep waiting for the CLI | `sudo -iu sqin claude` (interactive login) → `wd claude-check` (a successful probe or CLI call lifts the pause, fails back and requeues the content / lookup jobs that died during the outage — their words back to `queued`, CLAUDE_INTEGRATION §10.6) → `POST /api/admin/ai/pause {paused:false}` only if the admin pause is set |
| Claude account out of balance (`balance:` — 402 / `insufficient balance` / 余额不足 in the CLI output; the CLI path emits only the `balance:` and `network:` prefixes, never `quota:`) | banner 「Claude 账户余额不足或配额用尽，请充值后运行 wd claude-check」 (`failover.banner_for('balance')`), `claude_auth` event, CLI paused 24 h (mode `auto`: the fallback serves meanwhile) | top up → `wd claude-check` — any successful CLI call or probe lifts the pause early and releases the parked jobs; `POST /api/admin/ai/pause {paused:false}` lifts every pause and `'0'` mark at once |
| Fallback provider paused or unavailable (`ai_fallback_paused` event: Zhipu 1308 quota window → `quota:` until `retry_at`, 1113 / 402 → `balance:` 24 h, auth / 403 → the cooldown, six overloads → 15 min; `ai_fallback_quality` event: three unusable answers in a row, retries included → the cooldown as a **quality pause**, `kv.ai.fallback.pause_reason='quality'`; `fallback_unavailable` event and `ai.fallback.available='0'` after a 404, an unknown model or a missing key / URL — `not_found:` / `spawn_error`) | AI tab 「备用模型已暂停」 or 不可用 next to 当前提供方 (`AdminOverview.ai.fallback_paused_until` / `fallback_available`); no banner — the `claude_auth` banners are CLI-only; a quality pause sends 「备用模型输出异常，已暂停」 (its last sentence says whether Claude is paused, unconfirmed or back); in mode `auto` with the CLI paused too, the admins' webhook says 「AI 暂时不可用」 | wait for `retry_at` / fix the key, URL or model → 「探测备用」 or `wd ai-check --provider fallback` (a success lifts the pause and the mark — a quality pause only through a probe, an applied group or the resume, never through an ordinary call; a transient probe failure never re-marks `'0'`) or resume via `POST /api/admin/ai/pause {paused:false}` |
| `claude` binary cannot start (`spawn_error`) | banner 「Claude CLI 无法启动，请检查 WD_CLAUDE_BIN 指向的可执行文件后运行 wd claude-check」, `claude_auth` event, `kv.claude.available='0'`, health `claude_bin.ok=false` | fix `WD_CLAUDE_BIN` / the install → `wd claude-check` (a successful probe or CLI call lifts the mark and the pause; the admin's resume deletes the mark too) |
| Daily AI cap reached | `budget_daily` event; cards say 「今日 AI 额度已用完」 | raise `WD_AI_DAILY_BUDGET_USD` + restart, or wait for the next `WD_TZ` day |
| Many words show the text-only card (low photo hit rate) | admin overview `words.card_only` high vs `with_photo`/`with_claude_svg`; `budget_svg` event when the SVG sub-cap is hit | raise `WD_AI_SVG_DAILY_BUDGET_USD` (each call ≈ $0.0124, ≈ $0.0140 per delivered card) + restart; or add a keyed provider (`WD_PIXABAY_KEY`/`WD_PEXELS_KEY`); or register an Openverse app key |
| Fresh install, nobody can log in | `GET /api/health` → `needs_setup:true`; login page says 「尚无账号，首个注册的账号将成为管理员」 | open the site and register — the first account becomes admin without an invite code; or `wd create-admin` on the box |
| Openverse 429 | provider cooldown in admin overview | nothing; Wikimedia continues; optionally register an Openverse app key |
| Disk low | admin health `disk_free_bytes` | prune `images/` of words nobody studies (`wd images-prune --unused-days 365`, ops.md) or move the data directory: stop → `mv` → fix `WD_DATA_DIR=` in the moved `.env` → `WD_DATA_DIR=<new> deploy/install.sh --move-data` (re-renders both units; without the flag a differing `WD_DATA_DIR` is refused; never a hand-edited unit — procedure in ops.md §5; later upgrades follow the unit by themselves) |
| Service down for days | first tick builds **today's** batches only (back before a user's push time → delivered at push time as usual; back after it → published at once, deliveries `skipped` when > 6 h late); `downtime` event; history shows 「服务器离线」 | nothing |
| Restore needed | — | §5 |
| Rotate secrets | — | edit `.env`, `sudo systemctl restart word-dance` |
| UI stale or mixed after an upgrade (old pages, lazy chunk imports failing, 「前端尚未构建」) | `readlink /home/sqin/word-dance-data/frontend` does not name the snapshot the last install run printed (`==> frontend publish: …`), or the service was not restarted after it (`--no-restart`, no passwordless sudo — `wd serve` resolves the symlink at startup) | `sudo systemctl restart word-dance`, reload the tab; symlink missing or `.env` still `WD_FRONTEND_DIST=""` → re-run `deploy/install.sh`; bad build → UI rollback (§10, ops.md §4) |
| Flag tier fell back to 0 | `claude_probe_fallback` event | inspect the stderr excerpt; upgrade the CLI or keep tier 0 (fully functional) |
