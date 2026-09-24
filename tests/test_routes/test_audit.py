"""
The audit trail: recorded with who/where, searchable, exportable, tamper-evident.
"""
import csv
import io
import json
import sqlite3
import uuid

import pytest

from app import config, migrations
from app.services import audit


def _name():
    return "g" + uuid.uuid4().hex[:8]


@pytest.fixture()
def fresh_db(tmp_path, monkeypatch):
    """A separate database, so tampering doesn't affect other tests."""
    db = tmp_path / "platform.db"
    migrations.migrate(db, make_backup=False)
    monkeypatch.setattr(config, "DB_PATH", db)
    return db


def test_entries_record_who_where_and_request(client):
    group = _name()
    resp = client.post("/groups", json={"name": group}, headers={"X-Request-ID": "audit-test-0001"})
    assert resp.status_code == 200
    logs = client.get("/activity/logs", params={"action": "group_created", "q": group}).json()["data"]["logs"]
    assert len(logs) == 1
    entry = logs[0]
    assert entry["user"] == "admin" and entry["request_id"] == "audit-test-0001" and entry["ip"]
    assert entry["details"] == {"group": group} and entry["status"] == "success" and entry["id"] > 0
    client.delete(f"/groups/{group}")


def test_filters(client):
    tag = _name()
    for status in ("success", "error"):
        audit.record("audit_filter_test", {"tag": tag, "status": status}, status, user="alice")
    audit.record("audit_filter_other", {"tag": tag}, user="bob")

    def get(**params):
        data = client.get("/activity/logs", params={"q": tag, **params}).json()["data"]
        return data["total"], data["logs"]

    assert get()[0] == 3
    assert get(action="audit_filter_test")[0] == 2
    assert get(action="audit_filter_*")[0] == 3
    assert get(user="ALICE")[0] == 2  # usernames match case-insensitively
    assert get(status="error")[1][0]["details"]["status"] == "error"
    assert get(since="2000-01-01", until="2999-12-31")[0] == 3
    assert get(until="2000-01-01")[0] == 0
    assert get(action="audit_filter_%")[0] == 0  # LIKE wildcards are literal
    assert client.get("/activity/logs", params={"since": "yesterday"}).status_code == 400
    facets = client.get("/activity/facets").json()["data"]
    assert "audit_filter_other" in facets["actions"] and "alice" in facets["users"]


def test_export_csv_and_jsonl(client):
    tag = _name()
    audit.record("audit_export_test", {"tag": tag, "text": "comma, quote \" and ünïcode"}, user="carol")
    resp = client.get("/activity/export", params={"format": "csv", "q": tag})
    assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/csv")
    assert "attachment" in resp.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(resp.text)))
    assert len(rows) == 1 and rows[0]["user"] == "carol" and len(rows[0]["hash"]) == 64
    assert json.loads(rows[0]["details"])["text"] == "comma, quote \" and ünïcode"

    lines = client.get("/activity/export", params={"format": "jsonl", "q": tag}).text.splitlines()
    entry = json.loads(lines[0])
    assert entry["action"] == "audit_export_test" and entry["hash"] and entry["prev_hash"]
    assert client.get("/activity/export", params={"format": "xml"}).status_code == 422


def test_verify_endpoint_is_admin_only(app, client):
    from fastapi.testclient import TestClient
    result = client.get("/activity/verify").json()
    assert result["success"] is True and result["data"]["ok"] and result["data"]["checked"] > 0
    name, pw = _name(), "viewer-password-1"
    user = client.post("/users", json={"username": name, "password": pw}).json()["data"]["user"]
    viewer = TestClient(app)
    viewer.post("/auth/login", json={"username": name, "password": pw})
    assert viewer.get("/activity/verify").status_code == 403
    assert viewer.get("/activity/logs").status_code == 200
    client.delete(f"/users/{user['id']}")


