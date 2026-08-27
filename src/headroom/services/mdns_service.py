"""LAN discovery — advertise the app as ``headroom.local`` via mDNS.

python-zeroconf answers A-record queries for the hostname attached to a
registered service, so registering a single ``_http._tcp`` service with
``server="headroom.local."`` makes http://headroom.local:8000 resolve on any
mDNS-capable client — macOS/iOS natively, Windows 10+, Linux with
avahi-daemon + nss-mdns.

Best-effort by design: any failure logs a warning and never blocks startup.
Docker note: multicast never crosses the default bridge network — use one of
the host-networking overlays (docker-compose.mdns.yml, or the http80 /
https-lan sidecar overlays) for the name to actually reach the LAN. In a
host-net container the responder is pinned to the detected LAN interface so it
doesn't leak onto docker0/veth (see ``_mdns_interfaces``); override with
``HEADROOM_MDNS_INTERFACE``.

**Both address families are advertised when the host has both, and that is a
load-bearing correctness fix, not thoroughness.** Advertising IPv4 alone made
every lookup of ``headroom.local`` stall for the client's full resolver
timeout — 5s on macOS, far worse on iOS, where Safari fires many parallel
requests and each one pays it. The site took over a minute to load and often
never did, while the TLS handshake itself measured 46ms.

The reason is a defect in python-zeroconf (0.150.0, the current release).
A responder that owns a name but has no AAAA is supposed to answer an AAAA
question with an **NSEC** record — a negative answer meaning "this name exists
and has only these types" (RFC 6762 §6.1) — which is what lets a client stop
waiting instantly. zeroconf builds that record with the wrong owner name:
``ServiceInfo._dns_nsec()`` passes ``self._name``, the service instance
(``headroom._http._tcp.local.``), where it must pass ``self.server``, the host
(``headroom.local.``). The assertion on the line above the call site —
``"Service server must be set for NSEC record."`` — shows ``server`` was
intended. An NSEC only asserts non-existence for the name it carries, so the
client correctly ignores an answer about a different name and keeps waiting.
Silence and a mis-named NSEC are indistinguishable to the querier.

It cannot be fixed from outside: zeroconf ships compiled Cython, so the call
is dispatched at C level and a ``ServiceInfo`` subclass overriding
``_dns_nsec`` is simply never consulted (measured, not assumed). Registering
both address types sidesteps it structurally — with nothing missing there is
no NSEC to get wrong, and IPv6 clients get a real answer instead of a negative
one. Hosts with no global IPv6 still hit the upstream bug; that is upstream's
to fix and is reported there.

A host that advertises AAAA but serves only IPv4 (the no-sidecar path — the
Dockerfile binds uvicorn to ``0.0.0.0``) is not a problem worth a reachability
probe: the client gets an immediate RST from the host's own kernel and Happy
Eyeballs falls back to IPv4 in milliseconds. A probe that returned a false
negative would reinstate the multi-second stall this exists to remove, which is
a far worse failure than one wasted round trip.
"""

import logging
import os
import socket
from urllib.parse import urlsplit

from headroom.config import env_flag, env_int, settings

logger = logging.getLogger(__name__)

_aiozc = None  # zeroconf.asyncio.AsyncZeroconf | None — module-level singleton

# The only runtime-captured facts; everything else in mdns_status() is derived.
_ip: str | None = None
_ipv6: str | None = None
_error: str | None = None


def mdns_enabled() -> bool:
    return env_flag("HEADROOM_MDNS_ENABLED")


def mdns_hostname() -> str:
    """Advertised host label, normalized: 'headroom.local' / 'headroom.' → 'headroom'."""
    raw = os.environ.get("HEADROOM_MDNS_HOSTNAME", "headroom").strip().lower()
    return raw.removesuffix(".").removesuffix(".local").strip(".") or "headroom"


def mdns_port() -> int:
    return env_int("HEADROOM_MDNS_PORT", 8000)


def _mdns_interfaces(lan_ips: list[str]):
    """Which interface(s) zeroconf should bind to.

    Default: the detected LAN addresses — IPv4, plus IPv6 when the host has a
    global one. This matters inside a Docker host-net container (the
    recommended LAN/sidecar deployment): the host stack there also carries
    ``docker0`` and transient ``veth``/``br-`` interfaces, and zeroconf's
    default "all interfaces" mode binds a socket per interface — one flaky
    bridge socket can make the whole registration throw (caught silently →
    never advertises), and even when it registers the responder leaks onto the
    bridge and multicast can egress the wrong NIC, so the name never resolves
    on the LAN while the raw IP still works.

    Override with ``HEADROOM_MDNS_INTERFACE`` — an explicit IP to bind, or the
    literal ``all`` to restore zeroconf's pre-2.0.3 all-interfaces behavior.
    An explicit override replaces the whole list rather than joining it: it
    exists to say "use exactly this NIC", and quietly binding a second address
    beside it would defeat the point.

    Returns whatever zeroconf's ``interfaces=`` accepts: a list of IPs, or
    ``InterfaceChoice.All`` (its own default) for the ``all`` escape hatch.
    """
    override = os.environ.get("HEADROOM_MDNS_INTERFACE", "").strip()
    if override.lower() == "all":
        from zeroconf import InterfaceChoice  # noqa: PLC0415 — lazy, as elsewhere

        return InterfaceChoice.All
    if override:
        return [override]
    return list(lan_ips)


