"""Retained originals, re-cutting, and gallery thumbnails.

Two problems with one root: the pre-cutout JPEG used to be deleted the moment
rembg succeeded. That made a poor cutout unfixable except by re-uploading the
photo — the stored PNG can never be re-segmented, because running rembg on an
already-transparent image eats the alpha and trims the bill a little more each
pass. Keeping the original makes a re-cut possible; it also happens to be what
lets the gallery serve something smaller than a 1200px PNG.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from headroom.config import settings
from headroom.utils.photo import THUMB_DIMENSION, make_thumbnail

pytestmark = pytest.mark.anyio


@pytest.fixture
def fake_cutout(monkeypatch):
    """Make background removal actually produce a PNG.

    conftest stubs `remove_background` to return None everywhere (rembg is far
    too heavy for tests), which means no cutout — and with no cutout there is
    correctly no separate original to keep. Retention and re-cutting only exist
    on the path where a cutout succeeds, so they need this.
    """
    async def _remove(input_path, output_path):
        out = output_path.with_suffix(".png")
        img = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
        for x in range(50, 150):
            for y in range(50, 150):
                img.putpixel((x, y), (200, 30, 90, 255))
        img.save(out, "PNG")
        return out

    monkeypatch.setattr(
        "headroom.services.hat_analysis_pipeline.remove_background", _remove
    )


def _jpeg(color=(40, 90, 200)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (600, 600), color).save(buf, "JPEG")
    return buf.getvalue()


async def _hat_with_photo(client) -> dict:
    created = await client.post(
        "/api/hats", json={"condition": "new", "size": "classic", "style": "a_game"}
    )
    hat_id = created.json()["id"]
    resp = await client.post(
        f"/api/hats/{hat_id}/photo", files={"photo": ("h.jpg", _jpeg(), "image/jpeg")}
    )
    return resp.json()


async def test_thumbnail_is_small_and_keeps_transparency(tmp_path):
    """A flattened thumbnail would put a white box behind every floating hat."""
    src = tmp_path / "cutout.png"
    # Transparent surround with an opaque blob — an actual cutout. A fully
    # opaque RGBA would encode as RGB and prove nothing about alpha.
    img = Image.new("RGBA", (1200, 1200), (0, 0, 0, 0))
    for x in range(300, 900):
        for y in range(300, 900):
            img.putpixel((x, y), (200, 30, 90, 255))
    img.save(src, "PNG")

    thumb = make_thumbnail(src, tmp_path / "thumbs" / "cutout")

    assert thumb is not None and thumb.exists()
    with Image.open(thumb) as img:
        assert img.mode == "RGBA", "alpha must survive — hats float on the canvas"
        assert max(img.size) <= THUMB_DIMENSION
    assert thumb.stat().st_size < src.stat().st_size


async def test_thumbnail_failure_is_survivable(tmp_path):
    """Never let a missing thumbnail fail the thing that produced the photo."""
    assert make_thumbnail(tmp_path / "does-not-exist.png", tmp_path / "t") is None


async def test_upload_keeps_the_original_and_makes_a_thumbnail(client, fake_cutout):
    """Without the original there is nothing to re-cut from later."""
    body = await _hat_with_photo(client)

    assert body["original_path"], "the pre-cutout JPEG must be retained"
    assert (settings.upload_dir / body["original_path"]).exists()
    assert body["thumb_path"], "gallery thumbnail missing"
    assert (settings.upload_dir / body["thumb_path"]).exists()


async def test_recut_requires_an_original(client):
    """Hats analyzed before originals were kept must say so, not fail obscurely."""
    created = await client.post(
        "/api/hats", json={"condition": "new", "size": "classic", "style": "eagle"}
    )
    hat_id = created.json()["id"]

    resp = await client.post(f"/api/hats/{hat_id}/recut")
    assert resp.status_code == 400
    assert "re-upload" in resp.json()["detail"].lower()


async def test_recut_runs_the_pipeline_again_from_the_original(client, fake_cutout):
    """A re-cut is the upload path replayed, not a special case."""
    body = await _hat_with_photo(client)
    hat_id = body["id"]
    original = body["original_path"]

    resp = await client.post(f"/api/hats/{hat_id}/recut")
    assert resp.status_code == 200
    # The original is the input, so it must still be there afterwards —
    # otherwise a second re-cut would be impossible.
    assert (settings.upload_dir / original).exists()
    assert resp.json()["original_path"] == original


async def test_replacing_a_photo_clears_the_previous_derivatives(client, fake_cutout):
    """A stale thumb_path would show the OLD hat in the gallery."""
    body = await _hat_with_photo(client)
    hat_id = body["id"]
    old_thumb = settings.upload_dir / body["thumb_path"]
    old_original = settings.upload_dir / body["original_path"]

    replaced = await client.post(
        f"/api/hats/{hat_id}/photo",
        files={"photo": ("new.jpg", _jpeg((10, 200, 10)), "image/jpeg")},
    )

    assert replaced.json()["thumb_path"] != body["thumb_path"]
    assert not old_thumb.exists(), "the previous thumbnail was left on disk"
    assert not old_original.exists(), "the previous original was left on disk"


async def test_replacing_a_photo_clears_the_export_derivative(client, fake_cutout):
    """The fourth derivative, which is not named by any column.

    `photo_path`, `original_path` and `thumb_path` are all on the hat, so a
    loop over them catches three of the four. The export image is derived from
    the canonical photo's FILENAME and lives under `hats/export/`, so it was
    invisible to that loop and every re-shot hat leaked one 800px WebP.
    """
    from headroom.utils.photo import export_derivative_path

    body = await _hat_with_photo(client)
    hat_id = body["id"]

    # Build the derivative the way the export does, so this fails if the two
    # ever disagree about where it lives.
    await client.get("/api/admin/collection-export")
    stale = export_derivative_path(settings.upload_dir, body["photo_path"])
    assert stale.exists(), "export did not produce a derivative to begin with"

    await client.post(
        f"/api/hats/{hat_id}/photo",
        files={"photo": ("new.jpg", _jpeg((10, 200, 10)), "image/jpeg")},
    )
    assert not stale.exists(), "the previous export image was left on disk"


async def test_backfill_only_touches_hats_without_a_thumbnail(client, db_session, fake_cutout):
    """Idempotent, so a restart mid-backfill resumes instead of redoing."""
    from sqlalchemy import update as sa_update

    from headroom.models.hat import Hat
    from headroom.services import hat_service

    body = await _hat_with_photo(client)
    hat_id = body["id"]

    # Nothing to do while the thumbnail is present.
    assert await hat_service.backfill_thumbnails(db_session) == 0

    await db_session.execute(
        sa_update(Hat).where(Hat.id == hat_id).values(thumb_path=None)
    )
    await db_session.commit()

    assert await hat_service.backfill_thumbnails(db_session) == 1
    assert await hat_service.backfill_thumbnails(db_session) == 0
