
import pytest


async def _create_hat_with_colors(client, colors, style="a_game"):
    """Create a hat and seed colors via the explicit /colors endpoint.

    Tests should use this rather than relying on photo-upload-driven analysis,
    which requires an Anthropic API key in the new pipeline.
    """
    resp = await client.post(
        "/api/hats",
        json={"condition": "new", "size": "classic", "style": style},
    )
    hat_id = resp.json()["id"]
    await client.put(f"/api/hats/{hat_id}/colors", json={"colors": colors})
    return hat_id


@pytest.mark.anyio
async def test_search_by_style(client):
    await client.post(
        "/api/hats",
        json={"condition": "new", "size": "classic", "style": "a_game"},
    )
    await client.post(
        "/api/hats",
        json={"condition": "new", "size": "classic", "style": "beanie"},
    )

    resp = await client.get("/api/search?q=a_game")
    assert resp.status_code == 200
    results = resp.json()
    assert len(results) == 1
    assert results[0]["style"] == "a_game"


@pytest.mark.anyio
async def test_search_by_condition(client):
    await client.post(
        "/api/hats",
        json={"condition": "worn", "size": "classic", "style": "a_game"},
    )
    await client.post(
        "/api/hats",
        json={"condition": "new", "size": "classic", "style": "beanie"},
    )

    resp = await client.get("/api/search?q=worn")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


@pytest.mark.anyio
async def test_search_by_size(client):
    await client.post(
        "/api/hats",
        json={"condition": "new", "size": "x_large", "style": "a_game"},
    )

    resp = await client.get("/api/search?q=x_large")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


@pytest.mark.anyio
@pytest.mark.parametrize("term", ["x-large", "xlarge", "X-Large", "x_large"])
async def test_a_size_is_found_by_how_it_is_printed(client, term):
    """Every page prints `x_large` as "X Large". A search for "x-large" or
    "xlarge" found nothing; only "x large" did, by accident — "x" and "large"
    each matched something on their own."""
    big = await client.post(
        "/api/hats", json={"condition": "new", "size": "x_large", "style": "a_game"}
    )
    await client.post(
        "/api/hats", json={"condition": "new", "size": "classic", "style": "a_game"}
    )

    resp = await client.get("/api/search", params={"q": term})

    assert resp.status_code == 200
    assert [h["id"] for h in resp.json()] == [big.json()["id"]], term


@pytest.mark.anyio
async def test_the_size_labels_are_the_ones_search_matches(client):
    """The picker's labels and the search's are one table, so what a person
    reads on the page is what finds the hat."""
    from headroom.schemas.hat import SIZE_LABELS, HatSize

    sizes = (await client.get("/api/meta/sizes")).json()

    assert sizes == [{"value": s.value, "label": SIZE_LABELS[s.value]} for s in HatSize]
    assert {o["label"] for o in sizes} == {"Small", "Classic", "X Large"}


@pytest.mark.anyio
async def test_a_size_label_is_matched_for_the_owner_only(client, db_session):
    """A guest's `SharedHat` carries no size, so a guest search must not match
    one by its label either — that would read every hat's size by probing.
    And a term that is all punctuation names no size at all, rather than
    being contained in every label."""
    from headroom.services import search_service

    # Odysea: a style label with no hyphen, so "-" has nothing else to match.
    created = await client.post(
        "/api/hats", json={"condition": "new", "size": "x_large", "style": "odysea"}
    )
    hat_id = created.json()["id"]

    assert [h.id for h in await search_service.search_hats(db_session, "xlarge")] == [hat_id]
    assert await search_service.search_hats(db_session, "xlarge", public_fields_only=True) == []
    assert await search_service.search_hats(db_session, "-") == []


@pytest.mark.anyio
async def test_search_multi_term_and(client):
    await client.post(
        "/api/hats",
        json={"condition": "new", "size": "classic", "style": "a_game"},
    )
    await client.post(
        "/api/hats",
        json={"condition": "worn", "size": "classic", "style": "a_game"},
    )

    # Both terms must match
    resp = await client.get("/api/search?q=a_game+new")
    assert resp.status_code == 200
    results = resp.json()
    assert len(results) == 1
    assert results[0]["condition"] == "new"


@pytest.mark.anyio
async def test_search_no_results(client):
    await client.post(
        "/api/hats",
        json={"condition": "new", "size": "classic", "style": "a_game"},
    )

    resp = await client.get("/api/search?q=nonexistent")
    assert resp.status_code == 200
    assert len(resp.json()) == 0


@pytest.mark.anyio
async def test_search_empty_query(client):
    resp = await client.get("/api/search?q=")
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_search_by_general_color(client):
    """Default search matches against general_color (e.g. 'red')."""
    hat_id = await _create_hat_with_colors(
        client,
        colors=[
            {
                "color_name": "crimson",
                "general_color": "red",
                "hex_value": "#dc143c",
                "dominance_rank": 1,
                "tier": "primary",
            }
        ],
    )

    resp = await client.get("/api/search?q=red")
    assert resp.status_code == 200
    results = resp.json()
    assert any(r["id"] == hat_id for r in results)


