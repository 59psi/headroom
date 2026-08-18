"""Phase-1 "find the hat" features: color-similarity search, normalized
color chips, name/brand search matching, disposed exclusion, per-case
capacity overrides."""

from __future__ import annotations

import pytest

from headroom.services.color_extraction import (
    color_distance,
    normalize_hex_name,
    palette,
    parse_hex,
)

pytestmark = pytest.mark.anyio


# --------------------------- color science ---------------------------- #


async def test_parse_hex_variants():
    assert parse_hex("#1c2541") == (28, 37, 65)
    assert parse_hex("1C2541") == (28, 37, 65)
    assert parse_hex("nope") is None
    assert parse_hex("#12345") is None


async def test_color_distance_orders_perceptually():
    """Nearer shades score lower. Identity is 0, garbage is None.

    Note what is deliberately NOT asserted any more. This test used to claim
    light blue was nearer to navy than to red — hue-family reasoning, and true
    under ΔE*76. Under CIEDE2000 it is false (55.8 vs 52.0), because a pale
    sky blue and a near-black navy are 58 points apart in lightness while the
    red is only 29. That is the correct answer to "are these the same colour",
    and it is the whole reason a light-blue search stopped returning navies.
    Both sit far beyond MAX_MATCH_SCORE, so their relative order decides
    nothing a user ever sees.
    """
    light_blue = "#8cb9e1"
    assert color_distance(light_blue, "#9dc4e8") < color_distance(light_blue, "#4a5a78")
    assert color_distance(light_blue, "#4a5a78") < color_distance(light_blue, "#1c2541")
    assert color_distance(light_blue, light_blue) == 0
    assert color_distance("bad", light_blue) is None


async def test_normalize_hex_name_snaps_to_palette():
    # "sky blue"-ish hex → palette's "light blue", whatever Claude called it
    assert normalize_hex_name("#8cb9e1", "sky blue") == "light blue"
    assert normalize_hex_name(None, "sky blue") == "sky blue"
    assert normalize_hex_name("garbage", "sky blue") == "sky blue"


async def test_palette_endpoint(client):
    resp = await client.get("/api/meta/colors")
    assert resp.status_code == 200
    chips = resp.json()
    assert {"name": "navy", "hex": "#1c2541"} in chips
    assert all(set(c) == {"name", "hex"} for c in chips)


# ----------------------- fixtures: a small collection ------------------ #


