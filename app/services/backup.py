"""
Full backups of Habeny's data: one .tar.gz with everything needed to rebuild an install.

Contents: the database (a consistent online copy), the key that decrypts stored secrets,
the TLS certificate, reports, config templates, container metadata, the activity log
and /etc/habeny/habeny.conf, plus manifest.json (versions and a SHA-256 per file).

- Scheduled (HABENY_BACKUP_INTERVAL_HOURS) by the maintenance task; the newest
  HABENY_BACKUP_KEEP are kept, in HABENY_BACKUP_DIR (default DATA_DIR/backups).
- `habeny backup create|list|verify|restore`, and admins can create and download
  backups from the Account page.

A backup contains the encryption key and every stored secret, so treat the file like a
password vault: keep copies off the server, somewhere only admins can read.
"""
import contextlib
import hashlib
import json
import logging
import os
import re
import shutil
import socket
import sqlite3
import tarfile
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from app import config
from app.config import DATA_DIR, DB_PATH

logger = logging.getLogger(__name__)

PREFIX = "habeny-backup-"
NAME = re.compile(r"^habeny-backup-\d{8}-\d{6}-[a-z-]+\.tar\.gz$")
FORMAT_VERSION = 1
# Data directories included (relative to DATA_DIR); agent-cache is a re-downloadable package cache
DIRECTORIES = ["reports", "configs", "agents", "tls", "logs"]
FILES = ["secret.key", "license.key", "server-id"]  # server-id: only where there is no machine ID

_lock = threading.Lock()  # one backup at a time


class BackupError(RuntimeError):
    pass


def backup_dir() -> Path:
    return Path(config.get("HABENY_BACKUP_DIR") or DATA_DIR / "backups")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def list_backups() -> list[dict]:
    directory = backup_dir()
    if not directory.is_dir():
        return []
    items = []
    for path in sorted(directory.glob(f"{PREFIX}*.tar.gz"), reverse=True):
        if not NAME.match(path.name):
            continue
        stat = path.stat()
        items.append({
            "name": path.name,
            "size_bytes": stat.st_size,
            "created_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            "label": path.name[len(PREFIX) + 16:-len(".tar.gz")],
        })
    return items


def backup_path(name: str) -> Path:
    """A backup's path, refusing anything that isn't a backup name (no path traversal)."""
    if not NAME.match(name):
        raise BackupError("Not a backup file name")
    path = backup_dir() / name
    if not path.is_file():
        raise BackupError(f"Backup {name} not found")
    return path


def create_backup(label: str = "manual") -> Path:
    """Write a new backup and prune old ones. Safe while Habeny is running."""
    from app.migrations import current_version
    from app.version import __version__

    if not re.fullmatch(r"[a-z-]+", label):
        raise BackupError("invalid label")
    directory = backup_dir()
    try:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError as e:
        raise BackupError(f"Can't create the backup directory {directory}: {e}") from e
    if not os.access(directory, os.W_OK):
        raise BackupError(f"The backup directory {directory} isn't writable by this service "
                          "(outside the data directory, systemd needs ReadWritePaths for it; see the administrator guide, Backups)")

    with _lock, tempfile.TemporaryDirectory(dir=directory, prefix=".backup-") as tmp:
        stage = Path(tmp) / "habeny-backup"
        stage.mkdir()
        # Database: SQLite's online backup gives a consistent copy while the app writes
        source = sqlite3.connect(DB_PATH)
        try:
            dest = sqlite3.connect(stage / "platform.db")
            try:
                source.backup(dest)
            finally:
                dest.close()
        finally:
            source.close()
        for name in FILES:
            if (DATA_DIR / name).is_file():
                shutil.copy2(DATA_DIR / name, stage / name)
        for name in DIRECTORIES:
            if (DATA_DIR / name).is_dir():
                shutil.copytree(DATA_DIR / name, stage / name, ignore=shutil.ignore_patterns("*.tmp"))
        conf = config.config_file()
        with contextlib.suppress(OSError):  # absent or unreadable: the rest is still a complete backup
            shutil.copy2(conf, stage / "habeny.conf")

        files = {str(p.relative_to(stage)): {"sha256": _sha256(p), "size": p.stat().st_size}
                 for p in sorted(stage.rglob("*")) if p.is_file()}
        manifest = {
            "format": FORMAT_VERSION,
            "habeny_version": __version__,
            "schema_version": current_version(stage / "platform.db"),
            "created_at": _now().isoformat(),
            "host": socket.gethostname(),
            "label": label,
            "secret_key": "included" if "secret.key" in files else
                          ("from HABENY_SECRET_KEY (not included; keep it too)" if config.raw("HABENY_SECRET_KEY")
                           else "none yet (nothing has been encrypted)"),
            "files": files,
        }
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2))

        target = directory / f"{PREFIX}{_now():%Y%m%d-%H%M%S}-{label}.tar.gz"
        while target.exists():  # two backups within a second
            time.sleep(0.2)
            target = directory / f"{PREFIX}{_now():%Y%m%d-%H%M%S}-{label}.tar.gz"
        partial = Path(tmp) / "partial.tar.gz"
        fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as raw, tarfile.open(fileobj=raw, mode="w:gz") as archive:
            archive.add(stage, arcname="habeny-backup")
        os.replace(partial, target)  # never a half-written backup under the real name

    size_mb = target.stat().st_size / 1e6
    logger.info(f"Backup written: {target} ({size_mb:.1f} MB)",
                extra={"fields": {"backup": str(target), "size_bytes": target.stat().st_size}})
    prune_backups()
    return target


