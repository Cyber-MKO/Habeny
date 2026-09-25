"""
SIEM targets: syslog destinations on manager profiles (and the migration that moved saved
syslog configs onto them), UTMstack syslog listeners, and the Dashboard's per-SIEM summary.
"""
import socket
import sqlite3

import pytest

from app import migrations
from app.routes.siem import summarize


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_profiles_carry_a_syslog_port(client):
    no_address = client.post("/managers", json={"name": "syslog-only", "siem_type": "none", "syslog_port": 514})
    assert no_address.status_code == 400 and "address" in no_address.json()["detail"]

    created = client.post("/managers", json={"name": "qradar", "siem_type": "none", "siem_ip": "10.1.2.3",
                                             "syslog_port": 514})
    assert created.status_code == 200, created.text
    mgr = created.json()["data"]
    assert (mgr["syslog_port"], mgr["syslog_protocol"]) == (514, "tcp")  # TCP unless told otherwise

    updated = client.put(f"/managers/{mgr['manager_id']}", json={"syslog_port": 1514, "syslog_protocol": "udp"})
    assert (updated.json()["data"]["syslog_port"], updated.json()["data"]["syslog_protocol"]) == (1514, "udp")
    renamed = client.put(f"/managers/{mgr['manager_id']}", json={"description": "lab"})
    assert renamed.json()["data"]["syslog_port"] == 1514  # untouched unless sent
    cleared = client.put(f"/managers/{mgr['manager_id']}", json={"syslog_port": None})
    assert (cleared.json()["data"]["syslog_port"], cleared.json()["data"]["syslog_protocol"]) == (None, None)
    assert client.put(f"/managers/{mgr['manager_id']}", json={"siem_ip": "", "syslog_port": 514}).status_code == 400


@pytest.mark.parametrize("extra", [{"syslog_port": 70000}, {"syslog_port": 514, "syslog_protocol": "carrier-pigeon"}])
def test_syslog_fields_are_validated(client, extra):
    body = {"name": "bad-syslog", "siem_type": "wazuh", "siem_ip": "10.0.0.1", **extra}
    assert client.post("/managers", json=body).status_code == 422


def test_syslog_port_test(client):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    try:
        mgr = client.post("/managers", json={"name": "local-syslog", "siem_type": "none", "siem_ip": "127.0.0.1",
                                             "syslog_port": port}).json()["data"]
        ok = client.post(f"/managers/{mgr['manager_id']}/syslog/test")
        assert ok.status_code == 200 and ok.json()["success"] is True and ok.json()["data"]["status"] == "connected"
    finally:
        listener.close()

    closed = client.post("/managers", json={"name": "closed-syslog", "siem_type": "none", "siem_ip": "127.0.0.1",
                                            "syslog_port": _free_port()}).json()["data"]
    failed = client.post(f"/managers/{closed['manager_id']}/syslog/test").json()
    assert failed["success"] is False and failed["data"]["status"] == "error"

    udp = client.post("/managers", json={"name": "udp-syslog", "siem_type": "none", "siem_ip": "127.0.0.1",
                                         "syslog_port": _free_port(), "syslog_protocol": "udp"}).json()["data"]
    assert client.post(f"/managers/{udp['manager_id']}/syslog/test").json()["data"]["status"] == "sent"

    plain = client.post("/managers", json={"name": "no-syslog", "siem_type": "wazuh", "siem_ip": "10.0.0.2"}).json()["data"]
    assert client.post(f"/managers/{plain['manager_id']}/syslog/test").status_code == 400
    assert client.post("/managers/nope/syslog/test").status_code == 404


def test_syslog_config_endpoints_are_gone(client):
    paths = client.get("/api/openapi.json").json()["paths"]
    assert not [p for p in paths if "syslog-config" in p]
    assert "/managers/{manager_id}/syslog/test" in paths


