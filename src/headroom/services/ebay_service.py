"""eBay Browse API — live comparable-listings prices.

Uses the Application access token flow (client_credentials, public scope).
The Browse API surfaces *currently listed* items, not sold prices — asking
prices skew higher than realized values, but they're real-time and free
(5,000 calls/day on the developer tier).

Marketplace Insights gives sold prices but requires partner approval —
out of scope for v0.4.
"""

from __future__ import annotations

import logging
import os
import statistics
import time
from datetime import datetime, timezone
from urllib.parse import quote

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.services import settings_service

logger = logging.getLogger(__name__)

EBAY_OAUTH = "https://api.ebay.com/identity/v1/oauth2/token"
EBAY_BROWSE = "https://api.ebay.com/buy/browse/v1/item_summary/search"
EBAY_BROWSE_HTML_BASE = "https://www.ebay.com/sch/i.html"

# Cache the application token in process memory; refresh shortly before expiry.
_token: str | None = None
_token_expires_at: float = 0.0


EBAY_APP_ID_KEY = "ebay_app_id"
EBAY_CERT_ID_KEY = "ebay_cert_id"
EBAY_MARKETPLACE_KEY = "ebay_marketplace"  # default EBAY_US


async def _get_creds(db: AsyncSession) -> tuple[str | None, str | None, str]:
    """Returns (app_id, cert_id, marketplace) — None when not configured."""
    app_id = await settings_service._get_setting(db, EBAY_APP_ID_KEY)  # noqa: SLF001
    cert_id = await settings_service._get_setting(db, EBAY_CERT_ID_KEY)  # noqa: SLF001
    marketplace = await settings_service._get_setting(db, EBAY_MARKETPLACE_KEY) or "EBAY_US"  # noqa: SLF001
    # Env fallbacks for ops users who'd rather inject via docker-compose
    app_id = app_id or os.environ.get("HEADROOM_EBAY_APP_ID")
    cert_id = cert_id or os.environ.get("HEADROOM_EBAY_CERT_ID")
    return app_id, cert_id, marketplace


async def _ensure_token(app_id: str, cert_id: str) -> str:
    global _token, _token_expires_at
    if _token and _token_expires_at - time.time() > 60:
        return _token
    auth = httpx.BasicAuth(app_id, cert_id)
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            EBAY_OAUTH,
            auth=auth,
            data={"grant_type": "client_credentials", "scope": "https://api.ebay.com/oauth/api_scope"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    if resp.status_code == 200:
        body = resp.json()
        _token = body["access_token"]
        _token_expires_at = time.time() + int(body.get("expires_in", 7200))
        return _token

    # Failure path — try to extract eBay's structured `error` + `error_description`
    # so the user sees what's actually wrong instead of a generic guess.
    raw = resp.text or ""
    err_code = ""
    err_desc = ""
    try:
        body = resp.json()
        err_code = str(body.get("error") or "")
        err_desc = str(body.get("error_description") or "")
    except Exception:  # noqa: BLE001
        pass

    logger.warning(
        "eBay OAuth failed: status=%s error=%r desc=%r raw=%s",
        resp.status_code, err_code, err_desc, raw[:300],
    )

    # Build the user-facing message. Lead with what eBay actually said, then
    # add a hint for the most common failure mode.
    parts = [f"eBay OAuth returned {resp.status_code}"]
    if err_code:
        parts.append(f"({err_code})")
    if err_desc:
        parts.append(f"— {err_desc}")
    elif not err_code:
        # No structured body, fall back to raw text
        parts.append(f"— {raw[:180] or 'no body'}")

    if resp.status_code == 401:
        parts.append(
            ". Most common cause: pasted Sandbox keys instead of Production. "
            "developer.ebay.com → My Account → Application Keysets → use the "
            "PRODUCTION column, not Sandbox. App ID + Cert ID must come from "
            "the same row."
        )

    raise EbayError(" ".join(parts))


async def verify_creds(db: AsyncSession) -> dict:
    """Probe the eBay credentials end-to-end. Returns a structured diagnostic.

    Tries: load creds → OAuth → cheap Browse search. Reports which stage
    failed so the UI can show something more useful than "502 Bad Gateway".
    """
    app_id, cert_id, marketplace = await _get_creds(db)
    if not app_id or not cert_id:
        return {"ok": False, "stage": "creds", "detail": "No App ID + Cert ID configured."}

    # Force a fresh token on every test so we don't accept a stale-cached one.
    global _token, _token_expires_at
    _token = None
    _token_expires_at = 0.0

    try:
        token = await _ensure_token(app_id, cert_id)
    except EbayError as exc:
        return {"ok": False, "stage": "oauth", "detail": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "stage": "oauth", "detail": f"Network/transport error: {exc}"}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                EBAY_BROWSE,
                params={"q": "melin hat", "limit": 1},
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-EBAY-C-MARKETPLACE-ID": marketplace,
                    "Accept": "application/json",
                },
            )
        if resp.status_code != 200:
            return {
                "ok": False, "stage": "browse",
                "detail": f"Browse API {resp.status_code}: {resp.text[:180]}",
            }
        body = resp.json()
        n = len(body.get("itemSummaries") or [])
        return {
            "ok": True, "stage": "ok",
            "detail": f"OAuth + Browse working. Sample query 'melin hat' returned {n} item(s).",
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "stage": "browse", "detail": f"Browse request failed: {exc}"}


