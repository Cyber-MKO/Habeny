"""
Shared test fixtures.

These work against the *current* root-level modules (db.py, models.py, utils.py)
and will continue to work as code migrates into app/ because the root files
become re-export shims.
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
