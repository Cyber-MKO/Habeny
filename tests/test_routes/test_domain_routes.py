"""
API coverage for groups, reports, simulations, log upload and SIEM stats,
against the LXC stub with in-container commands recorded (see the `attach` fixture).
"""
import csv
import io
import socket
import time

import pytest

# ── groups ──────────────────────────────────────────────────────────────

def test_group_lifecycle(client, container):
    assert client.post("/groups", json={"name": "blue-team", "description": "defenders"}).status_code == 200
    assert client.post("/groups", json={"name": "blue-team"}).status_code in (400, 409)
    assign = client.post("/groups/blue-team/assign", json={"agent_ids": [container]})
    assert assign.status_code == 200, assign.text
    groups = {g["name"]: g for g in client.get("/groups").json()["data"]["groups"]}
    assert "blue-team" in groups

    renamed = client.post("/groups/blue-team/rename", json={"new_name": "purple-team"})
    assert renamed.status_code == 200, renamed.text
    assert client.post("/groups/purple-team/remove", json={"agent_ids": [container]}).status_code == 200
    assert client.delete("/groups/purple-team").status_code == 200
    assert "purple-team" not in {g["name"] for g in client.get("/groups").json()["data"]["groups"]}


@pytest.mark.parametrize("body", [{"name": "-bad"}, {"name": ""}, {"name": "x" * 60}])
def test_group_name_validation(client, body):
    assert client.post("/groups", json=body).status_code == 422


def test_group_assign_needs_containers(client):
    client.post("/groups", json={"name": "empty-assign"})
    assert client.post("/groups/empty-assign/assign", json={"agent_ids": []}).status_code == 422
    client.delete("/groups/empty-assign")


def test_group_log_upload_runs_in_members(client, container, attach):
    client.post("/groups", json={"name": "loggers"})
    client.post("/groups/loggers/assign", json={"agent_ids": [container]})
    resp = client.post("/groups/loggers/logs/upload",
                       json={"content": "line one\n", "destination_path": "/var/log/app.log"})
    assert resp.status_code == 200, resp.text
    assert any(call["name"] == container for call in attach.calls)
    client.delete("/groups/loggers")


