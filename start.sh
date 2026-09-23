#!/usr/bin/env bash
# Start Habeny: API server plus the React frontend.
#
#   ./start.sh          Build the frontend (if needed) and serve everything on :9000
#   ./start.sh --dev    API on :9000 and Vite dev server with hot reload on :3000
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND="$ROOT/frontend"
STATIC_INDEX="$ROOT/static/index.html"

if ! command -v npm >/dev/null 2>&1; then
    echo "error: npm not found. Install Node.js 18+ to run the frontend." >&2
    exit 1
fi

NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)"
if [ "$NODE_MAJOR" -lt 18 ]; then
    echo "error: Node.js 18+ is required to run the frontend (found $(node -v 2>/dev/null || echo none))." >&2
    echo "       Install a current version, e.g.:" >&2
    echo "         curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -" >&2
    echo "         sudo apt install -y nodejs" >&2
    exit 1
fi

if [ ! -d "$FRONTEND/node_modules" ]; then
    echo "==> Installing frontend dependencies"
    npm --prefix "$FRONTEND" ci
fi

if [ "${1:-}" = "--dev" ]; then
    echo "==> Starting API server on https://0.0.0.0:9000"
    python3 "$ROOT/main.py" &
    API_PID=$!
    trap 'kill "$API_PID" 2>/dev/null || true' EXIT INT TERM

    echo "==> Starting frontend dev server on http://0.0.0.0:3000"
    npm --prefix "$FRONTEND" run dev -- --host
    exit $?
fi

# Rebuild when there is no build yet or the frontend sources changed since the last one.
if [ ! -f "$STATIC_INDEX" ] || [ -n "$(find "$FRONTEND/src" "$FRONTEND/index.html" \
        "$FRONTEND/package.json" "$FRONTEND/vite.config.js" -newer "$STATIC_INDEX" -print -quit)" ]; then
    echo "==> Building frontend"
    npm --prefix "$FRONTEND" run build
fi

if [ "${HABENY_TLS:-auto}" = "off" ]; then SCHEME=http; else SCHEME=https; fi
echo "==> Starting Habeny on ${SCHEME}://${HABENY_HOST:-0.0.0.0}:${HABENY_PORT:-9000}"
exec python3 "$ROOT/main.py"
