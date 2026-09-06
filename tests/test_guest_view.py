"""Guest view: browsing the collection without an account.

This is the only feature in the app that serves collection data to somebody
who has not logged in and holds no secret token, so the tests are mostly about
what it *refuses* to do.

Three properties, all deliberate:

* **Off by default** — unauthenticated read access to the whole collection is
  not something anyone should acquire by upgrading.
* **404, not 403, when off** — a 403 confirms the feature exists and is merely
  switched off, which is a fact about a private install a stranger has no
  reason to learn.
* **The share-link projection** — no prices, purchase history, disposition,
  wear counts, analysis state or owner notes.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.anyio


async def _enable(client, enabled=True):
    resp = await client.put("/api/settings/guest-view", json={"enabled": enabled})
    assert resp.status_code == 200
    return resp.json()


async def _hat(client, **fields):
    resp = await client.post(
        "/api/hats",
        json={"condition": "new", "size": "classic", "style": "a_game", **fields},
    )
    assert resp.status_code == 201
    return resp.json()


# ------------------------------- the switch -------------------------------- #


async def test_guest_view_is_off_by_default(client, anon_client):
    assert (await client.get("/api/settings/guest-view")).json()["enabled"] is False
    assert (await anon_client.get("/api/public/guest/collection")).status_code == 404


async def test_disabled_looks_like_an_unrouted_path(client, anon_client):
    """404, never 403. A 403 says "this exists and is switched off", which is a
    fact about a private install nobody outside it needs."""
    await _enable(client, False)

    for path in ("/api/public/guest/collection", "/api/public/guest/photo/1"):
        resp = await anon_client.get(path)
        assert resp.status_code == 404, f"{path} advertised itself"
        assert "guest" not in resp.text.lower()


async def test_turning_it_on_lets_a_stranger_browse(client, anon_client):
    await _hat(client, model_name="Coronado")
    await _enable(client)

    resp = await anon_client.get("/api/public/guest/collection")

    assert resp.status_code == 200
    assert [h["model_name"] for h in resp.json()["hats"]] == ["Coronado"]


async def test_turning_it_back_off_closes_the_door(client, anon_client):
    await _hat(client)
    await _enable(client)
    assert (await anon_client.get("/api/public/guest/collection")).status_code == 200

    await _enable(client, False)

    assert (await anon_client.get("/api/public/guest/collection")).status_code == 404


async def test_the_login_screen_is_told_whether_to_offer_it(client, anon_client):
    """The login page already makes this one unauthenticated call, so the flag
    rides along rather than costing a second round-trip before anything
    renders."""
    # Absent when off — a `false` would disclose that this install has a guest
    # mode at all, which is what the guest routes' 404 keeps private.
    assert "guest_view_enabled" not in (await anon_client.get("/api/auth/status")).json()

    await _enable(client)

    assert (await anon_client.get("/api/auth/status")).json()["guest_view_enabled"] is True


# ---------------------------- what leaks, and what doesn't ------------------ #


async def test_no_prices_reach_a_guest(client, anon_client):
    """The whole point of the projection. Returning the full model and trusting
    the frontend not to render the rest is exactly how this leaks."""
    await _hat(
        client,
        model_name="Coronado",
        purchase_price=89.0,
        artist_series="Skye Walker",
    )
    await _enable(client)

    body = (await anon_client.get("/api/public/guest/collection")).text

    for leak in ("purchase_price", "estimated_new_price", "resale_price", "89"):
        assert leak not in body, f"{leak!r} reached an unauthenticated caller"


async def test_owner_only_fields_are_absent_from_the_projection(client, anon_client):
    await _hat(client, model_name="Coronado", owner_notes="bought for the wedding")
    await _enable(client)

    body = (await anon_client.get("/api/public/guest/collection")).text

    for leak in ("owner_notes", "wedding", "analysis_status", "wear_count"):
        assert leak not in body


async def test_a_disposed_hat_is_not_on_show(client, anon_client):
    """A share link shows what is on the shelf, and what a hat sold for is
    nobody else's business. Guests get the same rule."""
    hat = await _hat(client, model_name="Departed")
    await client.post(
        f"/api/hats/{hat['id']}/dispose", json={"via": "sold", "price": 120}
    )
    await _enable(client)

    body = (await anon_client.get("/api/public/guest/collection")).json()

    assert body["hats"] == []


# --------------------------------- searching -------------------------------- #


