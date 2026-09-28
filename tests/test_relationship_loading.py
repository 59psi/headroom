"""What loading one row pulls in with it — counted, not assumed.

`Room.cases` and `Case.hats` were `lazy="selectin"` at the mapper, so every
Room load chained into its cases, their hats, and each hat's colors and wear
log. `list_rooms` swapped its explicit `selectinload` for a COUNT in 2.7.0 and
its docstring promised "without loading the cases" — and it still loaded the
whole collection, because the mapper default did the loading. These tests
count what is in the session's identity map after each read, which is the
only honest measure of what a query loaded.

They also pin the four back-references that used to default to
`lazy="select"` — a `MissingGreenlet` on first touch under AsyncSession — to
`lazy="raise"`, and prove the delete cascades still run through them.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import func, inspect, select
from sqlalchemy.exc import InvalidRequestError

from headroom.models.case import Case
from headroom.models.hat import Hat
from headroom.models.hat_color import HatColor
from headroom.models.import_job import ImportJob, ImportJobItem
from headroom.models.room import Room
from headroom.models.user import AuthSession, PasskeyCredential, User
from headroom.models.wear_log import WearLog
from headroom.services import room_service
from tests import conftest

pytestmark = pytest.mark.anyio


def _loaded(db) -> Counter:
    return Counter(type(obj).__name__ for obj in db.identity_map.values())


async def _seed_shelf(cases: int = 3, hats_per_case: int = 3) -> dict:
    """Room 1 with `cases` cases of hats (colors and wears each), plus one
    loose hat on the shelf. Returns the ids the tests need."""
    async with conftest.test_session_factory() as db:
        case_ids, cased_hat_ids = [], []
        for n in range(1, cases + 1):
            case = Case(case_type="archive", sequence_number=n, display_id=f"A-{n:03d}", room_id=1)
            db.add(case)
            await db.flush()
            case_ids.append(case.id)
            for pos in range(1, hats_per_case + 1):
                hat = Hat(
                    case_id=case.id, position_in_case=pos, condition="new",
                    size="classic", style="a_game",
                )
                db.add(hat)
                await db.flush()
                cased_hat_ids.append(hat.id)
                db.add_all([
                    HatColor(hat_id=hat.id, color_name="Navy", general_color="Navy",
                             hex_value="#000080", dominance_rank=1),
                    WearLog(hat_id=hat.id, worn_at=date(2026, 1, 1)),
                    WearLog(hat_id=hat.id, worn_at=date(2026, 1, 2)),
                ])
        loose = Hat(direct_room_id=1, condition="new", size="classic", style="odysea")
        db.add(loose)
        await db.commit()
        return {"case_ids": case_ids, "cased": cased_hat_ids, "loose": loose.id}


async def test_listing_rooms_loads_rooms_and_nothing_else():
    await _seed_shelf()
    async with conftest.test_session_factory() as db:
        rows = await room_service.list_rooms(db)
        loaded = _loaded(db)
    assert [n for _, n in rows] == [3]
    assert set(loaded) == {"Room"}, f"list_rooms loaded {dict(loaded)} to count cases"


async def test_reading_a_loose_hat_does_not_load_its_rooms_shelf():
    """`Hat.direct_room -> Room.cases` was the whole room, from one hat."""
    ids = await _seed_shelf()
    async with conftest.test_session_factory() as db:
        hat = await db.get(Hat, ids["loose"])
        assert hat.room_name == "Default Room"
        loaded = _loaded(db)
    assert loaded["Case"] == 0, dict(loaded)
    assert loaded["Hat"] == 1, dict(loaded)


async def test_reading_a_room_loads_the_room_and_counts_in_sql():
    """`get_room` loaded a room's cases (and, while `Case.hats` was selectin,
    every hat on the shelf and its colors) that no caller read: `RoomRead`'s
    counts come from `room_counts`, in SQL. Now it loads the row alone."""
    await _seed_shelf()
    async with conftest.test_session_factory() as db:
        room = await room_service.get_room(db, 1)
        loaded = _loaded(db)
        counts = await room_service.room_counts(db, room.id)
    assert set(loaded) == {"Room"}, f"get_room loaded {dict(loaded)}"
    assert counts == (3, 1)


async def test_reading_a_case_does_not_load_the_hats_in_it():
    """`Case.hats` was selectin, so every load of a CASE carried every hat in
    it — disposed ones included — and each hat's colors. The capacity check
    reads a case by id for one column (`capacity`), and paid for the shelf.

    Read the case itself: a cased HAT never showed the cost, because
    SQLAlchemy stops a default eager chain at the first mapper it revisits
    (Hat -> Case -> Hat is a cycle), so a test that loads a hat passes with
    `Case.hats` selectin or not."""
    ids = await _seed_shelf()
    async with conftest.test_session_factory() as db:
        case = await db.get(Case, ids["case_ids"][0])
        assert case.display_id == "A-001"
        loaded = _loaded(db)
    assert loaded["Hat"] == 0, dict(loaded)
    assert loaded["HatColor"] == 0, dict(loaded)


async def test_a_hat_list_counts_wears_without_loading_them():
    """`wear_count` was `len(self.wear_logs)`: every wear row of every hat in
    a list, loaded to produce one integer per hat."""
    await _seed_shelf()
    async with conftest.test_session_factory() as db:
        hats = (await db.execute(select(Hat).where(Hat.case_id.is_not(None)))).scalars().all()
        counts = {h.wear_count for h in hats}
        loaded = _loaded(db)
    assert counts == {2}
    assert loaded["WearLog"] == 0, dict(loaded)


async def test_wear_count_follows_the_log(client):
    """The count is the database's, so it moves with the rows."""
    hat = (await client.post(
        "/api/hats", json={"condition": "new", "size": "classic", "style": "a_game"}
    )).json()
    assert hat["wear_count"] == 0
    async with conftest.test_session_factory() as db:
        db.add(WearLog(hat_id=hat["id"], worn_at=date(2026, 3, 1)))
        await db.commit()
    assert (await client.get(f"/api/hats/{hat['id']}")).json()["wear_count"] == 1


