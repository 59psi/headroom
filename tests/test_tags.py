"""Physical tags: the URL a QR label or NFC tag carries, and the host in it.

These tags get printed onto adhesive and written into hardware, so the two
things that must not drift are the URL *shape* (a landing route has to keep
resolving it forever) and the *host* (a tag naming an address that stops
existing is indistinguishable from a broken tag).
"""

from __future__ import annotations

import pytest

from headroom.app import FRONTEND_DIST
from headroom.services import tag_service

pytestmark = pytest.mark.anyio


async def test_tag_url_shape():
    """Pinned because stickers outlive code: a change here orphans hardware."""
    assert tag_service.tag_path(tag_service.HAT, 42) == "/t/h/42"
    assert tag_service.tag_path(tag_service.CASE, "A-001") == "/t/c/A-001"
    assert (
        tag_service.tag_url("http://headroom.local:8000/", tag_service.HAT, 7)
        == "http://headroom.local:8000/t/h/7"
    )


async def test_tag_base_defaults_to_the_requesting_host(client):
    body = (await client.get("/api/settings/tags")).json()
    assert body["source"] == "request"
    assert body["example_url"].endswith("/t/h/1")


async def test_a_configured_base_wins_over_the_request(client):
    """The reason the setting exists.

    Browse to the Pi by IP once and every tag written that afternoon names a
    DHCP lease. The tags don't report this — they just stop opening anything.
    """
    resp = await client.put(
        "/api/settings/tags", json={"base_url": "http://headroom.local:8000"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["base_url"] == "http://headroom.local:8000"
    assert body["source"] == "settings"
    assert body["example_url"] == "http://headroom.local:8000/t/h/1"

    # And it survives into what actually gets printed. A case has to exist
    # for that to be checkable — this used to be `... or "0 labels" in html`
    # with no case created, so the second arm was always true and the base
    # URL was never actually looked for on the sheet.
    case = (await client.post("/api/cases", json={"case_type": "archive"})).json()
    html = (await client.get("/api/admin/case-labels")).text
    assert f"http://headroom.local:8000/t/c/{case['display_id']}" in html
    assert "0 labels" not in html


async def test_trailing_slash_does_not_double_up(client):
    await client.put(
        "/api/settings/tags", json={"base_url": "http://headroom.local:8000/"}
    )
    body = (await client.get("/api/settings/tags")).json()
    assert body["example_url"] == "http://headroom.local:8000/t/h/1"


async def test_clearing_falls_back_to_the_request_host(client):
    await client.put("/api/settings/tags", json={"base_url": "http://pinned:9000"})
    assert (await client.delete("/api/settings/tags")).status_code == 204
    assert (await client.get("/api/settings/tags")).json()["source"] == "request"


@pytest.mark.parametrize("bad", ["headroom.local:8000", "192.168.1.50", "ftp://x/"])
async def test_a_base_without_an_http_scheme_is_rejected(client, bad):
    """`headroom.local:8000` looks right and produces tags that do nothing.

    An NFC NDEF URI record needs a scheme, and a QR without one is read as
    plain text — the camera offers to copy it rather than open it. You would
    find out after sticking forty labels on.
    """
    resp = await client.put("/api/settings/tags", json={"base_url": bad})
    assert resp.status_code == 422


async def test_tag_landing_paths_are_not_auth_gated(anon_client):
    """The tag URL must serve the SPA shell so the app can boot and redirect.

    Gating it at the middleware would make a tap return bare JSON instead of a
    page. 404 is the legitimate answer when the frontend isn't built (CI has no
    `frontend/dist`, so the catch-all isn't mounted at all) — what must never
    happen is 401.
    """
    for path in ("/t/h/1", "/t/c/A-001"):
        resp = await anon_client.get(path)
        assert resp.status_code != 401, f"{path} was auth-gated"
        if FRONTEND_DIST.exists():
            assert resp.status_code == 200