async def test_a_guest_can_search(client, anon_client):
    await _hat(client, model_name="Coronado")
    await _hat(client, model_name="Odysea")
    await _enable(client)

    hits = (await anon_client.get("/api/public/guest/collection?q=Coronado")).json()

    assert [h["model_name"] for h in hits["hats"]] == ["Coronado"]
    assert hits["hat_count"] == 1


async def test_guest_search_uses_the_real_search(client, anon_client):
    """Delegated rather than reimplemented, but over the PROJECTED fields only.

    This test used to prove delegation by searching `construction=HYDROLite` —
    which was the leak: construction is not in `SharedHat`, so a hit confirmed
    a value the projection withholds. Room name is the right demonstration: it
    IS shown to guests, and matching a hat through its case's room is real
    search machinery no guest-only copy would reproduce by accident.
    """
    room = (await client.post("/api/rooms", json={"name": "Attic"})).json()
    case = (await client.post(
        "/api/cases", json={"case_type": "archive", "room_id": room["id"]}
    )).json()
    await _hat(client, model_name="Coronado", case_id=case["id"])
    await _enable(client)

    hits = (await anon_client.get("/api/public/guest/collection?q=Attic")).json()

    assert [h["model_name"] for h in hits["hats"]] == ["Coronado"]


async def test_search_still_hides_disposed_hats(client, anon_client):
    hat = await _hat(client, model_name="Departed")
    await client.post(f"/api/hats/{hat['id']}/dispose", json={"via": "sold"})
    await _enable(client)

    hits = (await anon_client.get("/api/public/guest/collection?q=Departed")).json()

    assert hits["hats"] == []


# ---------------------------------- photos ---------------------------------- #


async def test_a_photoless_hat_offers_no_photo_url(client, anon_client):
    await _hat(client, model_name="Coronado")
    await _enable(client)

    hat = (await anon_client.get("/api/public/guest/collection")).json()["hats"][0]

    assert hat["photo_url"] is None


async def test_an_unknown_photo_is_404(client, anon_client):
    await _enable(client)
    assert (await anon_client.get("/api/public/guest/photo/9999")).status_code == 404


async def test_a_disposed_hats_photo_is_not_served(client, anon_client):
    """The id arrives straight from the URL, so the route re-checks rather than
    trusting that the caller came from the collection listing."""
    hat = await _hat(client, model_name="Departed")
    await client.post(f"/api/hats/{hat['id']}/dispose", json={"via": "sold"})
    await _enable(client)

    resp = await anon_client.get(f"/api/public/guest/photo/{hat['id']}")

    assert resp.status_code == 404


# ------------------------------- read-only ---------------------------------- #


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
async def test_the_guest_surface_is_read_only(client, anon_client, method):
    """A guest reads. There is no route here that writes, and this fails if one
    is ever added."""
    await _enable(client)

    resp = await getattr(anon_client, method)("/api/public/guest/collection")

    assert resp.status_code in (404, 405), f"{method.upper()} was routed"


# --------------------- search must not become an oracle --------------------- #


@pytest.mark.parametrize(
    "field,value,term",
    [
        ("condition", "worn", "worn"),
        ("size", "x_large", "x_large"),
        ("artist_series", "Skye Walker", "Skye"),
        ("construction", "HYDROLite", "HYDROLite"),
        # Derived from construction — closing the front door and leaving this
        # window open would leak the same fact.
        ("construction", "HYDRO", "hydro"),
    ],
)
async def test_guest_search_cannot_probe_for_hidden_fields(
    client, anon_client, field, value, term
):
    """Matching on a field the caller cannot see turns search into an oracle.

    `SharedHat` withholds condition, size, collection and construction. If the
    query still matched them, a guest could read every hat's condition by
    trying `?q=worn` and seeing which came back — the projection would be
    withholding the value while search confirmed it.
    """
    base = {"condition": "new", "size": "classic", "style": "a_game"}
    marked = await _hat(client, model_name="Marked", **{**base, field: value})
    await _hat(client, model_name="Plain", **base)
    await _enable(client)

    hits = (await anon_client.get(
        f"/api/public/guest/collection?q={term}"
    )).json()["hats"]

    assert [h["model_name"] for h in hits] != ["Marked"], (
        f"guest search leaked {field}={value!r} via ?q={term}"
    )
    # The marked hat is still ON SHOW when not searched for — the field is
    # withheld from matching, not the hat from the collection.
    browse = (await anon_client.get("/api/public/guest/collection")).json()["hats"]
    assert marked["id"] in {h["id"] for h in browse}


