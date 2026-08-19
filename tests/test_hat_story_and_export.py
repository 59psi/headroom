"""The long-form write-up, the owner's own notes, and the shareable zip.

`write_story` itself is stubbed everywhere by an autouse conftest fixture — the
house rule is that tests never call Anthropic — so what is pinned here is the
*plumbing*: when a rewrite gets queued, what survives a refresh, and what the
export actually contains.
"""

from __future__ import annotations

import io
import zipfile

import pytest

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


# --------------------------- queueing a rewrite ------------------------ #


async def test_setting_the_collection_queues_a_rewrite(client, db_session):
    """The collection is the fact the write-up is most about.

    Nearly the whole middle paragraph is "what is this collab", so changing it
    invalidates prose that is otherwise still accurate — the failure mode is a
    hat confidently described as part of a series it is no longer in.
    """
    hat_id = await _hat(client)
    assert (await _row(db_session, hat_id)).story_pending is False

    resp = await client.put(f"/api/hats/{hat_id}", json={"artist_series": "Mark Healey"})
    assert resp.status_code == 200
    assert (await _row(db_session, hat_id)).story_pending is True


async def test_a_rewrite_is_not_queued_when_the_collection_did_not_change(
    client, db_session
):
    """Saving the same value must not queue work.

    The edit form PUTs every field it holds, so a save that only changed the
    size would otherwise re-run a Claude call for every hat the owner touches.
    """
    hat_id = await _hat(client, artist_series="Mark Healey")
    await client.put(f"/api/hats/{hat_id}", json={"artist_series": "Mark Healey"})
    assert (await _row(db_session, hat_id)).story_pending is False

    await client.put(f"/api/hats/{hat_id}", json={"size": "small"})
    assert (await _row(db_session, hat_id)).story_pending is False


async def test_a_respelt_collection_does_not_queue_a_rewrite(client, db_session):
    """"piña" and "Piña" are one collection, and would produce one write-up.

    Compared AFTER canonicalisation on purpose: the vocabulary layer snaps a
    typed value onto the spelling already on record, so comparing the raw input
    would queue a rewrite whose output is identical to what is already stored.
    """
    first = await _hat(client, artist_series="Piña")
    assert (await _row(db_session, first)).story_pending is False

    second = await _hat(client)
    await client.put(f"/api/hats/{second}", json={"artist_series": "Piña"})
    await client.put(f"/api/hats/{second}", json={"artist_series": "pina"})
    # The second PUT canonicalises back to the recorded spelling, so it is not
    # a change and must not queue.
    assert (await _row(db_session, second)).artist_series == "Piña"


# ------------------------------ owner notes ---------------------------- #


async def test_owner_notes_round_trip_and_are_never_touched_by_analysis(
    client, db_session, monkeypatch
):
    """The one field on a hat that no automated path may write.

    Everything else here is derived and gets rewritten by a refresh. If a
    refresh could clear this, the field would be a trap — you would lose what
    you typed and only find out later.
    """
    hat_id = await _hat(client)
    resp = await client.put(
        f"/api/hats/{hat_id}", json={"owner_notes": "Bought in Maui, first melin."}
    )
    assert resp.status_code == 200
    assert resp.json()["owner_notes"] == "Bought in Maui, first melin."

    # Run the story path over the hat the way an analysis would, with a writer
    # that succeeds — the notes must be untouched by it.
    from headroom.services import hat_story

    async def _writes(*_a, **_k):
        return "A rewritten write-up."

    monkeypatch.setattr("headroom.services.hat_story.write_story", _writes)
    row = await _row(db_session, hat_id)
    hat_story.apply_story(row, await _writes())
    await db_session.commit()

    fresh = await _row(db_session, hat_id)
    assert fresh.story == "A rewritten write-up."
    assert fresh.owner_notes == "Bought in Maui, first melin."


async def test_the_story_cannot_be_set_through_the_api(client):
    """`story` is derived, so a PUT that set it would be silently overwritten
    by the next refresh. Pydantic ignores the unknown field rather than
    erroring; what matters is that nothing is stored."""
    hat_id = await _hat(client)
    resp = await client.put(f"/api/hats/{hat_id}", json={"story": "I wrote this."})
    assert resp.status_code == 200
    assert resp.json()["story"] is None


async def test_hat_read_exposes_the_new_fields(client):
    hat_id = await _hat(client)
    body = (await client.get(f"/api/hats/{hat_id}")).json()
    for field in ("story", "story_generated_at", "story_pending", "owner_notes"):
        assert field in body, f"{field} missing from HatRead"


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
    row.story = "First paragraph.\n\nSecond paragraph."
    row.owner_notes = "Favourite one."
    await db_session.commit()

    zf = await _export(client)
    assert "index.html" in zf.namelist()
    page = zf.read("index.html").decode()
    assert "Melin Coronado" in page
    # The write-up is the reason this export beats a list of filenames.
    assert "First paragraph." in page and "Second paragraph." in page
    assert "Favourite one." in page


async def test_export_omits_prices_unless_asked(client, db_session):
    """This is the version you send a friend. The inventory report is the one
    with the money in it, and the share-link projection withholds prices for
    the same reason — so the default here must match."""
    hat_id = await _hat(client)
    row = await _row(db_session, hat_id)
    row.resale_price = 137.0
    await db_session.commit()

    assert "137" not in (await _export(client)).read("index.html").decode()
    assert "137" in (await _export(client, include_values="true")).read("index.html").decode()


async def test_export_excludes_disposed_hats_by_default(client, db_session):
    kept = await _hat(client)
    gone = await _hat(client)
    assert (await client.post(f"/api/hats/{gone}/dispose", json={"via": "sold"})).status_code == 200

    page = (await _export(client)).read("index.html").decode()
    assert f"#{kept}" in page or "Unidentified" in page
    assert "1 hats" in page or "1 hat" in page


async def test_export_survives_a_missing_photo_file(client, db_session):
    """A DB row pointing at a file that isn't there must cost that one photo,
    not the whole download — the export is most wanted when things are already
    a bit broken."""
    hat_id = await _hat(client)
    row = await _row(db_session, hat_id)
    row.thumb_path = "hats/thumbs/does-not-exist.webp"
    await db_session.commit()

    zf = await _export(client)
    assert "index.html" in zf.namelist()
    assert not [n for n in zf.namelist() if n.startswith("images/")]


async def test_export_names_images_by_hat_id_not_display_id(client, db_session):
    """An unassigned hat has no display id at all, and two hats can briefly
    share one mid-reshuffle — either would collide inside the zip."""
    from headroom.services.export_service import _image_name
    from headroom.models.hat import Hat

    hat = Hat(condition="new", size="classic", style="a_game", id=42)
    hat.thumb_path = "hats/thumbs/whatever.webp"
    assert _image_name(hat) == "42.webp"
    hat.thumb_path = None
    hat.photo_path = None
    assert _image_name(hat) is None