@pytest.mark.anyio
async def test_search_exact_colors(client):
    """With exact_colors=true, search matches the specific color_name."""
    hat_id = await _create_hat_with_colors(
        client,
        colors=[
            {
                "color_name": "darkslategray",
                "general_color": "gray",
                "hex_value": "#2f4f4f",
                "dominance_rank": 1,
                "tier": "primary",
            }
        ],
    )

    resp = await client.get("/api/search?q=darkslategray&exact_colors=true")
    assert resp.status_code == 200
    results = resp.json()
    assert any(r["id"] == hat_id for r in results)


@pytest.mark.anyio
async def test_search_by_room(client):
    """Search with room_id filter returns only hats in that room."""
    # Create a second room and cases in each room
    room_resp = await client.post("/api/rooms", json={"name": "Office"})
    room2_id = room_resp.json()["id"]

    case1_resp = await client.post(
        "/api/cases", json={"case_type": "archive", "room_id": 1}
    )
    case1_id = case1_resp.json()["id"]
    case2_resp = await client.post(
        "/api/cases", json={"case_type": "archive", "room_id": room2_id}
    )
    case2_id = case2_resp.json()["id"]

    # Create a hat in each case
    hat1_resp = await client.post(
        "/api/hats",
        json={"condition": "new", "size": "classic", "style": "a_game", "case_id": case1_id},
    )
    hat1_id = hat1_resp.json()["id"]
    hat2_resp = await client.post(
        "/api/hats",
        json={"condition": "new", "size": "classic", "style": "a_game", "case_id": case2_id},
    )
    hat2_id = hat2_resp.json()["id"]

    # Search with room_id filter
    resp = await client.get(f"/api/search?q=a_game&room_id={room2_id}")
    assert resp.status_code == 200
    results = resp.json()
    result_ids = [r["id"] for r in results]
    assert hat2_id in result_ids
    assert hat1_id not in result_ids


@pytest.mark.anyio
async def test_search_by_room_name(client):
    """Room names are searchable as terms."""
    room_resp = await client.post("/api/rooms", json={"name": "Garage"})
    room_id = room_resp.json()["id"]

    case_resp = await client.post(
        "/api/cases", json={"case_type": "archive", "room_id": room_id}
    )
    case_id = case_resp.json()["id"]
    hat_resp = await client.post(
        "/api/hats",
        json={"condition": "new", "size": "classic", "style": "a_game", "case_id": case_id},
    )
    hat_id = hat_resp.json()["id"]

    resp = await client.get("/api/search?q=garage")
    assert resp.status_code == 200
    results = resp.json()
    assert any(r["id"] == hat_id for r in results)


@pytest.mark.anyio
async def test_search_finds_hydro_and_hydrolite_flags(client):
    """USAGE promises "`hydro` finds every Hydro".

    They were `style` values until 2.6.0 made them boolean columns, at which
    point no `ilike` in the term filter could match them and the documented
    search silently returned nothing.
    """
    plain = await client.post(
        "/api/hats", json={"condition": "new", "size": "classic", "style": "a_game"}
    )
    hydro = await client.post(
        "/api/hats",
        json={"condition": "new", "size": "classic", "style": "coronado", "hydro": True},
    )
    lite = await client.post(
        "/api/hats",
        json={"condition": "new", "size": "classic", "style": "eagle", "hydrolite": True},
    )

    found = await client.get("/api/search?q=hydro")
    ids = {h["id"] for h in found.json()}
    assert hydro.json()["id"] in ids
    assert plain.json()["id"] not in ids

    found_lite = await client.get("/api/search?q=hydrolite")
    lite_ids = {h["id"] for h in found_lite.json()}
    assert lite.json()["id"] in lite_ids
    # "hydro" is a prefix of "hydrolite" — searching the longer word must not
    # also return every plain HYDRO hat.
    assert hydro.json()["id"] not in lite_ids


@pytest.mark.anyio
async def test_search_matches_the_colorway_for_the_owner_only(client, db_session):
    """"808" is printed on the hat card and matched nothing. The guest view
    does not show a colorway, so it must not match on one either."""
    from headroom.services import search_service

    created = await client.post(
        "/api/hats", json={"condition": "new", "size": "classic", "style": "a_game"}
    )
    hat_id = created.json()["id"]
    await client.put(f"/api/hats/{hat_id}", json={"colorway": "Hawaii 808"})

    found = await client.get("/api/search?q=808")
    assert hat_id in {h["id"] for h in found.json()}
    assert await search_service.search_hats(db_session, "808", public_fields_only=True) == []


@pytest.mark.anyio
async def test_search_matches_artist_series(client):
    """Special editions are findable by collaborator, not just by model."""
    created = await client.post(
        "/api/hats", json={"condition": "new", "size": "classic", "style": "collab"}
    )
    hat_id = created.json()["id"]
    await client.put(f"/api/hats/{hat_id}", json={"artist_series": "Skye Walker"})

    found = await client.get("/api/search?q=skye")
    assert hat_id in {h["id"] for h in found.json()}


