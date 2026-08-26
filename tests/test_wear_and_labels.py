"""Wear tracking + QR case-label sheet."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.anyio


async def _hat(client, **fields):
    resp = await client.post(
        "/api/hats", json={"condition": "new", "size": "classic", "style": "a_game", **fields}
    )
    return resp.json()["id"]


async def test_wear_log_and_undo(client):
    from datetime import datetime, timezone

    hat_id = await _hat(client)

    resp = await client.post(f"/api/hats/{hat_id}/wear", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["wear_count"] == 1
    # Records *today* (server clock, UTC) — assert the real date, not merely
    # "not None", which a stuck/epoch value would also satisfy.
    today = datetime.now(timezone.utc).date().isoformat()
    assert body["date_last_worn"] == today

    # Same-day double tap is idempotent
    resp = await client.post(f"/api/hats/{hat_id}/wear", json={})
    assert resp.json()["wear_count"] == 1

    # Backdated wear counts separately; date_last_worn stays at the max — today,
    # not the older backdated day.
    resp = await client.post(f"/api/hats/{hat_id}/wear", json={"worn_at": "2024-01-05"})
    body = resp.json()
    assert body["wear_count"] == 2
    assert body["date_last_worn"] == today

    # Undo removes the most recent (today), leaving the backdated one
    resp = await client.delete(f"/api/hats/{hat_id}/wear/latest")
    body = resp.json()
    assert body["wear_count"] == 1
    assert body["date_last_worn"] == "2024-01-05"


async def test_wear_rejected_for_disposed(client):
    hat_id = await _hat(client)
    await client.post(f"/api/hats/{hat_id}/dispose", json={"via": "sold"})
    resp = await client.post(f"/api/hats/{hat_id}/wear", json={})
    assert resp.status_code == 409


async def test_case_labels_sheet(client, anon_client):
    await client.post("/api/cases", json={"case_type": "archive", "capacity": 3})
    resp = await client.get("/api/admin/case-labels")
    assert resp.status_code == 200
    html = resp.text
    assert "<svg" in html and "A-001" in html and "0/3 hats" in html
    # Auth-gated like the rest of /api
    assert (await anon_client.get("/api/admin/case-labels")).status_code == 401


# --------------------------- Case label occupancy --------------------------- #


async def test_case_label_shows_nominal_capacity_not_the_overfill_limit(client):
    """A full 3-hat case must read "3/3", not "3/4".

    The sheet used to compute its own capacity as `c.capacity or (6 if beanie
    else 4)`. 4 is the OVERFILL limit — the hard ceiling a write is refused
    above — not the number at which a case is full, so a case with no room left
    printed as having one slot spare. `capacity.evaluate` owns that distinction
    (`max_regular` vs `limit_regular`) and the sheet now asks it, rather than
    keeping a third copy of a rule the module exists to centralize.
    """
    case = (await client.post("/api/cases", json={"case_type": "archive"})).json()
    for _ in range(3):
        await _hat(client, case_id=case["id"])

    html = (await client.get("/api/admin/case-labels")).text
    assert "3/3 hats" in html
    assert "3/4 hats" not in html


async def test_case_label_ignores_disposed_hats(client):
    """A disposed hat frees its slot, so it must not count against the case."""
    case = (await client.post("/api/cases", json={"case_type": "archive"})).json()
    keep = await _hat(client, case_id=case["id"])
    gone = await _hat(client, case_id=case["id"])
    await client.post(f"/api/hats/{gone}/dispose", json={"via": "sold"})

    html = (await client.get("/api/admin/case-labels")).text
    assert "1/3 hats" in html, "a disposed hat was still occupying its slot"
    assert keep  # the surviving hat is the one being counted


async def test_case_label_uses_a_stated_capacity(client):
    """A per-case override is exact and gets no overfill latitude."""
    await client.post("/api/cases", json={"case_type": "archive", "capacity": 2})
    html = (await client.get("/api/admin/case-labels")).text
    assert "0/2 hats" in html


# ------------------------------- Hat labels -------------------------------- #


async def test_hat_labels_sheet(client, anon_client):
    case = (await client.post("/api/cases", json={"case_type": "archive"})).json()
    hat_id = await _hat(client, case_id=case["id"], model_name="Coronado")

    resp = await client.get("/api/admin/hat-labels")
    assert resp.status_code == 200
    html = resp.text
    assert "<svg" in html
    assert "Coronado" in html
    # The tag URL is printed as text so it can be pasted into an NFC writer.
    assert f"/t/h/{hat_id}" in html
    assert (await anon_client.get("/api/admin/hat-labels")).status_code == 401


async def test_hat_label_url_survives_the_hat_changing_case(client):
    """The whole reason a hat tag keys on `id` rather than `display_id`.

    A display id is derived from case + position, so it changes whenever a hat
    is reshuffled — and a sticker cannot be rewritten. Keying on it would leave
    a label that still scans and still resolves, silently, to a different hat.
    """
    a = (await client.post("/api/cases", json={"case_type": "archive"})).json()
    b = (await client.post("/api/cases", json={"case_type": "daily_wear"})).json()
    hat_id = await _hat(client, case_id=a["id"])

    before = (await client.get(f"/api/hats/{hat_id}")).json()["display_id"]
    moved = await client.patch(f"/api/hats/{hat_id}/assign", json={"case_id": b["id"]})
    assert moved.status_code == 200
    after = moved.json()["display_id"]

    assert before != after, "test is vacuous unless the display id actually moved"
    html = (await client.get("/api/admin/hat-labels")).text
    assert f"/t/h/{hat_id}" in html


async def test_hat_labels_can_be_narrowed_to_one_case(client):
    a = (await client.post("/api/cases", json={"case_type": "archive"})).json()
    b = (await client.post("/api/cases", json={"case_type": "daily_wear"})).json()
    in_a = await _hat(client, case_id=a["id"], model_name="Alpha")
    in_b = await _hat(client, case_id=b["id"], model_name="Bravo")

    html = (await client.get(f"/api/admin/hat-labels?case={a['display_id']}")).text
    assert f"/t/h/{in_a}" in html
    assert f"/t/h/{in_b}" not in html


async def test_hat_labels_exclude_disposed_hats(client):
    """You don't put a sticker in a hat you no longer own."""
    hat_id = await _hat(client, model_name="Departed")
    await client.post(f"/api/hats/{hat_id}/dispose", json={"via": "sold"})

    html = (await client.get("/api/admin/hat-labels")).text
    assert f"/t/h/{hat_id}" not in html


async def test_hat_labels_include_unassigned_hats(client):
    """An unassigned hat has no display id — it must still get a label.

    This is precisely the state a hat is in while you're tagging it, so
    excluding it (or keying the label on the missing display id) would break
    the one workflow the sheet exists for.
    """
    hat_id = await _hat(client, model_name="Homeless")
    html = (await client.get("/api/admin/hat-labels")).text
    assert f"/t/h/{hat_id}" in html
    assert "unassigned" in html
