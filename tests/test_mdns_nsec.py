"""Negative answers for record types the advertisement does not hold.

Advertising both address families (2.61.0) fixed AAAA and nothing else, because
the defect was never about addresses: zeroconf answers a query for an absent
type at our hostname with SILENCE, and a resolver that gets silence from a name
it believes exists waits out its full timeout.

Probed against the live advertisement, per record type:

    A           answered in 0.002s
    AAAA        answered in 0.001s
    HTTPS/SVCB  NO ANSWER in 4.0s
    SRV         NO ANSWER in 4.0s

iOS Safari asks for the HTTPS record (type 65) before connecting, so every
navigation paid that timeout — while curl and getaddrinfo, which only ask for
A/AAAA, measured 3ms and made it look fixed.

These tests are on the PURE decision function on purpose. The bug is silence,
and a broken fix produces silence too, so "it didn't crash" proves nothing —
only the bytes do.
"""

from __future__ import annotations

import struct

import pytest

from headroom.services.mdns_service import (
    _encode_name,
    _type_bitmap,
    nsec_payload,
    nsec_reply_for,
)

pytestmark = pytest.mark.anyio

HOST = "headroom.local"

TYPE_A, TYPE_AAAA, TYPE_NSEC, TYPE_SRV, TYPE_HTTPS, TYPE_ANY = 1, 28, 47, 33, 65, 255


def query(name: str, qtype: int, *, unicast: bool = False) -> bytes:
    qclass = 0x8001 if unicast else 0x0001
    header = struct.pack(">HHHHHH", 0, 0, 1, 0, 0, 0)
    return header + _encode_name(name) + struct.pack(">HH", qtype, qclass)


async def test_an_absent_type_gets_a_negative_answer():
    """The whole bug: type 65 used to get nothing at all."""
    reply = nsec_reply_for(query(HOST, TYPE_HTTPS), HOST)
    assert reply is not None, (
        "silence here is the bug — iOS asks for this on every navigation"
    )
    payload, unicast = reply
    assert unicast is False
    assert struct.unpack(">H", payload[6:8])[0] == 1, "exactly one answer"


async def test_the_answer_is_an_nsec_owned_by_our_hostname():
    """The owner name is the whole point.

    Upstream builds this record with the SERVICE INSTANCE name instead of the
    host, and an NSEC only asserts non-existence for the name it carries — so
    a mis-named one is indistinguishable from silence to the querier. That is
    precisely the defect being worked around, so it must be pinned here.
    """
    payload = nsec_payload(HOST)
    owner = _encode_name(HOST)
    rr = payload[12:]
    assert rr.startswith(owner), "the NSEC must be owned by headroom.local"

    rtype, rclass = struct.unpack(">HH", rr[len(owner):len(owner) + 4])
    assert rtype == TYPE_NSEC
    assert rclass & 0x8000, "cache-flush: we are authoritative for this name"

    # RDATA is the next-domain name (itself, in mDNS) plus the type bitmap.
    rdlen = struct.unpack(">H", rr[len(owner) + 8:len(owner) + 10])[0]
    rdata = rr[len(owner) + 10:len(owner) + 10 + rdlen]
    assert rdata.startswith(owner)
    assert rdata[len(owner):] == _type_bitmap((TYPE_A, TYPE_AAAA))