class EbayError(Exception):
    pass


def _build_query(brand: str | None, model: str | None, style: str | None) -> str:
    """Build a search query from the available identifiers, falling back through hierarchy."""
    parts: list[str] = []
    if brand:
        parts.append(brand)
    if model:
        parts.append(model)
    elif style:
        parts.append(style.replace("_", " "))
    parts.append("hat")
    return " ".join(parts).strip()


def _browse_html_url(query: str) -> str:
    return f"{EBAY_BROWSE_HTML_BASE}?_nkw={quote(query)}"


async def find_comps(
    db: AsyncSession,
    *,
    brand: str | None,
    model: str | None,
    style: str | None,
    max_results: int = 25,
) -> dict:
    """Fetch comparable listings + summary stats. Returns a dict ready to
    persist on a Hat row.
    """
    query = _build_query(brand, model, style)
    if not query.strip() or query.strip() == "hat":
        return {
            "ebay_avg_price": None,
            "ebay_median_price": None,
            "ebay_listing_count": 0,
            "ebay_search_url": None,
            "ebay_checked_at": datetime.now(timezone.utc),
        }

    app_id, cert_id, marketplace = await _get_creds(db)
    search_url = _browse_html_url(query)

    if not app_id or not cert_id:
        # Credentials unset — return the deep link only, no live prices.
        return {
            "ebay_avg_price": None,
            "ebay_median_price": None,
            "ebay_listing_count": None,  # null = unknown, not zero
            "ebay_search_url": search_url,
            "ebay_checked_at": datetime.now(timezone.utc),
        }

    try:
        token = await _ensure_token(app_id, cert_id)
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.get(
                EBAY_BROWSE,
                params={"q": query, "limit": max_results},
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-EBAY-C-MARKETPLACE-ID": marketplace,
                    "Accept": "application/json",
                },
            )
        if resp.status_code == 401:
            # token might have just expired — invalidate + retry once
            global _token
            _token = None
            token = await _ensure_token(app_id, cert_id)
            async with httpx.AsyncClient(timeout=12.0) as client:
                resp = await client.get(
                    EBAY_BROWSE,
                    params={"q": query, "limit": max_results},
                    headers={
                        "Authorization": f"Bearer {token}",
                        "X-EBAY-C-MARKETPLACE-ID": marketplace,
                        "Accept": "application/json",
                    },
                )
        if resp.status_code != 200:
            raise EbayError(f"Browse API {resp.status_code}: {resp.text[:200]}")

        body = resp.json()
        items = body.get("itemSummaries") or []
        prices: list[float] = []
        for it in items:
            price = it.get("price") or {}
            try:
                v = float(price.get("value"))
            except (TypeError, ValueError):
                continue
            if v > 0:
                prices.append(v)

        return {
            "ebay_avg_price": round(statistics.fmean(prices), 2) if prices else None,
            "ebay_median_price": round(statistics.median(prices), 2) if prices else None,
            "ebay_listing_count": len(items),
            "ebay_search_url": search_url,
            "ebay_checked_at": datetime.now(timezone.utc),
        }
    except EbayError:
        raise
    except Exception as exc:  # noqa: BLE001 — surfaced to caller
        raise EbayError(f"eBay lookup failed: {exc}") from exc
