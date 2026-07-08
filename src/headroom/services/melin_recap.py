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
_STYLE_TO_CATEGORY: dict[str, str] = {
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
    category = _STYLE_TO_CATEGORY.get(style.lower())
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


async def _query_listings(params: dict) -> list[dict]:
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
        raise MelinRecapError(f"Melin Recap lookup failed: {exc}") from exc
    if resp.status_code != 200:
        raise MelinRecapError(f"Melin Recap query {resp.status_code}: {resp.text[:200]}")
    return resp.json().get("data", [])


async def fetch_resale_stats(
    style: str | None, model_name: str | None = None
) -> dict | None:
    """Live asking-price stats for comparable listings, or None.

    Queries the hat's style category (up to 100 listings), then narrows to
    listings whose title contains every token of `model_name` when that
    leaves a meaningful sample. Returns
    {"median": float$, "count": int, "sample": "model" | "category"}.
    """
    category = _STYLE_TO_CATEGORY.get(style.lower()) if style else None
    params: dict = {"per_page": 100, "fields.listing": "title,price"}
    if category:
        params["pub_category"] = category
    elif model_name:
        params["keywords"] = model_name
    else:
        return None

    listings = await _query_listings(params)
    priced = [
        (
            (li.get("attributes") or {}).get("title", ""),
            ((li.get("attributes") or {}).get("price") or {}).get("amount"),
        )
        for li in listings
    ]
    priced = [(title, amount) for title, amount in priced if amount]
    if not priced:
        return None

    sample = "category"
    if model_name:
        tokens = [t for t in model_name.lower().split() if t]
        matched = [
            (title, amount)
            for title, amount in priced
            if all(t in title.lower() for t in tokens)
        ]
        if len(matched) >= _MIN_MODEL_SAMPLE:
            priced = matched
            sample = "model"

    amounts = [amount / 100 for _title, amount in priced]
    return {"median": round(median(amounts), 2), "count": len(amounts), "sample": sample}
