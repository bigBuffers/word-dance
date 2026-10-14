# word-Dance — Deployment and operations (Ubuntu 24.04, this box)

Facts this relies on (FACTS §1/§3): Ubuntu 24.04.4, Python 3.12.3 with `python3.12-venv` (PEP 668 → venv mandatory), Node 22.22.2 / npm 10.9.7, systemd 255, passwordless `sudo -n`, `loginctl` Linger=**no** (so a `systemctl --user` unit would die at logout → we use a **system** unit running as `sqin`), `claude` 2.1.299 at `/home/sqin/.local/bin/claude` authenticated for `sqin` (credentials in `/home/sqin/.claude*`, no `ANTHROPIC_API_KEY`), ports 8000/80/443 free, 92 GB free on `/home`.

## 1. Layout on the box

| Path | Purpose | Mode / owner |
|---|---|---|
| `/home/sqin/word-Dance` | git checkout (code only; safe to `git pull`) | sqin |
| `/home/sqin/word-Dance/.venv` | Python venv (gitignored) | sqin |
| `/home/sqin/word-Dance/frontend/dist` | built SPA (gitignored) | sqin |
| `/home/sqin/word-dance-data` (`WD_DATA_DIR`) | **all runtime state**, outside the checkout | 0700 sqin |
| `…/word-dance-data/.env` | config + secrets (`EnvironmentFile`) | 0600 sqin |
| `…/word-dance-data/word-dance.db` (+`-wal`,`-shm`) | SQLite | 0600 |
| `…/word-dance-data/images/<2hex>/<sha>.jpg\|.svg` | cached media | 0600 |
| `…/word-dance-data/claude-cwd/` | empty cwd for `claude -p` | 0700 |
| `…/word-dance-data/claude-logs/YYYY-MM-DD/` | raw CLI stdout/stderr, 14 days | 0600 |
| `…/word-dance-data/backups/` | `word-dance-YYYYMMDD-HHMM.db.gz`, `pre-migrate-<v>.db.gz` | 0600 |
| `…/word-dance-data/tmp/` | downloads in flight (cleared at start) | 0700 |
| `/etc/systemd/system/word-dance.service`, `word-dance-backup.{service,timer}` | units (installed with sudo) | root |

`UMask=0077` in the units plus `os.umask(0o077)` in `wd serve` guarantee the modes above. `git clean -fdx` in the checkout can never destroy data.

## 2. `deploy/install.sh` (idempotent; run as `sqin` from the checkout; `sudo -n` only for systemd/proxy files)

