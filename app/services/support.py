"""
Support bundle: what Habeny Platform support needs to diagnose a problem, in one file
(`habeny support-bundle`).

Included: versions, OS, service states, settings (secrets hidden), configuration problems,
database schema status, license state (not the license file), disk space, container
counts, backup list, audit-chain check, and the last lines of Habeny's log file if
HABENY_LOG_FILE is set.

Never included: passwords, API tokens, SIEM auth keys, secret.key, the license file,
the database, uploaded log content or container data. The server log excerpt can name
users, client IPs and container names, so customers should look through the bundle
before sending it (it's plain text inside).
"""
import contextlib
import io
import json
import platform
import shutil
import socket
import subprocess
import sys
import tarfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app import config

LOG_LINES = 2000
README = """Habeny support bundle
=====================

Created by `habeny support-bundle` for Habeny Platform support. It contains diagnostics
only: no passwords, tokens, keys, license file, database, uploaded logs or container data.
server.log (if present) can include user names, client IPs and container names; remove
anything you don't want to share before sending.

The journal isn't included, because the service account can't read it. If support asks
for it, run:  sudo journalctl -u habeny -u habeny-helper --since -24h > journal.txt
"""


def _run(cmd: list[str], timeout: int = 10) -> str:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        return (out.stdout + out.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"(not available: {e})"


def _safe(section: str, fn) -> Any:
    try:
        return fn()
    except Exception as e:  # one failing check must not stop the bundle
        return {"error": f"{section}: {type(e).__name__}: {e}"}


def _settings() -> list[dict[str, str]]:
    rows = []
    for setting in config.SETTINGS:
        value = config.raw(setting.name)
        rows.append({"name": setting.name, "value": "(set, hidden)" if setting.secret and value else value,
                     "source": config.source(setting.name)})
    return rows


def _disk() -> dict[str, Any]:
    result = {}
    for name, path in (("data", config.DATA_DIR), ("containers", Path("/var/lib/lxc"))):
        with contextlib.suppress(OSError):
            usage = shutil.disk_usage(path)
            result[name] = {"path": str(path), "total_gb": round(usage.total / 1e9, 1),
                            "free_gb": round(usage.free / 1e9, 1),
                            "free_percent": round(usage.free * 100 / usage.total, 1)}
    return result


def _containers() -> dict[str, Any]:
    from app.core.lxc_backend import lxc
    names = list(lxc.list_containers())
    running = len(lxc.list_containers(active=True, defined=False)) if names else 0
    return {"total": len(names), "running": running}


def _license() -> dict[str, Any]:
    from app.services import licensing
    info = licensing.status_info()
    lic = info.get("license") or {}
    return {"state": info["state"], "message": info["message"], "server_id": info["server_id"],
            "license_id": lic.get("id"), "expires": lic.get("expires"), "max_containers": lic.get("max_containers")}


def _log_excerpt() -> str | None:
    path = config.raw("HABENY_LOG_FILE")
    if not path or not Path(path).is_file():
        return None
    lines = Path(path).read_text(errors="replace").splitlines()[-LOG_LINES:]
    return "\n".join(lines) + "\n"


def collect() -> dict[str, Any]:
    from app import migrations
    from app.services import audit, backup
    from app.version import __version__

    os_release = {}
    with contextlib.suppress(OSError):
        for line in Path("/etc/os-release").read_text().splitlines():
            key, _, value = line.partition("=")
            os_release[key] = value.strip('"')
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "habeny_version": __version__,
        "host": socket.gethostname(),
        "os": os_release.get("PRETTY_NAME", platform.platform()),
        "kernel": platform.release(),
        "python": sys.version.split()[0],
        "lxc": _run(["lxc-ls", "--version"]),
        "services": {name: _run(["systemctl", "is-active", name]) for name in ("habeny", "habeny-helper")},
        "config_file": str(config.config_file()),
        "config_problems": _safe("config", config.validate),
        "settings": _safe("settings", _settings),
        "database": _safe("database", lambda: migrations.status(config.DB_PATH)),
        "license": _safe("license", _license),
        "disk": _safe("disk", _disk),
        "containers": _safe("containers", _containers),
        "backups": _safe("backups", lambda: backup.list_backups()[:20]),
        "audit_chain": _safe("audit", lambda: {k: v for k, v in audit.verify().items() if k != "head_hash"}),
    }


def create(out_dir: Path) -> Path:
    """Write the bundle (a .tar.gz readable only by its owner) and return its path."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = Path(out_dir) / f"habeny-support-{socket.gethostname()}-{stamp}.tar.gz"
    files = {"README.txt": README, "diagnostics.json": json.dumps(collect(), indent=2, default=str) + "\n"}
    excerpt = _log_excerpt()
    if excerpt:
        files["server.log"] = excerpt
    with open(path, "xb") as raw:
        path.chmod(0o600)
        with tarfile.open(fileobj=raw, mode="w:gz") as tar:
            for name, text in files.items():
                data = text.encode()
                info = tarfile.TarInfo(f"habeny-support-{stamp}/{name}")
                info.size, info.mtime, info.mode = len(data), int(time.time()), 0o600
                tar.addfile(info, io.BytesIO(data))
    return path
