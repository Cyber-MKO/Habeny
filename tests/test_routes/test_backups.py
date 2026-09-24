"""
Full backups: what's in them, API access, download safety, verification, restore,
pruning and scheduling.
"""
import io
import json
import shutil
import sqlite3
import tarfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import migrations
from app.services import backup


@pytest.fixture()
def data(tmp_path, monkeypatch):
    """An isolated data directory with a database, key, report and config template."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db = data_dir / "platform.db"
    migrations.migrate(db)
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO groups (name, created_at, updated_at) VALUES ('red-team', 'x', 'x')")
    conn.commit()
    conn.close()
    (data_dir / "secret.key").write_text("key-v1")
    (data_dir / "reports").mkdir()
    (data_dir / "reports" / "q3.csv").write_text("report v1")
    (data_dir / "configs").mkdir()
    (data_dir / "configs" / "template.json").write_text("{}")
    (data_dir / "agent-cache").mkdir()
    (data_dir / "agent-cache" / "big.deb").write_bytes(b"x" * 1000)
    monkeypatch.setattr(backup, "DATA_DIR", data_dir)
    monkeypatch.setattr(backup, "DB_PATH", db)
    monkeypatch.setenv("HABENY_BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setenv("HABENY_CONFIG", str(tmp_path / "habeny.conf"))
    (tmp_path / "habeny.conf").write_text("HABENY_PORT=9443\n")
    return data_dir


def _names(path: Path) -> set:
    with tarfile.open(path) as archive:
        return {m.name.removeprefix("habeny-backup/") for m in archive.getmembers() if m.isfile()}


def test_backup_contents(data):
    path = backup.create_backup()
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    assert _names(path) == {"manifest.json", "platform.db", "secret.key", "reports/q3.csv",
                            "configs/template.json", "habeny.conf"}  # not the package cache
    manifest = backup.verify_backup(path)
    assert manifest["schema_version"] == migrations.latest_version() and manifest["secret_key"] == "included"


def test_tampered_backup_fails_verification(data, tmp_path):
    path = backup.create_backup()
    tampered = tmp_path / "tampered.tar.gz"
    with tarfile.open(path) as src, tarfile.open(tampered, "w:gz") as dst:
        for member in src.getmembers():
            content = src.extractfile(member).read() if member.isfile() else None
            if member.name.endswith("reports/q3.csv"):
                content = b"report EDITED"
                member.size = len(content)
            dst.addfile(member, io.BytesIO(content) if content is not None else None)
    with pytest.raises(backup.BackupError, match="reports/q3.csv is missing or damaged"):
        backup.verify_backup(tampered)


def test_malicious_archive_is_refused(data, tmp_path):
    evil = tmp_path / "evil.tar.gz"
    with tarfile.open(evil, "w:gz") as archive:
        info = tarfile.TarInfo("habeny-backup/../../etc/cron.d/evil")
        info.size = 3
        archive.addfile(info, io.BytesIO(b"bad"))
    with pytest.raises(backup.BackupError, match="unexpected path"):
        backup.restore_backup(evil)


def test_restore_brings_data_back_and_keeps_what_it_replaced(data):
    path = backup.create_backup()
    conn = sqlite3.connect(data / "platform.db")
    conn.execute("DELETE FROM groups")
    conn.commit()
    conn.close()
    (data / "secret.key").write_text("key-v2")
    (data / "reports" / "q3.csv").write_text("report v2")

    manifest = backup.restore_backup(path)
    groups = [r[0] for r in sqlite3.connect(data / "platform.db").execute("SELECT name FROM groups")]
    assert groups == ["red-team"]
    assert (data / "secret.key").read_text() == "key-v1"
    assert (data / "reports" / "q3.csv").read_text() == "report v1"
    # what was replaced is kept
    assert (data / "secret.key.before-restore").read_text() == "key-v2"
    assert (data / "reports.before-restore" / "q3.csv").read_text() == "report v2"
    assert (data / "restored-habeny.conf").read_text() == "HABENY_PORT=9443\n"
    assert manifest["config_restored_to"].endswith("restored-habeny.conf")


def test_backup_from_newer_habeny_is_refused(data, tmp_path):
    path = backup.create_backup()
    work = tmp_path / "unpacked"
    with tarfile.open(path) as archive:
        archive.extractall(work, filter="data")
    root = work / "habeny-backup"
    manifest = json.loads((root / "manifest.json").read_text())
    manifest["schema_version"] = migrations.latest_version() + 1
    (root / "manifest.json").write_text(json.dumps(manifest))
    newer = tmp_path / "newer.tar.gz"
    with tarfile.open(newer, "w:gz") as archive:
        archive.add(root, arcname="habeny-backup")
    with pytest.raises(backup.BackupError, match="newer Habeny"):
        backup.restore_backup(newer)


def test_old_backups_are_pruned(data, monkeypatch):
    monkeypatch.setenv("HABENY_BACKUP_KEEP", "2")
    for _ in range(4):
        backup.create_backup()
    assert len(backup.list_backups()) == 2


def test_schedule(data, monkeypatch):
    monkeypatch.setenv("HABENY_BACKUP_INTERVAL_HOURS", "0")
    assert backup.backup_if_due() is None
    monkeypatch.setenv("HABENY_BACKUP_INTERVAL_HOURS", "24")
    first = backup.backup_if_due()
    assert first is not None and first.name.endswith("-scheduled.tar.gz")
    assert backup.backup_if_due() is None  # not due again yet
    backup.create_backup("manual")  # manual ones don't reset the schedule's clock
    assert [b["label"] for b in backup.list_backups()].count("scheduled") == 1


def test_unwritable_backup_dir_gives_a_clear_error(data, monkeypatch, tmp_path):
    ro = tmp_path / "readonly"
    ro.mkdir()
    ro.chmod(0o500)
    monkeypatch.setenv("HABENY_BACKUP_DIR", str(ro))
    try:
        if backup.os.access(ro, backup.os.W_OK):
            pytest.skip("running as root: permissions aren't enforced")
        with pytest.raises(backup.BackupError, match="isn't writable"):
            backup.create_backup()
    finally:
        ro.chmod(0o700)


def test_api_admin_only_and_download(app, client, data):
    created = client.post("/system/backups")
    assert created.status_code == 200, created.text
    name = created.json()["data"]["backup"]["name"]
    listed = client.get("/system/backups").json()["data"]
    assert name in [b["name"] for b in listed["backups"]] and listed["schedule"]["interval_hours"] == 24
    download = client.get(f"/system/backups/{name}")
    assert download.status_code == 200 and download.content == (Path(backup.backup_dir()) / name).read_bytes()

    for bad in ("habeny-backup-x.tar.gz", "secret.key", "..%2f..%2fplatform.db", "..%2fsecret.key"):
        resp = client.get(f"/system/backups/{bad}")
        # 404, or (when %2f turns it into another path) the UI page: never a file from the data dir
        assert resp.status_code == 404 or resp.headers["content-type"].startswith("text/html"), bad
        assert not resp.content.startswith(b"SQLite format") and b"key-v1" not in resp.content

    # an operator can't list, create or download
    name_op = "op" + name[-8:-7] + "user1"
    client.post("/users", json={"username": name_op, "password": "operator-password-1", "role": "operator"})
    op = TestClient(app)
    op.post("/auth/login", json={"username": name_op, "password": "operator-password-1"})
    assert op.get("/system/backups").status_code == 403
    assert op.post("/system/backups").status_code == 403
    assert op.get(f"/system/backups/{name}").status_code == 403
    shutil.rmtree(backup.backup_dir())