```bash
#!/usr/bin/env bash
# usage: deploy/install.sh [--with-caddy DOMAIN | --with-nginx DOMAIN] [--with-ecdict] [--no-restart] [--dry-run] [--contact-email ADDR]
#        options may be given in any order and combined, e.g. deploy/install.sh --with-ecdict --with-caddy words.example.com --no-restart
set -euo pipefail
REPO=$(cd "$(dirname "$0")/.." && pwd)
DATA=${WD_DATA_DIR:-/home/sqin/word-dance-data}
RUN_USER=${RUN_USER:-$(id -un)}            # must be the user whose `claude` CLI is authenticated (sqin)
PY=python3
PROXY=""; DOMAIN=""; ECDICT=0; NO_RESTART=0; DRY=0; CONTACT=${WD_CONTACT_EMAIL:-}
while [ $# -gt 0 ]; do
  case "$1" in
    --with-caddy|--with-nginx) PROXY=${1#--with-}; DOMAIN=${2:?domain required after $1}; shift;;
    --with-ecdict)   ECDICT=1;;
    --no-restart)    NO_RESTART=1;;
    --dry-run)       DRY=1;;
    --contact-email) CONTACT=${2:?address required after --contact-email}; shift;;
    -h|--help)       sed -n '2,3p' "$0"; exit 0;;
    *) echo "unknown option: $1"; sed -n '2,3p' "$0"; exit 64;;
  esac
  shift
done
log(){ printf '\n==> %s\n' "$*"; }
run(){ if [ "$DRY" = 1 ]; then echo "+ $*"; else "$@"; fi; }     # EVERY mutating step goes through run(); --dry-run prints them and changes nothing

# 1. preflight (read-only) -------------------------------------------------
log "preflight"
$PY -c 'import sys; assert sys.version_info >= (3,12), sys.version'
$PY -c 'import venv, ensurepip, sqlite3, zoneinfo'          # python3.12-venv present (verified)
node --version | grep -Eq '^v(2[2-9]|[3-9][0-9])' || { echo "Node >= 22 required"; exit 1; }
CLAUDE_BIN=$(command -v claude || true)
[ -n "$CLAUDE_BIN" ] || { echo "claude CLI not found in PATH for $RUN_USER (expected /home/sqin/.local/bin/claude)"; exit 1; }
[ "$(df --output=avail -m /home | tail -1)" -gt 2048 ] || { echo "need > 2 GB free on /home"; exit 1; }
[ -f "$REPO/frontend/package-lock.json" ] || { echo "frontend/package-lock.json missing (npm ci needs it)"; exit 1; }
sudo -n true 2>/dev/null && HAVE_SUDO=1 || { HAVE_SUDO=0; echo "WARN: no passwordless sudo — systemd steps will be printed, not executed"; }

# 2. data dir -------------------------------------------------------------
log "data dir $DATA"
run install -d -m 0700 "$DATA" "$DATA/images" "$DATA/claude-cwd" "$DATA/claude-logs" "$DATA/backups" "$DATA/tmp"

# 3. backend venv ---------------------------------------------------------
log "python venv"
[ -d "$REPO/.venv" ] || run $PY -m venv "$REPO/.venv"
run "$REPO/.venv/bin/pip" install --quiet --upgrade pip wheel
run "$REPO/.venv/bin/pip" install --quiet -r "$REPO/backend/requirements.txt"
run "$REPO/.venv/bin/pip" install --quiet -e "$REPO/backend"          # provides the `wd` console script ([build-system] setuptools, TASKS P0)

# 4. frontend build -------------------------------------------------------
log "frontend build"
run bash -c "cd '$REPO/frontend' && npm ci --silent && npm run build --silent"      # → frontend/dist

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
if [ -n "$PROXY" ]; then
  run sed -i "s|^WD_HOST=.*|WD_HOST=\"127.0.0.1\"|; s|^WD_PUBLIC_URL=.*|WD_PUBLIC_URL=\"https://$DOMAIN\"|; s|^WD_TRUST_PROXY=.*|WD_TRUST_PROXY=\"1\"|" "$DATA/.env"
elif grep -Eq '^WD_PUBLIC_URL=("")?$' "$DATA/.env"; then
  # no proxy and no public URL yet → the LAN URL, so e-mail buttons / webhook `url` fields have a target (DESIGN §6.5); the CSRF check
  # also accepts the Host-derived origin (API.md §1), so reaching the site by hostname keeps working
  LAN_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
  PORT=$(sed -n 's/^WD_PORT="\{0,1\}\([0-9][0-9]*\)"\{0,1\}$/\1/p' "$DATA/.env"); PORT=${PORT:-8000}
  [ -n "$LAN_IP" ] && run sed -i "s|^WD_PUBLIC_URL=.*|WD_PUBLIC_URL=\"http://$LAN_IP:$PORT\"|" "$DATA/.env"
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
if [ "$HAVE_SUDO" = 1 ] && systemctl is-active --quiet word-dance.service 2>/dev/null; then
  if [ "$NO_RESTART" = 0 ]; then
    run sudo -n systemctl stop word-dance.service        # an upgrade: the previous version must not keep serving while the schema changes,
  else                                                   # and the pre-migrate `VACUUM INTO` must not race live writes; step 7 starts it again
    echo "NOTE: --no-restart: the running service is kept; pending migrations must be purely ADDITIVE (new tables/columns/indexes only) — DEPLOY §10"
  fi
fi
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
  echo "run as root:"; echo "  install units from $REPO/deploy into /etc/systemd/system, then: systemctl daemon-reload && systemctl enable --now word-dance word-dance-backup.timer"
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
if [ -n "${WD_PUBLIC_URL:-}" ]; then echo "word-Dance is running at $WD_PUBLIC_URL";
else echo "word-Dance is running at http://$(hostname -I | awk '{print $1}'):${WD_PORT:-8000}  (bind ${WD_HOST:-0.0.0.0})"; fi
echo "registration mode: ${WD_REGISTRATION_MODE:-invite} — the first account registered becomes admin; afterwards create invite codes with: $REPO/.venv/bin/wd invite --uses 5 --days 7"
```

