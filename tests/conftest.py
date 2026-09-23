"""
Shared test fixtures.

These work against the app/ package.
"""
import sqlite3
from pathlib import Path

import pytest


@pytest.fixture()
def tmp_db(tmp_path):
    """Yield a temporary SQLite database initialized with the platform schema."""
    from app.db import init_db
    db_path = tmp_path / "test.db"
    init_db(db_path)
    return db_path
