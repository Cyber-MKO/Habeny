"""
Smoke tests for the wired application returned by create_app().
"""
import pytest
from fastapi.testclient import TestClient
from starlette.routing import Match


def test_root_returns_200(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_health_returns_200(client):
    resp = client.get("/system/health")
    assert resp.status_code == 200


def test_api_prefix_is_accepted(client):
    resp = client.get("/api/system/health")
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


@pytest.mark.parametrize("path", ["/..%2fmain.py", "/..%2f..%2f..%2f..%2f..%2fetc%2fpasswd", "/%2e%2e/%2e%2e/etc/passwd"])
def test_spa_does_not_serve_files_outside_static_dir(app, path):
    resp = TestClient(app).get(path)
    assert "Entry point" not in resp.text and "root:" not in resp.text


def test_health_reports_real_uptime(client):
    uptime = client.get("/system/health").json()["uptime_seconds"]
    assert 0 <= uptime < 24 * 3600  # was time.time(), i.e. ~56 years


def test_container_state_summary_single_pass_and_cached(monkeypatch):
    import app.services.agent_info as ai

    states = {"a": "RUNNING", "b": "STOPPED", "c": "FROZEN", "d": "STARTING"}
    calls = {"list": 0, "state": 0}

    class FakeContainer:
        def __init__(self, name):
            self.name = name

        @property
        def state(self):
            calls["state"] += 1
            return states[self.name]

    def fake_list():
        calls["list"] += 1
        return list(states)

    monkeypatch.setattr(ai.lxc, "list_containers", fake_list)
    monkeypatch.setattr(ai.lxc, "Container", FakeContainer)
    monkeypatch.setitem(ai._scan_cache, "value", None)

    summary = ai.container_state_summary()
    assert summary["total"] == 4
    assert summary["by_state"] == {"RUNNING": 1, "STOPPED": 1, "FROZEN": 1, "OTHER": 1}
    assert summary["running"] == 3  # like lxc's Container.running: anything not STOPPED
    assert calls == {"list": 1, "state": 4}

    ai.container_state_summary()  # within the TTL: served from the shared scan
    assert calls == {"list": 1, "state": 4}
    monkeypatch.setitem(ai._scan_cache, "value", None)
