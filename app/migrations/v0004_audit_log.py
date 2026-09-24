"""Audit trail in the database (hash-chained), imported from the daily activity files."""
import json
from pathlib import Path


def up(conn):
    conn.execute(
        """
        CREATE TABLE audit_log (
            id INTEGER PRIMARY KEY,
            ts TEXT NOT NULL,
            action TEXT NOT NULL,
            status TEXT NOT NULL,
            username TEXT,
            token TEXT,
            ip TEXT,
            request_id TEXT,
            details TEXT NOT NULL,
            prev_hash TEXT NOT NULL,
            hash TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX idx_audit_ts ON audit_log(ts)")
    conn.execute("CREATE INDEX idx_audit_user_ts ON audit_log(username COLLATE NOCASE, ts)")
    conn.execute("CREATE INDEX idx_audit_action_ts ON audit_log(action, ts)")
    # Entries are never edited; pruning (oldest first) is the only removal
    conn.execute(
        """
        CREATE TRIGGER audit_log_no_update BEFORE UPDATE ON audit_log
        BEGIN SELECT RAISE(ABORT, 'the audit log is append-only'); END
        """
    )
    _import_activity_files(conn)


def _import_activity_files(conn):
    """Bring in the activity_YYYYMMDD.json files written by earlier versions, oldest first."""
    from app.services.audit import append

    main_db = next((row[2] for row in conn.execute("PRAGMA database_list") if row[1] == "main"), "")
    if not main_db:
        return
    logs_dir = Path(main_db).parent / "logs"
    for path in sorted(logs_dir.glob("activity_*.json")):
        try:
            lines = path.read_text(errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            line = line.strip()
            if not (line.startswith("{") and line.endswith("}")):
                continue
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if not isinstance(e, dict) or not e.get("action"):
                continue
            append(conn, str(e.get("timestamp", "")), str(e["action"]), str(e.get("status", "success")),
                   e.get("user"), e.get("token"), None, e.get("request_id"),
                   e.get("details") if isinstance(e.get("details"), dict) else {"value": e.get("details")})


def down(conn):
    conn.execute("DROP TABLE audit_log")
    conn.execute("DELETE FROM meta WHERE key IN ('audit_anchor_id', 'audit_anchor_hash')")
