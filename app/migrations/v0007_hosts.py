"""Other Habeny servers (LXC hosts) managed from this console."""


def up(conn):
    conn.execute(
        """
        CREATE TABLE hosts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE COLLATE NOCASE,
            url TEXT NOT NULL,
            token TEXT NOT NULL,
            fingerprint TEXT,
            team_id INTEGER REFERENCES teams(id) ON DELETE SET NULL,
            created_at TEXT NOT NULL,
            last_checked_at TEXT,
            last_status TEXT,
            last_error TEXT,
            version TEXT
        )
        """
    )


def down(conn):
    conn.execute("DROP TABLE hosts")
