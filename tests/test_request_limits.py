"""What an unauthenticated caller can spend, and what an error hands back.

Every upload path in this app is careful about memory. Nothing else was: a
JSON body was read in full and parsed before any route saw it, so the cheapest
denial of service against a 1 GB Pi was one curl command at the login page.
"""

from __future__ import annotations

import pytest

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
    # 1 KiB is the floor below which no body of any kind could arrive (the
    # login is ~60 bytes) — so the cap is the floor and the body clears it.
    monkeypatch.setenv("HEADROOM_MAX_BODY_BYTES", "1024")

    resp = await anon_client.post("/api/hats", json={"style": "a_game" * 300})

    # 413, not the 401 the auth gate would have returned.
    assert resp.status_code == 413


async def test_a_normal_request_is_untouched(anon_client):
    resp = await anon_client.post(
        "/api/auth/login", json={"username": "nobody", "password": "wrong-password"}
    )

    assert resp.status_code != 413


async def test_an_upload_route_takes_multipart_above_the_json_cap(client, monkeypatch):
    """Upload routes stream to disk under their own, much larger caps.

    A JSON-shaped limit applied here would break bulk import; bulk import's
    750 MB applied to JSON would protect nothing. So the limit asks which
    ENDPOINT is reading the body rather than pretending one number fits both.
    """
    import io

    # The body must actually EXCEED the limit, or the exemption is not what
    # let it through. This test used to assert `x + 1 > x` and then post 4 KB
    # against an unpatched 2 MB cap — deleting the multipart branch from
    # `limits.py` broke bulk import in production and left this green.
    monkeypatch.setenv("HEADROOM_MAX_BODY_BYTES", "1024")
    payload = b"x" * 8192
    assert len(payload) > 1024

    files = [("photos", ("a.jpg", io.BytesIO(payload), "image/jpeg"))]
    resp = await client.post("/api/hats/import", files=files)

    assert resp.status_code == 202, (
        "a multipart upload was body-capped — upload routes carry their own, "
        "much larger caps and stream to disk"
    )


async def test_a_multipart_body_to_a_json_route_is_capped_like_json(anon_client, monkeypatch):
    """The exemption keys on the ENDPOINT, never on the client's Content-Type.

    It used to key on the request header: anything labeled
    `multipart/form-data` skipped the cap entirely, whatever route it was
    aimed at. A JSON route (`/api/auth/login`, open by necessity) reads its
    body in full before the parse fails, so an anonymous 900 MB POST with a
    multipart label was buffered whole into a 1 GB container — the exact
    one-curl-command denial of service this middleware's docstring says it
    prevents, through the door it left open. Measured live: a 50 MB
    JSON-typed body was cut at 786 KB; the same bytes with a multipart label
    were accepted in full.
    """
    monkeypatch.setenv("HEADROOM_MAX_BODY_BYTES", "1024")
    body = b"--x\r\n" + b"y" * 8192 + b"\r\n--x--\r\n"

    resp = await anon_client.post(
        "/api/auth/login",
        content=body,
        headers={"content-type": "multipart/form-data; boundary=x"},
    )

    assert resp.status_code == 413


async def test_a_multipart_body_to_an_upload_route_still_has_a_ceiling(client, monkeypatch):
    """Even a real upload route is bounded — at the batch cap, not at nothing.

    Starlette parses the whole multipart stream before the handler runs, so
    without a ceiling a client could stream any number of bytes at the SD
    card the spool lives on; the route's own per-file and per-batch caps only
    apply to what it reads back afterwards.
    """
    import io

    from headroom import limits

    monkeypatch.setattr(limits, "MULTIPART_MAX_BODY_BYTES", 4096)
    payload = b"x" * 8192

    files = [("photos", ("a.jpg", io.BytesIO(payload), "image/jpeg"))]
    resp = await client.post("/api/hats/import", files=files)

    assert resp.status_code == 413


async def test_the_upload_endpoints_are_derived_from_their_signatures():
    """Which endpoints get the large ceiling is read off `UploadFile` hints.

    A roster of paths would rot the day a fifth upload route landed; the
    predicate cannot. Pinned against the four that exist so a route that
    starts or stops taking files changes this list on purpose.
    """
    from headroom import limits
    from headroom.routes import hats, import_jobs, settings, share

    assert limits.endpoint_streams_files(hats.upload_hat_photo)
    assert limits.endpoint_streams_files(import_jobs.create_import_job)
    assert limits.endpoint_streams_files(settings.upload_logo)
    assert limits.endpoint_streams_files(share.share_target)
    assert not limits.endpoint_streams_files(hats.list_hats)
    assert not limits.endpoint_streams_files(None)


async def test_a_get_is_never_body_checked(anon_client, monkeypatch):
    monkeypatch.setenv("HEADROOM_MAX_BODY_BYTES", "1")

    assert (await anon_client.get("/health")).status_code == 200


# ---- 422 redaction ---------------------------------------------------- #


async def test_a_rejected_password_is_not_echoed_back(anon_client):
    """Pydantic puts the offending `input` in every validation error.

    FastAPI serializes that list straight into the body, so a password
    rejected for being too short came back in clear text — into the browser's
    network tab, and into any proxy log on the way.
    """
    # Not "short": pydantic's own error type is `string_too_short`, so that
    # sentinel is present in a correctly-redacted body and the assertion would
    # fail on working code. A password-shaped value that appears nowhere in
    # the framework's vocabulary is the only thing this can test with.
    secret = "Zq4!v"  # the point of the test

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


async def test_a_chunked_oversize_body_gets_a_413_not_a_500(
    anon_client, db_session, monkeypatch
):
    """A chunked request declares no Content-Length, so the byte count is the
    only limit that applies — and it must end the same way the declared path
    does.

    It used to return an ASGI disconnect, which Starlette turns into
    `ClientDisconnect` inside the route. Nothing catches that, so it reached
    the unhandled-exception handler: a 500 to the caller AND a durable
    `error.unhandled` row. On `/api/auth/login`, which is open, that made an
    oversize chunked body an unauthenticated way to write an audit row per
    request — the same disk-filling shape as the rate-limit branch.
    """
    from sqlalchemy import func, select

    from headroom.models.activity_log import ActivityLog

    monkeypatch.setenv("HEADROOM_MAX_BODY_BYTES", "1024")

    async def chunks():
        for _ in range(8):
            yield b"x" * 512

    async def unhandled_rows() -> int:
        db_session.expire_all()
        return (await db_session.execute(
            select(func.count(ActivityLog.id)).where(
                ActivityLog.kind == "error.unhandled"
            )
        )).scalar_one()

    before = await unhandled_rows()
    resp = await anon_client.post(
        "/api/auth/login",
        content=chunks(),
        headers={"content-type": "application/json"},
    )

    assert resp.status_code == 413, (
        f"chunked oversize body returned {resp.status_code}, not a 413"
    )
    assert await unhandled_rows() == before, (
        "an oversize body wrote an unhandled-error audit row"
    )
