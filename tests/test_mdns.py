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
    assert mdns_service._mdns_interfaces(["192.168.1.5"]) == ["192.168.1.5"]
    # Both families are bound when the host has both.
    assert mdns_service._mdns_interfaces(["192.168.1.5", "2600:1::5"]) == [
        "192.168.1.5",
        "2600:1::5",
    ]


async def test_mdns_interfaces_override_and_all(monkeypatch):
    from zeroconf import InterfaceChoice

    # An explicit override REPLACES the list — it means "use exactly this NIC",
    # so quietly binding the detected v6 address beside it would defeat it.
    monkeypatch.setenv("HEADROOM_MDNS_INTERFACE", "10.0.0.9")
    assert mdns_service._mdns_interfaces(["192.168.1.5", "2600:1::5"]) == ["10.0.0.9"]
    # The literal "all" (any case) restores zeroconf's all-interfaces default.
    monkeypatch.setenv("HEADROOM_MDNS_INTERFACE", "all")
    assert mdns_service._mdns_interfaces(["192.168.1.5"]) is InterfaceChoice.All
    monkeypatch.setenv("HEADROOM_MDNS_INTERFACE", "ALL")
    assert mdns_service._mdns_interfaces(["192.168.1.5"]) is InterfaceChoice.All


# ---------------- IPv6: the >60s "handshake" that was never a handshake ------ #


async def test_lan_ipv6_rejects_link_local(monkeypatch):
    """A bare fe80:: AAAA is unusable to the receiver — it needs a scope id."""
    import socket as _socket

    class _FakeSock:
        def __init__(self, addr):
            self._addr = addr

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def connect(self, _target):
            pass

        def getsockname(self):
            return (self._addr, 0, 0, 0)

    def fake_socket_factory(addr):
        def _factory(*_args, **_kwargs):
            return _FakeSock(addr)

        return _factory

    for addr, expected in [
        ("2600:6c52:7500:a7b::1", "2600:6c52:7500:a7b::1"),
        ("2600:6c52:7500:a7b::1%en0", "2600:6c52:7500:a7b::1"),  # scope stripped
        ("fe80::1471:2eda:a7a3:172c", None),
        ("::1", None),
        ("not-an-address", None),
    ]:
        monkeypatch.setattr(_socket, "socket", fake_socket_factory(addr))
        assert mdns_service._lan_ipv6() == expected, addr


async def _capture_registration(monkeypatch, *, ipv4, ipv6):
    """Run start_mdns() against a fake AsyncZeroconf and return what it registered."""
    import zeroconf.asyncio as zasync

    monkeypatch.setenv("HEADROOM_MDNS_ENABLED", "true")
    monkeypatch.delenv("HEADROOM_MDNS_INTERFACE", raising=False)
    monkeypatch.setattr(mdns_service, "_lan_ip", lambda: ipv4)
    monkeypatch.setattr(mdns_service, "_lan_ipv6", lambda: ipv6)
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
    return captured


def _address_answer_names(info):
    """Names of the records this advertisement offers for hostname questions,
    as {record type: owner name}. This is what a querying client actually sees."""
    return {record.type: record.name for record in info.get_address_and_nsec_records()}


async def test_advertises_both_address_families_so_aaaa_is_answerable(monkeypatch):
    """Regression for the >60s page load.

    Advertising IPv4 alone left every AAAA question for the hostname
    unanswered — not refused, *unanswered* — so every client burned its full
    resolver timeout on every lookup (5s on macOS, far worse on iOS). The TLS
    handshake was 46ms the whole time.

    The rule this pins: every address type must be accounted for under the
    HOSTNAME. See the module docstring for the upstream zeroconf defect that
    makes a v4-only advertisement file its negative answer under the service
    name instead, where no client will look for it.
    """
    from zeroconf import IPVersion
    from zeroconf.const import _TYPE_A, _TYPE_AAAA

    captured = await _capture_registration(
        monkeypatch, ipv4="192.168.7.42", ipv6="2600:6c52:7500:a7b::99"
    )
    try:
        info = captured["info"]
        # NOT `info.addresses` — that property is legacy and returns IPv4 only,
        # so asserting on it would report "no IPv6 registered" on a correctly
        # dual-stacked advertisement.
        assert info.parsed_addresses(IPVersion.All) == [
            "192.168.7.42",
            "2600:6c52:7500:a7b::99",
        ]
        # Both sockets bound, both interfaces pinned (no docker0/veth leak).
        assert captured["kwargs"].get("interfaces") == [
            "192.168.7.42",
            "2600:6c52:7500:a7b::99",
        ]
        assert captured["kwargs"].get("ip_version") is IPVersion.All

        # The property that actually fixes the stall: a client asking the
        # HOSTNAME for either address type finds a record bearing that name.
        answers = _address_answer_names(info)
        assert answers.get(_TYPE_A) == "headroom.local."
        assert answers.get(_TYPE_AAAA) == "headroom.local."
    finally:
        await mdns_service.stop_mdns()


async def test_ipv4_only_host_still_binds_v4_only(monkeypatch):
    """No global IPv6 → don't bind a v6 socket we can do nothing with.

    Such a host still trips the upstream NSEC defect; that is upstream's to fix
    and there is no way to correct it from here (zeroconf ships compiled
    Cython, so a ServiceInfo subclass overriding _dns_nsec is never consulted).
    This test exists so the v4-only path stays deliberate rather than becoming
    an accident of a future edit.
    """
    from zeroconf import IPVersion

    captured = await _capture_registration(monkeypatch, ipv4="192.168.7.42", ipv6=None)
    try:
        # The address list itself is asserted by test_start_mdns_pins_lan_interface;
        # what is specific here is that we do not open an unusable v6 socket.
        assert captured["kwargs"].get("ip_version") is IPVersion.V4Only
    finally:
        await mdns_service.stop_mdns()


async def test_status_reports_the_advertised_ipv6(monkeypatch):
    """The Settings card must show what is actually being advertised — an
    advertised address the operator can't see is one they can't diagnose."""
    captured = await _capture_registration(
        monkeypatch, ipv4="192.168.7.42", ipv6="2600:6c52:7500:a7b::99"
    )
    try:
        assert captured["info"] is not None
        status = mdns_service.mdns_status()
        assert status["ip"] == "192.168.7.42"
        assert status["ipv6"] == "2600:6c52:7500:a7b::99"
    finally:
        await mdns_service.stop_mdns()
    # Withdrawn advertisement must not keep reporting a stale address.
    assert mdns_service.mdns_status()["ipv6"] is None


async def test_start_mdns_pins_lan_interface(monkeypatch):
    """Regression (the Docker/sidecar bug): the responder must bind the detected
    LAN interface only — not all interfaces, where docker0/veth break it — and
    the A-record must carry that LAN IP.

    ``_lan_ipv6`` is pinned to None rather than left live: this asserts the
    exact interface list, and on any host that has a global IPv6 the real
    detector would (correctly) add a second address and fail it for the wrong
    reason. The v6 path has its own tests below.
    """
    import socket

    captured = await _capture_registration(monkeypatch, ipv4="192.168.7.42", ipv6=None)
    try:
        assert captured["kwargs"].get("interfaces") == ["192.168.7.42"]
        assert captured["info"].addresses == [socket.inet_aton("192.168.7.42")]
    finally:
        await mdns_service.stop_mdns()  # resets the module singleton
