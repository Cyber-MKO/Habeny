"""
Two-factor authentication: TOTP (RFC 6238, the codes authenticator apps show), one-time
recovery codes, and the short-lived challenge between the password and the code at sign-in.
"""
import base64
import hashlib
import hmac
import json
import secrets
import struct
import threading
import time
from urllib.parse import quote, urlencode

from app.config import DB_PATH
from app.core.secrets import decrypt_secret
from app.db import claim_totp_step, use_recovery_code

ISSUER = "Habeny"
DIGITS = 6
PERIOD = 30
DRIFT_STEPS = 1  # accept the previous/next code too, for clock skew
RECOVERY_CODE_COUNT = 10


def new_secret() -> str:
    """A random 160-bit secret, base32 as authenticator apps expect."""
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _code_at(secret: str, step: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10 ** DIGITS).zfill(DIGITS)


def current_step(now: float | None = None) -> int:
    return int((time.time() if now is None else now) // PERIOD)


def code_for(secret: str, now: float | None = None) -> str:
    return _code_at(secret, current_step(now))


def matching_step(secret: str, code: str, last_step: int | None = None,
                  now: float | None = None) -> int | None:
    """The time step `code` is valid for, or None. Steps at or before `last_step`
    (already used) are refused, so a code can't be replayed."""
    code = "".join(code.split())
    if len(code) != DIGITS or not code.isdigit():
        return None
    step = current_step(now)
    for candidate in range(step - DRIFT_STEPS, step + DRIFT_STEPS + 1):
        if last_step is not None and candidate <= last_step:
            continue
        if hmac.compare_digest(_code_at(secret, candidate), code):
            return candidate
    return None


def provisioning_uri(secret: str, username: str) -> str:
    label = quote(f"{ISSUER}:{username}")
    params = urlencode({"secret": secret, "issuer": ISSUER, "algorithm": "SHA1",
                        "digits": DIGITS, "period": PERIOD})
    return f"otpauth://totp/{label}?{params}"


# ── recovery codes ──────────────────────────────────────────────────────

_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no 0/o, 1/l/i


def _normalize_recovery(code: str) -> str:
    return "".join(ch for ch in code.lower() if ch.isalnum())


def hash_recovery_code(code: str) -> str:
    # 50 bits of randomness each and single use, so a fast hash is enough
    return hashlib.sha256(_normalize_recovery(code).encode()).hexdigest()


def new_recovery_codes() -> list[str]:
    codes = []
    for _ in range(RECOVERY_CODE_COUNT):
        raw = "".join(secrets.choice(_ALPHABET) for _ in range(10))
        codes.append(f"{raw[:5]}-{raw[5:]}")
    return codes


def looks_like_recovery_code(code: str) -> bool:
    return len(_normalize_recovery(code)) == 10


# ── sign-in challenges ──────────────────────────────────────────────────

CHALLENGE_TTL = 5 * 60
CHALLENGE_MAX_ATTEMPTS = 5


class ChallengeStore:
    """Password accepted, code pending. Kept in memory: a restart just means signing in again."""

    def __init__(self):
        self._items: dict[str, dict] = {}
        self._lock = threading.Lock()

    def create(self, user_id: int) -> str:
        token = secrets.token_urlsafe(32)
        now = time.monotonic()
        with self._lock:
            self._items = {k: v for k, v in self._items.items() if v["expires"] > now}
            self._items[token] = {"user_id": user_id, "expires": now + CHALLENGE_TTL, "attempts": 0}
        return token

    def user_for(self, token: str) -> int | None:
        with self._lock:
            item = self._items.get(token)
            if not item or item["expires"] <= time.monotonic():
                self._items.pop(token, None)
                return None
            return item["user_id"]

    def failed(self, token: str) -> None:
        """Count a wrong code; the challenge is dropped after too many."""
        with self._lock:
            item = self._items.get(token)
            if item:
                item["attempts"] += 1
                if item["attempts"] >= CHALLENGE_MAX_ATTEMPTS:
                    self._items.pop(token, None)

    def finish(self, token: str) -> None:
        with self._lock:
            self._items.pop(token, None)


challenges = ChallengeStore()


# ── checking a user's second factor ─────────────────────────────────────

def check_second_factor(user: dict, code: str) -> str | None:
    """Verify an authenticator code or an unused recovery code for a user with 2FA on.
    Returns "totp" or "recovery" (and marks it used), or None."""
    if not user.get("totp_enabled") or not user.get("totp_secret"):
        return None
    code = (code or "").strip()
    if looks_like_recovery_code(code):
        return "recovery" if use_recovery_code(DB_PATH, user["id"], hash_recovery_code(code)) else None
    step = matching_step(decrypt_secret(user["totp_secret"]), code, user.get("totp_last_step"))
    if step is not None and claim_totp_step(DB_PATH, user["id"], step):
        return "totp"
    return None


def recovery_codes_left(user: dict) -> int:
    return len(json.loads(user["recovery_codes"])) if user.get("recovery_codes") else 0