@pytest.mark.anyio
async def test_search_results_carry_construction(client):
    """The Hats and Search pages share one filter bar and one predicate.

    `matchesHatFilters` reads `construction` off each row, and the Search page
    applies it to whatever `/api/search` returns. A field the filter reads but
    the projection omits is the worst kind of broken: the control renders, the
    dropdown is populated from `/api/meta/constructions`, and selecting
    anything silently matches nothing.
    """
    resp = await client.post(
        "/api/hats",
        json={
            "condition": "new", "size": "classic", "style": "a_game",
            "model_name": "Coronado", "construction": "HYDROLite",
        },
    )
    assert resp.status_code == 201

    results = (await client.get("/api/search?q=Coronado")).json()
    assert len(results) == 1
    assert results[0]["construction"] == "HYDROLite"


@pytest.mark.anyio
async def test_search_result_construction_is_null_when_unrecorded(client):
    """Null rather than absent — the "Not recorded" filter option needs it."""
    await client.post(
        "/api/hats",
        json={
            "condition": "new", "size": "classic", "style": "a_game",
            "model_name": "Bare",
        },
    )
    results = (await client.get("/api/search?q=Bare")).json()
    assert len(results) == 1
    assert "construction" in results[0]
    assert results[0]["construction"] is None


async def _hat_with_colors(client, model_name, colors):
    """Create a hat whose swatches are `colors`, IN DOMINANCE ORDER.

    `dominance_rank` is assigned positionally by every writer — the analysis
    pipeline, the fallback path and this endpoint all do `enumerate(start=1)`
    — so the rank is the index, not something a caller can state. Passing a
    rank field here would be ignored, which is exactly the trap that made an
    earlier version of these tests pass for the wrong reason.
    """
    resp = await client.post(
        "/api/hats",
        json={"condition": "new", "size": "classic", "style": "a_game",
              "model_name": model_name},
    )
    hat_id = resp.json()["id"]
    await client.put(
        f"/api/hats/{hat_id}/colors",
        json={"colors": [
            {"color_name": c, "general_color": c, "hex_value": "#123456",
             "dominance_rank": i}
            for i, c in enumerate(colors, start=1)
        ]},
    )
    return hat_id


@pytest.mark.anyio
async def test_color_search_ignores_accents_by_default(client):
    """A hat is not "pink" because its logo is.

    Every melin hat is a dark crown with a bright mark on it, so matching any
    row in `hat_colors` made color terms close to useless — the accent colors
    are precisely the ones that vary.
    """
    # Names deliberately free of the search term: `model_name` is also
    # searched, so calling them "PinkLogo" would match whatever the color
    # clause did and the test would prove nothing.
    await _hat_with_colors(client, "Coronado", ["pink", "black"])
    await _hat_with_colors(client, "Odysea", ["black", "grey", "pink"])

    hits = (await client.get("/api/search?q=pink")).json()

    assert [h["model_name"] for h in hits] == ["Coronado"], "an accent matched"


@pytest.mark.anyio
async def test_accent_scope_finds_the_opposite_set(client):
    """Its own question, not just the complement: "which hats have pink on them
    somewhere" is how you look for a collab mark."""
    await _hat_with_colors(client, "Coronado", ["pink", "black"])
    await _hat_with_colors(client, "Odysea", ["black", "grey", "pink"])

    hits = (await client.get("/api/search?q=pink&color_scope=accent")).json()

    assert [h["model_name"] for h in hits] == ["Odysea"]


@pytest.mark.anyio
async def test_all_scope_returns_both(client):
    await _hat_with_colors(client, "Coronado", ["pink"])
    await _hat_with_colors(client, "Odysea", ["black", "grey", "pink"])

    hits = (await client.get("/api/search?q=pink&color_scope=all")).json()

    assert sorted(h["model_name"] for h in hits) == ["Coronado", "Odysea"]


@pytest.mark.anyio
async def test_secondary_colors_still_count_as_major(client):
    """Rank 2 is the hat's other real color — a two-tone crown — not an
    accent. Excluding it would make a black/white cap unfindable as "white"."""
    await _hat_with_colors(client, "TwoTone", ["black", "white"])

    hits = (await client.get("/api/search?q=white")).json()

    assert [h["model_name"] for h in hits] == ["TwoTone"]


@pytest.mark.anyio
async def test_an_unknown_color_scope_is_refused_not_guessed(client, db_session):
    """It arrives from a query string, so a typo is the caller's 422 — not a
    500, not a silently wider search, and not the default scope's answer
    under a request that asked for a different one (which is what reading it
    as `major` returned, indistinguishable from "no accent matches").

    Below the route the service still reads anything unknown as the
    narrowest scope, for a caller that is not an HTTP request."""
    from headroom.services import search_service

    await _hat_with_colors(client, "Odysea", ["black", "grey", "pink"])

    resp = await client.get("/api/search?q=pink&color_scope=nonsense")
    assert resp.status_code == 422

    assert await search_service.search_hats(db_session, "pink", color_scope="nonsense") == []
