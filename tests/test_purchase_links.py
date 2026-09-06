"""Purchase↔hat links under deletion and under concurrent imports.

Both were found by execution, not reading. Deleting a hat left its purchase
pointing at a row that no longer existed (no `PRAGMA foreign_keys`), so the
receipt was never offered to another hat again; and two imports of one file
running together each counted zero rows on record and wrote every line
twice.
"""

from __future__ import annotations

import asyncio

import pytest

pytestmark = pytest.mark.anyio

HAT = {"condition": "new", "size": "classic", "style": "odysea", "model_name": "Odysea Hydro"}
LINE = {"item_title": "Odysea Hydro - Navy", "price": 79.0, "quantity": 1, "size": "Classic",
        "order_ref": "ORD-1"}


async def test_deleting_a_hat_gives_its_receipt_back(client):
    hat_id = (await client.post("/api/hats", json=HAT)).json()["id"]
    resp = await client.post("/api/admin/purchases/import", json={"items": [LINE]})
    assert resp.status_code == 200, resp.text
    assert resp.json()["matched"] == 1
    rows = (await client.get("/api/admin/purchases")).json()
    assert rows[0]["hat_id"] == hat_id

    assert (await client.delete(f"/api/hats/{hat_id}")).status_code == 204

    rows = (await client.get("/api/admin/purchases")).json()
    assert rows[0]["hat_id"] is None, "the receipt still pointed at a hat that no longer exists"
    # And it is offered to the next hat that fits.
    replacement = (await client.post("/api/hats", json=HAT)).json()["id"]
    match = (await client.post("/api/admin/purchases/match")).json()
    assert match["matched"] == 1
    assert (await client.get(f"/api/hats/{replacement}")).json()["purchase_price"] == 79.0


async def test_two_imports_of_one_file_at_once_do_not_double_the_rows(file_client, monkeypatch):
    """The dedupe reads the rows on record, then the batch commits. Two
    imports interleaving at that read both see none. The read is made to
    yield here so the window is a certainty rather than a matter of timing;
    the lock around the route is what closes it (remove the lock and this
    writes four rows)."""
    from headroom.services import catalog_service

    real = catalog_service._units_to_add

    async def slow(*args, **kwargs):
        result = await real(*args, **kwargs)
        await asyncio.sleep(0.05)
        return result

    monkeypatch.setattr(catalog_service, "_units_to_add", slow)
    two = {**LINE, "quantity": 2}
    responses = await asyncio.gather(*[
        file_client.post("/api/admin/purchases/import", json={"items": [two]}) for _ in range(2)
    ])
    assert [r.status_code for r in responses] == [200, 200], [r.text for r in responses]
    rows = (await file_client.get("/api/admin/purchases")).json()
    assert len(rows) == 2, f"{len(rows)} rows for a line that says × 2"
    assert sum(r["imported"] for r in map(lambda r: r.json(), responses)) == 2
