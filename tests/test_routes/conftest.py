import importlib.util

import pytest
from fastapi.testclient import TestClient

# The app imports python-lxc; skip these tests (not the whole run) where it's missing
if importlib.util.find_spec("lxc") is None:
    collect_ignore_glob = ["test_*.py"]

ADMIN = {"username": "admin", "password": "correct-horse-battery"}


@pytest.fixture(scope="session")
def app():
    from app import create_app
    return create_app()


@pytest.fixture(scope="session")
def admin_created(app):
    """Complete first-run setup once for the test session."""
    client = TestClient(app)
    if client.get("/auth/status").json()["data"]["setup_required"]:
        assert client.post("/auth/setup", json=ADMIN).status_code == 200
    return ADMIN


@pytest.fixture()
def client(app, admin_created):
    """A client signed in as the admin."""
    c = TestClient(app)
    assert c.post("/auth/login", json=admin_created).status_code == 200
    return c
