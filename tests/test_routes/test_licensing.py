"""
Per-server licenses: signing and checking, trial and grace, gating new work, the API and CLI.
"""
import base64
from datetime import date, timedelta

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app import cli, licensing_key
from app.services import alerts, licensing

lxc = pytest.importorskip("lxc")
if not hasattr(lxc, "_containers"):
    pytest.skip("needs the LXC stub (PYTHONPATH=tests/stubs)", allow_module_level=True)

TODAY = date.today()


def _public(key):
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode()


@pytest.fixture()
def vendor_key(monkeypatch, tmp_path):
    """Licensing on, with a throwaway signing key; no license installed; a fixed server ID."""
    key = Ed25519PrivateKey.generate()
    monkeypatch.setattr(licensing_key, "PUBLIC_KEYS", [_public(key)])
    monkeypatch.setattr(licensing, "license_path", lambda: tmp_path / "license.key")
    monkeypatch.setattr(licensing, "_machine_id", lambda: "test-machine")
    yield key
    alerts.manager.clear("license")


@pytest.fixture(autouse=True)
def lxc_access(app):
    from app.core.common import check_root
    app.dependency_overrides[check_root] = lambda: True
    yield
    app.dependency_overrides.pop(check_root, None)


def _payload(**changes):
    payload = {"v": 1, "id": "L-TEST-1", "customer": "Example Corp", "server_id": licensing.server_id(),
               "issued": TODAY.isoformat(), "expires": (TODAY + timedelta(days=365)).isoformat(),
               "max_containers": None, "features": []}
    return {**payload, **changes}


def _trial_started(monkeypatch, days_ago):
    monkeypatch.setattr(licensing, "_trial_start", lambda: TODAY - timedelta(days=days_ago))


def test_off_without_public_key(client, monkeypatch):
    monkeypatch.setattr(licensing_key, "PUBLIC_KEYS", [])
    info = client.get("/license").json()["data"]
    assert info["state"] == "off" and info["allows_new_work"]
    licensing.require(adding=10_000)  # nothing is enforced
    resp = client.post("/license", json={"license": "HBYL1.anything.here"})
    assert resp.status_code == 400 and "off" in resp.json()["detail"]


def test_sign_and_decode(vendor_key):
    text = licensing.sign(vendor_key, _payload())
    assert text.startswith("HBYL1.") and licensing.decode(f"# comment\n{text}\n")["customer"] == "Example Corp"
    head, body, sig = text.split(".")
    tampered = base64.urlsafe_b64encode(base64.urlsafe_b64decode(body + "==").replace(b"Example", b"Exanple"))
    with pytest.raises(licensing.LicenseError, match="signature"):
        licensing.decode(f"{head}.{tampered.decode().rstrip('=')}.{sig}")
    other = licensing.sign(Ed25519PrivateKey.generate(), _payload())
    with pytest.raises(licensing.LicenseError, match="signature"):
        licensing.decode(other)
    with pytest.raises(licensing.LicenseError, match="isn't a Habeny license"):
        licensing.decode("hello")
    with pytest.raises(licensing.LicenseError, match="container limit"):
        licensing.sign(vendor_key, _payload(max_containers=0))


def test_server_id_is_stable_and_hides_machine_id(vendor_key):
    sid = licensing.server_id()
    assert sid == licensing.server_id() and len(sid) == 24 and sid.count("-") == 4
    assert "test-machine" not in sid.lower()


def test_trial_then_trial_ended(client, vendor_key, monkeypatch):
    _trial_started(monkeypatch, 3)
    info = client.get("/license").json()["data"]
    assert info["state"] == "trial" and info["days_left"] == licensing.TRIAL_DAYS - 3 and info["allows_new_work"]
    _trial_started(monkeypatch, licensing.TRIAL_DAYS + 1)
    info = client.get("/license").json()["data"]
    assert info["state"] == "trial_ended" and not info["allows_new_work"]
    licensing.check_alert()
    assert any(a["name"] == "license" and a["severity"] == "critical" for a in alerts.manager.active())


def test_new_work_refused_but_management_allowed(client, vendor_key, monkeypatch):
    _trial_started(monkeypatch, licensing.TRIAL_DAYS + 1)
    resp = client.post("/agents/deploy", json={"count": 1, "siem_type": "none", "agent_base_name": "lic"})
    assert resp.status_code == 402 and "trial has ended" in resp.json()["detail"]
    assert client.post("/benchmarks/start", json={"scenario_id": "x"}).status_code == 402
    assert client.post("/simulations/syslog/start", json={"target_ip": "127.0.0.1"}).status_code == 402
    # viewing and managing existing containers still work
    c = lxc.Container("lic-existing")
    c.create("download")
    c.start()
    try:
        assert client.get("/agents").status_code == 200
        assert client.post("/agents/lic-existing/stop").status_code == 200
        assert client.delete("/agents/lic-existing").status_code == 200
    finally:
        lxc._containers.pop("lic-existing", None)


def test_install_via_api_and_container_limit(client, vendor_key, monkeypatch):
    _trial_started(monkeypatch, licensing.TRIAL_DAYS + 1)
    text = licensing.sign(vendor_key, _payload(max_containers=2))
    resp = client.post("/license", json={"license": text})
    assert resp.status_code == 200, resp.text
    info = resp.json()["data"]
    assert info["state"] == "active" and info["license"]["customer"] == "Example Corp"
    existing = len(lxc.list_containers())
    licensing.require(adding=1, existing=1)
    with pytest.raises(licensing.LicenseRequired, match="allows 2 containers"):
        licensing.require(adding=3, existing=existing)
    entries = client.get("/activity/logs", params={"action": "license_installed"}).json()["data"]
    assert "L-TEST-1" in str(entries)


