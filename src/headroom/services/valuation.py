"""What a hat is worth — the server's copy of the rule.

The authoritative statement of this rule, with the full reasoning, is
`frontend/src/lib/valuation.ts`. It lives there because every screen that
shows a value is React; this module exists only because the printable
inventory report is rendered server-side and cannot import TypeScript.

Two copies of one rule is the exact failure this rework was undoing — there
were three, and the home page ended up describing a calculation that was no
longer running. What stops it recurring here is
`tests/test_valuation_parity.py`, which reads the constants out of the
TypeScript file and asserts they match the ones below. A change to either side
alone fails the suite.

The short version of the reasoning, so this file is readable on its own:
neither price feed knows what anything sold for. eBay's Browse API returns
currently-listed items and the melinrecap figure is a median of live listings —
both are ASKING prices, so they get discounted, then adjusted for the condition
of the specific hat rather than the mixed pool the median came from.
"""

from __future__ import annotations

from dataclasses import dataclass

from headroom.models.hat import Hat

#: Asking price -> realistic sale price.
ASK_TO_SOLD = 0.85

#: This hat versus the mixed-condition pool a market median is drawn from.
CONDITION_VS_MARKET: dict[str, float] = {
    "new_with_tags": 1.0,
    "new": 0.92,
    "worn": 0.78,
}

#: Fraction of new retail retained, when there is no market signal at all.
RETAIL_RETENTION: dict[str, float] = {
    "new_with_tags": 0.65,
    "new": 0.45,
    "worn": 0.30,
}

_FALLBACK_RETENTION = 0.4
_FALLBACK_CONDITION_VS_MARKET = 0.9

#: Display names for each basis, matching the UI's `BASIS_LABEL`.
BASIS_LABEL: dict[str, str] = {
    "manual": "Your price",
    "comp": "Model comps",
    "retail": "From retail",
    "category": "Category avg",
    "none": "Not valued",
}


@dataclass(frozen=True)
class HatValue:
    """`value` is None when nothing on the record supports a number.

    Deliberately not 0.0: a hat nobody has priced is not a worthless hat, and
    every total that summed it as one was understating the collection while
    looking precise.
    """

    value: float | None
    basis: str


def value_hat(hat: Hat) -> HatValue:
    """Best estimate of what one hat fetches if sold today, and on what basis."""
    ask = hat.resale_price or 0.0
    retail = hat.estimated_new_price or 0.0
    condition = hat.condition or ""

    if hat.resale_price_scope == "manual" and ask > 0:
        return HatValue(ask, "manual")

    if hat.resale_price_scope == "model" and ask > 0:
        return HatValue(_market_adjusted(ask, condition), "comp")

    if retail > 0:
        retention = RETAIL_RETENTION.get(condition, _FALLBACK_RETENTION)
        return HatValue(retail * retention, "retail")

    if ask > 0:
        return HatValue(_market_adjusted(ask, condition), "category")

    return HatValue(None, "none")


def _market_adjusted(ask: float, condition: str) -> float:
    factor = CONDITION_VS_MARKET.get(condition, _FALLBACK_CONDITION_VS_MARKET)
    return ask * ASK_TO_SOLD * factor
