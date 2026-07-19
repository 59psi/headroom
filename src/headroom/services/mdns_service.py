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
"""

import logging
import os
import socket
from urllib.parse import urlsplit

from headroom.config import env_flag, settings

logger = logging.getLogger(__name__)

_aiozc = None  # zeroconf.asyncio.AsyncZeroconf | None — module-level singleton

# The only runtime-captured facts; everything else in mdns_status() is derived.
_ip: str | None = None
_error: str | None = None


def mdns_enabled() -> bool:
    return env_flag("HEADROOM_MDNS_ENABLED")


def mdns_hostname() -> str:
    """Advertised host label, normalized: 'headroom.local' / 'headroom.' → 'headroom'."""
    raw = os.environ.get("HEADROOM_MDNS_HOSTNAME", "headroom").strip().lower()
    return raw.removesuffix(".").removesuffix(".local").strip(".") or "headroom"


def mdns_port() -> int:
    try:
        return int(os.environ.get("HEADROOM_MDNS_PORT", "8000"))
    except ValueError:
        return 8000


def _mdns_interfaces(lan_ip: str) -> list[str] | None:
    """Which interface(s) zeroconf should bind to.

    Default: the single detected LAN IP. This matters inside a Docker host-net
    container (the recommended LAN/sidecar deployment): the host stack there
    also carries ``docker0`` and transient ``veth``/``br-`` interfaces, and
    zeroconf's default "all interfaces" mode binds a socket per interface —
    one flaky bridge socket can make the whole registration throw (caught
    silently → never advertises), and even when it registers the responder
    leaks onto the bridge and multicast can egress the wrong NIC, so the name
    never resolves on the LAN while the raw IP still works.

    Override with ``HEADROOM_MDNS_INTERFACE`` — an explicit IP to bind, or the
    literal ``all`` to restore zeroconf's pre-2.0.3 all-interfaces behavior.
    """
    override = os.environ.get("HEADROOM_MDNS_INTERFACE", "").strip()
    if override.lower() == "all":
        return None  # let zeroconf enumerate every interface itself
    return [override] if override else [lan_ip]


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


async def start_mdns() -> None:
    """Register the mDNS advertisement. Call once from the app lifespan."""
    global _aiozc, _ip, _error
    if not mdns_enabled() or _aiozc is not None:
        return
    ip = _lan_ip()
    if ip is None:
        logger.warning("mDNS: no LAN address found — not advertising")
        _error = "no LAN address found"
        return
    host, port = mdns_hostname(), mdns_port()
    aiozc = None
    try:
        from zeroconf import IPVersion, ServiceInfo
        from zeroconf.asyncio import AsyncZeroconf

        info = ServiceInfo(
            type_="_http._tcp.local.",
            name=f"{host}._http._tcp.local.",
            addresses=[socket.inet_aton(ip)],
            port=port,
            server=f"{host}.local.",
            properties={"path": "/"},
        )
        # Bind to the LAN interface only (not docker0/veth in a host-net
        # container) unless HEADROOM_MDNS_INTERFACE overrides it.
        interfaces = _mdns_interfaces(ip)
        zc_kwargs = {"ip_version": IPVersion.V4Only}
        if interfaces is not None:
            zc_kwargs["interfaces"] = interfaces
        aiozc = AsyncZeroconf(**zc_kwargs)
        # allow_name_change resolves instance-name conflicts; a conflicting
        # *hostname* (another device already owns <host>.local) raises and
        # lands in the except below.
        await aiozc.async_register_service(info, allow_name_change=True)
        _aiozc = aiozc
        _ip, _error = ip, None
        logger.info(
            "mDNS: advertising %s → %s (interfaces=%s)",
            _advertised_url(host, port), ip, interfaces or "all",
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
    global _aiozc, _ip
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
