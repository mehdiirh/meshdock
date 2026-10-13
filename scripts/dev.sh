#!/bin/sh
set -eu
usage() {
    cat <<'HELP'
Usage: ./scripts/dev.sh [--prod]

Default: demo mode; deployments are simulated and never use SSH.
--prod  Enable real server deployments using a separate local database.
--help  Show this help.

Both modes run the local development servers, not the Docker production stack.
HELP
}

case "$#:${1-}" in
    0:) tm_dev_mode=demo ;;
    1:--prod) tm_dev_mode=prod ;;
    1:--help|1:-h) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
esac
readonly tm_dev_mode

cd "$(dirname "$0")/.."
if [ ! -f .env ]; then python3 scripts/setup.py --demo; fi
set -a
. ./.env
set +a
# Apply these AFTER .env so neither it nor inherited variables can enable SSH.
case "$tm_dev_mode" in
    demo) export TM_DEMO=true ;;
    prod) export TM_DEMO=false ;;
esac
# Never share simulated jobs, topology or encrypted credentials with real mode.
export TM_DATA_DIR="$PWD/.data/$tm_dev_mode"
export TM_MASTER_KEY_FILE="$TM_DATA_DIR/master.key"
printf 'Mode: %s (TM_DEMO=%s)\nData: %s\n' "$tm_dev_mode" "$TM_DEMO" "$TM_DATA_DIR"
if [ "$tm_dev_mode" = prod ]; then
    printf '%s\n' 'Real deployments enabled: saving tunnel changes can modify your servers.'
fi
export TM_PUBLIC_ORIGIN=http://127.0.0.1:5177
export TM_COOKIE_SECURE=false
uv sync --project backend --frozen
uv run --project backend --no-sync python backend/compile_locales.py
npm --prefix frontend ci --no-audit --no-fund
(cd backend && exec uv run --frozen uvicorn app.main:app --host 127.0.0.1 --port 8017) &
api_pid=$!
(cd backend && exec uv run --frozen python -m app.worker) &
worker_pid=$!
trap 'kill "$api_pid" "$worker_pid" 2>/dev/null || true' EXIT INT TERM
npm --prefix frontend run dev
