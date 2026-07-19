"""mDNS advertising — config gating + name/port normalization.

Real registration opens multicast sockets, so tests only exercise the pure
helpers and the disabled path; `start_mdns()` must be a no-op when
HEADROOM_MDNS_ENABLED is false (conftest sets it for the whole suite).
"""

import pytest

from headroom.services import mdns_service

pytestmark = pytest.mark.anyio


async def test_start_mdns_noop_when_disabled(monkeypatch):
    monkeypatch.setenv("HEADROOM_MDNS_ENABLED", "false")
    await mdns_service.start_mdns()
    assert mdns_service._aiozc is None
    # stop after a never-started advertisement must be safe too
    await mdns_service.stop_mdns()


async def test_mdns_enabled_parsing(monkeypatch):
    for raw, expected in [
        ("false", False),
        ("0", False),
        ("no", False),
        ("true", True),
        ("1", True),
        ("YES", True),
    ]:
        monkeypatch.setenv("HEADROOM_MDNS_ENABLED", raw)
        assert mdns_service.mdns_enabled() is expected


async def test_mdns_hostname_normalization(monkeypatch):
    for raw, expected in [
        ("headroom", "headroom"),
        ("headroom.local", "headroom"),
        ("Hats.Local.", "hats"),
        (".local", "headroom"),
        ("", "headroom"),
        ("  lids  ", "lids"),
    ]:
        monkeypatch.setenv("HEADROOM_MDNS_HOSTNAME", raw)
        assert mdns_service.mdns_hostname() == expected
    monkeypatch.delenv("HEADROOM_MDNS_HOSTNAME")
    assert mdns_service.mdns_hostname() == "headroom"


async def test_advertised_url_scheme_and_port():
    assert mdns_service._advertised_url("headroom", 8000) == "http://headroom.local:8000"
    assert mdns_service._advertised_url("headroom", 443) == "https://headroom.local"
    assert mdns_service._advertised_url("headroom", 80) == "http://headroom.local"
    assert mdns_service._advertised_url("hats", 9000) == "http://hats.local:9000"


async def test_advertised_url_prefers_matching_origin(monkeypatch):
    """When HEADROOM_ORIGIN already points at the mDNS name (https-lan overlay),
    it is the front door — no scheme guessing from the port."""
    from headroom.config import settings

    monkeypatch.setattr(settings, "origin", "https://headroom.local:8443")
    assert mdns_service._advertised_url("headroom", 8443) == "https://headroom.local:8443"
    # different hostname → origin doesn't apply, port heuristic stands
    assert mdns_service._advertised_url("hats", 8443) == "http://hats.local:8443"


async def test_mdns_status_endpoint_disabled(client):
    """conftest disables mDNS suite-wide → endpoint reports disabled, idle."""
    resp = await client.get("/api/settings/mdns")
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is False
    assert body["advertising"] is False
    assert body["hostname"] == "headroom.local"
    assert body["url"] is None


async def test_mdns_status_endpoint_requires_auth(anon_client):
    resp = await anon_client.get("/api/settings/mdns")
    assert resp.status_code == 401


async def test_mdns_port_parsing(monkeypatch):
    monkeypatch.setenv("HEADROOM_MDNS_PORT", "9000")
    assert mdns_service.mdns_port() == 9000
    monkeypatch.setenv("HEADROOM_MDNS_PORT", "not-a-port")
    assert mdns_service.mdns_port() == 8000
    monkeypatch.delenv("HEADROOM_MDNS_PORT")
    assert mdns_service.mdns_port() == 8000


# ------------------ interface pinning (Docker host-net fix) ------------ #


async def test_mdns_interfaces_defaults_to_lan_ip(monkeypatch):
    monkeypatch.delenv("HEADROOM_MDNS_INTERFACE", raising=False)
    assert mdns_service._mdns_interfaces("192.168.1.5") == ["192.168.1.5"]


async def test_mdns_interfaces_override_and_all(monkeypatch):
    monkeypatch.setenv("HEADROOM_MDNS_INTERFACE", "10.0.0.9")
    assert mdns_service._mdns_interfaces("192.168.1.5") == ["10.0.0.9"]
    # The literal "all" (any case) restores zeroconf's all-interfaces default.
    monkeypatch.setenv("HEADROOM_MDNS_INTERFACE", "all")
    assert mdns_service._mdns_interfaces("192.168.1.5") is None
    monkeypatch.setenv("HEADROOM_MDNS_INTERFACE", "ALL")
    assert mdns_service._mdns_interfaces("192.168.1.5") is None


async def test_start_mdns_pins_lan_interface(monkeypatch):
    """Regression (the Docker/sidecar bug): the responder must bind the detected
    LAN interface only — not all interfaces, where docker0/veth break it — and
    the A-record must carry that LAN IP."""
    import socket

    import zeroconf.asyncio as zasync

    monkeypatch.setenv("HEADROOM_MDNS_ENABLED", "true")
    monkeypatch.delenv("HEADROOM_MDNS_INTERFACE", raising=False)
    monkeypatch.setattr(mdns_service, "_lan_ip", lambda: "192.168.7.42")
    monkeypatch.setattr(mdns_service, "_aiozc", None)

    captured: dict = {}

    class _FakeAIOZC:
        def __init__(self, *args, **kwargs):
            captured["kwargs"] = kwargs

        async def async_register_service(self, info, allow_name_change=False):
            captured["info"] = info

        async def async_close(self):
            pass

    monkeypatch.setattr(zasync, "AsyncZeroconf", _FakeAIOZC)

    await mdns_service.start_mdns()
    try:
        assert captured["kwargs"].get("interfaces") == ["192.168.7.42"]
        assert captured["info"].addresses == [socket.inet_aton("192.168.7.42")]
    finally:
        await mdns_service.stop_mdns()  # resets the module singleton
