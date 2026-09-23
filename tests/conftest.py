"""
Shared test fixtures.

These work against the root-level db.py/models.py and the app/ package.
"""
import sqlite3
import pytest
from pathlib import Path


@pytest.fixture()
def tmp_db(tmp_path):
    """Yield a temporary SQLite database initialized with the platform schema."""
    from db import init_db
    db_path = tmp_path / "test.db"
    init_db(db_path)
    return db_path
