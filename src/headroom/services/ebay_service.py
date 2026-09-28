"""eBay Browse API — live comparable-listings prices.

Uses the Application access token flow (client_credentials, public scope).
The Browse API surfaces *currently listed* items, not sold prices — asking
prices skew higher than realized values, but they're real-time and free
(5,000 calls/day on the developer tier).

Marketplace Insights gives sold prices but requires partner approval —
out of scope for v0.4.
"""

from __future__ import annotations

import hashlib
import logging
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
#: WHICH credentials minted `_token`, as a fingerprint rather than a second
#: copy of the secret. The cache used to be keyed on nothing: replacing the
#: keyset in Settings kept searching with the token the OLD one minted for up
#: to its two-hour life, so a revoked or mistyped keyset went on "working"
#: while the Test button (which resets the cache) reported the truth.
_token_creds: str | None = None


EBAY_APP_ID_KEY = "ebay_app_id"
EBAY_CERT_ID_KEY = "ebay_cert_id"
EBAY_MARKETPLACE_KEY = "ebay_marketplace"  # default EBAY_US

# The keyset is an externally issued credential like the Anthropic and Vision
# keys, so it resolves the way they do — `settings_service.get_key`, database
# over `config.settings` — instead of a hand-rolled copy that read
# `os.environ` directly, bypassed the one module that owns the environment,
# and could not say where a value came from. Not mounted through the generic
# `/api/settings/<slug>` routes: eBay's two halves are set together, with a
# marketplace, by `routes/admin/ebay.py`. The slug is the one a generic mount
# would give them.
EBAY_APP_ID = settings_service.KeyProvider(
    name="ebay_app_id",
    slug="ebay-app-id",
    setting_key=EBAY_APP_ID_KEY,
    env_attr="ebay_app_id",
    label="eBay App ID",
)
EBAY_CERT_ID = settings_service.KeyProvider(
    name="ebay_cert_id",
    slug="ebay-cert-id",
    setting_key=EBAY_CERT_ID_KEY,
    env_attr="ebay_cert_id",
    label="eBay Cert ID",
)


async def get_creds(db: AsyncSession) -> tuple[str | None, str | None, str]:
    """Returns (app_id, cert_id, marketplace) — None when not configured.

    Database first, then `HEADROOM_EBAY_APP_ID` / `HEADROOM_EBAY_CERT_ID` for
    ops users who would rather inject them via docker-compose.
    """
    app_id, _app_source = await settings_service.get_key(db, EBAY_APP_ID)
    cert_id, _cert_source = await settings_service.get_key(db, EBAY_CERT_ID)
    marketplace = await settings_service.get_setting(db, EBAY_MARKETPLACE_KEY) or "EBAY_US"
    return app_id, cert_id, marketplace


def _fingerprint(app_id: str, cert_id: str) -> str:
    return hashlib.sha256(f"{app_id}\0{cert_id}".encode()).hexdigest()


def _json_object(resp: httpx.Response) -> dict | None:
    """The body as a JSON object, or None if it is not one (not JSON at all,
    or a JSON list/string). Callers decide what a missing object means."""
    try:
        body = resp.json()
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


async def _ensure_token(app_id: str, cert_id: str) -> str:
    """An application token for THESE credentials. Raises only `EbayError`.

    Every failure is typed — transport, a rejected keyset, and a 200 that
    carries no usable token (a proxy's HTML page, or JSON without the field),
    which used to escape as a raw KeyError or decode error. Callers catch
    `EbayError` and degrade; `verify_creds` reports it as the OAuth stage.
    """
    global _token, _token_expires_at, _token_creds
    creds = _fingerprint(app_id, cert_id)
    if _token and _token_creds == creds and _token_expires_at - time.time() > 60:
        return _token
    auth = httpx.BasicAuth(app_id, cert_id)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                EBAY_OAUTH,
                auth=auth,
                data={"grant_type": "client_credentials", "scope": "https://api.ebay.com/oauth/api_scope"},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
    except httpx.HTTPError as exc:
        raise EbayError(f"Network/transport error reaching eBay OAuth: {exc}") from exc
    if resp.status_code == 200:
        body = _json_object(resp) or {}
        token = body.get("access_token")
        if not isinstance(token, str) or not token:
            raise EbayError("eBay OAuth answered 200 without an access token")
        try:
            lifetime = int(body.get("expires_in", 7200))
        except (TypeError, ValueError):
            lifetime = 7200  # eBay's documented default for this grant
        _token, _token_expires_at, _token_creds = token, time.time() + lifetime, creds
        return _token

    # Failure path — try to extract eBay's structured `error` + `error_description`
    # so the user sees what's actually wrong instead of a generic guess.
    raw = resp.text or ""
    body = _json_object(resp) or {}
    err_code = str(body.get("error") or "")
    err_desc = str(body.get("error_description") or "")

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


