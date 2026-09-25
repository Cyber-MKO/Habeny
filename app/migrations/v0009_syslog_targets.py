"""Syslog destinations become part of manager profiles (SIEM targets).

A saved syslog config linked to a profile, with the same address or none, moves onto that
profile. Every other one becomes a profile of its own (SIEM type "none", i.e. syslog only),
so no destination is lost. The syslog_configs table is then dropped.

Containers record whether their UTMstack syslog listener (port 7014) is on, instead of a
syslog config being created for it.
"""
import uuid
from datetime import datetime, timezone

CONFIG_COLUMNS = "config_id, name, description, manager_profile_id, target_ip, target_port, protocol, created_at"


def _unique_name(conn, name: str) -> str:
    candidate, n = name, 1
    while conn.execute("SELECT 1 FROM managers WHERE name = ?", (candidate,)).fetchone():
        n += 1
        candidate = f"{name} (syslog)" if n == 2 else f"{name} (syslog {n - 1})"
    return candidate


def up(conn):
    conn.execute("ALTER TABLE managers ADD COLUMN syslog_port INTEGER")
    conn.execute("ALTER TABLE managers ADD COLUMN syslog_protocol TEXT")
    conn.execute("ALTER TABLE agents ADD COLUMN syslog_listener TEXT")  # "tcp", "udp" or NULL
    now = datetime.now(timezone.utc).isoformat()
    for (_, name, description, profile_id, target_ip, port, protocol, created_at) in conn.execute(
            f"SELECT {CONFIG_COLUMNS} FROM syslog_configs ORDER BY created_at, name").fetchall():
        port, protocol = port or 514, (protocol or "tcp").lower()
        linked = profile_id and conn.execute(
            "SELECT siem_ip, syslog_port FROM managers WHERE manager_id = ?", (profile_id,)).fetchone()
        if linked and linked[1] is None and (not linked[0] or linked[0] == target_ip):
            conn.execute("UPDATE managers SET siem_ip = ?, syslog_port = ?, syslog_protocol = ?, updated_at = ? "
                         "WHERE manager_id = ?", (target_ip, port, protocol, now, profile_id))
            continue
        conn.execute(
            "INSERT INTO managers (manager_id, name, description, siem_type, siem_ip, syslog_port, syslog_protocol, "
            "created_at, updated_at) VALUES (?, ?, ?, 'none', ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), _unique_name(conn, name), description or "Syslog destination",
             target_ip, port, protocol, created_at or now, now))
    conn.execute("DROP TABLE syslog_configs")


def down(conn):
    conn.execute(
        """
        CREATE TABLE syslog_configs (
            config_id TEXT PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            description TEXT,
            manager_profile_id TEXT,
            target_ip TEXT NOT NULL,
            target_port INTEGER DEFAULT 514,
            protocol TEXT DEFAULT 'tcp',
            siem_type TEXT,
            enabled INTEGER DEFAULT 1,
            created_at TEXT,
            updated_at TEXT
        )
        """
    )
    now = datetime.now(timezone.utc).isoformat()
    for (manager_id, name, description, siem_type, siem_ip, port, protocol) in conn.execute(
            "SELECT manager_id, name, description, siem_type, siem_ip, syslog_port, syslog_protocol FROM managers "
            "WHERE syslog_port IS NOT NULL AND siem_ip IS NOT NULL AND siem_ip != ''").fetchall():
        conn.execute(
            "INSERT INTO syslog_configs (config_id, name, description, manager_profile_id, target_ip, target_port, "
            "protocol, siem_type, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), name, description, manager_id, siem_ip, port, protocol or "tcp",
             None if siem_type == "none" else siem_type, now, now))
    conn.execute("ALTER TABLE managers DROP COLUMN syslog_protocol")
    conn.execute("ALTER TABLE managers DROP COLUMN syslog_port")
    conn.execute("ALTER TABLE agents DROP COLUMN syslog_listener")
