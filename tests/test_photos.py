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
async def test_there_is_no_case_photo_route(client):
    """Cases show their CONTENTS, not a picture of the case.

    Every case looks identical from the outside, so the photo carried no
    information — and an empty one was actively worse: a case with three hats
    in it rendered a screen-filling "NO PHOTO" placeholder above its own
    contents. The grid moved to a collage of the hats first, but the detail
    page, the edit form and this route all kept the old feature alive, so the
    uploader was still there to be tapped. This pins the removal.
    """
    await client.post("/api/cases", json={"case_type": "archive"})
    resp = await client.post(
        "/api/cases/A-001/photo",
        files={"photo": ("test.jpg", _make_test_image_file(), "image/jpeg")},
    )
    # 404 or 405, and WHICH depends on the environment rather than on the app:
    # the SPA catch-all is only mounted when `frontend/dist` exists, and when it
    # is, it matches this path for GET — so an unmatched POST becomes "method
    # not allowed" instead of "not found". A dev box that has run a build gets
    # 405; CI, which builds the frontend in a separate job, gets 404. Asserting
    # either one alone pins the harness, not the behavior.
    assert resp.status_code in (404, 405), (
        f"the case-photo upload route is back (got {resp.status_code})"
    )


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
async def test_the_no_key_path_still_logs_its_timing(client, caplog):
    """A 24 s rembg run (minutes on a Pi) left no log line at all when no key
    was set: the timing line sat below the early return. Per-stage timing is
    a promise CLAUDE.md makes for every analysis, not only the ones Claude
    joined."""
    import logging

    resp = await client.post(
        "/api/hats", json={"condition": "new", "size": "classic", "style": "a_game"}
    )
    hat_id = resp.json()["id"]
    with caplog.at_level(logging.INFO, logger="headroom.services.hat_analysis_pipeline"):
        resp = await client.post(
            f"/api/hats/{hat_id}/photo",
            files={"photo": ("hat.jpg", _make_test_image_file(), "image/jpeg")},
        )
    assert resp.status_code == 200
    assert any(
        f"hat={hat_id} analyzed" in r.getMessage() and "rembg=" in r.getMessage()
        for r in caplog.records
    ), [r.getMessage() for r in caplog.records]


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


def _bomb_jpeg(width: int, height: int) -> bytes:
    """A real 1×1 JPEG whose frame header is patched to claim `width`×`height`.

    Pillow reads the dimensions out of the SOF0 marker before allocating a
    single pixel, which is exactly where the ceiling must fire.
    """
    buf = io.BytesIO()
    Image.new("RGB", (1, 1)).save(buf, "JPEG")
    data = bytearray(buf.getvalue())
    sof0 = data.index(b"\xff\xc0")
    # marker(2) length(2) precision(1) height(2) width(2)
    data[sof0 + 5 : sof0 + 7] = height.to_bytes(2, "big")
    data[sof0 + 7 : sof0 + 9] = width.to_bytes(2, "big")
    return bytes(data)


async def _hat_id(client) -> int:
    resp = await client.post(
        "/api/hats", json={"condition": "new", "size": "classic", "style": "a_game"}
    )
    return resp.json()["id"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "name, body, mime",
    [
        ("page.png", b"<html><script>alert(1)</script></html>", "image/png"),
        ("empty.jpg", b"", "image/jpeg"),
        ("bomb.jpg", _bomb_jpeg(60000, 60000), "image/jpeg"),
    ],
    ids=["html-as-png", "zero-bytes", "decompression-bomb"],
)
async def test_an_unreadable_photo_is_a_400_not_a_500(client, name, body, mime):
    """The content-type check reads a header the client chose; the real gate
    is Pillow's decode, and its failure was unhandled on THIS route while the
    logo route (fixed in review) answered 400 for the same bytes. Each of
    these produced a 500 and a durable `error.unhandled` row: HTML with an
    image MIME, an empty file, and a 60000×60000 header (3.6 gigapixels —
    Pillow refuses it before allocating, but only because a ceiling is set).
    """
    hat_id = await _hat_id(client)

    resp = await client.post(f"/api/hats/{hat_id}/photo", files={"photo": (name, body, mime)})

    assert resp.status_code == 400, resp.text
    assert "not an image" in resp.json()["detail"]
    rows = (await client.get("/api/admin/activity-log?limit=20")).json()
    assert not [r for r in rows if r["kind"] == "error.unhandled"], (
        "a bad upload is a client error, not an incident"
    )


@pytest.mark.anyio
async def test_the_logo_route_refuses_the_same_files_the_same_way(client):
    """One decoder, one answer: the two single-file routes must not diverge
    again (they did — B-2 fixed the logo and left the hat photo 500ing)."""
    for name, body, mime in [
        ("page.png", b"<html>", "image/png"),
        ("bomb.jpg", _bomb_jpeg(60000, 60000), "image/jpeg"),
    ]:
        resp = await client.post("/api/settings/logo", files={"photo": (name, body, mime)})
        assert resp.status_code == 400, (name, resp.text)
        assert "not an image" in resp.json()["detail"]


@pytest.mark.anyio
async def test_the_pixel_ceiling_is_set_once_for_every_decoder():
    """Pillow's default only WARNS at ~89 megapixels and errors at twice that,
    and a 178-megapixel file decodes to ~700 MB of RGBA beside the 179 MB
    rembg model in a 1 GB container. The ceiling is set where every decoder
    imports from, so a new `Image.open` site inherits it. A 48-megapixel
    phone photo must still pass (warning only, no error).
    """
    from PIL import Image

    from headroom.utils import photo

    assert Image.MAX_IMAGE_PIXELS == photo.MAX_SOURCE_PIXELS
    assert 40_000_000 <= photo.MAX_SOURCE_PIXELS <= 60_000_000
    # Pillow errors above 2× the ceiling, so the largest phone photo (8064 ×
    # 6048 = 48.8 MP) decodes and the bomb above does not.
    assert 8064 * 6048 < 2 * photo.MAX_SOURCE_PIXELS < 60000 * 60000


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
