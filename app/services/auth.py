"""
Authentication: password hashing, sessions, the login-required dependency and login rate limiting.
"""
import hashlib
import hmac
import secrets
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

from fastapi import HTTPException, WebSocketException, status
from starlette.requests import HTTPConnection

from app.config import DB_PATH, SESSION_COOKIE, SESSION_TTL_HOURS
from app.db import create_session, delete_session, get_session_user

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


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def start_session(user_id: int) -> str:
    """Create a session and return its token (only the hash is stored)."""
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(hours=SESSION_TTL_HOURS)
    create_session(DB_PATH, _token_hash(token), user_id, expires.isoformat())
    return token


def end_session(token: str) -> None:
    delete_session(DB_PATH, _token_hash(token))


def session_user(conn: HTTPConnection) -> dict[str, Any] | None:
    token = conn.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    return get_session_user(DB_PATH, _token_hash(token))


def _same_origin(conn: HTTPConnection) -> bool:
    """Browsers always send Origin on WebSocket handshakes; reject ones from other sites."""
    origin = conn.headers.get("origin")
    if not origin:
        return True  # non-browser client; the session cookie is still required
    return urlparse(origin).netloc == conn.headers.get("host")


async def require_user(conn: HTTPConnection) -> dict[str, Any]:
    """Dependency for every protected HTTP route and WebSocket."""
    user = session_user(conn)
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
