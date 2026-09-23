#!/usr/bin/env bash
# Sets up (or upgrades) an installed copy of Habeny. Shared by deploy/install.sh and the
# .deb package; not meant to be run by hand.
#
#   postinstall.sh INSTALL_DIR DATA_DIR [--package] [--no-start]
#
# --package: the .deb already installed the systemd units and /usr/bin/habeny.
set -euo pipefail

INSTALL_DIR="$1"
DATA_DIR="$2"
shift 2
PACKAGE=0
START=1
for arg in "$@"; do
    case "$arg" in
        --package) PACKAGE=1 ;;
        --no-start) START=0 ;;
        *) echo "postinstall.sh: unknown option $arg" >&2; exit 2 ;;
    esac
done

SVC_USER=habeny
CONF_DIR=/etc/habeny
CONF_FILE="$CONF_DIR/habeny.conf"
VENV="$INSTALL_DIR/.venv"

[ "$(id -u)" -eq 0 ] || { echo "postinstall.sh must run as root" >&2; exit 1; }
[ -f "$INSTALL_DIR/static/index.html" ] || {
    echo "error: $INSTALL_DIR/static has no frontend build. Install from a release (it's prebuilt)," >&2
    echo "       or from a checkout with Node.js 20.19+/22.12+ so deploy/install.sh can build it." >&2
    exit 1
}

echo "==> Service user '$SVC_USER'"
id "$SVC_USER" >/dev/null 2>&1 || useradd --system --home-dir "$DATA_DIR" --shell /usr/sbin/nologin "$SVC_USER"

echo "==> Python environment ($VENV)"
# Rebuild it when the system Python changed (e.g. after an OS upgrade) or it's broken
SYS_PY="$(python3 -c 'import sys; print(sys.version_info[:2])')"
if [ "$("$VENV/bin/python" -c 'import sys; print(sys.version_info[:2])' 2>/dev/null)" != "$SYS_PY" ]; then
    rm -rf "$VENV"
    python3 -m venv "$VENV"
fi
PY_TAG="$("$VENV/bin/python" -c 'import sys; print(f"cp{sys.version_info[0]}{sys.version_info[1]}")')"
WHEELS="${HABENY_WHEELS:-$INSTALL_DIR/wheels/$PY_TAG}"
if [ -d "$WHEELS" ]; then
    echo "    offline: installing from $WHEELS"
    "$VENV/bin/pip" install -q --no-index --find-links "$WHEELS" -r "$INSTALL_DIR/requirements.txt"
else
    "$VENV/bin/pip" install -q --upgrade pip
    "$VENV/bin/pip" install -q -r "$INSTALL_DIR/requirements.txt" || {
        echo "error: installing Python packages failed. Without internet access, download" >&2
        echo "       habeny-wheels-<version>-$PY_TAG-x86_64.tar.gz from the release, extract it into" >&2
        echo "       $INSTALL_DIR/wheels/ and run the installation again." >&2
        exit 1
    }
fi

echo "==> Configuration ($CONF_FILE)"
mkdir -p "$CONF_DIR"
if [ ! -f "$CONF_FILE" ]; then
    if [ -f /etc/default/habeny ]; then
        # Settings from before /etc/habeny existed
        { echo "# Moved from /etc/default/habeny"; cat /etc/default/habeny; } > "$CONF_FILE"
        mv /etc/default/habeny /etc/default/habeny.moved-to-etc-habeny
        echo "    moved /etc/default/habeny here"
    else
        cp "$INSTALL_DIR/deploy/habeny.conf.example" "$CONF_FILE"
    fi
fi
# Readable by the service (it may hold secrets such as the SSO client secret)
chown root:"$SVC_USER" "$CONF_DIR" "$CONF_FILE"
chmod 750 "$CONF_DIR"
chmod 640 "$CONF_FILE"

echo "==> Permissions: code root-owned and read-only for the service; data owned by $SVC_USER"
chown -R root:root "$INSTALL_DIR"
chmod -R go-w "$INSTALL_DIR"
chmod -R a+rX "$INSTALL_DIR"
mkdir -p "$DATA_DIR"
chown -R "$SVC_USER:$SVC_USER" "$DATA_DIR"   # also migrates data created by a root install
chmod 750 "$DATA_DIR"

render() {  # template -> file, filling in the install and data paths
    sed -e "s|@INSTALL_DIR@|$INSTALL_DIR|g" -e "s|@DATA_DIR@|$DATA_DIR|g" "$1" > "$2"
}
if [ "$PACKAGE" -eq 0 ]; then
    echo "==> systemd units and the habeny command"
    for unit in habeny-helper.service habeny.service; do
        render "$INSTALL_DIR/deploy/systemd/$unit" "/etc/systemd/system/$unit"
    done
    render "$INSTALL_DIR/deploy/habeny-cli.sh" /usr/local/bin/habeny
    chmod 755 /usr/local/bin/habeny
fi
HABENY_CMD="$INSTALL_DIR/.venv/bin/python -m app.cli"

echo "==> Checking the configuration"
run_as_service() {
    (cd "$INSTALL_DIR" && runuser -u "$SVC_USER" -- env HABENY_DATA_DIR="$DATA_DIR" HABENY_LXC_BACKEND=helper "$@")
}
run_as_service $HABENY_CMD config check || {
    echo "error: fix $CONF_FILE, then: sudo systemctl restart habeny" >&2
    exit 1
}

systemctl daemon-reload
# Upgrades: stop first so the database is migrated with nothing using it. Stopping waits for
# running deployments to finish (HABENY_SHUTDOWN_TIMEOUT).
if systemctl is-active --quiet habeny.service; then
    echo "==> Stopping Habeny (waits for running deployments to finish)"
    systemctl stop habeny.service
fi

echo "==> Database"
run_as_service $HABENY_CMD db migrate || {
    echo "error: the database was not changed (see above). To keep running, reinstall the version" >&2
    echo "       you had; Habeny stays stopped until then." >&2
    exit 1
}

systemctl enable habeny-helper.service habeny.service >/dev/null
if [ "$START" -eq 0 ]; then
    echo "Installed (not started): systemctl start habeny-helper habeny"
    exit 0
fi
systemctl restart habeny-helper.service habeny.service

for _ in $(seq 20); do
    systemctl is-active --quiet habeny.service && break
    sleep 1
done
sleep 2
if systemctl is-active --quiet habeny.service; then
    VERSION="$(run_as_service $HABENY_CMD version)"
    echo
    echo "$VERSION is running: https://$(hostname -I | awk '{print $1}'):$(run_as_service $HABENY_CMD config \
        | awk '$1 == "HABENY_PORT" {print $2}')"
    echo "  status:   systemctl status habeny habeny-helper"
    echo "  logs:     journalctl -u habeny -u habeny-helper -f"
    echo "  settings: $CONF_FILE (then: sudo systemctl restart habeny)"
    echo "  admin:    habeny --help"
else
    echo "error: habeny.service did not stay up; see: journalctl -u habeny -n 50" >&2
    exit 1
fi
