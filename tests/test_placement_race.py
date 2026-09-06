"""Concurrent placement: capacity and positions under simultaneous writes.

`_validate_capacity` and `_get_next_position` are read-then-write with
nothing serializing them, and nothing in the schema forbids two active hats
at one position. Measured before the fix, on a file-backed database with each
request on its own connection: 10 concurrent assigns into an empty 3-hat case
landed FIVE hats (limit 4) at positions `[1, 1, 1, 1, 1]`; six concurrent
creates with a `case_id` were all accepted, five of them as `D-001-01`.
`display_id` is derived from case + position, so those are five hats with
one label — and the picker, the labels sheet and every tag read that label.

The app is single-process by design (CLAUDE.md), so an `asyncio.Lock` around
every placement writer is the right serialization, and a partial unique index
on `(case_id, position_in_case)` for active hats is the backstop that turns
any future gap into a loud failure instead of a quiet duplicate.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.anyio


async def _hat(client, **over) -> int:
    body = {"condition": "new", "size": "classic", "style": "a_game", **over}
    resp = await client.post("/api/hats", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_concurrent_assigns_cannot_overfill_a_case(file_client):
    case_id = (await file_client.post("/api/cases", json={"case_type": "archive"})).json()["id"]
    hats = [await _hat(file_client) for _ in range(10)]

    responses = await asyncio.gather(*[
        file_client.patch(f"/api/hats/{h}/assign", json={"case_id": case_id}) for h in hats
    ])
    codes = sorted(r.status_code for r in responses)

    # 3 nominal + 1 overfill allowance is the hard limit; everything else 409.
    assert codes.count(200) == 4, codes
    assert codes.count(409) == 6, codes
    placed = [r.json() for r in responses if r.status_code == 200]
    positions = sorted(h["position_in_case"] for h in placed)
    assert positions == [1, 2, 3, 4], positions
    labels = [h["display_id"] for h in placed]
    assert len(set(labels)) == 4, labels
    listing = (await file_client.get("/api/cases/A-001")).json()
    assert listing["hat_count"] == 4


async def test_concurrent_creates_into_a_case_get_distinct_positions(file_client):
    case_id = (await file_client.post("/api/cases", json={"case_type": "archive"})).json()["id"]

    responses = await asyncio.gather(*[
        file_client.post(
            "/api/hats",
            json={"condition": "new", "size": "classic", "style": "a_game", "case_id": case_id},
        )
        for _ in range(6)
    ])
    codes = sorted(r.status_code for r in responses)
    assert codes.count(201) == 4, codes
    assert codes.count(409) == 2, codes
    positions = sorted(r.json()["position_in_case"] for r in responses if r.status_code == 201)
    assert positions == [1, 2, 3, 4], positions


async def test_concurrent_case_creation_gets_distinct_display_ids(file_client):
    """`get_next_sequence` had the same read-then-write shape; the unique
    `display_id` made it fail loud (one row, five 500s) rather than silently.
    Serialized, six presses are six cases."""
    responses = await asyncio.gather(*[
        file_client.post("/api/cases", json={"case_type": "archive"}) for _ in range(6)
    ])
    codes = [r.status_code for r in responses]
    assert codes == [201] * 6, codes
    ids = sorted(r.json()["display_id"] for r in responses)
    assert ids == [f"A-00{i}" for i in range(1, 7)], ids


async def test_the_schema_forbids_two_active_hats_at_one_position(file_engine):
    """The backstop under the lock: whatever path forgets to serialize, the
    database refuses the duplicate. Disposed hats keep their old position and
    are excluded, since `undispose` re-slots them."""
    from sqlalchemy.exc import IntegrityError

    from headroom import database

    engine, factory = file_engine
    await database.init_db(bind=engine, session_factory=factory)
    async with factory() as db:
        await db.execute(text(
            "INSERT INTO cases (case_type, sequence_number, display_id, room_id) "
            "VALUES ('archive', 1, 'A-001', 1)"
        ))
        await db.execute(text(
            "INSERT INTO hats (case_id, position_in_case, condition, size, style, is_beanie, limited_edition, hydro, hydrolite) "
            "VALUES (1, 1, 'new', 'classic', 'a_game', 0, 0, 0, 0)"
        ))
        await db.commit()
        with pytest.raises(IntegrityError):
            await db.execute(text(
                "INSERT INTO hats (case_id, position_in_case, condition, size, style, is_beanie, limited_edition, hydro, hydrolite) "
                "VALUES (1, 1, 'new', 'classic', 'a_game', 0, 0, 0, 0)"
            ))
            await db.commit()
        await db.rollback()
        # A disposed hat at that position is history, not occupancy.
        await db.execute(text(
            "INSERT INTO hats (case_id, position_in_case, condition, size, style, is_beanie, limited_edition, hydro, hydrolite, disposed_at) "
            "VALUES (1, 1, 'new', 'classic', 'a_game', 0, 0, 0, 0, '2026-01-01 00:00:00')"
        ))
        await db.commit()


async def test_existing_duplicate_positions_are_repaired_before_the_index_lands(file_engine):
    """A database that already carries the race's fallout must still boot.

    `CREATE UNIQUE INDEX` on a table with duplicates fails, and a boot that
    fails on an upgraded database is the worst outcome available. So the
    migration renumbers the active hats of any case holding duplicates —
    by position then id, so the survivors' labels move as little as
    possible — and only then creates the index.
    """
    from headroom import database

    engine, factory = file_engine
    async with factory() as db:
        # A pre-2.79 database: the table exists, the index does not.
        await db.execute(text("DROP INDEX ux_hats_case_position"))
        await db.execute(text(
            "INSERT INTO cases (case_type, sequence_number, display_id, room_id) "
            "VALUES ('archive', 1, 'A-001', 1)"
        ))
        for _ in range(3):
            await db.execute(text(
                "INSERT INTO hats (case_id, position_in_case, condition, size, style, is_beanie, limited_edition, hydro, hydrolite) "
                "VALUES (1, 1, 'new', 'classic', 'a_game', 0, 0, 0, 0)"
            ))
        await db.execute(text(
            "INSERT INTO hats (case_id, position_in_case, condition, size, style, is_beanie, limited_edition, hydro, hydrolite) "
            "VALUES (1, 2, 'new', 'classic', 'a_game', 0, 0, 0, 0)"
        ))
        await db.commit()

    await database.init_db(bind=engine, session_factory=factory)

    async with factory() as db:
        rows = (await db.execute(text(
            "SELECT id, position_in_case FROM hats WHERE case_id = 1 ORDER BY position_in_case, id"
        ))).all()
    assert [p for _, p in rows] == [1, 2, 3, 4], rows
    # The hat that already sat alone at 2 keeps a low slot; the duplicates fan out.
    assert rows[0][0] == 1 and rows[0][1] == 1
