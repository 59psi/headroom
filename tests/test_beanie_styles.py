"""melin's beanie shapes are models, not one undifferentiated bucket.

Journey, Destination and All Day are named and priced like any other melin
model (see melin's own "Beanie Shape Guide"), so they are styles. The risk in
adding them is that `Hat.is_beanie` is a real column — search filters query it
and case capacity depends on it (`capacity.MAX_BEANIE` beanies per case against
`capacity.MAX_REGULAR` regular hats) —
that is DERIVED from style. A new beanie shape missing from `BEANIE_STYLES`
packs 3-to-a-case, vanishes from the Beanies filter, and makes the case picker
offer cases the save then rejects with a 409.

So these tests are mostly about the derivation, not the enum.
"""

from __future__ import annotations

import pytest

from headroom.schemas.hat import BEANIE_STYLES, HatStyle, is_beanie_style
from headroom.services import retail_pricing
from headroom.services import capacity

pytestmark = pytest.mark.anyio

BEANIE_MODELS = ("journey", "destination", "all_day")


async def _hat(client, **fields):
    return await client.post(
        "/api/hats",
        json={"condition": "new", "size": "classic", "style": "a_game", **fields},
    )


# ------------------------------ the derivation ----------------------------- #


@pytest.mark.parametrize("style", BEANIE_MODELS)
async def test_a_named_beanie_is_a_beanie(client, style):
    body = (await _hat(client, style=style)).json()
    assert body["is_beanie"] is True, f"{style} did not derive is_beanie"


async def test_a_regular_style_is_not_a_beanie(client):
    assert (await _hat(client, style="a_game")).json()["is_beanie"] is False


async def test_every_beanie_style_is_declared(client):
    """`BEANIE_STYLES` must not fall behind the enum.

    Guards the exact mistake this file exists for: adding a shape to `HatStyle`
    and forgetting the set. Anything whose label says "Beanie" must be in it.
    """
    labels = {o["value"]: o["label"] for o in (await client.get("/api/meta/styles")).json()}
    for value, label in labels.items():
        if "beanie" in label.lower():
            assert value in BEANIE_STYLES, f"{value} looks like a beanie but isn't declared"


async def test_is_beanie_style_handles_absent_values():
    assert is_beanie_style(None) is False
    assert is_beanie_style("") is False
    assert is_beanie_style("a_game") is False
    assert is_beanie_style(HatStyle.journey) is True


# ------------------------------- consequences ------------------------------ #


async def test_named_beanies_pack_six_to_a_case(client):
    """The reason the derivation matters: a case takes MAX_BEANIE beanies, not
    MAX_REGULAR hats — the figures come from `capacity`, never retyped here."""
    case = (await client.post("/api/cases", json={"case_type": "archive"})).json()
    for i in range(capacity.MAX_BEANIE):
        resp = await _hat(client, style="journey", case_id=case["id"])
        assert resp.status_code == 201, f"beanie {i + 1} rejected: {resp.text}"

    detail = (await client.get(f"/api/cases/{case['display_id']}")).json()
    assert detail["beanie_count"] == capacity.MAX_BEANIE
    assert detail["regular_count"] == 0


async def test_a_named_beanie_cannot_share_a_case_with_regular_hats(client):
    """Type exclusivity has to see the new shapes as beanies too."""
    case = (await client.post("/api/cases", json={"case_type": "archive"})).json()
    await _hat(client, style="a_game", case_id=case["id"])

    resp = await _hat(client, style="destination", case_id=case["id"])

    assert resp.status_code == 409
    assert "beanie" in resp.text.lower() or "mix" in resp.text.lower()


async def test_changing_style_to_a_beanie_flips_the_flag(client):
    """`update_hat` re-derives on the same rule — it had its own copy of the
    comparison, which is how the two would have drifted apart."""
    hat_id = (await _hat(client, style="a_game")).json()["id"]

    body = (await client.put(f"/api/hats/{hat_id}", json={"style": "journey"})).json()

    assert body["style"] == "journey"
    assert body["is_beanie"] is True


async def test_beanie_filter_finds_the_named_shapes(client):
    """`?style=` is exact, but `is_beanie` is what the Type filter uses."""
    await _hat(client, style="all_day")
    hats = (await client.get("/api/hats")).json()
    assert [h for h in hats if h["is_beanie"]], "no hat reported as a beanie"


# ------------------------------- the API shape ----------------------------- #


async def test_meta_styles_publishes_the_beanie_flag(client):
    """Served rather than re-derived client-side: the flag decides which cases
    the picker offers, so a second definition in TypeScript would eventually
    disagree with the server and offer a case the save refuses."""
    options = {o["value"]: o for o in (await client.get("/api/meta/styles")).json()}

    for style in BEANIE_MODELS:
        assert options[style]["is_beanie"] is True
    assert options["a_game"]["is_beanie"] is False
    assert options["journey"]["label"] == "Journey Beanie"


# --------------------------------- pricing --------------------------------- #


@pytest.mark.parametrize("style", ["journey", "destination"])
async def test_named_beanies_are_priced_from_the_order_history(style):
    """$79 each: Journey (Dusty Sage #1715774, Mustard #1792264) and
    Destination (Military #1789227)."""
    assert retail_pricing.base_retail(style, None) == 79.0


async def test_all_day_has_no_asserted_price():
    """It appears in the order history exactly once, at $0.00 — the "FREE All
    Day Pom Beanie With Purchase" promo. A giveaway is not a retail price, and
    no melin email states its value, so there is no number to state.

    None is a real answer here (the same call made for Thermal and the Mill
    straw line): it falls through to Claude's estimate, clearly labeled as a
    guess, rather than inheriting the $79 that Journey and Destination
    establish for beanies there IS evidence for.
    """
    assert retail_pricing.base_retail("all_day", None) is None


async def test_a_promo_zero_never_becomes_the_retail_price():
    """Guards the specific poisoning route: $0.00 order lines exist."""
    price, source = retail_pricing.resolve_retail(
        "all_day", None, estimate=0.0, current=None, current_source=None
    )
    assert price != 79.0
    assert (price, source) == (0.0, "Claude Vision") or price is None
