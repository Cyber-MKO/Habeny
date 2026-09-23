"""
Password change and user management (admin only), including lockout guards.
"""
import uuid

import pytest
from fastapi.testclient import TestClient


def _new_name():
    return "u" + uuid.uuid4().hex[:8]


def _sign_in(app, username, password):
    c = TestClient(app)
    assert c.post("/auth/login", json={"username": username, "password": password}).status_code == 200
    return c


@pytest.fixture()
def member(app, client):
    """A non-admin user created by the admin; yields (id, username, password)."""
    name, pw = _new_name(), "member-password-1"
    user = client.post("/users", json={"username": name, "password": pw}).json()["data"]["user"]
    assert user["is_admin"] is False
    yield user["id"], name, pw
    client.delete(f"/users/{user['id']}")


def test_status_includes_admin_flag(client):
    assert client.get("/auth/status").json()["data"]["user"]["is_admin"] is True


def test_admin_lists_users(client):
    users = client.get("/users").json()["data"]["users"]
    assert any(u["username"] == "admin" and u["is_admin"] for u in users)
    assert all("password_hash" not in u for u in users)


def test_duplicate_username_rejected_case_insensitive(client, member):
    _, name, _ = member
    resp = client.post("/users", json={"username": name.upper(), "password": "whatever-123"})
    assert resp.status_code == 409


@pytest.mark.parametrize("body", [
    {"username": "ab", "password": "long-enough-1"},
    {"username": "-bad", "password": "long-enough-1"},
    {"username": "okname", "password": "short"},
])
def test_invalid_new_user_rejected(client, body):
    assert client.post("/users", json=body).status_code == 422


def test_non_admin_cannot_manage_users(app, member):
    uid, name, pw = member
    c = _sign_in(app, name, pw)
    assert c.get("/users").status_code == 403
    assert c.post("/users", json={"username": _new_name(), "password": "x" * 10}).status_code == 403
    assert c.delete(f"/users/{uid}").status_code == 403
    # ...but the rest of the app works for them
    assert c.get("/groups").status_code == 200


def test_change_own_password(app, member):
    _, name, pw = member
    c = _sign_in(app, name, pw)
    other_device = _sign_in(app, name, pw)
    assert c.post("/users/me/password", json={"current_password": "wrong", "new_password": "brand-new-pass"}).status_code == 400
    assert c.post("/users/me/password", json={"current_password": pw, "new_password": pw}).status_code == 400
    assert c.post("/users/me/password", json={"current_password": pw, "new_password": "brand-new-pass"}).status_code == 200
    assert c.get("/groups").status_code == 200                # this session keeps working
    assert other_device.get("/groups").status_code == 401     # other sessions are signed out
    assert TestClient(app).post("/auth/login", json={"username": name, "password": pw}).status_code == 401
    _sign_in(app, name, "brand-new-pass")


def test_admin_reset_password_signs_user_out(app, client, member):
    uid, name, pw = member
    theirs = _sign_in(app, name, pw)
    assert client.post(f"/users/{uid}/password", json={"new_password": "reset-by-admin"}).status_code == 200
    assert theirs.get("/groups").status_code == 401
    _sign_in(app, name, "reset-by-admin")


def test_promote_and_demote(app, client, member):
    uid, name, pw = member
    assert client.patch(f"/users/{uid}", json={"is_admin": True}).status_code == 200
    assert _sign_in(app, name, pw).get("/users").status_code == 200
    assert client.patch(f"/users/{uid}", json={"is_admin": False}).status_code == 200
    assert _sign_in(app, name, pw).get("/users").status_code == 403


def test_admin_cannot_delete_or_demote_self(client):
    me = client.get("/auth/status").json()["data"]["user"]
    assert client.delete(f"/users/{me['id']}").status_code == 400
    assert client.patch(f"/users/{me['id']}", json={"is_admin": False}).status_code == 400
    assert client.post(f"/users/{me['id']}/password", json={"new_password": "whatever-123"}).status_code == 400


def test_last_admin_cannot_be_removed(app, client, member):
    """Another admin can't delete or demote the only remaining admin."""
    uid, name, pw = member
    client.patch(f"/users/{uid}", json={"is_admin": True})
    second = _sign_in(app, name, pw)
    admin_id = client.get("/auth/status").json()["data"]["user"]["id"]
    # demote the member again from the admin side, leaving 'admin' as the only admin
    client.patch(f"/users/{uid}", json={"is_admin": False})
    assert second.delete(f"/users/{admin_id}").status_code == 403  # no longer admin
    # the DB-level guard, exercised directly
    from app.config import DB_PATH
    from app.db import delete_user, set_user_admin
    assert set_user_admin(DB_PATH, admin_id, False) is False
    assert delete_user(DB_PATH, admin_id) is False


def test_delete_user_revokes_sessions(app, client):
    name, pw = _new_name(), "doomed-password"
    uid = client.post("/users", json={"username": name, "password": pw}).json()["data"]["user"]["id"]
    theirs = _sign_in(app, name, pw)
    assert client.delete(f"/users/{uid}").status_code == 200
    assert theirs.get("/groups").status_code == 401
    assert client.delete(f"/users/{uid}").status_code == 404


def test_unknown_user_404(client):
    assert client.patch("/users/999999", json={"is_admin": True}).status_code == 404


def test_legacy_account_becomes_admin_on_migration(tmp_path):
    """Databases created before roles existed: the oldest account is promoted."""
    import sqlite3

    from app.db import init_db, list_users
    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL COLLATE NOCASE,"
                 " password_hash TEXT NOT NULL, created_at TEXT NOT NULL, last_login_at TEXT)")
    conn.execute("INSERT INTO users (username, password_hash, created_at) VALUES ('first', 'x', '2026-01-01'), ('second', 'x', '2026-01-02')")
    conn.commit()
    conn.close()
    init_db(db)
    init_db(db)  # idempotent
    roles = {u["username"]: u["is_admin"] for u in list_users(db)}
    assert roles == {"first": True, "second": False}
