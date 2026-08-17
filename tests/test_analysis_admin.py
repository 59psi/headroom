"""Queue visibility and bulk re-analysis.

Bulk re-analysis is the retroactive half of any prompt change: the pricing
anchors added in 2.8.0 only affect hats analysed after them, so without this a
collection keeps whatever estimates the old prompt produced.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

pytestmark = pytest.mark.anyio


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), (30, 60, 120)).save(buf, "JPEG")
    return buf.getvalue()


async def _hat_with_photo(client) -> int:
    created = await client.post(
        "/api/hats", json={"condition": "new", "size": "classic", "style": "a_game"}
    )
    hat_id = created.json()["id"]
    await client.post(
        f"/api/hats/{hat_id}/photo", files={"photo": ("h.jpg", _jpeg(), "image/jpeg")}
    )
    return hat_id


async def test_queue_status_reports_worker_and_backlog(client):
    resp = await client.get("/api/admin/analysis/queue")
    assert resp.status_code == 200
    body = resp.json()
    # The worker is disabled in tests, which is exactly the state an operator
    # needs to be able to see: a backlog with nothing draining it.
    assert body["worker_alive"] is False
    assert body["pending_count"] == 0
    assert body["pending"] == []


async def test_reanalyze_all_queues_every_hat_that_has_a_photo(client):
    with_photo = await _hat_with_photo(client)
    without_photo = (
        await client.post(
            "/api/hats", json={"condition": "new", "size": "classic", "style": "eagle"}
        )
    ).json()["id"]

    resp = await client.post("/api/admin/analysis/reanalyze-all")
    assert resp.status_code == 200
    assert resp.json()["queued"] == 1, "only the hat with a photo can be re-analysed"

    queue = (await client.get("/api/admin/analysis/queue")).json()
    assert queue["pending_count"] == 1
    assert [h["id"] for h in queue["pending"]] == [with_photo]

    # The photoless hat must not be left claiming to be queued.
    other = await client.get(f"/api/hats/{without_photo}")
    assert other.json()["analysis_status"] != "pending"


async def test_reanalyze_all_skips_disposed_hats(client):
    """Disposed hats are gone — re-pricing them spends Claude calls on nothing."""
    hat_id = await _hat_with_photo(client)
    await client.post(f"/api/hats/{hat_id}/dispose", json={"via": "sold", "price": 40})

    resp = await client.post("/api/admin/analysis/reanalyze-all")
    assert resp.json()["queued"] == 0


async def test_reanalyze_all_can_spare_hand_entered_prices(client):
    """`only_priced_by_claude` exists so a manual correction isn't overwritten."""
    hat_id = await _hat_with_photo(client)
    # No Claude key in tests, so the pipeline never sets the source — stand in
    # for a hand-entered price by leaving it unset.
    await client.put(f"/api/hats/{hat_id}", json={"estimated_new_price": 120.0})

    spared = await client.post(
        "/api/admin/analysis/reanalyze-all?only_priced_by_claude=true"
    )
    assert spared.json()["queued"] == 0, "a price Claude didn't set must be left alone"

    everything = await client.post("/api/admin/analysis/reanalyze-all")
    assert everything.json()["queued"] == 1


async def test_queue_endpoints_require_auth(anon_client):
    assert (await anon_client.get("/api/admin/analysis/queue")).status_code in (401, 403)
    assert (
        await anon_client.post("/api/admin/analysis/reanalyze-all")
    ).status_code in (401, 403)
