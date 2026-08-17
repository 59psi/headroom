import pytest


async def _create_case(client, case_type="archive"):
    resp = await client.post("/api/cases", json={"case_type": case_type})
    return resp.json()


async def _create_hat(client, **overrides):
    data = {
        "condition": "new",
        "size": "classic",
        "style": "a_game",
    }
    data.update(overrides)
    return await client.post("/api/hats", json=data)


@pytest.mark.anyio
async def test_create_hat_unassigned(client):
    resp = await _create_hat(client)
    assert resp.status_code == 201
    data = resp.json()
    assert data["case_id"] is None
    assert data["display_id"] is None
    assert data["is_beanie"] is False


@pytest.mark.anyio
async def test_create_hat_in_case(client):
    case = await _create_case(client)
    resp = await _create_hat(client, case_id=case["id"])
    assert resp.status_code == 201
    data = resp.json()
    assert data["case_id"] == case["id"]
    assert data["position_in_case"] == 1
    assert data["display_id"] == "A-001-01"
    assert data["case_display_id"] == "A-001"


@pytest.mark.anyio
async def test_hat_read_exposes_every_derived_field(client):
    """HatRead is built straight off the ORM object, so the values that come
    from a *relationship* rather than a column are the ones that can silently
    go null. Pin all of them on one fully-populated hat.

    room_id in particular is what the Hats page filters on client-side — if it
    stopped being populated the filter would just quietly match nothing.
    """
    room = (await client.post("/api/rooms", json={"name": "Closet"})).json()
    case = (await client.post(
        "/api/cases", json={"case_type": "daily_wear", "room_id": room["id"]}
    )).json()
    hat_id = (await _create_hat(client, case_id=case["id"])).json()["id"]
    await client.post(f"/api/hats/{hat_id}/wear", json={})

    data = (await client.get(f"/api/hats/{hat_id}")).json()
    assert data["case_display_id"] == case["display_id"]
    assert data["case_type"] == "daily_wear"
    assert data["room_id"] == room["id"]
    assert data["room_name"] == "Closet"
    assert data["wear_count"] == 1
    assert data["display_id"] == f"{case['display_id']}-01"

    # An unassigned hat must degrade to nulls, not raise walking hat.case.room.
    loose_id = (await _create_hat(client)).json()["id"]
    loose = (await client.get(f"/api/hats/{loose_id}")).json()
    assert loose["case_display_id"] is None
    assert loose["case_type"] is None
    assert loose["room_id"] is None
    assert loose["room_name"] is None
    assert loose["wear_count"] == 0


@pytest.mark.anyio
async def test_hat_positions_sequential(client):
    case = await _create_case(client)
    await _create_hat(client, case_id=case["id"])
    resp = await _create_hat(client, case_id=case["id"])
    data = resp.json()
    assert data["position_in_case"] == 2
    assert data["display_id"] == "A-001-02"


@pytest.mark.anyio
async def test_create_beanie(client):
    resp = await _create_hat(client, style="beanie")
    assert resp.status_code == 201
    assert resp.json()["is_beanie"] is True


@pytest.mark.anyio
async def test_list_hats(client):
    await _create_hat(client)
    await _create_hat(client, style="beanie")
    resp = await client.get("/api/hats")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


@pytest.mark.anyio
async def test_list_hats_filter_by_style(client):
    await _create_hat(client, style="a_game")
    await _create_hat(client, style="beanie")
    resp = await client.get("/api/hats?style=beanie")
    assert len(resp.json()) == 1
    assert resp.json()[0]["style"] == "beanie"


