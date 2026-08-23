"""Hand out Caddy's ROOT certificate, so a device can trust the LAN name.

`https://headroom.local` is signed by Caddy's built-in CA, because Let's
Encrypt cannot issue for `.local`. Every device therefore has to trust that CA
once — and until it does, passkeys and Face ID will not work, because browsers
only offer them in a secure context.

Getting the file onto a phone used to mean `docker compose cp` on the Pi
followed by AirDrop. This serves it instead: open the URL on the device, and
iOS offers to install it.

**Only `root.crt` is ever served, and the filename is hardcoded.** Caddy's PKI
directory holds four files:

    root.crt          the trust anchor — this is the one
    root.key          private key
    intermediate.crt  signs leaf certs; NOT a trust anchor
    intermediate.key  private key

Two of those are private keys, and handing one out would let anyone mint a
certificate this network trusts. So this module takes no path, no filename and
no parameter of any kind: there is no input to traverse with. That is a
stronger guarantee than validating a path would be.

The **intermediate is the trap**, and it is why this endpoint exists at all:
it sits next to the root, has a plausible name, and installing it achieves
nothing. A trust anchor is by definition self-signed and installed out of
band; an intermediate is presented by the *server* during the handshake and
is only meaningful once its issuer is already trusted. Devices are within
their rights to accept the file and go on refusing the connection, which is
exactly what "the certificate won't install" looks like from outside.

Unauthenticated on purpose: a device cannot establish a secure context until
it has this, and the file is a public certificate — the whole point of a CA
root is that everybody has it.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter(prefix="/api/public", tags=["public"])

#: Where `docker-compose.https-lan.yml` mounts Caddy's data volume, read-only.
#: Absent on every other deployment, which is what makes the 404 below the
#: normal answer rather than an error.
CA_ROOT_PATH = Path("/caddy-data/caddy/pki/authorities/local/root.crt")

#: What makes iOS and Android offer to INSTALL the file rather than display or
#: download it. Serving it as text/plain is a common way to make a perfectly
#: good certificate look broken.
CA_MEDIA_TYPE = "application/x-x509-ca-cert"


@router.get("/ca-certificate")
async def ca_certificate():
    """Caddy's root CA, for trusting `https://headroom.local` on this device.

    404 when the file isn't there — which is every deployment except the
    LAN-HTTPS overlay, and is a statement about this install rather than a
    failure.
    """
    if not CA_ROOT_PATH.is_file():
        raise HTTPException(
            status_code=404,
            detail=(
                "No local CA certificate on this install. It exists only when "
                "running docker-compose.https-lan.yml."
            ),
        )
    return FileResponse(
        CA_ROOT_PATH,
        media_type=CA_MEDIA_TYPE,
        filename="headroom-ca.crt",
    )
