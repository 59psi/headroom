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
    light_blue = "#8cb9e1"
    assert color_distance(light_blue, "#9dc4e8") < color_distance(light_blue, "#1c2541")
    assert color_distance(light_blue, "#1c2541") < color_distance(light_blue, "#c82828")
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
    sky = await _hat(client)
    navy = await _hat(client)
    red = await _hat(client)
    await _set_colors(db_session, sky, [("sky blue", "light blue", "#9dc4e8")])
    await _set_colors(db_session, navy, [("navy", "navy", "#1c2541")])
    await _set_colors(db_session, red, [("crimson", "red", "#c82828")])

    resp = await client.get("/api/search/color", params={"hex": "8cb9e1"})
    assert resp.status_code == 200
    results = resp.json()
    assert [r["id"] for r in results][:1] == [sky]
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
