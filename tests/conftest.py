"""
Shared test fixtures.

These work against the app/ package.
"""
import os
import tempfile

import pytest

# Keep the app's data (database, logs, reports) out of /var/lib during tests.
# Must be set before app.config is imported.
os.environ.setdefault("HABENY_DATA_DIR", tempfile.mkdtemp(prefix="habeny-test-"))


@pytest.fixture()
def tmp_db(tmp_path):
    """Yield a temporary SQLite database initialized with the platform schema."""
    from app.db import init_db
    db_path = tmp_path / "test.db"
    init_db(db_path)
    return db_path