Behaviour: re-running after `git pull` upgrades dependencies, rebuilds the frontend, **stops the running unit** (unless `--no-restart`), applies new migrations (with a pre-migrate snapshot), starts the unit again, and never touches `.env` (apart from filling an empty `WD_PUBLIC_URL` with the LAN URL on a proxy-less install), the DB or images. `.env` is validated before it is sourced: every line must be `KEY="value"` (§4).

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
Group=__USER__
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
* `wd serve` = `uvicorn.run("wd.main:create_app", factory=True, host=WD_HOST, port=WD_PORT, workers=1, limit_concurrency=200, proxy_headers=WD_TRUST_PROXY, forwarded_allow_ips="127.0.0.1", log_config=None)`; `main.py` refuses `workers != 1` and takes the `kv.worker_lease` (a second `wd serve` idles with a warning).

```ini
# deploy/word-dance-backup.service
[Unit]
Description=word-Dance nightly backup (VACUUM INTO + integrity_check + gzip)
[Service]
Type=oneshot
User=__USER__
Group=__USER__
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
| `WD_SEED_PATH` | `<repo>/data/seed/vocab.jsonl.gz` (= `Path(wd.__file__).parents[2] / 'data/seed/vocab.jsonl.gz'`) | the shipped seed; default of `wd import-seed --file` and of the lifespan seed check (`kv.seed_version` vs the file's sha256). Correct for the editable install install.sh performs; a non-editable install must set it |
| `WD_TRUST_PROXY` | `0` | honour the first `X-Forwarded-For` / `X-Forwarded-Proto` hop |
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
| `WD_CLAUDE_BIN` | `/home/sqin/.local/bin/claude` | absolute path set by install.sh |
| `WD_CLAUDE_HOME` / `WD_CLAUDE_PATH` / `WD_CLAUDE_CWD` | `$HOME` / `/home/sqin/.local/bin:/usr/local/bin:/usr/bin:/bin` / `$WD_DATA_DIR/claude-cwd` | child environment (CLAUDE_INTEGRATION.md §1.3) |
| `WD_AI_ENABLED` | `1` | kill switch |
| `WD_AI_MODEL` / `WD_AI_FALLBACK_MODEL` / `WD_AI_EXTRA_ARGS` | `sonnet` / (empty) / (empty) | fallback off by default |
| `WD_AI_BATCH_SIZE` / `WD_AI_CONCURRENCY` | `10` / `1` | **1–12** (clamped in `config.py`: `content_v1.json` has `items.maxItems: 12`, CLAUDE_INTEGRATION §4) / 1–3 |
| `WD_AI_TIMEOUT_CONTENT_SEC` / `_LOOKUP_SEC` / `_CONSOLIDATE_SEC` / `_SVG_SEC` | `180` / `120` / `240` / `120` | |
| `WD_AI_BUDGET_CONTENT` / `_LOOKUP` / `_CONSOLIDATE` / `_SVG` | `0.25` / `0.15` / `0.40` / `0.10` | `--max-budget-usd` per call |
| `WD_AI_DAILY_BUDGET_USD` / `WD_AI_MONTHLY_BUDGET_USD` | `3.00` / `40.00` | measured $0.004/word → ≈ 750 words/day |
| `WD_AI_PREWARM_DAILY_BUDGET_USD` / `WD_AI_HOURLY_CALL_CAP` | `1.00` / `60` | |
| `WD_AI_SVG_DAILY_BUDGET_USD` | `0.50` | daily sub-cap for Claude-drawn SVG concept cards (≈ 18 cards/day at the measured $0.028), counted inside the daily cap; `0` disables SVG generation without turning the feature off (CLAUDE_INTEGRATION §7) |
| `WD_AI_LOG_KEEP_DAYS` | `14` | raw CLI logs |
| `WD_ECDICT_DB_PATH` | (empty) | optional full `stardict.db` (851 MB) for instant lookups of words outside the seed |
| `WD_IMAGES_ENABLED` | `1` | |
| `WD_IMAGE_PROVIDERS` | `wikimedia,openverse` | ordered chain; `pixabay`/`pexels` appended when keys exist |
| `WD_SVG_VIA_CLAUDE` | `1` | Claude-drawn SVG concept card when no acceptable photo is found, for words a user actually studies (never prewarm), budgeted by `WD_AI_SVG_DAILY_BUDGET_USD`; the text-only template card is the final fallback. `0` = photos or the template card only (then 配图 is satisfied only when a photo is found — the admin overview shows the `card_only` share) |
| `WD_IMAGE_MAX_BYTES` / `WD_IMAGE_MAX_EDGE` | `8000000` / `800` | |
| `WD_WIKIMEDIA_MIN_INTERVAL_MS` / `WD_WIKIMEDIA_DAILY_LIMIT` | `1000` / `2000` | politeness |
| `WD_OPENVERSE_MINUTE_LIMIT` / `WD_OPENVERSE_DAILY_LIMIT` | `15` / `160` | anonymous limits are 20/min, 200/day |
| `WD_OPENVERSE_CLIENT_ID` / `WD_OPENVERSE_CLIENT_SECRET` | (empty) | optional registered app (raises limits) |
| `WD_PIXABAY_KEY` / `WD_PEXELS_KEY` | (empty) | optional providers |
| `WD_SMTP_HOST` / `WD_SMTP_PORT` / `WD_SMTP_USER` / `WD_SMTP_PASSWORD` / `WD_SMTP_FROM` / `WD_SMTP_TLS` | (empty) / `587` / … / `starttls` | e-mail channel enabled when host + from are set (`starttls` / `ssl` / `none`) |
| `WD_LOG_LEVEL` / `WD_LOG_FORMAT` / `WD_LOG_FILE` | `INFO` / `json` / (empty) | |
| `WD_BACKUP_KEEP_DAILY` / `WD_BACKUP_KEEP_WEEKLY` | `14` / `8` | |
| `WD_ADMIN_USERNAME` / `WD_ADMIN_PASSWORD` | (empty) | unattended `wd create-admin --if-none`; remove the password afterwards |
| `WD_DEV_REAL_CLAUDE` | `0` | dev only (`scripts/dev.sh`): `1` uses the real CLI instead of `tests/fake_claude.py` |
| `WD_SMOKE_MOCK_HTTP` | `0` | tests/smoke only: `1` routes image-provider HTTP through `httpx.MockTransport` fixtures |

Secrets never leave `.env`; `GET /api/admin/config` masks them.

**Quoting rule for `.env` (binding, stated at the top of `deploy/env.example`)**: the same file is read by three parsers — bash (`set -a; . .env` in install.sh), systemd `EnvironmentFile=` and python-dotenv (dev/tests) — whose unquoted-value rules differ (bash would *execute* `low` for `WD_AI_EXTRA_ARGS=--effort low`). Therefore every value is written **double-quoted**, `KEY="value"`, which all three accept identically for ordinary values (`WD_AI_EXTRA_ARGS="--effort low"`); a secret containing `$`, `` ` `` or `\` is written **single-quoted** (`WD_SMTP_PASSWORD='p$ss'`), literal in all three parsers; `#` starts a comment only at the beginning of a line. install.sh runs `bash -n` plus a line-shape check (`^WD_[A-Z0-9_]+=("[^"$`\\]*"|'[^']*')$`) before sourcing and aborts with the offending line(s). `env.example` ships every variable of this table in that form with its default.

