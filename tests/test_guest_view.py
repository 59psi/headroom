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


async def test_only_an_authenticated_owner_can_flip_it(anon_client):
    resp = await anon_client.put("/api/settings/guest-view", json={"enabled": True})
    assert resp.status_code == 401


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


async def test_guest_view_does_not_open_the_rest_of_the_api(client, anon_client):
    """Enabling guest browsing must not weaken the gate on anything else."""
    await _enable(client)

    for path in ("/api/hats", "/api/cases", "/api/rooms", "/api/settings/guest-view"):
        assert (await anon_client.get(path)).status_code == 401, path


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
    assert marked  # named for the reader


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


async def test_guest_search_count_is_not_capped(client, anon_client):
    """`hat_count` is the response's own length, so a truncated list would make
    it a lie — the `len()`-of-a-capped-list mistake, for the third time."""
    for i in range(55):
        await _hat(client, model_name=f"Coronado {i}")
    await _enable(client)

    body = (await anon_client.get("/api/public/guest/collection?q=Coronado")).json()

    assert body["hat_count"] == 55
    assert len(body["hats"]) == 55


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

    assert set(body) == {
        "id", "display_id", "brand", "model_name", "style",
        "photo_url", "colors", "case", "room",
    }
    for leak in ("purchase_price", "owner_notes", "secret", "89"):
        assert leak not in (await anon_client.get(
            f"/api/public/guest/hat/{hat['id']}"
        )).text


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
