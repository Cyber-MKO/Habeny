"""
SQLite persistence: agents, groups, manager and syslog profiles, metrics.
"""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.secrets import decrypt_secret, encrypt_secret, is_encrypted


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db(db_path: Path) -> None:
    """Create or upgrade the database to the current schema (see app/migrations)."""
    from app.migrations import migrate
    migrate(db_path)


@contextmanager
def _connection(db_path: Path):
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
    finally:
        conn.close()


def _bool_to_int(value: bool | None) -> int | None:
    if value is None:
        return None
    return 1 if value else 0


def _int_to_bool(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(value)


def _serialize_ip_addresses(value: Any) -> str | None:
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


def get_agent_by_name(db_path: Path, agent_name: str) -> dict[str, Any] | None:
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


def get_agent_siem_types(db_path: Path) -> dict[str, str | None]:
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


def mark_agents_interrupted(db_path: Path, from_status: str, to_status: str) -> int:
    with _connection(db_path) as conn:
        cur = conn.execute("UPDATE agents SET lifecycle_status = ?, updated_at = ? WHERE lifecycle_status = ?",
                           (to_status, utc_now(), from_status))
        conn.commit()
        return cur.rowcount


def upsert_agent(db_path: Path, agent_name: str, data: dict[str, Any]) -> None:
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
        updates = ", ".join([f"{col}=excluded.{col}" for col in payload if col != "agent_name"])
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


def create_group(db_path: Path, name: str, description: str | None = None) -> dict[str, Any]:
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


def list_groups(db_path: Path) -> dict[str, Any]:
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


def get_agents_in_group(db_path: Path, name: str) -> list[str]:
    with _connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT agent_name FROM agents
            WHERE agent_group = ? AND deleted_at IS NULL
            """,
            (name,)
        ).fetchall()
        return [row["agent_name"] for row in rows]


def assign_agents_to_group(db_path: Path, name: str, agent_names: list[str]) -> int:
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


def remove_agents_from_group(db_path: Path, agent_names: list[str]) -> int:
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


def rename_group(db_path: Path, old_name: str, new_name: str, description: str | None = None) -> dict[str, Any]:
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

def _manager_row(row) -> dict[str, Any] | None:
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


def create_manager(db_path: Path, manager_id: str, data: dict[str, Any]) -> dict[str, Any]:
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


def list_managers(db_path: Path) -> list[dict[str, Any]]:
    with _connection(db_path) as conn:
        rows = conn.execute("SELECT * FROM managers ORDER BY name").fetchall()
        return [_manager_row(r) for r in rows]


def get_manager(db_path: Path, manager_id: str) -> dict[str, Any] | None:
    with _connection(db_path) as conn:
        row = conn.execute("SELECT * FROM managers WHERE manager_id = ?", (manager_id,)).fetchone()
        return _manager_row(row)


def get_manager_by_name(db_path: Path, name: str) -> dict[str, Any] | None:
    with _connection(db_path) as conn:
        row = conn.execute("SELECT * FROM managers WHERE name = ?", (name,)).fetchone()
        return _manager_row(row)


def update_manager(db_path: Path, manager_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
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

def create_syslog_config(db_path: Path, config_id: str, data: dict[str, Any]) -> dict[str, Any]:
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


def list_syslog_configs(db_path: Path) -> list[dict[str, Any]]:
    with _connection(db_path) as conn:
        rows = conn.execute("SELECT * FROM syslog_configs ORDER BY name").fetchall()
        return [dict(r) for r in rows]


def get_syslog_config(db_path: Path, config_id: str) -> dict[str, Any] | None:
    with _connection(db_path) as conn:
        row = conn.execute("SELECT * FROM syslog_configs WHERE config_id = ?", (config_id,)).fetchone()
        return dict(row) if row else None


def update_syslog_config(db_path: Path, config_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
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
                  value: float, tags: str | None = None) -> None:
    with _connection(db_path) as conn:
        conn.execute(
            "INSERT INTO metrics (metric_type, metric_name, value, tags, recorded_at) VALUES (?, ?, ?, ?, ?)",
            (metric_type, metric_name, value, tags, utc_now())
        )
        conn.commit()


def record_metrics_batch(db_path: Path, rows: list[tuple]) -> None:
    """rows: list of (metric_type, metric_name, value, tags[, recorded_at]); without a time, now."""
    with _connection(db_path) as conn:
        now = utc_now()
        conn.executemany(
            "INSERT INTO metrics (metric_type, metric_name, value, tags, recorded_at) VALUES (?, ?, ?, ?, ?)",
            [(r[0], r[1], r[2], r[3], r[4] if len(r) > 4 else now) for r in rows]
        )
        conn.commit()


def prune_metrics(db_path: Path, before: str, metric_types: list[str] | None = None,
                  exclude_types: list[str] | None = None, batch: int = 5000) -> int:
    """Delete metric rows recorded before `before` (ISO time), a batch at a time so writers
    aren't blocked for long. Returns the number deleted."""
    where, params = "recorded_at < ?", [before]
    if metric_types:
        where += f" AND metric_type IN ({','.join('?' * len(metric_types))})"
        params += metric_types
    if exclude_types:
        where += f" AND metric_type NOT IN ({','.join('?' * len(exclude_types))})"
        params += exclude_types
    deleted = 0
    while True:
        with _connection(db_path) as conn:
            cur = conn.execute(f"DELETE FROM metrics WHERE id IN (SELECT id FROM metrics WHERE {where} LIMIT ?)",
                               (*params, batch))
            conn.commit()
        deleted += cur.rowcount
        if cur.rowcount < batch:
            return deleted


def prune_expired_sessions(db_path: Path) -> int:
    with _connection(db_path) as conn:
        cur = conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (utc_now(),))
        conn.commit()
        return cur.rowcount


