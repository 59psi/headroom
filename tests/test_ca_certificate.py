"""Handing out Caddy's ROOT certificate.

`https://headroom.local` is signed by Caddy's built-in CA, so every device has
to trust that CA once before passkeys work. The failure this endpoint exists
to prevent is installing the wrong file: the PKI directory holds `root.crt`
next to `intermediate.crt`, and an intermediate is not a trust anchor —
installing it changes nothing, which from outside looks exactly like "the
certificate won't install".

It also holds `root.key` and `intermediate.key`, which is why the route takes
no path, no filename and no parameter at all.
"""

from __future__ import annotations

import pytest

from headroom.routes import ca_cert

pytestmark = pytest.mark.anyio


async def test_absent_on_a_deployment_without_the_local_ca(client):
    """Every deployment except the LAN-HTTPS overlay. A statement about this
    install, not a failure."""
    resp = await client.get("/api/public/ca-certificate")
    assert resp.status_code == 404
    assert "https-lan" in resp.json()["detail"]


async def test_serves_the_root_when_it_exists(client, monkeypatch, tmp_path):
    ca = tmp_path / "root.crt"
    ca.write_text("-----BEGIN CERTIFICATE-----\nstub\n-----END CERTIFICATE-----\n")
    monkeypatch.setattr(ca_cert, "CA_ROOT_PATH", ca)

    resp = await client.get("/api/public/ca-certificate")

    assert resp.status_code == 200
    assert "BEGIN CERTIFICATE" in resp.text


async def test_the_media_type_makes_ios_offer_to_install_it(client, monkeypatch, tmp_path):
    """Served as text/plain, a perfectly good certificate looks broken: the
    phone displays it instead of offering the install flow."""
    ca = tmp_path / "root.crt"
    ca.write_text("cert")
    monkeypatch.setattr(ca_cert, "CA_ROOT_PATH", ca)

    resp = await client.get("/api/public/ca-certificate")

    assert resp.headers["content-type"].startswith("application/x-x509-ca-cert")
    assert "headroom-ca.crt" in resp.headers.get("content-disposition", "")


async def test_it_is_reachable_without_logging_in(anon_client, monkeypatch, tmp_path):
    """A device cannot establish a secure context until it has this, so
    requiring a session would be a deadlock. The file is a public certificate;
    the whole point of a CA root is that everyone has it."""
    ca = tmp_path / "root.crt"
    ca.write_text("cert")
    monkeypatch.setattr(ca_cert, "CA_ROOT_PATH", ca)

    resp = await anon_client.get("/api/public/ca-certificate")

    assert resp.status_code == 200


async def test_it_serves_the_root_and_only_the_root():
    """The PKI directory holds two private keys beside the certificate.

    The route takes no input, so there is nothing to traverse with — this pins
    that property rather than testing a validator that does not exist.
    """
    import inspect

    src = inspect.getsource(ca_cert)

    assert "root.crt" in src
    # Nothing else in that directory may be nameable by this module.
    for forbidden in ("root.key", "intermediate.key"):
        assert forbidden not in src.replace("#", "").split('"""')[-1], forbidden

    # The handler takes no parameters at all.
    sig = inspect.signature(ca_cert.ca_certificate)
    assert list(sig.parameters) == [], "the endpoint accepts input it shouldn't"
