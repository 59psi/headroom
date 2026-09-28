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

That applies to the certificate AUTHORITY as much as to the leaf. The root
fingerprint (`ca_sha256`) is read from the exported `root.crt`, because a root
is never sent in a handshake — but on its own that file says what this install
HANDS OUT, not what it SERVES. After restoring an authority from a backup,
Caddy can go on serving a cached leaf from the authority it generated in the
meantime, and the file and the chain then disagree: the card used to label the
file "now serving" and report all-clear while every device refused the
connection. So the served chain is checked against that root too
(`chain_matches_ca`), signature by signature.

**It never gates readiness.** An expired certificate is not something restarting
this container can fix — the certificate belongs to Caddy — so failing the
health check would turn a broken padlock into a restart loop and take the app
down with it. Report, don't gate: the same reasoning that keeps an unconfigured
Anthropic key out of `/health/ready`.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
import ssl
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse

from cryptography import x509
from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes

# Both modules, read as attributes at call time: `config.settings.origin` and
# `ca_cert.CA_ROOT_PATH`. The path used to be imported inside `ca_fingerprint`
# under a "cycle" noqa that did not hold; the local import only ever mattered
# because it re-read the name on every call, which is what lets a test point it
# at a fixture. A module attribute does the same thing honestly.
from headroom import config
from headroom.routes import ca_cert

logger = logging.getLogger(__name__)

#: Warn this far ahead.
#:
#: Tuned to the 820-day certificates this deployment now issues (see
#: ./Caddyfile), not to Caddy's twelve-hour default. Under that default a
#: two-day warning was generous; against an 820-day cert it would fire two days
#: before an outage, which is a fire alarm that rings as the roof falls in.
#: Thirty days is enough notice to act without the warning becoming background
#: noise, and it still catches a stalled renewal long before anything breaks.
RENEWAL_GRACE_DAYS = 30

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
    #:
    #: Read from the exported root, so on its own it is what this install
    #: hands out — see `chain_matches_ca` for whether it is what is served.
    ca_sha256: str | None = None
    #: Does the chain Caddy actually SERVES lead up to that root? True when
    #: every link verifies, signature by signature; False when it leads
    #: somewhere else — a leaf from an authority this install no longer hands
    #: out, which every device that trusts `ca_sha256` refuses. None when it
    #: cannot be told: no exported root, no handshake, or an interpreter that
    #: exposes only the leaf (`get_unverified_chain` is Python 3.13+).
    chain_matches_ca: bool | None = None
    error: str | None = None


def front_door() -> tuple[str, int] | None:
    """Host and port of the HTTPS front door, or None if there isn't one.

    Taken from `config.settings.origin` — the same normalized value passkeys
    verify against, which the https overlays set to the name passkeys are
    bound to — so this checks the certificate for the origin the app actually
    claims, rather than a second guess at what it is. It read
    `HEADROOM_ORIGIN` from the environment itself, a second reader of one
    knob, and that is how the two came to disagree on whitespace. Read at CALL
    time (a module attribute, not a copy) so a test can point it elsewhere.
    The default, `http://localhost:8000`, is not https and so means "no front
    door", exactly as unset used to.
    """
    origin = config.settings.origin
    if not origin:
        return None
    parsed = urlparse(origin)
    if parsed.scheme != "https" or not parsed.hostname:
        return None
    return parsed.hostname, parsed.port or 443


def _fetch_peer_chain(host: str, port: int, timeout: float) -> tuple[list[bytes], bool]:
    """The chain as served, leaf first, with verification deliberately OFF.

    Returns `(chain, complete)`. `complete` is False only on an interpreter
    without `SSLSocket.get_unverified_chain` (Python < 3.13), where the leaf is
    all a handshake exposes — a partial answer that must not be read as "the
    server sent nothing else".

    `CERT_NONE` is the whole point, and is not the usual mistake it looks like.
    Disabling verification is dangerous when it makes an app *trust* an
    unverified peer; here it makes the app *look at* one. A verifying handshake
    fails on precisely the certificates this function exists to report on,
    leaving an exception where an expiry date is needed — which is how a
    37-day-expired certificate went unreported in the first place.

    The security property is that this connection is never used for anything:
    no request is written, no response is read, no data crosses it, and nothing
    becomes trusted as a result. The socket is opened, the peer's certificates
    are taken from the handshake, and it is closed; whether that chain leads to
    this install's root is then decided by `chain_matches_root`, checking each
    signature itself. Do not reuse this context for a real client — build a
    verifying one.
    """
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with socket.create_connection((host, port), timeout=timeout) as raw:
        with ctx.wrap_socket(raw, server_hostname=host) as tls:
            der = tls.getpeercert(binary_form=True)
            read_chain = getattr(tls, "get_unverified_chain", None)
            served = list(read_chain() or []) if read_chain is not None else None
    if not der:
        raise ssl.SSLError("peer presented no certificate")
    if not served:
        return [der], False
    return served, True


