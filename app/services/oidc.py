"""
Single sign-on with OpenID Connect (Microsoft Entra ID, Okta, Google Workspace, Keycloak,
Authentik, ...): the authorization code flow with PKCE, ID token verification, and
mapping IdP users and groups to Habeny accounts and roles.

Configured with HABENY_OIDC_* environment variables (see README); off unless
HABENY_OIDC_ISSUER is set.
"""
import base64
import hashlib
import json
import re
import secrets
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Optional

import jwt

from app import config

HTTP_TIMEOUT = 10
FLOW_TTL = 10 * 60  # seconds a user has to finish signing in at the IdP
METADATA_TTL = 60 * 60
ROLES = ("viewer", "operator", "admin")
# SSO usernames may be emails (preferred_username often is)
SSO_USERNAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@+-]{0,63}$")


class OIDCError(Exception):
    """A sign-in that must be refused; the message is safe to show the user."""


@dataclass
class Settings:
    issuer: str
    client_id: str
    client_secret: str
    redirect_uri: str  # empty: derived from the request
    scopes: str
    username_claim: str
    groups_claim: str
    role_groups: dict[str, set[str]] = field(default_factory=dict)
    default_role: str = "viewer"
    label: str = "Sign in with SSO"
    ca_bundle: str = ""

    @property
    def group_mapping(self) -> bool:
        return any(self.role_groups.values())


def settings() -> Optional[Settings]:
    """Current SSO settings (see app/config.py), or None when SSO is off."""
    issuer = config.get("HABENY_OIDC_ISSUER").rstrip("/")
    if not issuer:
        return None
    client_id = config.get("HABENY_OIDC_CLIENT_ID")
    if not client_id:
        raise config.ConfigError("HABENY_OIDC_ISSUER is set but HABENY_OIDC_CLIENT_ID is not")
    return Settings(
        issuer=issuer,
        client_id=client_id,
        client_secret=config.raw("HABENY_OIDC_CLIENT_SECRET"),
        redirect_uri=config.get("HABENY_OIDC_REDIRECT_URI"),
        scopes=config.get("HABENY_OIDC_SCOPES"),
        username_claim=config.get("HABENY_OIDC_USERNAME_CLAIM"),
        groups_claim=config.get("HABENY_OIDC_GROUPS_CLAIM"),
        role_groups={role: set(config.get(f"HABENY_OIDC_{role.upper()}_GROUPS")) for role in ROLES},
        default_role=config.get("HABENY_OIDC_DEFAULT_ROLE"),
        label=config.get("HABENY_OIDC_BUTTON_LABEL"),
        ca_bundle=config.get("HABENY_OIDC_CA_BUNDLE"),
    )


# ── HTTP ────────────────────────────────────────────────────────────────

def _ssl_context(cfg: Settings) -> ssl.SSLContext:
    return ssl.create_default_context(cafile=cfg.ca_bundle or None)


def _http_json(cfg: Settings, url: str, data: Optional[dict] = None, headers: Optional[dict] = None) -> dict:
    if urllib.parse.urlsplit(url).scheme != "https" and not config.get("HABENY_OIDC_ALLOW_HTTP"):
        raise OIDCError(f"Refusing non-HTTPS identity provider URL: {url}")
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers={"Accept": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT, context=_ssl_context(cfg)) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        detail = e.read()[:300].decode(errors="replace")
        raise OIDCError(f"Identity provider returned HTTP {e.code}: {detail}") from e
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        raise OIDCError(f"Couldn't reach the identity provider: {e}") from e


_cache: dict[str, tuple[float, Any]] = {}
_cache_lock = threading.Lock()


def _cached(key: str, loader, ttl: float = METADATA_TTL):
    with _cache_lock:
        hit = _cache.get(key)
        if hit and hit[0] > time.monotonic():
            return hit[1]
    value = loader()
    with _cache_lock:
        _cache[key] = (time.monotonic() + ttl, value)
    return value


def metadata(cfg: Settings) -> dict:
    def load():
        meta = _http_json(cfg, f"{cfg.issuer}/.well-known/openid-configuration")
        if meta.get("issuer", "").rstrip("/") != cfg.issuer:
            raise OIDCError(f"Issuer mismatch: discovery says {meta.get('issuer')!r}, expected {cfg.issuer!r}")
        return meta
    return _cached(f"meta:{cfg.issuer}", load)


def _signing_key(cfg: Settings, token: str):
    kid = jwt.get_unverified_header(token).get("kid")
    for refresh in (False, True):  # the IdP may have rotated keys since we cached them
        key = f"jwks:{cfg.issuer}"
        if refresh:
            with _cache_lock:
                _cache.pop(key, None)
        jwks = _cached(key, lambda: _http_json(cfg, metadata(cfg)["jwks_uri"]))
        for jwk in jwks.get("keys", []):
            if jwk.get("use", "sig") == "sig" and (kid is None or jwk.get("kid") == kid):
                return jwt.PyJWK(jwk).key
    raise OIDCError("The identity provider's signing key for this token wasn't found")