async def test_the_bitmap_says_exactly_A_and_AAAA_exist():
    """A bitmap claiming a type we cannot serve would be worse than silence."""
    bitmap = _type_bitmap((TYPE_A, TYPE_AAAA))
    assert bitmap == bytes([0, 4, 0x40, 0x00, 0x00, 0x08])

    present = {
        t for t in range(8 * bitmap[1])
        if bitmap[2 + t // 8] & (0x80 >> (t % 8))
    }
    assert present == {TYPE_A, TYPE_AAAA}


@pytest.mark.parametrize("qtype", [TYPE_A, TYPE_AAAA, TYPE_ANY])
async def test_types_zeroconf_answers_are_left_alone(qtype):
    """Never duplicate a real answer, and never negate one.

    A and AAAA are advertised; ANY is never a negative answer. Replying here
    would put a contradicting record on the wire against our own responder.
    """
    assert nsec_reply_for(query(HOST, qtype), HOST) is None


async def test_another_hosts_name_is_never_answered_for():
    """Answering for a name we do not own would break that other device."""
    assert nsec_reply_for(query("printer.local", TYPE_HTTPS), HOST) is None


async def test_the_unicast_bit_is_honored():
    """QU set means the querier wants the reply direct, not on the group."""
    _, unicast = nsec_reply_for(query(HOST, TYPE_HTTPS, unicast=True), HOST)
    assert unicast is True


async def test_responses_are_not_treated_as_questions():
    """Answering someone else's answer would be a broadcast storm."""
    response = bytearray(query(HOST, TYPE_HTTPS))
    struct.pack_into(">H", response, 2, 0x8400)  # QR + AA
    assert nsec_reply_for(bytes(response), HOST) is None


@pytest.mark.parametrize("junk", [b"", b"\x00", b"\x00" * 11, b"\xff" * 12])
async def test_malformed_packets_are_ignored_not_fatal(junk):
    """5353 is a public port on the LAN; anything can arrive on it."""
    assert nsec_reply_for(junk, HOST) is None


async def test_a_compression_pointer_in_a_question_is_refused():
    """Guessing the name could make us answer for someone else's."""
    header = struct.pack(">HHHHHH", 0, 0, 1, 0, 0, 0)
    pointer = header + b"\xc0\x0c" + struct.pack(">HH", TYPE_HTTPS, 0x0001)
    assert nsec_reply_for(pointer, HOST) is None


async def test_srv_at_the_host_name_is_also_negative():
    """Not just type 65 — the probe showed SRV stalling identically.

    Fixing only the type that happened to be reported would leave the next
    resolver that asks for something else stalling exactly the same way.
    """
    assert nsec_reply_for(query(HOST, TYPE_SRV), HOST) is not None


async def test_the_responder_really_answers_on_a_socket():
    """End to end over a real socket, not just the byte builder.

    The unit tests above prove the packet is correct. They cannot prove it ever
    reaches the wire — and "the bytes were fine but nothing was sent" is
    indistinguishable, from the client's side, from the stall being fixed here.
    Loopback with the QU bit set, so this needs no multicast and runs anywhere.
    """
    import asyncio
    import socket as sock_mod

    from headroom.services.mdns_service import _NsecProtocol

    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        lambda: _NsecProtocol(HOST), local_addr=("127.0.0.1", 0)
    )
    try:
        port = transport.get_extra_info("socket").getsockname()[1]

        client = sock_mod.socket(sock_mod.AF_INET, sock_mod.SOCK_DGRAM)
        client.settimeout(5)
        try:
            client.sendto(query(HOST, TYPE_HTTPS, unicast=True), ("127.0.0.1", port))
            data, _ = await asyncio.get_running_loop().run_in_executor(
                None, client.recvfrom, 4096
            )
        finally:
            client.close()
    finally:
        transport.close()

    assert struct.unpack(">H", data[6:8])[0] == 1
    rr = data[12:]
    owner = _encode_name(HOST)
    assert rr.startswith(owner)
    assert struct.unpack(">H", rr[len(owner):len(owner) + 2])[0] == TYPE_NSEC


async def test_a_query_for_a_type_we_hold_draws_no_packet_at_all():
    """Silence is correct HERE — zeroconf is answering, and two responders
    putting records for the same name on the wire is a conflict, not a fix."""
    import asyncio
    import socket as sock_mod

    from headroom.services.mdns_service import _NsecProtocol

    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        lambda: _NsecProtocol(HOST), local_addr=("127.0.0.1", 0)
    )
    try:
        port = transport.get_extra_info("socket").getsockname()[1]
        client = sock_mod.socket(sock_mod.AF_INET, sock_mod.SOCK_DGRAM)
        client.settimeout(0.5)
        try:
            client.sendto(query(HOST, TYPE_A, unicast=True), ("127.0.0.1", port))
            with pytest.raises(sock_mod.timeout):
                client.recvfrom(4096)
        finally:
            client.close()
    finally:
        transport.close()
