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


def _ids(group):
    return {h["hat_id"] for h in group["hats"]}


async def test_a_price_carried_by_many_hats_is_reported(client, db_session):
    ids = [await _hat(client) for _ in range(5)]
    for hat_id in ids:
        await _price(db_session, hat_id, 85.0, "Melin Recap · median of 13 live Trenches Hydro listings")

    groups = (await client.get("/api/admin/prices/shared")).json()
    assert len(groups) == 1
    assert groups[0]["resale_price"] == 85.0
    assert groups[0]["hat_count"] == 5
    assert _ids(groups[0]) == set(ids)


async def test_a_handful_sharing_a_price_is_not_reported(client, db_session):
    """Two examples of one product genuinely cost the same. It takes a crowd
    before the number stops being about the hat.

    Pins the boundary in BOTH directions. `MAX_UNREMARKABLE` is compared with
    `>`, and the constant it replaced (`SHARED_THRESHOLD = 3`) read as "three
    or more" while meaning four or more — a test that only checked the quiet
    side would keep passing whichever the code meant.
    """
    ids = [await _hat(client) for _ in range(3)]
    for hat_id in ids:
        await _price(db_session, hat_id, 85.0, "src")

    assert (await client.get("/api/admin/prices/shared")).json() == [], (
        "three hats sharing a number is ordinary"
    )

    await _price(db_session, await _hat(client), 85.0, "src")
    groups = (await client.get("/api/admin/prices/shared")).json()
    assert [g["hat_count"] for g in groups] == [4], "a fourth makes it a crowd"


async def test_one_line_stays_one_group_when_the_live_count_moves(client, db_session):
    """The source sentence quotes how many listings were live at that moment,
    and that number MOVES.

    Re-pricing is sequential, paced a second apart, oldest-first and resumable,
    so hats priced against one line off one median routinely carry different
    counts. Grouping on the raw sentence split the very cluster this report
    exists to reveal — into fragments that each fell under the threshold and
    vanished, leaving a collection of identical prices looking healthy.
    """
    for count in (13, 13, 14, 15):
        await _price(
            db_session, await _hat(client), 85.0,
            f"Melin Recap · median of {count} live classic new Trenches Hydro listings",
        )

    groups = (await client.get("/api/admin/prices/shared")).json()
    assert len(groups) == 1, "one line, one group, whatever the count said that second"
    assert groups[0]["hat_count"] == 4
    assert "median of" in groups[0]["source"], "the sentence is shown verbatim, not the key"


async def test_a_different_line_is_still_a_different_group(client, db_session):
    """The control for the test above: neutralizing the count must not blur two
    genuinely different comparisons into one."""
    for _ in range(4):
        await _price(
            db_session, await _hat(client), 85.0,
            "Melin Recap · median of 9 live Trenches Hydro listings",
        )
    for _ in range(4):
        await _price(
            db_session, await _hat(client), 85.0,
            "Melin Recap · median of 9 live Odysea Rope listings",
        )

    groups = (await client.get("/api/admin/prices/shared")).json()
    assert len(groups) == 2


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
    assert _ids(groups[0]) == set(scraped)


async def test_the_missing_colorway_count_is_the_actionable_half(client, db_session):
    """A missing colorway is what prevents naming a product. It cannot be
    inferred from the photo (measured at 12% precision); the two sources that
    can supply it are the owner and an already-imported order that matching
    has not been re-run against (`unclaimed_from_purchases`)."""
    for i in range(6):
        await _price(
            db_session, await _hat(client), 85.0, "src",
            colorway="Prismatic" if i < 2 else None,
        )

    group = (await client.get("/api/admin/prices/shared")).json()[0]
    assert group["hat_count"] == 6
    assert group["missing_colorway"] == 4


async def test_hats_missing_a_colorway_come_first(client, db_session):
    """The card names only the first few of a group, so the sample it truncates
    to must be the rows worth opening.

    The two priced hats are created FIRST, so they hold the lower ids — without
    the sort they would head the list and a group of thirty would show eight
    hats nothing can be done about.
    """
    for _ in range(2):
        await _price(db_session, await _hat(client), 85.0, "src", colorway="Prismatic")
    for _ in range(3):
        await _price(db_session, await _hat(client), 85.0, "src")

    group = (await client.get("/api/admin/prices/shared")).json()[0]
    assert [h["has_colorway"] for h in group["hats"]] == [False, False, False, True, True]


async def test_a_hat_with_no_case_keeps_its_neighbors_labels_straight(client, db_session):
    """A hat carries its OWN label, so ids and labels cannot fall out of step.

    They did: the group appended every id but only the display_ids that were
    set, and the card indexed the two side by side. A hat with no case has no
    display_id — the normal state for a room-stored or freshly-added hat — so
    one of those shifted every later label onto the wrong hat's link, pointing
    at hat A under hat B's shelf id.
    """
    case = (await client.post("/api/cases", json={"case_type": "archive"})).json()
    cased = await _hat(client, case_id=case["id"])
    loose = [await _hat(client) for _ in range(3)]

    for hat_id in [cased, *loose]:
        await _price(db_session, hat_id, 85.0, "src")

    group = (await client.get("/api/admin/prices/shared")).json()[0]
    labels = {h["hat_id"]: h["display_id"] for h in group["hats"]}

    assert labels[cased] == f"{case['display_id']}-01"
    for hat_id in loose:
        assert labels[hat_id] is None, "a caseless hat reports no label, rather than borrowing one"


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


