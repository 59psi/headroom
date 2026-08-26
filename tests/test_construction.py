"""Construction: structured suggestions over a free-form field.

melin ships specialty fabrics in seasonal and collab drops, so the old
two-boolean model could not record a hat whose tag said anything except HYDRO
or HYDROLite. This covers the replacement — free text, with `hydro`/`hydrolite`
derived from it so the search filters that query those columns keep working —
and the back-compat path for clients still sending the booleans.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.anyio


async def _add(client, **over) -> dict:
    body = {"condition": "new", "size": "classic", "style": "trenches"}
    body.update(over)
    resp = await client.post("/api/hats", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_specialty_fabric_survives_the_round_trip(client):
    """The whole point: a fabric that is on no list can still be recorded."""
    hat = await _add(client, construction="Waxed Canvas")

    assert hat["construction"] == "Waxed Canvas"
    # Not one of the two known builds, so neither flag is set — a hat that is
    # not HYDRO must not match a HYDRO filter.
    assert hat["hydro"] is False and hat["hydrolite"] is False

    fetched = (await client.get(f"/api/hats/{hat['id']}")).json()
    assert fetched["construction"] == "Waxed Canvas"


async def test_known_constructions_still_set_their_flags(client):
    """The derived columns are what search queries, so they must track the text."""
    lite = await _add(client, construction="HYDROLite")
    assert lite["hydrolite"] is True and lite["hydro"] is False

    # Product-name phrasing, not the bare word — this is how people type it.
    hydro = await _add(client, construction="A-Game Hydro")
    assert hydro["hydro"] is True and hydro["hydrolite"] is False


async def test_editing_construction_re_derives_the_flags(client):
    """A correction has to move the flags too, or search silently disagrees."""
    hat = await _add(client, construction="HYDROLite")
    assert hat["hydrolite"] is True

    edited = (
        await client.put(f"/api/hats/{hat['id']}", json={"construction": "Corduroy"})
    ).json()
    assert edited["construction"] == "Corduroy"
    assert edited["hydrolite"] is False, "a stale flag would still match a HYDROLite filter"


async def test_unrelated_edit_leaves_construction_alone(client):
    """`exclude_unset` regression guard.

    An earlier cut of this folded the legacy flags into `construction`
    unconditionally, which marked the field as set on every request — so a PUT
    changing only the brand silently blanked the construction.
    """
    hat = await _add(client, construction="Thermal")

    edited = (
        await client.put(f"/api/hats/{hat['id']}", json={"brand": "melin"})
    ).json()
    assert edited["construction"] == "Thermal"
    assert edited["brand"] == "melin"


async def test_legacy_boolean_clients_keep_working(client):
    """Pre-2.11 clients (the documented iOS Shortcut) send flags, not text."""
    hat = await _add(client, hydro=True)
    assert hat["construction"] == "HYDRO", "the flag must fold into the field"
    assert hat["hydro"] is True


async def test_legacy_flag_clears_only_its_own_construction(client):
    """`{"hydrolite": false}` means "not HYDROLite", not "no construction".

    Resolved in the service rather than the schema precisely so the hat's
    current state is in hand: a HYDRO hat told "hydrolite: false" must stay
    HYDRO.
    """
    hat = await _add(client, construction="HYDRO")

    still_hydro = (
        await client.put(f"/api/hats/{hat['id']}", json={"hydrolite": False})
    ).json()
    assert still_hydro["construction"] == "HYDRO"
    assert still_hydro["hydro"] is True

    # Turning off the flag the hat actually has does clear it.
    cleared = (
        await client.put(f"/api/hats/{hat['id']}", json={"hydro": False})
    ).json()
    assert cleared["construction"] is None
    assert cleared["hydro"] is False


async def test_a_legacy_flag_cannot_wipe_a_fabric_it_cannot_express(client):
    """The old vocabulary must not silently overwrite the richer one.

    A hat recorded as "Waxed Canvas" already has both booleans false. A
    pre-2.11 client sending `hydro: false` is restating a default, not saying
    anything about the canvas — so treating it as "clear the field" destroyed a
    value that client had no way of knowing existed. Reachable from the
    documented iOS Shortcut.
    """
    hat = await _add(client, construction="Waxed Canvas")

    after = (await client.put(f"/api/hats/{hat['id']}", json={"hydro": False})).json()

    assert after["construction"] == "Waxed Canvas"


async def test_blank_construction_is_not_stated(client):
    """An untouched form field must not look like an answer."""
    hat = await _add(client, construction="   ")
    assert hat["construction"] is None


async def test_suggestions_merge_the_curated_list_with_what_is_in_use(client):
    """A fabric typed once becomes a suggestion, which is what stops five
    spellings of the same material accumulating."""
    await _add(client, construction="Waxed Canvas")

    options = (await client.get("/api/meta/constructions")).json()

    assert options[0] == "HYDRO", "curated entries lead — they are the common answers"
    assert "HYDROLite" in options
    assert "Waxed Canvas" in options, "a value in use must become a suggestion"
    # No duplicates, however the casing arrived.
    assert len(options) == len({o.casefold() for o in options})


async def test_suggestions_do_not_duplicate_a_curated_value(client):
    """Typing "hydro" in lowercase must not create a second HYDRO entry."""
    await _add(client, construction="hydro")

    options = (await client.get("/api/meta/constructions")).json()

    assert [o for o in options if o.casefold() == "hydro"] == ["HYDRO"]


async def test_a_specialty_fabric_is_searchable_by_name(client):
    """Findable by the fabric, or recording it was pointless.

    The two booleans could only ever be matched by the two hard-coded terms, so
    before this the only way to find a Waxed Canvas hat was to remember which
    one it was.
    """
    hat = await _add(client, construction="Waxed Canvas")

    found = (await client.get("/api/search?q=canvas")).json()

    assert [h["id"] for h in found] == [hat["id"]]


async def test_hydro_search_matches_the_family_but_hydrolite_stays_precise(client):
    """Searching the text widened `hydro` on purpose; `hydrolite` stays exact.

    `hydro` now also returns HYDROLite hats, because "HYDROLite" contains
    "hydro" and the field is free text — substring matching is what text search
    does, and HYDROLite is a HYDRO-family build, so the wider result is the
    useful one. The narrower direction is the one that would be wrong: asking
    for `hydrolite` must NOT return every plain HYDRO hat, since those are a
    different (cheaper, heavier) product.
    """
    hydro = await _add(client, construction="A-Game Hydro")
    lite = await _add(client, construction="HYDROLite")

    hydro_hits = {h["id"] for h in (await client.get("/api/search?q=hydro")).json()}
    lite_hits = {h["id"] for h in (await client.get("/api/search?q=hydrolite")).json()}

    assert hydro["id"] in hydro_hits
    assert lite["id"] in hydro_hits, "HYDROLite is a HYDRO-family build"
    assert lite_hits == {lite["id"]}, "hydrolite must not match plain HYDRO hats"


async def test_collection_can_be_set_when_adding(client):
    """The owner knows the collection while holding the box; the analyzer
    cannot see it in a photo of the hat. Withholding this until the Edit form
    meant typing it twice or hoping Claude guessed."""
    hat = await _add(client, artist_series="Piña", model_name="Trenches")

    assert hat["artist_series"] == "Piña"
    assert hat["model_name"] == "Trenches"


async def test_denim_is_offered_as_a_material(client):
    """Curated materials are suggested before any hat uses one.

    `GET /api/meta/constructions` merges the curated list with whatever is
    already on record, so a new entry has to show up on an empty collection —
    that is the whole reason the curated half exists.
    """
    options = (await client.get("/api/meta/constructions")).json()

    assert "Denim" in options


async def test_denim_canonicalizes_to_the_curated_spelling(client):
    """Typed casing must snap to the list, or the field splits in two.

    The curated vocabulary is checked FIRST for exactly this: without it,
    "denim" typed into an empty database would store that spelling and sit
    permanently at odds with the "Denim" the picker offers.
    """
    hat = await _add(client, construction="denim")

    assert hat["construction"] == "Denim"
    # A material is not a melin technical line, so the derived flags stay off —
    # a stale flag here would match a HYDRO filter.
    assert hat["hydro"] is False
    assert hat["hydrolite"] is False
