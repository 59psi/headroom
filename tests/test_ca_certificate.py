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

import os

import pytest

from headroom.routes import ca_cert

pytestmark = pytest.mark.anyio

#: Root ignores directory permission bits, so the unreadable-mount cases below
#: would silently assert nothing. Skipping is honest; passing would be a lie.
skip_if_root = pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="root bypasses the directory permissions these tests depend on",
)


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


# ---- the mounted-but-unreadable case ---------------------------------- #
#
# The bug this section exists for: the route pointed straight into Caddy's PKI,
# which Caddy creates 0700 root-owned, while this app runs as a non-root user
# by policy. `Path.is_file()` reports a permission failure as plain False, so
# the endpoint answered "you aren't running the https-lan overlay" to an
# operator who was looking directly at Caddy serving certificates. It had
# never worked on any standard image.


async def test_the_served_path_is_not_inside_caddys_pki():
    """Pins the fix, not the symptom.

    Any path under Caddy's PKI is unreadable to this process no matter what
    the handler does with it, so this is the property that has to hold.
    """
    assert "pki" not in ca_cert.CA_ROOT_PATH.parts
    assert ca_cert.CA_ROOT_PATH.name == "root.crt"


@skip_if_root
async def test_an_unreadable_authority_does_not_claim_the_overlay_is_absent(
    client, monkeypatch, tmp_path
):
    """The wrong answer here costs hours, because it is confidently wrong.

    "It exists only when running docker-compose.https-lan.yml" sends someone
    to check an overlay that is demonstrably already running.
    """
    pki = tmp_path / "pki"
    pki.mkdir()
    pki.chmod(0o600)  # readable bit set, traverse bit NOT — same shape as Caddy's
    monkeypatch.setattr(ca_cert, "_LEGACY_PKI_DIR", pki)
    monkeypatch.setattr(ca_cert, "CA_ROOT_PATH", tmp_path / "absent" / "root.crt")

    try:
        resp = await client.get("/api/public/ca-certificate")

        assert resp.status_code == 404
        detail = resp.json()["detail"]
        assert "unreadable" in detail
        # It must name the thing that fixes it.
        assert "caddy-ca-export" in detail
    finally:
        # Or the tmp_path teardown cannot remove the directory.
        pki.chmod(0o700)


@skip_if_root
async def test_a_readable_authority_still_gets_the_ordinary_answer(
    client, monkeypatch, tmp_path
):
    """A traversable PKI with no cert in it is a different state again, and
    the plain message is the right one."""
    pki = tmp_path / "pki"
    pki.mkdir()
    monkeypatch.setattr(ca_cert, "_LEGACY_PKI_DIR", pki)
    monkeypatch.setattr(ca_cert, "CA_ROOT_PATH", tmp_path / "absent" / "root.crt")

    resp = await client.get("/api/public/ca-certificate")

    assert resp.status_code == 404
    assert "https-lan" in resp.json()["detail"]


async def test_a_missing_legacy_mount_is_not_an_error(client, monkeypatch, tmp_path):
    """The overwhelmingly common case — no overlay, nothing mounted — must not
    raise out of the diagnosis path."""
    monkeypatch.setattr(ca_cert, "_LEGACY_PKI_DIR", tmp_path / "nope")
    monkeypatch.setattr(ca_cert, "CA_ROOT_PATH", tmp_path / "absent" / "root.crt")

    resp = await client.get("/api/public/ca-certificate")

    assert resp.status_code == 404
    assert "https-lan" in resp.json()["detail"]


async def test_it_serves_the_root_and_only_the_root():
    """The PKI directory holds two private keys beside the certificate.

    The route takes no input, so there is nothing to traverse with — this pins
    that property rather than testing a validator that does not exist.
    """
    import ast
    import inspect

    src = inspect.getsource(ca_cert)
    assert "root.crt" in src

    # Nothing else in that directory may be nameable by this module's CODE.
    # The docstrings legitimately name the keys (to say why they are never
    # served), so strip every string constant and compare what executes. The
    # previous check looked only at the text after the LAST triple quote —
    # the final six lines of the file — so a `Path("/caddy-ca/root.key")`
    # anywhere above it would have passed.
    tree = ast.parse(src)
    code_strings = {
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    docstrings = {
        ast.get_docstring(node, clean=False)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    executable_strings = code_strings - {d for d in docstrings if d}
    for forbidden in ("root.key", "intermediate.key"):
        assert not any(forbidden in s for s in executable_strings), (
            f"{forbidden} is nameable by code in routes/ca_cert.py"
        )

    # The handler takes no parameters at all.
    sig = inspect.signature(ca_cert.ca_certificate)
    assert list(sig.parameters) == [], "the endpoint accepts input it shouldn't"