def test_migration_moves_syslog_configs_onto_profiles(tmp_path):
    db = tmp_path / "platform.db"
    migrations.migrate(db, make_backup=False)
    migrations.downgrade(db, 8)  # back to the syslog_configs table
    conn = sqlite3.connect(db)
    conn.executescript("""
        INSERT INTO managers (manager_id, name, siem_type, siem_ip) VALUES
            ('m-wazuh', 'wazuh-lab', 'wazuh', '10.0.0.5'),
            ('m-utm', 'utm-lab', 'utmstack', '10.0.0.6');
        INSERT INTO syslog_configs (config_id, name, description, manager_profile_id, target_ip, target_port, protocol, created_at) VALUES
            ('c1', 'wazuh syslog', NULL, 'm-wazuh', '10.0.0.5', 514, 'udp', '2026-01-01'),
            ('c2', 'utm-lab', 'firewall feed', 'm-utm', '10.9.9.9', 7014, 'tcp', '2026-01-02'),
            ('c3', 'splunk', NULL, NULL, '10.0.0.7', NULL, NULL, '2026-01-03');
    """)
    conn.commit()
    conn.close()

    migrations.migrate(db, make_backup=False)
    conn = sqlite3.connect(db)
    rows = {r[0]: r[1:] for r in conn.execute(
        "SELECT name, siem_type, siem_ip, syslog_port, syslog_protocol, description FROM managers")}
    assert rows["wazuh-lab"][:4] == ("wazuh", "10.0.0.5", 514, "udp")        # linked, same address: merged
    assert rows["utm-lab"][:4] == ("utmstack", "10.0.0.6", None, None)       # linked, other address: kept apart
    assert rows["utm-lab (syslog)"] == ("none", "10.9.9.9", 7014, "tcp", "firewall feed")
    assert rows["splunk"] == ("none", "10.0.0.7", 514, "tcp", "Syslog destination")
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "syslog_configs" not in tables
    conn.close()


def test_utmstack_listener_is_recorded_on_the_container(client, container, attach):
    on = client.post(f"/agents/{container}/enable-syslog", params={"protocol": "udp"})
    assert on.status_code == 200 and on.json()["success"] is True, on.text
    assert any("enable-integration syslog udp" in " ".join(c["argv"]) for c in attach.calls)
    assert client.get(f"/agents/{container}").json()["data"]["syslog_listener"] == "udp"

    off = client.post(f"/agents/{container}/disable-syslog", params={"protocol": "udp"})
    assert off.json()["success"] is True
    assert client.get(f"/agents/{container}").json()["data"].get("syslog_listener") is None


def test_siem_summary_counts_agents_and_latest_detection():
    infos = [
        {"siem_type": "wazuh", "lifecycle_status": "running", "siem_agent_running": True, "manager_reachable": True},
        {"siem_type": "wazuh", "lifecycle_status": "running", "siem_agent_running": True, "manager_reachable": False},
        {"siem_type": "wazuh", "lifecycle_status": "stopped"},
        {"siem_type": "none", "lifecycle_status": "running"},
        {"lifecycle_status": "running"},
    ]
    done = lambda rate, at: {"status": "done", "siem": "elastic", "detection_rate": rate, "detected": 1,  # noqa: E731
                             "containers": 2, "checked_at": at, "manager_name": "es"}
    sims = [
        {"simulation_id": "s1", "profile_id": "web_attacks", "detection": done(50.0, "2026-09-01T10:00:00Z")},
        {"simulation_id": "s2", "profile_id": "auth_bruteforce", "detection": done(100.0, "2026-09-02T10:00:00Z")},
        {"simulation_id": "s3", "profile_id": "auth_bruteforce", "detection": {"status": "error", "siem": "elastic"}},
        {"simulation_id": "s4", "profile_id": None},
    ]
    rows = {r["siem_type"]: r for r in summarize(infos, sims)}
    assert set(rows) == {"elastic", "wazuh"}
    wazuh = rows["wazuh"]
    assert (wazuh["containers"], wazuh["running"], wazuh["agents_running"], wazuh["manager_reachable"]) == (3, 2, 2, 1)
    assert wazuh["last_detection"] is None
    elastic = rows["elastic"]
    assert elastic["containers"] == 0 and elastic["detection_checks"] == 2
    assert elastic["last_detection"]["simulation_id"] == "s2" and elastic["last_detection"]["detection_rate"] == 100.0


def test_siem_summary_endpoint(client, container):
    resp = client.get("/siem/summary")
    assert resp.status_code == 200 and isinstance(resp.json()["data"]["siems"], list)
