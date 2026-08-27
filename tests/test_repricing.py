"""Periodic re-pricing — the sweep that keeps appraisals current.

Before this existed, `refresh_melin_resale` was reachable only from inside the
analysis pipeline, so a hat's value moved only when that hat was ANALYZED. On
the real deployment every appraisal sat frozen at the date of the last bulk
re-analysis, and the only way to move them was to re-analyze the collection —
a Claude vision call per hat to fetch a marketplace median that needs no Claude.

The coupling also chained two unrelated failures: when the Anthropic balance
ran out, Claude raised, the pipeline fell back and returned, and the price
refresh below it never ran. Prices stopped because identification stopped.

Nothing here touches the network: `refresh_melin_resale` is stubbed at the
module the sweep imports it from.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from headroom.models.hat import Hat
from headroom.services import repricing

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _fresh_health():
    repricing._health = repricing.RepricingHealth()
    yield
    repricing._health = repricing.RepricingHealth()


@pytest.fixture(autouse=True)
def _no_pacing(monkeypatch):
    """The inter-hat delay is real behavior, not something to sit through."""
    monkeypatch.setattr(repricing, "repricing_delay_seconds", lambda: 0.0)


def _factory(session):
    """Hand `reprice_once` the test session without closing it."""
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _f():
        yield session

    return _f


def _hat(**over) -> Hat:
    fields = dict(
        brand="melin", model_name="Odysea Hydro", style="cap",
        condition="excellent", size="classic",
    )
    fields.update(over)
    return Hat(**fields)


async def test_manual_prices_are_never_swept(db_session):
    """An owner's own number outranks a scraped median.

    `refresh_melin_resale` already refuses to overwrite one. Excluding it from
    the QUERY as well is what makes a protected hat cost no API call at all —
    on a collection where most prices are hand-entered, the difference is the
    whole sweep.
    """
    db_session.add(_hat(resale_price_scope="manual", resale_price=120.0))
    db_session.add(_hat(resale_price_scope="model", resale_price=80.0))
    db_session.add(_hat(resale_price_scope=None))
    await db_session.commit()

    eligible = await repricing._eligible_hats(db_session)
    scopes = sorted(str(h.resale_price_scope) for h in eligible)
    assert scopes == ["None", "model"], scopes


async def test_disposed_hats_are_never_swept(db_session):
    """They have left the collection; re-pricing them is work for nobody."""
    db_session.add(_hat(disposed_at=datetime.now(timezone.utc)))
    db_session.add(_hat())
    await db_session.commit()

    eligible = await repricing._eligible_hats(db_session)
    assert len(eligible) == 1
    assert eligible[0].disposed_at is None


async def test_stalest_prices_are_swept_first(db_session):
    """A sweep cut short by a restart or a batch cap must still make progress.

    Oldest-checked-first means the hats that have gone longest without a price
    are the ones a partial run reaches. Newest-first would re-do the freshest
    prices forever and never reach the stale tail.
    """
    old = _hat(model_name="Old", resale_checked_at=datetime(2026, 1, 1))
    recent = _hat(model_name="Recent", resale_checked_at=datetime(2026, 8, 1))
    never = _hat(model_name="Never", resale_checked_at=None)
    for h in (recent, old, never):
        db_session.add(h)
    await db_session.commit()

    order = [h.model_name for h in await repricing._eligible_hats(db_session)]
    assert order[0] == "Never", order  # nulls first — never priced is stalest
    assert order.index("Old") < order.index("Recent"), order


async def test_a_sweep_counts_prices_that_CHANGED_not_hats_visited(
    client, db_session, monkeypatch
):
    """A sweep that checks 234 hats and moves none is a working sweep.

    Reporting the visit count would make a flat market look like busy work, and
    (worse) would look identical to a sweep that is silently failing to write.
    """
    from headroom.services import hat_analysis_pipeline

    db_session.add(_hat(model_name="Moves", resale_price=50.0))
    db_session.add(_hat(model_name="Stays", resale_price=50.0))
    await db_session.commit()

    async def fake_refresh(hat):
        if hat.model_name == "Moves":
            hat.resale_price = 99.0

    monkeypatch.setattr(hat_analysis_pipeline, "refresh_melin_resale", fake_refresh)

    resp = await client.post("/api/admin/repricing/run")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["considered"] == 2, body
    assert body["repriced"] == 1, body


async def test_one_unreachable_listing_does_not_stop_the_sweep(
    client, db_session, monkeypatch
):
    """Best-effort per hat, like every other outward call in this app."""
    from headroom.services import hat_analysis_pipeline

    db_session.add(_hat(model_name="Boom", resale_price=10.0))
    db_session.add(_hat(model_name="Fine", resale_price=10.0))
    await db_session.commit()

    async def fake_refresh(hat):
        if hat.model_name == "Boom":
            raise RuntimeError("marketplace unreachable")
        hat.resale_price = 42.0

    monkeypatch.setattr(hat_analysis_pipeline, "refresh_melin_resale", fake_refresh)

    body = (await client.post("/api/admin/repricing/run")).json()
    assert body["considered"] == 2, body
    assert body["repriced"] == 1, body


async def test_status_reports_the_last_sweep(client, db_session, monkeypatch):
    """A list of prices cannot distinguish "nothing changed" from "nothing ran"."""
    from headroom.services import hat_analysis_pipeline

    db_session.add(_hat(resale_price=10.0))
    await db_session.commit()

    async def fake_refresh(hat):
        hat.resale_price = 77.0

    monkeypatch.setattr(hat_analysis_pipeline, "refresh_melin_resale", fake_refresh)

    before = (await client.get("/api/admin/repricing")).json()
    assert before["last_success_at"] is None
    # conftest disables the scheduler suite-wide; the manual run must work anyway,
    # because turning the background task off should not remove the ability to
    # refresh prices on purpose.
    assert before["enabled"] is False

    await client.post("/api/admin/repricing/run")

    after = (await client.get("/api/admin/repricing")).json()
    assert after["last_success_at"] is not None
    assert after["last_repriced"] == 1
    assert after["consecutive_failures"] == 0


async def test_repricing_status_requires_auth(anon_client):
    assert (await anon_client.get("/api/admin/repricing")).status_code == 401
    assert (await anon_client.post("/api/admin/repricing/run")).status_code == 401


async def test_the_scheduler_does_not_start_when_disabled(monkeypatch):
    monkeypatch.setenv("HEADROOM_REPRICING_ENABLED", "false")
    assert await repricing.start_repricing() is None


async def test_repricing_is_independent_of_analysis(db_session):
    """The point of the whole module.

    A hat whose analysis failed — no key, expired balance, unreadable photo —
    is still perfectly re-priceable: the marketplace lookup keys on style,
    model_name, condition and size, all of which are already in the database.
    """
    db_session.add(_hat(analysis_status="fallback", analysis_error="credit balance too low"))
    await db_session.commit()

    eligible = await repricing._eligible_hats(db_session)
    assert len(eligible) == 1
    assert eligible[0].analysis_status == "fallback"


# ---- what the adversarial review caught -------------------------------- #


async def test_a_manual_run_does_not_clear_a_standing_scheduler_failure(
    client, db_session, monkeypatch
):
    """Clicking a button proves the code works, not that the loop is alive.

    `record_success` used to zero `consecutive_failures` and clear
    `last_error` unconditionally, so a sweep failing nightly for a month read
    "swept just now, 0 failures" after one press — hiding exactly the dead-task
    condition the health record exists to expose.
    """
    from headroom.services import hat_analysis_pipeline

    db_session.add(_hat(resale_price=10.0))
    await db_session.commit()

    async def fake_refresh(hat):
        hat.resale_price = 55.0

    monkeypatch.setattr(hat_analysis_pipeline, "refresh_melin_resale", fake_refresh)

    repricing.health().record_failure("MelinRecapError: 429 Too Many Requests")
    repricing.health().record_failure("MelinRecapError: 429 Too Many Requests")

    await client.post("/api/admin/repricing/run")

    after = (await client.get("/api/admin/repricing")).json()
    assert after["consecutive_failures"] == 2, after
    assert "429" in (after["last_error"] or ""), after
    # ...while still reporting that the manual sweep itself worked.
    assert after["last_repriced"] == 1


async def test_a_scheduled_sweep_does_clear_the_alarm(db_session, monkeypatch):
    """The scheduler recovering is the one thing that means recovery."""
    repricing.health().record_failure("boom")
    repricing.health().record_success(3, 10, scheduled=True)

    assert repricing.health().consecutive_failures == 0
    assert repricing.health().last_error is None


async def test_a_failing_manual_run_is_recorded_not_swallowed(
    client, db_session, monkeypatch
):
    """A manual sweep that fails forever must not leave the last success showing."""
    async def boom(session_factory=None, limit=None):
        raise RuntimeError("marketplace down")

    monkeypatch.setattr(repricing, "reprice_once", boom)

    # The handler records and then RE-RAISES, so the traceback still reaches
    # the container log (CLAUDE.md: "Starlette re-raises"). Under
    # ASGITransport that surfaces here rather than as a 500 — the contract
    # being pinned is "recorded, then raised", not the status code.
    with pytest.raises(RuntimeError, match="marketplace down"):
        await client.post("/api/admin/repricing/run")

    after = repricing.health()
    assert after.consecutive_failures == 1
    assert "marketplace down" in (after.last_error or "")


async def test_unpriceable_hats_do_not_starve_the_queue(db_session, monkeypatch):
    """The ordering must ADVANCE, or a capped sweep never reaches the tail.

    `refresh_melin_resale` sets `resale_checked_at` only when it finds
    listings — it returns early for a non-melin brand, an API error, or an
    empty result. Ordered `nulls_first`, those hats keep a NULL timestamp
    forever and permanently own the head of the queue, so every capped sweep
    re-visits the same never-priceable rows and never gets past them.
    """
    from headroom.services import hat_analysis_pipeline

    for i in range(3):
        db_session.add(_hat(model_name=f"Dud{i}", brand="not-melin"))
    await db_session.commit()

    async def never_prices(hat):
        return  # exactly what a non-melin brand or an empty result does

    monkeypatch.setattr(hat_analysis_pipeline, "refresh_melin_resale", never_prices)

    first = [h.model_name for h in await repricing._eligible_hats(db_session, limit=2)]
    await repricing.reprice_once(session_factory=_factory(db_session), limit=2)
    db_session.expire_all()
    second = [h.model_name for h in await repricing._eligible_hats(db_session, limit=2)]

    assert first != second, (
        f"the queue did not advance: swept {first}, next sweep offers {second}"
    )


async def test_a_manual_run_is_bounded_and_says_what_is_left(
    client, db_session, monkeypatch
):
    """Uncapped this is a four-minute HTTP request — a dead spinner on a phone."""
    from headroom.services import hat_analysis_pipeline

    monkeypatch.setattr(repricing, "MANUAL_SWEEP_LIMIT", 2)
    for i in range(5):
        db_session.add(_hat(model_name=f"H{i}"))
    await db_session.commit()

    async def fake_refresh(hat):
        return

    monkeypatch.setattr(hat_analysis_pipeline, "refresh_melin_resale", fake_refresh)

    body = (await client.post("/api/admin/repricing/run")).json()
    assert body["considered"] == 2, body
    assert body["remaining"] == 5, body  # a COUNT, not len() of the capped list