async def _hat(client, style="a_game", **fields):
    resp = await client.post(
        "/api/hats", json={"condition": "new", "size": "classic", "style": style, **fields}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _set_colors(db_session, hat_id, colors):
    from headroom.models.hat_color import HatColor

    for rank, (name, general, hexv) in enumerate(colors, start=1):
        db_session.add(
            HatColor(
                hat_id=hat_id,
                color_name=name,
                general_color=general,
                hex_value=hexv,
                dominance_rank=rank,
                tier=["primary", "secondary", "tertiary"][min(rank - 1, 2)],
            )
        )
    await db_session.commit()


# ------------------------- color similarity search --------------------- #


async def test_color_search_ranks_by_closeness(client, db_session):
    """Nearest first, among hats that are actually near.

    The three seeds are all inside MAX_MATCH_SCORE on purpose. This used to
    seed a navy and a red as the second and third results, which only worked
    because there was no cutoff and the list was padded out with whatever was
    least-far. Ranking is still the assertion; "returns three rows" no longer
    is, and `test_color_search_drops_hats_beyond_the_cutoff` covers why.
    """
    sky = await _hat(client)
    paler = await _hat(client)
    slate = await _hat(client)
    await _set_colors(db_session, sky, [("sky blue", "light blue", "#9dc4e8")])
    await _set_colors(db_session, paler, [("pale blue", "light blue", "#b8d4ef")])
    await _set_colors(db_session, slate, [("slate", "blue", "#6d93bd")])

    resp = await client.get("/api/search/color", params={"hex": "8cb9e1"})
    assert resp.status_code == 200
    results = resp.json()
    assert [r["id"] for r in results] == [sky, paler, slate]
    assert results[0]["distance"] < results[1]["distance"] < results[2]["distance"]
    assert results[0]["matched_hex"] == "#9dc4e8"


async def test_color_search_matches_secondary_colors(client, db_session):
    """A hat whose SECONDARY color is light blue still surfaces near the top."""
    two_tone = await _hat(client)
    await _set_colors(
        db_session,
        two_tone,
        [("black", "black", "#121212"), ("sky blue", "light blue", "#8fbde4")],
    )
    resp = await client.get("/api/search/color", params={"hex": "8cb9e1"})
    results = resp.json()
    assert results[0]["id"] == two_tone
    assert results[0]["matched_hex"] == "#8fbde4"  # matched on the secondary
    assert results[0]["matched_rank"] == 2


async def test_a_hat_that_IS_the_colour_outranks_one_that_merely_accents_it(
    client, db_session
):
    """The bug this whole weighting exists for.

    A melin hat is a dark neutral crown with a bright logo, so a search colour
    that appears as somebody's logo appears on half the collection. Scoring a
    hat on the MINIMUM distance across its swatches made a green hat with a
    pink logo score 0.00 — identical to a hat that is actually pink, listed
    indistinguishably beside it, with nothing on screen explaining why.

    Both still come back. The order is the point.
    """
    pink = await _hat(client)
    green_with_pink_logo = await _hat(client)
    await _set_colors(db_session, pink, [("pink", "pink", "#c86fa8")])
    await _set_colors(
        db_session,
        green_with_pink_logo,
        [
            ("forest", "forest green", "#2f4739"),
            ("grey", "gray", "#6b6f70"),
            ("pink logo", "pink", "#c86fa8"),  # exactly the search colour
        ],
    )

    results = (await client.get("/api/search/color", params={"hex": "c86fa8"})).json()
    assert [r["id"] for r in results] == [pink, green_with_pink_logo]
    # Both matched a swatch identical to the target, so raw distance cannot be
    # what separates them — only the rank can.
    assert results[0]["distance"] == results[1]["distance"] == 0.0
    assert results[0]["matched_rank"] == 1
    assert results[1]["matched_rank"] == 3


async def test_the_rank_penalty_is_a_distance_budget_not_just_a_tiebreak(
    client, db_session
):
    """The same swatch is a match as a hat's main colour and not as its accent.

    #a04a80 is 14.3 from the target — a recognisably different pink. On the
    hat that IS that colour, that is close enough to answer "show me the pink
    ones". As a logo on an otherwise green hat it is neither the colour asked
    for nor even a match for it, and returning it is how the list filled up
    with things the eye rejects instantly.
    """
    its_main_colour = await _hat(client)
    only_its_logo = await _hat(client)
    await _set_colors(db_session, its_main_colour, [("dusky", "pink", "#a04a80")])
    await _set_colors(
        db_session,
        only_its_logo,
        [
            ("forest", "forest green", "#2f4739"),
            ("grey", "gray", "#6b6f70"),
            ("dusky logo", "pink", "#a04a80"),
        ],
    )

    results = (await client.get("/api/search/color", params={"hex": "c86fa8"})).json()
    assert [r["id"] for r in results] == [its_main_colour]


async def test_a_neutral_search_no_longer_matches_the_entire_collection(
    client, db_session
):
    """CIEDE2000 puts a low-chroma neutral moderately near everything.

    Every hat here owns a grey swatch, so at the old cutoff of 30 a grey was
    within range of 17 of the 25 other palette colours — red, orange, purple
    and pink included — and every colour search returned every hat, bunched at
    distances that made them all look equally relevant.

    Searching pink must not return grey hats. Searching grey still must.
    """
    grey = await _hat(client)
    charcoal = await _hat(client)
    await _set_colors(db_session, grey, [("grey", "gray", "#6b7078")])
    await _set_colors(db_session, charcoal, [("charcoal", "charcoal", "#3a3f45")])

    pink_hits = (await client.get("/api/search/color", params={"hex": "c86fa8"})).json()
    assert pink_hits == [], "a grey hat is not a pink hat"

    grey_hits = (await client.get("/api/search/color", params={"hex": "808080"})).json()
    assert [r["id"] for r in grey_hits] == [grey]


async def test_color_search_excludes_disposed_and_validates_hex(client, db_session):
    hat_id = await _hat(client)
    await _set_colors(db_session, hat_id, [("navy", "navy", "#1c2541")])
    disposed = await client.post(
        f"/api/hats/{hat_id}/dispose", json={"via": "sold"}
    )
    assert disposed.status_code == 200

    resp = await client.get("/api/search/color", params={"hex": "1c2541"})
    assert all(r["id"] != hat_id for r in resp.json())

    resp = await client.get("/api/search/color", params={"hex": "not-a-color"})
    assert resp.status_code == 422


# --------------------------- text search upgrades ---------------------- #


async def test_search_matches_brand_and_model(client, db_session):
    from headroom.models.hat import Hat

    hat_id = await _hat(client)
    hat = await db_session.get(Hat, hat_id)
    hat.brand = "Melin"
    hat.model_name = "A-Game Hydro"
    await db_session.commit()

    resp = await client.get("/api/search", params={"q": "hydro"})
    results = resp.json()
    assert [r["id"] for r in results] == [hat_id]
    assert results[0]["brand"] == "Melin"
    assert results[0]["model_name"] == "A-Game Hydro"


async def test_search_excludes_disposed(client):
    hat_id = await _hat(client)
    await client.post(f"/api/hats/{hat_id}/dispose", json={"via": "sold"})
    resp = await client.get("/api/search", params={"q": "a_game"})
    assert all(r["id"] != hat_id for r in resp.json())


# ------------------------- normalization backfill ---------------------- #


async def test_normalize_existing_colors_backfill(client, db_session):
    from headroom.models.hat_color import HatColor
    from headroom.services.hat_service import normalize_existing_colors

    hat_id = await _hat(client)
    await _set_colors(db_session, hat_id, [("sky blue", "sky blue", "#8cb9e1")])

    changed = await normalize_existing_colors(db_session)
    assert changed == 1

    row = (await db_session.execute(
        __import__("sqlalchemy").select(HatColor).where(HatColor.hat_id == hat_id)
    )).scalar_one()
    assert row.general_color == "light blue"   # normalized
    assert row.color_name == "sky blue"        # original phrasing kept

    # Idempotent
    assert await normalize_existing_colors(db_session) == 0


# ------------------------- per-case capacity --------------------------- #


async def test_case_capacity_override(client):
    case = await client.post("/api/cases", json={"case_type": "archive", "capacity": 3})
    assert case.status_code == 201, case.text
    data = case.json()
    assert data["capacity"] == 3
    case_id = data["id"]

    for _ in range(3):
        resp = await client.post(
            "/api/hats",
            json={"condition": "new", "size": "classic", "style": "a_game", "case_id": case_id},
        )
        assert resp.status_code == 201, resp.text

    resp = await client.post(
        "/api/hats",
        json={"condition": "new", "size": "classic", "style": "a_game", "case_id": case_id},
    )
    assert resp.status_code == 409
    assert "capacity (3)" in resp.json()["detail"]


async def test_case_capacity_default_unchanged(client):
    """No override → the classic 4-regular limit still applies."""
    case = await client.post("/api/cases", json={"case_type": "archive"})
    case_id = case.json()["id"]
    assert case.json()["capacity"] is None

    for _ in range(4):
        resp = await client.post(
            "/api/hats",
            json={"condition": "new", "size": "classic", "style": "a_game", "case_id": case_id},
        )
        assert resp.status_code == 201
    resp = await client.post(
        "/api/hats",
        json={"condition": "new", "size": "classic", "style": "a_game", "case_id": case_id},
    )
    assert resp.status_code == 409


async def test_case_capacity_update(client):
    case = await client.post("/api/cases", json={"case_type": "archive", "capacity": 3})
    display_id = case.json()["display_id"]
    resp = await client.put(f"/api/cases/{display_id}", json={"capacity": 4})
    assert resp.status_code == 200
    assert resp.json()["capacity"] == 4


# ----------------------- CIEDE2000 conformance ------------------------- #
#
# The distance function is CIEDE2000, not the ΔE*76 it used to be. The formula
# has several places — the hue-average discontinuity at the 0/360 wrap, the
# atan2 quadrant, degrees vs radians — where a plausible-looking mistake still
# returns plausible-looking numbers, so it is pinned to the published test set
# rather than eyeballed. Source: Sharma, Wu & Dalal (2005), the standard
# verification data for the CIE formula.
#
# Pairs 9-15 exist specifically to catch the hue-wrap bug: a naive mean-hue
# average is out by 180 degrees there and every other pair still passes.
_SHARMA_PAIRS = [
    ((50, 2.6772, -79.7751), (50, 0, -82.7485), 2.0425),
    ((50, 3.1571, -77.2803), (50, 0, -82.7485), 2.8615),
    ((50, 2.8361, -74.0200), (50, 0, -82.7485), 3.4412),
    ((50, -1.3802, -84.2814), (50, 0, -82.7485), 1.0000),
    ((50, -1.1848, -84.8006), (50, 0, -82.7485), 1.0000),
    ((50, -0.9009, -85.5211), (50, 0, -82.7485), 1.0000),
    ((50, 0, 0), (50, -1, 2), 2.3669),
    ((50, -1, 2), (50, 0, 0), 2.3669),
    ((50, 2.4900, -0.0010), (50, -2.4900, 0.0009), 7.1792),
    ((50, 2.4900, -0.0010), (50, -2.4900, 0.0010), 7.1792),
    ((50, 2.4900, -0.0010), (50, -2.4900, 0.0011), 7.2195),
    ((50, 2.4900, -0.0010), (50, -2.4900, 0.0012), 7.2195),
    ((50, -0.0010, 2.4900), (50, 0.0009, -2.4900), 4.8045),
    ((50, -0.0010, 2.4900), (50, 0.0010, -2.4900), 4.8045),
    ((50, -0.0010, 2.4900), (50, 0.0011, -2.4900), 4.7461),
    ((50, 2.5, 0), (50, 0, -2.5), 4.3065),
    ((50, 2.5, 0), (73, 25, -18), 27.1492),
    ((50, 2.5, 0), (61, -5, 29), 22.8977),
    ((50, 2.5, 0), (56, -27, -3), 31.9030),
    ((50, 2.5, 0), (58, 24, 15), 19.4535),
    ((50, 2.5, 0), (50, 3.1736, 0.5854), 1.0000),
    ((50, 2.5, 0), (50, 3.2972, 0), 1.0000),
    ((50, 2.5, 0), (50, 1.8634, 0.5757), 1.0000),
    ((50, 2.5, 0), (50, 3.2592, 0.3350), 1.0000),
    ((60.2574, -34.0099, 36.2677), (60.4626, -34.1751, 39.4387), 1.2644),
    ((63.0109, -31.0961, -5.8663), (62.8187, -29.7946, -4.0864), 1.2630),
    ((61.2901, 3.7196, -5.3901), (61.4292, 2.2480, -4.9620), 1.8731),
    ((35.0831, -44.1164, 3.7933), (35.0232, -40.0716, 1.5901), 1.8645),
    ((22.7233, 20.0904, -46.6940), (23.0331, 14.9730, -42.5619), 2.0373),
    ((36.4612, 47.8580, 18.3852), (36.2715, 50.5065, 21.2231), 1.4146),
    ((90.8027, -2.0831, 1.4410), (91.1528, -1.6435, 0.0447), 1.4441),
    ((90.9257, -0.5406, -0.9208), (88.6381, -0.8985, -0.7239), 1.5381),
    ((6.7747, -0.2908, -2.4247), (5.8714, -0.0985, -2.2286), 0.6377),
    ((2.0776, 0.0795, -1.1350), (0.9033, -0.0636, -0.5514), 0.9082),
]


@pytest.mark.parametrize("lab1,lab2,expected", _SHARMA_PAIRS)
async def test_ciede2000_matches_the_published_reference_data(lab1, lab2, expected):
    from headroom.services.color_extraction import lab_distance

    assert lab_distance(lab1, lab2) == pytest.approx(expected, abs=1e-4)


async def test_ciede2000_is_symmetric():
    from headroom.services.color_extraction import lab_distance

    for lab1, lab2, _ in _SHARMA_PAIRS:
        assert lab_distance(lab1, lab2) == pytest.approx(lab_distance(lab2, lab1), abs=1e-9)


async def test_navy_shades_read_as_closer_than_navy_to_slate():
    """The reason for the change.

    ΔE*76 over-weights differences among saturated blues, which is most of
    this collection. Two navies a person would call the same shade scored
    further apart than a navy and a grey-blue; CIEDE2000's chroma and
    hue-rotation terms are what fix it.
    """
    navy, other_navy, slate = "#1c2541", "#1d2947", "#4a5a78"
    assert color_distance(navy, other_navy) < color_distance(navy, slate)


# ------------------------ colour-search cutoff ------------------------- #


async def _hat_with_color(client, db_session, hex_value: str):
    from headroom.models.hat import Hat
    from headroom.models.hat_color import HatColor

    resp = await client.post(
        "/api/hats", json={"condition": "new", "size": "classic", "style": "a_game"}
    )
    hat_id = resp.json()["id"]
    row = await db_session.get(Hat, hat_id)
    row.colors.append(
        HatColor(color_name="x", general_color="x", hex_value=hex_value, dominance_rank=1)
    )
    await db_session.commit()
    return hat_id


async def test_color_search_drops_hats_beyond_the_cutoff(client, db_session):
    """A result list that always fills to `limit` says nothing about whether
    anything matched. Before the cutoff, searching a teal in a collection of
    a hundred returned thirty hats however far away they were."""
    near_hat = await _hat_with_color(client, db_session, "#8cb9e1")   # light blue
    await _hat_with_color(client, db_session, "#c82828")            # red
    await _hat_with_color(client, db_session, "#2f7a2f")            # green

    resp = await client.get("/api/search/color?hex=%238cb9e1")
    assert resp.status_code == 200
    ids = [r["id"] for r in resp.json()]
    assert ids == [near_hat], "only the light blue is close to light blue"


async def test_color_search_still_returns_near_misses(client, db_session):
    """The cutoff must not be so tight that it only matches near-exactly —
    "show me the light blue ones" is the whole point of the feature."""
    exact = await _hat_with_color(client, db_session, "#8cb9e1")
    nearby = await _hat_with_color(client, db_session, "#9dc4e8")

    ids = [r["id"] for r in (await client.get("/api/search/color?hex=%238cb9e1")).json()]
    assert set(ids) == {exact, nearby}


async def test_color_search_can_return_nothing(client, db_session):
    """Empty is now a real answer, and the UI says so rather than 'No hats'."""
    await _hat_with_color(client, db_session, "#c82828")
    assert (await client.get("/api/search/color?hex=%238cb9e1")).json() == []


async def test_cutoff_is_applied_before_the_limit(client, db_session):
    """Order matters: filtering after truncation would let far-away hats
    occupy slots and push nearer ones out."""
    from headroom.services.search_service import search_hats_by_color

    near = await _hat_with_color(client, db_session, "#8cb9e1")
    await _hat_with_color(client, db_session, "#c82828")

    ranked = await search_hats_by_color(db_session, "#8cb9e1", limit=1)
    assert [m.hat.id for m in ranked] == [near]
