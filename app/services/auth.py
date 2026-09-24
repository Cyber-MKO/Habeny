"""
Authentication: password hashing, sessions, the login-required dependency and login rate limiting.
"""
import contextlib
import hashlib
import hmac
import secrets
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

from fastapi import Depends, HTTPException, WebSocketException, status
from starlette.requests import HTTPConnection

from app.config import DB_PATH, SESSION_COOKIE, SESSION_TTL_HOURS
from app.db import (
    create_session,
    delete_session,
    get_api_token_user,
    get_session_user,
    touch_api_token,
    touch_session,
)
from app.logging_config import request_context, set_request_user
from app.services import lifecycle

# scrypt parameters (~16 MiB memory per hash)
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2 ** 14, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P)
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_hex, digest_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=int(n), r=int(r), p=int(p))
        return hmac.compare_digest(digest.hex(), digest_hex)
    except ValueError:
        return False


# Verified against when the username doesn't exist, so response time doesn't reveal valid usernames
_DUMMY_HASH = hash_password(secrets.token_hex(16))


def check_credentials(user: dict[str, Any] | None, password: str) -> bool:
    if user is None:
        verify_password(password, _DUMMY_HASH)
        return False
    return verify_password(password, user["password_hash"])


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def client_ip(conn: HTTPConnection) -> str | None:
    return conn.client.host if conn.client else None


def start_session(user_id: int, conn: HTTPConnection | None = None) -> str:
    """Create a session and return its token (only the hash is stored)."""
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(hours=SESSION_TTL_HOURS)
    create_session(DB_PATH, token_hash(token), user_id, expires.isoformat(),
                   ip=client_ip(conn) if conn else None,
                   user_agent=conn.headers.get("user-agent") if conn else None)
    return token


def session_public_id(hashed: str) -> str:
    """Short handle for listing/revoking a session; can't be used to authenticate."""
    return hashed[:16]


TOUCH_INTERVAL = timedelta(seconds=60)


def end_session(token: str) -> None:
    delete_session(DB_PATH, token_hash(token))


# ── API tokens (scripts, CI, Prometheus, other Habeny consoles) ──────────
# "hby_" + 256 random bits. Only a SHA-256 hash is stored; the token is shown once.
API_TOKEN_PREFIX = "hby_"


def new_api_token() -> tuple[str, str]:
    """A new token and the short prefix kept for recognising it in lists."""
    token = API_TOKEN_PREFIX + secrets.token_urlsafe(32)
    return token, token[:12]


def bearer_token(conn: HTTPConnection) -> str | None:
    scheme, _, value = conn.headers.get("authorization", "").partition(" ")
    return value.strip() or None if scheme.lower() == "bearer" else None


def token_user(conn: HTTPConnection, token: str) -> dict[str, Any] | None:
    """The user an API token acts as. Its role is the lower of the token's and the account's,
    so demoting the account also limits its tokens."""
    user = get_api_token_user(DB_PATH, token_hash(token))
    if user is None:
        return None
    token_role = user.pop("token_role")
    user["role"] = min(token_role, user["role"], key=lambda r: _RANK.get(r, -1))
    user["auth"] = "token"
    seen = user.pop("token_last_used_at", None)
    now = datetime.now(timezone.utc)
    if not seen or now - datetime.fromisoformat(seen) > TOUCH_INTERVAL:
        with contextlib.suppress(Exception):  # "last used" is informational
            touch_api_token(DB_PATH, user["token_id"], client_ip(conn))
    return user


def session_user(conn: HTTPConnection) -> dict[str, Any] | None:
    """The signed-in user: from an `Authorization: Bearer` API token when one is sent,
    otherwise from the session cookie."""
    bearer = bearer_token(conn)
    if bearer is not None:
        return token_user(conn, bearer)
    token = conn.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    hashed = token_hash(token)
    user = get_session_user(DB_PATH, hashed)
    if user is not None:
        # "Last active" for the sessions list, written at most once a minute per session
        seen = user.pop("session_last_seen_at", None)
        now = datetime.now(timezone.utc)
        if not seen or now - datetime.fromisoformat(seen) > TOUCH_INTERVAL:
            with contextlib.suppress(Exception):  # "last active" is informational
                touch_session(DB_PATH, hashed, client_ip(conn))
        user["session_id"] = session_public_id(hashed)
        user["auth"] = "session"
    return user


