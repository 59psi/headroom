import io

import pytest
from PIL import Image


def _make_test_image(color=(255, 0, 0)):
    img = Image.new("RGB", (100, 100), color)
    buf = io.BytesIO()
    img.save(buf, "JPEG")
    buf.seek(0)
    return buf


async def _create_hat_with_photo(client, style="a_game", color=(255, 0, 0)):
    resp = await client.post(
        "/api/hats",
        json={"condition": "new", "size": "classic", "style": style},
    )
    hat_id = resp.json()["id"]
    photo = _make_test_image(color)
    await client.post(
        f"/api/hats/{hat_id}/photo",
        files={"photo": ("hat.jpg", photo, "image/jpeg")},
    )
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
    hat_id = await _create_hat_with_photo(client, color=(255, 0, 0))

    resp = await client.get("/api/search?q=red")
    assert resp.status_code == 200
    results = resp.json()
    assert any(r["id"] == hat_id for r in results)


@pytest.mark.anyio
async def test_search_exact_colors(client):
    """With exact_colors=true, search matches CSS3 color_name."""
    hat_id = await _create_hat_with_photo(client, color=(255, 0, 0))

    # Get the hat to find its exact CSS3 color_name
    hat_resp = await client.get(f"/api/hats/{hat_id}")
    hat_data = hat_resp.json()
    if not hat_data["colors"]:
        pytest.skip("No colors detected")

    exact_name = hat_data["colors"][0]["color_name"]

    resp = await client.get(f"/api/search?q={exact_name}&exact_colors=true")
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
