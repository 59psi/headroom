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
    ebay_service._token_creds = None
    yield
    ebay_service._token = None
    ebay_service._token_expires_at = 0.0
    ebay_service._token_creds = None


async def test_a_cached_ebay_token_is_reused(monkeypatch):
    """Re-authenticating per call would spend an API quota on nothing."""
    ebay_service._token = "cached-token"
    ebay_service._token_expires_at = time.time() + 3600
    ebay_service._token_creds = ebay_service._fingerprint("id", "secret")

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


class _NotJson:
    """A 200 whose body is a proxy's or captive portal's HTML page."""

    status_code = 200
    text = "<html><body>Sign in to the Wi-Fi</body></html>"

    def json(self):
        raise ValueError("Expecting value: line 1 column 1 (char 0)")


@pytest.mark.parametrize(
    "resp",
    [_NotJson(), _Resp(200, ["a", "list"]), _Resp(200, {"data": "not a list"})],
    ids=["html-200", "json-list", "data-not-list"],
)
async def test_a_malformed_marketplace_reply_is_the_services_own_error(monkeypatch, resp):
    """Callers catch `MelinRecapError` and degrade to a link. A 200 that was
    not `{"data": [...]}` used to escape as a raw decode or attribute error —
    and after a successful (paid) Claude analysis that threw the analysis
    away, or in a bulk import deleted the hat."""
    async def _token(_client, force=False):
        return "tok"

    monkeypatch.setattr(melin_recap, "_get_anon_token", _token)
    monkeypatch.setattr(melin_recap.httpx, "AsyncClient", _client_returning(resp))

    with pytest.raises(melin_recap.MelinRecapError):
        await _real_query_listings({"pub_category": "aGame"})


async def test_a_reply_without_data_is_an_empty_market_not_an_error(monkeypatch):
    async def _token(_client, force=False):
        return "tok"

    monkeypatch.setattr(melin_recap, "_get_anon_token", _token)
    monkeypatch.setattr(melin_recap.httpx, "AsyncClient", _client_returning(_Resp(200, {"meta": {}})))

    assert await _real_query_listings({"pub_category": "aGame"}) == []


@pytest.mark.parametrize(
    "resp",
    [_NotJson(), _Resp(200, ["tok"]), _Resp(200, {"access_token": 5}), _Resp(200, {})],
    ids=["html-200", "json-list", "token-not-string", "no-token"],
)
async def test_a_malformed_token_reply_is_the_services_own_error(monkeypatch, resp):
    """Same seam, one step earlier — and a bad reply must not poison the
    module-wide token cache for the next call."""
    monkeypatch.setattr(melin_recap, "_token", None)
    client = _client_returning(resp)()

    with pytest.raises(melin_recap.MelinRecapError):
        await melin_recap._get_anon_token(client, force=True)
    assert melin_recap._token is None


# ---- eBay: every failure is EbayError, and the token belongs to its keyset -- #


async def test_a_token_minted_for_other_credentials_is_not_reused(monkeypatch):
    """Replacing the keyset in Settings kept searching with the token the OLD
    keyset minted, for up to its two-hour life — so revoked or mistyped keys
    went on "working". Measured: the only request made was a Browse search
    with the old app's bearer token."""
    ebay_service._token = "TOKEN-FOR-OLD-APP"
    ebay_service._token_expires_at = time.time() + 3600
    ebay_service._token_creds = ebay_service._fingerprint("old-app", "old-cert")

    async def _creds(_db):
        return "new-app", "new-cert", "EBAY_US"

    seen: list = []
    monkeypatch.setattr(ebay_service, "get_creds", _creds)
    monkeypatch.setattr(ebay_service.httpx, "AsyncClient", _client_returning(
        _Resp(200, {"access_token": "TOKEN-FOR-NEW-APP", "expires_in": 7200}),
        _Resp(200, {"itemSummaries": [{"price": {"value": "50"}}], "total": 1}),
        capture=seen,
    ))

    await ebay_service.find_comps(None, brand="Melin", model="A-Game", style="a_game")

    assert [method for method, _url, _kw in seen] == ["POST", "GET"]
    assert seen[0][1] == ebay_service.EBAY_OAUTH
    assert seen[1][2]["headers"]["Authorization"] == "Bearer TOKEN-FOR-NEW-APP"


async def test_the_credential_test_never_trusts_a_cached_token(monkeypatch):
    """Test re-authenticates even with a live cached token for the same keys,
    or a revoked keyset would pass on the strength of an old token."""
    ebay_service._token = "cached"
    ebay_service._token_expires_at = time.time() + 3600
    ebay_service._token_creds = ebay_service._fingerprint("app", "cert")

    async def _creds(_db):
        return "app", "cert", "EBAY_US"

    seen: list = []
    monkeypatch.setattr(ebay_service, "get_creds", _creds)
    monkeypatch.setattr(ebay_service.httpx, "AsyncClient", _client_returning(
        _Resp(200, {"access_token": "fresh", "expires_in": 7200}),
        _Resp(200, {"itemSummaries": [{}]}),
        capture=seen,
    ))

    result = await ebay_service.verify_creds(None)

    assert result["ok"] is True, result
    assert seen[0][:2] == ("POST", ebay_service.EBAY_OAUTH), "Test reused the cached token"
    assert seen[1][2]["headers"]["Authorization"] == "Bearer fresh"


