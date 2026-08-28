"""Melin Recap resale data: deep links + live comparable-listing stats.

melinrecap.com is a Treet marketplace running on Sharetribe Flex. The
storefront is client-rendered (static HTML has no prices), but its own
frontend talks to the public Sharetribe Marketplace API with an anonymous
`public-read` token — the client id is embedded in their JS bundle. We use
the same API the same way any visitor's browser does: one listings query per
analysis, filtered by the hat's style category, prices aggregated to a
median. No scraping, no headless browser (Pi-friendly).

Deep links are still generated as the browse affordance; the live median
fills `resale_price` where we previously left null. If the API is
unreachable (or Treet rotates the client id — override via
HEADROOM_MELIN_CLIENT_ID), callers degrade to link-only, exactly the old
behavior.
"""

from __future__ import annotations

import logging
import re
import time
from statistics import median
from urllib.parse import urlencode

import httpx

from headroom.config import settings

logger = logging.getLogger(__name__)

MELIN_BASE = "https://www.melinrecap.com"
FLEX_API = "https://flex-api.sharetribe.com/v1"

# Fewer than this many title-matched listings → widen to the whole category.
_MIN_MODEL_SAMPLE = 3


class MelinRecapError(Exception):
    pass

# Maps our internal style enum to melinrecap's pub_category values.
# Verified against the marketplace's "By Shape" navigation.
# Public: `catalog_service` harvests the whole catalog and needs both the
# category map and the query primitive. It was importing them through their
# underscore names, which claims "private" while a second module depends on
# them — so a future refactor would read this as safe to change freely.
STYLE_TO_CATEGORY: dict[str, str] = {
    "a_game": "aGame",
    "coronado": "coronado",
    "odysea": "odysea",
    "trenches": "trenches",
    "eagle": "eagle",
    "compass": "compass",
    "legend": "legend",
    "caddy": "caddy",
    "coast": "coast",
}


def is_melin(brand: str | None) -> bool:
    return bool(brand) and "melin" in brand.lower()


def melin_recap_link(style: str | None) -> str | None:
    """Return a deep link to the relevant Melin Recap filter page, or None."""
    if not style:
        return f"{MELIN_BASE}/"
    category = STYLE_TO_CATEGORY.get(style.lower())
    if not category:
        return f"{MELIN_BASE}/"
    qs = urlencode({"mode": "filter-change", "pub_category": category})
    return f"{MELIN_BASE}/?{qs}"


def build_resale_pointer(brand: str | None, style: str | None) -> dict | None:
    """Return resale fields to persist on the Hat record, or None.

    Only emits a pointer when the brand looks like Melin. `resale_price`
    stays null here; `fetch_resale_stats()` fills it with a live median
    when the marketplace API is reachable.
    """
    if not is_melin(brand):
        return None
    return {
        "resale_price": None,
        "resale_price_source": "Melin Recap",
        "resale_price_url": melin_recap_link(style),
    }


# ---------------------- live marketplace stats ------------------------ #

# Anonymous public-read token, cached module-wide. Sharetribe grants these
# freely; we refresh conservatively and retry once on a 401.
_token: str | None = None
_token_fetched_at: float = 0.0
_TOKEN_TTL_S = 20 * 60


async def _get_anon_token(client: httpx.AsyncClient, *, force: bool = False) -> str:
    global _token, _token_fetched_at
    if not force and _token and (time.monotonic() - _token_fetched_at) < _TOKEN_TTL_S:
        return _token
    resp = await client.post(
        f"{FLEX_API}/auth/token",
        data={
            "client_id": settings.melin_client_id,
            "grant_type": "client_credentials",
            "scope": "public-read",
        },
    )
    if resp.status_code != 200:
        raise MelinRecapError(
            f"Sharetribe auth {resp.status_code} — client id may have rotated "
            "(override with HEADROOM_MELIN_CLIENT_ID)"
        )
    _token = resp.json().get("access_token")
    _token_fetched_at = time.monotonic()
    if not _token:
        raise MelinRecapError("Sharetribe auth returned no access_token")
    return _token


