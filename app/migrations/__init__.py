"""
Versioned database migrations.

Each migration is a module here named vNNNN_description.py with `up(conn)` and,
where the change can be undone, `down(conn)`. The database records its version in
`PRAGMA user_version` and every applied step in the schema_history table.

- Upgrading (at startup, or `habeny db migrate`): the database is backed up to
  DATA_DIR/backups first, then each pending migration runs in its own transaction.
  A failing migration is rolled back, so the database is never left half-changed.
- Rolling back: `habeny db restore <backup>` (always possible), or
  `habeny db downgrade --to N` when the migrations in between define down().
- An older Habeny won't start on a database migrated by a newer one.

To change the schema, add the next vNNNN_*.py; never edit one that has been released.
"""
import importlib
import logging
import pkgutil
import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType

logger = logging.getLogger(__name__)

KEEP_BACKUPS = 10
_NAME = re.compile(r"^v(\d{4})_(\w+)$")


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    module: ModuleType

    @property
    def description(self) -> str:
        return (self.module.__doc__ or "").strip().splitlines()[0] if self.module.__doc__ else self.name

    @property
    def up(self) -> Callable[[sqlite3.Connection], None]:
        return self.module.up

    @property
    def down(self) -> Callable[[sqlite3.Connection], None] | None:
        return getattr(self.module, "down", None)


def all_migrations() -> list[Migration]:
    found = []
    for info in pkgutil.iter_modules(__path__):
        match = _NAME.match(info.name)
        if match:
            module = importlib.import_module(f"{__name__}.{info.name}")
            found.append(Migration(int(match.group(1)), match.group(2), module))
    found.sort(key=lambda m: m.version)
    versions = [m.version for m in found]
    if versions != list(range(1, len(found) + 1)):
        raise MigrationError(f"migrations must be numbered 1..n without gaps; found {versions}")
    return found


def latest_version() -> int:
    return len(all_migrations())


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30, isolation_level=None)  # transactions managed here
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def current_version(db_path: Path) -> int:
    if not Path(db_path).exists():
        return 0
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()


def _has_tables(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0] > 0


def status(db_path: Path) -> dict:
    current = current_version(db_path)
    migrations = all_migrations()
    return {
        "database": str(db_path),
        "current": current,
        "latest": len(migrations),
        "pending": [f"v{m.version:04d} {m.description}" for m in migrations if m.version > current],
        "too_new": current > len(migrations),
        "backups": [str(p) for p in list_backups(Path(db_path))],
    }


# ── backups ─────────────────────────────────────────────────────────────

def backup_dir(db_path: Path) -> Path:
    return Path(db_path).parent / "backups"


def list_backups(db_path: Path) -> list[Path]:
    directory = backup_dir(db_path)
    return sorted(directory.glob(f"{Path(db_path).stem}-*.db"), reverse=True) if directory.is_dir() else []


def backup(db_path: Path, label: str = "manual") -> Path:
    """Consistent copy of the live database (SQLite online backup; safe while running)."""
    db_path = Path(db_path)
    directory = backup_dir(db_path)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    target = directory / f"{db_path.stem}-{stamp}-v{current_version(db_path)}-{label}.db"
    source = sqlite3.connect(db_path)
    try:
        dest = sqlite3.connect(target)
        try:
            source.backup(dest)
        finally:
            dest.close()
    finally:
        source.close()
    target.chmod(0o600)
    for old in list_backups(db_path)[KEEP_BACKUPS:]:
        old.unlink(missing_ok=True)
    return target


