"""
HTTPS for the built-in server.

HABENY_TLS=auto (default): use HABENY_TLS_CERT / HABENY_TLS_KEY if set, otherwise a
self-signed certificate generated once under DATA_DIR/tls/.
HABENY_TLS=off: plain HTTP, for running behind a reverse proxy that terminates TLS
(the proxy must send X-Forwarded-Proto; uvicorn trusts it from FORWARDED_ALLOW_IPS,
127.0.0.1 by default).
"""
import datetime
import ipaddress
import logging
import os
import socket
from pathlib import Path

from app import config
from app.config import DATA_DIR

logger = logging.getLogger(__name__)

TLS_DIR = DATA_DIR / "tls"
SELF_SIGNED_CERT = TLS_DIR / "cert.pem"
SELF_SIGNED_KEY = TLS_DIR / "key.pem"


def tls_mode() -> str:
    return config.get("HABENY_TLS")


def uses_own_certificate() -> bool:
    return bool(config.raw("HABENY_TLS_CERT") and config.raw("HABENY_TLS_KEY"))


def _local_names() -> tuple[list[str], list[str]]:
    names = {"localhost", socket.gethostname(), socket.getfqdn()}
    ips = {"127.0.0.1"}
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    try:  # the address used for outbound traffic (no packets are sent)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))
            ips.add(s.getsockname()[0])
    except OSError:
        pass
    return sorted(n for n in names if n), sorted(ips)


def _generate_self_signed(cert_path: Path, key_path: Path) -> None:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    names, ips = _local_names()
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, names[0] if names else "habeny"),
                         x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Habeny (self-signed)")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=825))
        .add_extension(x509.SubjectAlternativeName(
            [x509.DNSName(n) for n in names] + [x509.IPAddress(ipaddress.ip_address(i)) for i in ips]
        ), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                  serialization.NoEncryption()))
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    logger.info(f"Generated a self-signed TLS certificate for {', '.join(names + ips)} at {cert_path}")


def server_ssl_options() -> dict:
    """uvicorn.run(...) keyword arguments for TLS ({} when TLS is off)."""
    mode = tls_mode()
    if mode in ("off", "false", "0", "no"):
        logger.warning("HABENY_TLS=off: serving plain HTTP. Only do this behind a reverse proxy that terminates TLS.")
        return {}
    if uses_own_certificate():
        return {"ssl_certfile": config.raw("HABENY_TLS_CERT"), "ssl_keyfile": config.raw("HABENY_TLS_KEY")}
    if not (SELF_SIGNED_CERT.exists() and SELF_SIGNED_KEY.exists()):
        _generate_self_signed(SELF_SIGNED_CERT, SELF_SIGNED_KEY)
    return {"ssl_certfile": str(SELF_SIGNED_CERT), "ssl_keyfile": str(SELF_SIGNED_KEY)}


def listen_address() -> tuple[str, int]:
    return config.get("HABENY_HOST"), config.get("HABENY_PORT")


def hsts_enabled() -> bool | None:
    """Only with a real certificate: HSTS on a self-signed one would make the browser
    warning impossible to click through."""
    return tls_mode() not in ("off", "false", "0", "no") and uses_own_certificate()


def _fingerprint_of_file(path) -> str | None:
    import hashlib
    import ssl as _ssl
    try:
        with open(path) as f:
            der = _ssl.PEM_cert_to_DER_cert(f.read())
    except (OSError, ValueError):
        return None
    digest = hashlib.sha256(der).hexdigest().upper()
    return ":".join(digest[i:i + 2] for i in range(0, 64, 2))


def certificate_fingerprint() -> str | None:
    """SHA-256 fingerprint of the certificate this server presents (what another Habeny
    console pins when adding this server as a host)."""
    return _fingerprint_of_file(config.raw("HABENY_TLS_CERT") if uses_own_certificate() else SELF_SIGNED_CERT)