async def query_listings(params: dict) -> list[dict]:
    """One listings query against the Flex API. Seam for tests."""
    try:
        async with httpx.AsyncClient(timeout=settings.http_timeout) as client:
            token = await _get_anon_token(client)
            resp = await client.get(
                f"{FLEX_API}/api/listings/query",
                params=params,
                headers={"Authorization": f"bearer {token}"},
            )
            if resp.status_code == 401:  # stale cached token — re-auth once
                token = await _get_anon_token(client, force=True)
                resp = await client.get(
                    f"{FLEX_API}/api/listings/query",
                    params=params,
                    headers={"Authorization": f"bearer {token}"},
                )
    except httpx.HTTPError as exc:
        # ERROR, not a bare raise. The caller catches MelinRecapError and
        # degrades to a link, which is right — but it means a total outage is
        # invisible from the outside except as every hat quietly losing its
        # resale price. This module had a logger and never once used it.
        logger.error("Melin Recap lookup failed: %s", exc)
        raise MelinRecapError(f"Melin Recap lookup failed: {exc}") from exc
    if resp.status_code != 200:
        # The documented failure mode is Treet rotating the anonymous client
        # id, which arrives as a 401/403 on every call. Naming the status is
        # the difference between "prices stopped" and a diagnosis.
        logger.error(
            "Melin Recap query returned %s: %s", resp.status_code, resp.text[:200]
        )
        raise MelinRecapError(f"Melin Recap query {resp.status_code}: {resp.text[:200]}")
    return resp.json().get("data", [])


#: The API's maximum page size. Its `meta` block reports `totalItems` and
#: `totalPages` alongside every response — both were discarded.
_PAGE_SIZE = 100

#: Pages walked per category before giving up. Six covers every melinrecap
#: category with room to spare; the largest (odysea) holds 436 listings.
_MAX_PAGES = 6

#: Anything that is not a letter or digit is a separator, never part of a token.
_TOKEN_SPLIT = re.compile(r"[^a-z0-9]+")


def model_tokens(name: str | None) -> list[str]:
    """Lowercase word tokens, punctuation stripped.

    Splitting on whitespace alone left punctuation glued to the tokens. A hat
    named ``Odysea Hydro "Have More Fun"`` then demanded the tokens ``"have``
    and ``fun"``, which appear in no listing title that has ever existed — so
    the model tier matched nothing and the hat fell through to a category
    median. Applied to BOTH sides, or the normalization is one-sided and the
    comparison is still between different alphabets.
    """
    return [t for t in _TOKEN_SPLIT.split((name or "").lower()) if t]


async def query_all_listings(params: dict, max_pages: int = _MAX_PAGES) -> list[dict]:
    """Every listing matching `params`, not just the first page.

    `fetch_resale_stats` used to send one request and take what came back. The
    odysea category holds **436** listings, so that read 23% of the market and
    priced every Odysea in the collection off whichever quarter the API
    happened to return first — 28 different hats landing on the identical
    $115.00, which is the median of an arbitrary slice, not any hat's value.

    Termination is a short page rather than `meta.totalPages`, so this keeps
    `query_listings` as the single seam tests already patch instead of adding
    a second one that only the real API populates.
    """
    out: list[dict] = []
    for page in range(1, max_pages + 1):
        rows = await query_listings({**params, "perPage": _PAGE_SIZE, "page": page})
        out.extend(rows)
        if len(rows) < _PAGE_SIZE:
            break
    return out


# Payout rates (what a seller receives: 80% cash / 110% credit) deliberately
# do NOT live here. They were defined in this module too, unused by anything,
# and outside the reach of `tests/test_valuation_parity.py` — a third copy of a
# number the app prints to a person, free to drift from the two the parity test
# actually guards. They belong to valuation: see `frontend/src/lib/valuation.ts`
# and its mirror `services/valuation.py`. Re-check them by reading
# `publicData.payoutInfo` off any listing.

# Marketplace condition vocabulary -> the app's three conditions.
# Anything not listed (good, fair, and whatever gets added later) is worn:
# an unrecognized condition is certainly not new, and guessing "new" would
# quietly inflate every valuation that used it.
_CONDITION_MAP: dict[str, str] = {
    "new_with_tags": "new_with_tags",
    "new_without_tags": "new",
    "excellent": "worn",
    "good": "worn",
    "fair": "worn",
}

# Marketplace size vocabulary -> `Hat.size`. Both spellings appear in live
# data. One-size entries map to nothing: they are visors and accessories,
# not a size a fitted hat can be compared against.
_SIZE_MAP: dict[str, str] = {
    "c": "classic", "classic": "classic",
    "s": "small", "small": "small",
    "xl": "x_large", "x-large": "x_large", "xlarge": "x_large",
}


def _listing_facts(li: dict) -> tuple[str, float, str | None, str | None] | None:
    """(title, dollars, condition, size) for one listing, or None if unusable."""
    attrs = li.get("attributes") or {}
    amount = (attrs.get("price") or {}).get("amount")
    if not amount:
        return None
    pub = attrs.get("publicData") or {}
    raw_size = (pub.get("size") or "").strip().lower()
    raw_condition = (pub.get("condition") or "").strip().lower()
    return (
        attrs.get("title", ""),
        amount / 100,
        # A condition that is STATED but unrecognized falls to "worn": the
        # marketplace's two "new" grades are the ones enumerated above, so a
        # value outside that set is some flavor of used. Defaulting the other
        # way would let a vocabulary addition quietly inflate valuations.
        # A condition that is ABSENT stays None — unknown, not worn.
        _CONDITION_MAP.get(raw_condition, "worn" if raw_condition else None),
        _SIZE_MAP.get(raw_size),
    )


