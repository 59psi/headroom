"""melin retail prices, looked up rather than guessed.

`estimated_new_price` used to come entirely from Claude Vision: the prompt
carried a block of price "anchors" and asked the model to estimate from a
photo. That is the wrong mechanism for the one brand this app is built around.
A photo cannot show a price, so the anchors WERE the answer — and they were
years stale ("HYDRO caps — $69 is the common price") which quietly mispriced
the whole collection, including the retail-share fallback in valuation.

The prices below are the owner's own, cross-checked against 223 order lines
from his melin order history:

    HYDROLite   $99 x16, $89 x1           -> $99, unambiguous
    HYDRO       $89 x67, $69 x30, $79 x29 -> the band has moved over the years;
                                             $79 is the current base
    Beanie      $79 x3                    -> $79 (Destination, Journey)
    Case        $49 x34, $39 x15          -> $49 (3 Hat Travel Case)
    Aviator     $179 (Scout Thermal), $139 (Infinite Thermal)
    Mill/straw  $99 (Pinya, United), $180 (Little Havana, Y'allternative)

Two things this table deliberately does NOT do:

* It does not price every construction. Thermal came back $79/$89/$99 across
  caps and $139/$179 on Aviators, and the Mill straw line runs $99 to $180 —
  none of those is one number, and none is a number this file should invent.
  Anything absent falls through to Claude's estimate, which is a guess clearly
  labelled as one.
* It does not model the premium tier. Some hats are $89 rather than $79 —
  collabs, artist series, particular colorways — and there is no field that
  reliably predicts which. The base is what a plain example costs; a hat that
  cost more is corrected per-hat, and that correction now STICKS (see
  `estimated_new_price_source == "Manual"`).
"""

from __future__ import annotations

MANUAL_SOURCE = "Manual"
TABLE_SOURCE = "melin retail"

# Keyed on the normalised construction word. Lower-case, substring-matched the
# same way `Hat.set_construction` derives its flags — HYDROLite is checked
# first because "hydro" is a substring of it.
_BY_CONSTRUCTION: tuple[tuple[str, float], ...] = (
    ("hydrolite", 99.0),
    ("hydro", 79.0),
)

# Aviator is a SHAPE, not a construction, and sits in its own price class: the
# owner's two are a Scout Thermal at $179 and an Infinite Thermal at $139, so
# construction alone would price them like a cap. $99 is his stated floor —
# used only as a base when nothing better is known, never to pull a higher
# known price down.
_BY_STYLE: dict[str, float] = {
    "aviator": 99.0,
    # Beanies are a shape with no construction of their own. $79 across every
    # one in the order history: Journey (Dusty Sage #1715774, Mustard #1792264)
    # and Destination (Military #1789227).
    "beanie": 79.0,
    "journey": 79.0,
    "destination": 79.0,
    # `all_day` is DELIBERATELY absent. It appears in the order history exactly
    # once, at $0.00 — the "FREE All Day Pom Beanie With Purchase" promo — and
    # a giveaway price is not a retail price. No melin email states its value,
    # so there is no number here to state. Falling through to Claude's estimate
    # is the honest answer, the same call made for Thermal and the Mill straw
    # line; inheriting the $79 that Journey and Destination establish would be
    # asserting a price for the one beanie there is no evidence for.
}

# The physical article the whole app is organised around: melin's 3 Hat Travel
# Case. $49 x34 and $39 x15 in the order history — the $39s are the older
# price, the same drift that left the hat anchors stale.
#
# A Case has no price COLUMN: every one of them is the same product at the same
# price, so storing it per row would be 40 copies of one number waiting to
# disagree. `CaseRead.retail_price` publishes it instead.
CASE_RETAIL = 49.0


def base_retail(style: str | None, construction: str | None) -> float | None:
    """melin's base retail for this hat, or None if the table doesn't know.

    None is a real answer and must stay one: it means "no better than a guess
    is available", which is the caller's cue to keep Claude's estimate rather
    than substitute a number this module made up.
    """
    text = (construction or "").strip().lower()
    for needle, price in _BY_CONSTRUCTION:
        if needle in text:
            return price
    return _BY_STYLE.get((style or "").strip().lower())


def resolve_retail(
    style: str | None,
    construction: str | None,
    *,
    estimate: float | None,
    current: float | None,
    current_source: str | None,
) -> tuple[float | None, str | None]:
    """Decide the retail price and where it came from. Returns (price, source).

    Order, and the reasoning for it:

    1. **A manual price wins outright.** Somebody read a tag or an order
       confirmation; nothing derived should overwrite that. This is the same
       rule `resale_price_scope == "manual"` already enforces, and for the same
       reason — an unattended re-analysis silently replacing a number a person
       entered is the worst kind of data loss, because it looks like nothing
       happened.
    2. **The table, when it knows.** A looked-up price beats a guess.
    3. **Claude's estimate**, kept as-is and labelled as a guess.

    Note that (2) never pulls a KNOWN-higher price down: if the estimate
    exceeds the base — a collab, an artist series, a premium colorway — the
    higher figure is kept, because the base is what a plain example costs and
    the table has no way to see which hats are the exceptions.
    """
    if current_source == MANUAL_SOURCE and current is not None:
        return current, MANUAL_SOURCE

    base = base_retail(style, construction)
    if base is None:
        return estimate, ("Claude Vision" if estimate is not None else None)

    if estimate is not None and estimate > base:
        # Above the base is plausible (collab / limited run); below it is the
        # systematic under-estimation this table exists to stop.
        return estimate, "Claude Vision"
    return base, TABLE_SOURCE


async def backfill_retail_prices(db) -> int:
    """Re-price every hat the table knows about. Returns how many changed.

    Existing hats were priced by the stale prompt anchors, so fixing the code
    alone would leave a collection where the number depends on *when* a hat was
    photographed. Run once from lifespan behind a settings flag, like the other
    one-time repairs.

    Manual prices are untouched — `resolve_retail` enforces that, and this walks
    every hat through it rather than reimplementing the rule.
    """
    from sqlalchemy import select

    from headroom.models.hat import Hat

    changed = 0
    for hat in (await db.execute(select(Hat))).scalars().all():
        price, source = resolve_retail(
            hat.style,
            hat.construction,
            # Deliberately NOT passing the stored price as the estimate: it may
            # itself be a stale-anchor number, and feeding it back in would let
            # a wrong $69 outrank the $79 the table now knows. A hat whose
            # price genuinely came from Claude keeps it only when the table has
            # nothing better, which `estimate=None` still allows.
            estimate=hat.estimated_new_price
            if hat.estimated_new_price_source == "Claude Vision" else None,
            current=hat.estimated_new_price,
            current_source=hat.estimated_new_price_source,
        )
        if (price, source) != (hat.estimated_new_price, hat.estimated_new_price_source):
            hat.estimated_new_price, hat.estimated_new_price_source = price, source
            changed += 1
    await db.commit()
    return changed
