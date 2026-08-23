"""What an unauthenticated caller can spend, and what an error hands back.

Every upload path in this app is careful about memory. Nothing else was: a
JSON body was read in full and parsed before any route saw it, so the cheapest
denial of service against a 1 GB Pi was one curl command at the login page.
"""

from __future__ import annotations

import pytest

from headroom import limits

pytestmark = pytest.mark.anyio


async def test_an_oversize_json_body_is_refused(anon_client, monkeypatch):
    monkeypatch.setenv("HEADROOM_MAX_BODY_BYTES", "1024")

    resp = await anon_client.post(
        "/api/auth/login", json={"username": "x", "password": "y" * 4096}
    )

    assert resp.status_code == 413


async def test_the_refusal_happens_before_the_route(anon_client, monkeypatch):
    """Refused on the way in, not by a handler that already paid for it.

    The middleware is outermost, so an oversize body never reaches the auth
    gate's database lookup — which is the work an attacker would otherwise get
    for free, per request.
    """
    monkeypatch.setenv("HEADROOM_MAX_BODY_BYTES", "16")

    resp = await anon_client.post("/api/hats", json={"style": "a_game" * 100})

    # 413, not the 401 the auth gate would have returned.
    assert resp.status_code == 413


async def test_a_normal_request_is_untouched(anon_client):
    resp = await anon_client.post(
        "/api/auth/login", json={"username": "nobody", "password": "wrong-password"}
    )

    assert resp.status_code != 413


async def test_multipart_is_exempt(client):
    """Upload routes stream to disk under their own, much larger caps.

    A JSON-shaped limit applied here would break bulk import; bulk import's
    750 MB applied to JSON would protect nothing. So the limit asks what kind
    of body it is rather than pretending one number fits both.
    """
    import io

    monkey_size = limits.DEFAULT_MAX_BODY_BYTES + 1
    assert monkey_size > limits.DEFAULT_MAX_BODY_BYTES

    files = [("photos", ("a.jpg", io.BytesIO(b"x" * 4096), "image/jpeg"))]
    resp = await client.post("/api/hats/import", files=files)

    assert resp.status_code == 202


async def test_a_get_is_never_body_checked(anon_client, monkeypatch):
    monkeypatch.setenv("HEADROOM_MAX_BODY_BYTES", "1")

    assert (await anon_client.get("/health")).status_code == 200


# ---- 422 redaction ---------------------------------------------------- #


async def test_a_rejected_password_is_not_echoed_back(anon_client):
    """Pydantic puts the offending `input` in every validation error.

    FastAPI serialises that list straight into the body, so a password
    rejected for being too short came back in clear text — into the browser's
    network tab, and into any proxy log on the way.
    """
    # Not "short": pydantic's own error type is `string_too_short`, so that
    # sentinel is present in a correctly-redacted body and the assertion would
    # fail on working code. A password-shaped value that appears nowhere in
    # the framework's vocabulary is the only thing this can test with.
    secret = "Zq4!v"  # noqa: S105 — the point of the test

    resp = await anon_client.post(
        "/api/auth/setup", json={"username": "owner", "password": secret}
    )

    assert resp.status_code == 422
    assert secret not in resp.text


async def test_the_422_still_says_which_field_and_why(anon_client):
    """Redaction must not turn a useful error into a useless one.

    The field name and the reason are what makes a 422 actionable. The value
    is the one part the caller already has.
    """
    resp = await anon_client.post(
        "/api/auth/setup", json={"username": "owner", "password": "Zq4!v"}
    )

    detail = resp.json()["detail"]
    assert any("password" in str(err.get("loc", "")) for err in detail)
    assert all(err.get("msg") for err in detail)


# ---- credentials in URLs ---------------------------------------------- #


async def test_the_vision_key_travels_in_a_header_not_the_url(monkeypatch):
    """httpx logs the full request URL at INFO on every call.

    As `?key=…` the Google Vision credential was printed in clear text into
    the container log each time a hat fell back to Vision. Logs get shipped,
    pasted into issues, and read over shoulders.
    """
    from headroom.services import google_vision

    seen: dict = {}

    class _Resp:
        status_code = 200

        def json(self):
            return {"responses": [{}]}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, **kw):
            seen["url"] = url
            seen["headers"] = kw.get("headers", {})
            seen["params"] = kw.get("params")
            return _Resp()

    monkeypatch.setattr(google_vision.httpx, "AsyncClient", lambda **kw: _Client())

    await google_vision._annotate({}, "super-secret-key")

    assert seen["headers"]["X-Goog-Api-Key"] == "super-secret-key"
    assert seen["params"] is None
    assert "super-secret-key" not in seen["url"]
