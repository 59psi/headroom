"""What counts as evidence that a receipt is a hat's — fixes from the review
of 2.84.0's matcher.

Three ways a link could vouch for itself or pass on nothing: a series veto
that any shared "the" or "melin" satisfied; a price the link itself copied
onto the hat, counted as corroboration of that same link; and colorway and
size compared with `.lower()` where `naming` is the one "same name" rule.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from headroom.models import Hat, Purchase
from headroom.services import purchase_service

pytestmark = pytest.mark.anyio


def _hat(**kw) -> Hat:
    """A transient hat with just the fields matching reads; no colors."""
    hat = Hat(condition="new", size=kw.pop("size", "classic"), style="a_game")
    for k, v in kw.items():
        setattr(hat, k, v)
    hat.colors = []
    return hat


# ---- the series veto ------------------------------------------------------ #


@pytest.mark.parametrize("series", [
    "Melin x Hawaii (Explore The Unexplored)",  # shares only "the"
    "Melin Signature",                            # shares only "melin"
])
async def test_a_series_sharing_only_a_filler_word_is_still_ruled_out(series):
    """The veto needs a word that names the LINE. On this shelf a Hawaii hat
    scored 8 against "The Shore Hydro - Black" because both say "the"."""
    purchase = Purchase(
        item_title="MELIN The Shore Hydro - Black", model_name="The Shore Hydro",
        colorway="Black", size="classic", price=89.0,
    )
    hat = _hat(model_name="Shore Hydro", artist_series=series)

    assert purchase_service._match_score(purchase, hat) is None


async def test_a_series_sharing_a_real_word_still_passes():
    purchase = Purchase(
        item_title="Trenches Icon Hydro - Black Camo", model_name="Trenches Icon Hydro",
        colorway="Black Camo", size="classic", price=89.0,
    )
    hat = _hat(model_name="Trenches Hydro", artist_series="CAMO")

    assert purchase_service._match_score(purchase, hat) is not None


# ---- a link's own price is not evidence for it ---------------------------- #


def _linked(*, wrote_price: bool | None) -> Purchase:
    """A Black receipt linked to a Navy hat at the receipt's own $89.

    `wrote_price`: True — the link copied the price on; False — the hat had
    it already; None — a link from before `match_writes` was recorded.
    """
    hat = _hat(model_name="Trenches Hydro", colorway="Navy", purchase_price=89.0)
    purchase = Purchase(
        item_title="Trenches Hydro - Black", model_name="Trenches Hydro",
        colorway="Black", size="classic", price=89.0,
    )
    purchase.hat = hat
    purchase.hat_id = 7
    if wrote_price is not None:
        purchase.match_writes = json.dumps({"purchase_price": 89.0} if wrote_price else {})
    return purchase


async def test_a_price_the_link_copied_on_does_not_clear_it():
    """`is_suspect` called the price that this very link put on the hat
    "corroboration", which overrides the colorway veto — so a Navy hat holding
    a Black receipt never reached the To check list."""
    assert purchase_service.is_suspect(_linked(wrote_price=True))


async def test_a_legacy_links_price_is_not_trusted_either():
    """No record of what the link wrote: the price may be its own copy."""
    assert purchase_service.is_suspect(_linked(wrote_price=None))


async def test_a_price_the_hat_already_had_still_corroborates():
    """The hat carried $89 before the link, so it is a fact about the hat —
    the Hickory Denim case: same line, same price, a colorway the owner guessed."""
    assert not purchase_service.is_suspect(_linked(wrote_price=False))


async def test_the_pick_list_does_not_list_a_copied_price_as_a_reason(client):
    """The hat's own receipt was shown "price" among the reasons it fit —
    the price that receipt itself had written there."""
    hat = await client.post("/api/hats", json={
        "condition": "new", "size": "classic", "style": "odysea", "model_name": "Odysea Hydro",
    })
    hat_id = hat.json()["id"]
    imported = await client.post("/api/admin/purchases/import", json={"items": [{
        "item_title": "Odysea Hydro - Sage", "order_ref": "R1", "price": 79.0,
        "quantity": 1, "size": "Classic", "order_date": "2025-03-05",
    }]})
    assert imported.status_code == 200, imported.text
    purchase_id = next(
        p["id"] for p in (await client.get("/api/admin/purchases")).json() if p["order_ref"] == "R1"
    )
    await client.post(f"/api/admin/purchases/{purchase_id}/unmatch")
    linked = await client.post(f"/api/admin/purchases/{purchase_id}/link", json={"hat_id": hat_id})
    assert linked.status_code == 200, linked.text
    assert "purchase_price" in linked.json()["wrote"]

    options = (await client.get(f"/api/admin/purchases/{purchase_id}/hats")).json()["options"]
    own = next(o for o in options if o["hat_id"] == hat_id)

    assert "price" not in own["agrees"]


# ---- the one "same name" rule --------------------------------------------- #


async def test_colorways_are_compared_as_names_not_strings():
    """"Black/Gum" and "black gum" are one colorway; `.lower()` called them
    two, and two stated colorways that differ veto the pair."""
    purchase = Purchase(
        item_title="Trenches Hydro - Black/Gum", model_name="Trenches Hydro",
        colorway="Black/Gum", size="classic", price=89.0,
    )
    hat = _hat(model_name="Trenches Hydro", colorway="black gum")

    assert purchase_service._match_score(purchase, hat) is not None
    assert "colorway" in purchase_service._agreements(purchase, hat)


# ---- why a link is suspect ------------------------------------------------- #


@pytest.mark.parametrize(("hat_fields", "reason"), [
    ({"model_name": "Odysea Hydro"}, "model"),
    ({"model_name": "Trenches Hydro", "construction": "THERMAL"}, "construction"),
    ({"model_name": "Trenches Hydro", "artist_series": "Have More Fun"}, "series"),
    ({"model_name": "Trenches Hydro", "colorway": "Navy"}, "colorway"),
    ({"model_name": "Trenches Hydro", "size": "small"}, "size"),
    ({"model_name": "Trenches Hydro"}, None),
])
async def test_a_suspect_link_names_the_rule_that_rejects_it(hat_fields, reason):
    """The review list and the hat page blamed the series for every suspect
    link; the reason is now the veto that actually fires — the same one the
    matcher's "no match" comes from."""
    purchase = Purchase(
        item_title="Trenches Hydro - Black", model_name="Trenches Hydro",
        colorway="Black", size="classic", price=89.0,
    )
    purchase.hat = _hat(**hat_fields)
    purchase.hat_id = 7

    assert purchase_service.suspect_reason(purchase) == reason
    assert purchase_service.is_suspect(purchase) is (reason is not None)


async def test_a_vouched_or_unlinked_purchase_has_no_reason():
    purchase = Purchase(item_title="Trenches Hydro - Black", model_name="Trenches Hydro")
    purchase.hat = _hat(model_name="Odysea Hydro")
    assert purchase_service.suspect_reason(purchase) is None  # no hat_id: not linked
    purchase.hat_id = 7
    assert purchase_service.suspect_reason(purchase) == "model"
    purchase.link_confirmed_at = datetime.now(timezone.utc)
    assert purchase_service.suspect_reason(purchase) is None
