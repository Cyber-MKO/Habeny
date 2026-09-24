"""
Several LXC hosts under one console: registering other Habeny servers (with certificate
pinning), relaying API calls and WebSockets to them, per-team hosts, health checks.

The "other host" is this same app served over real TLS by uvicorn in a thread.
"""
import json
import socket
import threading
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from app.services import alerts
from app.services import hosts as svc


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def remote(app, tmp_path_factory):
    import uvicorn

    from app.tls import _generate_self_signed
    directory = tmp_path_factory.mktemp("remote-tls")
    cert, key = directory / "cert.pem", directory / "key.pem"
    _generate_self_signed(cert, key)
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, ssl_certfile=str(cert),
                                           ssl_keyfile=str(key), log_level="warning", lifespan="off"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    assert server.started
    yield {"url": f"https://127.0.0.1:{port}", "cert": cert}
    server.should_exit = True
    thread.join(timeout=10)


@pytest.fixture()
def token(client):
    info = client.post("/users/me/tokens", json={"name": "console-" + uuid.uuid4().hex[:6], "role": "operator"}).json()
    yield info["data"]["token"]
    client.delete(f"/users/me/tokens/{info['data']['info']['id']}")


@pytest.fixture()
def host(client, remote, token):
    fp = client.post("/hosts", json={"name": "probe", "url": remote["url"], "token": token}).json()["data"]["fingerprint"]
    resp = client.post("/hosts", json={"name": "lab-" + uuid.uuid4().hex[:6], "url": remote["url"] + "/",
                                       "token": token, "fingerprint": fp})
    assert resp.status_code == 200, resp.text
    host = resp.json()["data"]["host"]
    yield host
    client.delete(f"/hosts/{host['id']}")
    alerts.manager.reset()


def test_adding_a_self_signed_host_needs_its_fingerprint_confirmed(client, remote, token):
    from app.tls import _fingerprint_of_file
    first = client.post("/hosts", json={"name": "lab", "url": remote["url"], "token": token}).json()
    assert first["success"] is False and first["error"] == "fingerprint_needed"
    assert first["data"]["fingerprint"] == _fingerprint_of_file(remote["cert"])
    wrong = client.post("/hosts", json={"name": "lab", "url": remote["url"], "token": token,
                                        "fingerprint": "AA:" * 31 + "AA"})
    assert wrong.status_code == 400 and "different certificate" in wrong.json()["detail"]
    bad_token = client.post("/hosts", json={"name": "lab", "url": remote["url"], "token": "hby_nope",
                                            "fingerprint": first["data"]["fingerprint"]})
    assert bad_token.status_code == 400 and "token" in bad_token.json()["detail"]
    assert client.post("/hosts", json={"name": "lab", "url": "ftp://x", "token": token}).status_code == 400
    assert client.get("/hosts").json()["data"]["hosts"] == []


def test_host_is_listed_without_its_token(client, host):
    listed = client.get("/hosts").json()["data"]["hosts"]
    assert [h["name"] for h in listed] == [host["name"]]
    assert "token" not in listed[0] and listed[0]["token_hint"].startswith("hby_")
    assert listed[0]["url"] == host["url"] and not host["url"].endswith("/")


def test_relaying_api_calls(client, host):
    local = client.get("/agents/stats").json()["data"]["total_agents"]
    relayed = client.get(f"/hosts/{host['id']}/api/agents/stats")
    assert relayed.status_code == 200 and relayed.json()["data"]["total_agents"] == local
    assert "X-Remote-Request-ID" in relayed.headers
    group = "relay" + uuid.uuid4().hex[:6]
    assert client.post(f"/hosts/{host['id']}/api/groups", json={"name": group}).status_code == 200
    assert group in [g["name"] for g in client.get("/groups").json()["data"]["groups"]]  # same server here
    assert client.delete(f"/hosts/{host['id']}/api/groups/{group}").status_code == 200
    assert client.get(f"/hosts/{host['id']}/api/agents/nope").status_code == 404  # the host's answer
    for local_only in ("users", "auth/status", "hosts", "teams", "notifications/channels", "system/backups"):
        assert client.get(f"/hosts/{host['id']}/api/{local_only}").status_code == 403, local_only
    assert client.get("/hosts/999/api/agents").status_code == 404


def test_viewers_can_only_read_through_the_relay(app, client, host):
    name, pw = "v" + uuid.uuid4().hex[:6], "viewer-password-1"
    user = client.post("/users", json={"username": name, "password": pw}).json()["data"]["user"]
    viewer = TestClient(app)
    viewer.post("/auth/login", json={"username": name, "password": pw})
    assert viewer.get(f"/hosts/{host['id']}/api/agents/stats").status_code == 200
    assert viewer.post(f"/hosts/{host['id']}/api/groups", json={"name": "x"}).status_code == 403
    assert viewer.post("/hosts", json={"name": "x", "url": "https://x", "token": "t"}).status_code == 403
    client.delete(f"/users/{user['id']}")


def test_team_hosts(app, client, host):
    team = client.post("/teams", json={"name": "hosts-" + uuid.uuid4().hex[:6]}).json()["data"]["team"]
    client.put(f"/hosts/{host['id']}", json={"name": host["name"], "team_id": team["id"]})
    name, pw = "o" + uuid.uuid4().hex[:6], "operator-password-1"
    user = client.post("/users", json={"username": name, "password": pw, "role": "operator"}).json()["data"]["user"]
    other = TestClient(app)
    other.post("/auth/login", json={"username": name, "password": pw})
    assert other.get("/hosts").json()["data"]["hosts"] == []
    assert other.get(f"/hosts/{host['id']}/api/agents").status_code == 404
    client.put(f"/users/{user['id']}/team", json={"team_id": team["id"]})
    assert [h["id"] for h in other.get("/hosts").json()["data"]["hosts"]] == [host["id"]]
    client.delete(f"/users/{user['id']}")
    client.delete(f"/teams/{team['id']}")


def test_overview_and_health_checks(client, host, token, monkeypatch):
    overview = client.get("/hosts/overview").json()["data"]["hosts"][0]
    assert overview["status"] == "ok" and overview["version"] and overview["containers"] is not None
    svc.check_all()
    assert not [a for a in alerts.manager.active() if a["name"] == "host_unreachable"]
    # the host's token gets revoked over there
    client.delete(f"/users/me/tokens/{next(t['id'] for t in client.get('/users/me/tokens').json()['data']['tokens'] if token.startswith(t['prefix']))}")
    relayed = client.get(f"/hosts/{host['id']}/api/agents")
    assert relayed.status_code == 502 and "rejected this console's API token" in relayed.json()["detail"]
    svc.check_all()
    active = [a for a in alerts.manager.active() if a["name"] == "host_unreachable"]
    assert active and active[0]["target"] == host["name"]
    assert client.get("/hosts").json()["data"]["hosts"][0]["last_status"] == "error"


def test_websocket_relay(client, host):
    with client.websocket_connect(f"/hosts/{host['id']}/ws/metrics") as ws:
        first = json.loads(ws.receive_text())
    assert "total_agents" in first and "system" in first  # the host's live metrics payload


def test_cli_prints_this_servers_fingerprint(capsys, monkeypatch, remote):
    from app import cli, tls
    monkeypatch.setattr(tls, "SELF_SIGNED_CERT", remote["cert"])
    assert cli.main(["tls", "fingerprint"]) == 0
    assert capsys.readouterr().out.strip() == tls._fingerprint_of_file(remote["cert"])
