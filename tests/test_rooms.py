import pytest


@pytest.mark.anyio
async def test_default_room_exists(client):
    resp = await client.get("/api/rooms")
    assert resp.status_code == 200
    rooms = resp.json()
    assert len(rooms) >= 1
    default = next(r for r in rooms if r["id"] == 1)
    assert default["name"] == "Default Room"


@pytest.mark.anyio
async def test_create_room(client):
    resp = await client.post("/api/rooms", json={"name": "Bedroom"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Bedroom"
    assert data["case_count"] == 0


@pytest.mark.anyio
async def test_rename_room(client):
    resp = await client.post("/api/rooms", json={"name": "Old Name"})
    room_id = resp.json()["id"]

    resp = await client.put(f"/api/rooms/{room_id}", json={"name": "New Name"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "New Name"


@pytest.mark.anyio
async def test_delete_room_reassigns(client):
    # Create a room and a case in it
    resp = await client.post("/api/rooms", json={"name": "Temp Room"})
    room_id = resp.json()["id"]

    resp = await client.post("/api/cases", json={"case_type": "archive", "room_id": room_id})
    assert resp.status_code == 201
    case_display_id = resp.json()["display_id"]

    # Delete the room
    resp = await client.delete(f"/api/rooms/{room_id}")
    assert resp.status_code == 204

    # Case should now be in default room
    resp = await client.get(f"/api/cases/{case_display_id}")
    assert resp.json()["room_id"] == 1


@pytest.mark.anyio
async def test_cannot_delete_default_room(client):
    resp = await client.delete("/api/rooms/1")
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_exactly_one_room_is_default(client):
    """The flag is the invariant the fallback logic depends on — zero flagged
    rooms breaks case creation, two makes the reassignment target ambiguous."""
    await client.post("/api/rooms", json={"name": "Garage"})
    rooms = (await client.get("/api/rooms")).json()
    assert [r["is_default"] for r in rooms].count(True) == 1
    assert next(r for r in rooms if r["is_default"])["id"] == 1


@pytest.mark.anyio
async def test_default_can_be_reassigned_and_old_default_deleted(client):
    """The whole point of the flag: the original default stops being special
    once another room takes the role, so it can finally be deleted."""
    garage = (await client.post("/api/rooms", json={"name": "Garage"})).json()

    # Blocked while room 1 still holds the flag.
    assert (await client.delete("/api/rooms/1")).status_code == 400

    resp = await client.post(f"/api/rooms/{garage['id']}/default")
    assert resp.status_code == 200
    assert resp.json()["is_default"] is True

    # Flag moved, so it is now the *new* default that is protected...
    assert (await client.delete(f"/api/rooms/{garage['id']}")).status_code == 400
    # ...and the original is deletable.
    assert (await client.delete("/api/rooms/1")).status_code == 204

    rooms = (await client.get("/api/rooms")).json()
    assert [r["id"] for r in rooms] == [garage["id"]]
    assert rooms[0]["is_default"] is True


@pytest.mark.anyio
async def test_cases_follow_the_current_default_not_id_1(client):
    """Both the reassignment target and the new-case default must resolve from
    the flag. Hardcoding 1 would send cases to a room that no longer exists."""
    garage = (await client.post("/api/rooms", json={"name": "Garage"})).json()
    await client.post(f"/api/rooms/{garage['id']}/default")

    # New case with no room named → lands in the current default, not room 1.
    case = (await client.post("/api/cases", json={"case_type": "archive"})).json()
    assert case["room_id"] == garage["id"]

    # A deleted room's cases reassign to the current default too.
    temp = (await client.post("/api/rooms", json={"name": "Temp"})).json()
    orphan = (await client.post(
        "/api/cases", json={"case_type": "daily_wear", "room_id": temp["id"]}
    )).json()
    assert (await client.delete(f"/api/rooms/{temp['id']}")).status_code == 204

    moved = (await client.get(f"/api/cases/{orphan['display_id']}")).json()
    assert moved["room_id"] == garage["id"]


@pytest.mark.anyio
async def test_get_room_by_id(client):
    resp = await client.get("/api/rooms/1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == 1
    assert data["name"] == "Default Room"


@pytest.mark.anyio
async def test_get_room_not_found(client):
    resp = await client.get("/api/rooms/9999")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_rooms_meta_endpoint(client):
    resp = await client.get("/api/meta/rooms")
    assert resp.status_code == 200
    data = resp.json()
    assert any(r["label"] == "Default Room" for r in data)


@pytest.mark.anyio
async def test_room_case_count_is_accurate(client):
    """`case_count` comes from a SQL COUNT now, not `len(room.cases)`.

    Regression guard for the swap: a wrong join or a lost GROUP BY would report
    zero for a room that plainly has cases, which is indistinguishable from the
    room genuinely being empty.
    """
    bedroom = await client.post("/api/rooms", json={"name": "Bedroom"})
    bedroom_id = bedroom.json()["id"]
    office = await client.post("/api/rooms", json={"name": "Office"})
    office_id = office.json()["id"]

    for _ in range(6):
        r = await client.post(
            "/api/cases", json={"case_type": "archive", "room_id": bedroom_id}
        )
        assert r.status_code == 201
    await client.post("/api/cases", json={"case_type": "daily_wear", "room_id": office_id})

    rooms = {r["name"]: r["case_count"] for r in (await client.get("/api/rooms")).json()}
    assert rooms["Bedroom"] == 6, f"Bedroom should hold 6 cases, got {rooms['Bedroom']}"
    assert rooms["Office"] == 1
    # A room with no cases must still appear, at zero — that's the outer join.
    empty = await client.post("/api/rooms", json={"name": "Attic"})
    assert empty.json()["id"]
    rooms2 = {r["name"]: r["case_count"] for r in (await client.get("/api/rooms")).json()}
    assert rooms2["Attic"] == 0
    assert rooms2["Bedroom"] == 6


@pytest.mark.anyio
async def test_creating_a_case_in_a_missing_room_is_rejected(client):
    """Nothing at the DB level stops an orphan — no `PRAGMA foreign_keys`.

    An unknown `room_id` used to be written straight through, and the symptoms
    never named the cause: the case reported its room as "Unknown", while the
    room it should have been in reported zero cases.
    """
    resp = await client.post("/api/cases", json={"case_type": "archive", "room_id": 99999})
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_boot_reattaches_cases_whose_room_vanished(client, monkeypatch):
    """Existing orphans are repaired on the next start, not left to be found.

    The frontend used to send a hardcoded `room_id: 1` regardless of the picker,
    so deleting the room that happened to be id 1 — which the `is_default` flag
    exists to permit — orphaned every case created afterwards.
    """
    from sqlalchemy import text

    import headroom.database as database
    from tests.conftest import test_session_factory

    # The repair runs on the boot path and uses the app's session factory;
    # point it at the test database.
    monkeypatch.setattr(database, "async_session", test_session_factory)

    room = await client.post("/api/rooms", json={"name": "Doomed"})
    room_id = room.json()["id"]
    case = await client.post("/api/cases", json={"case_type": "archive", "room_id": room_id})
    display_id = case.json()["display_id"]

    # Point the case at a room that does not exist, exactly as the old client did.
    async with test_session_factory() as db:
        await db.execute(text(f"UPDATE cases SET room_id = 99999 WHERE display_id = '{display_id}'"))
        await db.commit()

    detail = await client.get(f"/api/cases/{display_id}")
    assert detail.json()["room_name"] == "Unknown", "precondition: the case is orphaned"

    await database.reattach_orphaned_cases()

    repaired = await client.get(f"/api/cases/{display_id}")
    assert repaired.json()["room_name"] != "Unknown"
    # And it now counts towards the room that adopted it.
    rooms = {r["name"]: r["case_count"] for r in (await client.get("/api/rooms")).json()}
    assert sum(rooms.values()) >= 1
