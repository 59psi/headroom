"""The paths this app takes when an outside service is unavailable.

Three integrations — eBay, Google Vision, melinrecap — plus the Claude call
itself, and every one is documented as degrading rather than failing. They
were also the least-covered modules after the import worker: 53%, 72%, 69%
and 57%, with the missing lines almost entirely inside `except` blocks.

That is the wrong thing to leave untested here. This deployment is a Pi on a
home connection talking to four third parties; the degradation paths are not
edge cases, they are Tuesday. And branch coverage is what exposes them — a
statement-only number counts them covered the moment the happy path runs once.

Nothing here touches the network. `conftest` already pops every credential out
of the environment, and each test stubs the transport it needs.
"""

from __future__ import annotations

import time

import httpx
import pytest

from headroom.services import ebay_service, google_vision, melin_recap

# Captured at IMPORT time, before conftest's autouse `no_live_melin_marketplace`
# fixture replaces the module attribute. That fixture is the house rule keeping
# the suite off the live Sharetribe API, and it works by stubbing exactly this
# function — so a test of the function ITSELF has to hold a reference from
# before the swap. The stubs below still apply: the real body reaches httpx and
# `_get_anon_token` through module globals, which each test patches.
_real_query_listings = melin_recap.query_listings

pytestmark = pytest.mark.anyio


class _Resp:
    """Enough of httpx.Response for these call sites."""

    def __init__(self, status=200, payload=None, text=""):
        self.status_code = status
        self._payload = payload if payload is not None else {}
        self.text = text or ""

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


def _client_returning(*responses, capture=None):
    """An httpx.AsyncClient stand-in yielding `responses` in order."""
    queue = list(responses)

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        async def post(self, url, **kw):
            if capture is not None:
                capture.append(("POST", url, kw))
            return queue.pop(0)

        async def get(self, url, **kw):
            if capture is not None:
                capture.append(("GET", url, kw))
            return queue.pop(0)

    return lambda **_kw: _Client()


# ---- eBay ------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _clear_ebay_token():
    """The token cache is a module global, so one test can poison the next."""
    ebay_service._token = None
    ebay_service._token_expires_at = 0.0
    yield
    ebay_service._token = None
    ebay_service._token_expires_at = 0.0


async def test_a_cached_ebay_token_is_reused(monkeypatch):
    """Re-authenticating per call would spend an API quota on nothing."""
    ebay_service._token = "cached-token"
    ebay_service._token_expires_at = time.time() + 3600

    def _explode(**_kw):
        raise AssertionError("re-authenticated despite a live cached token")

    monkeypatch.setattr(ebay_service.httpx, "AsyncClient", _explode)

    assert await ebay_service._ensure_token("id", "secret") == "cached-token"


async def test_a_token_about_to_expire_is_refreshed(monkeypatch):
    """The 60-second margin matters: a token that expires mid-request fails
    the request, and the retry costs more than refreshing early."""
    ebay_service._token = "stale"
    ebay_service._token_expires_at = time.time() + 30  # inside the margin

    monkeypatch.setattr(
        ebay_service.httpx, "AsyncClient",
        _client_returning(_Resp(200, {"access_token": "fresh", "expires_in": 7200})),
    )

    assert await ebay_service._ensure_token("id", "secret") == "fresh"


async def test_a_rejected_ebay_credential_reports_ebays_own_reason(monkeypatch):
    """"Invalid client" beats a generic failure — it tells you which of the
    two credentials to go and look at."""
    monkeypatch.setattr(
        ebay_service.httpx, "AsyncClient",
        _client_returning(_Resp(401, {
            "error": "invalid_client",
            "error_description": "client authentication failed",
        })),
    )

    with pytest.raises(ebay_service.EbayError) as excinfo:
        await ebay_service._ensure_token("bad", "creds")

    assert "invalid_client" in str(excinfo.value)


async def test_find_comps_returns_a_deep_link_when_credentials_are_unset(client):
    """The commonest state on a fresh install, and it must not be an error.

    You still get a link you can click; you just don't get live prices.
    """
    from tests.conftest import test_session_factory

    async with test_session_factory() as db:
        result = await ebay_service.find_comps(
            db, brand="Melin", model="A-Game Hydro", style="a_game"
        )

    assert result["ebay_search_url"], "no deep link offered"
    assert result["ebay_median_price"] is None
    assert result["ebay_checked_at"] is not None


