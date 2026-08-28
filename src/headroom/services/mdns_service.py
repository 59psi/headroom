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

import asyncio
import logging
import os
import socket
import struct
from urllib.parse import urlsplit

from headroom.config import env_flag, env_int, settings

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Negative answers (NSEC) — the other half of the stall described above.
#
# Advertising both address families fixed AAAA. It could not fix anything else,
# because the defect is not about addresses: zeroconf answers a query for a
# type it does not hold at our hostname with SILENCE, and a resolver that gets
# silence from a name it believes exists waits out its full timeout.
#
# That is not hypothetical and it is not only AAAA. Probing the live
# advertisement for each record type:
#
#     A           answered in 0.002s
#     AAAA        answered in 0.001s
#     HTTPS/SVCB  NO ANSWER in 4.0s
#     SRV         NO ANSWER in 4.0s
#
# iOS Safari queries the HTTPS record (type 65) before connecting, so every
# navigation to https://headroom.local paid that timeout — while `curl` and
# `getaddrinfo`, which only ever ask for A/AAAA, measured 3ms and looked
# perfect. Testing with curl is what made this look fixed when it was not.
#
# RFC 6762 §6.1 is explicit: a responder that owns a name must answer a query
# for an absent type with an NSEC record asserting which types DO exist at that
# name. So we send one. This is a targeted addition, not a second responder —
# it answers ONLY for our own hostname, and only for types zeroconf has no
# answer for, so it can never contradict or race the real advertisement.
# --------------------------------------------------------------------------- #

_MDNS_GROUP = "224.0.0.251"
_MDNS_PORT = 5353

#: The record types our advertisement actually holds at the hostname. Anything
#: else gets a negative answer. A/AAAA are excluded because zeroconf answers
#: them itself; ANY is excluded because it is never a negative answer.
_HELD_TYPES = (1, 28)
_TYPE_NSEC = 47
_QTYPE_ANY = 255

#: RFC 6762 §10: 120s for records tied to a specific host.
_NSEC_TTL = 120
#: Cache-flush bit | class IN. We are authoritative for this name.
_CLASS_FLUSH_IN = 0x8001

_nsec_transport = None  # asyncio.DatagramTransport | None


def _encode_name(name: str) -> bytes:
    out = bytearray()
    for label in name.rstrip(".").split("."):
        raw = label.encode("utf-8")
        out.append(len(raw))
        out += raw
    out.append(0)
    return bytes(out)


def _read_name(buf: bytes, off: int) -> tuple[str | None, int]:
    """Decode a QNAME. Refuses compression pointers rather than guessing.

    Questions do not use compression in practice, and a wrong guess here would
    make us answer for a name we do not own — far worse than staying silent.
    """
    parts: list[str] = []
    while True:
        if off >= len(buf):
            return None, off
        n = buf[off]
        if n == 0:
            return ".".join(parts), off + 1
        if n & 0xC0:
            return None, off
        off += 1
        parts.append(buf[off:off + n].decode("utf-8", "replace"))
        off += n


