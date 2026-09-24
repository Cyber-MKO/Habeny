"""
The `habeny` admin command: version, config, db, backup and prune, run through main().
"""
import sqlite3

import pytest

from app import cli, config, migrations
from app.services import backup, instance


@pytest.fixture()
def data(tmp_path, monkeypatch):
    """Point the CLI at a fresh data directory (not the shared test database)."""
    db = tmp_path / "platform.db"
    migrations.migrate(db)
    monkeypatch.setattr(config, "DB_PATH", db)
    monkeypatch.setattr(backup, "DATA_DIR", tmp_path)
    monkeypatch.setattr(backup, "DB_PATH", db)
    monkeypatch.setattr(instance, "LOCK_FILE", tmp_path / "habeny.lock")
    monkeypatch.setenv("HABENY_BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)  # no systemctl here
    return tmp_path


def run(capsys, *argv):
    code = cli.main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_version(capsys):
    code, out, _ = run(capsys, "version")
    assert code == 0 and out.startswith("Habeny ") and f"schema v{migrations.latest_version()}" in out


def test_config_show_and_check(capsys, monkeypatch):
    monkeypatch.setenv("HABENY_OIDC_CLIENT_SECRET", "super-secret-value")
    code, out, _ = run(capsys, "config")
    assert code == 0 and "HABENY_PORT" in out and "super-secret-value" not in out and "(set, hidden)" in out
    assert run(capsys, "config", "check")[0] == 0
    monkeypatch.setenv("HABENY_PORT", "nope")
    code, _, err = run(capsys, "config", "check")
    assert code == cli.EX_CONFIG and "HABENY_PORT" in err


def test_config_example_and_docs(capsys):
    assert "#HABENY_PORT=9000" in run(capsys, "config", "example")[1]
    assert "| `HABENY_PORT` |" in run(capsys, "config", "docs")[1]


def test_db_commands(capsys, data):
    code, out, _ = run(capsys, "db", "status")
    assert code == 0 and f"v{migrations.latest_version()}" in out and "Backups:   none" in out
    assert "Already up to date" in run(capsys, "db", "migrate")[1]
    code, out, _ = run(capsys, "db", "backup")
    saved = out.strip()
    assert code == 0 and saved.endswith(".db")
    code, out, _ = run(capsys, "db", "restore", saved)
    assert code == 0 and "Restored" in out
    code, _, err = run(capsys, "db", "downgrade", "--to", "1")
    assert code == 0 or "can't be undone" in err  # v0001 has no down(); v0002 does


def test_restore_refuses_while_habeny_runs(capsys, data, monkeypatch):
    monkeypatch.setattr(instance, "running_pid", lambda: 4242)
    code, _, err = run(capsys, "db", "restore", "whatever.db")
    assert code == 1 and "Habeny is running" in err
    code, _, err = run(capsys, "backup", "restore", "whatever.tar.gz")
    assert code == 1 and "Habeny is running" in err


def test_backup_commands(capsys, data):
    conn = sqlite3.connect(config.DB_PATH)
    conn.execute("INSERT INTO groups (name, created_at, updated_at) VALUES ('cli-group', 'x', 'x')")
    conn.commit()
    conn.close()
    code, out, _ = run(capsys, "backup", "create")
    path = out.strip()
    assert code == 0 and path.endswith("-manual.tar.gz")
    assert "manual.tar.gz" in run(capsys, "backup", "list")[1]
    code, out, _ = run(capsys, "backup", "verify", path)
    assert code == 0 and out.startswith("OK: Habeny")
    code, out, _ = run(capsys, "backup", "restore", path)
    assert code == 0 and "Restored the backup" in out
    code, _, err = run(capsys, "backup", "verify", str(data / "missing.tar.gz"))
    assert code == 1 and "isn't a readable backup" in err


def test_prune(capsys, app):
    code, out, _ = run(capsys, "prune", "--dry-run")
    assert code == 0 and out.startswith("Would delete")
    code, out, _ = run(capsys, "prune")
    assert code == 0 and out.startswith("Deleted:")


def test_token_commands(capsys, data):
    from app.db import create_user
    from app.services.auth import hash_password
    create_user(config.DB_PATH, "robot", hash_password("robot-password-1"), "operator")

    code, out, err = run(capsys, "token", "create", "robot", "deploy-bot", "--expires-days", "7")
    assert code == 0 and out.strip().startswith("hby_") and "operator token 'deploy-bot'" in err
    assert run(capsys, "token", "create", "robot", "x", "--role", "admin")[0] == 1  # above the account's role
    assert run(capsys, "token", "create", "nobody", "x")[0] == 1

    code, out, _ = run(capsys, "token", "list")
    assert code == 0 and "deploy-bot" in out and "robot" in out and out.strip().split()[0] == "1"
    assert run(capsys, "token", "revoke", "1")[0] == 0
    assert "No API tokens" in run(capsys, "token", "list")[1]
    assert run(capsys, "token", "revoke", "1")[0] == 1
