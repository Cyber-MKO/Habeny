"""
Single sign-on (OIDC): the redirect, state/PKCE/nonce checks, ID token verification,
account linking and group-to-role mapping, against a fake identity provider.
"""
import base64
import hashlib
import time
import uuid
from urllib.parse import parse_qs, unquote, urlsplit

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.services import oidc

ISSUER = "https://idp.example.test"
CLIENT_ID = "habeny-test"


def _rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


class FakeIdP:
    def __init__(self):
        self.key = _rsa_key()
        self.kid = "k1"
        self.claims = {}
        self.token_requests = []
        self.overrides = {}  # claims to force into the next ID token (e.g. a bad nonce)
        self.sign_with = None

    def jwks(self):
        jwk = jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key(), as_dict=True)
        return {"keys": [{**jwk, "kid": self.kid, "use": "sig", "alg": "RS256"}]}

    def http_json(self, cfg, url, data=None, headers=None):
        if url == f"{ISSUER}/.well-known/openid-configuration":
            return {"issuer": ISSUER, "authorization_endpoint": f"{ISSUER}/authorize",
                    "token_endpoint": f"{ISSUER}/token", "jwks_uri": f"{ISSUER}/jwks",
                    "token_endpoint_auth_methods_supported": ["client_secret_basic"]}
        if url == f"{ISSUER}/jwks":
            return self.jwks()
        if url == f"{ISSUER}/token":
            self.token_requests.append({"data": data, "headers": headers})
            now = int(time.time())
            claims = {"iss": ISSUER, "aud": CLIENT_ID, "iat": now, "exp": now + 300,
                      "nonce": self.pending_nonce, **self.claims, **self.overrides}
            token = jwt.encode(claims, self.sign_with or self.key, algorithm="RS256", headers={"kid": self.kid})
            return {"access_token": "at", "token_type": "Bearer", "id_token": token}
        raise AssertionError(f"unexpected IdP request {url}")


@pytest.fixture()
def idp(monkeypatch, client):
    fake = FakeIdP()
    monkeypatch.setenv("HABENY_OIDC_ISSUER", ISSUER)
    monkeypatch.setenv("HABENY_OIDC_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("HABENY_OIDC_CLIENT_SECRET", "s3cret")
    monkeypatch.setattr(oidc, "_http_json", fake.http_json)
    oidc._cache.clear()
    yield fake
    oidc._cache.clear()
    for user in client.get("/users").json()["data"]["users"]:  # don't leave extra admins behind
        if user["sso"]:
            client.delete(f"/users/{user['id']}")


def _browser(app):
    c = TestClient(app)
    c.follow_redirects = False  # to see the redirects to/from the IdP
    return c


def _person(idp, **extra):
    name = "sso" + uuid.uuid4().hex[:8]
    idp.claims = {"sub": uuid.uuid4().hex, "preferred_username": f"{name}@corp.example", **extra}
    return f"{name}@corp.example"


def _start(app):
    """Begin SSO in a fresh browser; returns (client, authorize-URL query params)."""
    c = _browser(app)
    resp = c.get("/auth/oidc/login")
    assert resp.status_code == 303
    url = urlsplit(resp.headers["location"])
    assert f"{url.scheme}://{url.netloc}{url.path}" == f"{ISSUER}/authorize"
    return c, {k: v[0] for k, v in parse_qs(url.query).items()}


def _sign_in(app, idp):
    c, params = _start(app)
    idp.pending_nonce = params["nonce"]
    idp.last_authorize = params
    resp = c.get("/auth/oidc/callback", params={"state": params["state"], "code": "authcode"})
    return c, resp


def _error(resp):
    assert resp.status_code == 303
    location = resp.headers["location"]
    assert location.startswith("/?sso_error="), location
    return unquote(location.split("=", 1)[1])


def test_not_configured(app, admin_created, monkeypatch):
    monkeypatch.delenv("HABENY_OIDC_ISSUER", raising=False)
    c = _browser(app)
    assert c.get("/auth/status").json()["data"]["sso"] == {"enabled": False}
    assert c.get("/auth/oidc/login").status_code == 404


def test_status_advertises_sso(app, admin_created, idp, monkeypatch):
    monkeypatch.setenv("HABENY_OIDC_BUTTON_LABEL", "Sign in with Okta")
    sso = TestClient(app).get("/auth/status").json()["data"]["sso"]
    assert sso == {"enabled": True, "label": "Sign in with Okta"}


def test_authorize_request_uses_pkce_state_and_nonce(app, admin_created, idp):
    c, params = _start(app)
    assert params["response_type"] == "code" and params["client_id"] == CLIENT_ID
    assert params["redirect_uri"] == "http://testserver/api/auth/oidc/callback"
    assert params["code_challenge_method"] == "S256" and "openid" in params["scope"].split()
    assert len(params["state"]) >= 32 and len(params["nonce"]) >= 32
    assert c.cookies.get("habeny_oidc_state") == params["state"]


def test_first_sign_in_creates_a_viewer_and_reuses_it(app, admin_created, idp):
    username = _person(idp)
    c, resp = _sign_in(app, idp)
    assert resp.status_code == 303 and resp.headers["location"] == "/"
    me = c.get("/auth/status").json()["data"]["user"]
    assert me["username"] == username and me["role"] == "viewer" and me["sso"] is True

    # PKCE verifier and client authentication reached the token endpoint
    sent = idp.token_requests[-1]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(sent["data"]["code_verifier"].encode()).digest())
    assert sent["headers"]["Authorization"].startswith("Basic ")
    assert challenge.rstrip(b"=").decode() == idp.last_authorize["code_challenge"]
    assert sent["data"]["code"] == "authcode"

    c2, _ = _sign_in(app, idp)
    assert c2.get("/auth/status").json()["data"]["user"]["id"] == me["id"]