def _type_bitmap(types: tuple[int, ...]) -> bytes:
    """RFC 4034 §4.1.2 type bitmap. One window is enough — every type is < 256."""
    length = max(types) // 8 + 1
    bits = bytearray(length)
    for t in types:
        bits[t // 8] |= 0x80 >> (t % 8)
    return bytes([0, length]) + bytes(bits)


def nsec_payload(hostname: str) -> bytes:
    """A response whose single answer is "this name has only A and AAAA"."""
    owner = _encode_name(hostname)
    rdata = owner + _type_bitmap(_HELD_TYPES)
    header = struct.pack(">HHHHHH", 0, 0x8400, 0, 1, 0, 0)  # QR + AA, 1 answer
    rr = owner + struct.pack(
        ">HHIH", _TYPE_NSEC, _CLASS_FLUSH_IN, _NSEC_TTL, len(rdata)
    ) + rdata
    return header + rr


def nsec_reply_for(query: bytes, hostname: str) -> tuple[bytes, bool] | None:
    """`(payload, unicast)` if this query deserves a negative answer, else None.

    Pure, so the decision is testable without a socket — which matters, because
    the failure mode being fixed is *silence*, and silence is exactly what a
    broken implementation of this would also produce.
    """
    if len(query) < 12:
        return None
    flags, qdcount = struct.unpack(">HH", query[2:6])
    if flags & 0x8000 or qdcount == 0:
        return None  # a response, or a query asking nothing

    target = hostname.rstrip(".").lower()
    off, matched, unicast = 12, False, False
    for _ in range(qdcount):
        name, off = _read_name(query, off)
        if name is None or off + 4 > len(query):
            return None
        qtype, qclass = struct.unpack(">HH", query[off:off + 4])
        off += 4
        if name.lower() != target:
            continue  # not our name — never answer for someone else's
        if qtype in _HELD_TYPES or qtype == _QTYPE_ANY:
            continue  # zeroconf has a real answer; ours would be a duplicate
        matched = True
        # QU bit: the querier asked for a unicast reply.
        unicast = unicast or bool(qclass & 0x8000)

    return (nsec_payload(hostname), unicast) if matched else None


class _NsecProtocol(asyncio.DatagramProtocol):
    """Answers only the queries zeroconf leaves unanswered, for our name only."""

    def __init__(self, hostname: str) -> None:
        self._hostname = hostname
        self._transport = None

    def connection_made(self, transport) -> None:
        self._transport = transport

    def datagram_received(self, data: bytes, addr) -> None:
        if self._transport is None:
            return
        try:
            reply = nsec_reply_for(data, self._hostname)
        except Exception:  # noqa: BLE001 — a malformed packet must not kill us
            return
        if reply is None:
            return
        payload, unicast = reply
        try:
            self._transport.sendto(
                payload, addr if unicast else (_MDNS_GROUP, _MDNS_PORT)
            )
        except OSError:
            pass  # LAN convenience; a send failure is never fatal


async def _start_nsec_responder(hostname: str, ip: str):
    """Bind alongside zeroconf (and avahi) to serve negative answers.

    SO_REUSEPORT is what lets several responders share 5353 — the Pi already
    runs avahi and zeroconf on it together, so this is the arrangement already
    in use rather than a new one. Multicast is delivered to every joined
    socket, so all of them see each query and each answers for what it owns.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    except (AttributeError, OSError):
        pass
    sock.bind(("", _MDNS_PORT))
    sock.setsockopt(
        socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
        socket.inet_aton(_MDNS_GROUP) + socket.inet_aton(ip),
    )
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(ip))
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
    sock.setblocking(False)

    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        lambda: _NsecProtocol(f"{hostname}.local"), sock=sock
    )
    return transport

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

        # Negative answers for every other record type. Separately guarded: if
        # binding 5353 alongside zeroconf fails, the advertisement above is
        # still good and the app still resolves — it just resolves slowly for
        # clients that ask for a type we do not hold.
        global _nsec_transport
        try:
            _nsec_transport = await _start_nsec_responder(host, ip)
            logger.info("mDNS: answering absent-type queries for %s.local with NSEC", host)
        except OSError as exc:
            logger.warning(
                "mDNS: could not serve NSEC for %s.local (%s) — clients asking "
                "for HTTPS/SVCB records may stall", host, exc,
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
    global _aiozc, _ip, _ipv6, _nsec_transport
    # Closed first and unconditionally: it binds 5353, and leaving it open
    # across a restart is what makes the next bind fail.
    if _nsec_transport is not None:
        try:
            _nsec_transport.close()
        except Exception as exc:  # noqa: BLE001
            logger.debug("mDNS NSEC responder shutdown error: %s", exc)
        _nsec_transport = None
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
