"""
OSSIM support was removed (the product was retired in 2024): nothing new can be deployed
with it, and a manager profile saved before still gets a clear error.
"""
import uuid

import pytest

from app.config import DB_PATH
from app.db import create_manager, delete_manager


@pytest.fixture(autouse=True)
def lxc_access(app):
    from app.core.common import check_root
    app.dependency_overrides[check_root] = lambda: True
    yield
    app.dependency_overrides.pop(check_root, None)


def test_new_ossim_deployments_and_profiles_are_refused(client):
    resp = client.post("/agents/deploy", json={"count": 1, "siem_type": "ossim", "siem_ip": "10.0.0.1"})
    assert resp.status_code == 422
    resp = client.post("/managers", json={"name": "old", "siem_type": "ossim", "siem_ip": "10.0.0.1"})
    assert resp.status_code == 422
    assert "ossim" not in client.get("/").json()["data"]["supported_siem_types"]


def test_saved_ossim_profile_gets_a_clear_error(client):
    manager_id = uuid.uuid4().hex
    create_manager(DB_PATH, manager_id, {"name": f"legacy-{manager_id[:6]}", "siem_type": "ossim",
                                         "siem_ip": "10.0.0.1"})
    try:
        resp = client.post("/agents/deploy", json={"count": 1, "manager_profile_id": manager_id,
                                                   "agent_base_name": "legacy"})
        assert resp.status_code == 400 and "no longer supported" in resp.json()["detail"]
    finally:
        delete_manager(DB_PATH, manager_id)
