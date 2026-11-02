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