def query_metrics(db_path: Path, metric_type: str | None = None,
                  metric_name: str | None = None,
                  since: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
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
                       since: str | None = None) -> dict[str, Any]:
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


def create_first_user(db_path: Path, username: str, password_hash: str) -> dict[str, Any] | None:
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


def _user_row(row) -> dict[str, Any] | None:
    if not row:
        return None
    user = dict(row)
    for flag in ("is_admin", "totp_enabled"):
        if flag in user:
            user[flag] = bool(user[flag])
    return user


def get_user_by_username(db_path: Path, username: str) -> dict[str, Any] | None:
    with _connection(db_path) as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        return _user_row(row)


def get_user_by_id(db_path: Path, user_id: int) -> dict[str, Any] | None:
    with _connection(db_path) as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return _user_row(row)


def list_users(db_path: Path) -> list[dict[str, Any]]:
    with _connection(db_path) as conn:
        rows = conn.execute(
            "SELECT id, username, is_admin, role, totp_enabled, oidc_subject, created_at, last_login_at, team_id,"
            " max_containers FROM users"
            " ORDER BY username COLLATE NOCASE"
        ).fetchall()
        return [_user_row(r) for r in rows]


def create_user(db_path: Path, username: str, password_hash: str, role: str) -> dict[str, Any] | None:
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


# Stored as the password hash of single sign-on accounts: matches no password
SSO_ONLY_PASSWORD = "!sso"


def get_user_by_oidc_subject(db_path: Path, subject: str) -> dict[str, Any] | None:
    with _connection(db_path) as conn:
        row = conn.execute("SELECT * FROM users WHERE oidc_subject = ?", (subject,)).fetchone()
        return _user_row(row)


def create_sso_user(db_path: Path, username: str, subject: str, role: str) -> dict[str, Any] | None:
    """Create an account for a single sign-on identity. None if the username is taken."""
    with _connection(db_path) as conn:
        now = utc_now()
        try:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash, is_admin, role, oidc_subject, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (username, SSO_ONLY_PASSWORD, int(role == "admin"), role, subject, now),
            )
        except sqlite3.IntegrityError:
            return None
        conn.commit()
        return {
            "id": cur.lastrowid, "username": username, "is_admin": role == "admin", "role": role,
            "oidc_subject": subject, "totp_enabled": False, "created_at": now, "last_login_at": None,
        }


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


def delete_user_sessions(db_path: Path, user_id: int, keep_token_hash: str | None = None) -> None:
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


def enable_totp(db_path: Path, user_id: int, step: int, recovery_hashes: list[str]) -> None:
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


def set_recovery_codes(db_path: Path, user_id: int, recovery_hashes: list[str]) -> None:
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
                   ip: str | None = None, user_agent: str | None = None) -> None:
    with _connection(db_path) as conn:
        now = utc_now()
        conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
        conn.execute(
            "INSERT INTO sessions (token_hash, user_id, created_at, expires_at, ip, user_agent, last_seen_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (token_hash, user_id, now, expires_at, ip, (user_agent or "")[:300], now),
        )
        conn.commit()


