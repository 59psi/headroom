"""What a write body may carry — money, text, and a few rules of sense.

Every one of these used to be accepted. `resale_price: NaN` became a row with
no price and `scope='manual'`, immune to every refresh forever; `Infinity`
made every valuation total `$inf`; `-5` rendered `PAID $-5` and `$-5.00/wear`;
a "lost" hat carried the previous sale's `$50` into the audit log; a room
named with a bidi override read `live` in every list; a 500-character room
name made a `<select>` 5,205 px wide; `"   "` and `""` were stored two
different ways by the same field. The schema is where a wire body is
described, so the schema is where all of this is refused.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

pytestmark = pytest.mark.anyio

HAT = {"condition": "new", "size": "classic", "style": "a_game"}


async def _hat(client) -> int:
    resp = await client.post("/api/hats", json=HAT)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.mark.parametrize("field", ["purchase_price", "estimated_new_price", "resale_price"])
@pytest.mark.parametrize("raw", ["NaN", "Infinity", "-Infinity", "-1", "1e308", "2000000"])
async def test_a_price_that_is_not_a_price_is_refused(client, field, raw):
    hat_id = await _hat(client)
    resp = await client.put(
        f"/api/hats/{hat_id}",
        content=f'{{"{field}": {raw}}}',
        headers={"content-type": "application/json"},
    )
    assert resp.status_code == 422, (field, raw, resp.text)
    hat = (await client.get(f"/api/hats/{hat_id}")).json()
    assert hat[field] is None
    assert hat["resale_price_scope"] != "manual", "a refused price must not stamp the scope"


async def test_a_real_price_still_lands(client):
    hat_id = await _hat(client)
    resp = await client.put(f"/api/hats/{hat_id}", json={"resale_price": 85.5, "purchase_price": 0})
    assert resp.status_code == 200, resp.text
    assert resp.json()["resale_price"] == 85.5
    assert resp.json()["purchase_price"] == 0, "free is a real price"


@pytest.mark.parametrize("via", ["gifted", "lost", "trashed"])
async def test_a_price_is_only_for_a_sale_or_a_trade(client, via):
    hat_id = await _hat(client)
    resp = await client.post(f"/api/hats/{hat_id}/dispose", json={"via": via, "price": 50})
    assert resp.status_code == 422, resp.text
    ok = await client.post(f"/api/hats/{hat_id}/dispose", json={"via": via})
    assert ok.status_code == 200, ok.text
    assert ok.json()["disposed_price"] is None


@pytest.mark.parametrize("via", ["sold", "trade"])
async def test_a_sale_keeps_its_price(client, via):
    hat_id = await _hat(client)
    resp = await client.post(f"/api/hats/{hat_id}/dispose", json={"via": via, "price": 45})
    assert resp.status_code == 200, resp.text
    assert resp.json()["disposed_price"] == 45


async def test_room_names_are_bounded_and_control_free(client):
    assert (await client.post("/api/rooms", json={"name": "x" * 101})).status_code == 422
    assert (await client.post("/api/rooms", json={"name": "   "})).status_code == 422
    # A right-to-left override spells "evil" so it reads "live".
    resp = await client.post("/api/rooms", json={"name": "‮evil‬"})
    assert resp.status_code == 201, resp.text
    assert resp.json()["name"] == "evil"
    # Emoji spelled with a zero-width joiner survive: those are letters here.
    resp = await client.post("/api/rooms", json={"name": "Closet \U0001f3f3️‍\U0001f308"})
    assert resp.status_code == 201, resp.text
    assert "‍" in resp.json()["name"]


async def test_hat_text_is_trimmed_bounded_and_empty_becomes_null(client):
    hat_id = await _hat(client)
    resp = await client.put(
        f"/api/hats/{hat_id}",
        json={"colorway": "  Navy \x00Denim  ", "artist_series": "   ", "owner_notes": "line one\nline two"},
    )
    assert resp.status_code == 200, resp.text
    hat = resp.json()
    assert hat["colorway"] == "Navy Denim"
    assert hat["artist_series"] is None, "whitespace-only is nothing, not a blank string"
    assert hat["owner_notes"] == "line one\nline two", "notes keep their newlines"
    too_long = await client.put(f"/api/hats/{hat_id}", json={"owner_notes": "n" * 10_001})
    assert too_long.status_code == 422
    too_long = await client.put(f"/api/hats/{hat_id}", json={"model_name": "m" * 121})
    assert too_long.status_code == 422


async def test_the_model_id_is_shaped_like_a_model_id(client):
    bad = await client.put("/api/settings/model", json={"model_id": "<script>alert(1)</script>"})
    assert bad.status_code == 422
    ok = await client.put("/api/settings/model", json={"model_id": "claude-fable-5-1"})
    assert ok.status_code == 200, ok.text


async def test_a_wear_cannot_be_logged_in_the_future(client):
    hat_id = await _hat(client)
    future = (date.today() + timedelta(days=30)).isoformat()
    assert (await client.post(f"/api/hats/{hat_id}/wear", json={"worn_at": future})).status_code == 422
    # Tomorrow is allowed: a phone a day ahead of the server's UTC clock.
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    assert (await client.post(f"/api/hats/{hat_id}/wear", json={"worn_at": tomorrow})).status_code in (200, 201)
