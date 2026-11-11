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
| `…/word-dance-data/audio/<2hex>/<sha>.m4a\|.mp3` | cached pronunciation clips (`GET /media/audio`, API.md 76; m4a from `say`, mp3 from `youdao` / `bailian`) — a cache, safe to delete, capped by `WD_AUDIO_CACHE_MB`; under `WD_AUDIO_PROVIDER=cache` the read-only mirror of the Mac's clips instead: deleting it means `missing` for everything until the next sync (ops.md §5); under `bailian` a deleted clip is one paid re-synthesis | 0600 |
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
| `WD_SECRET_KEY` | generated by install.sh | HMAC key for the verification codes — `login_codes.code_hash` (the 6-digit phone / e-mail codes and the stale-phone challenge tokens, migration 0018; before 0018 `email_codes.code_hash`) and the captcha signatures (API.md 79): codes must not be brute-forceable from a DB dump; must be non-empty; rotating it only invalidates unexpired codes, challenges and captchas |
| `WD_TZ` | `Asia/Shanghai` | **operational timezone**: AI budget day, maintenance 03:30, admin views (user pushes use each user's own timezone) |
| `WD_REGISTRATION_MODE` | `invite` | `open` / `invite` / `closed` / `verified` — `verified` (docs/AUTH_SIGNUP_DESIGN.md): 必须先验证手机号或邮箱（a code through API.md 80 / 81 creates the account）；用户名密码只作登录/附加方式（set later through 89 / 7；`POST /api/auth/register` answers 403 `verification_required`）；邀请码可选（consumed when given）. The very first account is created with a username + password and becomes admin in every mode (the bootstrap rule, API.md 2); phone codes need `WD_SMS_PROVIDER`, e-mail codes a mail provider — with neither the login page offers the password entry only. Pair `verified` with `WD_AI_USER_DAILY_WORDS` (the per-user AI quota) before opening the site to strangers |
| `WD_SESSION_DAYS` | `30` | the guardian's / learner's session (slid daily, never shortened); a child's device session (API.md 107) is fixed at 90 days |
| `WD_MAX_BODY_BYTES` | `1048576` | |
| `WD_WORKER_ENABLED` | `1` | `0` in tests |
| `WD_TICK_SECONDS` / `WD_PREBUILD_HOURS` | `60` / `3` | scheduler |
| `WD_CONTACT_EMAIL` | (empty → `admin@localhost`) | in the Wikimedia User-Agent; set by `install.sh` from `--contact-email`, the environment, or an interactive prompt when `.env` is first created |
| `WD_CLAUDE_BIN` | `/home/sqin/.local/bin/claude` | absolute path set by install.sh; a relative path containing `/` (such as `backend/tests/fake_claude.py` from the repository root) is made absolute against the start-up working directory, because the CLI is spawned in `WD_CLAUDE_CWD`; a bare name is looked up on `WD_CLAUDE_PATH` |
| `WD_CLAUDE_HOME` / `WD_CLAUDE_PATH` / `WD_CLAUDE_CWD` | `$HOME` / `/home/sqin/.local/bin:/usr/local/bin:/usr/bin:/bin` / `$WD_DATA_DIR/claude-cwd` | child environment (CLAUDE_INTEGRATION.md §1.3) |
| `WD_AI_ENABLED` | `1` | kill switch |
| `WD_AI_MODEL` / `WD_AI_CLI_FALLBACK_MODEL` / `WD_AI_EXTRA_ARGS` | `sonnet` / (empty) / (empty) | `WD_AI_CLI_FALLBACK_MODEL` is the CLI's own `--fallback-model` (Claude ↔ Claude, off when empty) — it was named `WD_AI_FALLBACK_MODEL` before migration 0010; that key now names the fallback *provider's* model (below) and a non-empty value with `WD_AI_FALLBACK_KIND=none` refuses to start with a hint naming the move |
| `WD_AI_BATCH_SIZE` / `WD_AI_CONCURRENCY` | `10` / `1` | **1–12** (clamped in `config.py`: `content_v1.json` has `items.maxItems: 12`, CLAUDE_INTEGRATION §4) — words per `generate_content` call on the CLI; while the fallback provider takes the group the effective size is `min(WD_AI_BATCH_SIZE, WD_AI_FALLBACK_BATCH_SIZE)` (below) / 1–3 |
| `WD_AI_TIMEOUT_CONTENT_SEC` / `_LOOKUP_SEC` / `_CONSOLIDATE_SEC` / `_SVG_SEC` / `_DANCE_SEC` | `180` / `120` / `240` / `120` / `120` | |
| `WD_AI_BUDGET_CONTENT` / `_LOOKUP` / `_CONSOLIDATE` / `_SVG` / `_DANCE` | `0.25` / `0.15` / `0.40` / `0.10` / `0.25` | `--max-budget-usd` per call |
| `WD_AI_DAILY_BUDGET_USD` / `WD_AI_MONTHLY_BUDGET_USD` | `3.00` / `40.00` | measured $0.004/word → ≈ 750 words/day |
| `WD_AI_PREWARM_DAILY_BUDGET_USD` / `WD_AI_HOURLY_CALL_CAP` | `1.00` / `60` | |
| `WD_AI_SVG_DAILY_BUDGET_USD` | `0.50` | daily sub-cap for Claude-drawn SVG concept cards (≈ 35–40 cards/day at the measured $0.0124/call — $0.0140 per delivered card, 2026-11-05), counted inside the daily cap; `0` disables SVG generation without turning the feature off (CLAUDE_INTEGRATION §7) |
| `WD_AI_DANCE_DAILY_BUDGET_USD` | `0.50` | daily sub-cap for the 单词之舞 Claude annotations (`generate_dance`, 20 words per call ≈ $0.07 → ≈ 140 words/day, docs/WORD_DANCE_DESIGN.md §6.2), counted inside the daily cap; `0` disables the annotations only — nothing is queued and the rule-based dance keeps playing |
| `WD_AI_USER_DAILY_WORDS` | `80` | per-learner AI quota (0–100000; `0` = unlimited): the words one user may cause content generation for per UTC day — a learner's 不熟悉 marks and 「生成例句」 requests beyond it are served from dictionary data until tomorrow (`system_events('ai_quota_user')` once per user and day; `auth_throttle` key `ai:user:<id>`, reset by deleting that row, ops.md §6), prewarm and batch building are not counted (docs/AUTH_SIGNUP_DESIGN.md D2, PUBLIC_LAUNCH_AND_IOS.md A1/A2) — the precondition of `WD_REGISTRATION_MODE=verified` |
| `WD_AI_LOG_KEEP_DAYS` | `14` | raw CLI logs (the fallback's raw responses land there too) |
| `WD_AI_PROVIDER` | `claude_cli` | which provider serves the AI calls (docs/AI_FALLBACK_MODEL.md §4, CLAUDE_INTEGRATION §10): `claude_cli` = the CLI only (today's behaviour) · `openai_http` = the fallback HTTP provider only (the CLI is never spawned) · `auto` = the CLI with automatic failover to the fallback and fail-back by probe · `split` = the learners' kinds (`WD_AI_FALLBACK_KINDS`, prewarm groups excepted) on the fallback and the operator's work (prewarm content, `wd dance-annotate`, admin-requested SVGs) on the CLI, with no switching either way — a paused provider holds only its own work; a learner's action queues no svg / dance job in this mode (template card and rule dance serve until the operator pre-generates), the admin's 重新生成 and the manual 整理 (priority 10) follow the learners' lane, and a paused fallback sends the `fallback_paused` webhook since it is the learners' only provider (`docs/releases/2026-11-ai-split.md`). `openai_http`, `auto` and `split` refuse to start unless the fallback is fully configured (kind, base URL, model and a key). In `openai_http` mode **only the kinds in `WD_AI_FALLBACK_KINDS` ever run**: with the default list (`content,lookup,consolidate`) only `generate_svg` and `generate_dance` jobs — which the fallback never serves — and prewarm `generate_content` groups (priority ≥ 90, unless `WD_AI_FALLBACK_PREWARM=1`) wait indefinitely (re-deferred every 30 min; a `prewarm_plan` started before the switch keeps fanning such groups out — finish or cancel it first, or set the flag); a kind removed from the list waits the same way — without `content` every `generate_content` job waits and learners get dictionary data only — and the service then starts with a warning naming only the removed kinds (the prewarm gate is not part of it), not an error (CLAUDE_INTEGRATION §10.1) |
| `WD_AI_FALLBACK_KIND` / `_BASE_URL` / `_API_KEY` / `_API_KEY_FILE` / `_MODEL` | `none` / (empty) / (empty) / (empty) / (empty) | the fallback provider: kind `openai_http` = an OpenAI-format `POST {base}/chat/completions` endpoint (Zhipu `https://open.bigmodel.cn/api/paas/v4`, Alibaba Bailian `https://dashscope.aliyuncs.com/compatible-mode/v1`, DeepSeek, …; a trailing `/` is stripped; it must start with `http://` or `https://` and name a host — `ConfigError` otherwise, since a scheme-less value would fail every call as a soft `network:` error instead of refusing to start — and plain `http://` to a host other than loopback starts with a warning that the key travels in cleartext), the bearer key (masked by `GET /api/admin/config` — prefer the 0600 key **file**, whose first line is read at call time; the file must exist and be a readable regular file at startup, `ConfigError` naming the path otherwise, and a group/other-readable mode logs a warning) and the vendor model id (e.g. `glm-4.7-flash`). `WD_AI_FALLBACK_MODEL` was the CLI's `--fallback-model` before migration 0010 — that setting is now `WD_AI_CLI_FALLBACK_MODEL` above |
| `WD_AI_FALLBACK_DIALECT` / `_JSON_MODE` / `_THINKING` | `auto` / `auto` / `off` | request shape (CLAUDE_INTEGRATION §10.2): dialect `auto` is derived from the host (`zhipu` / `bailian` / `deepseek` / `generic`); JSON mode `auto` = `json_object` with the schema in the system prompt, except `json_schema` (a strict copy of the schema) for Bailian; thinking `off` sends the vendor's disable-thinking field, `on` enables it, `default` sends nothing |
| `WD_AI_FALLBACK_TIMEOUT_SCALE` / `_MAX_OUTPUT_TOKENS` / `_HOURLY_CALL_CAP` | `1.5` / `0` / `40` | the kind's timeout × scale (0.5–5.0; free-tier models are slower); `max_tokens` override (0 = the adapter's per-kind table: content 8192, lookup 8192, consolidate 12288, svg 4096, probe 512); the fallback's own hourly call cap, counted over its own `ai_calls.provider='fallback'` rows (the CLI keeps `WD_AI_HOURLY_CALL_CAP`) |
| `WD_AI_FALLBACK_BATCH_SIZE` | `5` | **1–12** (clamped with a warning, like `WD_AI_BATCH_SIZE`; a non-integer refuses to start): words per `generate_content` call while the fallback takes the group — the effective size is `min(WD_AI_BATCH_SIZE, WD_AI_FALLBACK_BATCH_SIZE)`. The worker already claims content in groups of that size when the fallback would take the head group (`failover.claim_limit`), and a larger group claimed for the CLI is regrouped before it reruns on the fallback (the claim's attempt is given back; CLAUDE_INTEGRATION §10.5); the dead jobs a fail-back revives carry no `group_size` mark, so they batch the same way (§10.6). Lookup groups stay ≤ 20 and consolidate 1 on either provider |
| `WD_AI_FALLBACK_KINDS` / `_PREWARM` | `content,lookup,consolidate` / `0` | the job kinds the fallback may serve — a comma list out of `content`, `lookup`, `consolidate` (`svg` never; remove `content` to keep example generation on the CLI only — in mode `split` that sends the learners' card requests to the CLI, which the startup warning names; the AI_FALLBACK_MODEL §5 eval is still recommended, it just no longer gates the default; an empty or blank value — `""`, `" "`, `","` — means the default) — and whether priority-≥ 90 prewarm groups may use it (`0`: prewarm content waits for the CLI even while ordinary content runs on the fallback — a claim that mixed both is split and the runnable prewarm backlog parked until the CLI pause ends, CLAUDE_INTEGRATION §10.4; in mode `openai_http`, where the CLI is never spawned, that means indefinitely: `POST /api/admin/content/prewarm` refuses new plans there, but the priority-90 jobs of a plan started before the switch stay queued until the mode changes or `_PREWARM=1`). In mode `auto` a kind outside the list stays on the CLI (and waits while the CLI is paused); in mode `openai_http` it never runs — see `WD_AI_PROVIDER` |
| `WD_AI_FALLBACK_PRICE_JSON` / `WD_AI_CNY_PER_USD` | (empty = free) / `7.2` | the fallback's price in CNY per million tokens as a JSON object, e.g. `{"input": 0.2, "output": 0.8, "cache_read": 0.04}` (single-quoted in `.env` because of the double quotes; the names are exactly `input` and `output` — both required when the object is not empty — plus an optional `cache_read`, anything else is a `ConfigError` because a mis-keyed table would record `cost_usd` 0 for a paid leg; empty or `{}` = the free tier), and the CNY → USD rate; the fallback's `cost_usd` is recorded post hoc from it and counted inside the daily / monthly caps (its reservation is 0, CLAUDE_INTEGRATION §7) |
| `WD_AI_FAILOVER_COOLDOWN_MIN` / `_PROBE_EVERY_MIN` | `30` / `30` | minutes (1–1440): the pause applied to a provider after a hard failure (auth, spawn_error, 403 — a balance failure pauses 24 h, a quota window until its reset; in **every** mode — `split` included) and after the fallback's third consecutive invalid answer (the quality pause, CLAUDE_INTEGRATION §10.4 — in `auto`, `openai_http` and `split` alike, retries of the same group included; tagged `kv.ai.fallback.pause_reason='quality'`): a success of that provider, a call or a probe, or the admin's resume lifts a hard-failure pause early and releases the jobs parked at it, while the quality pause is lifted only by a fallback probe, an applied fallback group or the resume — an ordinary HTTP-ok answer may still be rejected by the handler (§10.4–§10.6); and the interval of the CLI fail-back probe while the fallback is active (one attempt pinned to the recorded flag tier; doubled after 12 failed probes) |
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
| `WD_AUDIO_PROVIDER` | `auto` | server-side pronunciation clips for devices without an English voice — Android's WebView, the Android container of HarmonyOS NEXT, domestic ROMs without an English TTS (API.md 76, DESIGN §9 「Pronunciation clips」, `wd/audio.py`): `say` = macOS `/usr/bin/say` + `/usr/bin/afconvert` (offline, AAC ≈ 8 KB per word); `youdao` = `https://dict.youdao.com/dictvoice` (the unofficial public endpoint Chinese dictionary apps use, mp3 — opt-in, its terms are not published, and **every uncached text is sent to Youdao** with a neutral `User-Agent` that carries neither your e-mail nor your URL); `cache` = read-only: serves the `say` clips another host synthesised (the same content-addressed files, mirrored with `rsync`; the voices they were made with in `WD_AUDIO_CACHE_VOICES`), a text without a clip answering 503 `{reason:"missing"}` (event `audio_clip_missing`, no budget spent): a browser that still has `speechSynthesis` (it had no English voice, which is why it asked) speaks it with its default voice, the App shell (no voice) shows 「这条发音还没有生成，请稍后再试」 until the next sync; `WD_AUDIO_CACHE_MB` is not enforced on that host and nothing there touches or prunes the mirror — the way a Linux server plays the Mac's Ava / Serena clips (the loop: `wd audio-texts` on the server → `wd audio-prewarm --texts FILE` on the Mac → `rsync` of `audio/` back, ops.md §5); `bailian` = 阿里云百炼 CosyVoice / Qwen-Audio TTS over its synchronous HTTP API (mp3 24 kHz; the `WD_BAILIAN_*` rows below) — **the provider for a public deployment and for a Linux server**: the macOS SLA keeps the `say` voices personal and non-commercial and forbids redistributing their output (docs/BUSINESS_MODEL.md §0 item 4), and a Linux host has no `say` at all; the owner opts in explicitly (`auto` never picks it), the text of every uncached clip is sent to 百炼 (English headwords and example sentences of the shared library — no personal data, DESIGN §10), the price is 1 元 per 10 000 characters with `cosyvoice-v3-flash` (an English letter, space or punctuation mark counts 1; ≈ ¥115 for the whole library's words and sentences, `wd audio-prewarm --dry-run` prints the estimate of a run), the limit 180 requests per minute per model — the server keeps its own requests 0.4 s apart and answers 503 `{reason:"busy"}` on a 429 / 5xx (the client retries later; 「通常 1 分钟内恢复」); with `bailian` a Linux server synthesises on demand and the `cache` mirror is optional; `wd audio-probe` is the day-0 check; `off` = the endpoint answers 503 `audio_unavailable {reason:"off"}` and every client keeps its own voice; `auto` = `say` when `/usr/bin/say` exists on the host (a Mac), else `off` — so a Linux VPS has **no** pronunciation fallback until this is set (`bailian`, `cache` or `youdao`). Clips are cached under `audio/` (content-addressed by provider, voice, accent and text; delete the directory to re-synthesise) up to `WD_AUDIO_CACHE_MB`. The startup log names the effective provider (event `audio_provider`) |
| `WD_AUDIO_SAY_VOICE` | (empty) | the `say -v` voice name used for both accents, exactly as `say -v '?'` lists it (e.g. `Ava (Premium)` after downloading it in System Settings → Accessibility → Spoken Content → System voice → Manage voices; `wd audio-voices` prints the installed voices of the preference lists exactly as `say` lists them — the tier stayed English on this zh-CN Mac, only the Eloquence voices carry localised qualifiers — with their tier and whether `say` resolves them; at startup the warm-up logs `audio_voice` per accent, or `audio_voice_failed` when no voice resolves — the requests then answer 503 `failed`); empty = the best installed voice of the preference list per accent — US: Ava, Zoe, Allison, Samantha, Nicky, Joelle, Evan, Tom, Alex; UK: Serena, Kate, Stephanie, Jamie, Oliver, Daniel — Premium before Enhanced before the compact voice of the same name, the other accent's choice before none; the novelty voices and the Eloquence voices (Eddy, Flo, Reed …) are never chosen, so a Mac with only those answers 503 `{reason:"failed"}` and the log says to download one. `say` accepts a name it does not know and silently speaks with another voice, so the server probes every candidate once per process (events `audio_voice` = the choice, `audio_voice_probe_failed`) and a misspelt or not-yet-downloaded override is a 503 `failed` naming it in the log — never a cache full of clips in the wrong voice. A voice downloaded while the service runs is used after a restart; a different voice means different cache keys (the old clips age out) |
| `WD_AUDIO_CACHE_VOICES` | (empty) | with `WD_AUDIO_PROVIDER=cache`: the `say` voices the mirrored clips were made with, per accent, exactly as `say -v '?'` prints them on the host that synthesises — `en-US=Ava (Premium);en-GB=Serena (Premium)` (`wd audio-voices` there shows the choice). Both accents required; part of every clip's content-addressed name, so a wrong voice is a cache that never hits (`wd audio-voices` here prints the configured pair and the clip count) |
| `WD_AUDIO_CACHE_MB` | `256` | cap of the clip cache under `audio/` (16–1000000); when a synthesis pushes it over, the least recently played clips are removed down to 90 % (event `audio_cache_pruned`). ≈ 8 KB per word and 15–30 KB per example sentence with `say`, so the default holds tens of thousands of clips |
| `WD_BAILIAN_API_KEY_FILE` | (empty) | with `WD_AUDIO_PROVIDER=bailian` (required): path of a 0600 file whose first line is the 百炼 API key (`sk-…`, created in the 百炼 console → API-Key 管理 for the region and 业务空间 below; shown in full only once). The `WD_ALIYUN_ACCESS_KEY_SECRET_FILE` rule: whenever it is set the file must exist and be readable at startup (the service refuses to start and names the variable otherwise), a group/other-readable mode only warns — `chmod 600` it; the key is read at call time (a rotated key is used by the next clip), never lands in `Settings`, a log line or an error message — `GET /api/admin/config` shows the path, `wd check providers` whether the file is readable |
| `WD_BAILIAN_WORKSPACE_ID` | (empty) | required with `bailian`: the 业务空间 id (百炼 console → 业务空间管理) — the TTS host is `{WorkspaceId}.{region}.maas.aliyuncs.com`, the production host form 百炼 recommends; the key must belong to the same 业务空间 and region |
| `WD_BAILIAN_REGION` | `cn-beijing` | `cn-beijing` (华北2 北京 — the only region whose CosyVoice system English voices are documented for the HTTP API; the free 新人额度 exists only there) or `ap-southeast-1` (新加坡: Qwen-Audio-TTS's 精品英文音色 with `qwen-audio-3.1-tts-flash`); keys, models and voices are per region and never cross (a key of the other region is 401 `InvalidApiKey`) |
| `WD_BAILIAN_TTS_URL` | (empty) | optional full endpoint override (a test mock, a future host); empty = `https://{WorkspaceId}.{region}.maas.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer`. Must start with `http://` or `https://` and name a host (the service refuses to start otherwise); plain `http://` to a host other than loopback starts with a warning (the key travels in cleartext). `GET /api/admin/config` shows the endpoint in force |
| `WD_BAILIAN_TTS_MODEL` | `cosyvoice-v3-flash` | the `model` field: `cosyvoice-v3-flash` (1 元 / 万字符 in 北京, system English voices `loong*_v3`) or `qwen-audio-3.1-tts-flash` (both regions, billed per token, voices `*_v3.1`; the server adds `language_hints: ["en"]` for the `qwen-audio` models — same endpoint and body otherwise); part of `ServerFlags.audio_key`, so a model switch is a new clip URL for every browser. `wd audio-prewarm --dry-run` prices a run only for the per-character models |
| `WD_BAILIAN_TTS_VOICES` | `en-US=loongabby_v3;en-GB=loongemily_v3` | one 百炼 voice per accent in the `WD_AUDIO_CACHE_VOICES` shape — voices of the model above (the 百炼 音色列表: for CosyVoice v3 `loongabby_v3` 美式英文女, `loongandy_v3` 美式英文男, `loongemily_v3` 英式英文女, `loongeric_v3` 英式英文男; for `qwen-audio-3.1-tts-flash` `Abby_v3.1` / `Andy_v3.1` / `Emily_v3.1` / `Eric_v3.1`); a voice the model does not have is 400 `InvalidParameter` → 503 `failed` (`wd audio-probe` shows it). Both accents required with `bailian`. The voice is part of every clip's content-addressed name: a new voice means new clips (the old ones age out under `WD_AUDIO_CACHE_MB`, or `wd audio-prewarm --purge-others` drops them) and a new `audio_key` |
| `WD_MAIL_PROVIDER` | `smtp` | the e-mail channel's transport (docs/AUTH_SIGNUP_DESIGN.md §5.2): `smtp` = the `WD_SMTP_*` server below (the channel is enabled when host + from are set); `aliyun_dm` = Aliyun DirectMail `SingleSendMail` over HTTPS with `WD_ALIYUN_ACCESS_KEY_ID` / `_SECRET_FILE` and `WD_SMTP_FROM` as the sender (`AccountName` = its address part, `FromAlias` = its display name) — refuses to start unless all three are set; `ServerFlags.email_configured` / `GET /api/health.email_enabled` follow the selected provider, 409 `smtp_unconfigured` keeps its name for "no mail provider" |
| `WD_SMTP_HOST` / `WD_SMTP_PORT` / `WD_SMTP_USER` / `WD_SMTP_PASSWORD` / `WD_SMTP_FROM` / `WD_SMTP_TLS` | (empty) / `587` / … / `starttls` | the `smtp` provider: the e-mail channel is enabled when host + from are set (`starttls` / `ssl` / `none`); `WD_SMTP_FROM` is the sender address of **both** providers (also `aliyun_dm`'s verified DirectMail sender) |
| `WD_SMS_PROVIDER` | `off` | phone verification codes (API.md §3.1, docs/AUTH_SIGNUP_DESIGN.md §5.2): `off` = no SMS — the login page offers e-mail and password only (`ServerFlags.sms_enabled` false, 409 `sms_unconfigured` for the phone channel); `aliyun_verify` = Aliyun 号码认证 `SendSmsVerifyCode` (the system signature and the built-in templates, no per-site signature review) — refuses to start unless `WD_ALIYUN_ACCESS_KEY_ID`, `WD_ALIYUN_ACCESS_KEY_SECRET_FILE` and `WD_ALIYUN_SMS_SIGN_NAME` are set; `wd sms-probe <number>` sends one real code through it (the day-0 check of the release note) |
| `WD_ALIYUN_ACCESS_KEY_ID` | (empty) | the RAM user's AccessKey ID shared by `aliyun_verify` and `aliyun_dm` (grant it the 号码认证 / DirectMail send actions only); masked by `GET /api/admin/config` |
| `WD_ALIYUN_ACCESS_KEY_SECRET_FILE` | (empty) | path of a 0600 file whose first line is the AccessKey secret, read at call time (never an inline variable: the secret stays out of `.env` and `GET /api/admin/config` shows the path only); validated like `WD_AI_FALLBACK_API_KEY_FILE` — it must exist and be a readable regular file at startup (`ConfigError` naming the path otherwise), a group/other-readable mode logs a warning |
| `WD_ALIYUN_SMS_SIGN_NAME` | (empty) | the system signature name shown in the 号码认证 console (the `SignName` parameter of `SendSmsVerifyCode`); required by `aliyun_verify` |
| `WD_SMS_DAILY_CAP` | `200` | phone codes per `WD_TZ` day for the whole site (0–100000; `0` = the cap is already reached, i.e. phone codes off for the day budget) — beyond it every phone send answers 503 `sms_budget_exhausted` (`retry_after_s` to the next day), sends that would create an account stop at 70 % of it (`AdminOverview.sms.registration_open`), and `system_events` `sms_budget_50` / `_80` / `_100` are written once per day with a webhook notice to the admins at 80 % and 100 % (ops.md §6) |
| `WD_SMS_HOURLY_CAP` | `40` | phone codes per UTC hour for the whole site (0–100000); beyond it 503 `sms_budget_exhausted` with `retry_after_s` to the next hour |
| `WD_CODE_IP_HOURLY` | `20` | verification-code sends per client IP per hour (1–100000; API.md 80 / 82 / 85 / 90, `auth_throttle` key `code_send:ip:<ip>`) — the per-target limits (1/min, 5/h, 10/day) and the phone-prefix limit (5/h) are fixed in `security.py` |
| `WD_PHONE_STALE_DAYS` | `90` | a phone identity that has not logged in by code for this many days (1–3650) gets the stale-phone challenge instead of a session (API.md 81–84: the account's password or verified e-mail confirms it is still the same person; 「不是我的」 disputes the binding and registers the number anew — the admin page lists and can restore disputed bindings, API.md 92 / 93) |
| `WD_CAPTCHA` | `on` | `on` / `off`: the self-hosted image captcha (API.md 79 — 4 digits drawn with Pillow, signed with `WD_SECRET_KEY`, 2 minutes, single use, no third-party script — the CSP forbids one) required by the **public** code sends when no session exists (API.md 80 / 90; 400 `captcha_required` / `invalid_captcha`); logged-in sends (85) and the password login never ask for it. The test environment sets `off` |
| `WD_WECHAT_APPID` | (empty) | third-party sign-in, slice 2-A (docs/AUTH_SIGNUP_DESIGN.md §5.3, API.md §3.3 — everything ships dark): the mini program's AppID; together with `WD_WECHAT_SECRET_FILE` it turns the WeChat login bridge on (`Settings.wechat_configured` → `ServerFlags.wechat_enabled`, endpoints 112–116: 小程序码 + pairing code on the web, scan / confirm in the mini program `miniprogram/`). An appid without the secret file refuses to start (`ConfigError`, the `aliyun_verify` rule); the AppID is not a secret |
| `WD_WECHAT_SECRET_FILE` | (empty) | path of a 0600 file whose first line is the AppSecret, read at call time by `delivery/wechat.py` (code2Session, the stable access token, `getwxacodeunlimit`) — the `WD_ALIYUN_ACCESS_KEY_SECRET_FILE` rule: it must exist and be a readable regular file at startup (`ConfigError` naming the path otherwise), a group/other-readable mode logs a warning; `GET /api/admin/config` shows the path, never the content |
| `WD_WECHAT_ENV` | `release` | `release` / `trial` / `develop` — the `env_version` of the 小程序码 endpoint 114 requests (`develop` / `trial` while the mini program is not published; `release` once it is) |
| `WD_WECHAT_PAGE` | `pages/confirm/confirm` | the mini-program page the 小程序码 opens (the scene is the ticket; `miniprogram/app.json`) |
| `WD_QQ_APPID` | (empty) | QQ 互联 网站应用 APP ID; together with `WD_QQ_KEY_FILE` and `WD_QQ_CALLBACK_URL` it turns QQ login on (`qq_configured` → `ServerFlags.qq_enabled`, endpoints 118 / 119). An appid without the key file or the callback refuses to start |
| `WD_QQ_KEY_FILE` | (empty) | path of a 0600 file whose first line is the APP Key (the same file rule as `WD_WECHAT_SECRET_FILE`; read at call time by `delivery/qq.py`) |
| `WD_QQ_CALLBACK_URL` | (empty) | the callback registered at QQ 互联: `https://<filed domain>/api/auth/qq/callback` — the mainland relay host (§7.1) proxies that path to this server; must start with `https://` and name a host (`http://` is accepted only with `WD_DEV=1`, for the fake consent flow on a laptop) |
| `WD_APPLE_CLIENT_ID` | (empty) | the Services ID of Sign in with Apple (web redirect flow, `response_mode=form_post`); together with `WD_APPLE_CALLBACK_URL` it turns Apple login on (`apple_configured` → `ServerFlags.apple_enabled`, endpoints 120 / 121). A client id without the callback refuses to start |
| `WD_APPLE_APP_ID` | (empty) | the iOS bundle id, also accepted as the id_token `aud` — read but unused until the iOS Capacitor plugin exists (docs/MOBILE_APP.md; owner decision D6) |
| `WD_APPLE_CALLBACK_URL` | (empty) | `https://<host>/api/auth/apple/callback`, registered as a Return URL of the Services ID; the same `https://` rule as `WD_QQ_CALLBACK_URL`. The callback is the one `/api` POST exempt from the CSRF header (API.md §1 / 121) — Apple posts the id_token there, the HMAC-signed `state` is its defence |
| `WD_LOG_LEVEL` / `WD_LOG_FORMAT` / `WD_LOG_FILE` | `INFO` / `json` / (empty) | |
| `WD_BACKUP_KEEP_DAILY` / `WD_BACKUP_KEEP_WEEKLY` | `14` / `8` | |
| `WD_ADMIN_USERNAME` / `WD_ADMIN_PASSWORD` | (empty) | unattended `wd create-admin --if-none` — the only command that reads them (`set-password` prompts, or takes an explicit `--password-env VAR`); remove the password afterwards |
| `WD_DEV_REAL_CLAUDE` | `0` | dev only (`scripts/dev.sh`): `1` uses the real CLI instead of `tests/fake_claude.py` |
| `WD_SMOKE_MOCK_HTTP` | `0` | tests/smoke only: `1` (together with `WD_DEV=1`, otherwise ignored) routes every outbound `httpx` request (image providers, downloads, webhooks) through the `wd.smoke_mock` `httpx.MockTransport` fixtures and pins the SSRF DNS step — installed by `create_app` for `wd serve` **and** by `wd.cli.main` for every other `wd` command, so the `wd worker-once` / `wd tick --once` / `wd fetch-image` subprocesses `make smoke` spawns are mocked too (nothing leaves the box) |
| `WD_AUTH_FAKE_PROVIDERS` | `0` | dev only — `1` refuses to start without `WD_DEV=1` (`ConfigError`; unlike `WD_SMOKE_MOCK_HTTP` it is not silently ignored, because the fake consent pages would sign anyone in as anyone): installs the fake WeChat / QQ / Apple clients (`delivery/wechat.FakeWechatClient`, `delivery/qq.FakeQQClient`, `delivery/apple.FakeAppleKeys`) and the fake consent routes `/api/auth/fake/qq` / `/api/auth/fake/apple` (`routers/auth_fake.py`), so `ServerFlags.wechat_enabled` / `qq_enabled` / `apple_enabled` read true and `make smoke` or a developer's browser can run the three third-party flows end to end without credentials — nothing leaves the box (slice 2-A, API.md §3.3) |

Secrets never leave `.env`; `GET /api/admin/config` masks them.

**Quoting rule for `.env` (binding, stated at the top of `deploy/env.example`)**: the same file is read by three parsers — bash (`set -a; . .env` in install.sh), systemd `EnvironmentFile=` and python-dotenv (dev/tests) — whose unquoted-value rules differ (bash would *execute* `low` for `WD_AI_EXTRA_ARGS=--effort low`). Therefore every value is written **double-quoted**, `KEY="value"`, which all three accept identically for ordinary values (`WD_AI_EXTRA_ARGS="--effort low"`); a value containing `"` (`WD_AI_FALLBACK_PRICE_JSON`) or a secret containing `$`, `` ` `` or `\` is written **single-quoted** (`WD_SMTP_PASSWORD='p$ss'`), literal in all three parsers; `#` starts a comment only at the beginning of a line. install.sh runs `bash -n` plus a line-shape check (`^WD_[A-Z0-9_]+=("[^"$`\\]*"|'[^']*')$`) before sourcing and aborts with the offending line(s). `env.example` ships every variable of this table in that form with its default.

## 5. Backups and restore (`backend/wd/backup.py` owns CLI `wd backup|restore` and the `snapshot_before_migrate` hook; `wd migrate` itself lives in `cli.py`, TASKS P0)

* `wd backup --keep-daily N --keep-weekly M`: `VACUUM INTO '$DATA/tmp/word-dance-<ts>.db'` (consistent online snapshot under WAL) → `PRAGMA integrity_check` on the copy (abort + `system_events('backup_failed')` + non-zero exit if not `ok`) → gzip → `$DATA/backups/word-dance-YYYYMMDD-HHMM.db.gz` (0600) → retention: newest N daily + Sunday copies up to M weekly → `kv.backup.last = {file, at, bytes}` (shown in admin health). Images are re-fetchable and not backed up by default; `--with-images` adds `images-YYYYMMDD.tar`. The same flags are used everywhere (timer unit, DESIGN §11, WP9 acceptance).
* `wd migrate [--dry-run]` (`cli.py` → `db.run_migrations(conn, pre_hook=wd.backup.snapshot_before_migrate)`, the hook late-imported and skipped with a warning if `backup.py` is absent during Phase 0): pending = `backend/wd/migrations/NNNN_*.sql` whose `NNNN` is not in `schema_migrations`; before applying the first pending file it writes `backups/pre-migrate-<from>-to-<to>.db.gz` (same pipeline); each file then runs inside one `BEGIN IMMEDIATE` transaction and **the runner inserts `schema_migrations(version, name)` in that same transaction** — migration files never self-register (SCHEMA.sql §1/§10), so a fresh install cannot hit a duplicate-key crash and a half-applied file rolls back together with its bookkeeping row. This atomicity holds only because `db.connect()` opens the connection with `sqlite3.connect(path, autocommit=True)` (Python 3.12) and the runner issues `BEGIN IMMEDIATE`/`COMMIT`/`ROLLBACK` explicitly — in the legacy default mode `conn.executescript()` commits implicitly before running the file (verified on this box), silently ending the transaction (TASKS P0 step 4 + its unit test). The runner also owns foreign-key enforcement around each file: `PRAGMA foreign_keys=OFF` *before* the `BEGIN` (inside a transaction the PRAGMA is a silent no-op), `PRAGMA foreign_key_check` before the bookkeeping row (a file that leaves orphans is rolled back with a `MigrationError` naming them), `PRAGMA foreign_keys=ON` again afterwards — so the SQLite table rebuild a CHECK-list change needs (create new → copy → `DROP` old → `RENAME`) does not cascade-delete the children of the dropped parent table (SCHEMA.sql §1; migration files never toggle `PRAGMA foreign_keys` themselves and must delete child rows explicitly when they delete parents). `--dry-run` lists pending files only. install.sh stops the running unit before `wd migrate` (unless `--no-restart`, §2/§10). Which files are safe while the service runs is a property of each file: `0011_primary_stage.sql` (the 小学 stage: `words` / `user_settings` are rebuilt), `0013_word_forms_alias.sql` (`word_forms` rebuilt) and `0016_word_dances.sql` (`jobs` / `ai_calls` rebuilt for the new job type and kind, plus the new `word_dances` table — the 单词之舞 P2 release, `docs/releases/2026-11-word-dance-p2.md`) are **stop-first** — never under `--no-restart`, and the pre-migrate snapshot is the only rollback (`wd restore backups/pre-migrate-<from>-to-<to>.db.gz`, code and database roll back together); `0012_word_images_meta.sql` (four `ADD COLUMN`s on `word_images`), `0014_learn_rank.sql` (one `ADD COLUMN` on `words`, filled by the service start / `wd learn-order`), `0015_dance_mode.sql` (one `ADD COLUMN` on `user_settings` with its default — the 单词之舞 release, `docs/releases/2026-11-word-dance-p1.md`), `0017_word_dances_corrected.sql` (one nullable `ADD COLUMN` on `word_dances`, filled by the service start) and `0018_auth_identities.sql` (the `identities` / `login_codes` tables, eight nullable or defaulted columns on `users` with the in-file `password_set_at = created_at` backfill, `sessions.actor_user_id` — the sign-in-by-code release, `docs/releases/2026-11-auth-signup-1a.md`) and `0019_family.sql` (the `family_codes` table, `users.profile_prompted_at`, `sessions.guardian_gate_at` — the guardian + child release, `docs/releases/2026-11-auth-signup-1b.md`; no data step) are additive. Rehearse on a copy first (`cp` the database to a private directory, `WD_DATA_DIR=<copy> wd migrate --dry-run && wd migrate`).
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

### 7.1 Relay host (mainland)

The WeChat mini program and QQ 互联 accept only a filed (备案) mainland domain as their server / callback domain, while the application itself may run abroad (the Tokyo host of docs/QUICK_DEPLOY_AND_MOBILE.md). Slice 2-A therefore allows a small **relay host**: a mainland 轻量应用服务器 with the filed domain whose nginx forwards exactly the third-party sign-in paths (`/api/auth/wechat/`, `/api/auth/qq/callback`, `/api/auth/apple/callback`, `/api/health`) to this server over TLS and serves a static product page for everything else — no other path crosses, AI endpoints never do. `WD_QQ_CALLBACK_URL` (and, when the Apple Return URL is registered on the filed domain, `WD_APPLE_CALLBACK_URL`) names that host; the result reaches the SPA's own origin through the one-time grant of API.md 122, so cookies are never set on the relay domain. Purchase, filing order (① website ② mini program), the 工具 category wording, the inspection risk of proxying abroad, certbot and the exit condition are in `deploy/relay/README.md`; the nginx template is `deploy/relay/nginx.relay.conf.example`, the product page `deploy/relay/index.html` (with the `〔ICP 备案号〕` / `〔公安备案号〕` placeholders).

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

`serve` · `migrate [--dry-run]` · `version` [`wd.cli` itself] · `import-seed [--file PATH (default: WD_SEED_PATH)] [--force] [--dry-run] [--report PATH]` (`--dry-run` writes nothing and prints the plan — inserts / updates / unchanged, orphans, stage-flag changes, the stage_min matrix, unknown stage codes; `--report PATH` saves it as JSON; a database with no schema yet or with pending migrations gets one line — `run wd migrate first` — and exit 1, so the import never runs ahead of the schema, §10) [`wd.seed`, WP1] · `create-admin [--if-none] [--username U] [--password-env VAR]` (the only command that falls back to `WD_ADMIN_PASSWORD`) · `set-password <username> [--password-env VAR]` (prompts twice; never reads `WD_ADMIN_PASSWORD` implicitly — the variable is required when stdin is not a terminal) · `promote|demote <username>` (`promote` refuses an account without a password — `admin_needs_password`, API.md 57: admins sign in with a password only, so run `wd set-password` first) · `invite [--uses N] [--days D] [--note …]` (prints the code once) · `unlock <identifier>` (clear the login lockout of a username / phone / e-mail for every client IP — the `login:user:<identifier>:<ip>` rows; prints the count, never the identifier) · `sms-probe <number>` (send ONE real login code, template 100001, through `WD_SMS_PROVIDER` and print the provider's `Code` / `Message` / `RequestId` — the day-0 check of the Aliyun signature and template; prints neither the code nor the full number, touches neither the database nor the SMS budget; exit 2 while the provider is `off`, 1 when it refused) [`wd.security`, WP2] · `claude-check` · `ai-check [--provider claude|fallback]` (one probe round — CLI: tier 1 then tier 0 as in CLAUDE_INTEGRATION §2, the same code path as `claude-check`; fallback: one `kind='probe'` HTTP call — the same schema and exact-match rule; exit 2 on failure; §10.6) [`wd.ai.probe`, WP5] · `backup [--keep-daily N] [--keep-weekly M] [--with-images]` · `restore <file> [--yes]` [`wd.backup`, WP9] · `worker-once` (drain the queue synchronously; dev/smoke **only** — refuses with exit 2 and the hint 「word-dance.service is running — watch `journalctl -u word-dance -f` or GET /api/admin/jobs」 while `kv.worker_lease` is live, exactly like `restore`, because a second claimer next to the service gets its jobs swept and re-run — CLAUDE_INTEGRATION §6.2) [`wd.jobs.worker`, WP5] · `tick [--once]` (run the scheduler tick; dev/tests; same lease refusal) [`wd.jobs.scheduler`, WP4] · `build-batch <username> [--date YYYY-MM-DD]` · `push-now <username>` [`wd.services.batches`, WP4] · `consolidate <username>` [`wd.ai.consolidate`, WP5] · `fetch-image <word> [--provider P]` (manual image fetch, logs the attribution) · `images-prune --unused-days N` (delete cached files of words in no bank and no batch for N days) · `images-retry [--limit N] [--dry-run]` (requeue `fetch_image` for `failed` words somebody is studying — the nightly 03:30 sweep by hand: ≥ 6 h after the last attempt, ≤ 3 automatic retries per word per 30 days, ≤ N per run (default 50), function words excluded; `--dry-run` lists the words without queueing; safe next to the live service, whose IoWorker runs the jobs; `--since ISO` runs the library-wide provider-outage sweep instead: every `failed` word, studied or not, whose ONLY fetch attempt at or after that instant found no photo — the chain ran while Wikimedia was unreachable, in cooldown or over `WD_WIKIMEDIA_DAILY_LIMIT` — is queued once more at priority 90 (Wikimedia only, no SVG, no retry flag, so the learners' automatic retries are untouched), ≤ N per run; a word with two attempts in the window is never swept again, so the sweep cannot loop over the words that really have no photo. Run it when Wikimedia answers again, out of cooldown (`wd check providers`) and with quota left (2 000 requests per UTC day by default — about 1 700 words); e.g. `wd images-retry --since 2026-11-11T12:00:00Z --limit 100 --dry-run`) [`wd.images.handler`, WP6] · `stats` · `check [db|claude|smtp|providers|all]` · `logs --tail N` [`wd.diag`, WP5] · `learn-order [--dry-run] [--show STAGE [--top N] [--cur STAGE]] [--report PATH] [--db PATH]` (recompute the learning order `words.learn_rank` — the derived key every 词库 / 筛词 / 推荐词 / prewarm list sorts by — writing only the rows whose key changed; `--dry-run` prints the movers report and writes nothing; `--show` prints the first N words of a stage with the reason for each position; `--report` writes the `data/seed/learn_order.json` document; refuses below schema 14 like `import-seed`; safe next to the live service — `docs/releases/2026-11-learn-order.md`) [`wd.services.learn_order`] · `dance-annotate (--stage S | --word W …) [--limit N] [--priority P] [--force] [--dry-run]` (enqueue `generate_dance` — the 单词之舞 Claude annotations, CLAUDE_INTEGRATION §6.8 — for every public validated word of a stage in learning order or for the named words; `--force` re-annotates words that already have a Claude spec; `--dry-run` lists them; safe next to the live service, whose ClaudeWorker runs the jobs 20 words per call under `WD_AI_DANCE_DAILY_BUDGET_USD` — `docs/releases/2026-11-word-dance-p2.md`) [`wd.ai.dance`] · `audio-voices` (the pronunciation provider in force, the installed `say` voices of the preference lists with their tier and whether `say` really resolves them, and the voice each accent gets — run it after downloading a voice; under `bailian` the model, the region and the configured voice per accent instead, no `say` listing; exit 1 when an accent gets none; the probes need the data directory, so on the Mac `WD_DATA_DIR=/Users/sqin/word-dance-data` like every command) · `audio-probe [--accent en-US|en-GB] [TEXT]` (synthesise ONE clip through the provider in force — any provider — and print the provider, the voice, the bytes, the media type and the path; the default text is `The cat sat on the mat.`; a clip already cached is served from the cache and says so — pass another TEXT to reach the provider; exit 1 on a provider error with its kind and message — `busy` = 百炼 429 / 5xx, usually over within a minute —, 2 without a provider, for a text the rule refuses or a configuration error: the day-0 check of a 百炼 key, workspace and voices, like `sms-probe`) · `audio-prewarm [--accent en-US|en-GB …] [--stage xs|zk|gk|cet4|cet6 …] [--limit N] [--dry-run] [--purge-others] [--texts FILE] [--db PATH]` (synthesise the pronunciation clips of the study path ahead of the taps: the display form of every word with content or in a bank and the English of its example sentences, in learning order, plus the headwords of every public valid word of each `--stage` — what the welcome screening and 词库 browsing can tap; anything else a learner taps is made at the tap. For `en-US` plus every accent a learner chose, two `say` processes at a time (`youdao`: one request at a time, a pause between two; `bailian`: two requests at a time kept 0.4 s apart — ≤ 150 of the 180 requests per minute —, the plan line pricing the characters of the run at the model's list price, e.g. 「≈ 136 characters to send to 百炼 (model cosyvoice-v3-flash): ≈ ¥0.01 …」). Cached clips are counted, not remade; `--limit` bounds the clips to make; `--dry-run` prints the plan — texts, clips cached / to make, the cache size afterwards against `WD_AUDIO_CACHE_MB`, what `--purge-others` would delete — and makes nothing; a plan that would push the cache past 90 % of the cap is refused (exit 1: raise the cap or narrow the set), and clips the cap pruned during the run are reported (exit 1). Stops after five failed attempts in a row (the provider went down) and on Ctrl-C (exit 130), both with the partial report; no voice at all is exit 1 up front. `--purge-others` first deletes the cached clips outside the set — another voice's after a voice change, but also ad-hoc or earlier `--stage` texts, one re-synthesis each at the next tap (it keeps every accent in use, `--accent` or not) — so run it only after the service was restarted with the new voice (its log event `audio_voice` names the voice; the plan line names the CLI's — they must agree); a purge during a playback can cost that one load. `--texts FILE` synthesises the texts of a UTF-8 file instead (one per line — the output of `audio-texts` on a host that serves a read-only `cache`; both accents unless `--accent` says; not with `--stage` / `--purge-others` / `--db`, so its `--dry-run` prints no purge preview; an unreadable file is exit 2). Refuses below schema 14 like `learn-order`; exit 2 without a provider or a database, or under `WD_AUDIO_PROVIDER=cache` (that host does not synthesise). Safe next to the live service, whose running total is re-counted from disk at the first synthesis after five minutes (`SCAN_INTERVAL_S`) — `docs/releases/2026-11-server-audio.md` §6) · `audio-texts [--stage S …] [--db PATH]` (print the texts `audio-prewarm` would synthesise on this host, one per line on stdout, the count on stderr — run on the server that serves a read-only `cache`, feed the file to `audio-prewarm --texts` on the host with `say`, then `rsync` `audio/` back; ops.md §5; refused texts are left out of stdout and counted on stderr; exit 1 below schema 14, 2 without a database, like `audio-prewarm` — `docs/releases/2026-11-server-audio.md` §7) [`wd.audio`].

## 10. Upgrade and rollback

Upgrade: `cd /home/sqin/word-Dance && git pull && deploy/install.sh` — deps, frontend (built into `$WD_DATA_DIR/frontend-releases/<sha>.new`), then **the unit is stopped**, the snapshot is published (`frontend` symlink → `frontend-releases/<sha>` with one atomic rename; the two newest snapshots are kept), migrations run with the pre-migrate snapshot, and the unit is started again (downtime ≈ the migration time + 3 s, typically < 30 s; in-flight jobs are recovered by the stale-lock sweep; a `claude` call in flight is allowed up to `TimeoutStopSec=300` to finish). With `--no-restart` the service keeps running during `wd migrate`, which is safe **only for purely additive migrations** (new tables/columns/indexes, e.g. `0008_fk_child_indexes.sql`, `0012_word_images_meta.sql`, `0014_learn_rank.sql`, `0015_dance_mode.sql`, `0017_word_dances_corrected.sql`, `0018_auth_identities.sql`, `0019_family.sql`, `0020_wechat_tickets.sql`; never `DROP`/`RENAME`/type changes — `0011_primary_stage.sql`, `0013_word_forms_alias.sql` and `0016_word_dances.sql` are table rebuilds, §5) — install.sh prints that note. The same applies without passwordless `sudo -n` (§2): the script detects the running unit anyway but cannot stop or restart it, prints the note plus a `WARN` that the OLD version keeps serving, and its last line tells you to run `sudo systemctl restart word-dance` instead of claiming success — stop the unit yourself before re-running when a pending migration is not additive. **Before the upgrade that brings migration 0010** (the fallback provider): a deployment that opted into the CLI's `--fallback-model` must rename `WD_AI_FALLBACK_MODEL="…"` to `WD_AI_CLI_FALLBACK_MODEL="…"` in `.env` first — the old key now names the fallback *provider's* model (§4) and `wd migrate` / `wd serve` refuse to start with a `ConfigError` naming the move otherwise, which would leave the unit stopped at step 7; the shipped empty value needs nothing. A table rebuild (the only way to change a CHECK list in SQLite) is an ordinary stop-first migration: the runner turns foreign-key enforcement off around the file and runs `foreign_key_check` before committing (§5), so the rebuild keeps every child row. Rollback: `git checkout <previous tag> && deploy/install.sh` (stops, migrates nothing new, restarts); if a migration must be undone, `sudo systemctl stop word-dance && wd restore backups/pre-migrate-*.db.gz && sudo systemctl start word-dance`. If the data directory was moved (ops.md §5), every `deploy/install.sh` run here keeps working without a variable: when `WD_DATA_DIR` is unset the script takes the directory from the installed unit's `EnvironmentFile=` line (step 0, §2) and prints `data dir from the installed unit: …` — the older rule (`WD_DATA_DIR=<dir>` required on every run, else a fresh, empty instance at the default path) no longer applies. An explicit `WD_DATA_DIR=<dir>` is fine when it names the unit's directory (the ops.md §5 profile export) and is refused with exit 2 when it does not — a stale export or a typo; only the move procedure passes a different value, and it does so with `--move-data`.

**The live UI is a snapshot in the data directory, not the checkout's build output.** `wd serve` reads `WD_FRONTEND_DIST=$WD_DATA_DIR/frontend` (filled into `.env` once by install.sh, §4), a symlink to `frontend-releases/<sha>` that only step 6 of install.sh replaces — after the unit is stopped, with one atomic rename. Running `make test` or `npm run build` in the checkout writes `<repo>/frontend/dist` and changes nothing the service serves (before this, the service read `<repo>/frontend/dist` directly: a gate run on the checkout hot-swapped the SPA under the running pre-upgrade backend — new UI against the old API — and open tabs lost their lazy chunks whenever the hashed asset names changed under them). A re-run on the same commit builds into `<sha>.new` and swaps it in after the stop, so the live tree is never rebuilt in place either. Rollback of the UI alone (a bad build, API unchanged): `ls -1t /home/sqin/word-dance-data/frontend-releases` (newest first; the second entry is the previous release) → `cd /home/sqin/word-dance-data && ln -sfn frontend-releases/<previous sha> frontend.tmp && mv -T frontend.tmp frontend && sudo systemctl restart word-dance` — the process resolves the symlink at startup, so the restart is part of the rollback (`git checkout <previous tag> && deploy/install.sh` does the same inside a full rollback). The first upgrade of a deployment whose `.env` still has `WD_FRONTEND_DIST=""` fills that one line (`sed -i`, printed by `--dry-run`) and creates `frontend` + `frontend-releases/`; the stale `<repo>/frontend/dist` is no longer read (`make clean` removes it).

## 11. Runbook highlights (`docs/ops.md`)

| Situation | What you see | Action |
|---|---|---|
| Claude not logged in / token expired (`auth`) | admin banner 「Claude CLI 未登录，请以 sqin 身份运行 claude 完成登录」 (`failover.banner_for`), `system_events claude_auth`, CLI paused for `WD_AI_FAILOVER_COOLDOWN_MIN`; mode `claude_cli` — or `auto` while no provider can take content (fallback unconfigured / paused / marked `'0'`, or `content` removed from `WD_AI_FALLBACK_KINDS`): jobs queued until the pause ends, UI runs on dictionary data; mode `auto` with a usable fallback: the group reruns on the fallback at once (`ai_failover` event, content in groups of `WD_AI_FALLBACK_BATCH_SIZE`) and learners get fallback-generated example sentences; mode `split`: only the operator's groups (prewarm content, `wd dance-annotate`, requested SVGs) wait for the pause — the learners' lookups / cards / consolidations keep running on the fallback, and the probe lifting the pause releases those groups (no fail-back requeue) (`word_contents.model` = the vendor id, e.g. `glm-4.7-flash`; ledger 「来源」 = fallback); prewarm groups (priority ≥ 90) and `svg` keep waiting for the CLI | `sudo -iu sqin claude` (interactive login) → `wd claude-check` (a successful probe or CLI call lifts the pause, fails back and requeues the content / lookup jobs that died during the outage — their words back to `queued`, CLAUDE_INTEGRATION §10.6) → `POST /api/admin/ai/pause {paused:false}` only if the admin pause is set |
| Claude account out of balance (`balance:` — 402 / `insufficient balance` / 余额不足 in the CLI output; the CLI path emits only the `balance:` and `network:` prefixes, never `quota:`) | banner 「Claude 账户余额不足或配额用尽，请充值后运行 wd claude-check」 (`failover.banner_for('balance')`), `claude_auth` event, CLI paused 24 h (mode `auto`: the fallback serves meanwhile) | top up → `wd claude-check` — any successful CLI call or probe lifts the pause early and releases the parked jobs; `POST /api/admin/ai/pause {paused:false}` lifts every pause and `'0'` mark at once |
| Fallback provider paused or unavailable (`ai_fallback_paused` event: Zhipu 1308 quota window → `quota:` until `retry_at`, 1113 / 402 → `balance:` 24 h, auth / 403 → the cooldown, six overloads → 15 min; `ai_fallback_quality` event: three unusable answers in a row, retries included → the cooldown as a **quality pause**, `kv.ai.fallback.pause_reason='quality'`; `fallback_unavailable` event and `ai.fallback.available='0'` after a 404, an unknown model or a missing key / URL — `not_found:` / `spawn_error`) | AI tab 「备用模型已暂停」 or 不可用 next to 当前提供方 (`AdminOverview.ai.fallback_paused_until` / `fallback_available`); no banner — the `claude_auth` banners are CLI-only; mode `split` sends the `fallback_paused` webhook 「学习者的备用模型已暂停」 on every fallback pause (it is the learners' only provider there); a quality pause sends 「备用模型输出异常，已暂停」 (its last sentence says whether Claude is paused, unconfirmed or back); in mode `auto` with the CLI paused too, the admins' webhook says 「AI 暂时不可用」 | wait for `retry_at` / fix the key, URL or model → 「探测备用」 or `wd ai-check --provider fallback` (a success lifts the pause and the mark — a quality pause only through a probe, an applied group or the resume, never through an ordinary call; a transient probe failure never re-marks `'0'`) or resume via `POST /api/admin/ai/pause {paused:false}` |
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