@pytest.mark.anyio
async def test_get_hat(client):
    create_resp = await _create_hat(client)
    hat_id = create_resp.json()["id"]
    resp = await client.get(f"/api/hats/{hat_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == hat_id


@pytest.mark.anyio
async def test_get_hat_not_found(client):
    resp = await client.get("/api/hats/999")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_update_hat(client):
    create_resp = await _create_hat(client)
    hat_id = create_resp.json()["id"]
    resp = await client.put(
        f"/api/hats/{hat_id}", json={"condition": "worn"}
    )
    assert resp.status_code == 200
    assert resp.json()["condition"] == "worn"


@pytest.mark.anyio
async def test_delete_hat(client):
    create_resp = await _create_hat(client)
    hat_id = create_resp.json()["id"]
    resp = await client.delete(f"/api/hats/{hat_id}")
    assert resp.status_code == 204
    resp = await client.get(f"/api/hats/{hat_id}")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_assign_hat_to_case(client):
    case = await _create_case(client)
    create_resp = await _create_hat(client)
    hat_id = create_resp.json()["id"]
    resp = await client.patch(
        f"/api/hats/{hat_id}/assign", json={"case_id": case["id"]}
    )
    assert resp.status_code == 200
    assert resp.json()["case_id"] == case["id"]
    assert resp.json()["display_id"] == "A-001-01"


@pytest.mark.anyio
async def test_unassign_hat(client):
    case = await _create_case(client)
    create_resp = await _create_hat(client, case_id=case["id"])
    hat_id = create_resp.json()["id"]
    resp = await client.patch(
        f"/api/hats/{hat_id}/assign", json={"case_id": None}
    )
    assert resp.status_code == 200
    assert resp.json()["case_id"] is None
    assert resp.json()["display_id"] is None


@pytest.mark.anyio
async def test_hat_nonexistent_case(client):
    resp = await _create_hat(client, case_id=999)
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_hydrolite_is_orthogonal_to_style(client):
    """HYDROLite is melin CONSTRUCTION, not a model line.

    It ships across A-Game, Coronado, Trenches and the rest, so it has to be a
    per-hat flag: as a HatStyle value it would need a second entry per model and
    would split one model's hats across two style buckets. This pins that the
    flag rides alongside style rather than replacing it, on create and update.
    """
    hat = (await client.post("/api/hats", json={
        "condition": "new", "size": "classic", "style": "coronado", "hydrolite": True,
    })).json()
    assert hat["hydrolite"] is True
    assert hat["style"] == "coronado"   # still its own model
    # The legacy boolean is folded into the free-form field it replaced, so a
    # pre-2.11 client's hat is indistinguishable from one added through the
    # current form.
    assert hat["construction"] == "HYDROLite"

    # Togglable without disturbing the model.
    off = (await client.put(f"/api/hats/{hat['id']}", json={"hydrolite": False})).json()
    assert off["hydrolite"] is False
    assert off["construction"] is None
    assert off["style"] == "coronado"


@pytest.mark.anyio
async def test_hydrolite_defaults_to_false_when_omitted(client):
    hat = (await client.post("/api/hats", json={
        "condition": "new", "size": "classic", "style": "a_game",
    })).json()
    assert hat["hydrolite"] is False


@pytest.mark.anyio
async def test_hydrolite_is_not_a_style_option(client):
    """Guards the mistake this replaced — it must not reappear in the model list."""
    styles = (await client.get("/api/meta/styles")).json()
    assert "hydrolite" not in [s["value"] for s in styles]


@pytest.mark.anyio
async def test_hydro_and_hydrolite_are_independent_flags(client):
    """Two constructions, two flags — set, cleared and read back independently."""
    hat = (await client.post("/api/hats", json={
        "condition": "new", "size": "classic", "style": "coronado", "hydro": True,
    })).json()
    assert hat["hydro"] is True
    assert hat["hydrolite"] is False

    swapped = (await client.put(
        f"/api/hats/{hat['id']}", json={"hydro": False, "hydrolite": True}
    )).json()
    assert swapped["hydro"] is False
    assert swapped["hydrolite"] is True


@pytest.mark.anyio
async def test_artist_series_round_trips(client):
    hat = (await client.post("/api/hats", json={
        "condition": "new", "size": "classic", "style": "collab",
    })).json()
    assert hat["artist_series"] is None
    named = (await client.put(
        f"/api/hats/{hat['id']}", json={"artist_series": "Skye Walker"}
    )).json()
    assert named["artist_series"] == "Skye Walker"


@pytest.mark.anyio
async def test_hats_list_accepts_the_whole_collection_limit(client):
    """The Hats grid, Home carousel and Valuation totals all fetch every hat.

    They filter and total client-side, so a short page doesn't read as
    "page 1 of n" — it reads as hats having vanished and the collection being
    worth less than it is. `FULL_COLLECTION_LIMIT` in `api/hats.ts` sends this
    exact value, so the API has to accept it.
    """
    resp = await client.get("/api/hats?limit=1000")
    assert resp.status_code == 200, "limit=1000 must be within the allowed range"

    too_big = await client.get("/api/hats?limit=1001")
    assert too_big.status_code == 422, "the ceiling should still bound the response"
