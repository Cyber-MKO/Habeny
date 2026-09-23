"""
Versioned migrations: fresh and legacy databases, backups, failure rollback,
downgrade/restore, and refusing a database from a newer Habeny.
"""
import sqlite3
from pathlib import Path

import pytest

from app import migrations
from app.migrations import Migration, MigrationError

LEGACY = sorted((Path(__file__).parent / "fixtures" / "legacy_db").glob("*.sql"))


def _schema(db: Path) -> dict:
    """{table: {(column, type, notnull, default)}} and the index names."""
    conn = sqlite3.connect(db)
    try:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        columns = {t: {tuple(c[1:5]) for c in conn.execute(f"PRAGMA table_info({t})")} for t in tables}
        indexes = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND sql IS NOT NULL")}
        return {"columns": columns, "indexes": indexes}
    finally:
        conn.close()


def _legacy_db(tmp_path: Path, dump: Path) -> Path:
    db = tmp_path / "platform.db"
    conn = sqlite3.connect(db)
    conn.executescript(dump.read_text())
    conn.close()
    return db


@pytest.fixture()
def fresh(tmp_path):
    db = tmp_path / "fresh" / "platform.db"
    db.parent.mkdir()
    migrations.migrate(db)
    return db


def test_fresh_database_is_at_latest_version(fresh):
    assert migrations.current_version(fresh) == migrations.latest_version()
    history = sqlite3.connect(fresh).execute("SELECT version, direction FROM schema_history").fetchall()
    assert history == [(m.version, "up") for m in migrations.all_migrations()]
    assert migrations.list_backups(fresh) == []  # nothing to back up on a new database


@pytest.mark.parametrize("dump", LEGACY, ids=[p.stem for p in LEGACY])
def test_legacy_databases_upgrade_to_the_current_schema(tmp_path, fresh, dump):
    db = _legacy_db(tmp_path, dump)
    assert migrations.current_version(db) == 0
    applied = migrations.migrate(db)
    assert [m.version for m in applied] == list(range(1, migrations.latest_version() + 1))
    assert _schema(db) == _schema(fresh)  # same result as a new install

    conn = sqlite3.connect(db)
    assert conn.execute("SELECT siem_type FROM agents WHERE agent_name='legacy-0001'").fetchone() == ("wazuh",)
    users = conn.execute("SELECT username, role FROM users ORDER BY id").fetchall()
    if users:  # accounts from before roles: the oldest becomes admin, the rest keep operator access
        assert users == [("olduser", "admin"), ("second", "operator")]
    # the untouched original was kept
    (saved,) = migrations.list_backups(db)
    assert sqlite3.connect(saved).execute("PRAGMA user_version").fetchone()[0] == 0


def test_migrating_again_does_nothing(fresh):
    assert migrations.migrate(fresh) == []
    assert migrations.list_backups(fresh) == []


def _with_extra(monkeypatch, up, down=None):
    """Pretend a migration v(latest+1) exists."""
    real = migrations.all_migrations()
    module = type("M", (), {"up": staticmethod(up), "__doc__": "test migration"})
    if down:
        module.down = staticmethod(down)
    extra = Migration(len(real) + 1, "test_extra", module)
    monkeypatch.setattr(migrations, "all_migrations", lambda: [*real, extra])
    return extra


def test_failed_migration_is_rolled_back(fresh, monkeypatch):
    def broken(conn):
        conn.execute("CREATE TABLE half_done (x INTEGER)")
        conn.execute("ALTER TABLE agents ADD COLUMN extra TEXT")
        raise RuntimeError("boom")

    extra = _with_extra(monkeypatch, broken)
    with pytest.raises(MigrationError, match=f"v{extra.version:04d}.*rolled back.*unchanged"):
        migrations.migrate(fresh)
    assert migrations.current_version(fresh) == extra.version - 1
    assert "half_done" not in _schema(fresh)["columns"]
    assert ("extra", "TEXT", 0, None) not in _schema(fresh)["columns"]["agents"]


def test_upgrade_then_downgrade(fresh, monkeypatch):
    extra = _with_extra(monkeypatch,
                        up=lambda c: c.execute("ALTER TABLE agents ADD COLUMN note TEXT"),
                        down=lambda c: c.execute("ALTER TABLE agents DROP COLUMN note"))
    migrations.migrate(fresh)
    assert migrations.current_version(fresh) == extra.version
    assert len(migrations.list_backups(fresh)) == 1  # taken before the upgrade

    migrations.downgrade(fresh, extra.version - 1)
    assert migrations.current_version(fresh) == extra.version - 1
    assert "note" not in {c[0] for c in _schema(fresh)["columns"]["agents"]}
    directions = [r[0] for r in sqlite3.connect(fresh).execute("SELECT direction FROM schema_history")]
    assert directions[-2:] == ["up", "down"]


def test_downgrade_without_down_points_to_restore(fresh, monkeypatch):
    extra = _with_extra(monkeypatch, up=lambda c: None)
    migrations.migrate(fresh)
    with pytest.raises(MigrationError, match="restore a backup"):
        migrations.downgrade(fresh, extra.version - 1)


def test_newer_database_is_refused(fresh):
    conn = sqlite3.connect(fresh)
    conn.execute(f"PRAGMA user_version = {migrations.latest_version() + 1}")
    conn.close()
    with pytest.raises(MigrationError, match="newer version.*restore the backup"):
        migrations.migrate(fresh)


def test_backup_and_restore(fresh):
    conn = sqlite3.connect(fresh)
    conn.execute("INSERT INTO groups (name, created_at, updated_at) VALUES ('keep-me', 'x', 'x')")
    conn.commit()
    saved = migrations.backup(fresh)
    conn.execute("DELETE FROM groups")
    conn.commit()
    conn.close()

    assert migrations.restore(fresh, saved) == migrations.latest_version()
    names = [r[0] for r in sqlite3.connect(fresh).execute("SELECT name FROM groups")]
    assert names == ["keep-me"]
    assert any("before-restore" in p.name for p in migrations.list_backups(fresh))


def test_restore_rejects_bad_files(fresh, tmp_path):
    junk = tmp_path / "junk.db"
    junk.write_text("not a database")
    with pytest.raises(MigrationError, match="isn't a Habeny database"):
        migrations.restore(fresh, junk)
    newer = tmp_path / "newer.db"
    sqlite3.connect(newer).execute(f"PRAGMA user_version = {migrations.latest_version() + 5}")
    with pytest.raises(MigrationError, match="newer than this Habeny"):
        migrations.restore(fresh, newer)


def test_old_backups_are_pruned(fresh, monkeypatch):
    stamps = iter(range(100))

    class Clock:
        @staticmethod
        def now(tz=None):
            from datetime import datetime
            return datetime(2026, 1, 1, 0, 0, next(stamps), tzinfo=tz)

    monkeypatch.setattr(migrations, "datetime", Clock)
    for _ in range(migrations.KEEP_BACKUPS + 3):
        migrations.backup(fresh)
    kept = migrations.list_backups(fresh)
    assert len(kept) == migrations.KEEP_BACKUPS
    assert "000012" in kept[0].name  # newest kept


def test_migration_files_are_well_formed():
    for m in migrations.all_migrations():
        assert m.module.__doc__, f"v{m.version:04d} needs a docstring (shown by `habeny db status`)"