def _covers(cert: x509.Certificate, host: str) -> bool:
    """Does the certificate's SAN list include this host?

    Only SANs are consulted. CN has not been a valid source of identity for
    browsers since 2017, so honoring it here would report a pass that Chrome
    and Safari would then refuse.

    **An IP host is matched against IP SANs and never against DNS ones.** That
    is what browsers do, and getting it wrong here is worse than useless: since
    2.49 an install can serve on a bare address (`HEADROOM_SITE_ADDRESSES`),
    Caddy puts it in the certificate as an `IPAddress` SAN, and a DNS-only
    lookup finds nothing — so a perfectly good certificate gets reported as
    "doesn't cover this host, browsers will refuse it". A false alarm on the
    one card people consult when TLS is already confusing them.
    """
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
    except x509.ExtensionNotFound:
        return False

    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None:
        return address in san.value.get_values_for_type(x509.IPAddress)

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


def _exported_root() -> x509.Certificate | None:
    """The root this install hands out (`/api/public/ca-certificate`), or None."""
    try:
        return x509.load_pem_x509_certificate(ca_cert.CA_ROOT_PATH.read_bytes())
    except Exception:  # noqa: BLE001 — absent on most installs, not an error
        return None


def _fingerprint(cert: x509.Certificate) -> str:
    return ":".join(f"{b:02X}" for b in cert.fingerprint(hashes.SHA256()))


def ca_fingerprint() -> str | None:
    """SHA-256 of the root this install hands out, colon-separated, or None.

    The same format `openssl x509 -fingerprint -sha256` and Keychain Access
    both print, so it can be compared by eye without converting anything.
    """
    root = _exported_root()
    return _fingerprint(root) if root is not None else None


def _issued_by(cert: x509.Certificate, issuer: x509.Certificate) -> bool:
    """Did `issuer`'s key sign `cert`? Names alone prove nothing here.

    Every Caddy root is called `Caddy Local Authority - <year> ECC Root`, so a
    chain from a DIFFERENT authority matches this one's names exactly. Only the
    signature separates them.
    """
    try:
        cert.verify_directly_issued_by(issuer)
    except (ValueError, TypeError, InvalidSignature, UnsupportedAlgorithm):
        return False
    return True


def chain_matches_root(
    served: list[x509.Certificate], root: x509.Certificate | None, *, complete: bool,
) -> bool | None:
    """Does the served chain (leaf first) lead up to `root`?

    Walked link by link from the leaf, each step a signature check against
    the next certificate the server sent, until one is signed by `root` — or
    is `root`, for a server that sends its anchor too. A root is never
    required in the chain; that is what makes it a root.

    None when the answer is not knowable rather than False: with no root there
    is nothing to compare against, and with only the leaf (`complete=False`)
    a leaf signed by an intermediate the server did send cannot be told apart
    from one signed by a stranger.
    """
    if root is None or not served:
        return None
    root_fp = root.fingerprint(hashes.SHA256())
    if any(c.fingerprint(hashes.SHA256()) == root_fp for c in served):
        return True
    current, pool = served[0], list(served[1:])
    while True:
        if _issued_by(current, root):
            return True
        parent = next((c for c in pool if _issued_by(current, c)), None)
        if parent is None:
            return False if complete else None
        pool.remove(parent)
        current = parent


def check_certificate(timeout: float = DEFAULT_TIMEOUT) -> TlsStatus:
    """Inspect the served certificate. Never raises."""
    root = _exported_root()
    ca_sha256 = _fingerprint(root) if root is not None else None
    target = front_door()
    if target is None:
        return TlsStatus(applicable=False, ca_sha256=ca_sha256)
    host, port = target
    try:
        chain_der, complete = _fetch_peer_chain(host, port, timeout)
        served = [x509.load_der_x509_certificate(der) for der in chain_der]
    except Exception as exc:  # noqa: BLE001 — a report, not a control path
        logger.warning("Could not read the TLS certificate for %s:%s: %s", host, port, exc)
        return TlsStatus(
            applicable=True, host=host, port=port,
            ca_sha256=ca_sha256, error=str(exc),
        )

    cert = served[0]
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
        ca_sha256=ca_sha256,
        chain_matches_ca=chain_matches_root(served, root, complete=complete),
    )
