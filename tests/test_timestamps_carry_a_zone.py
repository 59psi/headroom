"""Every timestamp on the wire carries its offset.

SQLite stores no zone; the columns came back naive; pydantic serialized
them as `2026-09-06T16:32:27` and the browser read that as local time —
seven hours out on the real deployment, "just now" for the first seven hours
of every run. `database.UtcDateTime` is the fix; this walks the responses
that showed the symptom and checks the string itself, because the symptom
was invisible to every test that compared `datetime` objects.
"""

from __future__ import annotations

import re

import pytest

pytestmark = pytest.mark.anyio

WITH_OFFSET = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")


async def test_hat_and_activity_timestamps_are_zoned(client):
    hat = (await client.post(
        "/api/hats", json={"condition": "new", "size": "classic", "style": "a_game"}
    )).json()
    assert WITH_OFFSET.match(hat["created_at"]), hat["created_at"]
    assert WITH_OFFSET.match(hat["updated_at"]), hat["updated_at"]

    await client.post(f"/api/hats/{hat['id']}/dispose", json={"via": "gifted"})
    disposed = (await client.get(f"/api/hats/{hat['id']}")).json()
    assert WITH_OFFSET.match(disposed["disposed_at"]), disposed["disposed_at"]

    rows = (await client.get("/api/admin/activity-log?limit=5")).json()
    assert rows, "the dispose wrote an audit row"
    assert all(WITH_OFFSET.match(r["occurred_at"]) for r in rows), rows[0]["occurred_at"]


async def test_loaded_timestamps_are_utc_aware(db_session):
    from datetime import datetime, timezone

    from sqlalchemy import select

    from headroom.models.room import Room

    room = (await db_session.execute(select(Room))).scalars().first()
    assert room.created_at.tzinfo is not None
    assert room.created_at.utcoffset().total_seconds() == 0
    # A value bound from another zone is stored as UTC and read back as UTC.
    from datetime import timedelta

    pacific = timezone(timedelta(hours=-7))
    room.updated_at = datetime(2026, 9, 6, 9, 30, tzinfo=pacific)
    await db_session.commit()
    db_session.expire_all()
    room = (await db_session.execute(select(Room))).scalars().first()
    assert room.updated_at == datetime(2026, 9, 6, 16, 30, tzinfo=timezone.utc)
