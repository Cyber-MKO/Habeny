#!/usr/bin/env bash
# Install Habeny as two services: an unprivileged web app (user "habeny") and a small
# root helper that performs the LXC operations. Run from the repository as root:
#   sudo ./deploy/install.sh
# Re-running upgrades in place (dependencies, frontend build, unit files).
set -euo pipefail

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="${HABENY_DATA_DIR:-/var/lib/lxc-siem-platform}"
SVC_USER=habeny

[ "$(id -u)" -eq 0 ] || { echo "Run as root: sudo $0" >&2; exit 1; }

echo "==> System packages"
apt-get install -y lxc lxc-utils python3-lxc python3-venv >/dev/null

echo "==> Service user '$SVC_USER'"
id "$SVC_USER" >/dev/null 2>&1 || useradd --system --home-dir "$DATA_DIR" --shell /usr/sbin/nologin "$SVC_USER"

echo "==> Python environment ($INSTALL_DIR/.venv)"
python3 -m venv "$INSTALL_DIR/.venv"
"$INSTALL_DIR/.venv/bin/pip" install -q --upgrade pip
"$INSTALL_DIR/.venv/bin/pip" install -q -r "$INSTALL_DIR/requirements.txt"

if command -v npm >/dev/null 2>&1; then
    echo "==> Frontend build"
    npm --prefix "$INSTALL_DIR/frontend" ci --silent
    npm --prefix "$INSTALL_DIR/frontend" run build --silent
elif [ ! -f "$INSTALL_DIR/static/index.html" ]; then
    echo "warning: npm not found and no prebuilt frontend in static/; the UI will be unavailable" >&2
fi

echo "==> Data directory $DATA_DIR (owned by $SVC_USER)"
mkdir -p "$DATA_DIR"
chown -R "$SVC_USER:$SVC_USER" "$DATA_DIR"   # also migrates data created by a root install
chmod 750 "$DATA_DIR"

echo "==> Code is root-owned and read-only for the service"
chown -R root:root "$INSTALL_DIR"
chmod -R go-w "$INSTALL_DIR"

echo "==> systemd units"
for unit in habeny-helper.service habeny.service; do
    sed -e "s|@INSTALL_DIR@|$INSTALL_DIR|g" -e "s|@DATA_DIR@|$DATA_DIR|g" \
        "$INSTALL_DIR/deploy/systemd/$unit" > "/etc/systemd/system/$unit"
done
systemctl daemon-reload
systemctl enable --now habeny-helper.service habeny.service
systemctl restart habeny-helper.service habeny.service

echo
echo "Habeny is running: https://$(hostname -I | awk '{print $1}'):9000"
echo "  status:  systemctl status habeny habeny-helper"
echo "  logs:    journalctl -u habeny -u habeny-helper -f"
