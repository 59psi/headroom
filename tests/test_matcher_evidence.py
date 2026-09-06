"""Which receipt wins a contended hat — and therefore which price gets written.

These exist because mutation testing showed the suite executing every line of
the purchase matcher's scoring while constraining none of it. With
`catalog_service.py` at 93% line coverage, each of the following left all 988
tests green: zeroing BOTH bonus tiers, deleting the local-search call site,
disabling the exact-price tiebreak, collapsing the stripped-model tier into
the contained one, and dropping `colorway` from the preview's evidence list.
The tests covered the code; they did not constrain what it decided.

Every test here asserts an OUTCOME — a `hat_id` link or the `purchase_price`
that landed on a hat — never a score. A score assertion would only restate
the constant it is meant to check and would pass under any mutation that kept
the arithmetic consistent. Each docstring names the mutation it was written
against and was confirmed to fail under it.

The recurring fixture shape is the one from the review that found this: two
receipts share a model, one costs $79 and the other $999, and only the tier
under test separates them. Under the mutation the $999 line writes its price
onto the hat — measured on the real history as a cost basis of $999 where
$79 was provable.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from headroom.models.catalog import Purchase
from headroom.models.hat import Hat
from headroom.models.hat_color import HatColor
from headroom.services import catalog_service

pytestmark = pytest.mark.anyio


async def _hat(
    client, db_session, *, model, size="classic", colorway=None,
    artist_series=None, purchase_price=None, colors=(),
) -> int:
    resp = await client.post(
        "/api/hats", json={"condition": "new", "size": size, "style": "trenches"}
    )
    assert resp.status_code == 201, resp.text
    hat_id = resp.json()["id"]
    row = await db_session.get(Hat, hat_id)
    row.model_name = model
    row.colorway = colorway
    row.artist_series = artist_series
    row.purchase_price = purchase_price
    for rank, (name, general) in enumerate(colors, start=1):
        db_session.add(HatColor(
            hat_id=hat_id, color_name=name, general_color=general,
            hex_value="#000000", dominance_rank=rank,
        ))
    await db_session.commit()
    return hat_id


def _purchase(db_session, *, title, model, price, size=None, colorway=None) -> Purchase:
    """Inserted in call order — which is the order the matcher visits ties in."""
    row = Purchase(
        source="test", item_title=title, model_name=model,
        colorway=colorway, size=size, price=price, quantity=1,
    )
    db_session.add(row)
    return row


async def _price_of(client, hat_id) -> float | None:
    return (await client.get(f"/api/hats/{hat_id}")).json()["purchase_price"]


async def _linked_to(db_session, hat_id) -> list[float]:
    """Prices of every purchase linked to this hat, for hats that already had one."""
    db_session.expire_all()
    rows = (await db_session.execute(
        select(Purchase).where(Purchase.hat_id == hat_id)
    )).scalars().all()
    return [p.price for p in rows]


# --------------------------------------------------------------------------
# The bonus tiers decide contended hats. (Mutation: STATED_FIELD = 0,
# COLOR_WORD = 0 — both survived with 988 green.)
# --------------------------------------------------------------------------


async def test_a_stated_series_in_the_title_decides_a_contended_hat(client, db_session):
    """STATED_FIELD. Two receipts for one hat; only the owner's series separates them.

    The $999 line is inserted FIRST on purpose. Under `STATED_FIELD = 0` the two
    tie, ties go to insertion order, and the hat is written a $999 cost basis
    with the receipt that actually names its series left unmatched.
    """
    hat = await _hat(client, db_session, model="Trenches Icon Hydro", artist_series="Links")

    _purchase(db_session, title="Trenches Icon Hydro - Camo",
              model="Trenches Icon Hydro", size="classic", price=999.0)
    _purchase(db_session, title="Trenches Icon Hydro - Links Camo",
              model="Trenches Icon Hydro", size="classic", colorway="Links Camo", price=79.0)
    await db_session.commit()

    result = await catalog_service.match_purchases_to_hats(db_session)

    assert result["matched"] == 1
    assert await _price_of(client, hat) == 79.0, (
        "the receipt naming the hat's own series lost to one that merely shares "
        "the model — the STATED_FIELD bonus is not deciding anything"
    )


async def test_a_color_read_off_the_photo_decides_a_contended_hat(client, db_session):
    """COLOR_WORD. Same shape; the only separator is the analyzer's color words.

    A hat with no recorded colorway still has the colors read off its own
    photo, and on an unmatched shelf that is the one tiebreaker available.
    """
    hat = await _hat(client, db_session, model="Odysea Hydro", colors=[("Black", "black")])

    _purchase(db_session, title="Odysea Hydro - Bone",
              model="Odysea Hydro", size="classic", colorway="Bone", price=999.0)
    _purchase(db_session, title="Odysea Hydro - Black",
              model="Odysea Hydro", size="classic", colorway="Black", price=79.0)
    await db_session.commit()

    result = await catalog_service.match_purchases_to_hats(db_session)

    assert result["matched"] == 1
    assert await _price_of(client, hat) == 79.0, (
        "the receipt whose colorway matches the photo lost to one that "
        "contradicts it — the COLOR_WORD bonus is not deciding anything"
    )


async def test_an_exact_price_decides_between_otherwise_identical_receipts(client, db_session):
    """PRICE_EXACT. (Mutation: `PRICE_EXACT = 0` — survived.)

    The hat already carries the price its owner typed off the order
    confirmation, so matching will not rewrite it; the outcome is WHICH
    purchase gets linked. A price agreeing to the cent is the only signal here
    that is a fact rather than somebody's words for a color, and the docstring
    ranks it above every descriptive one. Nothing checked that it ranked above
    zero.
    """
    hat = await _hat(client, db_session, model="A-Game Hydro", purchase_price=79.0)

    _purchase(db_session, title="A-Game Hydro - Black",
              model="A-Game Hydro", size="classic", price=999.0)
    _purchase(db_session, title="A-Game Hydro - Black",
              model="A-Game Hydro", size="classic", price=79.0)
    await db_session.commit()

    result = await catalog_service.match_purchases_to_hats(db_session)

    assert result["matched"] == 1
    assert await _linked_to(db_session, hat) == [79.0], (
        "the receipt matching the owner's price to the cent lost to one that "
        "does not — PRICE_EXACT is not deciding anything"
    )


# --------------------------------------------------------------------------
# The local search is WIRED IN, not merely correct. (Mutation: delete the
# `_improve_by_swapping(...)` call in `assign_purchases` — survived, because
# `test_catalog.py` drives the function directly and never the call site.)
# --------------------------------------------------------------------------


async def test_the_best_evidenced_receipt_wins_even_after_kuhns_displaces_it(client, db_session):
    """End to end, through `match_purchases_to_hats`, the 910-vs-1500 shape.

    Two hats of one model in two sizes. P1 has no size and fits BOTH, but fits
    the Classic far better (its series and its color agree). P2 is Classic-only
    and P3 Small-only. Kuhn's takes P1 -> Classic, then P2 displaces it onto
    the Small to lengthen the path, and P3 is left out — two links, the
    Classic carrying P2's $999.

    The same two links are worth more as P1 -> Classic ($79) and P3 -> Small:
    that needs the PURCHASE end of a pair to change, which only the substitute
    move can do. The function that does it has its own tests; this is the test
    that it is actually called, since deleting the call left every one of them
    green.

    Deliberately robust to reversing the purchase iteration order: with local
    search present, order is a fast path, not the guarantee. Removing BOTH
    order and local search fails this; removing order alone does not, and that
    is the defense in depth working as intended rather than a gap.
    """
    classic = await _hat(client, db_session, model="Trenches Icon Hydro", size="classic",
                         artist_series="Links", colors=[("Black", "black")])
    small = await _hat(client, db_session, model="Trenches Icon Hydro", size="small")

    _purchase(db_session, title="Trenches Icon Hydro - Links Black",           # P1
              model="Trenches Icon Hydro", colorway="Links Black", price=79.0)
    _purchase(db_session, title="Trenches Icon Hydro - Camo",                  # P2
              model="Trenches Icon Hydro", size="classic", price=999.0)
    _purchase(db_session, title="Trenches Icon Hydro - Bone",                  # P3
              model="Trenches Icon Hydro", size="small", price=85.0)
    await db_session.commit()

    result = await catalog_service.match_purchases_to_hats(db_session)

    assert result["matched"] == 2, "two hats, two links — cardinality must be maximum"
    assert await _price_of(client, classic) == 79.0, (
        "the Classic took the $999 line: Kuhn's displaced the best-evidenced "
        "receipt and nothing moved it back — the local search is not wired in"
    )
    assert await _price_of(client, small) == 85.0


# --------------------------------------------------------------------------
# Tier ORDERING, stated in the docstrings and checked nowhere. (Mutation:
# `return MODEL_EXACT_STRIPPED` -> `return MODEL_CONTAINED` — survived.)
#
# As OUTCOMES, like everything else in this file. An earlier version asserted
# `contained < stripped < exact` and `MODEL_CONTAINED + STATED_FIELD <
# MODEL_EXACT` directly — score assertions, in the one file whose header
# forbids them, and ones that pass under any mutation keeping the arithmetic
# consistent. Each relationship below is a contended hat where only that
# relationship decides which receipt writes its price.
# --------------------------------------------------------------------------


async def test_a_stripped_exact_match_beats_a_mere_prefix_for_the_same_receipt(client, db_session):
    """MODEL_EXACT_STRIPPED > MODEL_CONTAINED.

    One receipt for "Eagle Mill Union"; two free hats. "Eagle Mill Union Denim"
    is both sides naming the same LINE (one also naming the fabric); "Eagle
    Mill" is a prefix of it. The receipt must land on the Denim hat. Under the
    collapse mutation the two tiers tie and insertion order decides — so the
    prefix hat is created first, and takes the price under the mutation.
    """
    prefix_hat = await _hat(client, db_session, model="Eagle Mill")
    line_hat = await _hat(client, db_session, model="Eagle Mill Union Denim")

    _purchase(db_session, title="Eagle Mill Union - Hickory",
              model="Eagle Mill Union", size="classic", price=129.0)
    await db_session.commit()

    result = await catalog_service.match_purchases_to_hats(db_session)

    assert result["matched"] == 1
    assert await _price_of(client, line_hat) == 129.0, (
        "the hat naming the receipt's own line lost to a hat that is merely a "
        "prefix of it — the stripped-exact tier is not above the contained one"
    )
    assert await _price_of(client, prefix_hat) is None


async def test_a_literal_exact_match_beats_a_stripped_one(client, db_session):
    """MODEL_EXACT > MODEL_EXACT_STRIPPED: the names being literally the same
    outranks the names being the same once a fabric word is removed."""
    stripped_hat = await _hat(client, db_session, model="Eagle Mill Union Denim")
    exact_hat = await _hat(client, db_session, model="Eagle Mill Union")

    _purchase(db_session, title="Eagle Mill Union - Hickory",
              model="Eagle Mill Union", size="classic", price=129.0)
    await db_session.commit()

    await catalog_service.match_purchases_to_hats(db_session)

    assert await _price_of(client, exact_hat) == 129.0
    assert await _price_of(client, stripped_hat) is None


async def test_an_exact_model_outranks_a_contained_one_carrying_the_series(client, db_session):
    """MODEL_CONTAINED + STATED_FIELD < MODEL_EXACT.

    The sentence beside the constants: "an exact model hit must outrank a
    contained one that also carries a series, or the generic-family match
    would beat the product the receipt names." One receipt for "Trenches Icon
    Hydro - Camo"; the family-named hat ALSO carries the series `Icon` in its
    owner-stated field, so it collects the series bonus on top of containment.
    The product-named hat must still win.
    """
    family_hat = await _hat(client, db_session, model="Trenches Hydro", artist_series="Icon")
    product_hat = await _hat(client, db_session, model="Trenches Icon Hydro")

    _purchase(db_session, title="Trenches Icon Hydro - Camo",
              model="Trenches Icon Hydro", size="classic", colorway="Camo", price=79.0)
    await db_session.commit()

    await catalog_service.match_purchases_to_hats(db_session)

    assert await _price_of(client, product_hat) == 79.0, (
        "a generic family match plus a series bonus beat the product the receipt names"
    )
    assert await _price_of(client, family_hat) is None


async def test_an_owner_stated_series_outranks_a_color_word(client, db_session):
    """STATED_FIELD > COLOR_WORD: "Weakest signal here" is the color word.

    Two hats of one model, both free. One carries the series the receipt names
    in its owner-stated field; the other carries a color word the receipt's
    colorway mentions, read off its photo. The series is a fact somebody
    typed; the color is the analyzer's word for a swatch. The series wins.
    """
    color_hat = await _hat(client, db_session, model="Trenches Icon Hydro",
                           colors=[("Black", "black")])
    series_hat = await _hat(client, db_session, model="Trenches Icon Hydro",
                            artist_series="Links")

    _purchase(db_session, title="Trenches Icon Hydro - Links Black",
              model="Trenches Icon Hydro", size="classic", colorway="Links Black", price=89.0)
    await db_session.commit()

    await catalog_service.match_purchases_to_hats(db_session)

    assert await _price_of(client, series_hat) == 89.0, (
        "a color word read off a photo outranked a series the owner stated"
    )
    assert await _price_of(client, color_hat) is None


# --------------------------------------------------------------------------
# The preview shows its working. (Mutation: drop "colorway" from `_matched_on`
# — survived.)
# --------------------------------------------------------------------------


async def test_the_preview_names_every_field_that_agreed(client, db_session):
    """`matched_on` is the column the operator reads before pressing Import.

    A colorway that agreed and is not listed makes a strong match read as a
    weak one; a size that agreed and is not listed hides the reason a Small was
    chosen over a Classic. Nothing asserted the list's contents.
    """
    await _hat(client, db_session, model="A-Game Hydro", colorway="Black", size="small")

    preview = await catalog_service.preview_import(db_session, [
        {"item_title": "A-Game Hydro - Black", "size": "Small", "price": 79.0},
    ])

    assert preview["would_match"] == 1, preview
    assert preview["proposals"][0]["matched_on"] == ["model", "colorway", "size"]
