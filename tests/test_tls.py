"""
Built-in HTTPS: self-signed by default, own certificate, or off behind a proxy.
"""
import ssl

import pytest

tls = pytest.importorskip("app.tls")


@pytest.fixture()
def tls_dir(tmp_path, monkeypatch):
    for var in ("HABENY_TLS", "HABENY_TLS_CERT", "HABENY_TLS_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(tls, "SELF_SIGNED_CERT", tmp_path / "cert.pem")
    monkeypatch.setattr(tls, "SELF_SIGNED_KEY", tmp_path / "key.pem")
    return tmp_path


def test_default_generates_usable_self_signed_cert(tls_dir):
    opts = tls.server_ssl_options()
    assert opts == {"ssl_certfile": str(tls_dir / "cert.pem"), "ssl_keyfile": str(tls_dir / "key.pem")}
    ssl.create_default_context().load_cert_chain(opts["ssl_certfile"], opts["ssl_keyfile"])  # valid pair
    assert (tls_dir / "key.pem").stat().st_mode & 0o077 == 0  # private key not readable by others
    before = (tls_dir / "cert.pem").read_bytes()
    tls.server_ssl_options()
    assert (tls_dir / "cert.pem").read_bytes() == before  # reused, not regenerated
    assert tls.hsts_enabled() is False  # never HSTS on a self-signed cert


def test_own_certificate(tls_dir, monkeypatch):
    monkeypatch.setenv("HABENY_TLS_CERT", "/etc/ssl/habeny.crt")
    monkeypatch.setenv("HABENY_TLS_KEY", "/etc/ssl/habeny.key")
    assert tls.server_ssl_options() == {"ssl_certfile": "/etc/ssl/habeny.crt", "ssl_keyfile": "/etc/ssl/habeny.key"}
    assert tls.hsts_enabled() is True
    assert not (tls_dir / "cert.pem").exists()


def test_off_behind_proxy(tls_dir, monkeypatch):
    monkeypatch.setenv("HABENY_TLS", "off")
    assert tls.server_ssl_options() == {}
    assert tls.hsts_enabled() is False
