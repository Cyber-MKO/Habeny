"""Notification channels (email, Slack, webhooks)."""


def up(conn):
    conn.execute(
        """
        CREATE TABLE notification_channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            type TEXT NOT NULL,
            config TEXT NOT NULL,
            events TEXT NOT NULL,
            only_problems INTEGER NOT NULL DEFAULT 0,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_sent_at TEXT,
            last_status TEXT,
            last_error TEXT
        )
        """
    )


def down(conn):
    conn.execute("DROP TABLE notification_channels")
