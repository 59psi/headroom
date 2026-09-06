"""The purchase-import body is validated at the wire, line by line.

It was `items: list[dict]`, the one request body in the app with no schema.
Measured before the fix: a DRY RUN with `quantity: 1e9` allocated 15 GB of
transient rows before it was killed; `quantity: 100000` wrote 100,000 rows
with no UI to remove them; `price: "abc"` passed the preview and 500'd the
real import at commit, rolling the whole batch back; `price: -5` matched a
hat and wrote `PAID $-5` and `$-5.00/wear` onto its page; an unparseable
`order_date` was silently dropped to NULL. The card asks the owner to paste
assistant-produced JSON, so one hallucinated digit was enough for any of it.
"""

from __future__ import annotations

import pytest

from headroom.schemas.admin import MAX_IMPORT_LINES, MAX_UNITS_PER_LINE

pytestmark = pytest.mark.anyio

URL = "/api/admin/purchases/import"


def _line(**over) -> dict:
    return {"item_title": "Odysea Hydro - Navy", "price": 79.0, "quantity": 1, **over}


@pytest.mark.parametrize(
    "bad, field",
    [
        ({"quantity": 1_000_000_000}, "quantity"),
        ({"quantity": MAX_UNITS_PER_LINE + 1}, "quantity"),
        ({"quantity": 0}, "quantity"),
        ({"quantity": -3}, "quantity"),
        ({"price": "abc"}, "price"),
        ({"price": -5}, "price"),
        ({"order_date": "2026-13-45"}, "order_date"),
        ({"item_title": "x" * 301}, "item_title"),
    ],
    ids=["1e9-units", "over-cap", "zero", "negative-qty", "text-price", "negative-price",
         "bad-date", "long-title"],
)
async def test_a_bad_line_is_a_422_that_names_the_line_and_the_field(client, bad, field):
    for dry_run in ("true", "false"):
        resp = await client.post(f"{URL}?dry_run={dry_run}", json={"items": [_line(), _line(**bad)]})
        assert resp.status_code == 422, (dry_run, resp.text)
        locs = [err["loc"] for err in resp.json()["detail"]]
        assert any(loc[-1] == field and 1 in loc for loc in locs), locs
    # Nothing was written by either attempt.
    assert (await client.get("/api/admin/purchases")).json() == []


async def test_an_infinite_price_is_refused_even_as_raw_json(client):
    """Python's own encoder refuses `inf`, so the probe goes on the wire as
    text — which is how a hand-written or third-party body would arrive."""
    body = '{"items": [{"item_title": "Odysea Hydro - Navy", "price": Infinity, "quantity": 1}]}'
    resp = await client.post(
        f"{URL}?dry_run=true", content=body, headers={"content-type": "application/json"}
    )
    assert resp.status_code == 422, resp.text


async def test_a_batch_over_the_line_cap_is_refused_whole(client):
    resp = await client.post(
        f"{URL}?dry_run=true", json={"items": [_line() for _ in range(MAX_IMPORT_LINES + 1)]}
    )
    assert resp.status_code == 422
    assert (await client.get("/api/admin/purchases")).json() == []


async def test_a_line_at_the_unit_cap_imports_that_many_rows(client):
    resp = await client.post(URL, json={"items": [_line(quantity=MAX_UNITS_PER_LINE)]})
    assert resp.status_code == 200, resp.text
    assert resp.json()["imported"] == MAX_UNITS_PER_LINE
    assert len((await client.get("/api/admin/purchases")).json()) == MAX_UNITS_PER_LINE


async def test_unknown_keys_are_ignored_not_refused(client):
    """The assistant producing the JSON may add fields; only the ones the
    prompt names are read, and a stray one must not sink the batch."""
    resp = await client.post(
        f"{URL}?dry_run=true", json={"items": [_line(note="from the receipt", sku="AB12")]}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["would_import"] == 1


async def test_a_date_only_order_date_parses(client):
    resp = await client.post(URL, json={"items": [_line(order_date="2026-03-14")]})
    assert resp.status_code == 200, resp.text
    rows = (await client.get("/api/admin/purchases")).json()
    assert rows[0]["order_date"].startswith("2026-03-14")
