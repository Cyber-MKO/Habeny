#!/usr/bin/env bash
# Build the release artifacts into OUT_DIR (default dist/). Run from a clean checkout of
# the release tag, after building the frontend (cd frontend && npm ci && npm run build):
#   deploy/build-release.sh [OUT_DIR]
#
# Produces:
#   habeny-VERSION.tar.gz                    the app with the frontend prebuilt
#   habeny_VERSION_all.deb                   Debian/Ubuntu package
#   habeny-wheels-VERSION-cpXY-x86_64.tar.gz Python packages for offline installs
#   SHA256SUMS
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="$(mkdir -p "${1:-$ROOT/dist}" && cd "${1:-$ROOT/dist}" && pwd)"
VERSION="$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' "$ROOT/app/version.py")"
COMMIT="$(git -C "$ROOT" rev-parse --short HEAD)"
PYTHONS="${HABENY_WHEEL_PYTHONS-3.10 3.11 3.12 3.13}"  # Ubuntu 22.04, Debian 12, Ubuntu 24.04, Debian 13

[ -f "$ROOT/static/index.html" ] || { echo "error: build the frontend first (cd frontend && npm ci && npm run build)" >&2; exit 1; }
[ -z "$(git -C "$ROOT" status --porcelain -- app deploy main.py requirements.txt)" ] || {
    echo "error: uncommitted changes; release from a clean checkout" >&2; exit 1; }

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
RELEASE="$STAGE/habeny-$VERSION"
mkdir -p "$RELEASE"

echo "==> Source ($COMMIT)"
git -C "$ROOT" archive HEAD | tar -x -C "$RELEASE"
rm -rf "$RELEASE/.github"

echo "==> Prebuilt frontend"
cp -a "$ROOT/static" "$RELEASE/static"
echo "Habeny $VERSION ($COMMIT, built $(date -u +%Y-%m-%d))" > "$RELEASE/static/.habeny-build"

echo "==> habeny-$VERSION.tar.gz"
tar -C "$STAGE" -czf "$OUT_DIR/habeny-$VERSION.tar.gz" "habeny-$VERSION"

echo "==> .deb"
"$ROOT/deploy/build-deb.sh" "$RELEASE" "$VERSION" "$OUT_DIR"

for py in $PYTHONS; do
    tag="cp${py/./}"
    echo "==> Offline wheels for Python $py"
    mkdir -p "$STAGE/wheels/$tag"
    python3 -m pip download -q -r "$ROOT/requirements.txt" -d "$STAGE/wheels/$tag" --only-binary=:all: \
        --implementation cp --python-version "$py" \
        --platform manylinux2014_x86_64 --platform manylinux_2_17_x86_64 --platform manylinux_2_28_x86_64
    tar -C "$STAGE" -czf "$OUT_DIR/habeny-wheels-$VERSION-$tag-x86_64.tar.gz" "wheels/$tag"
done

(cd "$OUT_DIR" && sha256sum habeny[-_]* > SHA256SUMS)
echo
ls -lh "$OUT_DIR"
