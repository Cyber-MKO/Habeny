#!/usr/bin/env bash
# Install Habeny as two services: an unprivileged web app (user "habeny") and a small
# root helper that performs the LXC operations. Run from a checkout, as root:
#   sudo ./deploy/install.sh [--no-start]
#
# The app is copied to $HABENY_INSTALL_DIR (default /opt/habeny); your checkout is left
# untouched, so it can live anywhere, including your home directory. Re-run after
# `git pull` to upgrade (code, dependencies, frontend build, unit files).
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="${HABENY_INSTALL_DIR:-/opt/habeny}"
DATA_DIR="${HABENY_DATA_DIR:-/var/lib/lxc-siem-platform}"
SVC_USER=habeny
START=1
[ "${1:-}" = "--no-start" ] && START=0

[ "$(id -u)" -eq 0 ] || { echo "Run as root: sudo $0" >&2; exit 1; }
case "$INSTALL_DIR/" in
    /home/*|/root/*)
        echo "error: HABENY_INSTALL_DIR must be outside /home and /root: the web service" >&2
        echo "       runs with ProtectHome=yes and as the '$SVC_USER' user." >&2
        exit 1 ;;
esac
[ "$SRC_DIR" != "$INSTALL_DIR" ] || { echo "error: run this from a checkout, not from $INSTALL_DIR" >&2; exit 1; }

echo "==> System packages"
apt-get install -y lxc lxc-utils python3-lxc python3-venv rsync >/dev/null

echo "==> Service user '$SVC_USER'"
id "$SVC_USER" >/dev/null 2>&1 || useradd --system --home-dir "$DATA_DIR" --shell /usr/sbin/nologin "$SVC_USER"

echo "==> Copying the app to $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
# --delete removes files dropped upstream; the venv and build caches are kept for speed
rsync -a --delete \
    --exclude .git --exclude .venv --exclude __pycache__ --exclude .pytest_cache --exclude .ruff_cache \
    --exclude frontend/node_modules --exclude static \
    "$SRC_DIR/" "$INSTALL_DIR/"

echo "==> Python environment ($INSTALL_DIR/.venv)"
python3 -m venv "$INSTALL_DIR/.venv"
"$INSTALL_DIR/.venv/bin/pip" install -q --upgrade pip
"$INSTALL_DIR/.venv/bin/pip" install -q -r "$INSTALL_DIR/requirements.txt"

if command -v npm >/dev/null 2>&1; then
    echo "==> Frontend build"
    npm --prefix "$INSTALL_DIR/frontend" ci --silent
    npm --prefix "$INSTALL_DIR/frontend" run build --silent
elif [ -f "$SRC_DIR/static/index.html" ]; then
    echo "==> Frontend: npm not found, using the build in $SRC_DIR/static"
    rsync -a --delete "$SRC_DIR/static/" "$INSTALL_DIR/static/"
else
    echo "warning: npm not found and no frontend build in $SRC_DIR/static; the UI will be unavailable" >&2
fi

echo "==> Permissions: code root-owned and read-only for the service; data owned by $SVC_USER"
chown -R root:root "$INSTALL_DIR"
chmod -R go-w "$INSTALL_DIR"
chmod -R a+rX "$INSTALL_DIR"
mkdir -p "$DATA_DIR"
chown -R "$SVC_USER:$SVC_USER" "$DATA_DIR"   # also migrates data created by a root install
chmod 750 "$DATA_DIR"

echo "==> systemd units"
for unit in habeny-helper.service habeny.service; do
    sed -e "s|@INSTALL_DIR@|$INSTALL_DIR|g" -e "s|@DATA_DIR@|$DATA_DIR|g" \
        "$INSTALL_DIR/deploy/systemd/$unit" > "/etc/systemd/system/$unit"
done
if [ "$START" -eq 0 ]; then
    echo "Installed (not started): systemctl enable --now habeny-helper habeny"
    exit 0
fi
systemctl daemon-reload
systemctl enable habeny-helper.service habeny.service >/dev/null
systemctl restart habeny-helper.service habeny.service

sleep 3
if systemctl is-active --quiet habeny.service; then
    echo
    echo "Habeny is running: https://$(hostname -I | awk '{print $1}'):9000"
else
    echo "error: habeny.service did not stay up; see: journalctl -u habeny -n 50" >&2
    exit 1
fi
echo "  status:  systemctl status habeny habeny-helper"
echo "  logs:    journalctl -u habeny -u habeny-helper -f"
