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


async def test_stage_is_hidden_once_analysis_finishes(client):
    """A stage on a terminal status would be a confident label for work that
    stopped — worse than no label. `HatRead` derives it away rather than
    trusting eight separate terminal transitions to each clear it.
    """
    from sqlalchemy import update as sa_update

    from headroom.models.hat import Hat
    from tests.conftest import test_session_factory

    hat_id = await _hat_with_photo(client)

    async with test_session_factory() as db:
        await db.execute(
            sa_update(Hat)
            .where(Hat.id == hat_id)
            .values(analysis_status="pending", analysis_stage="identifying")
        )
        await db.commit()
    assert (await client.get(f"/api/hats/{hat_id}")).json()["analysis_stage"] == "identifying"

    # Any terminal status must hide it, even with the column still populated.
    async with test_session_factory() as db:
        await db.execute(
            sa_update(Hat).where(Hat.id == hat_id).values(analysis_status="ok")
        )
        await db.commit()

    body = (await client.get(f"/api/hats/{hat_id}")).json()
    assert body["analysis_status"] == "ok"
    assert body["analysis_stage"] is None, "a finished hat must not report a running step"


async def test_reanalyze_all_opens_a_job_and_derives_its_progress(client):
    """Progress is counted from the hats, never accumulated on the job.

    Accumulating would mean the worker writing twice per hat, with a crash
    between the two leaving a progress bar that permanently disagrees with the
    hats it claims to describe.
    """
    from sqlalchemy import update as sa_update

    from headroom.models.hat import Hat
    from tests.conftest import test_session_factory

    a = await _hat_with_photo(client)
    b = await _hat_with_photo(client)

    started = await client.post("/api/admin/analysis/reanalyze-all")
    job = started.json()["job"]
    assert job is not None
    assert job["total"] == 2
    assert job["done"] == 0 and job["failed"] == 0
    assert job["status"] == "running"

    status = (await client.get("/api/admin/analysis/queue")).json()
    assert status["current_job"]["id"] == job["id"]

    # Finish one, fail the other — the counts must follow the hats.
    async with test_session_factory() as db:
        await db.execute(sa_update(Hat).where(Hat.id == a).values(analysis_status="ok"))
        await db.execute(
            sa_update(Hat).where(Hat.id == b).values(analysis_status="error")
        )
        await db.commit()

    status = (await client.get("/api/admin/analysis/queue")).json()
    finished = status["recent_jobs"][0]
    assert finished["done"] == 2
    assert finished["failed"] == 1
    assert finished["status"] == "done", "a job with nothing pending must close"
    assert finished["finished_at"] is not None
    assert status["current_job"] is None, "a closed job is not the current one"


async def test_recent_jobs_are_newest_first(client):
    """The card shows a short history; the last run has to be at the top."""
    await _hat_with_photo(client)

    first = (await client.post("/api/admin/analysis/reanalyze-all")).json()["job"]
    second = (await client.post("/api/admin/analysis/reanalyze-all")).json()["job"]

    recent = (await client.get("/api/admin/analysis/queue")).json()["recent_jobs"]
    assert [j["id"] for j in recent][:2] == [second["id"], first["id"]]
