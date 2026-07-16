"""LAN discovery — advertise the app as ``headroom.local`` via mDNS.

python-zeroconf answers A-record queries for the hostname attached to a
registered service, so registering a single ``_http._tcp`` service with
``server="headroom.local."`` makes http://headroom.local:8000 resolve on any
mDNS-capable client — macOS/iOS natively, Windows 10+, Linux with
avahi-daemon + nss-mdns.

Best-effort by design: any failure logs a warning and never blocks startup.
Docker note: multicast never crosses the default bridge network — use the
docker-compose.mdns.yml overlay (host networking, Linux/Pi only) for the
name to actually reach the LAN.
"""

import logging
import os
import socket

logger = logging.getLogger(__name__)

_aiozc = None  # zeroconf.asyncio.AsyncZeroconf | None — module-level singleton

# Live outcome of the last start/stop, surfaced read-only on the Settings page.
_status: dict = {"advertising": False, "ip": None, "url": None, "error": None}


def mdns_enabled() -> bool:
    return os.environ.get("HEADROOM_MDNS_ENABLED", "true").lower() in ("1", "true", "yes")


def mdns_hostname() -> str:
    """Advertised host label, normalized: 'headroom.local' / 'headroom.' → 'headroom'."""
    raw = os.environ.get("HEADROOM_MDNS_HOSTNAME", "headroom").strip().lower()
    return raw.removesuffix(".").removesuffix(".local").strip(".") or "headroom"


def mdns_port() -> int:
    try:
        return int(os.environ.get("HEADROOM_MDNS_PORT", "8000"))
    except ValueError:
        return 8000


def _advertised_url(host: str, port: int) -> str:
    scheme = "https" if port == 443 else "http"
    suffix = "" if port in (80, 443) else f":{port}"
    return f"{scheme}://{host}.local{suffix}"


def mdns_status() -> dict:
    """Read-only snapshot for the Settings page — config is env-only."""
    return {
        "enabled": mdns_enabled(),
        "hostname": f"{mdns_hostname()}.local",
        "port": mdns_port(),
        **_status,
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
    global _aiozc
    if not mdns_enabled() or _aiozc is not None:
        return
    ip = _lan_ip()
    if ip is None:
        logger.warning("mDNS: no LAN address found — not advertising")
        _status["error"] = "no LAN address found"
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
        aiozc = AsyncZeroconf(ip_version=IPVersion.V4Only)
        # allow_name_change resolves instance-name conflicts; a conflicting
        # *hostname* (another device already owns <host>.local) raises and
        # lands in the except below.
        await aiozc.async_register_service(info, allow_name_change=True)
        _aiozc = aiozc
        _status.update(
            advertising=True, ip=ip, url=_advertised_url(host, port), error=None
        )
        logger.info("mDNS: advertising %s → %s", _advertised_url(host, port), ip)
    except Exception as exc:  # noqa: BLE001 — LAN convenience, never fatal
        logger.warning("mDNS registration failed (%s.local): %s", host, exc)
        _status["error"] = str(exc)
        if aiozc is not None:
            try:
                await aiozc.async_close()
            except Exception:  # noqa: BLE001
                pass


async def stop_mdns() -> None:
    """Withdraw the advertisement (sends goodbye packets) and close sockets."""
    global _aiozc
    if _aiozc is None:
        return
    try:
        await _aiozc.async_unregister_all_services()
        await _aiozc.async_close()
    except Exception as exc:  # noqa: BLE001
        logger.debug("mDNS shutdown error: %s", exc)
    _aiozc = None
    _status.update(advertising=False, ip=None, url=None)
