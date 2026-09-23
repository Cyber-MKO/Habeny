"""
Authentication: first-run setup, login/logout, and that the API and WebSockets require a session.
"""
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.services.auth import LoginRateLimiter, hash_password, verify_password


def test_password_hash_roundtrip():
    stored = hash_password("s3cret-pass")
    assert stored.startswith("scrypt$") and "s3cret-pass" not in stored
    assert verify_password("s3cret-pass", stored)
    assert not verify_password("wrong", stored)
    assert not verify_password("s3cret-pass", "garbage")


def test_status_reports_signed_out(app, admin_created):
    data = TestClient(app).get("/auth/status").json()["data"]
    assert data == {"setup_required": False, "authenticated": False, "user": None,
                    "sso": {"enabled": False}}


def test_setup_cannot_run_twice(app, admin_created):
    resp = TestClient(app).post("/auth/setup", json={"username": "intruder", "password": "another-password", "setup_token": "x"})
    assert resp.status_code == 409


@pytest.mark.parametrize("path", ["/groups", "/agents", "/api/system/health", "/agents/deploy/progress/x"])
def test_api_requires_session(app, admin_created, path):
    assert TestClient(app).get(path).status_code == 401


def test_post_requires_session(app, admin_created):
    assert TestClient(app).post("/groups", json={"name": "g1"}).status_code == 401


@pytest.mark.parametrize("path", ["/ws/metrics", "/ws/console/c1"])
def test_websockets_require_session(app, admin_created, path):
    with pytest.raises(WebSocketDisconnect) as exc, TestClient(app).websocket_connect(path):
        pass
    assert exc.value.code == 1008


def test_websocket_rejects_cross_site_origin(client):
    with pytest.raises(WebSocketDisconnect), client.websocket_connect(
        "/ws/metrics", headers={"origin": "http://evil.example"}
    ):
        pass


def test_websocket_accepts_signed_in_same_origin(client):
    with client.websocket_connect("/ws/metrics", headers={"origin": "http://testserver"}) as ws:
        assert "timestamp" in ws.receive_json()


def test_login_sets_httponly_cookie_and_grants_access(app, admin_created):
    c = TestClient(app)
    resp = c.post("/auth/login", json=admin_created)
    assert resp.status_code == 200
    cookie = resp.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert c.get("/groups").status_code == 200
    assert c.get("/auth/status").json()["data"]["user"]["username"] == "admin"


def test_username_is_case_insensitive(app, admin_created):
    assert TestClient(app).post("/auth/login", json={**admin_created, "username": "ADMIN"}).status_code == 200


def test_wrong_password_rejected(app, admin_created):
    resp = TestClient(app).post("/auth/login", json={"username": "admin", "password": "nope-nope"})
    assert resp.status_code == 401


def test_logout_revokes_session(client):
    assert client.get("/groups").status_code == 200
    token = client.cookies.get("habeny_session")
    assert client.post("/auth/logout").status_code == 200
    assert client.get("/groups").status_code == 401
    # the old token is dead server-side, not just removed from the browser
    replay = TestClient(client.app, cookies={"habeny_session": token})
    assert replay.get("/groups").status_code == 401


def test_browser_root_serves_ui_when_built(app, admin_created):
    from app.config import STATIC_DIR
    if not (STATIC_DIR / "index.html").is_file():
        pytest.skip("frontend not built")
    resp = TestClient(app).get("/", headers={"accept": "text/html"})
    assert resp.status_code == 200 and "<!DOCTYPE html>" in resp.text[:50]


def test_rate_limiter_blocks_after_max_failures():
    rl = LoginRateLimiter(max_failures=3, window=60)
    for _ in range(3):
        assert rl.retry_after("1.2.3.4") == 0
        rl.record_failure("1.2.3.4")
    assert rl.retry_after("1.2.3.4") > 0
    assert rl.retry_after("5.6.7.8") == 0
    rl.reset("1.2.3.4")
    assert rl.retry_after("1.2.3.4") == 0


def test_no_cross_origin_access_by_default(client):
    resp = client.get("/groups", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in {k.lower() for k in resp.headers}
    pre = client.options("/groups", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in {k.lower() for k in pre.headers}


def test_setup_requires_the_one_time_token(app, admin_created, monkeypatch, tmp_path):
    import app.routes.auth as auth_routes
    import app.services.setup_token as st

    monkeypatch.setattr(st, "TOKEN_FILE", tmp_path / "setup-token")
    monkeypatch.setattr(st, "count_users", lambda db: 0)
    token = st.ensure_setup_token()
    assert (tmp_path / "setup-token").stat().st_mode & 0o077 == 0
    assert st.ensure_setup_token() == token  # stable across restarts until used

    monkeypatch.setattr(auth_routes, "count_users", lambda db: 0)  # pretend no account exists yet
    c = TestClient(app)
    body = {"username": "claimer", "password": "a-long-enough-pass"}
    assert c.post("/auth/setup", json=body).status_code == 422  # token missing
    assert c.post("/auth/setup", json={**body, "setup_token": "guess"}).status_code == 403
    # the right token gets past the check (then 409: an account already exists in this test DB)
    assert c.post("/auth/setup", json={**body, "setup_token": token}).status_code == 409
