"""
One-time token that protects first-run setup: without it, whoever reaches the server
first could create the admin account. Only someone with access to the server (its log
or data directory) can read the token.
"""
import contextlib
import hmac
import logging
import os
import secrets

from app.config import DATA_DIR, DB_PATH
from app.db import count_users

logger = logging.getLogger(__name__)

TOKEN_FILE = DATA_DIR / "setup-token"


def ensure_setup_token() -> str | None:
    """Create (once) and announce the setup token while no account exists."""
    if count_users(DB_PATH) > 0:
        remove_setup_token()
        return None
    try:
        token = TOKEN_FILE.read_text().strip()
    except FileNotFoundError:
        token = None
    if not token:
        token = secrets.token_urlsafe(18)
        fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(token + "\n")
    logger.warning(f"First-run setup: no account exists yet. Setup token: {token} (also in {TOKEN_FILE})")
    return token


def check_setup_token(candidate: str) -> bool:
    try:
        expected = TOKEN_FILE.read_text().strip()
    except FileNotFoundError:
        return False
    return bool(expected) and hmac.compare_digest(candidate.strip().encode(), expected.encode())


def remove_setup_token() -> None:
    with contextlib.suppress(FileNotFoundError):
        TOKEN_FILE.unlink()
