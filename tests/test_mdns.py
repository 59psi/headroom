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


async def test_mdns_port_parsing(monkeypatch):
    monkeypatch.setenv("HEADROOM_MDNS_PORT", "9000")
    assert mdns_service.mdns_port() == 9000
    monkeypatch.setenv("HEADROOM_MDNS_PORT", "not-a-port")
    assert mdns_service.mdns_port() == 8000
    monkeypatch.delenv("HEADROOM_MDNS_PORT")
    assert mdns_service.mdns_port() == 8000
