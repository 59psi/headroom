"""The CA check reads the SERVED chain, not just the exported root file.

The root fingerprint comes from `/caddy-ca/root.crt`, because a root is never
sent in a handshake. On its own that file says what this install HANDS OUT.
After the CA-restore recipe puts the original authority back, Caddy can keep
serving a cached leaf from the authority it minted in the meantime: the file
says A, the chain says B, and the card reported "Currently serving a valid
certificate" — with the file's fingerprint labeled "Now serving" — while every
device that trusts A refused the connection.

Both authorities here carry Caddy's real naming, identical to the byte, so
nothing but a signature can tell them apart. That is the point.
"""

from __future__ import annotations

import socket
import ssl
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from headroom import config
from headroom.routes import ca_cert
from headroom.services import tls_health

pytestmark = pytest.mark.anyio

NOW = datetime.now(timezone.utc)
ROOT_NAME = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Caddy Local Authority - 2026 ECC Root")])
INTERMEDIATE_NAME = x509.Name(
    [x509.NameAttribute(NameOID.COMMON_NAME, "Caddy Local Authority - ECC Intermediate")]
)

needs_chain_api = pytest.mark.skipif(
    sys.version_info < (3, 13), reason="the served chain is readable from Python 3.13"
)


def _cert(subject, issuer_name, issuer_key, key, *, ca, san=None):
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer_name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(NOW - timedelta(hours=1))
        .not_valid_after(NOW + timedelta(days=400))
        .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
    )
    if san:
        builder = builder.add_extension(x509.SubjectAlternativeName([x509.DNSName(san)]), critical=False)
    return builder.sign(issuer_key, hashes.SHA256())


class _Authority:
    """One Caddy-shaped local CA: root → intermediate → leaf for `localhost`."""

    def __init__(self):
        self.root_key = ec.generate_private_key(ec.SECP256R1())
        self.root = _cert(ROOT_NAME, ROOT_NAME, self.root_key, self.root_key, ca=True)
        self.int_key = ec.generate_private_key(ec.SECP256R1())
        self.intermediate = _cert(INTERMEDIATE_NAME, ROOT_NAME, self.root_key, self.int_key, ca=True)
        self.leaf_key = ec.generate_private_key(ec.SECP256R1())
        leaf_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
        self.leaf = _cert(leaf_name, INTERMEDIATE_NAME, self.int_key, self.leaf_key, ca=False, san="localhost")

    def write_root(self, path):
        path.write_bytes(self.root.public_bytes(serialization.Encoding.PEM))
        return path

    def serve(self, tmp_path, *, with_intermediate=True):
        pem = self.leaf.public_bytes(serialization.Encoding.PEM)
        if with_intermediate:
            pem += self.intermediate.public_bytes(serialization.Encoding.PEM)
        chain, key = tmp_path / "chain.pem", tmp_path / "leaf.key"
        chain.write_bytes(pem)
        key.write_bytes(self.leaf_key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ))
        return _Server(chain, key)


class _Server:
    def __init__(self, chain, key):
        self._ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self._ctx.load_cert_chain(chain, key)
        self._sock = socket.socket()
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(4)
        self.port = self._sock.getsockname()[1]
        self._stop = threading.Event()
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while not self._stop.is_set():
            try:
                raw, _ = self._sock.accept()
            except OSError:
                return
            try:
                with self._ctx.wrap_socket(raw, server_side=True):
                    pass
            except OSError:
                pass

    def close(self):
        self._stop.set()
        self._sock.close()


@pytest.fixture
def serving(monkeypatch, tmp_path):
    servers = []

    def _serve(authority, *, exported, with_intermediate=True):
        where = tmp_path / f"s{len(servers)}"
        where.mkdir()
        server = authority.serve(where, with_intermediate=with_intermediate)
        servers.append(server)
        monkeypatch.setattr(config.settings, "origin", f"https://localhost:{server.port}")
        monkeypatch.setattr(ca_cert, "CA_ROOT_PATH", exported.write_root(tmp_path / "root.crt"))
        return server

    yield _serve
    for s in servers:
        s.close()