## 5. Backups and restore (`backend/wd/backup.py` owns CLI `wd backup|restore` and the `snapshot_before_migrate` hook; `wd migrate` itself lives in `cli.py`, TASKS P0)

* `wd backup --keep-daily N --keep-weekly M`: `VACUUM INTO '$DATA/tmp/word-dance-<ts>.db'` (consistent online snapshot under WAL) → `PRAGMA integrity_check` on the copy (abort + `system_events('backup_failed')` + non-zero exit if not `ok`) → gzip → `$DATA/backups/word-dance-YYYYMMDD-HHMM.db.gz` (0600) → retention: newest N daily + Sunday copies up to M weekly → `kv.backup.last = {file, at, bytes}` (shown in admin health). Images are re-fetchable and not backed up by default; `--with-images` adds `images-YYYYMMDD.tar`. The same flags are used everywhere (timer unit, DESIGN §11, WP9 acceptance).
* `wd migrate [--dry-run]` (`cli.py` → `db.run_migrations(pre_hook=wd.backup.snapshot_before_migrate)`, the hook late-imported and skipped with a warning if `backup.py` is absent during Phase 0): pending = `backend/wd/migrations/NNNN_*.sql` whose `NNNN` is not in `schema_migrations`; before applying the first pending file it writes `backups/pre-migrate-<from>-to-<to>.db.gz` (same pipeline); each file then runs inside one `BEGIN IMMEDIATE` transaction and **the runner inserts `schema_migrations(version, name)` in that same transaction** — migration files never self-register (SCHEMA.sql §1/§10), so a fresh install cannot hit a duplicate-key crash and a half-applied file rolls back together with its bookkeeping row. This atomicity holds only because `db.connect()` opens the connection with `sqlite3.connect(path, autocommit=True)` (Python 3.12) and the runner issues `BEGIN IMMEDIATE`/`COMMIT`/`ROLLBACK` explicitly — in the legacy default mode `conn.executescript()` commits implicitly before running the file (verified on this box), silently ending the transaction (TASKS P0 step 4 + its unit test). `--dry-run` lists pending files only. install.sh stops the running unit before `wd migrate` (unless `--no-restart`, §2/§10).
* `wd restore <file.db.gz> [--yes]`: refuses while the service runs (checks `kv.worker_lease` expiry and `systemctl is-active`); moves the current DB to `word-dance.db.bak-<ts>`, gunzips, runs `integrity_check`, removes stale `-wal/-shm`, prints `sudo systemctl start word-dance`.
* Off-box copies: `rsync -a --delete /home/sqin/word-dance-data/backups/ user@host:/backups/word-dance/` from any cron on another machine (documented in `docs/ops.md`).
* Monthly drill (ops.md): restore into `$DATA/tmp` and run `wd check --db <path>`.

