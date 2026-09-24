"""
Teams: container visibility per team, container limits, admin management.
"""
import uuid

import pytest
from fastapi.testclient import TestClient

lxc = pytest.importorskip("lxc")
if not hasattr(lxc, "_containers"):
    pytest.skip("needs the LXC stub (PYTHONPATH=tests/stubs)", allow_module_level=True)

from app.services import tenancy  # noqa: E402


def _uid():
    return uuid.uuid4().hex[:6]


def _make_container(name):
    c = lxc.Container(name)
    c.create("download")
    c.start()
    return name


@pytest.fixture(autouse=True)
def lxc_access(app):
    """CI runs unprivileged; these tests are about teams, not the root check."""
    from app.core.common import check_root
    app.dependency_overrides[check_root] = lambda: True
    yield
    app.dependency_overrides.pop(check_root, None)


@pytest.fixture()
def world(app, client):
    """Teams red and blue; operators alice (red), bob (blue), carol (no team); one container each,
    plus one created outside Habeny (no team)."""
    tag = _uid()
    red = client.post("/teams", json={"name": f"red-{tag}", "max_containers": 3}).json()["data"]["team"]
    blue = client.post("/teams", json={"name": f"blue-{tag}"}).json()["data"]["team"]
    people = {}
    for who, team in (("alice", red), ("bob", blue), ("carol", None)):
        name, pw = f"{who}{tag}", f"{who}-password-123"
        user = client.post("/users", json={"username": name, "password": pw, "role": "operator"}).json()["data"]["user"]
        assert client.put(f"/users/{user['id']}/team", json={"team_id": team["id"] if team else None}).status_code == 200
        c = TestClient(app)
        assert c.post("/auth/login", json={"username": name, "password": pw}).status_code == 200
        people[who] = {"id": user["id"], "client": c, "name": name}
    containers = {who: _make_container(f"{who}-{tag}") for who in ("alice", "bob", "carol")}
    containers["outside"] = _make_container(f"outside-{tag}")
    tenancy.record([containers["alice"]], {"id": people["alice"]["id"], "team_id": red["id"]})
    tenancy.record([containers["bob"]], {"id": people["bob"]["id"], "team_id": blue["id"]})
    tenancy.record([containers["carol"]], {"id": people["carol"]["id"], "team_id": None})
    yield {"red": red, "blue": blue, "people": people, "containers": containers, "tag": tag}
    for name in containers.values():
        lxc._containers.pop(name, None)
    tenancy.forget(list(containers.values()))
    for p in people.values():
        client.delete(f"/users/{p['id']}")
    for team in (red, blue):
        client.delete(f"/teams/{team['id']}")


def _names(c, **params):
    return {a["agent_name"] for a in c.get("/agents", params={"limit": 1000, **params}).json()["data"]["agents"]}


def test_each_team_sees_only_its_containers(client, world):
    c = world["containers"]
    alice, bob, carol = (world["people"][w]["client"] for w in ("alice", "bob", "carol"))
    ours = set(c.values())
    assert _names(alice) & ours == {c["alice"]}
    assert _names(bob) & ours == {c["bob"]}
    assert _names(carol) & ours == {c["carol"], c["outside"]}  # no team: unowned containers
    assert _names(client) & ours == ours  # admins see everything
    admin_view = {a["agent_name"]: a for a in client.get("/agents", params={"limit": 1000}).json()["data"]["agents"]}
    assert admin_view[c["alice"]]["team_id"] == world["red"]["id"] and admin_view[c["outside"]]["team_id"] is None
    assert alice.get("/agents/stats").json()["data"]["total_agents"] == 1


def test_other_teams_containers_read_as_not_found(world):
    alice = world["people"]["alice"]["client"]
    theirs = world["containers"]["bob"]
    assert alice.get(f"/agents/{theirs}").status_code == 404
    assert alice.post(f"/agents/{theirs}/stop").status_code == 404
    assert alice.delete(f"/agents/{theirs}").status_code == 404
    assert theirs in lxc._containers  # untouched
    bulk = alice.post("/agents/bulk/delete", json={"container_names": [theirs], "operation": "delete"}).json()
    assert bulk["data"]["results"] == [{"agent_id": theirs, "success": False, "error": "Not found"}]
    assert theirs in lxc._containers
    assert alice.post(f"/agents/{theirs}/logs/upload", json={"content": "x", "destination_path": "/var/log/x.log"}).status_code == 404
    with alice.websocket_connect(f"/ws/console/{theirs}") as ws:
        assert "not found" in ws.receive_text()
    assert alice.get(f"/agents/{world['containers']['alice']}").status_code == 200


