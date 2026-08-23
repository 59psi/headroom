"""Noticing that the HTTPS front door is serving an expired certificate.

Written after the real one went unnoticed for 37 days. Caddy's stored leaf key
vanished, its renewal queued every ten minutes and never completed, and
`https://headroom.local` kept serving a certificate that had expired weeks
before. Every other signal stayed green — healthy container, answering app,
running backups — because nothing here had ever looked at the certificate in
front of it.

These tests use REAL certificates against a REAL TLS socket rather than mocking
the parse. The bug was never in arithmetic on a date; it was that nobody
performed the handshake at all, and a mocked handshake tests the wrong half.
"""

from __future__ import annotations

import socket
import ssl
import threading
from datetime import datetime, timedelta, timezone

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from headroom.services import tls_health

pytestmark = pytest.mark.anyio


def _self_signed(host: str, not_before: datetime, not_after: datetime, tmp_path):
    """A throwaway certificate for `host`, valid over the given window."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before)
        .not_valid_after(not_after)
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(host)]), critical=False
        )
        .sign(key, hashes.SHA256())
    )
    cert_path = tmp_path / "c.pem"
    key_path = tmp_path / "k.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return cert_path, key_path


class _Server:
    """A TLS listener on localhost that serves one certificate and nothing else."""

    def __init__(self, cert_path, key_path):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert_path, key_path)
        self._sock = socket.socket()
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(4)
        self.port = self._sock.getsockname()[1]
        self._ctx = ctx
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        while not self._stop.is_set():
            try:
                raw, _ = self._sock.accept()
            except OSError:
                return
            try:
                # The handshake is the entire point; whatever happens after it
                # is irrelevant, and the client closes immediately anyway.
                with self._ctx.wrap_socket(raw, server_side=True):
                    pass
            except OSError:
                pass

    def close(self):
        self._stop.set()
        self._sock.close()


@pytest.fixture
def front_door(monkeypatch):
    """Point `check_certificate` at a local server serving `cert`."""
    servers = []

    def _serve(cert_path, key_path, host="localhost"):
        server = _Server(cert_path, key_path)
        servers.append(server)
        monkeypatch.setenv("HEADROOM_ORIGIN", f"https://{host}:{server.port}")
        return server

    yield _serve
    for s in servers:
        s.close()


# ---- when there is no front door at all -------------------------------- #


async def test_no_https_origin_is_not_a_problem(monkeypatch):
    """Every install without an HTTPS overlay. Must not render as an alarm."""
    monkeypatch.delenv("HEADROOM_ORIGIN", raising=False)

    status = tls_health.check_certificate()

    assert status.applicable is False
    assert status.needs_attention is False


async def test_a_plain_http_origin_is_also_not_applicable(monkeypatch):
    monkeypatch.setenv("HEADROOM_ORIGIN", "http://headroom.local")

    assert tls_health.check_certificate().applicable is False


# ---- the failure this exists for --------------------------------------- #


async def test_an_expired_certificate_is_reported(front_door, tmp_path):
    """The 37-day silence, in one assertion."""
    now = datetime.now(timezone.utc)
    cert, key = _self_signed(
        "localhost", now - timedelta(days=40), now - timedelta(days=37), tmp_path
    )
    front_door(cert, key)

    status = tls_health.check_certificate()

    assert status.applicable is True
    assert status.expired is True
    assert status.needs_attention is True
    assert status.days_remaining is not None and status.days_remaining < 0


async def test_a_healthy_certificate_is_not_flagged(front_door, tmp_path):
    now = datetime.now(timezone.utc)
    cert, key = _self_signed(
        "localhost", now - timedelta(hours=1), now + timedelta(days=30), tmp_path
    )
    front_door(cert, key)

    status = tls_health.check_certificate()

    assert status.expired is False
    assert status.needs_attention is False
    assert status.hostname_ok is True
    assert status.days_remaining is not None and status.days_remaining > 29


async def test_a_certificate_about_to_expire_is_flagged_before_it_does(
    front_door, tmp_path
):
    """Caddy's internal leaves live 12 hours and renew continuously.

    Inside the grace window means renewal has STOPPED, not that expiry is
    merely approaching — which is why the threshold is days, not weeks.
    """
    now = datetime.now(timezone.utc)
    cert, key = _self_signed(
        "localhost", now - timedelta(hours=1), now + timedelta(hours=6), tmp_path
    )
    front_door(cert, key)

    status = tls_health.check_certificate()

    assert status.expired is False
    assert status.needs_attention is True


async def test_a_certificate_for_the_wrong_name_is_caught(front_door, tmp_path):
    """A valid certificate for the wrong host fails in a browser just as hard."""
    now = datetime.now(timezone.utc)
    cert, key = _self_signed(
        "somewhere-else.invalid", now - timedelta(hours=1), now + timedelta(days=30),
        tmp_path,
    )
    front_door(cert, key)

    status = tls_health.check_certificate()

    assert status.expired is False
    assert status.hostname_ok is False


async def test_nothing_listening_is_an_error_not_a_crash(monkeypatch):
    """A closed port must produce a report, not an exception.

    This runs inside a settings endpoint; raising here would turn "the front
    door is down" into "the settings page is down".
    """
    # Port 1 on loopback: reserved, and nothing legitimate binds it.
    monkeypatch.setenv("HEADROOM_ORIGIN", "https://127.0.0.1:1")

    status = tls_health.check_certificate(timeout=2.0)

    assert status.applicable is True
    assert status.error is not None
    assert status.not_after is None


# ---- the endpoint ------------------------------------------------------ #


async def test_the_endpoint_reports_the_served_certificate(client, front_door, tmp_path):
    now = datetime.now(timezone.utc)
    cert, key = _self_signed(
        "localhost", now - timedelta(days=40), now - timedelta(days=37), tmp_path
    )
    front_door(cert, key)

    body = (await client.get("/api/settings/tls")).json()

    assert body["expired"] is True
    assert body["needs_attention"] is True


async def test_the_endpoint_needs_auth(anon_client):
    assert (await anon_client.get("/api/settings/tls")).status_code == 401


# ---- telling two identically-named roots apart ------------------------- #


async def test_the_ca_fingerprint_is_published(client, monkeypatch, tmp_path):
    """The failure that survives every other fix.

    Caddy names every root `Caddy Local Authority - <year> ECC Root`, so a
    second install produces a DIFFERENT root with the SAME name. A browser
    matching by name picks whichever it has and reports "invalid signature" on
    a chain that verifies perfectly at the server. Nothing in the name, the
    dates or the issuer separates them — only the fingerprint does, so the app
    has to publish it or the comparison cannot be made.
    """
    from headroom.routes import ca_cert
    from headroom.services import tls_health

    now = datetime.now(timezone.utc)
    cert_path, _key = _self_signed(
        "localhost", now - timedelta(days=1), now + timedelta(days=3650), tmp_path
    )
    monkeypatch.setattr(ca_cert, "CA_ROOT_PATH", cert_path)

    fingerprint = tls_health.ca_fingerprint()

    assert fingerprint is not None
    # Same shape openssl and Keychain Access print, so it compares by eye.
    assert len(fingerprint.split(":")) == 32
    assert fingerprint == fingerprint.upper()

    body = (await client.get("/api/settings/tls")).json()
    assert body["ca_sha256"] == fingerprint


async def test_two_different_roots_have_different_fingerprints(monkeypatch, tmp_path):
    """The property the whole diagnosis rests on."""
    from headroom.routes import ca_cert
    from headroom.services import tls_health

    now = datetime.now(timezone.utc)
    window = (now - timedelta(days=1), now + timedelta(days=3650))
    first, _ = _self_signed("localhost", *window, tmp_path / "a")
    second, _ = _self_signed("localhost", *window, tmp_path / "b")

    monkeypatch.setattr(ca_cert, "CA_ROOT_PATH", first)
    a = tls_health.ca_fingerprint()
    monkeypatch.setattr(ca_cert, "CA_ROOT_PATH", second)
    b = tls_health.ca_fingerprint()

    assert a and b and a != b


async def test_no_ca_on_disk_is_not_an_error(monkeypatch, tmp_path):
    from headroom.routes import ca_cert
    from headroom.services import tls_health

    monkeypatch.setattr(ca_cert, "CA_ROOT_PATH", tmp_path / "absent.crt")

    assert tls_health.ca_fingerprint() is None


async def test_an_expired_certificate_does_not_fail_readiness(client, front_door, tmp_path):
    """Reported, never enforced.

    The certificate belongs to Caddy, so failing readiness on it would
    restart-loop this app without fixing anything — and take the collection
    offline to protest a padlock.
    """
    now = datetime.now(timezone.utc)
    cert, key = _self_signed(
        "localhost", now - timedelta(days=40), now - timedelta(days=37), tmp_path
    )
    front_door(cert, key)

    resp = await client.get("/health/ready")

    assert resp.status_code == 200
    assert resp.json()["ok"] is True