## 6. Logs

JSON lines to stdout → journald: `journalctl -u word-dance -f`, `--since today`, `-p warning`. Fields: `ts level logger msg request_id user_id method path status duration_ms job_id job_type worker cost_usd provider event`. One line per request at INFO (health checks at DEBUG); bodies never logged; prompts only at DEBUG (word lists). Optional `WD_LOG_FILE` adds a `RotatingFileHandler(50 MB × 5)`. Raw `claude` output under `claude-logs/` for 14 days (pruned by maintenance). `wd logs --tail 200` prints the in-memory ring buffer (2000 lines) for quick debugging.

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

The app itself sets CSP/HSTS/nosniff/Referrer-Policy/frame-ancestors (DESIGN §10); with `WD_TRUST_PROXY=1` the client IP is the first `X-Forwarded-For` hop and `X-Forwarded-Proto=https` makes cookies `Secure`.

## 8. Development workflow

```
make setup   # python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt -r backend/requirements-dev.txt -e backend && (cd frontend && npm ci)
make dev     # scripts/dev.sh: WD_DEV=1 WD_DATA_DIR=./.dev-data WD_REGISTRATION_MODE=open WD_CLAUDE_BIN=./backend/tests/fake_claude.py \
             #   .venv/bin/uvicorn wd.main:create_app --factory --reload --port 8000  &  (cd frontend && npm run dev)   # vite :5173 proxies /api,/media
             #   set WD_DEV_REAL_CLAUDE=1 to use the real CLI while developing (spends money)
make test    # .venv/bin/pytest -q backend/tests && (cd frontend && npm run typecheck && npm test && npm run build)
make smoke   # scripts/smoke.py: throwaway data dir, port 8010, fake claude, mocked image providers (WD_SMOKE_MOCK_HTTP=1), registration open
make seed    # python3 -I scripts/build_seed.py --db <stardict.db> --lists <mahavivo dir> --out data/seed && gzip -9 -k -f data/seed/vocab.jsonl  (only when regenerating)
make install # deploy/install.sh
```

`WD_DEV=1` relaxes nothing security-relevant except the dev origin and the docs route. The seed build inputs (ECDICT `stardict.db` 851 MB, mahavivo lists) are **not** needed at deploy time; `data/seed/vocab.jsonl.gz` ships in the repo.

## 9. CLI reference (`wd …`, console script from `backend/pyproject.toml`; owning module in brackets — `cli.py` calls `register_cli(sub)` on each module of `CLI_MODULES`, TASKS P0 step 4)

