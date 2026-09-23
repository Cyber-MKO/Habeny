"""
Deploy workers run in processes forked from the multi-threaded web app, where SQLite
is unsafe ("database is locked"); they must not touch the database. The parent saves
what they return.
"""
import sqlite3

import pytest

import app.services.deployment as dep


def test_worker_never_opens_the_database(monkeypatch):
    def no_db(*args, **kwargs):
        raise AssertionError("deploy worker opened the database")

    monkeypatch.setattr(sqlite3, "connect", no_db)
    monkeypatch.setattr(dep, "setup_agent_health_check", lambda name: {"success": True})
    monkeypatch.setattr(dep.time, "sleep", lambda s: None)
    result = dep.deploy_single_siem_agent("wk-0001", {"siem_type": "none", "os_type": "ubuntu_22_04",
                                                      "memory_limit": "256MB", "cpu_shares": 512}, 7)
    assert result["success"] is True, result
    assert result["metadata"]["agent_seq_id"] == 7
    assert result["metadata"]["lifecycle_status"] in ("running", "stopped")


def test_parent_persists_metadata_and_metrics():
    from app.config import DB_PATH
    from app.db import get_or_create_agent_seq_id
    from app.services.agent_info import read_agent_metadata

    seq = get_or_create_agent_seq_id(DB_PATH, "wk-0002")
    result = {"agent_name": "wk-0002", "success": True, "deploy_time_seconds": 3.5,
              "metadata": {"agent_seq_id": seq, "siem_type": "wazuh", "lifecycle_status": "running"}}
    dep.persist_deploy_result(result, "wazuh")
    assert "metadata" not in result  # not sent to the API client
    assert read_agent_metadata("wk-0002")["siem_type"] == "wazuh"
    rows = sqlite3.connect(DB_PATH).execute(
        "SELECT metric_name FROM metrics WHERE metric_type='deployment' AND tags='wazuh'").fetchall()
    assert {r[0] for r in rows} >= {"container_deploy_time", "container_success"}


def test_save_failure_does_not_fail_a_deployed_container(monkeypatch, caplog):
    def locked(*a, **k):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(dep, "write_agent_metadata", locked)
    result = {"agent_name": "wk-0003", "success": True, "metadata": {"siem_type": "none"}}
    dep.persist_deploy_result(result)
    assert result["success"] is True
    assert "could not save its metadata" in caplog.text


@pytest.fixture(autouse=True)
def _app(app):  # initializes the test database
    yield
