#!/usr/bin/env bash
# Run Habeny in the foreground from a checkout (development and quick trials; for a
# server, install it as a service: see README "Installation").
#
#   ./start.sh          Serve everything on :9000, building the frontend first if needed
#   ./start.sh --dev    API on :9000 and Vite dev server with hot reload on :3000
#
# Node.js (20.19+ or 22.12+) is only needed for --dev or when the frontend has to be
# (re)built; with a prebuilt static/ (release tarballs include one) it isn't.
# Settings: /etc/habeny/habeny.conf or HABENY_* environment variables (`python3 -m app.cli config`).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND="$ROOT/frontend"
STATIC_INDEX="$ROOT/static/index.html"

require_node() {
    # Vite needs Node.js 20.19+ or 22.12+
    if ! command -v npm >/dev/null 2>&1 || ! node -e 'const [a, b] = process.versions.node.split(".").map(Number); process.exit((a === 20 && b >= 19) || (a === 22 && b >= 12) || a >= 23 ? 0 : 1)' 2>/dev/null; then
        echo "error: $1 needs Node.js 20.19+ or 22.12+ (found $(node -v 2>/dev/null || echo none)). Install it:" >&2
        echo "         curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -" >&2
        echo "         sudo apt install -y nodejs" >&2
        echo "       or use a release tarball, which has the frontend prebuilt." >&2
        exit 1
    fi
    if [ ! -d "$FRONTEND/node_modules" ]; then
        echo "==> Installing frontend dependencies"
        npm --prefix "$FRONTEND" ci
    fi
}

if [ "${1:-}" = "--dev" ]; then
    require_node "The dev server"
    echo "==> Starting API server on https://0.0.0.0:9000"
    python3 "$ROOT/main.py" &
    API_PID=$!
    trap 'kill "$API_PID" 2>/dev/null || true' EXIT INT TERM

    echo "==> Starting frontend dev server on http://0.0.0.0:3000"
    npm --prefix "$FRONTEND" run dev -- --host
    exit $?
fi

# Build when there's no build yet, or (in a checkout) the frontend sources changed since
# the last one. A release's prebuilt frontend (static/.habeny-build) is used as is.
if [ ! -f "$STATIC_INDEX" ]; then
    require_node "Building the frontend"
    echo "==> Building frontend"
    npm --prefix "$FRONTEND" run build
elif [ ! -f "$ROOT/static/.habeny-build" ] && [ -n "$(find "$FRONTEND/src" "$FRONTEND/index.html" \
        "$FRONTEND/package.json" "$FRONTEND/vite.config.js" "$ROOT/app/version.py" -newer "$STATIC_INDEX" -print -quit)" ]; then
    require_node "Rebuilding the frontend (its sources changed)"
    echo "==> Rebuilding frontend"
    npm --prefix "$FRONTEND" run build
fi

exec python3 "$ROOT/main.py"
