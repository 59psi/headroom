import io
import tempfile
from pathlib import Path

import pytest
from PIL import Image

from headroom.services.color_service import extract_colors
from headroom.utils.photo import process_image


def _make_test_image_file(color=(255, 0, 0), size=(100, 100)):
    """Return BytesIO with JPEG content for upload."""
    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    img.save(buf, "JPEG")
    buf.seek(0)
    return buf


@pytest.mark.anyio
async def test_process_image_resizes(tmp_path):
    img = Image.new("RGB", (3000, 2000), (0, 128, 255))
    input_path = tmp_path / "big.jpg"
    img.save(input_path, "JPEG")

    output_path = tmp_path / "out.jpg"
    result = process_image(input_path, output_path)

    result_img = Image.open(result)
    assert max(result_img.size) <= 1200


@pytest.mark.anyio
async def test_process_image_converts_png(tmp_path):
    img = Image.new("RGBA", (100, 100), (255, 0, 0, 128))
    input_path = tmp_path / "test.png"
    img.save(input_path, "PNG")

    output_path = tmp_path / "out.png"
    result = process_image(input_path, output_path)
    assert result.suffix == ".jpg"


@pytest.mark.anyio
async def test_extract_dominant_color(tmp_path):
    img = Image.new("RGB", (200, 200), (255, 0, 0))
    path = tmp_path / "red.jpg"
    img.save(path, "JPEG")

    colors = extract_colors(path, count=3)
    assert len(colors) >= 1
    assert colors[0]["dominance_rank"] == 1
    assert colors[0]["hex_value"].startswith("#")


@pytest.mark.anyio
async def test_upload_case_photo(client):
    await client.post("/api/cases", json={"case_type": "archive"})
    photo = _make_test_image_file()
    resp = await client.post(
        "/api/cases/A-001/photo",
        files={"photo": ("test.jpg", photo, "image/jpeg")},
    )
    assert resp.status_code == 200
    assert resp.json()["photo_path"] is not None
    assert "cases/" in resp.json()["photo_path"]


@pytest.mark.anyio
async def test_upload_hat_photo(client):
    resp = await client.post(
        "/api/hats",
        json={"condition": "new", "size": "standard", "style": "a_game"},
    )
    hat_id = resp.json()["id"]

    photo = _make_test_image_file(color=(0, 0, 200))
    resp = await client.post(
        f"/api/hats/{hat_id}/photo",
        files={"photo": ("blue_hat.jpg", photo, "image/jpeg")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["photo_path"] is not None
    assert "hats/" in data["photo_path"]
    assert len(data["colors"]) >= 1


@pytest.mark.anyio
async def test_upload_invalid_type(client):
    resp = await client.post(
        "/api/hats",
        json={"condition": "new", "size": "standard", "style": "a_game"},
    )
    hat_id = resp.json()["id"]

    resp = await client.post(
        f"/api/hats/{hat_id}/photo",
        files={"photo": ("test.txt", b"not an image", "text/plain")},
    )
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_replace_photo_deletes_old(client):
    resp = await client.post(
        "/api/hats",
        json={"condition": "new", "size": "standard", "style": "a_game"},
    )
    hat_id = resp.json()["id"]

    photo1 = _make_test_image_file(color=(255, 0, 0))
    resp1 = await client.post(
        f"/api/hats/{hat_id}/photo",
        files={"photo": ("red.jpg", photo1, "image/jpeg")},
    )
    old_path = resp1.json()["photo_path"]

    photo2 = _make_test_image_file(color=(0, 255, 0))
    resp2 = await client.post(
        f"/api/hats/{hat_id}/photo",
        files={"photo": ("green.jpg", photo2, "image/jpeg")},
    )
    new_path = resp2.json()["photo_path"]
    assert old_path != new_path