@pytest.mark.parametrize(
    ("model", "name"),
    [
        (Room, "cases"),
        (Case, "hats"),
        (Hat, "wear_logs"),
        (User, "sessions"),
        (User, "passkeys"),
        (HatColor, "hat"),
        (ImportJobItem, "job"),
    ],
)
async def test_collections_nothing_reads_implicitly_raise(model, name):
    """Loaded on request (`selectinload`) or not at all. The default,
    "select", is not a quiet fallback under AsyncSession — it is a
    `MissingGreenlet` at the access; "raise" fails at the same place and
    names the relationship."""
    assert inspect(model).relationships[name].lazy == "raise"


async def test_touching_an_unloaded_relationship_names_it():
    async with conftest.test_session_factory() as db:
        user = User(username="u", password_hash="x", api_token="t")
        db.add(user)
        await db.commit()
    async with conftest.test_session_factory() as db:
        user = await db.get(User, user.id)
        with pytest.raises(InvalidRequestError, match="lazy='raise'"):
            _ = user.passkeys


async def test_deleting_a_user_still_cascades_through_raise_collections():
    """"raise" governs attribute access; the unit of work loads the collection
    itself when a delete has to cascade."""
    async with conftest.test_session_factory() as db:
        user = User(username="gone", password_hash="x", api_token="tok")
        db.add(user)
        await db.flush()
        db.add_all([
            AuthSession(id="s1", user_id=user.id,
                        expires_at=datetime.now(timezone.utc) + timedelta(days=1)),
            PasskeyCredential(user_id=user.id, credential_id="c1", public_key="k"),
        ])
        await db.commit()
        uid = user.id
    async with conftest.test_session_factory() as db:
        await db.delete(await db.get(User, uid))
        await db.commit()
        sessions = (await db.execute(select(func.count(AuthSession.id)))).scalar()
        passkeys = (await db.execute(select(func.count(PasskeyCredential.id)))).scalar()
    assert (sessions, passkeys) == (0, 0)


async def test_deleting_a_hat_still_takes_its_colors_and_wears():
    ids = await _seed_shelf(cases=1, hats_per_case=1)
    async with conftest.test_session_factory() as db:
        await db.delete(await db.get(Hat, ids["cased"][0]))
        await db.commit()
        colors = (await db.execute(select(func.count(HatColor.id)))).scalar()
        wears = (await db.execute(select(func.count(WearLog.id)))).scalar()
    assert (colors, wears) == (0, 0)


async def test_deleting_an_import_job_still_takes_its_items():
    async with conftest.test_session_factory() as db:
        job = ImportJob(total=1)
        db.add(job)
        await db.flush()
        db.add(ImportJobItem(job_id=job.id, filename="a.jpg"))
        await db.commit()
        job_id = job.id
    async with conftest.test_session_factory() as db:
        job = (await db.execute(select(ImportJob).where(ImportJob.id == job_id))).scalar_one()
        await db.delete(job)
        await db.commit()
        items = (await db.execute(select(func.count(ImportJobItem.id)))).scalar()
    assert items == 0


async def test_a_case_without_a_room_is_refused_not_filed_in_room_one():
    """`room_id` defaulted to 1 — the hardcoded room `is_default` replaced, and
    one that may have been deleted. Forgetting the room is an error now, on
    every install: an upgraded database's column is nullable, so the schema
    alone would let it through."""
    async with conftest.test_session_factory() as db:
        db.add(Case(case_type="archive", sequence_number=1, display_id="A-001"))
        with pytest.raises(ValueError, match="no room_id"):
            await db.flush()


async def test_naming_the_room_by_relationship_satisfies_the_guard():
    async with conftest.test_session_factory() as db:
        room = await db.get(Room, 1)
        db.add(Case(case_type="archive", sequence_number=1, display_id="A-001", room=room))
        await db.commit()
        case = (await db.execute(select(Case))).scalar_one()
    assert case.room_id == 1
