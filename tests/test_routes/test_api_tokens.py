"""
API tokens: `Authorization: Bearer` access for scripts and CI.
"""
import uuid

import pytest
from fastapi.testclient import TestClient


def _new_name():
    return "t" + uuid.uuid4().hex[:8]


def _bearer(app, token):
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


@pytest.fixture()
def operator(app, client):
    """An operator account, signed in; yields (id, signed-in client)."""
    name, pw = _new_name(), "operator-password-1"
    user = client.post("/users", json={"username": name, "password": pw, "role": "operator"}).json()["data"]["user"]
    c = TestClient(app)
    assert c.post("/auth/login", json={"username": name, "password": pw}).status_code == 200
    yield user["id"], c
    client.delete(f"/users/{user['id']}")


def test_create_use_and_revoke(app, client):
    resp = client.post("/users/me/tokens", json={"name": "ci pipeline", "role": "viewer"})
    assert resp.status_code == 200, resp.text
    token, info = resp.json()["data"]["token"], resp.json()["data"]["info"]
    assert token.startswith("hby_") and info["prefix"] == token[:12] and info["role"] == "viewer"
    assert info["expires_at"]  # 90 days by default

    listed = client.get("/users/me/tokens").json()["data"]["tokens"]
    assert [t["name"] for t in listed if t["id"] == info["id"]] == ["ci pipeline"]
    assert all("token" not in t and "token_hash" not in t for t in listed)

    bot = _bearer(app, token)
    status = bot.get("/auth/status").json()["data"]
    assert status["user"]["username"] == "admin" and status["user"]["role"] == "viewer"
    assert bot.get("/agents").status_code == 200
    assert bot.get("/users/me/tokens").status_code == 403  # account settings need a browser session
    assert [t["last_used_at"] for t in client.get("/users/me/tokens").json()["data"]["tokens"]
            if t["id"] == info["id"]][0]

    assert client.delete(f"/users/me/tokens/{info['id']}").status_code == 200
    assert bot.get("/agents").status_code == 401


def test_token_role_limits_what_it_can_do(app, client):
    token = client.post("/users/me/tokens", json={"name": "read-only"}).json()["data"]["token"]
    viewer_token = client.post("/users/me/tokens", json={"name": "viewer", "role": "viewer"}).json()["data"]["token"]
    assert _bearer(app, token).get("/users").status_code == 200  # admin token (the account's role)
    viewer = _bearer(app, viewer_token)
    assert viewer.get("/users").status_code == 403
    assert viewer.post("/groups", json={"name": _new_name()}).status_code == 403  # changes need operator


def test_token_cannot_exceed_the_account_role(app, operator):
    _, c = operator
    assert c.post("/users/me/tokens", json={"name": "x", "role": "admin"}).status_code == 403
    assert c.post("/users/me/tokens", json={"name": "x", "role": "operator"}).status_code == 200


def test_demoting_the_account_limits_its_tokens(app, client, operator):
    user_id, c = operator
    token = c.post("/users/me/tokens", json={"name": "deploys"}).json()["data"]["token"]
    bot = _bearer(app, token)
    group = _new_name()
    assert bot.post("/groups", json={"name": group}).status_code == 200
    assert client.patch(f"/users/{user_id}", json={"role": "viewer"}).status_code == 200
    assert bot.post("/groups", json={"name": _new_name()}).status_code == 403
    client.delete(f"/groups/{group}")


def test_deleting_the_user_removes_their_tokens(app, client):
    name, pw = _new_name(), "someone-password-1"
    user = client.post("/users", json={"username": name, "password": pw}).json()["data"]["user"]
    c = TestClient(app)
    c.post("/auth/login", json={"username": name, "password": pw})
    token = c.post("/users/me/tokens", json={"name": "x"}).json()["data"]["token"]
    assert _bearer(app, token).get("/agents").status_code == 200
    client.delete(f"/users/{user['id']}")
    assert _bearer(app, token).get("/agents").status_code == 401


def test_admin_lists_and_revokes_any_token(app, client, operator):
    _, c = operator
    info = c.post("/users/me/tokens", json={"name": "theirs"}).json()["data"]["info"]
    everyone = client.get("/users/tokens").json()["data"]["tokens"]
    assert any(t["id"] == info["id"] and t["username"] for t in everyone)
    assert c.get("/users/tokens").status_code == 403
    assert client.delete(f"/users/tokens/{info['id']}").status_code == 200
    assert client.delete(f"/users/tokens/{info['id']}").status_code == 404


def test_expired_and_bad_tokens_are_rejected(app, client):
    from app.config import DB_PATH
    from app.db import _connection
    info = client.post("/users/me/tokens", json={"name": "short-lived", "expires_in_days": 1}).json()["data"]
    with _connection(DB_PATH) as conn:
        conn.execute("UPDATE api_tokens SET expires_at = '2000-01-01T00:00:00+00:00' WHERE id = ?", (info["info"]["id"],))
        conn.commit()
    assert _bearer(app, info["token"]).get("/agents").status_code == 401
    assert _bearer(app, "hby_not-a-real-token").get("/agents").status_code == 401
    # A bearer header wins over the session cookie: a bad token isn't rescued by a login
    client.headers["Authorization"] = "Bearer hby_nope"
    assert client.get("/agents").status_code == 401


def test_never_expiring_token(client):
    info = client.post("/users/me/tokens", json={"name": "forever", "expires_in_days": None}).json()["data"]["info"]
    assert info["expires_at"] is None
    client.delete(f"/users/me/tokens/{info['id']}")


def test_token_actions_are_audited(app, client):
    token = client.post("/users/me/tokens", json={"name": "audited"}).json()["data"]["token"]
    group = _new_name()
    _bearer(app, token).post("/groups", json={"name": group})
    logs = client.get("/activity/logs", params={"action": "group_created"}).json()["data"]["logs"]
    entry = next(e for e in logs if e["details"].get("name") == group or e["details"].get("group") == group)
    assert entry["user"] == "admin" and entry.get("token") == "audited"
    client.delete(f"/groups/{group}")