def _advertised_url(host: str, port: int) -> str:
    """The URL shown on the Settings card and in the startup log.

    When the configured public origin already points at the mDNS name (the
    https-lan overlay sets both), it *is* the front door — use it verbatim
    instead of guessing the scheme from the port number.
    """
    if urlsplit(settings.origin).hostname == f"{host}.local":
        return settings.origin
    scheme = "https" if port == 443 else "http"
    suffix = "" if port in (80, 443) else f":{port}"
    return f"{scheme}://{host}.local{suffix}"


def mdns_status() -> dict:
    """Read-only snapshot for the Settings page — config is env-only."""
    advertising = _aiozc is not None
    host, port = mdns_hostname(), mdns_port()
    return {
        "enabled": mdns_enabled(),
        "advertising": advertising,
        "hostname": f"{host}.local",
        "port": port,
        "ip": _ip,
        "ipv6": _ipv6,
        "url": _advertised_url(host, port) if advertising else None,
        "error": _error,
    }


def _lan_ip() -> str | None:
    """Best-guess LAN IPv4: the source address the kernel picks for a UDP
    socket "connected" to a public IP. No packet is ever sent."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            ip: str = s.getsockname()[0]
    except OSError:
        return None
    return None if ip.startswith("127.") else ip


def _lan_ipv6() -> str | None:
    """Best-guess global LAN IPv6, by the same trick as ``_lan_ip``. No packet
    is sent — the kernel picks a source address and we read it back.

    Returns None unless the address is a *global* one. Link-local (``fe80::``)
    is rejected on purpose: it is only meaningful together with a scope id
    identifying the interface, so published as a bare AAAA it is unusable by
    the receiver and worse than publishing nothing. Any scope suffix the
    platform appends (``%en0``) is stripped, since ``inet_pton`` rejects it.
    """
    try:
        with socket.socket(socket.AF_INET6, socket.SOCK_DGRAM) as s:
            s.connect(("2001:4860:4860::8888", 80))
            ip: str = s.getsockname()[0]
    except OSError:
        return None
    ip = ip.split("%", 1)[0]
    if ip.startswith("fe80:") or ip in ("::1", "::"):
        return None
    try:
        socket.inet_pton(socket.AF_INET6, ip)
    except OSError:
        return None
    return ip


async def start_mdns() -> None:
    """Register the mDNS advertisement. Call once from the app lifespan."""
    global _aiozc, _ip, _ipv6, _error
    if not mdns_enabled() or _aiozc is not None:
        return
    ip = _lan_ip()
    if ip is None:
        logger.warning("mDNS: no LAN address found — not advertising")
        _error = "no LAN address found"
        return
    ipv6 = _lan_ipv6()
    host, port = mdns_hostname(), mdns_port()
    aiozc = None
    try:
        from zeroconf import IPVersion, ServiceInfo
        from zeroconf.asyncio import AsyncZeroconf

        # Publish every family the host actually has. Advertising IPv4 alone
        # is what made every lookup stall for the client's full resolver
        # timeout — see the module docstring for the upstream NSEC defect this
        # sidesteps. IPv4 stays first: it is the one we know is served.
        addresses = [socket.inet_aton(ip)]
        if ipv6:
            addresses.append(socket.inet_pton(socket.AF_INET6, ipv6))

        info = ServiceInfo(
            type_="_http._tcp.local.",
            name=f"{host}._http._tcp.local.",
            addresses=addresses,
            port=port,
            server=f"{host}.local.",
            properties={"path": "/"},
        )
        interfaces = _mdns_interfaces([ip, ipv6] if ipv6 else [ip])
        # V4Only when that is all we have, so a host without IPv6 doesn't bind
        # a v6 socket it can do nothing with.
        ip_version = IPVersion.All if ipv6 else IPVersion.V4Only
        aiozc = AsyncZeroconf(ip_version=ip_version, interfaces=interfaces)
        # allow_name_change resolves instance-name conflicts; a conflicting
        # *hostname* (another device already owns <host>.local) raises and
        # lands in the except below.
        await aiozc.async_register_service(info, allow_name_change=True)
        _aiozc = aiozc
        _ip, _ipv6, _error = ip, ipv6, None
        logger.info(
            "mDNS: advertising %s → %s (interfaces=%s)",
            _advertised_url(host, port), ", ".join(filter(None, (ip, ipv6))), interfaces,
        )
    except Exception as exc:  # noqa: BLE001 — LAN convenience, never fatal
        logger.warning("mDNS registration failed (%s.local): %s", host, exc)
        _error = str(exc)
        if aiozc is not None:
            try:
                await aiozc.async_close()
            except Exception:  # noqa: BLE001
                pass


async def stop_mdns() -> None:
    """Withdraw the advertisement (sends goodbye packets) and close sockets."""
    global _aiozc, _ip, _ipv6
    if _aiozc is None:
        return
    try:
        # async_close() unregisters all services itself — calling
        # async_unregister_all_services() first would broadcast the goodbye
        # packets twice and double the shutdown sleeps.
        await _aiozc.async_close()
    except Exception as exc:  # noqa: BLE001
        logger.debug("mDNS shutdown error: %s", exc)
    _aiozc = None
    _ip = None
    _ipv6 = None
