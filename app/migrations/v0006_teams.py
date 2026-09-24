"""Teams: who sees which containers, and container limits per team and per user."""


def up(conn):
    conn.execute(
        """
        CREATE TABLE teams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE COLLATE NOCASE,
            description TEXT,
            max_containers INTEGER,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute("ALTER TABLE users ADD COLUMN team_id INTEGER REFERENCES teams(id) ON DELETE SET NULL")
    conn.execute("ALTER TABLE users ADD COLUMN max_containers INTEGER")
    # Which team (and user) a container belongs to. Containers without a row (created before
    # teams, or outside Habeny) belong to no team.
    conn.execute(
        """
        CREATE TABLE container_owners (
            name TEXT PRIMARY KEY,
            team_id INTEGER REFERENCES teams(id) ON DELETE SET NULL,
            owner_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX idx_container_owners_team ON container_owners(team_id)")
    conn.execute("CREATE INDEX idx_container_owners_owner ON container_owners(owner_id)")


# No down(): SQLite can't drop a column that has a foreign key. To go back, restore the
# backup taken before this migration (`habeny db restore`).
