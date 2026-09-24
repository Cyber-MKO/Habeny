"""
Monitoring and notifications: health probes, Prometheus metrics, alerts, channels.
"""
import hashlib
import hmac
import json
import re
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

from app.services import alerts, notify, telemetry


@pytest.fixture()
def receiver():
    """A local HTTP endpoint standing in for Slack or a webhook. `.fail_next` makes it answer 500."""
    received = []
    state = {"fail_next": 0}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            if state["fail_next"]:
                state["fail_next"] -= 1
                self.send_response(500)
                self.end_headers()
                return
            received.append({"path": self.path, "headers": dict(self.headers), "body": body})
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    yield type("Receiver", (), {"url": url, "received": received, "state": state})
    server.shutdown()


@pytest.fixture(autouse=True)
def clean_state(client):
    alerts.manager.reset()
    yield
    alerts.manager.reset()
    for channel in client.get("/notifications/channels").json()["data"]["channels"]:
        client.delete(f"/notifications/channels/{channel['id']}")


def _wait_for(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def _viewer_token(client):
    return client.post("/users/me/tokens", json={"name": "prometheus-" + uuid.uuid4().hex[:6],
                                                 "role": "viewer"}).json()["data"]["token"]


# ── health and metrics ──────────────────────────────────────────────────

def test_health_probes_need_no_sign_in(app):
    anonymous = TestClient(app)
    assert anonymous.get("/healthz").json()["status"] == "ok"
    ready = anonymous.get("/readyz")
    assert ready.status_code == 200 and ready.json() == {"status": "ready", "checks": {
        "database": "ok", "lxc": "ok", "disk": "ok"}}
    alerts.manager.fire("lxc_unavailable", "critical", "helper down")
    not_ready = anonymous.get("/readyz")
    assert not_ready.status_code == 503 and not_ready.json()["checks"]["lxc"] == "failing"
    assert "helper down" not in not_ready.text  # details only for signed-in users


_SAMPLE = re.compile(r'^[a-z_:][a-z0-9_:]*(\{([a-z_]+="([^"\\]|\\.)*",?)*\})? -?[0-9.e+Inf-]+$')


def test_metrics_need_a_token_and_are_valid_exposition(app, client):
    anonymous = TestClient(app)
    assert anonymous.get("/metrics").status_code == 401
    alerts.manager.fire("disk_low", "warning", "low", target="data")
    prometheus = TestClient(app, headers={"Authorization": f"Bearer {_viewer_token(client)}"})
    prometheus.get("/agents")
    resp = prometheus.get("/metrics")
    assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/plain; version=0.0.4")
    body = resp.text
    for line in body.splitlines():
        assert line.startswith("# HELP ") or line.startswith("# TYPE ") or _SAMPLE.match(line), line
    for name in ("habeny_info", "habeny_uptime_seconds", "habeny_lxc_up 1", "habeny_containers{state=",
                 "habeny_disk_free_bytes{", "habeny_database_size_bytes", "habeny_users",
                 'habeny_http_requests_total{code="2xx",method="GET"}',
                 'habeny_http_request_duration_seconds_bucket{le="+Inf",method="GET"}',
                 'habeny_alerts_active{alert="disk_low",severity="warning",target="data"} 1'):
        assert name in body, name


def test_label_values_are_escaped():
    counter = telemetry.Counter("x_total", "test")
    counter.inc(path='a "quoted"\\ value\n')
    assert list(counter.render())[-1] == 'x_total{path="a \\"quoted\\"\\\\ value\\n"} 1'


# ── alerts ──────────────────────────────────────────────────────────────

@pytest.fixture()
def lxc_reachable(monkeypatch):
    """CI runs unprivileged: without this, the check rightly raises lxc_unavailable too."""
    from app.core import lxc_backend
    monkeypatch.setattr(lxc_backend, "has_lxc_access", lambda: True)


def test_disk_alert_fires_and_clears(client, monkeypatch, lxc_reachable):
    usage = {"data": {"path": "/var/lib/habeny", "free": 4, "total": 100}}
    monkeypatch.setattr(telemetry, "disk_usage", lambda: usage)
    monkeypatch.setenv("HABENY_ALERT_DISK_PERCENT", "10")
    alerts.check()
    active = client.get("/system/alerts").json()["data"]["alerts"]
    assert [(a["name"], a["target"], a["severity"]) for a in active] == [("disk_low", "data", "critical")]
    assert "4.0% free" in active[0]["message"]
    usage["data"]["free"] = 50
    alerts.check()
    assert client.get("/system/alerts").json()["data"]["alerts"] == []


def test_lxc_alert(monkeypatch, lxc_reachable):
    from app.core import lxc_backend

    def broken():
        raise ConnectionRefusedError("helper socket refused")
    with monkeypatch.context() as m:
        m.setattr(lxc_backend.lxc, "list_containers", broken)
        alerts.check()
    assert any(a["name"] == "lxc_unavailable" for a in alerts.manager.active())
    alerts.check()
    assert not any(a["name"] == "lxc_unavailable" for a in alerts.manager.active())


def test_deploy_and_backup_alerts(monkeypatch):
    alerts.deployment_finished("d1", 10, 7, 3, None)
    alert = alerts.manager.active()[0]
    assert alert["name"] == "deploy_failed" and alert["severity"] == "warning" and "3 of 10" in alert["message"]
    alerts.deployment_finished("d2", 5, 5, 0, None)
    assert alerts.manager.active() == []

    from app.services import backup, maintenance

    def failing():
        raise backup.BackupError("disk full")
    monkeypatch.setattr(backup, "backup_if_due", failing)
    with pytest.raises(backup.BackupError):
        maintenance._backup_if_due()
    assert alerts.manager.active()[0]["name"] == "backup_failed"
    monkeypatch.setattr(backup, "backup_if_due", lambda: "path")
    maintenance._backup_if_due()
    assert alerts.manager.active() == []


def test_deployment_counts_in_metrics(client):
    before = telemetry.DEPLOYMENTS.value(result="failed")
    from app.routes.agents import _announce_deployment
    _announce_deployment("d3", "failed", 2, 0, 2, 1.5, "none", "no network")
    assert telemetry.DEPLOYMENTS.value(result="failed") == before + 1
    assert alerts.manager.active()[0]["severity"] == "critical"


# ── notification channels ───────────────────────────────────────────────

def test_channels_are_admin_only(app, client):
    name, pw = "op" + uuid.uuid4().hex[:6], "operator-password-1"
    user = client.post("/users", json={"username": name, "password": pw, "role": "operator"}).json()["data"]["user"]
    operator = TestClient(app)
    operator.post("/auth/login", json={"username": name, "password": pw})
    assert operator.get("/notifications/channels").status_code == 403
    assert operator.post("/notifications/channels", json={"name": "x", "type": "slack",
                                                          "config": {"url": "https://example.com"}}).status_code == 403
    client.delete(f"/users/{user['id']}")


@pytest.mark.parametrize("body,problem", [
    ({"type": "slack", "config": {"url": "ftp://x"}}, "url"),
    ({"type": "webhook", "config": {}}, "url"),
    ({"type": "webhook", "config": {"url": "https://x"}, "events": ["nope"]}, "unknown events"),
    ({"type": "email", "config": {"to": "not-an-address"}}, "to:"),
    ({"type": "email", "config": {"to": "ops@example.com"}}, "HABENY_SMTP_HOST"),
])
def test_channel_validation(client, body, problem):
    resp = client.post("/notifications/channels", json={"name": "bad", **body})
    assert resp.status_code == 400 and problem in resp.json()["detail"]


def test_webhook_delivery_with_signature_and_masked_secrets(client, receiver):
    resp = client.post("/notifications/channels", json={
        "name": "ops webhook", "type": "webhook", "events": ["deployment.finished"],
        "config": {"url": f"{receiver.url}/hook?token=abc123", "secret": "s3cret"}})
    assert resp.status_code == 200, resp.text
    channel = resp.json()["data"]["channel"]
    assert "abc123" not in json.dumps(channel) and "s3cret" not in json.dumps(channel)
    assert channel["config"]["url"].startswith("http://127.0.0.1:") and channel["config"]["secret"] == "••••••"
    assert client.post("/notifications/channels", json={"name": "ops webhook", "type": "webhook",
                                                        "config": {"url": "https://x"}}).status_code == 400

    assert notify.emit("simulation.finished", "not subscribed") == 0
    assert notify.emit("deployment.finished", "Deployment succeeded: 3/3", level="success",
                       fields={"deployment_id": "d9"}, link="/deploy") == 1
    assert _wait_for(lambda: receiver.received)
    got = receiver.received[0]
    assert got["path"] == "/hook?token=abc123" and got["headers"]["X-Habeny-Event"] == "deployment.finished"
    expected = hmac.new(b"s3cret", got["body"], hashlib.sha256).hexdigest()
    assert got["headers"]["X-Habeny-Signature"] == f"sha256={expected}"
    payload = json.loads(got["body"])
    assert payload["title"] == "Deployment succeeded: 3/3" and payload["fields"] == {"deployment_id": "d9"}
    assert payload["server"]["version"]
    assert _wait_for(lambda: client.get("/notifications/channels").json()["data"]["channels"][0]["last_status"] == "ok")

    # Editing without re-entering the secret keeps it
    client.put(f"/notifications/channels/{channel['id']}", json={
        "name": "ops webhook", "type": "webhook", "events": [], "config": {"url": "", "secret": ""}})
    stored = notify.get_channel(channel["id"], reveal=True)
    assert stored["config"] == {"url": f"{receiver.url}/hook?token=abc123", "secret": "s3cret"}


def test_only_problems_and_disabled_channels(client, receiver):
    client.post("/notifications/channels", json={"name": "problems", "type": "slack", "only_problems": True,
                                                 "config": {"url": receiver.url}})
    off = client.post("/notifications/channels", json={"name": "off", "type": "slack", "enabled": False,
                                                       "config": {"url": receiver.url}}).json()["data"]["channel"]
    assert notify.emit("deployment.finished", "fine", level="success") == 0
    assert notify.emit("deployment.finished", "broken", level="error") == 1
    assert _wait_for(lambda: receiver.received)
    slack = json.loads(receiver.received[0]["body"])
    assert slack["text"].startswith(":x: *broken*")
    assert off["enabled"] is False


def test_alerts_notify_when_they_start_and_clear(client, receiver):
    client.post("/notifications/channels", json={"name": "alerts", "type": "webhook",
                                                 "events": ["alert.firing", "alert.resolved"],
                                                 "config": {"url": receiver.url}})
    alerts.manager.fire("disk_low", "warning", "3% free", target="containers")
    alerts.manager.fire("disk_low", "warning", "2% free", target="containers")  # same episode: no repeat
    alerts.manager.clear("disk_low", "containers")
    assert _wait_for(lambda: len(receiver.received) == 2)
    events = [json.loads(r["body"]) for r in receiver.received]
    assert [e["event"] for e in events] == ["alert.firing", "alert.resolved"]
    assert events[0]["level"] == "warning" and events[0]["title"] == "Low disk space (containers)"


def test_failed_delivery_is_retried(client, receiver, monkeypatch):
    monkeypatch.setattr(notify, "RETRY_DELAYS", (0.05, 0.05))
    receiver.state["fail_next"] = 1
    client.post("/notifications/channels", json={"name": "flaky", "type": "webhook", "config": {"url": receiver.url}})
    notify.emit("benchmark.finished", "done")
    assert _wait_for(lambda: receiver.received)


def test_test_button(client, receiver):
    ok = client.post("/notifications/channels", json={"name": "t1", "type": "webhook",
                                                      "config": {"url": receiver.url}}).json()["data"]["channel"]
    assert client.post(f"/notifications/channels/{ok['id']}/test").json()["success"] is True
    assert json.loads(receiver.received[0]["body"])["event"] == "test"
    bad = client.post("/notifications/channels", json={"name": "t2", "type": "webhook",
                                                       "config": {"url": "http://127.0.0.1:9/nothing"}}).json()["data"]["channel"]
    result = client.post(f"/notifications/channels/{bad['id']}/test").json()
    assert result["success"] is False and result["error"]
    channels = {c["name"]: c for c in client.get("/notifications/channels").json()["data"]["channels"]}
    assert channels["t2"]["last_status"] == "error" and channels["t1"]["last_status"] == "ok"


def test_email(client, monkeypatch):
    sent = []

    class FakeSMTP:
        def __init__(self, host, port, timeout, **kw):
            sent.append(("connect", host, port))

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def starttls(self, context):
            sent.append(("starttls",))

        def login(self, user, password):
            sent.append(("login", user, password))

        def send_message(self, msg):
            sent.append(("send", msg["To"], msg["Subject"], msg.get_content()))

    monkeypatch.setattr(notify.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setenv("HABENY_SMTP_HOST", "mail.example.com")
    monkeypatch.setenv("HABENY_SMTP_USER", "habeny")
    monkeypatch.setenv("HABENY_SMTP_PASSWORD", "pw")
    channel = client.post("/notifications/channels", json={
        "name": "mail", "type": "email", "config": {"to": "ops@example.com; oncall@example.com"}}).json()["data"]["channel"]
    assert channel["config"]["to"] == ["ops@example.com", "oncall@example.com"]
    assert client.post(f"/notifications/channels/{channel['id']}/test").json()["success"] is True
    assert sent[0] == ("connect", "mail.example.com", 587) and ("starttls",) in sent and ("login", "habeny", "pw") in sent
    to, subject, content = sent[-1][1:]
    assert to == "ops@example.com, oncall@example.com" and subject == "[Habeny] Test notification"
    assert "is set up correctly" in content