# ── the sign-in flow ────────────────────────────────────────────────────

class FlowStore:
    """Pending sign-ins (state -> nonce, PKCE verifier), kept in memory for a few minutes."""

    def __init__(self):
        self._items: dict[str, dict] = {}
        self._lock = threading.Lock()

    def create(self, redirect_uri: str) -> dict:
        flow = {
            "state": secrets.token_urlsafe(32),
            "nonce": secrets.token_urlsafe(32),
            "verifier": secrets.token_urlsafe(64),
            "redirect_uri": redirect_uri,
            "expires": time.monotonic() + FLOW_TTL,
        }
        with self._lock:
            now = time.monotonic()
            self._items = {k: v for k, v in self._items.items() if v["expires"] > now}
            self._items[flow["state"]] = flow
        return flow

    def pop(self, state: str) -> Optional[dict]:
        with self._lock:
            flow = self._items.pop(state, None)
        return flow if flow and flow["expires"] > time.monotonic() else None


flows = FlowStore()


def _pkce_challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def authorization_url(cfg: Settings, flow: dict) -> str:
    params = {
        "response_type": "code",
        "client_id": cfg.client_id,
        "redirect_uri": flow["redirect_uri"],
        "scope": cfg.scopes,
        "state": flow["state"],
        "nonce": flow["nonce"],
        "code_challenge": _pkce_challenge(flow["verifier"]),
        "code_challenge_method": "S256",
    }
    endpoint = metadata(cfg)["authorization_endpoint"]
    return f"{endpoint}{'&' if '?' in endpoint else '?'}{urllib.parse.urlencode(params)}"


def exchange_code(cfg: Settings, flow: dict, code: str) -> dict:
    """Trade the authorization code for tokens and return the verified ID token claims."""
    meta = metadata(cfg)
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": flow["redirect_uri"],
        "code_verifier": flow["verifier"],
        "client_id": cfg.client_id,
    }
    headers = {}
    if cfg.client_secret:
        methods = meta.get("token_endpoint_auth_methods_supported") or ["client_secret_basic"]
        if "client_secret_basic" in methods:
            creds = f"{urllib.parse.quote(cfg.client_id, safe='')}:{urllib.parse.quote(cfg.client_secret, safe='')}"
            headers["Authorization"] = "Basic " + base64.b64encode(creds.encode()).decode()
        else:
            data["client_secret"] = cfg.client_secret
    tokens = _http_json(cfg, meta["token_endpoint"], data=data, headers=headers)
    id_token = tokens.get("id_token")
    if not id_token:
        raise OIDCError("The identity provider didn't return an ID token (is the 'openid' scope requested?)")
    return verify_id_token(cfg, id_token, flow["nonce"])


def verify_id_token(cfg: Settings, id_token: str, nonce: str) -> dict:
    try:
        claims = jwt.decode(
            id_token,
            _signing_key(cfg, id_token),
            algorithms=["RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512", "EdDSA"],
            audience=cfg.client_id,
            issuer=metadata(cfg)["issuer"],
            leeway=60,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
    except jwt.PyJWTError as e:
        raise OIDCError(f"Invalid ID token: {e}") from e
    if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
        raise OIDCError("Invalid ID token: nonce mismatch")
    return claims


# ── IdP identity -> Habeny account ──────────────────────────────────────

def subject_key(cfg: Settings, claims: dict) -> str:
    """Stable identity for linking: the issuer plus its subject id (usernames can change)."""
    return f"{cfg.issuer}|{claims['sub']}"


def username_from(cfg: Settings, claims: dict) -> str:
    name = claims.get(cfg.username_claim) or claims.get("email") or ""
    if not isinstance(name, str) or not SSO_USERNAME.match(name):
        raise OIDCError(f"The identity provider's '{cfg.username_claim}' claim isn't a usable username")
    return name


def role_from(cfg: Settings, claims: dict) -> Optional[str]:
    """Role from group membership when group mapping is configured (highest wins; None if
    in no mapped group). Without group mapping, None: the caller uses the default role."""
    if not cfg.group_mapping:
        return None
    groups = claims.get(cfg.groups_claim) or []
    if isinstance(groups, str):
        groups = [groups]
    groups = {str(g) for g in groups}
    for role in reversed(ROLES):
        if groups & cfg.role_groups[role]:
            return role
    raise OIDCError("Your account isn't in a group that's allowed to use Habeny. Ask your administrator.")
