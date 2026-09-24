#!/usr/bin/env bash
# Install or upgrade Habeny from a release tarball or a git checkout, as root:
#   sudo ./deploy/install.sh [--no-start]
#
# Sets up two services: an unprivileged web app (user "habeny") and a small root helper
# that performs the LXC operations. The app is copied to $HABENY_INSTALL_DIR (default
# /opt/habeny), so the source directory can live anywhere and is left untouched.
#
# Release tarballs include the built frontend. From a git checkout, the frontend is built
# here when needed, which requires Node.js 20.19+ or 22.12+.
#
# On Debian/Ubuntu you can also install the .deb from the release instead.
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="${HABENY_INSTALL_DIR:-/opt/habeny}"
DATA_DIR="${HABENY_DATA_DIR:-/var/lib/lxc-siem-platform}"
OPTS=()
[ "${1:-}" = "--no-start" ] && OPTS+=(--no-start)

[ "$(id -u)" -eq 0 ] || { echo "Run as root: sudo $0" >&2; exit 1; }
case "$INSTALL_DIR/" in
    /home/*|/root/*)
        echo "error: HABENY_INSTALL_DIR must be outside /home and /root: the web service" >&2
        echo "       runs with ProtectHome=yes and as the 'habeny' user." >&2
        exit 1 ;;
esac
[ "$SRC_DIR" != "$INSTALL_DIR" ] || { echo "error: run this from a release or checkout, not from $INSTALL_DIR" >&2; exit 1; }
if dpkg-query -W -f='${Status}' habeny 2>/dev/null | grep -q "install ok installed"; then
    echo "error: Habeny is installed as a .deb package; upgrade it with the newer .deb instead" >&2
    exit 1
fi

echo "==> System packages"
apt-get install -y lxc lxc-utils python3-lxc python3-venv rsync >/dev/null

# Vite needs Node.js 20.19+ or 22.12+
node_ok() { node -e 'const [a, b] = process.versions.node.split(".").map(Number); process.exit((a === 20 && b >= 19) || (a === 22 && b >= 12) || a >= 23 ? 0 : 1)' 2>/dev/null; }

# The frontend: prebuilt in releases; built here from a checkout when missing or outdated
STATIC_SRC="$SRC_DIR/static"
if [ -f "$SRC_DIR/static/.habeny-build" ]; then
    echo "==> Frontend: prebuilt ($(cat "$SRC_DIR/static/.habeny-build"))"
elif [ -d "$SRC_DIR/frontend/src" ] && { [ ! -f "$SRC_DIR/static/index.html" ] || [ -n "$(find \
        "$SRC_DIR/frontend/src" "$SRC_DIR/frontend/index.html" "$SRC_DIR/frontend/package.json" \
        "$SRC_DIR/frontend/vite.config.js" "$SRC_DIR/app/version.py" -newer "$SRC_DIR/static/index.html" -print -quit)" ]; }; then
    if command -v npm >/dev/null 2>&1 && node_ok; then
        echo "==> Frontend: building"
        # In a scratch copy, so nothing root-owned is left in your checkout
        BUILD="$(mktemp -d)"
        trap 'rm -rf "$BUILD"' EXIT
        mkdir -p "$BUILD/app"
        rsync -a --exclude node_modules "$SRC_DIR/frontend/" "$BUILD/frontend/"
        cp "$SRC_DIR/app/version.py" "$BUILD/app/"
        npm --prefix "$BUILD/frontend" ci --silent
        npm --prefix "$BUILD/frontend" run build --silent
        STATIC_SRC="$BUILD/static"
    elif [ -f "$SRC_DIR/static/index.html" ]; then
        echo "warning: the frontend sources changed since static/ was built, and Node.js 20.19+/22.12+" >&2
        echo "         isn't available to rebuild it; installing the existing build" >&2
    else
        echo "error: no frontend build. Either install from a release tarball or .deb (prebuilt), or" >&2
        echo "       install Node.js 22 to build it here:" >&2
        echo "         curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash - && sudo apt install -y nodejs" >&2
        exit 1
    fi
else
    echo "==> Frontend: using $SRC_DIR/static"
fi

echo "==> Copying the app to $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
# --delete removes files dropped upstream; the venv is kept for speed
rsync -a --delete \
    --exclude .git --exclude .venv --exclude __pycache__ --exclude .pytest_cache --exclude .ruff_cache \
    --exclude frontend/node_modules --exclude static --exclude wheels \
    "$SRC_DIR/" "$INSTALL_DIR/"
rsync -a --delete "$STATIC_SRC/" "$INSTALL_DIR/static/"
[ -d "$SRC_DIR/wheels" ] && rsync -a --delete "$SRC_DIR/wheels/" "$INSTALL_DIR/wheels/"

exec "$INSTALL_DIR/deploy/postinstall.sh" "$INSTALL_DIR" "$DATA_DIR" "${OPTS[@]}"