async def test_a_rejected_token_is_refreshed_once_and_the_search_retried(monkeypatch):
    """A cached token can be revoked before its stated expiry. The 401 retry
    is what keeps that from presenting as "eBay is down"."""
    ebay_service._token = "revoked"
    ebay_service._token_expires_at = time.time() + 3600
    ebay_service._token_creds = ebay_service._fingerprint("app", "cert")

    async def _creds(_db):
        return "app", "cert", "EBAY_US"

    seen: list = []
    monkeypatch.setattr(ebay_service, "get_creds", _creds)
    monkeypatch.setattr(ebay_service.httpx, "AsyncClient", _client_returning(
        _Resp(401, {}, text="Unauthorized"),
        _Resp(200, {"access_token": "fresh", "expires_in": 7200}),
        _Resp(200, {"itemSummaries": [{"price": {"value": "40"}}, {"price": {"value": "60"}}]}),
        capture=seen,
    ))

    result = await ebay_service.find_comps(None, brand="Melin", model="A-Game", style="a_game")

    assert result["ebay_median_price"] == 50.0
    assert [(m, kw.get("headers", {}).get("Authorization")) for m, _u, kw in seen] == [
        ("GET", "Bearer revoked"), ("POST", None), ("GET", "Bearer fresh"),
    ]


class _Boom:
    """A client whose request fails in transport."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return False

    async def post(self, *_a, **_kw):
        raise httpx.ConnectError("no route to host")

    get = post


@pytest.mark.parametrize(
    "client_factory",
    [
        lambda: _Boom(),
        _client_returning(_NotJson()),
        _client_returning(_Resp(200, ["a", "list"])),
        _client_returning(_Resp(200, {"expires_in": 7200})),
    ],
    ids=["transport", "html-200", "json-list", "no-access-token"],
)
async def test_every_oauth_failure_is_an_ebay_error(monkeypatch, client_factory):
    """A 200 with no usable token raised a raw KeyError or decode error, and a
    transport failure a raw httpx error — `verify_creds` papered over both
    with a blind except. `_ensure_token` now raises only `EbayError`."""
    monkeypatch.setattr(ebay_service.httpx, "AsyncClient", lambda **_kw: client_factory())

    with pytest.raises(ebay_service.EbayError):
        await ebay_service._ensure_token("app", "cert")
    assert ebay_service._token is None, "a failed mint must not be cached"


async def test_the_credential_test_names_a_transport_failure_at_the_oauth_stage(monkeypatch):
    async def _creds(_db):
        return "app", "cert", "EBAY_US"

    monkeypatch.setattr(ebay_service, "get_creds", _creds)
    monkeypatch.setattr(ebay_service.httpx, "AsyncClient", lambda **_kw: _Boom())

    result = await ebay_service.verify_creds(None)

    assert result["ok"] is False
    assert result["stage"] == "oauth"
    assert "Network/transport" in result["detail"]


async def test_the_credential_test_reports_a_non_json_browse_reply(monkeypatch):
    async def _creds(_db):
        return "app", "cert", "EBAY_US"

    monkeypatch.setattr(ebay_service, "get_creds", _creds)
    monkeypatch.setattr(ebay_service.httpx, "AsyncClient", _client_returning(
        _Resp(200, {"access_token": "t", "expires_in": 7200}), _NotJson(),
    ))

    result = await ebay_service.verify_creds(None)

    assert result == {
        "ok": False, "stage": "browse",
        "detail": "Browse API answered 200 with a body that is not a JSON object.",
    }


async def test_ebay_credentials_resolve_through_config_not_the_raw_environment(
    db_session, monkeypatch
):
    """The keyset is resolved like the other two externally issued keys —
    database over `config.settings` — rather than by a private
    `os.environ.get`, which bypassed the one module that owns the environment
    (and reads it once, at import)."""
    from types import SimpleNamespace

    from headroom.services import settings_service

    monkeypatch.setenv("HEADROOM_EBAY_APP_ID", "raw-env-app")
    monkeypatch.setenv("HEADROOM_EBAY_CERT_ID", "raw-env-cert")
    monkeypatch.setattr(
        settings_service, "config_settings",
        SimpleNamespace(ebay_app_id="cfg-app", ebay_cert_id="cfg-cert"),
    )

    assert await ebay_service.get_creds(db_session) == ("cfg-app", "cfg-cert", "EBAY_US")

    await settings_service.set_setting(db_session, ebay_service.EBAY_APP_ID_KEY, "db-app")
    app_id, cert_id, _market = await ebay_service.get_creds(db_session)
    assert (app_id, cert_id) == ("db-app", "cfg-cert"), "the database wins, per key"


async def test_an_env_ebay_keyset_reaches_the_real_settings(db_session, monkeypatch):
    """The test above stands a namespace in for `Settings`, so it cannot see
    whether `Settings` HAS the two fields `get_key` reads. It did not: the
    environment keyset resolved to None on every install that set it."""
    from headroom import config
    from headroom.services import settings_service

    monkeypatch.setenv("HEADROOM_EBAY_APP_ID", "env-app")
    monkeypatch.setenv("HEADROOM_EBAY_CERT_ID", "env-cert")
    monkeypatch.setattr(settings_service, "config_settings", config.Settings())

    assert await ebay_service.get_creds(db_session) == ("env-app", "env-cert", "EBAY_US")
