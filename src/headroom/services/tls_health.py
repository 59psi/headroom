"""Is the LAN HTTPS front door serving a certificate a browser will accept?

Written after this exact failure went unnoticed for 37 days on the real
deployment: Caddy's stored leaf key vanished, so its renewal queued every ten
minutes and never completed, and `https://headroom.local` kept serving a
certificate that had expired weeks earlier. Every other signal was green — the
container was healthy, the app answered, backups ran — because nothing in this
app had ever looked at the thing in front of it.

**This measures the SERVED chain, not a file on disk.** Reading Caddy's storage
would answer a different and less useful question: the bug above had a valid
certificate on disk and an expired one in Caddy's memory, so a file check would
have reported everything fine while browsers refused the connection.

**It never gates readiness.** An expired certificate is not something restarting
this container can fix — the certificate belongs to Caddy — so failing the
health check would turn a broken padlock into a restart loop and take the app
down with it. Report, don't gate: the same reasoning that keeps an unconfigured
Anthropic key out of `/health/ready`.
"""

from __future__ import annotations

import logging
import os
import socket
import ssl
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse

from cryptography import x509
from cryptography.hazmat.primitives import hashes

logger = logging.getLogger(__name__)

#: Warn this far ahead. Caddy's internal leaf certificates live twelve hours
#: and renew continuously, so anything inside a day means renewal has stopped
#: rather than that expiry is merely approaching.
RENEWAL_GRACE_DAYS = 2

DEFAULT_TIMEOUT = 5.0


@dataclass(frozen=True)
class TlsStatus:
    """What a browser would see, or why we could not find out."""

    #: False when this deployment has no LAN HTTPS front door at all, which is
    #: every install except the https-lan / https overlays. Not a problem.
    applicable: bool
    host: str | None = None
    port: int = 443
    not_before: datetime | None = None
    not_after: datetime | None = None
    days_remaining: float | None = None
    expired: bool = False
    #: Expired, or so close that renewal has evidently stopped.
    needs_attention: bool = False
    #: Whether the certificate actually covers the name it is served under. A
    #: valid certificate for the wrong name fails in a browser just as hard.
    hostname_ok: bool | None = None
    #: SHA-256 of the CA this install hands out, so it can be compared against
    #: what a device actually trusts.
    #:
    #: Caddy names every root `Caddy Local Authority - <year> ECC Root`, so two
    #: installs produce two DIFFERENT roots with the SAME name. A browser
    #: matching by name picks whichever it has and reports "invalid signature"
    #: on a chain that verifies perfectly at the server — and nothing
    #: distinguishes the two by eye. The fingerprint does.
    ca_sha256: str | None = None
    error: str | None = None


def front_door() -> tuple[str, int] | None:
    """Host and port of the HTTPS front door, or None if there isn't one.

    Taken from `HEADROOM_ORIGIN`, which the https overlays already set to the
    name passkeys are bound to — so this checks the certificate for the origin
    the app actually claims, rather than a second guess at what it is.
    """
    origin = os.environ.get("HEADROOM_ORIGIN", "").strip()
    if not origin:
        return None
    parsed = urlparse(origin)
    if parsed.scheme != "https" or not parsed.hostname:
        return None
    return parsed.hostname, parsed.port or 443


def _fetch_peer_certificate(host: str, port: int, timeout: float) -> bytes:
    """The certificate as served, with verification deliberately OFF.

    `CERT_NONE` is the whole point, and is not the usual mistake it looks like.
    Disabling verification is dangerous when it makes an app *trust* an
    unverified peer; here it makes the app *look at* one. A verifying handshake
    fails on precisely the certificates this function exists to report on,
    leaving an exception where an expiry date is needed — which is how a
    37-day-expired certificate went unreported in the first place.

    The security property is that this connection is never used for anything:
    no request is written, no response is read, no data crosses it, and nothing
    becomes trusted as a result. The socket is opened, the peer's certificate
    bytes are taken from the handshake, and it is closed. Do not reuse this
    context for a real client — build a verifying one.
    """
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with socket.create_connection((host, port), timeout=timeout) as raw:
        with ctx.wrap_socket(raw, server_hostname=host) as tls:
            der = tls.getpeercert(binary_form=True)
    if not der:
        raise ssl.SSLError("peer presented no certificate")
    return der


def _covers(cert: x509.Certificate, host: str) -> bool:
    """Does the certificate's SAN list include this hostname?

    Only SANs are consulted. CN has not been a valid source of identity for
    browsers since 2017, so honouring it here would report a pass that Chrome
    and Safari would then refuse.
    """
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
    except x509.ExtensionNotFound:
        return False
    names = san.value.get_values_for_type(x509.DNSName)
    host = host.lower()
    for name in names:
        name = name.lower()
        if name == host:
            return True
        # One wildcard label, matching one label — `*.a.com` covers `b.a.com`
        # but not `a.com` or `c.b.a.com`.
        if name.startswith("*.") and host.count(".") == name.count("."):
            if host.split(".", 1)[1] == name[2:]:
                return True
    return False


def ca_fingerprint() -> str | None:
    """SHA-256 of the root this install hands out, colon-separated, or None.

    The same format `openssl x509 -fingerprint -sha256` and Keychain Access
    both print, so it can be compared by eye without converting anything.
    """
    from headroom.routes.ca_cert import CA_ROOT_PATH  # noqa: PLC0415 — cycle

    try:
        pem = CA_ROOT_PATH.read_bytes()
        cert = x509.load_pem_x509_certificate(pem)
    except Exception:  # noqa: BLE001 — absent on most installs, not an error
        return None
    digest = cert.fingerprint(hashes.SHA256())
    return ":".join(f"{b:02X}" for b in digest)


def check_certificate(timeout: float = DEFAULT_TIMEOUT) -> TlsStatus:
    """Inspect the served certificate. Never raises."""
    target = front_door()
    if target is None:
        return TlsStatus(applicable=False, ca_sha256=ca_fingerprint())
    host, port = target
    try:
        der = _fetch_peer_certificate(host, port, timeout)
        cert = x509.load_der_x509_certificate(der)
    except Exception as exc:  # noqa: BLE001 — a report, not a control path
        logger.warning("Could not read the TLS certificate for %s:%s: %s", host, port, exc)
        return TlsStatus(
            applicable=True, host=host, port=port,
            ca_sha256=ca_fingerprint(), error=str(exc),
        )

    not_after = cert.not_valid_after_utc
    not_before = cert.not_valid_before_utc
    remaining = (not_after - datetime.now(timezone.utc)).total_seconds() / 86400
    expired = remaining <= 0
    return TlsStatus(
        applicable=True,
        host=host,
        port=port,
        not_before=not_before,
        not_after=not_after,
        days_remaining=round(remaining, 2),
        expired=expired,
        needs_attention=remaining < RENEWAL_GRACE_DAYS,
        hostname_ok=_covers(cert, host),
        ca_sha256=ca_fingerprint(),
    )
