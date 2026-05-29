"""
Tests for Pydantic model validation (models.py).

Focus on validators — the shared helpers and edge cases.
"""
import pytest

models = pytest.importorskip("models", reason="models.py requires pydantic")


def test_agent_deployment_request_validates_ip():
    req = models.AgentDeploymentRequest(count=1, siem_ip="192.168.1.1")
    assert req.siem_ip == "192.168.1.1"


def test_agent_deployment_request_validates_hostname():
    req = models.AgentDeploymentRequest(count=1, siem_ip="manager.example.com")
    assert req.siem_ip == "manager.example.com"


def test_agent_deployment_request_rejects_invalid_ip():
    with pytest.raises(Exception):
        models.AgentDeploymentRequest(count=1, siem_ip="not a host!")


def test_log_upload_rejects_relative_path():
    with pytest.raises(Exception):
        models.LogUploadRequest(content="x", destination_path="relative/path")


def test_log_upload_rejects_path_traversal():
    with pytest.raises(Exception):
        models.LogUploadRequest(content="x", destination_path="/var/log/../../etc/passwd")


def test_group_create_rejects_invalid_name():
    with pytest.raises(Exception):
        models.GroupCreateRequest(name="-bad-start")


def test_bulk_operation_rejects_invalid_operation():
    with pytest.raises(Exception):
        models.BulkOperationRequest(container_names=["c1"], operation="explode")