`serve` · `migrate [--dry-run]` · `version` [`wd.cli` itself] · `import-seed [--file PATH (default: WD_SEED_PATH)] [--force]` [`wd.seed`, WP1] · `create-admin [--if-none] [--username U] [--password-env VAR]` · `set-password <username>` · `promote|demote <username>` · `invite [--uses N] [--days D] [--note …]` (prints the code once) [`wd.security`, WP2] · `claude-check` [`wd.ai.probe`, WP5] · `backup [--keep-daily N] [--keep-weekly M] [--with-images]` · `restore <file> [--yes]` [`wd.backup`, WP9] · `worker-once` (drain the queue synchronously; dev/smoke **only** — refuses with exit 2 and the hint 「word-dance.service is running — watch `journalctl -u word-dance -f` or GET /api/admin/jobs」 while `kv.worker_lease` is live, exactly like `restore`, because a second claimer next to the service gets its jobs swept and re-run — CLAUDE_INTEGRATION §6.2) [`wd.jobs.worker`, WP5] · `tick [--once]` (run the scheduler tick; dev/tests; same lease refusal) [`wd.jobs.scheduler`, WP4] · `build-batch <username> [--date YYYY-MM-DD]` · `push-now <username>` [`wd.services.batches`, WP4] · `consolidate <username>` [`wd.ai.consolidate`, WP5] · `fetch-image <word> [--provider P]` (manual image fetch, logs the attribution) · `images-prune --unused-days N` (delete cached files of words in no bank and no batch for N days) [`wd.images.handler`, WP6] · `stats` · `check [db|claude|smtp|providers|all]` · `logs --tail N` [`wd.diag`, WP5].

## 10. Upgrade and rollback

Upgrade: `cd /home/sqin/word-Dance && git pull && deploy/install.sh` — deps, frontend, then **the unit is stopped**, migrations run with the pre-migrate snapshot, and the unit is started again (downtime ≈ the migration time + 3 s, typically < 30 s; in-flight jobs are recovered by the stale-lock sweep; a `claude` call in flight is allowed up to `TimeoutStopSec=300` to finish). With `--no-restart` the service keeps running during `wd migrate`, which is safe **only for purely additive migrations** (new tables/columns/indexes; never `DROP`/`RENAME`/type changes) — install.sh prints that note. Rollback: `git checkout <previous tag> && deploy/install.sh` (stops, migrates nothing new, restarts); if a migration must be undone, `sudo systemctl stop word-dance && wd restore backups/pre-migrate-*.db.gz && sudo systemctl start word-dance`.

## 11. Runbook highlights (`docs/ops.md`)

| Situation | What you see | Action |
|---|---|---|
| Claude not logged in / token expired | admin banner 「Claude CLI 未登录」, `system_events claude_auth`, jobs queued, UI runs on dictionary data | `sudo -iu sqin claude` (interactive login) → `wd claude-check` → `POST /api/admin/ai/pause {paused:false}` if paused |
| Daily AI cap reached | `budget_daily` event; cards say 「今日 AI 额度已用完」 | raise `WD_AI_DAILY_BUDGET_USD` + restart, or wait for the next `WD_TZ` day |
| Many words show the text-only card (low photo hit rate) | admin overview `words.card_only` high vs `with_photo`/`with_claude_svg`; `budget_svg` event when the SVG sub-cap is hit | raise `WD_AI_SVG_DAILY_BUDGET_USD` (each card ≈ $0.028) + restart; or add a keyed provider (`WD_PIXABAY_KEY`/`WD_PEXELS_KEY`); or register an Openverse app key |
| Fresh install, nobody can log in | `GET /api/health` → `needs_setup:true`; login page says 「尚无账号，首个注册的账号将成为管理员」 | open the site and register — the first account becomes admin without an invite code; or `wd create-admin` on the box |
| Openverse 429 | provider cooldown in admin overview | nothing; Wikimedia continues; optionally register an Openverse app key |
| Disk low | admin health `disk_free_bytes` | prune `images/` of words nobody studies (`wd images-prune --unused-days 365`, ops.md) or move `WD_DATA_DIR` |
| Service down for days | first tick builds **today's** batches only; `downtime` event; history shows 「服务器离线」 | nothing |
| Restore needed | — | §5 |
| Rotate secrets | — | edit `.env`, `sudo systemctl restart word-dance` |
| Flag tier fell back to 0 | `claude_probe_fallback` event | inspect the stderr excerpt; upgrade the CLI or keep tier 0 (fully functional) |
