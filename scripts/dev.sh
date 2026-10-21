#!/usr/bin/env bash
# scripts/dev.sh — `make dev` (docs/DEPLOY.md §8): backend with auto-reload on :8000 + Vite dev server on :5173.
#
#   WD_DEV=1 WD_DATA_DIR=./.dev-data WD_REGISTRATION_MODE=open WD_CLAUDE_BIN=./backend/tests/fake_claude.py \
#     .venv/bin/uvicorn wd.main:create_app --factory --reload --port 8000  &  (cd frontend && npm run dev)
#
# The fake claude costs nothing and needs no network. WD_DEV_REAL_CLAUDE=1 uses the real, authenticated CLI
# instead (spends money). DEV_PORT / DEV_DATA_DIR override the port and the data directory (the Vite proxy in
# frontend/vite.config.ts targets http://127.0.0.1:8000, so change the port only together with that file).
set -euo pipefail
REPO=$(cd "$(dirname "$0")/.." && pwd)
cd "$REPO"

PORT=${DEV_PORT:-8000}
DATA=${DEV_DATA_DIR:-$REPO/.dev-data}
UVICORN=$REPO/.venv/bin/uvicorn
[ -x "$UVICORN" ] || { echo "scripts/dev.sh: $UVICORN not found — run 'make setup' first" >&2; exit 2; }
[ -d "$REPO/frontend/node_modules" ] || { echo "scripts/dev.sh: frontend/node_modules missing — run 'make setup' (npm ci) first" >&2; exit 2; }

mkdir -p "$DATA"
export WD_DEV=1
export WD_DATA_DIR="$DATA"
export WD_REGISTRATION_MODE=open
export PYTHONPATH="$REPO/backend${PYTHONPATH:+:$PYTHONPATH}"
if [ "${WD_DEV_REAL_CLAUDE:-0}" = 1 ]; then
  echo "dev.sh: WD_DEV_REAL_CLAUDE=1 — using the real claude CLI (${WD_CLAUDE_BIN:-/home/sqin/.local/bin/claude}); every job spends money"
else
  export WD_CLAUDE_BIN="$REPO/backend/tests/fake_claude.py"
fi

echo "dev.sh: backend http://127.0.0.1:$PORT (data dir $DATA, registration open) — frontend http://localhost:5173"
"$UVICORN" wd.main:create_app --factory --reload --reload-dir "$REPO/backend/wd" --port "$PORT" &
UV=$!
trap 'kill "$UV" 2>/dev/null || true; wait "$UV" 2>/dev/null || true' EXIT INT TERM

cd "$REPO/frontend" && npm run dev