# ── reports ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("fmt", ["json", "csv", "pdf"])
def test_report_generation_and_download(client, fmt):
    body = {"start_time": "2026-01-01T00:00:00Z", "end_time": "2026-12-31T00:00:00Z", "format": fmt}
    resp = client.post("/reports/generate", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    report_id = data["report_id"]
    assert client.get(f"/reports/{report_id}").status_code == 200
    download = client.get(data["download_url"])
    assert download.status_code == 200
    if fmt == "pdf":
        assert download.content.startswith(b"%PDF")
    elif fmt == "csv":
        rows = list(csv.reader(io.StringIO(download.text)))
        assert len(rows) > 1
    else:
        assert download.json()
    listed = next(r for r in client.get("/reports").json()["data"]["reports"] if r["report_id"] == report_id)
    assert listed["formats"] == sorted({"json", fmt}) and listed["generated_at"] and listed["time_range"]


def test_report_rejects_backwards_time_range(client):
    body = {"start_time": "2026-12-31T00:00:00Z", "end_time": "2026-01-01T00:00:00Z"}
    assert client.post("/reports/generate", json=body).status_code == 422


def test_unknown_report_is_404(client):
    assert client.get("/reports/does-not-exist").status_code == 404


# ── simulations ─────────────────────────────────────────────────────────

def _wait(predicate, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.2)
    return False


def test_syslog_simulation_sends_messages(client):
    receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receiver.bind(("127.0.0.1", 0))
    receiver.settimeout(5)
    port = receiver.getsockname()[1]
    try:
        resp = client.post("/simulations/syslog/start", json={
            "target_ip": "127.0.0.1", "target_port": port, "protocol": "udp", "eps": 5, "duration": 1,
            "device_count": 1, "device_type": "firewall", "device_name_prefix": "fw"})
        assert resp.status_code == 200, resp.text
        sim_id = resp.json()["data"]["simulation_id"]
        message = receiver.recv(4096).decode()
        assert "fw-01" in message and message.startswith("<")  # an RFC 5424/3164 priority
        assert _wait(lambda: next(s for s in client.get("/simulations").json()["data"]["simulations"]
                                  if s["simulation_id"] == sim_id)["status"] == "completed")
    finally:
        receiver.close()


def test_attack_simulation_start_and_stop(app, client, container, attach):
    import threading

    from fastapi.testclient import TestClient

    from app.state import simulations_db

    # TestClient runs background tasks before it returns, so start from another thread
    starter = TestClient(app, cookies=client.cookies)
    started = {}
    thread = threading.Thread(target=lambda: started.update(resp=starter.post("/simulations/start", json={
        "profile_id": "auth_bruteforce", "duration": 60, "eps_target": 1,
        "agent_selector": {"agent_ids": [container]}})))
    thread.start()
    assert _wait(lambda: any(s.get("status") == "running" and container in s.get("target_agents", [])
                             for s in simulations_db.values()))
    sim_id = next(k for k, s in simulations_db.items() if container in s.get("target_agents", []))
    stopped = client.post(f"/simulations/{sim_id}/stop")
    assert stopped.status_code == 200 and stopped.json()["data"]["status"] == "stopped"
    thread.join(timeout=10)
    assert not thread.is_alive()  # the simulation loop noticed the stop
    assert started["resp"].status_code == 200
    assert client.post(f"/simulations/{sim_id}/stop").json()["success"] is False  # already stopped
    assert client.post("/simulations/nope/stop").status_code == 404


def test_simulation_rejects_empty_selection_and_bad_profile(client):
    assert client.post("/simulations/start", json={"profile_id": "auth_bruteforce",
                                                   "agent_selector": {}}).status_code == 422
    assert client.post("/simulations/start", json={"profile_id": "not-a-profile",
                                                   "agent_selector": {"count": 1}}).status_code == 422
    resp = client.post("/simulations/start", json={"profile_id": "auth_bruteforce",
                                                   "agent_selector": {"agent_ids": ["no-such-container"]}})
    assert resp.status_code == 400


def test_custom_log_simulation_writes_into_containers(client, container, attach):
    resp = client.post("/simulations/load", json={"agent_selector": {"agent_ids": [container]}, "eps": 2,
                                                  "duration": 1, "file_path": "/var/log/eps.json"})
    assert resp.status_code == 200, resp.text
    assert _wait(lambda: any(call["name"] == container for call in attach.calls))
    assert client.post("/simulations/load", json={"agent_selector": {"agent_ids": [container]},
                                                  "file_path": "relative.log"}).status_code == 422


# ── log upload and schedules ────────────────────────────────────────────

def test_log_upload(client, container, attach):
    resp = client.post(f"/agents/{container}/logs/upload",
                       json={"content": "hello\n", "destination_path": "/var/log/hello.log", "append": True})
    assert resp.status_code == 200, resp.text
    assert any(call["name"] == container for call in attach.calls)
    assert client.post("/agents/missing/logs/upload",
                       json={"content": "x", "destination_path": "/var/log/x.log"}).status_code == 404
    assert client.post(f"/agents/{container}/logs/upload",
                       json={"content": "x", "destination_path": "/etc/../../root/x"}).status_code == 422


def test_log_schedule_create_list_stop(client, container, attach):
    resp = client.post(f"/agents/{container}/logs/schedule",
                       json={"content": "tick\n", "destination_path": "/var/log/tick.log",
                             "interval_seconds": 5, "duration_seconds": 60})
    assert resp.status_code == 200, resp.text
    schedule_id = resp.json()["data"]["schedule_id"]
    assert "request" not in resp.json()["data"]  # the stored upload isn't exposed
    listed = client.get("/agents/logs/schedules").json()["data"]["schedules"]
    assert schedule_id in [s["schedule_id"] for s in listed]
    stopped = client.post(f"/agents/logs/schedules/{schedule_id}/stop")
    assert stopped.status_code == 200 and stopped.json()["data"]["status"] == "stopped"
    assert client.post(f"/agents/{container}/logs/schedule",
                       json={"content": "x", "destination_path": "/var/log/x.log",
                             "interval_seconds": 5}).status_code == 400  # needs a duration or indefinite


# ── SIEM stats ──────────────────────────────────────────────────────────

def test_siem_stats(client):
    resp = client.get("/siem/wazuh/stats")
    assert resp.status_code == 200, resp.text
    assert client.get("/siem/not-a-siem/stats").status_code in (400, 422)


def test_simulation_targets_only_the_selected_containers(client, attach):
    """Every selector criterion used to be ignored: all running containers were targeted."""
    import lxc

    from app.models import AgentSelector
    from app.services.agent_info import write_agent_metadata
    from app.services.simulation import select_agents_for_simulation

    names = []
    for i, (siem, group) in enumerate([("wazuh", "red"), ("ossec", "red"), ("wazuh", "blue")]):
        name = f"sel-{i}-{siem}-{group}"
        c = lxc.Container(name)
        c.create("download")
        c.start()
        write_agent_metadata(name, {"siem_type": siem, "agent_group": group})
        names.append(name)
    stopped = lxc.Container("sel-stopped")
    stopped.create("download")
    try:
        pick = lambda **kw: sorted(set(select_agents_for_simulation(AgentSelector(**kw))) & set(names + ["sel-stopped"]))  # noqa: E731
        assert pick(agent_ids=[names[0]]) == [names[0]]
        assert pick(agent_ids=["sel-stopped"]) == []  # not running
        assert pick(siem_type="wazuh") == sorted([names[0], names[2]])
        assert pick(agent_group="red") == sorted(names[:2])
        assert pick(siem_type="wazuh", agent_group="red") == [names[0]]
        assert len(select_agents_for_simulation(AgentSelector(agent_ids=names, count=2))) == 2
        resp = client.post("/simulations/start", json={"profile_id": "auth_bruteforce",
                                                       "agent_selector": {"agent_ids": ["no-such-container"]}})
        assert resp.status_code == 400
    finally:
        for name in names + ["sel-stopped"]:
            lxc._containers.pop(name, None)
