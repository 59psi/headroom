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


async def test_an_spa_route_is_the_shell(client):
    """The control for the typo test below: the catch-all exists and answers.

    Without it, "not the shell" is also what an app with NO catch-all answers
    — which is what CI ran for releases, since its backend job never builds
    `frontend/dist` and `create_app()` registers the catch-all only when that
    directory exists. The suite now serves a stub bundle (`spa_bundle` in
    conftest); this proves it is there.
    """
    from tests.conftest import SPA_SHELL_MARKER

    resp = await client.get("/hats/12")

    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert SPA_SHELL_MARKER in resp.text


#: One probe per first segment the SPA fallback refuses (`app._NOT_SPA_PREFIXES`).
#: `/uploads` bare, because `/uploads/<file>` is the static mount's to answer
#: and never reaches the fallback.
@pytest.mark.parametrize(
    "path",
    [
        "/health/readyz",
        "/api/does-not-exist",
        "/api/hats/x/y/z",
        "/uploads",
        "/openapi.json/x",
        "/docs",
        "/redoc/x",
    ],
)
async def test_a_typo_under_an_api_prefix_is_a_404_not_the_shell(client, path):
    from tests.conftest import SPA_SHELL_MARKER

    resp = await client.get(path)
    assert resp.status_code == 404, (path, resp.status_code)
    assert "text/html" not in resp.headers.get("content-type", ""), path
    assert SPA_SHELL_MARKER not in resp.text, path


@pytest.mark.parametrize("path", ["//api/hats", "//health/ready", "//uploads/hats/p.png"])
async def test_a_doubled_leading_slash_is_not_the_shell(tmp_path, monkeypatch, path):
    """`//api/hats` matches no route and no gate prefix, so it fell through to
    the SPA catch-all and answered `index.html` with a 200 — HTML from what
    reads as the hats endpoint. No SPA route begins with a second slash."""
    from tests.test_security import _make_app_with_dist

    client, _dist, _secret = _make_app_with_dist(tmp_path, monkeypatch)
    assert client.get("/").status_code == 200, "precondition: the SPA route exists"

    # A full URL: a bare "//api/hats" is a scheme-relative reference to a HOST
    # named `api`, which is not the request a browser or curl sends.
    resp = client.get(f"http://testserver{path}")
    assert resp.request.url.raw_path.startswith(b"//"), "precondition: the doubled slash is sent"

    assert resp.status_code == 404, (path, resp.status_code)
    assert resp.json() == {"detail": "Not found"}


async def test_the_api_docs_pages_are_not_served(client):
    """Their Swagger/ReDoc bundles come from a CDN the CSP blocks, so behind
    the login they were blank pages. The schema itself stays (gated)."""
    for path in ("/docs", "/redoc"):
        resp = await client.get(path)
        assert resp.status_code == 404, (path, resp.status_code)
        assert "text/html" not in resp.headers.get("content-type", ""), path
    assert (await client.get("/openapi.json")).status_code == 200


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
