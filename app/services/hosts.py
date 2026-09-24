"""
Other Habeny servers ("hosts") managed from this console.

Each LXC host runs its own Habeny. This console keeps, per host, its URL and an API token
created on that host (Account → API tokens there), and relays the UI's API calls and
WebSockets to it (/hosts/{id}/api/..., /hosts/{id}/ws/...). What you can do on a host is
what that token's role allows there, and never more than your own role here.

TLS: a host with a certificate from a trusted CA is verified normally. A host with
Habeny's self-signed certificate is pinned instead: its SHA-256 fingerprint is shown when
it's added, confirmed by the admin, and every connection must present that certificate.
"""
import contextlib
import hashlib
import http.client
import json
import socket
import sqlite3
import ssl
from typing import Any
from urllib.parse import urlencode, urlsplit

from app import config
from app.core.secrets import decrypt_secret, encrypt_secret
from app.models import utc_now

TIMEOUT = 15
MAX_BODY = 64 * 1024 * 1024
# Account and console administration stay on each server itself
LOCAL_ONLY = ("auth", "users", "hosts", "teams", "notifications", "system/backups")


class HostError(RuntimeError):
    pass


class FingerprintNeeded(HostError):
    def __init__(self, fingerprint: str):
        super().__init__("The host's certificate isn't from a trusted authority. Check this fingerprint on the host "
                         f"(`habeny tls fingerprint` there) and confirm it: {fingerprint}")
        self.fingerprint = fingerprint


