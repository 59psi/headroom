"""A case number, once issued, is never issued again.

A case's display id is what its printed label and its NFC tag point at
(`/t/c/D-002`), and neither can be rewritten. Numbering by "highest number in
use, plus one" handed a retyped or deleted case's number to the next new case
of that type, so the old label went on scanning and opened a DIFFERENT case —
the silent wrong answer `tag_service` keys hat tags on an immutable id to
avoid. A stale label must find nothing instead.
"""

import pytest
from sqlalchemy import delete

from headroom.models.app_setting import AppSetting

pytestmark = pytest.mark.anyio


async def _create(client, case_type: str) -> str:
    resp = await client.post("/api/cases", json={"case_type": case_type})
    assert resp.status_code == 201, resp.text
    return resp.json()["display_id"]


async def test_a_retyped_cases_number_is_not_reissued(client):
    assert [await _create(client, "daily_wear") for _ in range(2)] == ["D-001", "D-002"]

    moved = await client.put("/api/cases/D-002", json={"case_type": "archive"})
    assert moved.status_code == 200, moved.text
    assert moved.json()["display_id"] == "A-001"

    assert await _create(client, "daily_wear") == "D-003"
    assert (await client.get("/api/cases/D-002")).status_code == 404, (
        "a label printed for D-002 opens a different case"
    )


async def test_a_deleted_cases_number_is_not_reissued(client):
    assert [await _create(client, "archive") for _ in range(2)] == ["A-001", "A-002"]

    assert (await client.delete("/api/cases/A-002")).status_code == 204

    assert await _create(client, "archive") == "A-003"
    assert (await client.get("/api/cases/A-002")).status_code == 404


async def test_retyping_back_does_not_return_the_old_number(client):
    """The Edit page warns BEFORE the save that the number cannot be had back
    by switching the type again — this is what makes that true."""
    await _create(client, "archive")
    await client.put("/api/cases/A-001", json={"case_type": "daily_wear"})

    back = await client.put("/api/cases/D-001", json={"case_type": "archive"})

    assert back.json()["display_id"] == "A-002"


async def test_a_case_from_before_the_record_is_protected_too(client, db_session):
    """Installs upgrading with cases already on the shelf have no record yet.
    A number is recorded when a case gives it up — by retype or delete — not
    when it is issued, so those cases are covered from their first edit on,
    not only the ones created after the upgrade."""
    for _ in range(3):
        await _create(client, "daily_wear")
    await db_session.execute(delete(AppSetting).where(AppSetting.key.like("case_seq_%")))
    await db_session.commit()

    await client.put("/api/cases/D-003", json={"case_type": "archive"})
    await client.delete("/api/cases/D-002")

    assert await _create(client, "daily_wear") == "D-004"