async def test_find_comps_does_not_search_for_the_word_hat(client):
    """An unanalyzed hat has no brand and no model.

    Searching eBay for "hat" returns a price for the concept of hats, which
    would then be written onto the row as this hat's comparable value.
    """
    from tests.conftest import test_session_factory

    async with test_session_factory() as db:
        result = await ebay_service.find_comps(db, brand=None, model=None, style=None)

    assert result["ebay_listing_count"] == 0
    assert result["ebay_search_url"] is None


# ---- Google Vision ---------------------------------------------------- #


async def test_a_vision_http_error_becomes_the_services_own_error(monkeypatch, tmp_path):
    """Wrapped, not propagated raw.

    The pipeline catches `GoogleVisionError` specifically and carries on; a
    bare `httpx.ConnectError` would escape that handler and take the whole
    fallback analysis down — on the path whose entire job is to salvage
    something when the primary analyzer is already unavailable.
    """
    photo = tmp_path / "hat.png"
    photo.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)

    async def _boom(*_a, **_kw):
        raise httpx.ConnectError("no route to host")

    monkeypatch.setattr(google_vision, "_annotate", _boom)

    with pytest.raises(google_vision.GoogleVisionError):
        await google_vision.detect_brand_logo(photo, "key")


async def test_an_unreadable_photo_is_none_not_an_error(tmp_path):
    """A photo can genuinely vanish mid-run when a replacement upload deletes
    it, and this path must never be the thing that takes the run down."""
    assert await google_vision.detect_brand_logo(tmp_path / "gone.png", "key") is None


async def test_a_low_confidence_logo_is_discarded(monkeypatch, tmp_path):
    """Below the score floor a "logo" is usually a false hit on embroidery —
    and a wrong brand is worse than no brand, because it looks entered."""
    photo = tmp_path / "hat.png"
    photo.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)

    async def _weak(_payload, _key):
        return {"responses": [{"logoAnnotations": [
            {"description": "Melin", "score": google_vision._MIN_SCORE - 0.2},
        ]}]}

    monkeypatch.setattr(google_vision, "_annotate", _weak)

    assert await google_vision.detect_brand_logo(photo, "key") is None


async def test_a_confident_logo_is_returned(monkeypatch, tmp_path):
    photo = tmp_path / "hat.png"
    photo.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)

    async def _strong(_payload, _key):
        return {"responses": [{"logoAnnotations": [
            {"description": "Melin", "score": 0.95},
        ]}]}

    monkeypatch.setattr(google_vision, "_annotate", _strong)

    brand = await google_vision.detect_brand_logo(photo, "key")

    assert brand is not None
    assert brand[0] == "Melin"


# ---- melinrecap ------------------------------------------------------- #


async def test_a_melin_outage_raises_the_services_own_error(monkeypatch):
    """Callers catch `MelinRecapError` and degrade to a link.

    A raw httpx exception would escape that handling and fail the analysis.
    """
    async def _boom(*_a, **_kw):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(melin_recap, "_get_anon_token", _boom)

    with pytest.raises(melin_recap.MelinRecapError):
        await _real_query_listings({"pub_model": "A-Game"})


async def test_a_rotated_client_id_is_logged_at_error(monkeypatch, caplog):
    """The documented failure mode, and the reason this module got a logger.

    Treet rotating the anonymous client id presents as every hat quietly
    losing its resale price — which is invisible unless something says so.
    """
    caplog.set_level("ERROR")

    async def _token(_client, force=False):
        return "tok"

    monkeypatch.setattr(melin_recap, "_get_anon_token", _token)
    monkeypatch.setattr(
        melin_recap.httpx, "AsyncClient",
        _client_returning(_Resp(403, None, text="Forbidden"), _Resp(403, None, text="Forbidden")),
    )

    with pytest.raises(melin_recap.MelinRecapError):
        await _real_query_listings({"pub_model": "A-Game"})

    assert any("403" in r.getMessage() for r in caplog.records)


async def test_a_stale_token_is_retried_once(monkeypatch):
    """A cached token outliving its session is normal, not an outage.

    The 401 retry is what stops that presenting as a resale-price failure.
    """
    forced: list[bool] = []

    async def _token(_client, force=False):
        forced.append(force)
        return "tok"

    monkeypatch.setattr(melin_recap, "_get_anon_token", _token)
    monkeypatch.setattr(
        melin_recap.httpx, "AsyncClient",
        _client_returning(_Resp(401), _Resp(200, {"data": [{"id": "1"}]})),
    )

    listings = await _real_query_listings({"pub_model": "A-Game"})

    assert forced == [False, True], "the retry did not force a fresh token"
    assert listings == [{"id": "1"}]