@needs_chain_api
async def test_a_chain_from_another_authority_is_caught(serving):
    """The restore scenario: the file holds A, Caddy serves B."""
    handed_out, served = _Authority(), _Authority()
    serving(served, exported=handed_out)

    status = tls_health.check_certificate()

    assert status.expired is False and status.hostname_ok is True, (
        "the leaf itself is fine — which is exactly why nothing else noticed"
    )
    assert status.ca_sha256 is not None
    assert status.chain_matches_ca is False, (
        "the served chain leads to a different root than the one devices install"
    )


async def test_an_unresolvable_site_name_is_read_through_the_probe_address(serving, monkeypatch):
    """The LAN-HTTPS install: the site is `headroom.local`, which the container
    cannot resolve, while Caddy answers on the shared host network. Dialing the
    probe address and asking for the site name reads the real certificate;
    dialing the name itself fails every time."""
    authority = _Authority()
    server = serving(authority, exported=authority)
    monkeypatch.setattr(config.settings, "origin", f"https://headroom.invalid:{server.port}")

    monkeypatch.setattr(config.settings, "tls_probe_address", None)
    unreachable = tls_health.check_certificate()
    assert unreachable.error, "without a probe address the .invalid name cannot resolve"

    monkeypatch.setattr(config.settings, "tls_probe_address", "127.0.0.1")
    status = tls_health.check_certificate()
    assert status.error is None
    assert status.host == "headroom.invalid"  # reported and checked by the site name
    assert status.not_after is not None


async def test_the_lan_https_overlay_sets_the_probe_address():
    text = (Path(__file__).resolve().parents[1] / "docker-compose.https-lan.yml").read_text()
    assert 'HEADROOM_TLS_PROBE_ADDRESS: "127.0.0.1"' in text


@needs_chain_api
async def test_a_chain_from_this_authority_matches(serving):
    authority = _Authority()
    serving(authority, exported=authority)

    status = tls_health.check_certificate()

    assert status.chain_matches_ca is True
    assert status.ca_sha256 == tls_health.ca_fingerprint()


@needs_chain_api
async def test_a_leaf_sent_without_its_intermediate_does_not_match(serving):
    """A browser cannot build that chain either, so it is not "all clear"."""
    authority = _Authority()
    serving(authority, exported=authority, with_intermediate=False)

    assert tls_health.check_certificate().chain_matches_ca is False


async def test_with_no_exported_root_the_answer_is_unknown_not_false(monkeypatch, tmp_path):
    """Every install without the LAN-HTTPS overlay. Not an alarm."""
    authority = _Authority()
    server = authority.serve(tmp_path)
    try:
        monkeypatch.setattr(config.settings, "origin", f"https://localhost:{server.port}")
        monkeypatch.setattr(ca_cert, "CA_ROOT_PATH", tmp_path / "absent.crt")

        status = tls_health.check_certificate()
    finally:
        server.close()

    assert status.ca_sha256 is None
    assert status.chain_matches_ca is None


async def test_the_restore_recipe_in_the_archive_reissues_the_leaves():
    """The note inside every archive is the recipe that CREATES this state
    unless it also drops the certificates the interim authority issued."""
    from headroom.services import ca_vault

    assert "rm -rf /data/caddy/certificates/local" in ca_vault.BACKUP_README


# ---- the walk itself, without a socket ---------------------------------- #


async def test_the_walk_needs_a_signature_not_a_name():
    a, b = _Authority(), _Authority()
    assert a.root.subject == b.root.subject, "the premise: identical names"

    assert tls_health.chain_matches_root([a.leaf, a.intermediate], a.root, complete=True) is True
    assert tls_health.chain_matches_root([b.leaf, b.intermediate], a.root, complete=True) is False


async def test_a_served_root_counts_and_a_partial_chain_is_unknown():
    a = _Authority()
    assert tls_health.chain_matches_root([a.leaf, a.intermediate, a.root], a.root, complete=True) is True
    # Only the leaf readable (Python < 3.13): cannot tell, so do not claim either.
    assert tls_health.chain_matches_root([a.leaf], a.root, complete=False) is None
    assert tls_health.chain_matches_root([a.leaf, a.intermediate], None, complete=True) is None
