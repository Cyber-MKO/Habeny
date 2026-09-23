"""
Encryption at rest for stored secrets (SIEM auth keys / enrollment tokens).

Fernet (AES-128-CBC + HMAC-SHA256) from `cryptography`. The key comes from
HABENY_SECRET_KEY, or is generated once into DATA_DIR/secret.key (mode 0600).
This protects the database file (copies, backups, leaks); anyone who can read the
key file as well — e.g. root on this host — can still decrypt.
"""
import logging
import os
import threading
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from app.config import DATA_DIR

logger = logging.getLogger(__name__)

PREFIX = "enc:v1:"
KEY_FILE = DATA_DIR / "secret.key"

_fernet: Optional[Fernet] = None
_lock = threading.Lock()


def _load_key() -> bytes:
    env_key = os.environ.get("HABENY_SECRET_KEY")
    if env_key:
        return env_key.encode()
    try:
        return KEY_FILE.read_bytes().strip()
    except FileNotFoundError:
        pass
    KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    try:
        fd = os.open(KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:  # another process created it first
        return KEY_FILE.read_bytes().strip()
    with os.fdopen(fd, "wb") as f:
        f.write(key)
    logger.info(f"Generated secret key at {KEY_FILE}; back it up with the database")
    return key


def _cipher() -> Fernet:
    global _fernet
    with _lock:
        if _fernet is None:
            _fernet = Fernet(_load_key())
        return _fernet


def is_encrypted(value: Optional[str]) -> bool:
    return isinstance(value, str) and value.startswith(PREFIX)


def encrypt_secret(value: Optional[str]) -> Optional[str]:
    """Encrypt for storage. None/"" and already-encrypted values pass through."""
    if not value or is_encrypted(value):
        return value
    return PREFIX + _cipher().encrypt(value.encode()).decode()


def decrypt_secret(value: Optional[str]) -> Optional[str]:
    """Decrypt a stored value. Legacy plaintext passes through; an undecryptable value
    (wrong/lost key) returns None so callers ask for it to be re-entered."""
    if not is_encrypted(value):
        return value
    try:
        return _cipher().decrypt(value[len(PREFIX):].encode()).decode()
    except InvalidToken:
        logger.error("A stored secret could not be decrypted (secret key changed?); it must be re-entered")
        return None


def secret_hint(value: Optional[str]) -> Optional[str]:
    """Last 4 characters, for display ("••••abcd"); None when unset."""
    plain = decrypt_secret(value)
    if not plain:
        return None
    return "••••" + plain[-4:] if len(plain) > 8 else "••••"
