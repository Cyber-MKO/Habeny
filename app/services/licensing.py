"""
Per-server licenses, checked offline.

A license is a signed text file bound to one server:

    HBYL1.<payload, base64url JSON>.<Ed25519 signature, base64url>

The payload names the license, the customer, the server ID it's for, when it was issued
and when it expires (or null: perpetual), and optionally the most containers the server
may run. The signature covers "HBYL1.<payload>" and is checked with the public keys in
app/licensing_key.py; the vendor signs with the matching private key
(tools/license_tool.py), which never ships.

- The server ID is derived from /etc/machine-id (`habeny license request` prints it).
- With no public key built in, licensing is off and everything works (state "off").
- Without a valid license, a new install runs as a trial for TRIAL_DAYS from its first
  account.
- An expired license keeps working for GRACE_DAYS.
- After that, and when the trial ends, Habeny refuses new work: deployments, simulations,
  benchmarks and log uploads. Everything can still be viewed, and existing containers
  can still be started, stopped and deleted, so nothing is held hostage.

Like any offline check, this keeps honest customers honest. Someone with root on the
server and the source can defeat it, and the EULA is what covers that case.
"""
import base64
import binascii
import contextlib
import hashlib
import json
import logging
import os
import sqlite3
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from fastapi import HTTPException, status

from app import config, licensing_key

logger = logging.getLogger(__name__)

PREFIX = "HBYL1"
TRIAL_DAYS = 30
GRACE_DAYS = 14
WARN_DAYS = 30
MACHINE_ID_FILES = ["/etc/machine-id", "/var/lib/dbus/machine-id"]
_generated_id: str | None = None


class LicenseError(ValueError):
    pass


class LicenseRequired(HTTPException):
    def __init__(self, detail: str):
        super().__init__(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=detail)


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def license_path() -> Path:
    return config.DATA_DIR / "license.key"


# ── server ID ───────────────────────────────────────────────────────────

def _machine_id() -> str:
    for name in MACHINE_ID_FILES:
        with contextlib.suppress(OSError):
            value = Path(name).read_text().strip()
            if value:
                return value
    # No machine ID (rare: some minimal containers): use one kept with Habeny's data
    fallback = config.DATA_DIR / "server-id"
    with contextlib.suppress(OSError):
        value = fallback.read_text().strip()
        if value:
            return value
    global _generated_id
    if _generated_id is None:  # kept in memory too, in case the file can't be written
        _generated_id = uuid.uuid4().hex
        with contextlib.suppress(OSError):
            fallback.write_text(_generated_id + "\n")
    return _generated_id


def server_id() -> str:
    """This server's ID, e.g. 3F9A-0C21-77DE-B410-5A6E. A hash, so the machine ID stays private."""
    digest = hashlib.sha256(b"habeny-license:" + _machine_id().encode()).hexdigest()[:20].upper()
    return "-".join(digest[i:i + 4] for i in range(0, 20, 4))


# ── encoding and checking ───────────────────────────────────────────────

def _public_keys() -> list[Ed25519PublicKey]:
    keys = []
    for text in licensing_key.PUBLIC_KEYS:
        try:
            keys.append(Ed25519PublicKey.from_public_bytes(base64.b64decode(text)))
        except (ValueError, binascii.Error):
            logger.error("A public key in app/licensing_key.py is not a base64 Ed25519 key; ignoring it")
    return keys


def enforced() -> bool:
    return bool(licensing_key.PUBLIC_KEYS)


