#!/usr/bin/env bash
# habeny: administration commands (see `habeny --help`). Runs as the service user with
# the service's settings, so the database and files keep the right owner.
set -euo pipefail
cd "@INSTALL_DIR@"
CMD=(env HABENY_DATA_DIR="@DATA_DIR@" HABENY_LXC_BACKEND=helper "@INSTALL_DIR@/.venv/bin/python" -m app.cli "$@")
if [ "$(id -u)" -eq 0 ]; then
    exec runuser -u habeny -- "${CMD[@]}"
elif [ "$(id -un)" = habeny ]; then
    exec "${CMD[@]}"
else
    echo "habeny: run with sudo (e.g. sudo habeny $*)" >&2
    exit 1
fi
