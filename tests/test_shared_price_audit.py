"""Which prices describe a LINE rather than the hat beside them.

The reported complaint was that resale values "are all very wrong". They were
not individually implausible — they were IDENTICAL: 168 of 235 hats carried one
of five numbers, 54 at exactly $85.00. Nothing in the app said so, because each
hat's page shows its own figure with its own source sentence and only a query
across the whole collection reveals the overlap.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.anyio


async def _hat(client, **over):
    body = {"condition": "new", "size": "classic", "style": "a_game", **over}
    return (await client.post("/api/hats", json=body)).json()["id"]


async def _price(db_session, hat_id, price, source, colorway=None):
    from headroom.models.hat import Hat

    row = await db_session.get(Hat, hat_id)
    row.resale_price = price
    row.resale_price_source = source
    row.resale_price_scope = "model"
    row.colorway = colorway
    await db_session.commit()


async def test_a_price_carried_by_many_hats_is_reported(client, db_session):
    ids = [await _hat(client) for _ in range(5)]
    for hat_id in ids:
        await _price(db_session, hat_id, 85.0, "Melin Recap · median of 13 live Trenches Hydro listings")

    groups = (await client.get("/api/admin/prices/shared")).json()
    assert len(groups) == 1
    assert groups[0]["resale_price"] == 85.0
    assert groups[0]["hat_count"] == 5
    assert set(groups[0]["hat_ids"]) == set(ids)


async def test_a_handful_sharing_a_price_is_not_reported(client, db_session):
    """Two examples of one product genuinely cost the same. It takes a crowd
    before the number stops being about the hat."""
    for _ in range(3):
        await _price(db_session, await _hat(client), 85.0, "src")

    assert (await client.get("/api/admin/prices/shared")).json() == []


async def test_hats_priced_by_hand_are_left_alone(client, db_session):
    """A number the owner typed is theirs, and five hats they priced the same
    are not a measurement error.

    Carries a CONTROL group on purpose. Asserting only that the manual hats are
    absent passes just as well when the report returns nothing at all for some
    unrelated reason — which is exactly what an earlier version of this test
    did: deleting the manual filter outright left it green.
    """
    from headroom.models.hat import Hat

    manual = [await _hat(client) for _ in range(5)]
    for hat_id in manual:
        row = await db_session.get(Hat, hat_id)
        row.resale_price = 85.0
        row.resale_price_source = "Manual"
        row.resale_price_scope = "manual"
    await db_session.commit()

    scraped = [await _hat(client) for _ in range(5)]
    for hat_id in scraped:
        await _price(db_session, hat_id, 70.0, "Melin Recap · Trenches Hydro")

    groups = (await client.get("/api/admin/prices/shared")).json()
    assert [g["resale_price"] for g in groups] == [70.0], (
        "the scraped group must be reported and the manual one must not"
    )
    assert set(groups[0]["hat_ids"]) == set(scraped)


async def test_the_missing_colorway_count_is_the_actionable_half(client, db_session):
    """A missing colorway is what prevents naming a product, and the one thing
    only the owner can supply — it cannot be inferred from the photo (measured
    at 12% precision) nor from an unmatched receipt."""
    for i in range(6):
        await _price(
            db_session, await _hat(client), 85.0, "src",
            colorway="Prismatic" if i < 2 else None,
        )

    group = (await client.get("/api/admin/prices/shared")).json()[0]
    assert group["hat_count"] == 6
    assert group["missing_colorway"] == 4


async def test_the_same_price_from_different_sources_is_not_one_group(client, db_session):
    """Two lines that happen to sit at the same median are two facts, not one —
    grouping on the price alone would invent a cluster that does not exist."""
    for _ in range(4):
        await _price(db_session, await _hat(client), 85.0, "Trenches Hydro")
    for _ in range(4):
        await _price(db_session, await _hat(client), 85.0, "Odysea Rope")

    groups = (await client.get("/api/admin/prices/shared")).json()
    assert len(groups) == 2
    assert {g["source"] for g in groups} == {"Trenches Hydro", "Odysea Rope"}


async def test_disposed_hats_are_excluded(client, db_session):
    ids = [await _hat(client) for _ in range(5)]
    for hat_id in ids:
        await _price(db_session, hat_id, 85.0, "src")
    for hat_id in ids[:3]:
        await client.post(f"/api/hats/{hat_id}/dispose", json={"via": "sold"})

    assert (await client.get("/api/admin/prices/shared")).json() == []


async def test_groups_come_back_biggest_first(client, db_session):
    for _ in range(4):
        await _price(db_session, await _hat(client), 70.0, "small")
    for _ in range(9):
        await _price(db_session, await _hat(client), 85.0, "big")

    groups = (await client.get("/api/admin/prices/shared")).json()
    assert [g["hat_count"] for g in groups] == [9, 4]


async def test_the_report_requires_auth(anon_client):
    assert (await anon_client.get("/api/admin/prices/shared")).status_code == 401
