"""
Stored SIEM auth keys: encrypted at rest, never returned by the API.
"""
import sqlite3

import pytest
from cryptography.fernet import Fernet

from app.config import DB_PATH
from app.core import secrets


def test_roundtrip_and_legacy_plaintext():
    enc = secrets.encrypt_secret("utm-key-12345678")
    assert enc.startswith("enc:v1:") and "utm-key" not in enc
    assert secrets.decrypt_secret(enc) == "utm-key-12345678"
    assert secrets.encrypt_secret(enc) == enc  # not double-encrypted
    assert secrets.decrypt_secret("legacy-plain") == "legacy-plain"
    assert secrets.encrypt_secret(None) is None and secrets.encrypt_secret("") == ""
    assert secrets.secret_hint(enc) == "••••5678"


def test_wrong_key_fails_safely(monkeypatch):
    enc = secrets.encrypt_secret("some-secret-value")
    monkeypatch.setattr(secrets, "_fernet", Fernet(Fernet.generate_key()))
    assert secrets.decrypt_secret(enc) is None


def _raw_key(manager_id):
    return sqlite3.connect(DB_PATH).execute("SELECT siem_auth_key FROM managers WHERE manager_id=?", (manager_id,)).fetchone()[0]


def test_manager_api_never_returns_key(client):
    resp = client.post("/managers", json={"name": "utm-prod", "siem_type": "utmstack", "siem_ip": "10.0.0.9",
                                          "siem_auth_key": "SuperSecretKey123"}).json()
    mgr = resp["data"]
    assert "siem_auth_key" not in mgr and mgr["has_siem_auth_key"] is True and mgr["siem_auth_key_hint"] == "••••y123"
    for body in (client.get("/managers").text, client.get(f"/managers/{mgr['manager_id']}").text):
        assert "SuperSecretKey123" not in body
    assert _raw_key(mgr["manager_id"]).startswith("enc:v1:")

    # blank on edit keeps the stored key; a new one replaces it
    client.put(f"/managers/{mgr['manager_id']}", json={"description": "edited"})
    from app.db import get_manager
    assert get_manager(DB_PATH, mgr["manager_id"])["siem_auth_key"] == "SuperSecretKey123"
    client.put(f"/managers/{mgr['manager_id']}", json={"siem_auth_key": "RotatedKey9876"})
    assert get_manager(DB_PATH, mgr["manager_id"])["siem_auth_key"] == "RotatedKey9876"
    assert _raw_key(mgr["manager_id"]).startswith("enc:v1:")


def test_upgrade_encrypts_existing_plaintext_keys(client):
    from app.db import encrypt_plaintext_manager_secrets, get_manager
    mid = client.post("/managers", json={"name": "legacy", "siem_type": "elastic", "siem_ip": "fleet.local",
                                         "siem_auth_key": "dG9rZW4="}).json()["data"]["manager_id"]
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE managers SET siem_auth_key='dG9rZW4=' WHERE manager_id=?", (mid,))  # as stored before
    conn.commit()
    assert encrypt_plaintext_manager_secrets(DB_PATH) >= 1
    assert _raw_key(mid).startswith("enc:v1:")
    assert get_manager(DB_PATH, mid)["siem_auth_key"] == "dG9rZW4="
    assert encrypt_plaintext_manager_secrets(DB_PATH) == 0


def test_benchmark_config_never_stores_key():
    from app.services.benchmarks import _storable_config
    assert _storable_config({"siem_ip": "1.2.3.4", "siem_auth_key": "k"}) == {"siem_ip": "1.2.3.4"}


def test_deploy_with_profile_needs_no_key_in_request():
    from app.models import AgentDeploymentRequest
    req = AgentDeploymentRequest(count=1, siem_type="utmstack", manager_profile_id="p1")
    assert req.siem_auth_key is None
    with pytest.raises(ValueError):
        AgentDeploymentRequest(count=1, siem_type="utmstack", siem_ip="1.2.3.4")  # no profile: still required
