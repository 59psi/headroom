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
melinrecap is a FIXED-PRICE marketplace with automatic drops — a buyer clicks
buy at the number shown — so the listed price is the sale price and nothing is
discounted off it. What makes a median comparable is filtering, done upstream
in `melin_recap.fetch_resale_stats`: it matches listings on the hat's own
condition and size rather than averaging the category and multiplying by a
guess. The guesses it replaced were measurably wrong against 706 live
listings, and unnecessary when the real number is in the feed.
"""

from __future__ import annotations

from dataclasses import dataclass

from headroom.models.hat import Hat, ResaleScope
from headroom.services import retail_pricing

def value_cases(count: int) -> float:
    """What `count` cases are worth, at replacement cost.

    Mirrors `valueCases()` in the TypeScript, and lives here rather than in
    `report_service` for the reason the module docstring gives: the valuation
    rule is stated once per language, and the parity test only guards the
    copies it can see. A third statement of it inside the report renderer is
    exactly the drift this file exists to prevent — and it had already begun,
    charging a flat `CASE_RETAIL` per row where the browser sums each case's
    own served `retail_price`.

    Reads `retail_pricing.CASE_RETAIL` rather than restating $49, so there is
    one number even across the two rules.
    """
    return count * retail_pricing.CASE_RETAIL


#: What the marketplace pays a seller, as a fraction of the sale price.
CASH_PAYOUT = 0.80
CREDIT_PAYOUT = 1.10

#: Fraction of new retail retained, when there is no market signal at all.
RETAIL_RETENTION: dict[str, float] = {
    "new_with_tags": 0.65,
    "new": 0.45,
    "worn": 0.30,
}

#: Applied when a hat's condition is not one of the three known values.
#: Public, and named identically to the TS side, so `test_valuation_parity`
#: can compare them — see the note in `lib/valuation.ts`.
FALLBACK_RETENTION = 0.4

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

    if hat.resale_price_scope == ResaleScope.MANUAL and ask > 0:
        return HatValue(ask, "manual")

    if hat.resale_price_scope == ResaleScope.MODEL and ask > 0:
        return HatValue(ask, "comp")

    if retail > 0:
        retention = RETAIL_RETENTION.get(condition, FALLBACK_RETENTION)
        return HatValue(retail * retention, "retail")

    if ask > 0:
        return HatValue(ask, "category")

    return HatValue(None, "none")