def test_quota_per_team_and_per_user(client, world, monkeypatch):
    alice = world["people"]["alice"]
    # red allows 3 containers and has 1
    body = {"count": 3, "siem_type": "none", "agent_base_name": f"q{world['tag']}"}
    resp = alice["client"].post("/agents/deploy", json=body)
    assert resp.status_code == 403 and "limited to 3 containers" in resp.json()["detail"]
    # a personal limit is checked too
    client.put(f"/users/{alice['id']}/team", json={"team_id": world["red"]["id"], "max_containers": 1})
    resp = alice["client"].post("/agents/deploy", json={**body, "count": 1})
    assert resp.status_code == 403 and "Your limit is 1" in resp.json()["detail"]
    client.put(f"/users/{alice['id']}/team", json={"team_id": world["red"]["id"]})
    # stale ownership rows (deleted containers) don't count
    tenancy.record(["gone-1", "gone-2"], {"id": alice["id"], "team_id": world["red"]["id"]})
    tenancy.check_quota({"id": alice["id"]}, 2, list(lxc.list_containers()))
    tenancy.forget(["gone-1", "gone-2"])


def test_deploy_records_the_owner(client, world, monkeypatch):
    bob = world["people"]["bob"]

    def fake_workers(deployment_id, names, config, seq_ids, mode="multiprocessing"):
        for n in names:
            _make_container(n)
        return [{"agent_name": n, "success": True} for n in names], []
    monkeypatch.setattr("app.routes.agents.run_deployment_workers", fake_workers)
    base = f"own{world['tag']}"
    resp = bob["client"].post("/agents/deploy", json={"count": 2, "siem_type": "none", "agent_base_name": base})
    assert resp.status_code == 200, resp.text
    made = {f"{base}-0001", f"{base}-0002"}
    assert _names(bob["client"]) >= made
    assert not (_names(world["people"]["alice"]["client"]) & made)
    assert {tenancy.owners(list(made))[n]["team_id"] for n in made} == {world["blue"]["id"]}
    # deleting forgets the owner
    bob["client"].delete(f"/agents/{base}-0001")
    assert f"{base}-0001" not in tenancy.owners()
    lxc._containers.pop(f"{base}-0002", None)
    tenancy.forget([f"{base}-0002"])


def test_simulations_and_reports_are_per_team(client, world):
    alice, bob = world["people"]["alice"]["client"], world["people"]["bob"]["client"]
    sim = alice.post("/simulations/syslog/start", json={
        "target_ip": "127.0.0.1", "target_port": 5514, "protocol": "udp", "eps": 1, "duration": 1,
        "device_count": 1}).json()["data"]
    assert sim["team_id"] == world["red"]["id"] and sim["started_by"] == world["people"]["alice"]["name"]
    assert sim["simulation_id"] in {s["simulation_id"] for s in alice.get("/simulations").json()["data"]["simulations"]}
    assert sim["simulation_id"] not in {s["simulation_id"] for s in bob.get("/simulations").json()["data"]["simulations"]}
    assert bob.post(f"/simulations/{sim['simulation_id']}/stop").status_code == 404

    report = alice.post("/reports/generate", json={"format": "json", "start_time": "2020-01-01T00:00:00Z",
                                                  "end_time": "2099-01-01T00:00:00Z"}).json()["data"]
    report_id = report["report_id"]
    assert report["report"]["summary"]["total_agents"] == 1
    assert alice.get(f"/reports/{report_id}").status_code == 200
    assert bob.get(f"/reports/{report_id}").status_code == 404
    assert bob.get(f"/reports/{report_id}/download").status_code == 404
    listed = lambda c: {r["report_id"] for r in c.get("/reports").json()["data"]["reports"]}  # noqa: E731
    assert report_id in listed(alice) and report_id not in listed(bob) and report_id in listed(client)


def test_admin_moves_containers_and_deletes_teams(client, world):
    c = world["containers"]
    resp = client.post("/teams/assign", json={"team_id": world["blue"]["id"], "containers": [c["outside"], "nope"]})
    assert resp.json()["data"] == {"assigned": [c["outside"]], "not_found": ["nope"]}
    assert c["outside"] in _names(world["people"]["bob"]["client"])
    teams = {t["id"]: t for t in client.get("/teams").json()["data"]["teams"]}
    assert teams[world["blue"]["id"]]["containers"] == 2 and teams[world["blue"]["id"]]["members"] == 1

    assert client.delete(f"/teams/{world['blue']['id']}").status_code == 200
    # blue's containers and members now have no team: carol (no team) sees them, bob too
    assert c["bob"] in _names(world["people"]["carol"]["client"])
    status = world["people"]["bob"]["client"].get("/auth/status").json()["data"]["user"]
    assert status["team"] is None


def test_teams_are_admin_only(world):
    alice = world["people"]["alice"]["client"]
    assert alice.get("/teams").status_code == 403
    assert alice.post("/teams", json={"name": "mine"}).status_code == 403
    assert alice.put(f"/users/{world['people']['alice']['id']}/team", json={"team_id": None}).status_code == 403


def test_status_shows_the_team(world):
    status = world["people"]["alice"]["client"].get("/auth/status").json()["data"]["user"]
    assert status["team"] == {"id": world["red"]["id"], "name": world["red"]["name"]}