def _date(value: Any, name: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise LicenseError(f"The license's {name} date is invalid") from None


def _check_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("v") != 1:
        raise LicenseError("This license is for a different version of Habeny")
    for name in ("id", "customer", "server_id"):
        if not isinstance(payload.get(name), str) or not payload[name]:
            raise LicenseError(f"The license has no {name.replace('_', ' ')}")
    _date(payload.get("issued"), "issue")
    if payload.get("expires") is not None:
        _date(payload["expires"], "expiry")
    limit = payload.get("max_containers")
    if limit is not None and (not isinstance(limit, int) or isinstance(limit, bool) or limit < 1):
        raise LicenseError("The license's container limit is invalid")
    features = payload.get("features", [])
    if not isinstance(features, list) or not all(isinstance(f, str) for f in features):
        raise LicenseError("The license's feature list is invalid")
    return payload


def sign(private_key: Ed25519PrivateKey, payload: dict[str, Any]) -> str:
    """The license text for `payload`. Used by tools/license_tool.py and the tests."""
    _check_payload(payload)
    body = _b64encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    signature = private_key.sign(f"{PREFIX}.{body}".encode())
    return f"{PREFIX}.{body}.{_b64encode(signature)}"


def _token(text: str) -> str:
    """The license from a file's text: comment lines (#) and whitespace are ignored."""
    return "".join(line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith("#"))


def decode(text: str) -> dict[str, Any]:
    """The payload of a correctly signed license. Doesn't check the server or the dates."""
    parts = _token(text).split(".")
    if len(parts) != 3 or parts[0] != PREFIX:
        raise LicenseError("This isn't a Habeny license file")
    try:
        signature = _b64decode(parts[2])
        payload = json.loads(_b64decode(parts[1]))
    except (ValueError, binascii.Error):
        raise LicenseError("The license file is damaged") from None
    signed = f"{PREFIX}.{parts[1]}".encode()
    for key in _public_keys():
        try:
            key.verify(signature, signed)
            break
        except InvalidSignature:
            continue
    else:
        raise LicenseError("The license's signature doesn't match: it was changed, or it isn't from the Habeny vendor")
    return _check_payload(payload)


def _today() -> date:
    return datetime.now(timezone.utc).date()


def install(text: str) -> dict[str, Any]:
    """Check a license and make it this server's. Returns its payload."""
    if not enforced():
        raise LicenseError("Licensing is off in this build of Habeny, so there's nothing to install")
    payload = decode(text)
    if payload["server_id"] != server_id():
        raise LicenseError(f"This license is for server {payload['server_id']}; this server is {server_id()}")
    if payload.get("expires") and _date(payload["expires"], "expiry") + timedelta(days=GRACE_DAYS) < _today():
        raise LicenseError(f"This license expired on {payload['expires']}")
    path = license_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(f"# Habeny license {payload['id']} for {payload['customer']}\n{_token(text)}\n")
    os.chmod(tmp, 0o640)
    tmp.replace(path)
    logger.info("License installed", extra={"fields": {"license": payload["id"], "customer": payload["customer"]}})
    return payload


# ── state ───────────────────────────────────────────────────────────────

def _trial_start() -> date | None:
    """The trial starts with the first account (created at setup), so reinstalling the
    app doesn't restart it. None: no account yet."""
    try:
        conn = sqlite3.connect(config.DB_PATH, timeout=5)
        try:
            row = conn.execute("SELECT MIN(created_at) FROM users").fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    if not row or not row[0]:
        return None
    try:
        return datetime.fromisoformat(row[0]).date()
    except ValueError:
        return None


def status_info(today: date | None = None) -> dict[str, Any]:
    """Licensing state for the UI, the CLI and the checks.

    state: off | active | expiring | grace | expired | trial | trial_ended | invalid
    """
    today = today or _today()
    info: dict[str, Any] = {"enforced": enforced(), "server_id": server_id(), "license": None,
                            "days_left": None, "max_containers": None, "allows_new_work": True, "problem": None}
    if not info["enforced"]:
        return {**info, "state": "off", "message": "Licensing is off in this build"}

    payload, problem = None, None
    path = license_path()
    if path.exists():
        try:
            payload = decode(path.read_text())
            if payload["server_id"] != info["server_id"]:
                raise LicenseError(f"The installed license is for server {payload['server_id']}, not this one "
                                   f"({info['server_id']})")
        except (LicenseError, OSError) as e:
            payload, problem = None, str(e)

    if payload:
        expires = _date(payload["expires"], "expiry") if payload.get("expires") else None
        info["license"] = {k: payload.get(k) for k in ("id", "customer", "issued", "expires", "max_containers",
                                                        "features")}
        info["max_containers"] = payload.get("max_containers")
        if expires is None:
            return {**info, "state": "active", "message": f"Licensed to {payload['customer']}"}
        days_left = (expires - today).days
        info["days_left"] = days_left
        if days_left < 0:
            grace_left = GRACE_DAYS + days_left
            if grace_left >= 0:
                return {**info, "state": "grace",
                        "message": f"The license expired on {payload['expires']}. New work stops in "
                                   f"{grace_left} day{'s' if grace_left != 1 else ''}; renew it."}
            return {**info, "state": "expired", "allows_new_work": False,
                    "message": f"The license expired on {payload['expires']}. Viewing and managing existing "
                               "containers still work; install a renewed license to deploy and run tests."}
        if days_left <= WARN_DAYS:
            return {**info, "state": "expiring",
                    "message": f"The license expires on {payload['expires']} "
                               f"({days_left} day{'s' if days_left != 1 else ''} left)"}
        return {**info, "state": "active", "message": f"Licensed to {payload['customer']} until {payload['expires']}"}

    start = _trial_start() or today
    trial_left = (start + timedelta(days=TRIAL_DAYS) - today).days
    info["days_left"] = trial_left
    info["trial_ends"] = (start + timedelta(days=TRIAL_DAYS)).isoformat()
    if problem:
        info["problem"] = problem
    if trial_left >= 0:
        state = "invalid" if problem else "trial"
        message = (f"{problem}. " if problem else "") + \
            f"Trial: {trial_left} day{'s' if trial_left != 1 else ''} left. Install a license to keep deploying."
        return {**info, "state": state, "message": message}
    return {**info, "state": "invalid" if problem else "trial_ended", "allows_new_work": False,
            "message": (f"{problem}. " if problem else "The trial has ended. ") +
                       "Viewing and managing existing containers still work; install a license to deploy and "
                       "run tests."}


def require(adding: int = 0, existing: int = 0) -> None:
    """Refuse new work without a valid license (HTTP 402). `adding`/`existing`: containers,
    for the license's container limit."""
    if not enforced():
        return
    info = status_info()
    if not info["allows_new_work"]:
        raise LicenseRequired(info["message"])
    limit = info["max_containers"]
    if limit is not None and adding > 0 and existing + adding > limit:
        raise LicenseRequired(f"This server's license allows {limit} containers; there are {existing} and you "
                              f"asked for {adding} more.")


def check_alert() -> None:
    """Raise or clear the "license" alert. Called every minute with the other checks."""
    from app.services import alerts
    if not enforced():
        return
    info = status_info()
    if info["state"] in ("expired", "trial_ended") or (info["state"] == "invalid" and not info["allows_new_work"]):
        alerts.manager.fire("license", "critical", info["message"], link="/license")
    elif info["state"] in ("expiring", "grace", "invalid") or (info["state"] == "trial" and info["days_left"] <= 7):
        alerts.manager.fire("license", "warning", info["message"], link="/license")
    else:
        alerts.manager.clear("license", message=info["message"])
