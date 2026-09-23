"""
Baseline: the schema as of Habeny 2.1, before versioned migrations.

Written to be safe on any database from before this point too (which may have been
created by any earlier version): tables are created only if missing and each column
added only if absent. Later migrations can assume exactly this schema.
"""
import contextlib
import sqlite3


def up(conn: sqlite3.Connection) -> None:
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
        # Single sign-on: "<issuer>|<subject>" of the linked identity-provider account
        "ALTER TABLE users ADD COLUMN oidc_subject TEXT",
    ]:
        with contextlib.suppress(sqlite3.OperationalError):  # column already exists
            conn.execute(migration)

    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_oidc_subject ON users(oidc_subject)")

    # Accounts created before roles existed: the oldest one becomes the admin
    conn.execute(
        """
        UPDATE users SET is_admin = 1
        WHERE id = (SELECT MIN(id) FROM users)
          AND NOT EXISTS (SELECT 1 FROM users WHERE is_admin = 1)
        """
    )
    conn.execute("UPDATE users SET role = 'admin' WHERE is_admin = 1 AND role != 'admin'")


    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version INTEGER NOT NULL,
            name TEXT NOT NULL,
            direction TEXT NOT NULL,
            app_version TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
        """
    )
