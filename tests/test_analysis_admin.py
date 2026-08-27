"""Queue visibility and bulk re-analysis.

Bulk re-analysis is the retroactive half of any prompt change: the pricing
anchors added in 2.8.0 only affect hats analyzed after them, so without this a
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
    assert resp.json()["queued"] == 1, "only the hat with a photo can be re-analyzed"

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
    zero hats, i.e. protected a manual price by refusing to analyze the hat at
    all. That was never necessary — `retail_pricing.resolve_retail` returns a
    Manual price untouched, and the pipeline bails on
    `resale_price_scope == "manual"` in two places — and it was actively
    harmful: the same filter, wired to a default-ON checkbox, cut a 234-hat
    re-analysis down to 45 once 2.27 moved most hats onto the retail table.

    So the hat IS analyzed, and the price survives anyway.
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
    "Re-analyze every hat".

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


async def test_a_job_still_closes_when_one_of_its_hats_is_deleted(client, db_session):
    """`total` is frozen at creation; the counts are over surviving rows.

    So deleting a hat mid-run — which the Duplicates page does — left `done`
    permanently one short of `total`, and the job reported itself in flight
    forever, across restarts. A second run then re-tagged every hat and
    stranded the first one identically. Progress is derived from the rows, so
    the gate has to ask the rows: is anything still pending?
    """
    from headroom.models.hat import Hat
    from headroom.services import analysis_job_service

    ids = [await _hat_with_photo(client) for _ in range(3)]
    job = await analysis_job_service.create_job(db_session, ids)
    await db_session.commit()

    # Two finish; the third is deleted before the worker reaches it.
    for hat_id in ids[:2]:
        (await db_session.get(Hat, hat_id)).analysis_status = "ok"
    await db_session.delete(await db_session.get(Hat, ids[2]))
    await db_session.commit()

    progress = await analysis_job_service.progress_for(db_session, job)

    assert progress.done == 2
    assert progress.job.total == 3, "the recorded total is history, not a target"
    assert progress.job.status == "done", (
        "a deleted hat stranded the job — it can never reach its frozen total"
    )


async def test_analysis_failures_group_and_flag_a_billing_refusal(client, db_session):
    """235 hats failing for one reason is ONE problem, and it must read as one.

    The real incident: the Anthropic account ran out of credit, every hat fell
    back, and the only visible message was "add a Claude API key" — on a key
    that was set, valid, and had been working minutes earlier. Nothing in the
    app aggregated the actual reason, so it went unnoticed for three days.
    """
    from headroom.models.hat import Hat

    billing = (
        "Claude analysis failed: Anthropic API error: Error code: 400 - "
        "{'error': {'message': 'Your credit balance is too low to access the "
        "Anthropic API.'}, 'request_id': 'req_ONE'}"
    )
    other = "Claude analysis failed: Connection timed out"

    ids = [await _hat_with_photo(client) for _ in range(4)]
    for hat_id, err in zip(ids, [billing, billing.replace("req_ONE", "req_TWO"),
                                 billing.replace("req_ONE", "req_THREE"), other], strict=True):
        row = await db_session.get(Hat, hat_id)
        row.analysis_status = "fallback"
        row.analysis_error = err
    await db_session.commit()

    groups = (await client.get("/api/admin/analysis/failures")).json()

    assert groups[0]["hat_count"] == 3, (
        "three hats hit the same refusal — a differing request_id must not "
        "split one problem into three"
    )
    assert groups[0]["is_billing"] is True, (
        "a credit-balance refusal must be flagged; it is the failure that "
        "looks like a missing key and is not"
    )
    assert "credit balance is too low" in groups[0]["reason"]
    assert len(groups[0]["sample_hat_ids"]) == 3

    timeout = next(g for g in groups if "timed out" in g["reason"])
    assert timeout["is_billing"] is False


# --------------------------------------------------------------------------- #
# Retrying only what failed
#
# A transient `529 Overloaded` takes out a scattering of hats mid-run. The only
# repair used to be "Re-analyze every hat", which spends a Claude call on the
# 213 that were already right in order to fix the 21 that were not.
# --------------------------------------------------------------------------- #

#: A real 529, twice, differing only in the per-call request id. Grouping has to
#: see one problem here, and so does the retry that acts on the group.
_OVERLOAD = (
    "Claude analysis failed: Anthropic API error: Error code: 529 - "
    "{'type': 'error', 'error': {'type': 'overloaded_error', 'message': "
    "'Overloaded'}, 'request_id': 'req_%s'} — basic fallback applied"
)

#: A different failure entirely: this one will fail again on retry, which is
#: why it must stay separable from the overload group rather than share a button.
_UNPARSED = (
    "Claude analysis failed: Could not parse Claude response: string indices "
    "must be integers, not 'str' — basic fallback applied"
)


async def _set_analysis(db_session, hat_id: int, *, status: str, error: str | None):
    """Put a hat into a finished analysis state.

    Uploading a photo runs the pipeline inline in tests (no worker), and with
    no API key configured every hat lands on `skipped` WITH an error string —
    so a hat is only 'healthy' here once that text is explicitly cleared.
    """
    from headroom.models.hat import Hat

    row = await db_session.get(Hat, hat_id)
    row.analysis_status = status
    row.analysis_error = error
    await db_session.commit()


async def test_retry_failed_queues_only_the_hats_that_failed(client, db_session):
    """The whole point: fix the casualties without paying for the survivors."""
    healthy = [await _hat_with_photo(client) for _ in range(3)]
    failed = [await _hat_with_photo(client) for _ in range(2)]

    for hat_id in healthy:
        await _set_analysis(db_session, hat_id, status="ok", error=None)
    for i, hat_id in enumerate(failed):
        await _set_analysis(
            db_session, hat_id, status="fallback", error=_OVERLOAD % i
        )

    resp = await client.post("/api/admin/analysis/retry-failed")
    assert resp.status_code == 200
    assert resp.json()["queued"] == 2, (
        "a retry must cover the failures only — re-running all five is the "
        "cost this endpoint exists to avoid"
    )

    queue = (await client.get("/api/admin/analysis/queue")).json()
    assert sorted(h["id"] for h in queue["pending"]) == sorted(failed)


async def test_retry_can_target_a_single_failure_group(client, db_session):
    """Groups are not interchangeable.

    An overload wants retrying immediately; a response the parser choked on
    will choke again and is a bug report. One button for the whole card would
    force them to be treated the same.
    """
    overloaded = [await _hat_with_photo(client) for _ in range(3)]
    unparsed = await _hat_with_photo(client)

    for i, hat_id in enumerate(overloaded):
        await _set_analysis(
            db_session, hat_id, status="fallback", error=_OVERLOAD % i
        )
    await _set_analysis(db_session, unparsed, status="fallback", error=_UNPARSED)

    groups = (await client.get("/api/admin/analysis/failures")).json()
    overload_group = next(g for g in groups if "overloaded_error" in g["reason"])
    assert overload_group["hat_count"] == 3

    resp = await client.post(
        "/api/admin/analysis/retry-failed",
        params={"reason": overload_group["reason"]},
    )
    assert resp.json()["queued"] == 3, (
        "three differing request ids are one problem — the retry must match "
        "the same cleaned key the grouping does, not the raw error text"
    )

    queue = (await client.get("/api/admin/analysis/queue")).json()
    assert sorted(h["id"] for h in queue["pending"]) == sorted(overloaded)

    left = (await client.get("/api/admin/analysis/failures")).json()
    assert [g["reason"] for g in left] == [
        next(g["reason"] for g in groups if "parse" in g["reason"])
    ], "retrying one group must leave the other exactly where it was"


async def test_the_retry_count_is_the_count_the_card_shows(client, db_session):
    """The button's number and the card's number cannot be allowed to drift.

    They come from two different code paths — a grouped read and a queueing
    write — and a button reading "Retry 21" that queues 18 is worse than no
    button, because nothing says which three were left behind.
    """
    hats = [await _hat_with_photo(client) for _ in range(5)]
    for i, hat_id in enumerate(hats):
        await _set_analysis(
            db_session,
            hat_id,
            status="fallback",
            error=(_OVERLOAD % i) if i < 3 else _UNPARSED,
        )

    groups = (await client.get("/api/admin/analysis/failures")).json()
    advertised = sum(g["retryable_count"] for g in groups)

    queued = (await client.post("/api/admin/analysis/retry-failed")).json()["queued"]
    assert queued == advertised == 5


async def test_a_failure_that_cannot_be_retried_is_shown_but_not_promised(
    client, db_session
):
    """"Photo missing" is a real failure, unfixable by a retry, and worth seeing.

    Hiding it from the card would remove the one message explaining why a hat
    is stuck; counting it as retryable would have the button promise work it
    cannot do. So it appears, and `retryable_count` says zero.
    """
    photoless = (
        await client.post(
            "/api/hats", json={"condition": "new", "size": "classic", "style": "eagle"}
        )
    ).json()["id"]
    await _set_analysis(
        db_session,
        photoless,
        status="error",
        error="Photo missing before analysis could run.",
    )

    groups = (await client.get("/api/admin/analysis/failures")).json()
    stuck = next(g for g in groups if "Photo missing" in g["reason"])
    assert stuck["hat_count"] == 1
    assert stuck["retryable_count"] == 0

    assert (await client.post("/api/admin/analysis/retry-failed")).json()["queued"] == 0


async def test_retry_failed_skips_disposed_hats(client, db_session):
    """A hat that failed a year ago and has since left the collection is gone.

    Retrying it spends a Claude call on inventory that is no longer owned —
    the same exclusion the whole-collection run makes, applying here because
    this narrows that query rather than replacing it.
    """
    hat_id = await _hat_with_photo(client)
    await _set_analysis(db_session, hat_id, status="fallback", error=_OVERLOAD % 1)

    disposed = await client.post(f"/api/hats/{hat_id}/dispose", json={"via": "sold"})
    # Asserted, not assumed: the first draft of this test posted the wrong field
    # name, the request 422'd, and the hat it believed it had disposed was still
    # active — so the test failed for a reason that had nothing to do with the
    # exclusion it exists to pin.
    assert disposed.status_code == 200
    assert disposed.json()["disposed_at"] is not None

    assert (await client.post("/api/admin/analysis/retry-failed")).json()["queued"] == 0
    groups = (await client.get("/api/admin/analysis/failures")).json()
    assert groups == [], "a disposed hat's old failure is not an outstanding problem"


async def test_retrying_twice_finds_nothing_left_to_do(client, db_session):
    """Pressing again must not re-queue what is already in flight.

    `create_job` clears the failure text as it moves each hat to pending, so
    the second press finds a smaller set — reported honestly as zero rather
    than silently re-running the same work.
    """
    hats = [await _hat_with_photo(client) for _ in range(2)]
    for i, hat_id in enumerate(hats):
        await _set_analysis(
            db_session, hat_id, status="fallback", error=_OVERLOAD % i
        )

    assert (await client.post("/api/admin/analysis/retry-failed")).json()["queued"] == 2
    assert (await client.post("/api/admin/analysis/retry-failed")).json()["queued"] == 0


async def test_retry_failed_requires_auth(anon_client):
    resp = await anon_client.post("/api/admin/analysis/retry-failed")
    assert resp.status_code == 401
