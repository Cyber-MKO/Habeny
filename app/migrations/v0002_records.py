"""Persisted state for jobs and schedules (simulations, reports, deployments, log schedules, config templates)."""


def up(conn):
    conn.execute(
        """
        CREATE TABLE records (
            kind TEXT NOT NULL,
            id TEXT NOT NULL,
            status TEXT,
            data TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (kind, id)
        )
        """
    )
    conn.execute("CREATE INDEX idx_records_kind_updated ON records(kind, updated_at)")


def down(conn):
    conn.execute("DROP TABLE records")
