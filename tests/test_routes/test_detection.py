"""
Checking what the SIEM detected: the Elasticsearch-compatible search client (credentials,
certificate pinning, errors), the Wazuh and Elastic result parsing (detection rate, time to
detection, expected and missed rules, ingestion), manager profile settings (admins only,
secrets masked), and the check after a simulation.

The SIEM is a fake Elasticsearch/OpenSearch served over real TLS with a self-signed
certificate, answering from canned aggregations.
"""
import asyncio
import json
import ssl
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

from app.services import detection
from app.state import simulations_db

START = datetime(2026, 9, 24, 20, 0, tzinfo=timezone.utc)


def _iso(seconds):
    return (START + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


class FakeSiem:
    def __init__(self, tmp_path):
        from app.tls import _generate_self_signed
        cert, key = tmp_path / "es.pem", tmp_path / "es.key"
        _generate_self_signed(cert, key)
        self.requests = []
        self.answer = lambda path, body: (200, {"hits": {"total": {"value": 0}}, "aggregations": {}})
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")
                fake.requests.append({"path": self.path, "body": body, "auth": self.headers.get("Authorization")})
                status, payload = fake.answer(self.path, body)
                data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        self.server.socket = context.wrap_socket(self.server.socket, server_side=True)
        self.url = f"https://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        from app.services.hosts import peer_fingerprint
        self.fingerprint = peer_fingerprint(self.url)

    def close(self):
        self.server.shutdown()


@pytest.fixture()
def siem(tmp_path):
    fake = FakeSiem(tmp_path)
    yield fake
    fake.close()


def _manager(siem, siem_type="wazuh", **extra):
    return {"siem_type": siem_type, "detection_url": siem.url, "detection_username": "admin",
            "detection_secret": "s3cret", "detection_fingerprint": siem.fingerprint, **extra}


def _wazuh_answer(path, body):
    """Two of three containers alerted; c1 on an expected rule 30 s in, c2 only on an unrelated rule."""
    return 200, {"hits": {"total": {"value": 7}}, "aggregations": {
        "hosts": {"buckets": [
            {"key": "c1", "doc_count": 5, "first": {"value_as_string": _iso(25)},
             "rules": {"buckets": [{"key": "5710", "doc_count": 4, "first": {"value_as_string": _iso(30)}},
                                   {"key": "5712", "doc_count": 1, "first": {"value_as_string": _iso(90)}}]}},
            {"key": "c2", "doc_count": 2, "first": {"value_as_string": _iso(40)},
             "rules": {"buckets": [{"key": "5501", "doc_count": 2, "first": {"value_as_string": _iso(40)}}]}},
        ]},
        "rules": {"buckets": [
            {"key": "5710", "doc_count": 4, "sample": {"hits": {"hits": [{"_source": {
                "rule": {"description": "sshd: Attempt to login using a non-existent user", "level": 5,
                         "mitre": {"id": ["T1110"]}}}}]}}},
            {"key": "5712", "doc_count": 1, "sample": {"hits": {"hits": [{"_source": {
                "rule": {"description": "sshd: brute force", "level": 10}}}]}}},
            {"key": "5501", "doc_count": 2, "sample": {"hits": {"hits": [{"_source": {
                "rule": {"description": "PAM: Login session opened", "level": 3}}}]}}},
        ]},
    }}


def test_wazuh_detection_rate_time_and_rules(siem):
    siem.answer = _wazuh_answer
    result = detection.check(_manager(siem), "auth_bruteforce", ["c1", "c2", "c3"], START.isoformat(), _iso(300))
    assert result["containers"] == 3 and result["detected"] == 1 and result["detection_rate"] == 33.3
    rows = {c["name"]: c for c in result["per_container"]}
    assert rows["c1"]["detected"] and rows["c1"]["ttd_seconds"] == 30.0  # first *expected* rule, not first alert
    assert not rows["c2"]["detected"] and rows["c2"]["alerts"] == 2  # alerted, but not on what the profile does
    assert not rows["c3"]["detected"] and rows["c3"]["alerts"] == 0
    assert result["ttd_seconds"] == {"median": 30.0, "max": 30.0}
    rules = {r["id"]: r for r in result["rules"]}
    assert rules["5710"]["expected"] and rules["5710"]["technique"] == ["T1110"] and not rules["5501"]["expected"]
    assert result["missed"] == [] and all(e["seen"] for e in result["expected"])
    assert result["basis"] == "expected rules" and "ingestion" not in result
    # the query: the Wazuh alerts index, these agents, this time window, basic auth
    request = siem.requests[-1]
    assert request["path"].startswith("/wazuh-alerts-*/_search")
    assert request["auth"] == "Basic YWRtaW46czNjcmV0"
    filters = request["body"]["query"]["bool"]["filter"]
    assert set(filters[0]["terms"]["agent.name"]) == {"c1", "c2", "c3"}
    assert filters[1]["range"]["timestamp"]["lte"] == _iso(300)


def test_missed_expected_rules_are_listed(siem):
    siem.answer = _wazuh_answer
    result = detection.check(_manager(siem), "privilege_escalation", ["c1"], START.isoformat(), _iso(300))
    assert result["detected"] == 0 and sorted(result["missed"]) == ["5302", "5401", "5405"]


def test_elastic_counts_any_alert_and_measures_ingestion(siem):
    def answer(path, body):
        if path.startswith("/logs-*"):
            return 200, {"hits": {"total": {"value": 120}}, "aggregations": {"hosts": {"buckets": [
                {"key": "web-0001", "doc_count": 120, "first": {"value_as_string": _iso(12)}}]}}}
        return 200, {"hits": {"total": {"value": 1}}, "aggregations": {
            "hosts": {"buckets": [{"key": "web-0001", "doc_count": 1, "first": {"value_as_string": _iso(70)},
                                   "rules": {"buckets": [{"key": "uuid-1", "doc_count": 1,
                                                          "first": {"value_as_string": _iso(70)}}]}}]},
            "rules": {"buckets": [{"key": "uuid-1", "doc_count": 1, "sample": {"hits": {"hits": [{"_source": {
                "kibana.alert.rule.name": "Potential SSH Brute Force", "kibana.alert.severity": "medium"}}]}}}]}}}
    siem.answer = answer
    manager = _manager(siem, "elastic", detection_username="", detection_secret="aWQ6a2V5")
    result = detection.check(manager, "auth_bruteforce", ["web-0001", "web-0002"], START.isoformat(), _iso(300))
    assert result["basis"] == "any alert" and result["detected"] == 1 and result["expected"] == []
    assert result["rules"][0]["name"] == "Potential SSH Brute Force" and result["rules"][0]["level"] == "medium"
    assert result["ingestion"] == {"events": 120, "hosts_reporting": 1,
                                   "first_event_seconds": {"median": 12.0, "max": 12.0}}
    assert siem.requests[0]["path"].startswith("/.alerts-security.alerts-*/_search")
    assert siem.requests[0]["auth"] == "ApiKey aWQ6a2V5"  # no user name: an Elasticsearch API key


def test_connection_errors_are_clear(siem):
    unpinned = _manager(siem, detection_fingerprint=None)
    with pytest.raises(detection.FingerprintNeeded) as info:
        detection.test_connection(unpinned)
    assert info.value.fingerprint == siem.fingerprint
    with pytest.raises(detection.DetectionError, match="different certificate"):
        detection.test_connection(_manager(siem, detection_fingerprint="AA:" * 31 + "AA"))
    siem.answer = lambda path, body: (401, {"error": "unauthorized"})
    with pytest.raises(detection.DetectionError, match="rejected the credentials"):
        detection.test_connection(_manager(siem))
    siem.answer = lambda path, body: (200, b"<html>not elasticsearch</html>")
    with pytest.raises(detection.DetectionError, match="didn't answer like"):
        detection.test_connection(_manager(siem))
    siem.answer = lambda path, body: (400, {"error": {"reason": "no such field [agent.name]"}})
    with pytest.raises(detection.DetectionError, match="no such field"):
        detection.test_connection(_manager(siem))
    with pytest.raises(detection.DetectionError):
        detection.normalize_url("ftp://x")
    with pytest.raises(detection.DetectionError):
        detection.normalize_url("https://user:pw@x:9200")


# ── through the API ─────────────────────────────────────────────────────

@pytest.fixture()
def operator(app, client):
    client.post("/users", json={"username": "detop", "password": "operator-password-1", "role": "operator"})
    c = TestClient(app)
    c.post("/auth/login", json={"username": "detop", "password": "operator-password-1"})
    yield c
    uid = next(u["id"] for u in client.get("/users").json()["data"]["users"] if u["username"] == "detop")
    client.delete(f"/users/{uid}")


def test_profile_detection_settings_are_admin_only_and_masked(client, operator, siem):
    body = {"name": "wazuh-det", "siem_type": "wazuh", "siem_ip": "10.0.0.5",
            "detection_url": siem.url + "/", "detection_username": "admin", "detection_secret": "s3cret"}
    assert operator.post("/managers", json=body).status_code == 403
    created = client.post("/managers", json=body).json()["data"]
    try:
        assert created["detection_url"] == siem.url and created["has_detection_secret"]
        assert "detection_secret" not in created and "s3cret" not in client.get("/managers").text
        # operators can still edit the rest of the profile, but not the connection
        mid = created["manager_id"]
        assert operator.put(f"/managers/{mid}", json={"description": "edited"}).status_code == 200
        assert operator.put(f"/managers/{mid}", json={"detection_url": "https://evil:9200"}).status_code == 403
        # self-signed: the test answers with the fingerprint, an admin confirms it, then it connects
        resp = client.post(f"/managers/{mid}/detection/test")
        assert resp.status_code == 409 and resp.json()["fingerprint"] == siem.fingerprint
        client.put(f"/managers/{mid}", json={"detection_fingerprint": siem.fingerprint})
        siem.answer = lambda path, body: (200, {"hits": {"total": {"value": 42}}})
        ok = client.post(f"/managers/{mid}/detection/test").json()
        assert ok["success"] and ok["data"]["alerts_last_24h"] == 42
        bad = client.post("/managers", json={**body, "name": "bad", "detection_url": "ftp://x"})
        assert bad.status_code == 400 and "http(s)" in bad.json()["detail"]
    finally:
        client.delete(f"/managers/{created['manager_id']}")


def test_simulation_checks_detection_after_the_run(client, siem, monkeypatch):
    from app.config import DB_PATH
    from app.db import create_manager, delete_manager
    from app.services import simulation
    create_manager(DB_PATH, "det-mgr", {"name": "det-mgr", "siem_type": "wazuh", **{
        k: v for k, v in _manager(siem).items() if k != "siem_type"}})
    create_manager(DB_PATH, "plain-mgr", {"name": "plain-mgr", "siem_type": "wazuh"})
    siem.answer = _wazuh_answer
    monkeypatch.setattr(simulation, "execute_in_container",
                        lambda name, script, timeout: {"success": True, "stdout": "EVENTS_WRITTEN=5"})
    monkeypatch.setattr(simulation, "announce_finished", lambda sim_id: None)
    monkeypatch.setenv("HABENY_DETECTION_DELAY_SECONDS", "0")
    try:
        # a profile without a detection API is refused up front
        resp = client.post("/simulations/start", json={"profile_id": "auth_bruteforce", "detection_profile_id": "plain-mgr",
                                                       "agent_selector": {"agent_ids": ["c1"]}})
        assert resp.status_code in (400, 422)
        simulations_db["sim-det"] = {"simulation_id": "sim-det", "status": "running", "profile_id": "auth_bruteforce",
                                     "target_agents": ["c1", "c2"], "started_at": START.isoformat(),
                                     "detection": {"status": "waiting", "manager_profile_id": "det-mgr"}}
        asyncio.run(simulation.run_simulation("sim-det", "auth_bruteforce", ["c1", "c2"], 1, 5))
        found = simulations_db["sim-det"]["detection"]
        assert found["status"] == "done" and found["detected"] == 1 and found["containers"] == 2
        assert found["manager_name"] == "det-mgr" and found["missed"] == []
        # checked again by hand, e.g. after a slow SIEM caught up
        again = client.post("/simulations/sim-det/detection")
        assert again.status_code == 200 and again.json()["data"]["detection_rate"] == 50.0
        # a failing SIEM is reported, not raised
        siem.answer = lambda path, body: (401, {})
        failed = client.post("/simulations/sim-det/detection")
        assert failed.status_code == 502 and "credentials" in failed.json()["detail"]
        assert simulations_db["sim-det"]["detection"]["status"] == "error"
    finally:
        simulations_db.pop("sim-det", None)
        delete_manager(DB_PATH, "det-mgr")
        delete_manager(DB_PATH, "plain-mgr")


def test_interrupted_checks_are_marked_after_a_restart(tmp_path):
    import sqlite3

    from app import migrations
    from app.services.records import PersistentStore
    db = tmp_path / "platform.db"
    migrations.migrate(db)
    store = PersistentStore("simulation")
    store.load(db)
    store["s1"] = {"simulation_id": "s1", "status": "completed", "detection": {"status": "waiting"}}
    reloaded = PersistentStore("simulation")
    reloaded.load(db)
    assert reloaded["s1"]["detection"]["status"] == "not_checked"
    sqlite3.connect(db).close()


def test_reports_compare_detection_across_siems(client):
    from app.services.reporting import summarize_detections
    now = datetime.now(timezone.utc)
    runs = {"rep-w1": ("wazuh", 100.0, 20.0, []), "rep-w2": ("wazuh", 50.0, 40.0, ["5712"]),
            "rep-e1": ("elastic", 0.0, None, [])}
    for sid, (siem, rate, ttd, missed) in runs.items():
        simulations_db[sid] = {"simulation_id": sid, "status": "completed", "profile_id": "auth_bruteforce",
                               "started_at": now.isoformat(), "target_agents": ["c1", "c2"],
                               "detection": {"status": "done", "siem": siem, "detected": int(rate // 50),
                                             "containers": 2, "detection_rate": rate, "missed": missed,
                                             "ttd_seconds": {"median": ttd, "max": ttd} if ttd else None}}
    try:
        for fmt in ("json", "pdf", "csv"):
            resp = client.post("/reports/generate", json={"format": fmt, "start_time": (now - timedelta(hours=1)).isoformat(),
                                                          "end_time": (now + timedelta(hours=1)).isoformat()})
            assert resp.status_code == 200, resp.text
        summary = {(r["profile"], r["siem"]): r for r in resp.json()["data"]["report"]["detection_summary"]}
        wazuh = summary[("auth_bruteforce", "wazuh")]
        assert wazuh["runs"] == 2 and wazuh["detection_rate"] == 75.0 and wazuh["median_ttd_seconds"] == 30.0
        assert wazuh["missed_rules"] == ["5712"] and summary[("auth_bruteforce", "elastic")]["detection_rate"] == 0.0
        download = client.get(resp.json()["data"]["download_url"])
        assert "detection,auth_bruteforce.wazuh.detection_rate,75.0" in download.text
    finally:
        for sid in runs:
            simulations_db.pop(sid, None)
    assert summarize_detections([]) == []
