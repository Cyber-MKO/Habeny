#!/usr/bin/env bash
# Print the CHANGELOG.md section of a version (its release notes):
#   deploy/release-notes.sh 2.1.0
# Fails when the changelog has no section for it.
set -euo pipefail
VERSION="${1:?usage: $0 VERSION}"
CHANGELOG="$(dirname "${BASH_SOURCE[0]}")/../CHANGELOG.md"
notes="$(awk -v v="$VERSION" '
    /^## \[/ { if (found) exit; found = index($0, "## [" v "]") == 1; next }
    /^\[[^]]+\]: / { if (found) exit }
    found' "$CHANGELOG")"
[ -n "$(echo "$notes" | tr -d '[:space:]')" ] || {
    echo "error: CHANGELOG.md has no entries for $VERSION (add a \"## [$VERSION] - date\" section)" >&2
    exit 1
}
echo "$notes" | sed -e '/./,$!d'  # without leading blank lines
