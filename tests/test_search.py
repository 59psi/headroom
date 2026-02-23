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
        json={"condition": "new", "size": "standard", "style": style},
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
        json={"condition": "new", "size": "standard", "style": "a_game"},
    )
    await client.post(
        "/api/hats",
        json={"condition": "new", "size": "standard", "style": "beanie"},
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
        json={"condition": "worn", "size": "standard", "style": "a_game"},
    )
    await client.post(
        "/api/hats",
        json={"condition": "new", "size": "standard", "style": "beanie"},
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
        json={"condition": "new", "size": "standard", "style": "a_game"},
    )
    await client.post(
        "/api/hats",
        json={"condition": "worn", "size": "standard", "style": "a_game"},
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
        json={"condition": "new", "size": "standard", "style": "a_game"},
    )

    resp = await client.get("/api/search?q=nonexistent")
    assert resp.status_code == 200
    assert len(resp.json()) == 0


@pytest.mark.anyio
async def test_search_empty_query(client):
    resp = await client.get("/api/search?q=")
    assert resp.status_code == 422
