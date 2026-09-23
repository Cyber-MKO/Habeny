"""
Smoke tests for the wired application returned by create_app().
"""
import pytest

pytest.importorskip("lxc", reason="the app requires python-lxc")

from fastapi.testclient import TestClient  # noqa: E402
from starlette.routing import Match  # noqa: E402

from app import create_app  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return create_app()


def test_root_returns_200(app):
    resp = TestClient(app).get("/")
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_health_returns_200(app):
    resp = TestClient(app).get("/system/health")
    assert resp.status_code == 200


def test_api_prefix_is_accepted(app):
    resp = TestClient(app).get("/api/system/health")
    assert resp.status_code == 200


@pytest.mark.parametrize("method,path,endpoint", [
    ("POST", "/agents/bulk/start", "bulk_agent_operation"),
    ("GET", "/agents/stats", "get_agents_stats"),
    ("GET", "/benchmarks/scenarios", "list_benchmark_scenarios"),
    ("GET", "/agents/logs/schedules", "list_log_schedules"),
])
def test_overlapping_routes_resolve_to_specific_handler(app, method, path, endpoint):
    """Routers are included in an order where literal paths win over {param} ones."""
    scope = {"type": "http", "method": method, "path": path, "root_path": "", "query_string": b"", "headers": []}
    matched = next(r for r in app.router.routes if r.matches(scope)[0] == Match.FULL)
    assert matched.name == endpoint