def test_install_refuses_other_server_and_expired(client, vendor_key):
    wrong = licensing.sign(vendor_key, _payload(server_id="AAAA-BBBB-CCCC-DDDD-EEEE"))
    resp = client.post("/license", json={"license": wrong})
    assert resp.status_code == 400 and "for server AAAA" in resp.json()["detail"]
    old = (TODAY - timedelta(days=licensing.GRACE_DAYS + 1)).isoformat()
    resp = client.post("/license", json={"license": licensing.sign(vendor_key, _payload(expires=old))})
    assert resp.status_code == 400 and "expired" in resp.json()["detail"]


def test_install_needs_admin(app, client, vendor_key):
    from fastapi.testclient import TestClient
    client.post("/users", json={"username": "licviewer", "password": "viewer-password-123", "role": "viewer"})
    viewer = TestClient(app)
    viewer.post("/auth/login", json={"username": "licviewer", "password": "viewer-password-123"})
    assert viewer.get("/license").status_code == 200
    assert viewer.post("/license", json={"license": licensing.sign(vendor_key, _payload())}).status_code == 403
    uid = next(u["id"] for u in client.get("/users").json()["data"]["users"] if u["username"] == "licviewer")
    client.delete(f"/users/{uid}")


def test_expiring_grace_expired(vendor_key):
    licensing.install(licensing.sign(vendor_key, _payload(expires=(TODAY + timedelta(days=10)).isoformat())))
    assert licensing.status_info()["state"] == "expiring"
    licensing.check_alert()
    assert any(a["name"] == "license" and a["severity"] == "warning" for a in alerts.manager.active())
    expires = TODAY + timedelta(days=10)
    grace = licensing.status_info(today=expires + timedelta(days=3))
    assert grace["state"] == "grace" and grace["allows_new_work"]
    expired = licensing.status_info(today=expires + timedelta(days=licensing.GRACE_DAYS + 1))
    assert expired["state"] == "expired" and not expired["allows_new_work"]
    perpetual = licensing.sign(vendor_key, _payload(expires=None))
    licensing.install(perpetual)
    assert licensing.status_info(today=TODAY + timedelta(days=5000))["state"] == "active"
    licensing.check_alert()
    assert not any(a["name"] == "license" for a in alerts.manager.active())


def test_damaged_license_file_falls_back_to_trial(vendor_key, monkeypatch):
    _trial_started(monkeypatch, 1)
    licensing.license_path().write_text("HBYL1.garbage.x")
    info = licensing.status_info()
    assert info["state"] == "invalid" and info["allows_new_work"] and info["problem"]
    _trial_started(monkeypatch, licensing.TRIAL_DAYS + 1)
    assert not licensing.status_info()["allows_new_work"]


def test_cli(vendor_key, capsys, tmp_path, monkeypatch):
    _trial_started(monkeypatch, 1)
    assert cli.main(["license", "request"]) == 0
    assert licensing.server_id() in capsys.readouterr().out
    path = tmp_path / "customer.license"
    path.write_text(licensing.sign(vendor_key, _payload()) + "\n")
    assert cli.main(["license", "install", str(path)]) == 0
    out = capsys.readouterr().out
    assert "Installed license L-TEST-1" in out and "State:      active" in out
    bad = tmp_path / "bad.license"
    bad.write_text("nope")
    assert cli.main(["license", "install", str(bad)]) == 1
    assert "isn't a Habeny license" in capsys.readouterr().err


def test_vendor_tool(tmp_path, monkeypatch):
    import subprocess
    import sys
    key = tmp_path / "signing.pem"
    run = lambda *a: subprocess.run([sys.executable, "tools/license_tool.py", *a], capture_output=True,  # noqa: E731
                                    text=True, check=False)
    out = run("keygen", "--out", str(key))
    assert out.returncode == 0 and "PUBLIC_KEYS" in out.stdout and (key.stat().st_mode & 0o777) == 0o600
    assert run("keygen", "--out", str(key)).returncode != 0  # never overwrites a key
    lic = tmp_path / "x.license"
    out = run("sign", "--key", str(key), "--id", "L-1", "--customer", "ACME", "--server-id", "aaaa-bbbb",
              "--expires", "2030-01-01", "--max-containers", "5", "--out", str(lic))
    assert out.returncode == 0, out.stderr
    out = run("inspect", str(lic), "--key", str(key))
    assert out.returncode == 0 and '"server_id": "AAAA-BBBB"' in out.stdout
    assert run("inspect", str(lic)).returncode == 1  # not signed by a built-in key


def test_third_party_notices_route(client):
    resp = client.get("/THIRD_PARTY_NOTICES.txt")
    assert resp.headers["content-type"].startswith("text/plain")
    assert resp.status_code == 200 or "deploy/third_party_notices.py" in resp.text


def test_server_id_without_machine_id(monkeypatch, tmp_path):
    monkeypatch.setattr(licensing, "MACHINE_ID_FILES", [str(tmp_path / "missing")])
    monkeypatch.setattr(licensing.config, "DATA_DIR", tmp_path / "not-writable" / "x")
    monkeypatch.setattr(licensing, "_generated_id", None)
    assert licensing.server_id() == licensing.server_id()  # stable even when it can't be saved
    monkeypatch.setattr(licensing.config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(licensing, "_generated_id", None)
    first = licensing.server_id()
    monkeypatch.setattr(licensing, "_generated_id", None)
    assert licensing.server_id() == first and (tmp_path / "server-id").is_file()  # saved, survives restarts


def test_built_in_public_keys_are_valid():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    for key in licensing_key.PUBLIC_KEYS:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(key, validate=True))