async def test_guest_search_still_works_on_what_it_shows(client, anon_client):
    """The restriction must not gut the feature: everything the projection
    displays stays searchable."""
    # `brand` is analysis-written, not a creation field — set it the way the
    # Edit form does.
    for model in ("Coronado", "Odysea"):
        hat = await _hat(client, model_name=model)
        await client.put(f"/api/hats/{hat['id']}", json={"brand": "Melin"})
    await _enable(client)

    for term, expected in (("Coronado", ["Coronado"]), ("Melin", ["Coronado", "Odysea"])):
        hits = (await anon_client.get(
            f"/api/public/guest/collection?q={term}"
        )).json()["hats"]
        assert sorted(h["model_name"] for h in hits) == expected, term


async def test_the_owners_own_search_still_sees_everything(client):
    """The restriction is for guests only — narrowing the owner's search would
    be a real regression in the feature they use most."""
    await _hat(
        client, model_name="Marked", condition="worn", construction="HYDROLite"
    )

    for term in ("worn", "HYDROLite"):
        hits = (await client.get(f"/api/search?q={term}")).json()
        assert [h["model_name"] for h in hits] == ["Marked"], term


async def test_guest_search_count_is_not_capped(client, anon_client, monkeypatch):
    """`hat_count` is the response's own length, so a truncated list would make
    it a lie — the `len()`-of-a-capped-list mistake, for the third time. First
    the cap was 50, then 500; any ceiling lies once the collection outgrows it,
    and the browse path already returns everything, so search has NO cap now.
    Fifty-five hats prove the old 50; the captured `limit` proves there is no
    ceiling left to outgrow."""
    from headroom.services import search_service

    seen: dict = {}
    real = search_service.search_hats

    async def _capture(db, query, **kw):
        seen.update(kw)
        return await real(db, query, **kw)

    monkeypatch.setattr(search_service, "search_hats", _capture)

    for i in range(55):
        await _hat(client, model_name=f"Coronado {i}")
    await _enable(client)

    body = (await anon_client.get("/api/public/guest/collection?q=Coronado")).json()

    assert body["hat_count"] == 55
    assert len(body["hats"]) == 55
    assert seen.get("limit", "unset") is None, f"guest search still capped: {seen}"


# ------------------------------- hat detail --------------------------------- #


async def test_a_guest_can_open_one_hat(client, anon_client):
    """"Where does this one live" is the question a guest actually has, and it
    should survive being sent to somebody — hence a deep link rather than a
    detail rendered only from the listing payload."""
    room = (await client.post("/api/rooms", json={"name": "Study"})).json()
    case = (await client.post(
        "/api/cases", json={"case_type": "archive", "room_id": room["id"]}
    )).json()
    hat = await _hat(client, model_name="Coronado", case_id=case["id"])
    await _enable(client)

    body = (await anon_client.get(f"/api/public/guest/hat/{hat['id']}")).json()

    assert body["model_name"] == "Coronado"
    assert body["case"] == case["display_id"]
    assert body["room"] == "Study"


async def test_a_room_stored_hat_reports_its_room(client, anon_client):
    """A caseless hat has a location too — via `direct_room`, not a case."""
    room = (await client.post("/api/rooms", json={"name": "Shelf"})).json()
    hat = await _hat(client, model_name="Loose", room_id=room["id"])
    await _enable(client)

    body = (await anon_client.get(f"/api/public/guest/hat/{hat['id']}")).json()

    assert body["case"] is None
    assert body["room"] == "Shelf"


async def test_hat_detail_carries_no_more_than_the_listing(client, anon_client):
    """The detail view must not become a wider projection than the grid.

    A per-hat endpoint is exactly where someone would reach for "just one more
    field" — and this is the surface where that costs the most.
    """
    hat = await _hat(
        client, model_name="Coronado", purchase_price=89.0, owner_notes="secret"
    )
    await _enable(client)

    body = (await anon_client.get(f"/api/public/guest/hat/{hat['id']}")).json()

    # `thumb_url` joined in 2.79: the same photo at grid size on the same
    # public route, nothing an outsider could not already fetch.
    assert set(body) == {
        "id", "display_id", "brand", "model_name", "style",
        "photo_url", "thumb_url", "colors", "case", "room",
    }
    for leak in ("purchase_price", "owner_notes", "secret", "89"):
        assert leak not in (await anon_client.get(
            f"/api/public/guest/hat/{hat['id']}"
        )).text


