"""The suite cannot reach the network, whichever client library tries.

Popping the API keys out of the environment was the only thing standing
between a stored key and a billable call — a review agent stored a bogus key
and the Anthropic SDK made one real request to `api.anthropic.com` through
`httpx2`, which no fixture watched. The socket-level refusal in `conftest`
covers both `httpx` (the app's own clients) and `httpx2` (the SDK).
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.anyio


async def test_httpx_cannot_leave_the_process():
    import httpx

    async with httpx.AsyncClient() as client:
        with pytest.raises(httpx.ConnectError, match="disabled in tests"):
            await client.get("https://api.anthropic.com/")
    with pytest.raises(httpx.ConnectError, match="disabled in tests"):
        httpx.get("https://example.com/")


async def test_the_anthropic_sdk_cannot_leave_the_process():
    """Through the app's own seam, with a key the environment never had."""
    from anthropic import APIConnectionError, AsyncAnthropic

    from headroom.services import claude_analysis

    client = claude_analysis._anthropic_client("sk-ant-fake-key", 5.0)
    assert isinstance(client, AsyncAnthropic)
    # The SDK wraps the transport's refusal in its own connection error (and
    # would retry it with backoff — `max_retries=0` keeps the test fast).
    with pytest.raises(APIConnectionError) as info:
        await client.with_options(max_retries=0).models.list()
    assert "disabled in tests" in str(info.value.__cause__)


async def test_a_stored_key_still_ends_in_a_clean_analysis_failure(client, isolated_upload_dir):
    """The scenario that leaked: a key saved through the API, then a photo
    upload with nothing stubbed. It must fail as an analysis error, never as
    a request that left the box."""
    import io

    from PIL import Image

    assert (await client.put("/api/settings/api-key", json={"api_key": "sk-ant-api03-fake"})).status_code == 200
    hat_id = (await client.post(
        "/api/hats", json={"condition": "new", "size": "classic", "style": "a_game"}
    )).json()["id"]
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (10, 20, 200)).save(buf, "JPEG")
    buf.seek(0)

    resp = await client.post(
        f"/api/hats/{hat_id}/photo", files={"photo": ("hat.jpg", buf, "image/jpeg")}
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["analysis_status"] in ("error", "fallback")
    assert "disabled in tests" in (body["analysis_error"] or "") or "Connection" in (
        body["analysis_error"] or ""
    ), body["analysis_error"]