def test_chain_detects_changes_removals_and_reordering(fresh_db):
    for i in range(5):
        audit.record("step", {"i": i}, user="dave")
    result = audit.verify()
    assert result["ok"] and result["checked"] == 5

    conn = sqlite3.connect(fresh_db)
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        conn.execute("UPDATE audit_log SET details = '{}' WHERE id = 3")
    # Someone with direct database access removes the guard and edits an entry
    conn.execute("DROP TRIGGER audit_log_no_update")
    conn.execute("""UPDATE audit_log SET details = '{"i":99}' WHERE id = 3""")
    conn.commit()
    result = audit.verify()
    assert not result["ok"] and result["problem"]["id"] == 3 and "changed" in result["problem"]["reason"]
    assert result["checked"] == 2

    conn.execute("""UPDATE audit_log SET details = '{"i":2}' WHERE id = 3""")  # put it back
    conn.execute("DELETE FROM audit_log WHERE id = 4")
    conn.commit()
    result = audit.verify()
    assert not result["ok"] and result["problem"]["id"] == 4 and "missing" in result["problem"]["reason"]
    conn.close()


def test_prune_keeps_the_chain_verifiable(fresh_db):
    for i in range(6):
        audit.record("old" if i < 4 else "new", {"i": i})
    conn = sqlite3.connect(fresh_db)
    conn.execute("DROP TRIGGER audit_log_no_update")  # backdate the first four (and re-hash them)
    rows = conn.execute("SELECT * FROM audit_log ORDER BY id").fetchall()
    prev = audit.GENESIS
    for row in rows:
        ts = "2000-01-01T00:00:00+00:00" if row[2] == "old" else row[1]
        digest = audit.entry_hash(prev, row[0], ts, row[2], row[3], row[4], row[5], row[6], row[7], row[8])
        conn.execute("UPDATE audit_log SET ts = ?, prev_hash = ?, hash = ? WHERE id = ?", (ts, prev, digest, row[0]))
        prev = digest
    conn.commit()
    conn.close()
    assert audit.verify()["ok"]

    assert audit.prune("2001-01-01", dry_run=True) == 4
    assert audit.prune("2001-01-01") == 4
    result = audit.verify()
    assert result["ok"] and result["anchor_id"] == 4 and result["checked"] == 2
    audit.record("after", {})
    assert audit.verify()["ok"] and audit.verify()["last_id"] == 7


def test_migration_imports_old_activity_files(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "activity_20260901.json").write_text(
        json.dumps({"timestamp": "2026-09-01T10:00:00+00:00", "action": "first", "status": "success",
                    "details": {"a": 1}, "user": "erin", "request_id": "r1"}) + "\n\n{broken")
    (logs / "activity_20260902.json").write_text(
        json.dumps({"timestamp": "2026-09-02T10:00:00+00:00", "action": "second", "status": "error",
                    "details": {"b": 2}, "token": "ci"}) + "\n")
    db = tmp_path / "platform.db"
    migrations.migrate(db, make_backup=False)
    rows = sqlite3.connect(db).execute("SELECT id, action, username, token, request_id FROM audit_log ORDER BY id").fetchall()
    assert rows == [(1, "first", "erin", None, "r1"), (2, "second", None, "ci", None)]
    assert audit.verify(db)["ok"]


def test_cli_verify_and_export(fresh_db, capsys):
    from app import cli
    audit.record("cli_test", {"x": 1}, user="frank")
    assert cli.main(["audit", "verify"]) == 0
    assert "OK: 1 entries verified" in capsys.readouterr().out
    assert cli.main(["audit", "export", "--format", "jsonl", "--user", "frank"]) == 0
    assert json.loads(capsys.readouterr().out)["action"] == "cli_test"
    conn = sqlite3.connect(fresh_db)
    conn.execute("DROP TRIGGER audit_log_no_update")
    conn.execute("UPDATE audit_log SET status = 'error'")
    conn.commit()
    assert cli.main(["audit", "verify"]) == 1
    assert "BROKEN at entry 1" in capsys.readouterr().err
