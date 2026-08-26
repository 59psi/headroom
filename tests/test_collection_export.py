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
    row.owner_notes = "Favorite one."
    await db_session.commit()

    zf = await _export(client)
    assert "index.html" in zf.namelist()
    page = zf.read("index.html").decode()
    assert "Melin Coronado" in page
    assert "Favorite one." in page


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


# ------------------------- the export does no image work ---------------- #


async def test_the_export_does_no_image_work_on_the_event_loop(
    client, db_session, isolated_upload_dir, monkeypatch
):
    """The bug: minutes of a Pi answering nothing, and a download that
    appeared to produce nothing at all.

    Every hat's 800px derivative was generated inline, in the card-rendering
    loop, ON the event loop — a full-resolution decode plus a WebP `method=6`
    encode each. A few hundred hats is several minutes during which the app
    serves no request, with a decoded full-res image resident alongside
    rembg's model in a 1 GB container.

    Asserts on the thread rather than on elapsed time, because a timing
    assertion here would be slow AND flaky while proving something weaker.
    """
    import threading

    from headroom.services import export_service
    from headroom.config import settings

    hat_id = await _hat(client)
    _write_photo(settings.upload_dir / "hats" / "loop.png")
    row = await _row(db_session, hat_id)
    row.photo_path = "hats/loop.png"
    await db_session.commit()

    loop_thread = threading.current_thread().ident
    ran_on: list[int | None] = []
    real = export_service._export_image_path

    def _spy(source_rel):
        ran_on.append(threading.current_thread().ident)
        return real(source_rel)

    monkeypatch.setattr(export_service, "_export_image_path", _spy)

    await _export(client)

    assert ran_on, "the image path was never resolved"
    assert all(t != loop_thread for t in ran_on), (
        "export image work ran on the event loop"
    )


async def test_the_derivative_is_written_when_the_photo_is_processed(
    client, db_session, isolated_upload_dir
):
    """So an export is a zip of files that already exist.

    Generating them lazily meant the FIRST export of an existing collection
    paid for all of them at once, inside one request. One hat's work belongs
    where one hat is processed — in the analysis worker, where it costs the
    upload nothing.
    """
    from headroom.config import settings
    from headroom.services.hat_analysis_pipeline import finalize_hat_photo
    from headroom.utils.photo import export_derivative_path

    hat_id = await _hat(client)
    source = _write_photo(settings.upload_dir / "hats" / "fresh.png")
    row = await _row(db_session, hat_id)

    await finalize_hat_photo(db_session, row, source)

    assert export_derivative_path(settings.upload_dir, row.photo_path).exists()


async def test_the_backfill_covers_hats_that_predate_the_change(
    client, db_session, isolated_upload_dir
):
    """Otherwise the first export after upgrading still pays for everything.

    Which is the same several-minute stall, moved to a slightly later date.
    """
    from headroom.config import settings
    from headroom.services import hat_service
    from headroom.utils.photo import export_derivative_path

    hat_id = await _hat(client)
    _write_photo(settings.upload_dir / "hats" / "old.png")
    row = await _row(db_session, hat_id)
    row.photo_path = "hats/old.png"
    await db_session.commit()
    cache = export_derivative_path(settings.upload_dir, "hats/old.png")
    assert not cache.exists()

    made = await hat_service.backfill_export_images(db_session)

    assert made == 1
    assert cache.exists()


async def test_the_backfill_is_idempotent(client, db_session, isolated_upload_dir):
    """A restart mid-sweep must pick up, not start over.

    The file's existence is the record — there is no column — so this falls
    out of the mtime check rather than needing bookkeeping.
    """
    from headroom.config import settings
    from headroom.services import hat_service

    hat_id = await _hat(client)
    _write_photo(settings.upload_dir / "hats" / "twice.png")
    row = await _row(db_session, hat_id)
    row.photo_path = "hats/twice.png"
    await db_session.commit()

    assert await hat_service.backfill_export_images(db_session) == 1
    assert await hat_service.backfill_export_images(db_session) == 0