def test_callback_needs_the_browser_that_started_it(app, admin_created, idp):
    _person(idp)
    c, params = _start(app)
    other = _browser(app)  # no state cookie
    resp = other.get("/auth/oidc/callback", params={"state": params["state"], "code": "authcode"})
    assert "another browser" in _error(resp)
    assert other.get("/auth/status").json()["data"]["authenticated"] is False
    # and the state is single-use
    idp.pending_nonce = params["nonce"]
    assert "expired" in _error(c.get("/auth/oidc/callback", params={"state": params["state"], "code": "x"}))


@pytest.mark.parametrize("tamper,message", [
    ({"overrides": {"nonce": "attacker"}}, "nonce"),
    ({"overrides": {"aud": "some-other-app"}}, "audience"),
    ({"overrides": {"iss": "https://evil.example"}}, "issuer"),
    ({"overrides": {"exp": 1000}}, "expired"),
    ({"sign_with": _rsa_key()}, "Signature"),
])
def test_bad_id_tokens_are_refused(app, admin_created, idp, tamper, message):
    _person(idp)
    for attr, value in tamper.items():
        setattr(idp, attr, value)
    c, resp = _sign_in(app, idp)
    assert message.lower() in _error(resp).lower()
    assert c.get("/auth/status").json()["data"]["authenticated"] is False


def test_idp_error_is_shown(app, admin_created, idp):
    c, params = _start(app)
    resp = c.get("/auth/oidc/callback", params={"state": params["state"], "error": "access_denied",
                                                "error_description": "User cancelled"})
    assert "User cancelled" in _error(resp)
    # A crafted link (no sign-in in progress) can't put its text on the sign-in page
    resp = _browser(app).get("/auth/oidc/callback", params={"state": "x", "error": "e", "error_description": "Call 555"})
    assert "Call 555" not in _error(resp)


def test_never_links_to_an_existing_local_account(app, admin_created, idp):
    idp.claims = {"sub": uuid.uuid4().hex, "preferred_username": admin_created["username"]}
    c, resp = _sign_in(app, idp)
    assert "already exists" in _error(resp)
    assert c.get("/auth/status").json()["data"]["authenticated"] is False


def test_group_mapping_sets_and_updates_the_role(app, admin_created, idp, monkeypatch):
    monkeypatch.setenv("HABENY_OIDC_ADMIN_GROUPS", "habeny-admins")
    monkeypatch.setenv("HABENY_OIDC_OPERATOR_GROUPS", "soc-team,red-team")
    _person(idp, groups=["everyone", "red-team"])
    c, _ = _sign_in(app, idp)
    assert c.get("/auth/status").json()["data"]["user"]["role"] == "operator"
    idp.claims["groups"] = ["red-team", "habeny-admins"]
    c, _ = _sign_in(app, idp)
    assert c.get("/auth/status").json()["data"]["user"]["role"] == "admin"
    idp.claims["groups"] = ["everyone"]
    c, resp = _sign_in(app, idp)
    assert "isn't in a group" in _error(resp)


def test_sso_accounts_have_no_local_password_or_2fa(app, client, idp):
    _person(idp)
    c, _ = _sign_in(app, idp)
    uid = c.get("/auth/status").json()["data"]["user"]["id"]
    for path, body in [("/users/me/password", {"current_password": "!sso", "new_password": "x" * 16}),
                       ("/users/me/2fa/setup", {"current_password": "!sso"})]:
        resp = c.post(path, json=body)
        assert resp.status_code == 400 and "single sign-on" in resp.json()["detail"]
    resp = client.post(f"/users/{uid}/password", json={"new_password": "brand-new-password-9"})
    assert resp.status_code == 400
    # and the placeholder hash can't be used to sign in
    username = c.get("/auth/status").json()["data"]["user"]["username"]
    assert TestClient(app).post("/auth/login", json={"username": username, "password": "!sso"}).status_code == 401