def touch_session(db_path: Path, token_hash: str, ip: str | None) -> None:
    with _connection(db_path) as conn:
        conn.execute("UPDATE sessions SET last_seen_at = ?, ip = COALESCE(?, ip) WHERE token_hash = ?",
                     (utc_now(), ip, token_hash))
        conn.commit()


def list_user_sessions(db_path: Path, user_id: int) -> list[dict[str, Any]]:
    with _connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT token_hash, created_at, last_seen_at, expires_at, ip, user_agent
            FROM sessions WHERE user_id = ? AND expires_at > ? ORDER BY COALESCE(last_seen_at, created_at) DESC
            """,
            (user_id, utc_now()),
        ).fetchall()
        return [dict(r) for r in rows]


def get_session_user(db_path: Path, token_hash: str) -> dict[str, Any] | None:
    """Return the user for a live (unexpired) session, or None."""
    with _connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT u.id, u.username, u.is_admin, u.role, u.totp_enabled, u.oidc_subject, u.created_at, u.last_login_at,
                   u.team_id, u.max_containers, s.last_seen_at AS session_last_seen_at
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


# ===== API TOKENS =====

def create_api_token(db_path: Path, user_id: int, name: str, token_hash: str, prefix: str, role: str,
                     expires_at: str | None) -> dict[str, Any]:
    with _connection(db_path) as conn:
        now = utc_now()
        cur = conn.execute(
            "INSERT INTO api_tokens (user_id, name, token_hash, prefix, role, created_at, expires_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, name, token_hash, prefix, role, now, expires_at),
        )
        conn.commit()
        return {"id": cur.lastrowid, "user_id": user_id, "name": name, "prefix": prefix, "role": role,
                "created_at": now, "expires_at": expires_at, "last_used_at": None, "last_used_ip": None}


def list_api_tokens(db_path: Path, user_id: int | None = None) -> list[dict[str, Any]]:
    """A user's tokens, or every token (with its owner) when user_id is None."""
    with _connection(db_path) as conn:
        query = ("SELECT t.id, t.user_id, u.username, t.name, t.prefix, t.role, t.created_at, t.expires_at,"
                 " t.last_used_at, t.last_used_ip FROM api_tokens t JOIN users u ON u.id = t.user_id")
        if user_id is None:
            rows = conn.execute(query + " ORDER BY t.created_at DESC").fetchall()
        else:
            rows = conn.execute(query + " WHERE t.user_id = ? ORDER BY t.created_at DESC", (user_id,)).fetchall()
        return [dict(r) for r in rows]


def get_api_token_user(db_path: Path, token_hash: str) -> dict[str, Any] | None:
    """The user behind a live (unexpired) API token, with the token's id, name, role and last use."""
    with _connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT u.id, u.username, u.is_admin, u.role, u.totp_enabled, u.oidc_subject, u.created_at,
                   u.last_login_at, u.team_id, u.max_containers, t.id AS token_id, t.name AS token_name, t.role AS token_role,
                   t.last_used_at AS token_last_used_at
            FROM api_tokens t JOIN users u ON u.id = t.user_id
            WHERE t.token_hash = ? AND (t.expires_at IS NULL OR t.expires_at > ?)
            """,
            (token_hash, utc_now()),
        ).fetchone()
        return _user_row(row)


def touch_api_token(db_path: Path, token_id: int, ip: str | None) -> None:
    with _connection(db_path) as conn:
        conn.execute("UPDATE api_tokens SET last_used_at = ?, last_used_ip = COALESCE(?, last_used_ip) WHERE id = ?",
                     (utc_now(), ip, token_id))
        conn.commit()


def delete_api_token(db_path: Path, token_id: int, user_id: int | None = None) -> dict[str, Any] | None:
    """Delete a token (only one of `user_id`'s when given). Returns what was deleted."""
    with _connection(db_path) as conn:
        row = conn.execute("SELECT t.id, t.user_id, t.name, u.username FROM api_tokens t"
                           " JOIN users u ON u.id = t.user_id WHERE t.id = ?", (token_id,)).fetchone()
        if not row or (user_id is not None and row["user_id"] != user_id):
            return None
        conn.execute("DELETE FROM api_tokens WHERE id = ?", (token_id,))
        conn.commit()
        return dict(row)


def delete_expired_api_tokens(db_path: Path) -> int:
    with _connection(db_path) as conn:
        cur = conn.execute("DELETE FROM api_tokens WHERE expires_at IS NOT NULL AND expires_at <= ?", (utc_now(),))
        conn.commit()
        return cur.rowcount