def _conn():
    conn = sqlite3.connect(config.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def normalize_url(url: str) -> str:
    url = url.strip().rstrip("/")
    parts = urlsplit(url)
    if parts.scheme not in ("https", "http") or not parts.hostname:
        raise HostError("URL: https://host:port of the other Habeny")
    if parts.path not in ("", "/api"):
        raise HostError("URL: just https://host:port, without a path")
    return f"{parts.scheme}://{parts.netloc}"


# ── connections ─────────────────────────────────────────────────────────

def _fingerprint(der: bytes) -> str:
    digest = hashlib.sha256(der).hexdigest().upper()
    return ":".join(digest[i:i + 2] for i in range(0, 64, 2))


def _open(url: str, fingerprint: str | None) -> http.client.HTTPConnection:
    """Connected, with the certificate checked: pinned when a fingerprint is given, else by CA."""
    parts = urlsplit(url)
    if parts.scheme == "http":
        conn = http.client.HTTPConnection(parts.hostname, parts.port or 80, timeout=TIMEOUT)
        conn.connect()
        return conn
    if fingerprint:
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE  # replaced by the fingerprint check below
    else:
        context = ssl.create_default_context()
    conn = http.client.HTTPSConnection(parts.hostname, parts.port or 443, timeout=TIMEOUT, context=context)
    try:
        conn.connect()
    except ssl.SSLCertVerificationError:
        # Not CA-signed: find its fingerprint for the admin to confirm
        raise FingerprintNeeded(peer_fingerprint(url)) from None
    except (OSError, ssl.SSLError) as e:
        raise HostError(f"Can't connect to {url}: {e}") from None
    if fingerprint:
        presented = _fingerprint(conn.sock.getpeercert(binary_form=True))
        if presented != fingerprint:
            conn.close()
            raise HostError(f"{url} presented a different certificate ({presented}) than the one confirmed "
                            f"({fingerprint}). If the host's certificate was replaced on purpose, update the "
                            "fingerprint; otherwise something is intercepting the connection.")
    return conn


def peer_fingerprint(url: str) -> str:
    parts = urlsplit(url)
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    try:
        with socket.create_connection((parts.hostname, parts.port or 443), timeout=TIMEOUT) as sock, \
                context.wrap_socket(sock, server_hostname=parts.hostname) as tls:
            return _fingerprint(tls.getpeercert(binary_form=True))
    except OSError as e:
        raise HostError(f"Can't connect to {url}: {e}") from None


def call(url: str, token: str, fingerprint: str | None, method: str, path: str, query: str = "",
         body: bytes | None = None, headers: dict[str, str] | None = None) -> tuple[int, dict[str, str], bytes]:
    """One request to the host's API (path relative to /api)."""
    conn = _open(url, fingerprint)
    try:
        target = "/api/" + path.lstrip("/") + (f"?{query}" if query else "")
        conn.request(method, target, body=body, headers={
            "Authorization": f"Bearer {token}", "Accept": "application/json", **(headers or {})})
        resp = conn.getresponse()
        data = resp.read(MAX_BODY + 1)
        if len(data) > MAX_BODY:
            raise HostError("the host's response is too large to relay")
        return resp.status, {k.lower(): v for k, v in resp.getheaders()}, data
    except (OSError, http.client.HTTPException) as e:
        raise HostError(f"{url}: {e}") from None
    finally:
        conn.close()


def get_json(host: dict, path: str, **params) -> dict:
    status, _, data = call(host["url"], host["token"], host["fingerprint"], "GET", path, urlencode(params))
    try:
        payload = json.loads(data or b"{}")
    except ValueError:
        raise HostError(f"{host['url']} didn't answer like a Habeny server (HTTP {status})") from None
    if status == 401:
        raise HostError("the host rejected the API token (revoked or expired?)")
    if status >= 400:
        raise HostError(f"HTTP {status}: {payload.get('detail') or payload}")
    return payload


def probe(url: str, token: str, fingerprint: str | None) -> dict[str, Any]:
    """Check a host answers, the token works there, and what role it has."""
    host = {"url": url, "token": token, "fingerprint": fingerprint}
    status = get_json(host, "auth/status")
    user = (status.get("data") or {}).get("user")
    if not user:
        raise HostError("the host didn't accept the API token")
    health = get_json(host, "system/health")
    return {"version": health.get("version"), "role": user.get("role"), "user": user.get("username")}


# ── storage ─────────────────────────────────────────────────────────────

def _row(row, reveal: bool = False) -> dict[str, Any]:
    host = dict(row)
    token = decrypt_secret(host.pop("token"))
    if reveal:
        host["token"] = token
    else:
        host["token_hint"] = token[:12] + "…" if token else ""
    return host


def list_hosts(reveal: bool = False) -> list[dict[str, Any]]:
    with contextlib.closing(_conn()) as conn:
        return [_row(r, reveal) for r in conn.execute("SELECT * FROM hosts ORDER BY name COLLATE NOCASE")]


def get_host(host_id: int, reveal: bool = False) -> dict[str, Any] | None:
    with contextlib.closing(_conn()) as conn:
        row = conn.execute("SELECT * FROM hosts WHERE id = ?", (host_id,)).fetchone()
    return _row(row, reveal) if row else None


def add_host(name: str, url: str, token: str, fingerprint: str | None, team_id: int | None) -> dict[str, Any]:
    url = normalize_url(url)
    fingerprint = (fingerprint or "").strip().upper() or None
    info = probe(url, token, fingerprint)  # raises FingerprintNeeded for an unconfirmed self-signed host
    now = utc_now().isoformat()
    try:
        with contextlib.closing(_conn()) as conn:
            cur = conn.execute(
                "INSERT INTO hosts (name, url, token, fingerprint, team_id, created_at, last_checked_at, last_status,"
                " version) VALUES (?, ?, ?, ?, ?, ?, ?, 'ok', ?)",
                (name, url, encrypt_secret(token), fingerprint, team_id, now, now, info["version"]))
            conn.commit()
            host_id = cur.lastrowid
    except sqlite3.IntegrityError:
        raise HostError(f"a host named '{name}' exists") from None
    return {**get_host(host_id), "remote_role": info["role"], "remote_user": info["user"]}


def update_host(host_id: int, name: str, team_id: int | None, token: str | None, fingerprint: str | None) -> dict | None:
    current = get_host(host_id, reveal=True)
    if current is None:
        return None
    new_token = token or current["token"]
    new_fp = (fingerprint.strip().upper() if fingerprint else None) or current["fingerprint"]
    if token or fingerprint:
        probe(current["url"], new_token, new_fp)
    try:
        with contextlib.closing(_conn()) as conn:
            conn.execute("UPDATE hosts SET name = ?, team_id = ?, token = ?, fingerprint = ? WHERE id = ?",
                         (name, team_id, encrypt_secret(new_token), new_fp, host_id))
            conn.commit()
    except sqlite3.IntegrityError:
        raise HostError(f"a host named '{name}' exists") from None
    return get_host(host_id)


def delete_host(host_id: int) -> dict | None:
    host = get_host(host_id)
    if host:
        with contextlib.closing(_conn()) as conn:
            conn.execute("DELETE FROM hosts WHERE id = ?", (host_id,))
            conn.commit()
    return host


def record_check(host_id: int, error: str | None, version: str | None = None) -> None:
    with contextlib.suppress(Exception), contextlib.closing(_conn()) as conn:
        conn.execute("UPDATE hosts SET last_checked_at = ?, last_status = ?, last_error = ?,"
                     " version = COALESCE(?, version) WHERE id = ?",
                     (utc_now().isoformat(), "error" if error else "ok", error, version, host_id))
        conn.commit()


def usable_by(host: dict, user: dict | None) -> bool:
    """A host assigned to a team is for that team (and admins); others are for everyone."""
    if user is None or user.get("role") == "admin" or host.get("team_id") is None:
        return True
    return host["team_id"] == user.get("team_id")


def overview(host: dict) -> dict[str, Any]:
    """Status, version, containers and alerts of one host (for the Hosts page)."""
    try:
        health = get_json(host, "system/health")
        stats = get_json(host, "agents/stats").get("data") or {}
        active = (get_json(host, "system/alerts").get("data") or {}).get("alerts", [])
    except HostError as e:
        record_check(host["id"], str(e))
        return {"status": "unreachable", "error": str(e)}
    record_check(host["id"], None, health.get("version"))
    return {"status": "ok", "version": health.get("version"), "containers": stats.get("total_agents"),
            "running": (stats.get("by_status") or {}).get("running"), "alerts": active}


def check_all() -> None:
    """Maintenance: mark unreachable hosts and alert on them."""
    from app.services import alerts
    for host in list_hosts(reveal=True):
        try:
            health = get_json(host, "system/health")
        except HostError as e:
            record_check(host["id"], str(e))
            alerts.manager.fire("host_unreachable", "critical", f"Host {host['name']} ({host['url']}) is unreachable: {e}",
                                target=host["name"], details={"url": host["url"]}, link="/hosts")
            continue
        record_check(host["id"], None, health.get("version"))
        alerts.manager.clear("host_unreachable", host["name"], f"Host {host['name']} is reachable again")
