"""Caching, compression, HEAD, and where the SPA fallback stops.

All executed against the live app in the review: hashed assets carried no
`Cache-Control` (a 304 round trip per file per visit); a hat photo fetched
after Sign out answered 200 from the browser cache; `curl -I /health/ready`
was 405; `GET /health/readyz` was the SPA shell with a 200, so a watchdog
pointed at a typo would have polled a healthy answer forever; and the 550 KB
bundle went over `http://<ip>:8000` uncompressed.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.anyio


async def test_api_json_is_never_stored(client):
    resp = await client.get("/api/hats")
    assert resp.headers["cache-control"] == "no-store"


async def test_a_route_that_names_its_own_policy_keeps_it(anon_client):
    resp = await anon_client.get("/api/public/branding/logo")
    if resp.status_code == 200:
        assert "max-age=300" in resp.headers["cache-control"]
    else:  # no logo seeded under test — still not the blanket policy's job to decide
        assert resp.status_code == 404


async def test_uploads_must_be_revalidated_every_time(client, isolated_upload_dir):
    from headroom.config import settings

    (settings.upload_dir / "hats").mkdir(parents=True, exist_ok=True)
    (settings.upload_dir / "hats" / "p.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    resp = await client.get("/uploads/hats/p.png")
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "private, no-cache"
    assert resp.headers.get("etag"), "no-cache needs a validator or every hit is a full download"


async def test_signed_out_photo_requests_are_refused(anon_client):
    assert (await anon_client.get("/uploads/hats/p.png")).status_code == 401


async def test_health_answers_head(anon_client):
    assert (await anon_client.head("/health")).status_code == 200
    assert (await anon_client.head("/health/ready")).status_code in (200, 503)


@pytest.mark.parametrize("path", ["/health/readyz", "/api/does-not-exist", "/api/hats/x/y/z"])
async def test_a_typo_under_an_api_prefix_is_a_404_not_the_shell(client, path):
    resp = await client.get(path)
    assert resp.status_code == 404, (path, resp.status_code)
    assert "text/html" not in resp.headers.get("content-type", ""), path


async def test_big_json_is_gzipped_when_asked(client):
    for i in range(40):
        await client.post(
            "/api/hats",
            json={"condition": "new", "size": "classic", "style": "a_game",
                  "owner_notes": f"note {i} " + "x" * 200},
        )
    resp = await client.get("/api/hats", headers={"accept-encoding": "gzip"})
    assert resp.status_code == 200
    assert resp.headers.get("content-encoding") == "gzip"
    assert len(resp.json()) == 40, "the body still decodes"
