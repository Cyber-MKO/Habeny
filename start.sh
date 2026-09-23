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
    echo "error: npm not found. Install Node.js 22 to run the frontend." >&2
    exit 1
fi

# Vite needs Node.js 20.19+ or 22.12+
if ! node -e 'const [a, b] = process.versions.node.split(".").map(Number); process.exit((a === 20 && b >= 19) || (a === 22 && b >= 12) || a >= 23 ? 0 : 1)' 2>/dev/null; then
    echo "error: Node.js 20.19+ or 22.12+ is required to run the frontend (found $(node -v 2>/dev/null || echo none))." >&2
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
