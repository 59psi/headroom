import pytest


async def _create_case(client, case_type="archive"):
    resp = await client.post("/api/cases", json={"case_type": case_type})
    return resp.json()


async def _create_hat(client, **overrides):
    data = {"condition": "new", "size": "classic", "style": "a_game"}
    data.update(overrides)
    return await client.post("/api/hats", json=data)


@pytest.mark.anyio
async def test_regular_hat_capacity_limit(client):
    case = await _create_case(client)
    for _ in range(4):
        resp = await _create_hat(client, case_id=case["id"])
        assert resp.status_code == 201

    # 5th regular hat should fail
    resp = await _create_hat(client, case_id=case["id"])
    assert resp.status_code == 409
    assert "regular hat capacity" in resp.json()["detail"]


@pytest.mark.anyio
async def test_beanie_capacity_limit(client):
    """Eight beanies to a case. They have no brim and squash flat, so far more
    fit in the same shell than the three the case is named for."""
    case = await _create_case(client)
    for i in range(8):
        resp = await _create_hat(client, case_id=case["id"], style="beanie")
        assert resp.status_code == 201, f"beanie {i + 1} of 8 was refused"

    full = (await client.get(f"/api/cases/{case['display_id']}")).json()
    assert full["free_beanie"] == 0
    assert full["overfull"] is False, "eight is full, not overfull"
    assert full["accepts_beanie"] is False, "eight is the measured maximum"

    # The 9th is refused. Beanies get NO overfill allowance: the regular one
    # exists because 3 is melin's NAME for the case and a 4th demonstrably
    # fits, so the number to be lenient about was never a measurement. 8 is
    # the opposite — it is what fits, counted by packing it — and adding slack
    # on top would assert a 9th fits, which nobody has claimed.
    resp = await _create_hat(client, case_id=case["id"], style="beanie")
    assert resp.status_code == 409
    assert "beanie capacity" in resp.json()["detail"]
    assert "(8)" in resp.json()["detail"], "the refusal must quote the real ceiling"


@pytest.mark.anyio
async def test_mixed_types_rejected(client):
    """A case cannot hold both regular hats and beanies."""
    case = await _create_case(client)
    resp = await _create_hat(client, case_id=case["id"], style="a_game")
    assert resp.status_code == 201

    # Adding a beanie to a case with regular hats should fail
    resp = await _create_hat(client, case_id=case["id"], style="beanie")
    assert resp.status_code == 409
    assert "cannot mix types" in resp.json()["detail"]


@pytest.mark.anyio
async def test_assign_rejects_wrong_type(client):
    """Cannot assign a beanie to a case that already has regular hats."""
    case = await _create_case(client)
    await _create_hat(client, case_id=case["id"], style="a_game")

    # Create unassigned beanie, try to assign to the regular-hat case
    resp = await _create_hat(client, style="beanie")
    beanie_id = resp.json()["id"]
    resp = await client.patch(
        f"/api/hats/{beanie_id}/assign", json={"case_id": case["id"]}
    )
    assert resp.status_code == 409
    assert "cannot mix types" in resp.json()["detail"]


@pytest.mark.anyio
async def test_assign_respects_capacity(client):
    case = await _create_case(client)
    for _ in range(4):
        await _create_hat(client, case_id=case["id"])

    # Create unassigned hat, try to assign
    resp = await _create_hat(client)
    hat_id = resp.json()["id"]
    resp = await client.patch(
        f"/api/hats/{hat_id}/assign", json={"case_id": case["id"]}
    )
    assert resp.status_code == 409


@pytest.mark.anyio
async def test_delete_case_unassigns_hats(client):
    case = await _create_case(client)
    resp = await _create_hat(client, case_id=case["id"])
    hat_id = resp.json()["id"]

    # Delete the case
    resp = await client.delete(f"/api/cases/{case['display_id']}")
    assert resp.status_code == 204

    # Hat should now be unassigned
    resp = await client.get(f"/api/hats/{hat_id}")
    assert resp.status_code == 200
    assert resp.json()["case_id"] is None
    assert resp.json()["display_id"] is None


# ------------------ full vs overfull (v2.20) --------------------------- #
#
# Three is full — the physical article is a three-hat case, and melin's own
# order lines call it a "3 Hat Travel Case". A fourth does fit, so it is
# allowed and reported as overfull rather than refused or passed off as normal.


@pytest.mark.anyio
async def test_default_case_is_full_at_three_and_overfull_at_four(client):
    case = await _create_case(client)

    for _ in range(3):
        assert (await _create_hat(client, case_id=case["id"])).status_code == 201

    full = (await client.get(f"/api/cases/{case['display_id']}")).json()
    assert full["nominal_capacity"] == 3
    assert full["free_regular"] == 0
    assert full["overfull"] is False
    assert full["accepts_regular"] is True, "the fourth is allowed"

    assert (await _create_hat(client, case_id=case["id"])).status_code == 201

    over = (await client.get(f"/api/cases/{case['display_id']}")).json()
    assert over["overfull"] is True
    assert over["hat_count"] == 4
    assert over["accepts_regular"] is False, "one over is the whole allowance"

    fifth = await _create_hat(client, case_id=case["id"])
    assert fifth.status_code == 409
    # The message quotes the ceiling enforced, not the nominal already passed.
    assert "(4)" in fifth.json()["detail"]


@pytest.mark.anyio
async def test_a_stated_capacity_gets_no_overfill_allowance(client):
    """`capacity` exists for "a case you don't want to cram" (USAGE §2).

    Quietly allowing one more than the stated number would defeat the only
    reason to set the field, so the allowance applies to the default only.
    """
    case = (await client.post(
        "/api/cases", json={"case_type": "archive", "capacity": 2}
    )).json()

    for _ in range(2):
        assert (await _create_hat(client, case_id=case["id"])).status_code == 201

    read = (await client.get(f"/api/cases/{case['display_id']}")).json()
    assert read["nominal_capacity"] == 2
    assert read["accepts_regular"] is False, "stated means stated"
    assert read["overfull"] is False

    refused = await _create_hat(client, case_id=case["id"])
    assert refused.status_code == 409
    assert "(2)" in refused.json()["detail"]


@pytest.mark.anyio
async def test_a_zero_capacity_case_accepts_nothing():
    """The allowance is slack on a real capacity, not a way into an empty one.

    Tested against the rule directly: the API pins `capacity` at ge=1, so a 0
    can only arrive from a direct DB edit or a future caller. The branch is
    defensive, which is exactly the kind that rots unwatched.
    """
    from headroom.services.capacity import evaluate

    room = evaluate(capacity=0, beanie_count=0, regular_count=0)
    assert room.accepts_regular is False
    assert room.accepts_beanie is False
    assert room.limit_regular == 0


@pytest.mark.anyio
async def test_the_api_refuses_a_zero_capacity(client):
    resp = await client.post("/api/cases", json={"case_type": "archive", "capacity": 0})
    assert resp.status_code == 422
