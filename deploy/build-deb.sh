#!/usr/bin/env bash
# Build the .deb from a release directory (as made by deploy/build-release.sh):
#   deploy/build-deb.sh RELEASE_DIR VERSION OUT_DIR
# The package is architecture-independent: Python packages are installed into
# /opt/habeny/.venv when it is configured (from PyPI, or offline from wheels/).
set -euo pipefail

RELEASE_DIR="$1"
VERSION="$2"
OUT_DIR="$3"
INSTALL_DIR=/opt/habeny
DATA_DIR=/var/lib/lxc-siem-platform

PKG="$(mktemp -d)"
chmod 755 "$PKG"  # becomes / in the package
trap 'rm -rf "$PKG"' EXIT
mkdir -p "$PKG$INSTALL_DIR" "$PKG/lib/systemd/system" "$PKG/usr/bin" "$PKG/DEBIAN"

cp -a "$RELEASE_DIR/." "$PKG$INSTALL_DIR/"
render() { sed -e "s|@INSTALL_DIR@|$INSTALL_DIR|g" -e "s|@DATA_DIR@|$DATA_DIR|g" "$1" > "$2"; }
for unit in habeny.service habeny-helper.service; do
    render "$RELEASE_DIR/deploy/systemd/$unit" "$PKG/lib/systemd/system/$unit"
done
render "$RELEASE_DIR/deploy/habeny-cli.sh" "$PKG/usr/bin/habeny"
chmod 755 "$PKG/usr/bin/habeny"

cat > "$PKG/DEBIAN/control" <<CONTROL
Package: habeny
Version: $VERSION
Section: admin
Priority: optional
Architecture: all
Depends: python3 (>= 3.10), python3-venv, python3-lxc, lxc, lxc-utils, adduser
Installed-Size: $(du -sk "$PKG" | cut -f1)
Maintainer: Habeny <noreply@habeny.invalid>
Homepage: https://github.com/Cyber-MKO/Habeny
Description: Multi-SIEM container emulation platform
 Deploys and manages LXC containers running SIEM agents (Wazuh, OSSEC, Elastic,
 UTMStack, AlienVault OSSIM) at scale, with a web UI, attack simulations,
 benchmarks and reports. Runs as two services: an unprivileged web app and a small
 privileged helper for LXC operations.
CONTROL

cat > "$PKG/DEBIAN/postinst" <<POSTINST
#!/bin/sh
set -e
if [ "\$1" = "configure" ]; then
    $INSTALL_DIR/deploy/postinstall.sh $INSTALL_DIR $DATA_DIR --package
fi
POSTINST

cat > "$PKG/DEBIAN/prerm" <<'PRERM'
#!/bin/sh
set -e
case "$1" in
    upgrade)
        # Stop before the files are replaced; waits for running deployments to finish
        systemctl stop habeny.service 2>/dev/null || true ;;
    remove|deconfigure)
        systemctl disable --now habeny.service habeny-helper.service 2>/dev/null || true ;;
esac
PRERM

cat > "$PKG/DEBIAN/postrm" <<POSTRM
#!/bin/sh
set -e
case "\$1" in
    remove)
        # Created at install time, not part of the package
        rm -rf $INSTALL_DIR/.venv
        find $INSTALL_DIR -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
        systemctl daemon-reload 2>/dev/null || true ;;
    purge)
        rm -rf /etc/habeny
        echo "Habeny's data was kept in $DATA_DIR (remove it yourself if you no longer need it)." ;;
esac
POSTRM
chmod 755 "$PKG/DEBIAN/postinst" "$PKG/DEBIAN/prerm" "$PKG/DEBIAN/postrm"

chmod -R go-w "$PKG"  # independent of the build machine's umask
mkdir -p "$OUT_DIR"
dpkg-deb --root-owner-group --build "$PKG" "$OUT_DIR/habeny_${VERSION}_all.deb" >/dev/null
echo "$OUT_DIR/habeny_${VERSION}_all.deb"
