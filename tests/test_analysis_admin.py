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


async def test_a_hand_entered_price_is_spared_without_skipping_the_hat(client):
    """Manual prices are protected by the WRITE path, not by exclusion.

    This used to assert the opposite: that `only_priced_by_claude=true` queued
    zero hats, i.e. protected a manual price by refusing to analyse the hat at
    all. That was never necessary — `retail_pricing.resolve_retail` returns a
    Manual price untouched, and the pipeline bails on
    `resale_price_scope == "manual"` in two places — and it was actively
    harmful: the same filter, wired to a default-ON checkbox, cut a 234-hat
    re-analysis down to 45 once 2.27 moved most hats onto the retail table.

    So the hat IS analysed, and the price survives anyway.
    """
    hat_id = await _hat_with_photo(client)
    await client.put(f"/api/hats/{hat_id}", json={"estimated_new_price": 120.0})

    body = (await client.post("/api/admin/analysis/reanalyze-all")).json()
    assert body["queued"] == 1, "the hat must not be skipped"

    read = (await client.get(f"/api/hats/{hat_id}")).json()
    assert read["estimated_new_price"] == 120.0
    assert read["estimated_new_price_source"] == "Manual"


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


@pytest.mark.anyio
async def test_reanalyze_all_covers_every_hat_with_a_photo(client, monkeypatch):
    """The reported bug: 234 hats, 45 queued.

    A checkbox reading "Leave hand-entered prices alone", ON by default, mapped
    to a filter for hats priced by Claude. Before 2.27 nearly every hat WAS
    priced by Claude, so the filter matched almost everything and looked
    harmless. 2.27 moved the majority onto the retail table, and the same
    filter then matched only the remainder — under a button that says
    "Re-analyse every hat".

    The filter was redundant anyway: a Manual price is protected
    unconditionally by `resolve_retail` and the two `resale_price_scope ==
    "manual"` guards, so it never spared anything that wasn't already safe.
    """
    from sqlalchemy import select

    from headroom.models.hat import Hat
    from tests.conftest import test_session_factory

    ids = []
    for _ in range(5):
        resp = await client.post(
            "/api/hats", json={"condition": "new", "size": "classic", "style": "a_game"}
        )
        ids.append(resp.json()["id"])

    # Give them photos and a spread of price sources, the way a real
    # collection looks after 2.27: mostly table-priced, a few Claude, one
    # manual, one unpriced.
    sources = ["melin retail", "melin retail", "Claude Vision", "Manual", None]
    async with test_session_factory() as db:
        for hat_id, source in zip(ids, sources, strict=False):
            hat = (await db.execute(select(Hat).where(Hat.id == hat_id))).scalar_one()
            hat.photo_path = f"hats/{hat_id}.png"
            hat.estimated_new_price_source = source
            hat.estimated_new_price = 79.0 if source else None
        await db.commit()

    body = (await client.post("/api/admin/analysis/reanalyze-all")).json()

    assert body["queued"] == 5, "the run was filtered down by price source"
    assert body["job"]["total"] == 5


@pytest.mark.anyio
async def test_reanalyze_all_still_skips_photoless_and_disposed(client):
    """The only two exclusions, and both are deliberate."""
    from sqlalchemy import select

    from headroom.models.hat import Hat
    from tests.conftest import test_session_factory

    async def _hat():
        r = await client.post(
            "/api/hats", json={"condition": "new", "size": "classic", "style": "a_game"}
        )
        return r.json()["id"]

    with_photo, no_photo, disposed = await _hat(), await _hat(), await _hat()
    async with test_session_factory() as db:
        for hat_id in (with_photo, disposed):
            hat = (await db.execute(select(Hat).where(Hat.id == hat_id))).scalar_one()
            hat.photo_path = f"hats/{hat_id}.png"
        await db.commit()
    await client.post(f"/api/hats/{disposed}/dispose", json={"via": "sold"})

    body = (await client.post("/api/admin/analysis/reanalyze-all")).json()

    assert body["queued"] == 1, f"expected only #{with_photo}"
    assert no_photo and disposed  # named for the reader


@pytest.mark.anyio
async def test_pending_count_is_not_capped_by_the_preview_list(client):
    """`pending_count` was `len(hats)` over a list bounded to 50, so a deep
    queue always reported 50 — a count read off a limited feed, the same
    mistake as sizing the colorway catalog from its autocomplete endpoint."""
    from sqlalchemy import select

    from headroom.models.hat import Hat
    from tests.conftest import test_session_factory

    ids = []
    for _ in range(55):
        r = await client.post(
            "/api/hats", json={"condition": "new", "size": "classic", "style": "a_game"}
        )
        ids.append(r.json()["id"])
    async with test_session_factory() as db:
        for hat_id in ids:
            hat = (await db.execute(select(Hat).where(Hat.id == hat_id))).scalar_one()
            hat.analysis_status = "pending"
        await db.commit()

    body = (await client.get("/api/admin/analysis/queue")).json()

    assert body["pending_count"] == 55, "the count was capped by the preview list"
    assert len(body["pending"]) == 50, "the preview list itself stays bounded"
