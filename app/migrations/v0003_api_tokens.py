"""API tokens for scripts and CI (Authorization: Bearer)."""


def up(conn):
    conn.execute(
        """
        CREATE TABLE api_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            prefix TEXT NOT NULL,
            role TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT,
            last_used_at TEXT,
            last_used_ip TEXT
        )
        """
    )
    conn.execute("CREATE INDEX idx_api_tokens_user ON api_tokens(user_id)")


def down(conn):
    conn.execute("DROP TABLE api_tokens")
