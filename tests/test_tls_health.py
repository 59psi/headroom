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

import re
import socket
import ssl
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

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
    # Comfortably past RENEWAL_GRACE_DAYS rather than exactly on it: a cert
    # valid for exactly the grace window trips the check microseconds later,
    # which makes the test fail for a reason that has nothing to do with the
    # behavior it describes.
    now = datetime.now(timezone.utc)
    cert, key = _self_signed(
        "localhost", now - timedelta(hours=1), now + timedelta(days=400), tmp_path
    )
    front_door(cert, key)

    status = tls_health.check_certificate()

    assert status.expired is False
    assert status.needs_attention is False
    assert status.hostname_ok is True
    assert status.days_remaining is not None and status.days_remaining > 399


async def test_a_certificate_about_to_expire_is_flagged_before_it_does(
    front_door, tmp_path
):
    """Warn with time left to act, not as the outage starts."""
    now = datetime.now(timezone.utc)
    cert, key = _self_signed(
        "localhost", now - timedelta(hours=1), now + timedelta(days=3), tmp_path
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


async def test_an_ip_san_counts_as_covering_an_ip_host(front_door, tmp_path):
    """Since 2.49 an install can serve on a bare address.

    Caddy puts it in the certificate as an `IPAddress` SAN. Checking only DNS
    SANs found nothing and reported "doesn't cover this host, browsers will
    refuse it" about a perfectly good certificate — a false alarm on the one
    card people read when TLS is already confusing them.
    """
    import ipaddress as ipaddr

    from cryptography import x509 as x

    now = datetime.now(timezone.utc)
    key = ec.generate_private_key(ec.SECP256R1())
    name = x.Name([x.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    cert = (
        x.CertificateBuilder()
        .subject_name(name).issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x.random_serial_number())
        .not_valid_before(now - timedelta(hours=1))
        .not_valid_after(now + timedelta(days=400))
        .add_extension(
            x.SubjectAlternativeName([x.IPAddress(ipaddr.ip_address("127.0.0.1"))]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    tmp_path.mkdir(parents=True, exist_ok=True)
    cert_path, key_path = tmp_path / "c.pem", tmp_path / "k.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))
    front_door(cert_path, key_path, host="127.0.0.1")

    status = tls_health.check_certificate()

    assert status.hostname_ok is True, "an IP SAN must cover the IP it is served on"


async def test_a_dns_only_certificate_does_not_cover_an_ip_host(front_door, tmp_path):
    """The other direction, so the fix isn't just "always true"."""
    now = datetime.now(timezone.utc)
    cert, key = _self_signed(
        "headroom.local", now - timedelta(hours=1), now + timedelta(days=400), tmp_path
    )
    front_door(cert, key, host="127.0.0.1")

    assert tls_health.check_certificate().hostname_ok is False


async def test_every_dataclass_field_survives_into_the_schema():
    """`TlsStatusRead(**asdict(status))` drops unknown keys SILENTLY.

    Pydantic's default is `extra='ignore'`, so adding a field to `TlsStatus`
    and forgetting the schema loses it with no error anywhere — the API just
    stops reporting something. Same class of failure the Hat-column DDL test
    exists for.
    """
    import dataclasses

    from headroom.schemas.settings import TlsStatusRead

    dataclass_fields = {f.name for f in dataclasses.fields(tls_health.TlsStatus)}
    schema_fields = set(TlsStatusRead.model_fields)

    assert dataclass_fields <= schema_fields, (
        "TlsStatus and TlsStatusRead have drifted; these dataclass fields are "
        f"silently dropped by the API: {sorted(dataclass_fields - schema_fields)}"
    )

    # The reverse direction is legitimate but must stay deliberate: these come
    # from the ROUTE, not from `check_certificate`, because answering them
    # needs the database and this dataclass is built by a sync network call.
    # Enumerated so that adding a third is a decision rather than a default
    # nobody notices going out as False.
    assert schema_fields - dataclass_fields == {
        "ca_changed", "ca_expected_sha256", "issuer_not_after", "clamped_by_issuer",
    }


async def test_the_route_supplies_every_schema_only_field(client, monkeypatch):
    """A schema-only field the route forgets defaults silently — pin it.

    `ca_changed=False` is exactly what "everything is fine" looks like, so a
    route that stopped passing it would report health rather than nothing.
    """
    import dataclasses

    from headroom.schemas.settings import TlsStatusRead
    from headroom.services import ca_vault

    seen: dict = {}

    async def _fake_check(db, current):
        seen["called"] = True
        return True, "AA:BB:EXPECTED"

    monkeypatch.setattr(ca_vault, "check_root", _fake_check)
    monkeypatch.setattr(
        tls_health, "check_certificate",
        lambda *a, **k: tls_health.TlsStatus(applicable=True, ca_sha256="CC:DD"),
    )

    body = (await client.get("/api/settings/tls")).json()

    assert seen.get("called"), "the route never consulted the CA check"
    dataclass_fields = {f.name for f in dataclasses.fields(tls_health.TlsStatus)}
    for field in set(TlsStatusRead.model_fields) - dataclass_fields:
        assert field in body, f"route never supplies {field}"
    assert body["ca_changed"] is True
    assert body["ca_expected_sha256"] == "AA:BB:EXPECTED"


# ---- the Safari ceiling ------------------------------------------------ #
#
# These read the Caddyfile rather than a constant in this repo's Python,
# because the Caddyfile is what Caddy actually issues from. A constant here
# would agree with itself while the deployed lifetime said something else.


#: Safari's limit for a server certificate under a USER-ADDED root. The
#: widely-quoted 398 days is a different rule covering only Apple's
#: preinstalled roots. Verified by binary search: 825 accepted, 826 rejected.
SAFARI_MAX_VALIDITY_DAYS = 825

#: Caddy's default root lifetime, which this repo does not change.
CADDY_ROOT_LIFETIME_DAYS = 3600

#: Caddy's default `renewal_window_ratio`: an issued certificate's lifetime
#: must be under this share of its issuer's, or the CA refuses to start.
RENEWAL_WINDOW_RATIO = 1 / 3

CADDYFILE = Path(__file__).resolve().parent.parent / "Caddyfile"


def _caddyfile_days(directive: str) -> int:
    """Read `<directive> <N>d` out of the Caddyfile.

    `^\\s*lifetime` deliberately will not match `intermediate_lifetime` — the
    leading anchor means the two directives read independently.
    """
    pattern = rf"^\s*{directive}\s+(\d+)d\s*$"
    match = re.search(pattern, CADDYFILE.read_text(), re.MULTILINE)
    assert match, f"no `{directive} <N>d` in the Caddyfile — did the blocks change?"
    return int(match.group(1))


async def test_the_caddyfile_leaf_lifetime_is_under_the_safari_ceiling():
    """The one that breaks iPhones and nothing else.

    Safari rejects a TLS server certificate whose validity exceeds 825 days,
    even when it chains to a manually installed root.

    Chrome and Firefox impose no limit here at all, which is precisely the
    trap: raising this to "10 years" because a laptop is happy produces a
    setup that fails on every iPhone in the house, with a certificate error
    that looks like the trust store rather than the lifetime.
    """
    days = _caddyfile_days("lifetime")

    assert days < SAFARI_MAX_VALIDITY_DAYS, (
        f"leaf lifetime {days}d exceeds Safari's {SAFARI_MAX_VALIDITY_DAYS}-day "
        "limit — this works in Chrome and fails on every iPhone"
    )


async def test_the_site_addresses_are_env_driven_and_default_to_the_local_name():
    """Reachability off the LAN is a config value, not a hardcoded name.

    `.local` is mDNS — link-local multicast — so it does not resolve over a
    VPN, a tunnel, or a routed subnet. Connecting by IP instead fails the
    handshake outright, because Caddy rejects an SNI matching no site here,
    and the certificate has no IP SAN even if it did. Listing the address
    fixes both at once: Caddy serves it and signs it into the cert.

    The default must stay a `.local` name, since changing it silently changes
    what every existing install serves — and the addresses are also the
    certificate's SANs, so a wrong default is a certificate error, not a 404.
    """
    site_line = re.search(
        r"^\{\$HEADROOM_SITE_ADDRESSES:(?P<default>[^}]+)\} \{$",
        CADDYFILE.read_text(),
        re.MULTILINE,
    )

    assert site_line, (
        "no `{$HEADROOM_SITE_ADDRESSES:<default>} {` site line in the Caddyfile "
        "— a hardcoded address cannot be reached from off the LAN"
    )
    assert site_line.group("default").endswith(".local"), (
        f"default site address is {site_line.group('default')!r}; it must stay "
        "the mDNS name or existing installs change what they serve"
    )


async def test_the_intermediate_outlives_the_leaf_by_caddys_required_margin():
    """Caddy refuses to start if this is wrong, so catch it here instead.

    Getting it wrong is invisible until a deploy, where it presents as a
    sidecar that will not come up rather than as a bad number in a file.
    """
    leaf = _caddyfile_days("lifetime")
    intermediate = _caddyfile_days("intermediate_lifetime")

    assert leaf < intermediate * RENEWAL_WINDOW_RATIO, (
        f"leaf {leaf}d needs an intermediate over {leaf * 3}d; it is {intermediate}d"
    )
    assert intermediate < CADDY_ROOT_LIFETIME_DAYS, (
        f"intermediate {intermediate}d must stay under the "
        f"{CADDY_ROOT_LIFETIME_DAYS}d root"
    )


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


async def test_http3_is_not_advertised():
    """Caddy must not offer a protocol that does not complete here.

    Caddy enables HTTP/3 by default and stamps every response with
    `alt-svc: h3=":443"; ma=2592000`. Safari takes that literally and opens
    each fresh connection by attempting QUIC over UDP 443, remembering the
    advertisement for thirty days.

    Measured against the live deployment: **every request in Caddy's log
    negotiated h2, none ever negotiated h3** — from iOS Safari, with Caddy
    listening on UDP 443 and no firewall. So the advertisement bought nothing
    and cost a failed QUIC attempt before the TCP fallback on every fresh
    connection. That is the "slow on first load after idle, instant
    afterwards, iPhone only" report, and it survived a long time because it is
    invisible to `curl` and Firefox (neither attempts h3) and to `:8000`
    (which sends no Alt-Svc) — the two tools used to check it.

    Pinned here because the failure is SILENT and asymmetric: deleting this
    directive breaks nothing a test would notice, breaks nothing on a laptop,
    and makes the phone slow again.
    """
    text = CADDYFILE.read_text()

    match = re.search(r"servers\s*\{[^}]*protocols\s+([^\n}]+)", text)
    assert match, (
        "no `servers { protocols ... }` block in the Caddyfile — Caddy then "
        "advertises HTTP/3, which never completes on this deployment"
    )
    protocols = match.group(1).split()
    assert "h3" not in protocols, (
        f"protocols are {protocols!r}; advertising h3 makes Safari pay a failed "
        "QUIC attempt on every fresh connection"
    )
    assert "h1" in protocols and "h2" in protocols, (
        f"protocols are {protocols!r}; h1 and h2 are both needed"
    )


async def test_the_upstream_is_the_v4_loopback_not_localhost():
    """`localhost` resolves to `::1` first; uvicorn binds IPv4 only.

    The Dockerfile binds uvicorn to `0.0.0.0`, so nothing is listening on the
    v6 loopback. With `reverse_proxy localhost:8000` Caddy dialled `[::1]:8000`
    on this dual-stack host, got `connection refused`, and returned **502**
    instead of retrying the v4 address — observed on the live deployment
    against `/api/admin/recent-errors/count`.

    It also matters for `FORWARDED_ALLOW_IPS`, which trusts a specific
    loopback address: `::1` and `127.0.0.1` are not the same peer.
    """
    text = CADDYFILE.read_text()

    assert re.search(r"^\treverse_proxy 127\.0\.0\.1:8000$", text, re.MULTILINE), (
        "the reverse_proxy upstream must be 127.0.0.1:8000 — `localhost` "
        "resolves to ::1 first and uvicorn does not listen there"
    )
    assert "reverse_proxy localhost:" not in text, (
        "`reverse_proxy localhost:` is the 502 this test exists to prevent"
    )
