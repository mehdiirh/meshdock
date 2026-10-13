#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
if [ ! -f .env ]; then python3 scripts/setup.py --demo; fi
set -a
. ./.env
set +a
export TM_DATA_DIR="$PWD/.data"
export TM_PUBLIC_ORIGIN=http://127.0.0.1:5177
export TM_COOKIE_SECURE=false
uv sync --project backend --frozen
uv run --project backend --no-sync python backend/compile_locales.py
npm --prefix frontend ci --no-audit --no-fund
(cd backend && uv run --frozen uvicorn app.main:app --host 127.0.0.1 --port 8017) &
api_pid=$!
(cd backend && uv run --frozen python -m app.worker) &
worker_pid=$!
trap 'kill "$api_pid" "$worker_pid" 2>/dev/null || true' EXIT INT TERM
npm --prefix frontend run dev
