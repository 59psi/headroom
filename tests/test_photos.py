import io

import pytest
from PIL import Image

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
    # Fits inside the 1200 box AND preserves the exact 3:2 aspect ratio — not
    # merely "small enough" (a square crop would also satisfy max <= 1200).
    assert result_img.size == (1200, 800)


@pytest.mark.anyio
async def test_process_image_does_not_upscale(tmp_path):
    """A photo already under the cap keeps its dimensions — thumbnail() only
    shrinks. Upscaling would waste bytes and invent detail that isn't there."""
    img = Image.new("RGB", (640, 480), (10, 20, 30))
    input_path = tmp_path / "small.jpg"
    img.save(input_path, "JPEG")

    result = Image.open(process_image(input_path, tmp_path / "out.jpg"))
    assert result.size == (640, 480)


@pytest.mark.anyio
async def test_process_image_converts_png(tmp_path):
    img = Image.new("RGBA", (100, 100), (255, 0, 0, 128))
    input_path = tmp_path / "test.png"
    img.save(input_path, "PNG")

    output_path = tmp_path / "out.png"
    result = process_image(input_path, output_path)
    assert result.suffix == ".jpg"
    # A path rename is not a conversion: open the bytes and confirm they really
    # decode as a JPEG with the transparency flattened to RGB.
    with Image.open(result) as out:
        assert out.format == "JPEG"
        assert out.mode == "RGB"


@pytest.mark.anyio
async def test_upload_case_photo(client):
    from headroom.config import settings

    await client.post("/api/cases", json={"case_type": "archive"})
    photo = _make_test_image_file()
    resp = await client.post(
        "/api/cases/A-001/photo",
        files={"photo": ("test.jpg", photo, "image/jpeg")},
    )
    assert resp.status_code == 200
    photo_path = resp.json()["photo_path"]
    assert photo_path is not None
    assert "cases/" in photo_path
    # A returned path with no file behind it renders as a broken image — the
    # bytes must actually be on disk.
    saved = settings.upload_dir / photo_path
    assert saved.is_file() and saved.stat().st_size > 0


@pytest.mark.anyio
async def test_upload_hat_photo_no_api_key(client):
    """Without an API key, upload still succeeds; analysis is marked skipped."""
    resp = await client.post(
        "/api/hats",
        json={"condition": "new", "size": "classic", "style": "a_game"},
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
    assert data["analysis_status"] == "skipped"
    assert data["colors"] == []


@pytest.mark.anyio
async def test_upload_invalid_type(client):
    resp = await client.post(
        "/api/hats",
        json={"condition": "new", "size": "classic", "style": "a_game"},
    )
    hat_id = resp.json()["id"]

    resp = await client.post(
        f"/api/hats/{hat_id}/photo",
        files={"photo": ("test.txt", b"not an image", "text/plain")},
    )
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_replace_photo_deletes_old(client):
    from headroom.config import settings

    resp = await client.post(
        "/api/hats",
        json={"condition": "new", "size": "classic", "style": "a_game"},
    )
    hat_id = resp.json()["id"]

    photo1 = _make_test_image_file(color=(255, 0, 0))
    resp1 = await client.post(
        f"/api/hats/{hat_id}/photo",
        files={"photo": ("red.jpg", photo1, "image/jpeg")},
    )
    old_path = resp1.json()["photo_path"]
    old_file = settings.upload_dir / old_path
    assert old_file.is_file()  # the first upload really landed on disk

    photo2 = _make_test_image_file(color=(0, 255, 0))
    resp2 = await client.post(
        f"/api/hats/{hat_id}/photo",
        files={"photo": ("green.jpg", photo2, "image/jpeg")},
    )
    new_path = resp2.json()["photo_path"]
    new_file = settings.upload_dir / new_path

    assert old_path != new_path
    # The whole point of the endpoint: replacing a photo must delete the old
    # file, not orphan it. Orphaned cutouts silently fill the Pi's SD card, and
    # asserting only that the path string changed would never catch that.
    assert not old_file.exists(), "old photo was orphaned on disk"
    assert new_file.is_file(), "replacement photo missing on disk"