async def test_the_grid_gets_the_thumbnail_and_the_page_gets_the_photo(
    client, anon_client, isolated_upload_dir
):
    """The shared and guest grids served the full 1200 px cutout per tile —
    ~170 KB each, ~40 MB per open of a link to the real collection — while
    every signed-in grid rendered the 320 px WebP. Same route, `?variant=
    thumb`, and the projection says which is which."""
    from sqlalchemy import update as sa_update

    from headroom.config import settings
    from headroom.models.hat import Hat

    hat = await _hat(client, model_name="Thumbed")
    (settings.upload_dir / "hats" / "thumbs").mkdir(parents=True, exist_ok=True)
    (settings.upload_dir / "hats" / "full.png").write_bytes(b"\x89PNG full")
    (settings.upload_dir / "hats" / "thumbs" / "full.webp").write_bytes(b"RIFF small")
    from tests.conftest import test_session_factory

    async with test_session_factory() as db:
        await db.execute(sa_update(Hat).where(Hat.id == hat["id"]).values(
            photo_path="hats/full.png", thumb_path="hats/thumbs/full.webp",
        ))
        await db.commit()
    await _enable(client)

    listing = (await anon_client.get("/api/public/guest/collection")).json()
    row = next(h for h in listing["hats"] if h["id"] == hat["id"])
    assert row["photo_url"] == f"/api/public/guest/photo/{hat['id']}"
    assert row["thumb_url"] == f"/api/public/guest/photo/{hat['id']}?variant=thumb"
    assert (await anon_client.get(row["thumb_url"])).content == b"RIFF small"
    assert (await anon_client.get(row["photo_url"])).content == b"\x89PNG full"
    # An unknown variant is the full photo, never an error.
    assert (await anon_client.get(row["photo_url"] + "?variant=huge")).content == b"\x89PNG full"


async def test_a_photoless_hat_still_has_a_detail_page(client, anon_client):
    """`shared_hat` used to require a photo, because its only caller was the
    photo route. A hat plainly listed on the page you clicked from must not
    404 when you click it."""
    hat = await _hat(client, model_name="Unphotographed")
    await _enable(client)

    body = (await anon_client.get(f"/api/public/guest/hat/{hat['id']}")).json()

    assert body["model_name"] == "Unphotographed"
    assert body["photo_url"] is None


async def test_a_disposed_hat_has_no_detail_page(client, anon_client):
    hat = await _hat(client, model_name="Departed")
    await client.post(f"/api/hats/{hat['id']}/dispose", json={"via": "sold"})
    await _enable(client)

    assert (await anon_client.get(
        f"/api/public/guest/hat/{hat['id']}"
    )).status_code == 404


async def test_hat_detail_is_gated_like_everything_else(client, anon_client):
    hat = await _hat(client)
    await _enable(client, False)

    resp = await anon_client.get(f"/api/public/guest/hat/{hat['id']}")

    assert resp.status_code == 404
    assert "guest" not in resp.text.lower()


async def test_share_link_photos_still_require_a_photo(client, anon_client):
    """Relaxing `shared_hat` must not make the photo route serve a hat that
    hasn't got one."""
    hat = await _hat(client, model_name="Unphotographed")
    token = (await client.post(
        "/api/share-links", json={"label": "Mine"}
    )).json()["token"]

    resp = await anon_client.get(f"/api/public/share/{token}/photo/{hat['id']}")

    assert resp.status_code == 404


async def test_no_route_module_holds_a_shared_exception_instance(anon_client):
    """A module-level `HTTPException` re-raised per request leaks.

    CPython prepends each raise's frames onto the exception's existing
    `__traceback__`, so a shared instance grows a traceback chain for the life
    of the process and pins every request's locals with it — measured 0 → 30
    retained frames after five anonymous requests to these two modules, both
    reachable without a session. The 404s are factories now; this pins that no
    route module goes back to a shared instance, and drives the anonymous path
    a few times to make the property observable rather than declared.
    """
    import importlib
    import pkgutil

    from fastapi import HTTPException

    import headroom.routes as routes_pkg

    for _ in range(5):
        assert (await anon_client.get("/api/public/guest/collection")).status_code == 404
        assert (await anon_client.get("/api/public/share/not-a-real-token")).status_code == 404

    offenders = []
    for info in pkgutil.walk_packages(routes_pkg.__path__, routes_pkg.__name__ + "."):
        module = importlib.import_module(info.name)
        for name, value in vars(module).items():
            if isinstance(value, HTTPException):
                offenders.append(f"{info.name}.{name}")
                if value.__traceback__ is not None:
                    offenders[-1] += " (already carrying a traceback)"
    assert offenders == [], offenders