async def fetch_resale_stats(
    style: str | None,
    model_name: str | None = None,
    condition: str | None = None,
    size: str | None = None,
) -> dict | None:
    """Median live price for genuinely comparable listings, or None.

    **The listed price is the sale price here.** This is a fixed-price Treet
    marketplace with automatic 10% drops, not an auction and not a
    negotiation — a buyer clicks buy at the number shown. So no ask-to-sold
    haircut is applied anywhere downstream, and the figure this returns is
    what the hat actually changes hands for.

    What makes it comparable is filtering, not arithmetic. Every listing
    carries its own `condition` and `size` in `publicData`, and this used to
    ignore both: it took one median across all conditions and left the caller
    to multiply by a guessed condition factor. Measured against 706 live
    listings those guesses were wrong (new-without-tags is 0.95 of
    new-with-tags, not 0.92; worn is 0.82, not 0.78) and, more to the point,
    guessing was never necessary when the real number is right there.

    Narrows most-specific-first and stops at the first tier with a real
    sample, so a hat is priced against its own model, condition and size when
    the market supports it and against something honestly broader when it
    doesn't. Returns {"median", "count", "sample", "condition_matched",
    "size_matched"} — `sample` is "model" or "category" for the display label.
    """
    category = STYLE_TO_CATEGORY.get(style.lower()) if style else None
    params: dict = {}
    if category:
        params["pub_category"] = category
    elif model_name:
        params["keywords"] = model_name
    else:
        return None

    facts = [
        f for f in (_listing_facts(li) for li in await query_all_listings(params)) if f
    ]
    if not facts:
        return None

    tokens = model_tokens(model_name)

    def narrow(prefix: tuple[str, ...], by_condition: bool, by_size: bool):
        rows = facts
        if prefix:
            # Token containment on NORMALIZED tokens, both sides. Matching raw
            # substrings of the lowercased title kept punctuation glued to the
            # tokens, so a hat named `Odysea Hydro "Have More Fun"` demanded
            # `"have` and `fun"` — strings that appear in no listing title ever
            # — and every such hat fell silently through to the category median.
            wanted = set(prefix)
            rows = [f for f in rows if wanted <= set(model_tokens(f[0]))]
        if by_condition and condition:
            rows = [f for f in rows if f[2] == condition]
        if by_size and size:
            rows = [f for f in rows if f[3] == size]
        return rows

    # Model specificity is surrendered ONE TOKEN AT A TIME, and entirely,
    # before condition or size are given up at all.
    #
    # melin titles read `<line> <construction> - <colorway>`, and `model_name`
    # comes from Claude reading a PHOTO — so the leading tokens are the product
    # line and the trailing ones are whatever artwork was visible. Dropping the
    # last token steps from "this exact design" to "this line", which is a real
    # comparable: same product, different colorway.
    #
    # There used to be no such step. It went straight from "every token matches"
    # to the median of the entire category, so `Odysea Rope Hydro (WATERCOLOR)`
    # — whose parenthesized token could never match anything — was priced at the
    # median of all 436 Odyseas, identically to 27 other hats. Measured over the
    # real collection, this ladder finds a genuine line-level comp for 13 of 14
    # hats that previously fell to the category.
    for by_condition, by_size in ((True, True), (True, False), (False, False)):
        for k in range(len(tokens), -1, -1):
            prefix = tuple(tokens[:k])
            rows = narrow(prefix, by_condition, by_size)
            if len(rows) < _MIN_MODEL_SAMPLE:
                continue

            # A prefix is only a MODEL match if it either matched the hat's
            # whole name, or actually narrowed the field. Token count cannot
            # decide this: for an `a_game` hat the prefix `a game` has two
            # tokens and still selects the entire aGame category, so calling it
            # a model comp would dress the broadest possible comparison up as
            # the narrowest. Asking whether it excluded anything is the same
            # question, answered from the data instead of from the name.
            everything = narrow((), by_condition, by_size)
            narrowed = len(rows) < len(everything)
            matched = (
                " ".join(prefix).title()
                if prefix and (len(prefix) == len(tokens) or narrowed)
                else None
            )
            return {
                "median": round(median([f[1] for f in rows]), 2),
                "count": len(rows),
                "sample": "model" if matched else "category",
                # The line actually compared against, so the label can name it
                # instead of saying "model" and leaving which model unstated.
                "matched": matched,
                "condition_matched": bool(by_condition and condition),
                "size_matched": bool(by_size and size),
            }
    return None