def restore(db_path: Path, backup_file: Path) -> int:
    """Replace the database with a backup. Returns the restored schema version.
    Stop Habeny first: open connections would keep using the old data."""
    backup_file = Path(backup_file)
    if not backup_file.is_file():
        raise MigrationError(f"{backup_file} not found")
    check = sqlite3.connect(f"file:{backup_file}?mode=ro", uri=True)
    try:
        if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise MigrationError(f"{backup_file} is damaged (integrity check failed)")
        version = check.execute("PRAGMA user_version").fetchone()[0]
    except sqlite3.DatabaseError as e:
        raise MigrationError(f"{backup_file} isn't a Habeny database backup: {e}") from None
    finally:
        check.close()
    if version > latest_version():
        raise MigrationError(f"{backup_file} is schema v{version}, newer than this Habeny (v{latest_version()})")
    if Path(db_path).exists():
        backup(db_path, "before-restore")
    source = sqlite3.connect(f"file:{backup_file}?mode=ro", uri=True)
    try:
        dest = sqlite3.connect(db_path, timeout=5)
        try:
            source.backup(dest)  # replaces the contents in place, WAL included
        finally:
            dest.close()
    finally:
        source.close()
    return version


# ── applying ────────────────────────────────────────────────────────────

def _record(conn: sqlite3.Connection, migration: Migration, direction: str) -> None:
    from app.version import __version__
    conn.execute(
        "INSERT INTO schema_history (version, name, direction, app_version, applied_at) VALUES (?, ?, ?, ?, ?)",
        (migration.version, migration.name, direction, __version__, datetime.now(timezone.utc).isoformat()),
    )


def migrate(db_path: Path, make_backup: bool = True) -> list[Migration]:
    """Bring the database up to the latest version. Returns the migrations applied."""
    migrations = all_migrations()
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = _connect(db_path)
    try:
        current = conn.execute("PRAGMA user_version").fetchone()[0]
        if current > len(migrations):
            raise MigrationError(
                f"The database ({db_path}) is at schema v{current}, but this Habeny only knows v{len(migrations)}: "
                f"it was upgraded by a newer version. Run the newer version, or restore the backup taken before "
                f"the upgrade (`habeny db restore`; backups are in {backup_dir(db_path)})."
            )
        pending = [m for m in migrations if m.version > current]
        if not pending:
            return []
        if make_backup and _has_tables(conn):
            saved = backup(db_path, f"before-v{pending[-1].version}")
            logger.info(f"Database backed up to {saved} before migrating")
        for migration in pending:
            conn.execute("BEGIN IMMEDIATE")
            try:
                migration.up(conn)
                _record(conn, migration, "up")
                conn.execute(f"PRAGMA user_version = {migration.version}")
                conn.execute("COMMIT")
            except Exception as e:
                conn.execute("ROLLBACK")
                raise MigrationError(f"Migration v{migration.version:04d} ({migration.name}) failed and was rolled "
                                     f"back; the database is unchanged at v{migration.version - 1}: {e}") from e
            logger.info(f"Database migrated to v{migration.version:04d}: {migration.description}")
        return pending
    finally:
        conn.close()


def downgrade(db_path: Path, target: int) -> list[Migration]:
    """Undo migrations down to `target`. Needs down() on each; backs up first."""
    migrations = all_migrations()
    conn = _connect(db_path)
    try:
        current = conn.execute("PRAGMA user_version").fetchone()[0]
        if current <= 1:
            raise MigrationError(f"nothing to undo: the database is at v{current}, the first version")
        if not 1 <= target < current:
            raise MigrationError(f"can only downgrade to a version between 1 and {current - 1}")
        steps = [m for m in reversed(migrations) if target < m.version <= current]
        missing = [f"v{m.version:04d}" for m in steps if m.down is None]
        if missing:
            raise MigrationError(f"{', '.join(missing)} can't be undone automatically; restore a backup instead "
                                 f"(`habeny db restore`)")
        backup(db_path, f"before-downgrade-v{target}")
        for migration in steps:
            conn.execute("BEGIN IMMEDIATE")
            try:
                migration.down(conn)
                _record(conn, migration, "down")
                conn.execute(f"PRAGMA user_version = {migration.version - 1}")
                conn.execute("COMMIT")
            except Exception as e:
                conn.execute("ROLLBACK")
                raise MigrationError(f"Undoing v{migration.version:04d} failed and was rolled back: {e}") from e
        return steps
    finally:
        conn.close()
