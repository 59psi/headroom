"""Free-text fields must not accumulate five spellings of one thing.

`construction` and `artist_series` are deliberately open — melin ships
specialty fabrics and named collections whenever it likes. The cost of that
freedom is drift: "Neon" today, "NEON" next month, "neon" from the phone, and
one collection becomes three that never find each other in search.

Autocomplete alone only makes that less likely, because you can type past a
suggestion. Canonicalization on write is what makes it not happen.
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


async def test_a_differently_cased_collection_snaps_to_the_existing_spelling(client):
    """The headline case: Neon / NEON / neon must stay one collection."""
    first = await _add(client, artist_series="Neon")
    assert first["artist_series"] == "Neon"

    shouty = await _add(client, artist_series="NEON")
    quiet = await _add(client, artist_series="neon")

    assert shouty["artist_series"] == "Neon"
    assert quiet["artist_series"] == "Neon"

    options = (await client.get("/api/meta/collections")).json()
    assert options == ["Neon"], f"one collection expected, got {options}"


async def test_surrounding_and_doubled_whitespace_is_normalized(client):
    """Invisible in a picker, so it would be an undetectable duplicate."""
    await _add(client, artist_series="Skye Walker")
    padded = await _add(client, artist_series="  Skye   Walker ")

    assert padded["artist_series"] == "Skye Walker"
    assert (await client.get("/api/meta/collections")).json() == ["Skye Walker"]


async def test_a_genuinely_new_collection_is_kept_as_typed(client):
    """Canonicalizing must not mean guessing — an unseen name is the answer."""
    await _add(client, artist_series="Neon")
    fresh = await _add(client, artist_series="Deep Sea")

    assert fresh["artist_series"] == "Deep Sea"
    assert sorted((await client.get("/api/meta/collections")).json()) == ["Deep Sea", "Neon"]


async def test_accents_fold_together(client):
    """"Piña" and "Pina" are one collection typed with and without a
    long-press, not two drops."""
    await _add(client, artist_series="Piña")
    plain = await _add(client, artist_series="Pina")
    shouty = await _add(client, artist_series="PINA")

    assert plain["artist_series"] == "Piña"
    assert shouty["artist_series"] == "Piña"
    assert (await client.get("/api/meta/collections")).json() == ["Piña"]


async def test_the_accented_spelling_wins_even_when_it_arrives_second(client):
    """Adding an accent is deliberate; dropping one is what a phone keyboard
    does to you. So the accented form is the better guess at the real name,
    whichever order they were typed in."""
    await _add(client, artist_series="Pina")
    accented = await _add(client, artist_series="Piña")

    assert accented["artist_series"] == "Piña"


async def test_the_merge_pulls_unaccented_rows_across(client, db_session):
    """The write path keeps the better name; the merge moves the older rows
    onto it — otherwise the collection stays split until every hat is edited."""
    from headroom.models.hat import Hat
    from headroom.services import vocabulary

    for _ in range(3):
        await _add(client, artist_series="Pina")
    await _add(client, artist_series="Piña")

    await vocabulary.merge_case_variants(db_session, Hat.artist_series)

    assert (await client.get("/api/meta/collections")).json() == ["Piña"]


async def test_editing_canonicalizes_too(client):
    """The Edit form is where a value gets retyped from memory — the most
    likely place for a variant to enter."""
    await _add(client, artist_series="Neon")
    hat = await _add(client)

    edited = (
        await client.put(f"/api/hats/{hat['id']}", json={"artist_series": "nEoN"})
    ).json()

    assert edited["artist_series"] == "Neon"


async def test_construction_canonicalizes_on_the_same_rule(client):
    """Same treatment — it is the other free-text vocabulary field."""
    await _add(client, construction="Waxed Canvas")
    second = await _add(client, construction="waxed canvas")

    assert second["construction"] == "Waxed Canvas"
    options = (await client.get("/api/meta/constructions")).json()
    assert [o for o in options if o.casefold() == "waxed canvas"] == ["Waxed Canvas"]


async def test_curated_constructions_keep_their_canonical_casing(client):
    """Typing "hydrolite" must not create a rival spelling of a known build."""
    hat = await _add(client, construction="hydrolite")

    assert hat["construction"] == "HYDROLite"
    assert hat["hydrolite"] is True

    options = (await client.get("/api/meta/constructions")).json()
    assert len([o for o in options if o.casefold() == "hydrolite"]) == 1


async def test_collections_suggestions_exclude_hats_with_none(client):
    """Most hats have no collection; they must not become an empty suggestion."""
    await _add(client)
    await _add(client, artist_series="Neon")

    assert (await client.get("/api/meta/collections")).json() == ["Neon"]


async def test_existing_variants_are_merged_once(client, db_session):
    """Canonicalization only covers writes; this repairs what predates it."""
    from sqlalchemy import update as sa_update

    from headroom.models.hat import Hat
    from headroom.services import vocabulary

    a = await _add(client, artist_series="Neon")
    b = await _add(client, artist_series="Neon")
    c = await _add(client, artist_series="Neon")
    odd = await _add(client, artist_series="Neon")

    # Force variants past the write-time guard, as an import or an older
    # release would have left them.
    await db_session.execute(
        sa_update(Hat).where(Hat.id == odd["id"]).values(artist_series="NEON")
    )
    await db_session.execute(
        sa_update(Hat).where(Hat.id == c["id"]).values(artist_series="  neon ")
    )
    await db_session.commit()

    changed = await vocabulary.merge_case_variants(db_session, Hat.artist_series)

    assert changed == 2
    options = (await client.get("/api/meta/collections")).json()
    assert options == ["Neon"], f"variants survived the merge: {options}"

    # Idempotent — a second pass has nothing left to do.
    assert await vocabulary.merge_case_variants(db_session, Hat.artist_series) == 0
    assert a and b  # created, and untouched by the merge


async def test_the_merge_keeps_the_most_common_spelling(client, db_session):
    """A single early typo must not rename what everything else uses."""
    from sqlalchemy import update as sa_update

    from headroom.models.hat import Hat
    from headroom.services import vocabulary

    # All four first, so write-time canonicalization leaves them identical —
    # forcing the variant BEFORE the rest would make the later writes snap to
    # it, which is the guard doing its job rather than the case under test.
    hats = [await _add(client, artist_series="Deep Sea") for _ in range(4)]
    await db_session.execute(
        sa_update(Hat).where(Hat.id == hats[0]["id"]).values(artist_series="DEEP SEA")
    )
    await db_session.commit()

    await vocabulary.merge_case_variants(db_session, Hat.artist_series)

    assert (await client.get("/api/meta/collections")).json() == ["Deep Sea"]


async def test_the_merge_prefers_a_curated_spelling(client, db_session):
    """For constructions the curated list wins regardless of counts."""
    from sqlalchemy import update as sa_update

    from headroom.models.hat import Hat
    from headroom.schemas.hat import KNOWN_CONSTRUCTIONS
    from headroom.services import vocabulary

    hats = [await _add(client, construction="HYDROLite") for _ in range(3)]
    for h in hats:
        await db_session.execute(
            sa_update(Hat).where(Hat.id == h["id"]).values(construction="hydrolite")
        )
    await db_session.commit()

    await vocabulary.merge_case_variants(
        db_session, Hat.construction, known=KNOWN_CONSTRUCTIONS
    )

    options = (await client.get("/api/meta/constructions")).json()
    assert [o for o in options if o.casefold() == "hydrolite"] == ["HYDROLite"]