def _same_origin(conn: HTTPConnection) -> bool:
    """Browsers always send Origin on WebSocket handshakes; reject ones from other sites."""
    origin = conn.headers.get("origin")
    if not origin:
        return True  # non-browser client; the session cookie is still required
    return urlparse(origin).netloc == conn.headers.get("host")


async def require_user(conn: HTTPConnection) -> dict[str, Any]:
    """Dependency for every protected HTTP route and WebSocket."""
    user = session_user(conn)
    if user is not None:
        conn.state.user = user  # for routes: Depends(current_user)
        set_request_user(user["username"])  # for this request's log lines
        ctx = request_context.get()
        if ctx is not None and user.get("auth") == "token":
            ctx["token"] = user["token_name"]  # recorded with the audit entry
    if conn.scope["type"] == "websocket":
        if user is None or not _same_origin(conn):
            raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason="Not authenticated")
    elif user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return user


class LoginRateLimiter:
    """Allow at most `max_failures` failed logins per client IP within `window` seconds."""

    def __init__(self, max_failures: int = 10, window: int = 15 * 60):
        self.max_failures = max_failures
        self.window = window
        self._failures: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, key: str) -> deque[float]:
        q = self._failures.setdefault(key, deque())
        cutoff = time.monotonic() - self.window
        while q and q[0] < cutoff:
            q.popleft()
        return q

    def retry_after(self, key: str) -> int:
        """Seconds until another attempt is allowed (0 if allowed now)."""
        with self._lock:
            q = self._recent(key)
            if len(q) < self.max_failures:
                return 0
            return max(1, int(q[0] + self.window - time.monotonic()))

    def record_failure(self, key: str) -> None:
        with self._lock:
            self._recent(key).append(time.monotonic())

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)


login_limiter = LoginRateLimiter()


# ── roles ───────────────────────────────────────────────────────────────
# viewer: read-only · operator: + containers, simulations, console, profiles · admin: + users
ROLES = ("viewer", "operator", "admin")
_RANK = {role: i for i, role in enumerate(ROLES)}
# POST endpoints that only read (safe for viewers)
READ_ONLY_POSTS = {"/benchmarks/compare"}


def has_role(user: dict[str, Any], minimum: str) -> bool:
    return _RANK.get(user.get("role"), -1) >= _RANK[minimum]


def _forbidden(conn: HTTPConnection, needed: str):
    if conn.scope["type"] == "websocket":
        return WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason=f"{needed} role required")
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"This needs the {needed} role")


async def require_access(conn: HTTPConnection) -> dict[str, Any]:
    """Router-wide check: signed in, and the role the request needs. Reads (GET, the live
    metrics socket) are open to viewers; anything that changes something, and the
    container console, needs operator."""
    user = await require_user(conn)
    path = conn.scope.get("path", "")
    if conn.scope["type"] == "websocket":
        needed = "operator" if path.startswith("/ws/console") else "viewer"
    elif conn.scope.get("method") in ("GET", "HEAD", "OPTIONS") or path in READ_ONLY_POSTS:
        needed = "viewer"
    else:
        needed = "operator"
    if not has_role(user, needed):
        raise _forbidden(conn, needed)
    if needed == "operator" and lifecycle.shutting_down():
        # Don't start work that a restart would cut short
        if conn.scope["type"] == "websocket":
            raise WebSocketException(code=status.WS_1012_SERVICE_RESTART, reason="Habeny is restarting")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, headers={"Retry-After": "60"},
                            detail="Habeny is restarting. Try again in a minute.")
    return user


def current_user(conn: HTTPConnection) -> dict[str, Any] | None:
    """The signed-in user of this request (set by the router-wide access check)."""
    return getattr(conn.state, "user", None)


async def require_session(user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    """For changes to the account itself (password, two-factor, sessions, API tokens):
    only from a signed-in browser session, never with an API token."""
    if user.get("auth") == "token":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Account settings can't be changed with an API token; sign in instead")
    return user


async def require_admin(user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    if not has_role(user, "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrator access required")
    return user
