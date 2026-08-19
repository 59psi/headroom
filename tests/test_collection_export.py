"""The shareable zip, and the one field on a hat that no analysis may touch."""

from __future__ import annotations

import io
import zipfile

import pytest
from PIL import Image

pytestmark = pytest.mark.anyio


async def _hat(client, **fields):
    resp = await client.post("/api/hats", json={
        "condition": "new", "size": "classic", "style": "a_game", **fields
    })
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _row(db_session, hat_id):
    from headroom.models.hat import Hat
    db_session.expire_all()
    return await db_session.get(Hat, hat_id)


def _write_photo(path, size=(1400, 1400)):
    """A real RGBA image on disk — the export re-encodes, so it needs pixels."""
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    for i in range(0, min(size) // 2, 4):
        img.putpixel((i + 5, i + 5), (60 + i % 150, 90, 140, 255))
    img.save(path, "PNG")
    return path


# ------------------------------ owner notes ---------------------------- #


async def test_owner_notes_round_trip(client):
    hat_id = await _hat(client)
    resp = await client.put(
        f"/api/hats/{hat_id}", json={"owner_notes": "Bought in Maui, first melin."}
    )
    assert resp.status_code == 200
    assert resp.json()["owner_notes"] == "Bought in Maui, first melin."
    assert (await client.get(f"/api/hats/{hat_id}")).json()["owner_notes"] == (
        "Bought in Maui, first melin."
    )


async def test_owner_notes_survive_a_reanalysis(client, db_session, isolated_upload_dir):
    """Every other prose field on a hat is derived and gets rewritten. This one
    is the exception, and a refresh quietly clearing it would be a trap — you
    would lose what you typed and find out much later."""
    from headroom.config import settings
    from headroom.services.hat_analysis_pipeline import run_fallback_analysis

    hat_id = await _hat(client)
    await client.put(f"/api/hats/{hat_id}", json={"owner_notes": "Mine."})

    cutout = _write_photo(settings.upload_dir / "hats" / "cut.png", size=(300, 300))
    row = await _row(db_session, hat_id)
    await run_fallback_analysis(db_session, row, cutout, reason="test")
    await db_session.commit()

    assert (await _row(db_session, hat_id)).owner_notes == "Mine."


# -------------------------------- export ------------------------------- #


async def _export(client, **params):
    resp = await client.get("/api/admin/collection-export", params=params)
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/zip"
    return zipfile.ZipFile(io.BytesIO(resp.content))


async def test_export_is_a_zip_with_a_browsable_page(client, db_session):
    hat_id = await _hat(client)
    row = await _row(db_session, hat_id)
    row.brand = "Melin"
    row.model_name = "Coronado"
    row.owner_notes = "Favourite one."
    await db_session.commit()

    zf = await _export(client)
    assert "index.html" in zf.namelist()
    page = zf.read("index.html").decode()
    assert "Melin Coronado" in page
    assert "Favourite one." in page


async def test_export_omits_prices_unless_asked(client, db_session):
    """The version you send a friend. The inventory report is the one with the
    money in it, and share links withhold prices for the same reason."""
    hat_id = await _hat(client)
    row = await _row(db_session, hat_id)
    row.resale_price = 137.0
    await db_session.commit()

    assert "137" not in (await _export(client)).read("index.html").decode()
    assert "137" in (await _export(client, include_values="true")).read("index.html").decode()


async def test_export_excludes_disposed_hats_by_default(client):
    await _hat(client)
    gone = await _hat(client)
    assert (await client.post(f"/api/hats/{gone}/dispose", json={"via": "sold"})).status_code == 200
    assert "1 hats" in (await _export(client)).read("index.html").decode()


async def test_export_survives_a_photo_row_pointing_at_nothing(client, db_session):
    """A DB row naming a file that isn't there costs that one photo, not the
    whole download — the export is most wanted when things are already a bit
    broken."""
    hat_id = await _hat(client)
    row = await _row(db_session, hat_id)
    row.photo_path = "hats/does-not-exist.png"
    await db_session.commit()

    zf = await _export(client)
    assert "index.html" in zf.namelist()
    assert not [n for n in zf.namelist() if n.startswith("images/")]


async def test_export_re_encodes_at_800px_from_the_canonical_photo(
    client, db_session, isolated_upload_dir
):
    """Images are regenerated, not copied from the 320px grid thumbnail.

    Copying the thumbnail is what made an exported page look soft the moment
    anyone opened it on a laptop; upscaling one would be worse still, producing
    a bigger file that looks the same.
    """
    from headroom.config import settings

    hat_id = await _hat(client)
    _write_photo(settings.upload_dir / "hats" / "big.png", size=(1400, 1400))
    row = await _row(db_session, hat_id)
    row.photo_path = "hats/big.png"
    row.thumb_path = None
    await db_session.commit()

    zf = await _export(client)
    names = [n for n in zf.namelist() if n.startswith("images/")]
    assert names == [f"images/{hat_id}.webp"], names

    with Image.open(io.BytesIO(zf.read(names[0]))) as img:
        assert img.format == "WEBP"
        assert max(img.size) == 800, f"expected 800px, got {img.size}"


async def test_export_images_are_cached_and_reused(client, db_session, isolated_upload_dir):
    """Re-encoding every full-resolution photo on every download is a minute of
    Pi CPU for an unchanged collection. The second export must not redo it."""
    from headroom.config import settings

    hat_id = await _hat(client)
    _write_photo(settings.upload_dir / "hats" / "big.png")
    row = await _row(db_session, hat_id)
    row.photo_path = "hats/big.png"
    await db_session.commit()

    await _export(client)
    cached = settings.upload_dir / "hats" / "export" / "big.webp"
    assert cached.exists(), "export derivative was not cached"

    marker = cached.stat().st_mtime_ns
    await _export(client)
    assert cached.stat().st_mtime_ns == marker, "cache was needlessly rebuilt"


async def test_export_names_images_by_hat_id_not_display_id():
    """An unassigned hat has no display id, and two hats can briefly share one
    mid-reshuffle — either would collide inside the zip."""
    from headroom.models.hat import Hat
    from headroom.services.export_service import _image_name

    hat = Hat(condition="new", size="classic", style="a_game")
    hat.id = 42
    hat.photo_path = "hats/whatever.png"
    assert _image_name(hat) == "42.webp"

    hat.photo_path = None
    hat.thumb_path = None
    assert _image_name(hat) is None
