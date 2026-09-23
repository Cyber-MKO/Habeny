"""
SQLite persistence: agents, groups, manager and syslog profiles, metrics.
"""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.secrets import decrypt_secret, encrypt_secret, is_encrypted


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agents (
                agent_name TEXT PRIMARY KEY,
                seq_id INTEGER UNIQUE NOT NULL,
                siem_type TEXT,
                siem_ip TEXT,
                siem_version TEXT,
                agent_group TEXT,
                os_type TEXT,
                config_template_id TEXT,
                lifecycle_status TEXT,
                state TEXT,
                init_pid INTEGER,
                ip_addresses TEXT,
                siem_agent_status TEXT,
                siem_agent_running INTEGER,
                siem_agent_last_check TEXT,
                manager_host TEXT,
                manager_port TEXT,
                manager_status TEXT,
                manager_reachable INTEGER,
                created_at TEXT,
                updated_at TEXT,
                deleted_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS groups (
                name TEXT PRIMARY KEY,
                description TEXT,
                created_at TEXT,
                updated_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS managers (
                manager_id TEXT PRIMARY KEY,
                name TEXT UNIQUE NOT NULL,
                description TEXT,
                siem_type TEXT NOT NULL,
                siem_ip TEXT,
                siem_version TEXT,
                siem_auth_key TEXT,
                os_type TEXT DEFAULT 'ubuntu_22_04',
                agent_group TEXT DEFAULT 'default',
                memory_limit TEXT DEFAULT '512MB',
                cpu_shares INTEGER DEFAULT 1024,
                config_template_id TEXT,
                created_at TEXT,
                updated_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS syslog_configs (
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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                metric_type TEXT NOT NULL,
                metric_name TEXT NOT NULL,
                value REAL NOT NULL,
                tags TEXT,
                recorded_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS benchmarks (
                benchmark_id TEXT PRIMARY KEY,
                scenario_id TEXT NOT NULL,
                name TEXT,
                siem_type TEXT DEFAULT 'none',
                status TEXT DEFAULT 'pending',
                config TEXT,
                phases TEXT,
                current_phase INTEGER DEFAULT 0,
                results TEXT,
                started_at TEXT,
                completed_at TEXT,
                created_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS benchmark_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                benchmark_id TEXT NOT NULL,
                phase INTEGER DEFAULT 0,
                category TEXT NOT NULL,
                metric_name TEXT NOT NULL,
                value REAL NOT NULL,
                tags TEXT,
                recorded_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS benchmark_bottlenecks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                benchmark_id TEXT NOT NULL,
                phase INTEGER DEFAULT 0,
                severity TEXT NOT NULL,
                component TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                threshold REAL,
                actual_value REAL,
                recommendation TEXT,
                first_seen TEXT,
                occurrences INTEGER DEFAULT 1
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                is_admin INTEGER NOT NULL DEFAULT 0,
                role TEXT NOT NULL DEFAULT 'operator',
                created_at TEXT NOT NULL,
                last_login_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_bm_metrics_bid ON benchmark_metrics(benchmark_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_bm_metrics_time ON benchmark_metrics(recorded_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_bm_bottlenecks_bid ON benchmark_bottlenecks(benchmark_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_metrics_type ON metrics(metric_type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_metrics_time ON metrics(recorded_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_agents_seq_id ON agents(seq_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_agents_siem_type ON agents(siem_type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_agents_group ON agents(agent_group)")

        # Migrations for columns added after initial schema
        for migration in [
            "ALTER TABLE benchmarks ADD COLUMN siem_type TEXT DEFAULT 'none'",
            "ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0",
            # Roles (viewer/operator/admin). Existing non-admin accounts become operators,
            # which keeps the access they had.
            "ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'operator'",
            "ALTER TABLE sessions ADD COLUMN ip TEXT",
            "ALTER TABLE sessions ADD COLUMN user_agent TEXT",
            "ALTER TABLE sessions ADD COLUMN last_seen_at TEXT",
            # Two-factor authentication (secret is encrypted; recovery codes are hashes)
            "ALTER TABLE users ADD COLUMN totp_secret TEXT",
            "ALTER TABLE users ADD COLUMN totp_enabled INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE users ADD COLUMN totp_last_step INTEGER",
            "ALTER TABLE users ADD COLUMN recovery_codes TEXT",
        ]:
            try:
                conn.execute(migration)
            except sqlite3.OperationalError:
                pass  # column already exists

        # Accounts created before roles existed: the oldest one becomes the admin
        conn.execute(
            """
            UPDATE users SET is_admin = 1
            WHERE id = (SELECT MIN(id) FROM users)
              AND NOT EXISTS (SELECT 1 FROM users WHERE is_admin = 1)
            """
        )
        conn.execute("UPDATE users SET role = 'admin' WHERE is_admin = 1 AND role != 'admin'")

        conn.commit()
    finally:
        conn.close()


@contextmanager
def _connection(db_path: Path):
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
    finally:
        conn.close()


def _bool_to_int(value: Optional[bool]) -> Optional[int]:
    if value is None:
        return None
    return 1 if value else 0


def _int_to_bool(value: Any) -> Optional[bool]:
    if value is None:
        return None
    return bool(value)


def _serialize_ip_addresses(value: Any) -> Optional[str]:
    if value is None:
        return None
    return json.dumps(value)


def _deserialize_ip_addresses(value: Any) -> Any:
    if value is None:
        return None
    try:
        return json.loads(value)
    except Exception:
        return value


def get_agent_by_name(db_path: Path, agent_name: str) -> Optional[Dict[str, Any]]:
    with _connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM agents WHERE agent_name = ?",
            (agent_name,)
        ).fetchone()
        if not row:
            return None
        data = dict(row)
        data["ip_addresses"] = _deserialize_ip_addresses(data.get("ip_addresses"))
        data["siem_agent_running"] = _int_to_bool(data.get("siem_agent_running"))
        data["manager_reachable"] = _int_to_bool(data.get("manager_reachable"))
        return data


def get_agent_siem_types(db_path: Path) -> Dict[str, Optional[str]]:
    """agent_name -> stored siem_type for every agent, in one query."""
    with _connection(db_path) as conn:
        return {r["agent_name"]: r["siem_type"] for r in conn.execute("SELECT agent_name, siem_type FROM agents")}


def get_or_create_agent_seq_id(db_path: Path, agent_name: str) -> int:
    with _connection(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT seq_id FROM agents WHERE agent_name = ?",
            (agent_name,)
        ).fetchone()
        if row:
            conn.commit()
            return int(row["seq_id"])

        meta = conn.execute(
            "SELECT value FROM meta WHERE key = 'next_agent_seq_id'"
        ).fetchone()
        next_id = int(meta["value"]) if meta else 1
        conn.execute(
            "INSERT INTO meta (key, value) VALUES ('next_agent_seq_id', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(next_id + 1),)
        )
        now = utc_now()
        conn.execute(
            """
            INSERT INTO agents (agent_name, seq_id, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (agent_name, next_id, now, now)
        )
        conn.commit()
        return next_id


def upsert_agent(db_path: Path, agent_name: str, data: Dict[str, Any]) -> None:
    with _connection(db_path) as conn:
        payload = dict(data)
        payload["agent_name"] = agent_name
        payload["updated_at"] = utc_now()
        if "ip_addresses" in payload:
            payload["ip_addresses"] = _serialize_ip_addresses(payload["ip_addresses"])
        if "siem_agent_running" in payload:
            payload["siem_agent_running"] = _bool_to_int(payload["siem_agent_running"])
        if "manager_reachable" in payload:
            payload["manager_reachable"] = _bool_to_int(payload["manager_reachable"])

        columns = ", ".join(payload.keys())
        placeholders = ", ".join(["?"] * len(payload))
        updates = ", ".join([f"{col}=excluded.{col}" for col in payload.keys() if col != "agent_name"])
        conn.execute(
            f"""
            INSERT INTO agents ({columns})
            VALUES ({placeholders})
            ON CONFLICT(agent_name) DO UPDATE SET {updates}
            """,
            tuple(payload.values())
        )
        conn.commit()


def mark_agent_deleted(db_path: Path, agent_name: str) -> None:
    with _connection(db_path) as conn:
        now = utc_now()
        conn.execute(
            "UPDATE agents SET deleted_at = ?, updated_at = ? WHERE agent_name = ?",
            (now, now, agent_name)
        )
        conn.commit()


def create_group(db_path: Path, name: str, description: Optional[str] = None) -> Dict[str, Any]:
    with _connection(db_path) as conn:
        now = utc_now()
        conn.execute(
            """
            INSERT INTO groups (name, description, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (name, description, now, now)
        )
        conn.commit()
        return {"name": name, "description": description, "created_at": now, "updated_at": now}


def list_groups(db_path: Path) -> Dict[str, Any]:
    with _connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT g.name, g.description, g.created_at, g.updated_at,
                   COUNT(a.agent_name) as agent_count
            FROM groups g
            LEFT JOIN agents a
              ON a.agent_group = g.name AND a.deleted_at IS NULL
            GROUP BY g.name
            ORDER BY g.name
            """
        ).fetchall()
        return {"groups": [dict(row) for row in rows]}


def group_exists(db_path: Path, name: str) -> bool:
    with _connection(db_path) as conn:
        row = conn.execute(
            "SELECT name FROM groups WHERE name = ?",
            (name,)
        ).fetchone()
        return row is not None


def get_agents_in_group(db_path: Path, name: str) -> List[str]:
    with _connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT agent_name FROM agents
            WHERE agent_group = ? AND deleted_at IS NULL
            """,
            (name,)
        ).fetchall()
        return [row["agent_name"] for row in rows]


def assign_agents_to_group(db_path: Path, name: str, agent_names: List[str]) -> int:
    with _connection(db_path) as conn:
        now = utc_now()
        before = conn.total_changes
        for agent_name in agent_names:
            conn.execute(
                """
                UPDATE agents
                SET agent_group = ?, updated_at = ?
                WHERE agent_name = ? AND deleted_at IS NULL
                """,
                (name, now, agent_name)
            )
        conn.commit()
        return conn.total_changes - before


def remove_agents_from_group(db_path: Path, agent_names: List[str]) -> int:
    with _connection(db_path) as conn:
        now = utc_now()
        before = conn.total_changes
        for agent_name in agent_names:
            conn.execute(
                """
                UPDATE agents
                SET agent_group = NULL, updated_at = ?
                WHERE agent_name = ? AND deleted_at IS NULL
                """,
                (now, agent_name)
            )
        conn.commit()
        return conn.total_changes - before


def rename_group(db_path: Path, old_name: str, new_name: str, description: Optional[str] = None) -> Dict[str, Any]:
    with _connection(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute("SELECT name FROM groups WHERE name = ?", (old_name,)).fetchone()
        if not existing:
            raise ValueError("Group not found")
        conflict = conn.execute("SELECT name FROM groups WHERE name = ?", (new_name,)).fetchone()
        if conflict:
            raise ValueError("Group name already exists")

        now = utc_now()
        conn.execute(
            """
            UPDATE groups
            SET name = ?, description = COALESCE(?, description), updated_at = ?
            WHERE name = ?
            """,
            (new_name, description, now, old_name)
        )
        before = conn.total_changes
        conn.execute(
            """
            UPDATE agents
            SET agent_group = ?, updated_at = ?
            WHERE agent_group = ? AND deleted_at IS NULL
            """,
            (new_name, now, old_name)
        )
        conn.commit()
        updated_agents = conn.total_changes - before
        return {"name": new_name, "description": description, "updated_at": now, "containers_updated": updated_agents}


def delete_group(db_path: Path, name: str) -> int:
    with _connection(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        before = conn.total_changes
        conn.execute(
            """
            UPDATE agents
            SET agent_group = NULL, updated_at = ?
            WHERE agent_group = ? AND deleted_at IS NULL
            """,
            (utc_now(), name)
        )
        removed_agents = conn.total_changes - before
        conn.execute("DELETE FROM groups WHERE name = ?", (name,))
        conn.commit()
        return removed_agents


# ===== MANAGER PROFILES =====
# siem_auth_key is stored encrypted (app.core.secrets); these functions return it
# decrypted for internal use. API responses must go through a masking step.

def _manager_row(row) -> Optional[Dict[str, Any]]:
    if not row:
        return None
    mgr = dict(row)
    mgr["siem_auth_key"] = decrypt_secret(mgr.get("siem_auth_key"))
    return mgr


def encrypt_plaintext_manager_secrets(db_path: Path) -> int:
    """One-time upgrade: encrypt auth keys stored before encryption existed."""
    with _connection(db_path) as conn:
        rows = conn.execute("SELECT manager_id, siem_auth_key FROM managers WHERE siem_auth_key IS NOT NULL AND siem_auth_key != ''").fetchall()
        changed = 0
        for r in rows:
            if not is_encrypted(r["siem_auth_key"]):
                conn.execute("UPDATE managers SET siem_auth_key = ? WHERE manager_id = ?",
                             (encrypt_secret(r["siem_auth_key"]), r["manager_id"]))
                changed += 1
        conn.commit()
        return changed


def create_manager(db_path: Path, manager_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    with _connection(db_path) as conn:
        now = utc_now()
        conn.execute(
            """
            INSERT INTO managers (manager_id, name, description, siem_type, siem_ip,
                siem_version, siem_auth_key, os_type, agent_group, memory_limit,
                cpu_shares, config_template_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (manager_id, data["name"], data.get("description"), data["siem_type"],
             data.get("siem_ip"), data.get("siem_version"), encrypt_secret(data.get("siem_auth_key")),
             data.get("os_type", "ubuntu_22_04"), data.get("agent_group", "default"),
             data.get("memory_limit", "512MB"), data.get("cpu_shares", 1024),
             data.get("config_template_id"), now, now)
        )
        conn.commit()
        return {**data, "manager_id": manager_id, "created_at": now, "updated_at": now}


def list_managers(db_path: Path) -> List[Dict[str, Any]]:
    with _connection(db_path) as conn:
        rows = conn.execute("SELECT * FROM managers ORDER BY name").fetchall()
        return [_manager_row(r) for r in rows]


def get_manager(db_path: Path, manager_id: str) -> Optional[Dict[str, Any]]:
    with _connection(db_path) as conn:
        row = conn.execute("SELECT * FROM managers WHERE manager_id = ?", (manager_id,)).fetchone()
        return _manager_row(row)


def get_manager_by_name(db_path: Path, name: str) -> Optional[Dict[str, Any]]:
    with _connection(db_path) as conn:
        row = conn.execute("SELECT * FROM managers WHERE name = ?", (name,)).fetchone()
        return _manager_row(row)


def update_manager(db_path: Path, manager_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    with _connection(db_path) as conn:
        existing = conn.execute("SELECT * FROM managers WHERE manager_id = ?", (manager_id,)).fetchone()
        if not existing:
            return None
        now = utc_now()
        fields = ["name", "description", "siem_type", "siem_ip", "siem_version",
                  "siem_auth_key", "os_type", "agent_group", "memory_limit",
                  "cpu_shares", "config_template_id"]
        updates = []
        values = []
        for f in fields:
            if f in data:
                updates.append(f"{f} = ?")
                values.append(encrypt_secret(data[f]) if f == "siem_auth_key" else data[f])
        if not updates:
            return _manager_row(existing)
        updates.append("updated_at = ?")
        values.append(now)
        values.append(manager_id)
        conn.execute(f"UPDATE managers SET {', '.join(updates)} WHERE manager_id = ?", values)
        conn.commit()
        row = conn.execute("SELECT * FROM managers WHERE manager_id = ?", (manager_id,)).fetchone()
        return _manager_row(row)


def delete_manager(db_path: Path, manager_id: str) -> bool:
    with _connection(db_path) as conn:
        before = conn.total_changes
        conn.execute("DELETE FROM managers WHERE manager_id = ?", (manager_id,))
        conn.commit()
        return conn.total_changes > before


# ===== SYSLOG CONFIGS =====

def create_syslog_config(db_path: Path, config_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    with _connection(db_path) as conn:
        now = utc_now()
        conn.execute(
            """
            INSERT INTO syslog_configs (config_id, name, description, manager_profile_id,
                target_ip, target_port, protocol, siem_type, enabled, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (config_id, data["name"], data.get("description"), data.get("manager_profile_id"),
             data["target_ip"], data.get("target_port", 514), data.get("protocol", "tcp"),
             data.get("siem_type"), 1, now, now)
        )
        conn.commit()
        return {**data, "config_id": config_id, "enabled": True, "created_at": now, "updated_at": now}


def list_syslog_configs(db_path: Path) -> List[Dict[str, Any]]:
    with _connection(db_path) as conn:
        rows = conn.execute("SELECT * FROM syslog_configs ORDER BY name").fetchall()
        return [dict(r) for r in rows]


def get_syslog_config(db_path: Path, config_id: str) -> Optional[Dict[str, Any]]:
    with _connection(db_path) as conn:
        row = conn.execute("SELECT * FROM syslog_configs WHERE config_id = ?", (config_id,)).fetchone()
        return dict(row) if row else None


def update_syslog_config(db_path: Path, config_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    with _connection(db_path) as conn:
        existing = conn.execute("SELECT * FROM syslog_configs WHERE config_id = ?", (config_id,)).fetchone()
        if not existing:
            return None
        now = utc_now()
        fields = ["name", "description", "manager_profile_id", "target_ip", "target_port",
                  "protocol", "siem_type", "enabled"]
        updates, values = [], []
        for f in fields:
            if f in data:
                updates.append(f"{f} = ?")
                values.append(data[f])
        if not updates:
            return dict(existing)
        updates.append("updated_at = ?")
        values.append(now)
        values.append(config_id)
        conn.execute(f"UPDATE syslog_configs SET {', '.join(updates)} WHERE config_id = ?", values)
        conn.commit()
        row = conn.execute("SELECT * FROM syslog_configs WHERE config_id = ?", (config_id,)).fetchone()
        return dict(row)


def delete_syslog_config(db_path: Path, config_id: str) -> bool:
    with _connection(db_path) as conn:
        before = conn.total_changes
        conn.execute("DELETE FROM syslog_configs WHERE config_id = ?", (config_id,))
        conn.commit()
        return conn.total_changes > before


# ===== METRICS =====

def record_metric(db_path: Path, metric_type: str, metric_name: str,
                  value: float, tags: Optional[str] = None) -> None:
    with _connection(db_path) as conn:
        conn.execute(
            "INSERT INTO metrics (metric_type, metric_name, value, tags, recorded_at) VALUES (?, ?, ?, ?, ?)",
            (metric_type, metric_name, value, tags, utc_now())
        )
        conn.commit()


def record_metrics_batch(db_path: Path, rows: List[tuple]) -> None:
    """rows: list of (metric_type, metric_name, value, tags)"""
    with _connection(db_path) as conn:
        now = utc_now()
        conn.executemany(
            "INSERT INTO metrics (metric_type, metric_name, value, tags, recorded_at) VALUES (?, ?, ?, ?, ?)",
            [(t, n, v, tg, now) for t, n, v, tg in rows]
        )
        conn.commit()


def query_metrics(db_path: Path, metric_type: Optional[str] = None,
                  metric_name: Optional[str] = None,
                  since: Optional[str] = None, limit: int = 500) -> List[Dict[str, Any]]:
    with _connection(db_path) as conn:
        sql = "SELECT * FROM metrics WHERE 1=1"
        params: list = []
        if metric_type:
            sql += " AND metric_type = ?"
            params.append(metric_type)
        if metric_name:
            sql += " AND metric_name = ?"
            params.append(metric_name)
        if since:
            sql += " AND recorded_at >= ?"
            params.append(since)
        sql += " ORDER BY recorded_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def get_metric_summary(db_path: Path, metric_type: str, metric_name: str,
                       since: Optional[str] = None) -> Dict[str, Any]:
    with _connection(db_path) as conn:
        sql = "SELECT COUNT(*) as cnt, AVG(value) as avg, MIN(value) as min, MAX(value) as max FROM metrics WHERE metric_type = ? AND metric_name = ?"
        params: list = [metric_type, metric_name]
        if since:
            sql += " AND recorded_at >= ?"
            params.append(since)
        row = conn.execute(sql, params).fetchone()
        d = dict(row)
        # percentiles via sorted values
        vals_sql = "SELECT value FROM metrics WHERE metric_type = ? AND metric_name = ?"
        vals_params: list = [metric_type, metric_name]
        if since:
            vals_sql += " AND recorded_at >= ?"
            vals_params.append(since)
        vals_sql += " ORDER BY value"
        vals = [r["value"] for r in conn.execute(vals_sql, vals_params).fetchall()]
        n = len(vals)
        if n > 0:
            d["p50"] = vals[int(n * 0.5)]
            d["p90"] = vals[int(n * 0.9)]
            d["p99"] = vals[min(int(n * 0.99), n - 1)]
        return d


# ===== USERS & SESSIONS =====

def count_users(db_path: Path) -> int:
    with _connection(db_path) as conn:
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def create_first_user(db_path: Path, username: str, password_hash: str) -> Optional[Dict[str, Any]]:
    """Create a user only if none exist yet (first-run setup). Returns None if one already exists."""
    with _connection(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")  # serialize concurrent setup attempts
        if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
            conn.rollback()
            return None
        now = utc_now()
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, is_admin, role, created_at) VALUES (?, ?, 1, 'admin', ?)",
            (username, password_hash, now),
        )
        conn.commit()
        return {"id": cur.lastrowid, "username": username, "is_admin": True, "role": "admin", "created_at": now}


def _user_row(row) -> Optional[Dict[str, Any]]:
    if not row:
        return None
    user = dict(row)
    for flag in ("is_admin", "totp_enabled"):
        if flag in user:
            user[flag] = bool(user[flag])
    return user


def get_user_by_username(db_path: Path, username: str) -> Optional[Dict[str, Any]]:
    with _connection(db_path) as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        return _user_row(row)


def get_user_by_id(db_path: Path, user_id: int) -> Optional[Dict[str, Any]]:
    with _connection(db_path) as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return _user_row(row)


def list_users(db_path: Path) -> List[Dict[str, Any]]:
    with _connection(db_path) as conn:
        rows = conn.execute(
            "SELECT id, username, is_admin, role, totp_enabled, created_at, last_login_at FROM users"
            " ORDER BY username COLLATE NOCASE"
        ).fetchall()
        return [_user_row(r) for r in rows]


def create_user(db_path: Path, username: str, password_hash: str, role: str) -> Optional[Dict[str, Any]]:
    """Create a user. Returns None if the username is taken (case-insensitive)."""
    with _connection(db_path) as conn:
        now = utc_now()
        try:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash, is_admin, role, created_at) VALUES (?, ?, ?, ?, ?)",
                (username, password_hash, int(role == "admin"), role, now),
            )
        except sqlite3.IntegrityError:
            return None
        conn.commit()
        return {"id": cur.lastrowid, "username": username, "is_admin": role == "admin", "role": role,
                "created_at": now, "last_login_at": None}


def update_user_password(db_path: Path, user_id: int, password_hash: str) -> None:
    with _connection(db_path) as conn:
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, user_id))
        conn.commit()


def _is_last_admin(conn, user_id: int) -> bool:
    row = conn.execute("SELECT is_admin FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row or not row[0]:
        return False
    return conn.execute("SELECT COUNT(*) FROM users WHERE is_admin = 1").fetchone()[0] <= 1


def set_user_role(db_path: Path, user_id: int, role: str) -> bool:
    """Change a user's role. Returns False (and changes nothing) if it would remove the last admin."""
    with _connection(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        if role != "admin" and _is_last_admin(conn, user_id):
            conn.rollback()
            return False
        conn.execute("UPDATE users SET role = ?, is_admin = ? WHERE id = ?", (role, int(role == "admin"), user_id))
        conn.commit()
        return True


def delete_user(db_path: Path, user_id: int) -> bool:
    """Delete a user and their sessions. Returns False (and changes nothing) if they are the last admin."""
    with _connection(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        if _is_last_admin(conn, user_id):
            conn.rollback()
            return False
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
        return True


def delete_user_sessions(db_path: Path, user_id: int, keep_token_hash: Optional[str] = None) -> None:
    """Sign a user out everywhere (optionally except one session)."""
    with _connection(db_path) as conn:
        conn.execute(
            "DELETE FROM sessions WHERE user_id = ? AND token_hash IS NOT ?",
            (user_id, keep_token_hash),
        )
        conn.commit()


def set_pending_totp(db_path: Path, user_id: int, encrypted_secret: str) -> None:
    """Store a secret being enrolled; it only takes effect once enable_totp confirms a code."""
    with _connection(db_path) as conn:
        conn.execute("UPDATE users SET totp_secret = ? WHERE id = ? AND totp_enabled = 0",
                     (encrypted_secret, user_id))
        conn.commit()


def enable_totp(db_path: Path, user_id: int, step: int, recovery_hashes: List[str]) -> None:
    with _connection(db_path) as conn:
        conn.execute(
            "UPDATE users SET totp_enabled = 1, totp_last_step = ?, recovery_codes = ? WHERE id = ?",
            (step, json.dumps(recovery_hashes), user_id),
        )
        conn.commit()


def disable_totp(db_path: Path, user_id: int) -> None:
    with _connection(db_path) as conn:
        conn.execute(
            "UPDATE users SET totp_enabled = 0, totp_secret = NULL, totp_last_step = NULL, recovery_codes = NULL"
            " WHERE id = ?",
            (user_id,),
        )
        conn.commit()


def claim_totp_step(db_path: Path, user_id: int, step: int) -> bool:
    """Record a used code's time step. False if it (or a later one) was already used."""
    with _connection(db_path) as conn:
        cur = conn.execute(
            "UPDATE users SET totp_last_step = ? WHERE id = ? AND (totp_last_step IS NULL OR totp_last_step < ?)",
            (step, user_id, step),
        )
        conn.commit()
        return cur.rowcount == 1


def set_recovery_codes(db_path: Path, user_id: int, recovery_hashes: List[str]) -> None:
    with _connection(db_path) as conn:
        conn.execute("UPDATE users SET recovery_codes = ? WHERE id = ?", (json.dumps(recovery_hashes), user_id))
        conn.commit()


def use_recovery_code(db_path: Path, user_id: int, code_hash: str) -> bool:
    """Consume a recovery code. False if it isn't one of the user's unused codes."""
    with _connection(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT recovery_codes FROM users WHERE id = ?", (user_id,)).fetchone()
        codes = json.loads(row[0]) if row and row[0] else []
        if code_hash not in codes:
            conn.rollback()
            return False
        codes.remove(code_hash)
        conn.execute("UPDATE users SET recovery_codes = ? WHERE id = ?", (json.dumps(codes), user_id))
        conn.commit()
        return True


def update_user_last_login(db_path: Path, user_id: int) -> None:
    with _connection(db_path) as conn:
        conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (utc_now(), user_id))
        conn.commit()


def create_session(db_path: Path, token_hash: str, user_id: int, expires_at: str,
                   ip: Optional[str] = None, user_agent: Optional[str] = None) -> None:
    with _connection(db_path) as conn:
        now = utc_now()
        conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
        conn.execute(
            "INSERT INTO sessions (token_hash, user_id, created_at, expires_at, ip, user_agent, last_seen_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (token_hash, user_id, now, expires_at, ip, (user_agent or "")[:300], now),
        )
        conn.commit()


def touch_session(db_path: Path, token_hash: str, ip: Optional[str]) -> None:
    with _connection(db_path) as conn:
        conn.execute("UPDATE sessions SET last_seen_at = ?, ip = COALESCE(?, ip) WHERE token_hash = ?",
                     (utc_now(), ip, token_hash))
        conn.commit()


def list_user_sessions(db_path: Path, user_id: int) -> List[Dict[str, Any]]:
    with _connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT token_hash, created_at, last_seen_at, expires_at, ip, user_agent
            FROM sessions WHERE user_id = ? AND expires_at > ? ORDER BY COALESCE(last_seen_at, created_at) DESC
            """,
            (user_id, utc_now()),
        ).fetchall()
        return [dict(r) for r in rows]


def get_session_user(db_path: Path, token_hash: str) -> Optional[Dict[str, Any]]:
    """Return the user for a live (unexpired) session, or None."""
    with _connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT u.id, u.username, u.is_admin, u.role, u.totp_enabled, u.created_at, u.last_login_at,
                   s.last_seen_at AS session_last_seen_at
            FROM sessions s JOIN users u ON u.id = s.user_id
            WHERE s.token_hash = ? AND s.expires_at > ?
            """,
            (token_hash, utc_now()),
        ).fetchone()
        return _user_row(row)


def delete_session(db_path: Path, token_hash: str) -> None:
    with _connection(db_path) as conn:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
        conn.commit()
