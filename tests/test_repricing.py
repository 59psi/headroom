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