async def _browse(
    token: str, query: str, marketplace: str, limit: int, timeout: float = 12.0
) -> httpx.Response:
    """One Browse API search. Shared by the comps lookup, its 401 retry, and the
    credential probe — all three send the identical request."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        return await client.get(
            EBAY_BROWSE,
            params={"q": query, "limit": limit},
            headers={
                "Authorization": f"Bearer {token}",
                "X-EBAY-C-MARKETPLACE-ID": marketplace,
                "Accept": "application/json",
            },
        )


async def verify_creds(db: AsyncSession) -> dict:
    """Probe the eBay credentials end-to-end. Returns a structured diagnostic.

    Tries: load creds → OAuth → cheap Browse search. Reports which stage
    failed so the UI can show something more useful than "502 Bad Gateway".
    """
    app_id, cert_id, marketplace = await get_creds(db)
    if not app_id or not cert_id:
        return {"ok": False, "stage": "creds", "detail": "No App ID + Cert ID configured."}

    # Force a fresh token on every test so we don't accept a stale-cached one.
    global _token, _token_expires_at, _token_creds
    _token = None
    _token_expires_at = 0.0
    _token_creds = None

    try:
        token = await _ensure_token(app_id, cert_id)
    except EbayError as exc:
        # Transport failures included: `_ensure_token` raises nothing else.
        return {"ok": False, "stage": "oauth", "detail": str(exc)}

    try:
        resp = await _browse(token, "melin hat", marketplace, limit=1, timeout=10.0)
    except (httpx.HTTPError, UnicodeError) as exc:
        # UnicodeError: a stored marketplace id no HTTP header can carry.
        return {"ok": False, "stage": "browse", "detail": f"Browse request failed: {exc}"}
    if resp.status_code != 200:
        return {
            "ok": False, "stage": "browse",
            "detail": f"Browse API {resp.status_code}: {resp.text[:180]}",
        }
    body = _json_object(resp)
    if body is None:
        return {
            "ok": False, "stage": "browse",
            "detail": "Browse API answered 200 with a body that is not a JSON object.",
        }
    items = body.get("itemSummaries")
    n = len(items) if isinstance(items, list) else 0
    return {
        "ok": True, "stage": "ok",
        "detail": f"OAuth + Browse working. Sample query 'melin hat' returned {n} item(s).",
    }


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

    app_id, cert_id, marketplace = await get_creds(db)
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
        resp = await _browse(token, query, marketplace, max_results)
        if resp.status_code == 401:
            # token might have just expired — invalidate + retry once
            global _token
            _token = None
            token = await _ensure_token(app_id, cert_id)
            resp = await _browse(token, query, marketplace, max_results)
        if resp.status_code != 200:
            raise EbayError(f"Browse API {resp.status_code}: {resp.text[:200]}")

        body = _json_object(resp)
        if body is None:
            raise EbayError("Browse API answered 200 with a body that is not a JSON object")
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
            # The Browse API publishes `total` beside a page capped at
            # `max_results` (25). `len(items)` was the page length, rendered on
            # the hat page as "median of N live listings" — the same
            # first-page-is-the-market shape `melin_recap.query_all_listings`
            # documents fixing. The median itself is still over the page the
            # API ranked first; the count at least no longer claims the page is
            # the market.
            "ebay_listing_count": int(body.get("total") or len(items)),
            "ebay_search_url": search_url,
            "ebay_checked_at": datetime.now(timezone.utc),
        }
    except EbayError:
        raise
    except Exception as exc:  # surfaced to caller
        raise EbayError(f"eBay lookup failed: {exc}") from exc
