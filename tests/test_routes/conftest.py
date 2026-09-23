import importlib.util
import os

import pytest
from fastapi.testclient import TestClient

# The app needs LXC access: python-lxc (direct mode) or the helper (HABENY_LXC_BACKEND=helper).
# Skip these tests (not the whole run) where neither is available.
if os.environ.get("HABENY_LXC_BACKEND") != "helper" and importlib.util.find_spec("lxc") is None:
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
        from app.services.setup_token import TOKEN_FILE
        resp = client.post("/auth/setup", json={**ADMIN, "setup_token": TOKEN_FILE.read_text().strip()})
        assert resp.status_code == 200, resp.text
    return ADMIN


@pytest.fixture()
def client(app, admin_created):
    """A client signed in as the admin."""
    c = TestClient(app)
    assert c.post("/auth/login", json=admin_created).status_code == 200
    return c
