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


@pytest.fixture()
def attach(monkeypatch):
    """Record commands run inside containers instead of calling lxc-attach. Set
    attach.responses[substring] = stdout to answer commands containing `substring`."""
    import app.core.shell as shell
    import app.installers.cache as cache

    def fake(name, argv, env=None, input_bytes=None, timeout=300):
        fake.calls.append({"name": name, "argv": list(argv), "env": env, "input": input_bytes})
        command = " ".join(argv)
        stdout = next((out for key, out in fake.responses.items() if key in command), "")
        return {"returncode": 0, "stdout": stdout, "stderr": "", "timed_out": False}

    fake.calls = []
    fake.responses = {}
    monkeypatch.setattr(shell, "attach_run", fake)
    monkeypatch.setattr(cache, "attach_run", fake)
    return fake


@pytest.fixture()
def container():
    """A running container in the in-memory LXC stub (tests/stubs/lxc.py)."""
    import uuid

    import lxc
    if not hasattr(lxc, "_containers"):
        pytest.skip("needs the LXC stub (PYTHONPATH=tests/stubs)")
    name = "t" + uuid.uuid4().hex[:8]
    c = lxc.Container(name)
    c.create("download")
    c.start()
    yield name
    lxc._containers.pop(name, None)
