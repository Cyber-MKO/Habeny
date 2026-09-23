"""
Two-factor sign-in: enrolment, the second login step, recovery codes, replay and admin reset.
"""
import uuid

import pytest
from fastapi.testclient import TestClient

from app.services import totp
from app.services.auth import login_limiter


@pytest.fixture(autouse=True)
def _fresh_limiter():
    login_limiter.reset("testclient")
    yield
    login_limiter.reset("testclient")


@pytest.fixture()
def user(app, client):
    """A new operator, signed in; yields (session, id, username, password)."""
    name, pw = "u" + uuid.uuid4().hex[:8], "member-password-1"
    uid = client.post("/users", json={"username": name, "password": pw, "role": "operator"}).json()["data"]["user"]["id"]
    c = TestClient(app)
    assert c.post("/auth/login", json={"username": name, "password": pw}).status_code == 200
    yield c, uid, name, pw
    client.delete(f"/users/{uid}")


def _enroll(c, pw):
    """Turn 2FA on; returns (secret, recovery codes)."""
    setup = c.post("/users/me/2fa/setup", json={"current_password": pw})
    assert setup.status_code == 200, setup.text
    secret = setup.json()["data"]["secret"]
    assert setup.json()["data"]["otpauth_uri"].startswith("otpauth://totp/Habeny%3A")
    resp = c.post("/users/me/2fa/enable", json={"code": totp.code_for(secret)})
    assert resp.status_code == 200, resp.text
    return secret, resp.json()["data"]["recovery_codes"]


def _password_step(app, name, pw):
    c = TestClient(app)
    resp = c.post("/auth/login", json={"username": name, "password": pw})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["mfa_required"] is True and "user" not in data
    return c, data["mfa_token"]


def _next_code(secret):
    """A valid code for a later time step than the one enrolment used."""
    return totp.code_for(secret, now=totp.current_step() * totp.PERIOD + totp.PERIOD)


def test_totp_matches_rfc6238_vector():
    # RFC 6238 appendix B, SHA-1, T=59 -> 94287082 (8 digits); we use the last 6
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"  # base32 of "12345678901234567890"
    assert totp.code_for(secret, now=59) == "287082"
    assert totp.code_for(secret, now=1111111109) == "081804"


def test_setup_needs_password_and_confirmation(user):
    c, _, _, pw = user
    assert c.post("/users/me/2fa/setup", json={"current_password": "wrong"}).status_code == 400
    secret = c.post("/users/me/2fa/setup", json={"current_password": pw}).json()["data"]["secret"]
    assert c.post("/users/me/2fa/enable", json={"code": "000000"}).status_code == 400
    # Not on until confirmed
    assert c.get("/users/me/2fa").json()["data"]["enabled"] is False
    assert c.post("/users/me/2fa/enable", json={"code": totp.code_for(secret)}).status_code == 200
    status = c.get("/users/me/2fa").json()["data"]
    assert status == {"enabled": True, "recovery_codes_left": totp.RECOVERY_CODE_COUNT}
    assert c.get("/auth/status").json()["data"]["user"]["totp_enabled"] is True


def test_sign_in_requires_the_code(app, user):
    c, _, name, pw = user
    secret, _ = _enroll(c, pw)

    anon, token = _password_step(app, name, pw)
    assert anon.get("/auth/status").json()["data"]["authenticated"] is False  # no session yet
    assert anon.post("/auth/login/2fa", json={"mfa_token": token, "code": "123456"}).status_code == 401
    resp = anon.post("/auth/login/2fa", json={"mfa_token": token, "code": _next_code(secret)})
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["user"]["username"] == name
    assert anon.get("/auth/status").json()["data"]["authenticated"] is True
    # The challenge is single-use
    assert anon.post("/auth/login/2fa", json={"mfa_token": token, "code": _next_code(secret)}).status_code == 401


def test_codes_cannot_be_replayed(app, user):
    c, _, name, pw = user
    secret, _ = _enroll(c, pw)
    code = _next_code(secret)
    first, token = _password_step(app, name, pw)
    assert first.post("/auth/login/2fa", json={"mfa_token": token, "code": code}).status_code == 200
    second, token = _password_step(app, name, pw)
    assert second.post("/auth/login/2fa", json={"mfa_token": token, "code": code}).status_code == 401


def test_recovery_codes_work_once(app, user):
    c, _, name, pw = user
    _, codes = _enroll(c, pw)
    anon, token = _password_step(app, name, pw)
    assert anon.post("/auth/login/2fa", json={"mfa_token": token, "code": codes[0].upper()}).status_code == 200
    assert anon.get("/users/me/2fa").json()["data"]["recovery_codes_left"] == totp.RECOVERY_CODE_COUNT - 1
    anon, token = _password_step(app, name, pw)
    assert anon.post("/auth/login/2fa", json={"mfa_token": token, "code": codes[0]}).status_code == 401


def test_challenge_dropped_after_too_many_wrong_codes(app, user):
    c, _, name, pw = user
    secret, _ = _enroll(c, pw)
    anon, token = _password_step(app, name, pw)
    for _ in range(totp.CHALLENGE_MAX_ATTEMPTS):
        assert anon.post("/auth/login/2fa", json={"mfa_token": token, "code": "000000"}).status_code == 401
    resp = anon.post("/auth/login/2fa", json={"mfa_token": token, "code": _next_code(secret)})
    assert resp.status_code == 401 and "expired" in resp.json()["detail"]


def test_regenerate_and_disable(app, user):
    c, _, name, pw = user
    secret, old = _enroll(c, pw)
    new = c.post("/users/me/2fa/recovery-codes", json={"current_password": pw}).json()["data"]["recovery_codes"]
    assert set(new).isdisjoint(old)
    assert c.post("/users/me/2fa/disable", json={"current_password": pw, "code": old[0]}).status_code == 400
    assert c.post("/users/me/2fa/disable", json={"current_password": pw, "code": new[0]}).status_code == 200
    # Back to password-only sign-in
    resp = TestClient(app).post("/auth/login", json={"username": name, "password": pw})
    assert resp.json()["data"]["user"]["username"] == name


def test_secret_is_not_exposed(client, user):
    c, uid, _, pw = user
    _enroll(c, pw)
    listed = next(u for u in client.get("/users").json()["data"]["users"] if u["id"] == uid)
    assert listed["totp_enabled"] is True
    assert not {"totp_secret", "recovery_codes", "totp_last_step"} & set(listed)


def test_admin_can_reset_two_factor(app, client, user):
    c, uid, name, pw = user
    _enroll(c, pw)
    assert c.delete(f"/users/{uid}/2fa").status_code == 403  # operators can't
    assert client.delete(f"/users/{uid}/2fa").status_code == 200
    assert c.get("/auth/status").json()["data"]["authenticated"] is False  # signed out everywhere
    resp = TestClient(app).post("/auth/login", json={"username": name, "password": pw})
    assert resp.json()["data"]["user"]["totp_enabled"] is False