def prune_backups() -> int:
    keep = config.get("HABENY_BACKUP_KEEP")
    removed = 0
    for item in list_backups()[keep:]:
        (backup_dir() / item["name"]).unlink(missing_ok=True)
        removed += 1
    return removed


_last_scheduled: dict = {"at": None, "error": None}


def backup_if_due() -> Path | None:
    """Called hourly by the maintenance task."""
    hours = config.get("HABENY_BACKUP_INTERVAL_HOURS")
    if hours <= 0:
        return None
    newest = next((b for b in list_backups() if b["label"] == "scheduled"), None)
    if newest and (_now() - datetime.fromisoformat(newest["created_at"])).total_seconds() < hours * 3600 - 300:
        return None
    try:
        path = create_backup("scheduled")
        _last_scheduled.update(at=_now().isoformat(), error=None)
        return path
    except Exception as e:
        _last_scheduled.update(at=_now().isoformat(), error=str(e))
        raise


def schedule_status() -> dict:
    hours = config.get("HABENY_BACKUP_INTERVAL_HOURS")
    return {"interval_hours": hours, "keep": config.get("HABENY_BACKUP_KEEP"), "directory": str(backup_dir()),
            "last_scheduled_error": _last_scheduled["error"]}


# ── verify and restore ──────────────────────────────────────────────────

def _safe_members(archive: tarfile.TarFile) -> list[tarfile.TarInfo]:
    members = []
    for member in archive.getmembers():
        parts = Path(member.name).parts
        if member.name.startswith("/") or ".." in parts or not parts or parts[0] != "habeny-backup":
            raise BackupError(f"unexpected path in backup: {member.name!r}")
        if not (member.isfile() or member.isdir()):
            raise BackupError(f"unexpected entry type in backup: {member.name!r}")
        members.append(member)
    return members


def _unpack(path: Path, into: Path) -> tuple[Path, dict]:
    try:
        with tarfile.open(path, "r:gz") as archive:
            members = _safe_members(archive)
            # tarfile's "data" filter (Python 3.12, backported to 3.10.12/3.11.4) also refuses
            # links, devices and unsafe modes; _safe_members already covers older Pythons
            extra = {"filter": "data"} if hasattr(tarfile, "data_filter") else {}
            archive.extractall(into, members=members, **extra)
    except (tarfile.TarError, OSError, EOFError) as e:
        raise BackupError(f"{path} isn't a readable backup: {e}") from e
    root = into / "habeny-backup"
    try:
        manifest = json.loads((root / "manifest.json").read_text())
    except (OSError, ValueError) as e:
        raise BackupError(f"{path} has no valid manifest") from e
    for name, meta in manifest.get("files", {}).items():
        file = root / name
        if not file.is_file() or _sha256(file) != meta["sha256"]:
            raise BackupError(f"{path}: {name} is missing or damaged (checksum mismatch)")
    db = root / "platform.db"
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise BackupError(f"{path}: the database copy is damaged")
    finally:
        conn.close()
    return root, manifest


def verify_backup(path: Path) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        _, manifest = _unpack(Path(path), Path(tmp))
    return manifest


def restore_backup(path: Path) -> dict:
    """Restore the data from a backup (stop Habeny first). What's replaced is kept aside:
    the database under backups/, other files as *.before-restore."""
    from app import migrations

    with tempfile.TemporaryDirectory(dir=DATA_DIR, prefix=".restore-") as tmp:
        root, manifest = _unpack(Path(path), Path(tmp))
        if manifest.get("schema_version", 0) > migrations.latest_version():
            raise BackupError(f"This backup is from a newer Habeny (schema v{manifest['schema_version']}); "
                              f"install Habeny {manifest.get('habeny_version')} or later to restore it")
        migrations.restore(DB_PATH, root / "platform.db")
        for name in FILES:
            if (root / name).is_file():
                if (DATA_DIR / name).exists():
                    shutil.copy2(DATA_DIR / name, DATA_DIR / f"{name}.before-restore")
                shutil.copy2(root / name, DATA_DIR / name)
                os.chmod(DATA_DIR / name, 0o600)
        for name in DIRECTORIES:
            if (root / name).is_dir():
                target = DATA_DIR / name
                if target.exists():
                    aside = DATA_DIR / f"{name}.before-restore"
                    shutil.rmtree(aside, ignore_errors=True)
                    target.rename(aside)
                shutil.copytree(root / name, target)
        if (root / "habeny.conf").is_file():
            shutil.copy2(root / "habeny.conf", DATA_DIR / "restored-habeny.conf")
            manifest["config_restored_to"] = str(DATA_DIR / "restored-habeny.conf")
    return manifest
