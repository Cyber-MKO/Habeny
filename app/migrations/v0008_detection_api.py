"""Detection API settings on manager profiles (checking what the SIEM detected)."""

COLUMNS = [
    ("detection_url", "TEXT"),          # e.g. https://indexer:9200 (Wazuh indexer, Elasticsearch)
    ("detection_username", "TEXT"),
    ("detection_secret", "TEXT"),       # password or API key, encrypted like siem_auth_key
    ("detection_fingerprint", "TEXT"),  # pinned certificate for a self-signed endpoint
]


def up(conn):
    for name, kind in COLUMNS:
        conn.execute(f"ALTER TABLE managers ADD COLUMN {name} {kind}")


def down(conn):
    for name, _ in reversed(COLUMNS):
        conn.execute(f"ALTER TABLE managers DROP COLUMN {name}")
