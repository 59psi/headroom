"""Build deep links into melinrecap.com for resale-price browsing.

melinrecap.com is a Sharetribe-style marketplace where listings are rendered
client-side; static HTML scraping doesn't return prices. Instead of attempting
brittle headless-browser scraping (heavy on a Pi), we generate honest deep
links to the brand+style filter page so the user can see live comparable
listings. The hat record stores the URL + source label; price stays null
unless the user fills it in manually.
"""

from __future__ import annotations

from urllib.parse import urlencode

MELIN_BASE = "https://www.melinrecap.com"

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

    Only emits a pointer when the brand looks like Melin. We deliberately
    leave `resale_price` null — the UI presents the link as a 'browse'
    affordance rather than asserting a fabricated number.
    """
    if not is_melin(brand):
        return None
    return {
        "resale_price": None,
        "resale_price_source": "Melin Recap",
        "resale_price_url": melin_recap_link(style),
    }
