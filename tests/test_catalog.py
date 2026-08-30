"""Colorway catalog (melinrecap harvest) + purchase-history import/matching."""

from __future__ import annotations

import pytest

from headroom.services.catalog_service import parse_listing_title

pytestmark = pytest.mark.anyio


async def test_parse_listing_title_variants():
    assert parse_listing_title("A-Game Hydro - Heather Grey") == ("A-Game Hydro", "Heather Grey")
    assert parse_listing_title("Coronado Brick Hydro - Heather Ocean / Heather Charcoal") == (
        "Coronado Brick Hydro", "Heather Ocean / Heather Charcoal",
    )
    # No separator → model only
    assert parse_listing_title("Odysea Journey") == ("Odysea Journey", None)
    # Hyphen inside the model name only splits on " - " (spaced)
    assert parse_listing_title("A-Game Scout")[0] == "A-Game Scout"


def _pages(monkeypatch, pages_by_category):
    """Stub query_listings: serve canned title pages per category."""
    async def _fake(params):
        cat = params["pub_category"]
        page = params.get("page", 1)
        titles = pages_by_category.get(cat, [])
        per = params["per_page"]
        chunk = titles[(page - 1) * per : page * per]
        return [{"attributes": {"title": t}} for t in chunk]

    monkeypatch.setattr("headroom.services.catalog_service.query_listings", _fake)


async def test_harvest_upserts_and_counts(client, db_session, monkeypatch):
    from headroom.services.catalog_service import harvest_catalog

    _pages(monkeypatch, {
        "aGame": ["A-Game Hydro - Red", "A-Game Hydro - Red", "A-Game Scout - Grey"],
        "odysea": ["Odysea - Moss"],
    })
    result = await harvest_catalog(db_session)
    assert result["new_entries"] == 3          # dupe title upserted, not doubled
    assert result["catalog_total"] == 3

    # Second harvest adds nothing new but bumps counts
    result = await harvest_catalog(db_session)
    assert result["new_entries"] == 0
    assert result["catalog_total"] == 3


async def test_colorway_autocomplete_endpoint(client, db_session, monkeypatch):
    from headroom.services.catalog_service import harvest_catalog

    _pages(monkeypatch, {
        "aGame": ["A-Game Hydro - Heather Grey", "A-Game Hydro - Red", "A-Game Scout - Grey"],
    })
    await harvest_catalog(db_session)

    models = (await client.get("/api/meta/colorways")).json()
    assert {"value": "A-Game Hydro"} in models

    cws = (await client.get("/api/meta/colorways", params={"model": "a-game hydro"})).json()
    values = [c["value"] for c in cws]
    assert "Heather Grey" in values and "Red" in values and "Grey" not in values


async def test_purchase_import_dedupe_and_match(client, db_session):
    # A hat Claude identified but with no colorway/cost basis yet
    hat = await client.post(
        "/api/hats", json={"condition": "new", "size": "classic", "style": "a_game"}
    )
    hat_id = hat.json()["id"]
    from headroom.models.hat import Hat

    row = await db_session.get(Hat, hat_id)
    row.model_name = "A-Game Hydro"
    await db_session.commit()

    items = [
        {"item_title": "A-Game Hydro - Heather Grey", "order_ref": "M123",
         "order_date": "2024-06-01", "price": 69.0},
        {"item_title": "A-Game Hydro - Heather Grey", "order_ref": "M123",
         "order_date": "2024-06-01", "price": 69.0},  # dupe
        {"item_title": "Odysea - Moss", "order_ref": "M124", "price": 79.0},
    ]
    resp = await client.post("/api/admin/purchases/import", json={"items": items})
    assert resp.status_code == 200
    body = resp.json()
    assert body["imported"] == 2
    assert body["skipped"] == 1
    assert body["matched"] == 1     # the A-Game Hydro linked to our hat
    assert body["unmatched"] == 1   # no Odysea hat exists

    updated = (await client.get(f"/api/hats/{hat_id}")).json()
    assert updated["colorway"] == "Heather Grey"
    assert updated["purchase_price"] == 69.0
    assert updated["purchased_at"] is not None

    purchases = (await client.get("/api/admin/purchases")).json()
    linked = [p for p in purchases if p["hat_id"] == hat_id]
    assert len(linked) == 1


async def test_match_respects_colorway_disagreement(client, db_session):
    from headroom.models.hat import Hat

    hat = await client.post(
        "/api/hats", json={"condition": "new", "size": "classic", "style": "a_game"}
    )
    hat_id = hat.json()["id"]
    row = await db_session.get(Hat, hat_id)
    row.model_name = "A-Game Hydro"
    row.colorway = "Red"  # user already set it
    await db_session.commit()

    resp = await client.post(
        "/api/admin/purchases/import",
        json={"items": [{"item_title": "A-Game Hydro - Heather Grey", "price": 69.0}]},
    )
    assert resp.json()["matched"] == 0  # colorways disagree → no link

    updated = (await client.get(f"/api/hats/{hat_id}")).json()
    assert updated["colorway"] == "Red"
    assert updated["purchase_price"] is None


# ------------------- size-aware matching (v2.19) ---------------------- #
#
# Order emails have always carried the size ("Transit / Classic") and the
# importer dropped it. Matching on model name alone binds a purchase to
# whichever hat the database returns first, so with two sizes of one model on
# the shelf a Small can be handed a Classic's price — and nothing downstream
# ever looks wrong, because both hats end up with *a* cost basis.


async def test_normalize_size_maps_order_line_spellings():
    from headroom.services.catalog_service import normalize_size

    assert normalize_size("Classic") == "classic"
    assert normalize_size("X-Large") == "x_large"
    assert normalize_size("XL") == "x_large"
    assert normalize_size(" small ") == "small"
    assert normalize_size("Standard") == "classic"  # pre-2.0 name, same size
    # Not a hat size — travel cases ship as "One Size".
    assert normalize_size("One Size") is None
    assert normalize_size(None) is None
    # An unrecognized spelling must return None, not a guess: a wrong size
    # actively BLOCKS the correct match, where None merely fails to sharpen it.
    assert normalize_size("Toddler") is None


async def _hat_with(client, db_session, *, size, model, colorway=None):
    from headroom.models.hat import Hat

    resp = await client.post(
        "/api/hats", json={"condition": "new", "size": size, "style": "a_game"}
    )
    hat_id = resp.json()["id"]
    row = await db_session.get(Hat, hat_id)
    row.model_name = model
    row.colorway = colorway
    await db_session.commit()
    return hat_id


async def test_size_decides_between_two_hats_of_the_same_model(client, db_session):
    small = await _hat_with(client, db_session, size="small", model="A-Game Hydro")
    classic = await _hat_with(client, db_session, size="classic", model="A-Game Hydro")

    resp = await client.post(
        "/api/admin/purchases/import",
        json={"items": [{
            "item_title": "A-Game Hydro - Black",
            "price": 89.0,
            "size": "Classic",
        }]},
    )
    assert resp.json()["matched"] == 1

    assert (await client.get(f"/api/hats/{classic}")).json()["purchase_price"] == 89.0
    # The whole point: the Small must be untouched, not merely "also matched".
    assert (await client.get(f"/api/hats/{small}")).json()["purchase_price"] is None


async def test_size_disagreement_blocks_a_match_outright(client, db_session):
    await _hat_with(client, db_session, size="small", model="A-Game Hydro")

    resp = await client.post(
        "/api/admin/purchases/import",
        json={"items": [{
            "item_title": "A-Game Hydro - Black",
            "price": 89.0,
            "size": "X-Large",
        }]},
    )
    # Better to leave a purchase unmatched than to attach it to a hat we can
    # see is the wrong one.
    assert resp.json()["matched"] == 0


async def test_a_sizeless_purchase_still_matches(client, db_session):
    """Back-compat: pre-2.19 rows and hand-entered items carry no size."""
    hat_id = await _hat_with(client, db_session, size="classic", model="A-Game Hydro")

    resp = await client.post(
        "/api/admin/purchases/import",
        json={"items": [{"item_title": "A-Game Hydro - Black", "price": 89.0}]},
    )
    assert resp.json()["matched"] == 1
    assert (await client.get(f"/api/hats/{hat_id}")).json()["purchase_price"] == 89.0


async def test_identical_hats_are_reported_as_ambiguous(client, db_session):
    """Two hats the records genuinely cannot separate.

    One still gets the price — leaving both unpriced would be worse — but the
    coin flip is counted and surfaced rather than presented as a fact.
    """
    await _hat_with(client, db_session, size="classic", model="A-Game Hydro", colorway="Black")
    await _hat_with(client, db_session, size="classic", model="A-Game Hydro", colorway="Black")

    resp = await client.post(
        "/api/admin/purchases/import",
        json={"items": [{
            "item_title": "A-Game Hydro - Black", "price": 89.0, "size": "Classic",
        }]},
    )
    assert resp.json()["ambiguous"] == 1


# ----------------------------- dry run -------------------------------- #


async def test_dry_run_import_writes_nothing(client, db_session):
    hat_id = await _hat_with(client, db_session, size="classic", model="A-Game Hydro")

    payload = {"items": [{
        "item_title": "A-Game Hydro - Black", "price": 89.0, "size": "Classic",
    }]}
    resp = await client.post("/api/admin/purchases/import?dry_run=true", json=payload)
    body = resp.json()

    assert body["dry_run"] is True
    assert body["would_import"] == 1
    assert body["would_match"] == 1
    assert body["proposals"][0]["hat_id"] == hat_id
    assert "size" in body["proposals"][0]["matched_on"]

    # Nothing persisted: no purchase rows, no cost basis on the hat.
    assert (await client.get("/api/admin/purchases")).json() == []
    assert (await client.get(f"/api/hats/{hat_id}")).json()["purchase_price"] is None

    # And the real import still works afterwards — the preview left no state
    # behind that makes the row look already-imported.
    real = await client.post("/api/admin/purchases/import", json=payload)
    assert real.json()["imported"] == 1
    assert (await client.get(f"/api/hats/{hat_id}")).json()["purchase_price"] == 89.0


async def test_dry_run_counts_duplicates_against_what_is_already_there(client, db_session):
    await _hat_with(client, db_session, size="classic", model="A-Game Hydro")
    payload = {"items": [{
        "item_title": "A-Game Hydro - Black", "price": 89.0,
        "size": "Classic", "order_ref": "123",
    }]}
    await client.post("/api/admin/purchases/import", json=payload)

    resp = await client.post("/api/admin/purchases/import?dry_run=true", json=payload)
    body = resp.json()
    assert body["would_import"] == 0
    assert body["duplicates"] == 1


async def test_dry_run_flags_accessories(client, db_session):
    await _hat_with(client, db_session, size="classic", model="A-Game Hydro")

    resp = await client.post("/api/admin/purchases/import?dry_run=true", json={"items": [
        {"item_title": "3 Hat Travel Case - Black", "price": 49.0, "size": "One Size"},
        {"item_title": "Shipping Protection - Rest easy", "price": 4.76},
        {"item_title": "A-Game Hydro - Black", "price": 89.0, "size": "Classic"},
    ]})
    body = resp.json()
    # Flagged, but still imported — a heuristic that silently dropped lines
    # would hide a real hat behind wording nobody anticipated.
    assert body["likely_accessories"] == 2
    assert body["would_import"] == 3
    assert body["would_match"] == 1


async def test_dry_run_match_endpoint_leaves_links_alone(client, db_session):
    hat_id = await _hat_with(client, db_session, size="classic", model="A-Game Hydro")
    # Import with a model the hat doesn't have yet, so nothing matches...
    await client.post("/api/admin/purchases/import", json={"items": [
        {"item_title": "Odysea Journey - Black", "price": 79.0},
    ]})
    # ...then rename the hat so it WOULD match, and preview it.
    from headroom.models.hat import Hat
    row = await db_session.get(Hat, hat_id)
    row.model_name = "Odysea Journey"
    await db_session.commit()

    preview = await client.post("/api/admin/purchases/match?dry_run=true")
    assert preview.json()["matched"] == 1
    assert (await client.get(f"/api/hats/{hat_id}")).json()["purchase_price"] is None

    real = await client.post("/api/admin/purchases/match")
    assert real.json()["matched"] == 1
    assert (await client.get(f"/api/hats/{hat_id}")).json()["purchase_price"] == 79.0


# --------------- multi-buy lines become one row per hat ---------------- #
#
# A line reading "x 2" is two hats, and a purchase matches ONE hat — so one
# row per line meant the second hat of every multi-buy silently never got a
# cost basis. In this collection's real order history that's ~40% of lines.


async def test_a_quantity_two_line_prices_two_hats(client, db_session):
    a = await _hat_with(client, db_session, size="classic", model="A-Game Hydro")
    b = await _hat_with(client, db_session, size="classic", model="A-Game Hydro")

    resp = await client.post("/api/admin/purchases/import", json={"items": [{
        "item_title": "A-Game Hydro - Black", "price": 89.0,
        "size": "Classic", "quantity": 2, "order_ref": "555",
    }]})
    assert resp.json()["imported"] == 2
    assert resp.json()["matched"] == 2

    for hat_id in (a, b):
        assert (await client.get(f"/api/hats/{hat_id}")).json()["purchase_price"] == 89.0


async def test_reimporting_a_multi_buy_adds_nothing(client, db_session):
    await _hat_with(client, db_session, size="classic", model="A-Game Hydro")
    payload = {"items": [{
        "item_title": "A-Game Hydro - Black", "price": 89.0,
        "size": "Classic", "quantity": 2, "order_ref": "555",
    }]}
    first = await client.post("/api/admin/purchases/import", json=payload)
    assert first.json()["imported"] == 2

    # Count-based dedupe: the two rows are already there, so nothing is added.
    again = await client.post("/api/admin/purchases/import", json=payload)
    assert again.json()["imported"] == 0
    assert again.json()["skipped"] == 2
    assert len((await client.get("/api/admin/purchases")).json()) == 2


async def test_an_explicit_colorway_beats_one_parsed_from_the_title(client, db_session):
    """Order lines carry the colorway separately, and plenty of titles have
    no " - " to split on — "Odysea Hydro Indigo Depth" parses to a model with
    no colorway at all, which can then disambiguate nothing."""
    hat_id = await _hat_with(
        client, db_session, size="classic", model="Odysea Hydro Indigo Depth",
        colorway="Indigo Depth",
    )
    resp = await client.post("/api/admin/purchases/import", json={"items": [{
        "item_title": "Odysea Hydro Indigo Depth", "colorway": "Indigo Depth",
        "price": 89.0, "size": "Classic",
    }]})
    assert resp.json()["matched"] == 1
    stored = (await client.get("/api/admin/purchases")).json()[0]
    assert stored["colorway"] == "Indigo Depth"
    assert (await client.get(f"/api/hats/{hat_id}")).json()["purchase_price"] == 89.0


async def test_dry_run_counts_units_not_lines(client, db_session):
    await _hat_with(client, db_session, size="classic", model="A-Game Hydro")
    await _hat_with(client, db_session, size="classic", model="A-Game Hydro")

    resp = await client.post("/api/admin/purchases/import?dry_run=true", json={"items": [{
        "item_title": "A-Game Hydro - Black", "price": 89.0,
        "size": "Classic", "quantity": 2,
    }]})
    body = resp.json()
    # A preview that counted lines while the import counts units would
    # under-report exactly the multi-buys it exists to surface.
    assert body["would_import"] == 2
    assert body["would_match"] == 2


async def test_same_model_and_price_in_two_sizes_both_import(client, db_session):
    """One order, one model, one price, two sizes — two different hats.

    Taken from the real order history: order 1626812 bought a Richard Ham
    Hydro in Classic x2 AND Small x1 at the same $89. A dedupe key of
    (order, title, price) collapses the Small into the Classic line and the
    hat silently never gets a cost basis — the precise failure the size
    column was added to prevent.
    """
    await _hat_with(client, db_session, size="classic", model="A-Game Hydro")
    payload = {"items": [
        {"item_title": "A-Game Hydro - Black", "price": 89.0,
         "size": "Classic", "order_ref": "777", "quantity": 2},
        {"item_title": "A-Game Hydro - Black", "price": 89.0,
         "size": "Small", "order_ref": "777", "quantity": 1},
    ]}

    preview = (await client.post("/api/admin/purchases/import?dry_run=true",
                                 json=payload)).json()
    real = (await client.post("/api/admin/purchases/import", json=payload)).json()

    # The preview must predict the import exactly, or it isn't a preview.
    assert preview["would_import"] == real["imported"] == 3
    rows = (await client.get("/api/admin/purchases")).json()
    assert sorted(r["size"] for r in rows) == ["classic", "classic", "small"]

    # Still idempotent with size in the key.
    again = (await client.post("/api/admin/purchases/import", json=payload)).json()
    assert again["imported"] == 0


# ----------------------------- unmatch --------------------------------- #
#
# Matching had no undo at all: it mutates hats, runs over years of imported
# order history in one call, and `match_purchases_to_hats` only ever considers
# purchases with a NULL hat_id — so a wrong link was permanent AND invisible,
# because the hat still ended up with *a* price and *a* colorway.


async def _import_one(client, **over):
    payload = {"item_title": "A-Game Hydro - Black", "price": 89.0,
               "size": "Classic", "order_ref": "900", "quantity": 1}
    payload.update(over)
    return await client.post("/api/admin/purchases/import", json={"items": [payload]})


async def test_unmatch_returns_the_purchase_to_the_pool(client, db_session):
    hat_id = await _hat_with(client, db_session, size="classic", model="A-Game Hydro")
    await _import_one(client)

    purchase = (await client.get("/api/admin/purchases")).json()[0]
    assert purchase["hat_id"] == hat_id

    resp = await client.post(f"/api/admin/purchases/{purchase['id']}/unmatch")
    assert resp.status_code == 200
    assert resp.json()["unmatched"] == 1
    assert set(resp.json()["cleared"]) == {"purchase_price", "colorway"}

    hat = (await client.get(f"/api/hats/{hat_id}")).json()
    assert hat["purchase_price"] is None
    assert hat["colorway"] is None
    assert (await client.get("/api/admin/purchases")).json()[0]["hat_id"] is None

    # Back in the pool: re-running the matcher re-links it.
    assert (await client.post("/api/admin/purchases/match")).json()["matched"] == 1
    assert (await client.get(f"/api/hats/{hat_id}")).json()["purchase_price"] == 89.0


async def test_unmatch_leaves_values_edited_since_alone(client, db_session):
    """A reversal that clobbered a hand-typed price would be a worse bug than
    the mis-match it was undoing."""
    hat_id = await _hat_with(client, db_session, size="classic", model="A-Game Hydro")
    await _import_one(client)
    purchase = (await client.get("/api/admin/purchases")).json()[0]

    # Someone corrects the price by hand after the match.
    await client.put(f"/api/hats/{hat_id}", json={"purchase_price": 55.0})

    resp = await client.post(f"/api/admin/purchases/{purchase['id']}/unmatch")
    assert "purchase_price" not in resp.json()["cleared"]
    assert (await client.get(f"/api/hats/{hat_id}")).json()["purchase_price"] == 55.0
    # The colorway was untouched since the match, so it still reverts.
    assert "colorway" in resp.json()["cleared"]


async def test_unmatch_is_idempotent_and_404s_on_a_missing_row(client, db_session):
    await _hat_with(client, db_session, size="classic", model="A-Game Hydro")
    await _import_one(client)
    pid = (await client.get("/api/admin/purchases")).json()[0]["id"]

    assert (await client.post(f"/api/admin/purchases/{pid}/unmatch")).json()["unmatched"] == 1
    second = await client.post(f"/api/admin/purchases/{pid}/unmatch")
    assert second.status_code == 200
    assert second.json()["unmatched"] == 0

    assert (await client.post("/api/admin/purchases/999999/unmatch")).status_code == 404


async def test_unmatch_all_resets_every_link_but_keeps_the_rows(client, db_session):
    a = await _hat_with(client, db_session, size="classic", model="A-Game Hydro")
    b = await _hat_with(client, db_session, size="small", model="Odysea Journey")
    await client.post("/api/admin/purchases/import", json={"items": [
        {"item_title": "A-Game Hydro - Black", "price": 89.0, "size": "Classic"},
        {"item_title": "Odysea Journey - Bone", "price": 79.0, "size": "Small"},
    ]})

    resp = await client.post("/api/admin/purchases/unmatch-all")
    assert resp.json()["unmatched"] == 2

    for hat_id in (a, b):
        assert (await client.get(f"/api/hats/{hat_id}")).json()["purchase_price"] is None
    rows = (await client.get("/api/admin/purchases")).json()
    # The order history survives — re-importing it is the expensive part.
    assert len(rows) == 2 and all(r["hat_id"] is None for r in rows)

    assert (await client.post("/api/admin/purchases/match")).json()["matched"] == 2


async def test_unmatch_all_route_is_not_shadowed_by_the_id_route(client):
    """`unmatch-all` must not be parsed as a purchase id.

    A literal segment that can be read as an id is how `/api/hats/import` got
    shadowed by `/api/hats/{hat_id}` once already.
    """
    resp = await client.post("/api/admin/purchases/unmatch-all")
    assert resp.status_code == 200
    assert "unmatched" in resp.json()


async def test_unmatch_is_audited(client, db_session):
    hat_id = await _hat_with(client, db_session, size="classic", model="A-Game Hydro")
    await _import_one(client)
    pid = (await client.get("/api/admin/purchases")).json()[0]["id"]
    await client.post(f"/api/admin/purchases/{pid}/unmatch")

    kinds = [r["kind"] for r in (await client.get("/api/admin/activity-log")).json()]
    assert "purchase.unmatched" in kinds, f"no audit row for the undo: {kinds}"
    assert hat_id  # referenced so the fixture's intent is clear


# ------------------- harvest resilience + real counts ------------------ #


async def test_one_failing_category_does_not_abandon_the_rest(db_session, monkeypatch):
    """A single transient marketplace error used to end the whole harvest.

    The sweep is sequential and commits per page, so the result was a silently
    partial catalog: the endpoint had already returned 202 and nothing recorded
    that it stopped early. A catalog missing two thirds of its models looked
    exactly like a complete one.
    """
    from headroom.services import catalog_service
    from headroom.services.melin_recap import MelinRecapError

    calls: list[str] = []

    async def flaky(params):
        cat = params["pub_category"]
        calls.append(cat)
        if cat == "coronado":
            raise MelinRecapError("502 from the marketplace")
        return [{"attributes": {"title": f"{cat} Hydro - Color"}}]

    monkeypatch.setattr("headroom.services.catalog_service.query_listings", flaky)
    async def _no_sleep(_delay):  # the retry backoff, minus the waiting
        return None

    monkeypatch.setattr("headroom.services.catalog_service.asyncio.sleep", _no_sleep)

    result = await catalog_service.harvest_catalog(db_session)

    assert result["failed_categories"] == ["coronado"]
    # Every OTHER category still swept — the ones after the failure especially.
    assert "odysea" in calls and "coast" in calls
    assert result["distinct_models"] >= 8, result


async def test_a_transient_page_failure_is_retried(db_session, monkeypatch):
    """These are 429s and 502s, not permanent conditions — one retry saves the
    whole category."""
    from headroom.services import catalog_service
    from headroom.services.melin_recap import MelinRecapError

    attempts = {"n": 0}

    async def twitchy(params):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise MelinRecapError("429 slow down")
        return []

    monkeypatch.setattr("headroom.services.catalog_service.query_listings", twitchy)
    async def _no_sleep(_delay):  # the retry backoff, minus the waiting
        return None

    monkeypatch.setattr("headroom.services.catalog_service.asyncio.sleep", _no_sleep)

    got = await catalog_service._fetch_page({"pub_category": "aGame"})
    assert got == []
    assert attempts["n"] == 2, "the page was not retried"


async def test_catalog_stats_counts_the_catalog_not_a_page_of_autocomplete(
    client, db_session
):
    """The Settings card reported `len(GET /api/meta/colorways)` as "models
    known". That endpoint is autocomplete and caps at `catalog_options`'s
    default limit of 25, so the number sat at 25 however much was harvested —
    indistinguishable from a harvest that genuinely found 25.
    """
    from headroom.models.catalog import ColorwayEntry
    from headroom.services import catalog_service

    for i in range(40):
        db_session.add(ColorwayEntry(
            title=f"Model{i} Hydro - Color{i}", model_name=f"Model{i} Hydro",
            colorway=f"Color{i}", category="aGame", listing_count=1,
        ))
    await db_session.commit()

    # The service helper still caps by default — that is its job.
    assert len(await catalog_service.catalog_options(db_session)) == 25
    # The stats must not.
    stats = await catalog_service.catalog_stats(db_session)
    assert stats["models"] == 40, stats
    assert stats["entries"] == 40
    assert stats["colorways"] == 40

    body = (await client.get("/api/admin/colorways/status")).json()
    assert body["models"] == 40


async def test_the_colorway_picker_can_reach_the_whole_catalog(client, db_session):
    """Reported as "the catalog is missing so many colorways" — it wasn't.

    `GET /api/meta/colorways` called `catalog_options` without a limit, so it
    silently took the default of 25. The live catalog held 188 colorways and
    the picker offered 25 of them. Typing could not reach the rest either: the
    page fetches this feed WITHOUT `q` and the combobox filters client-side,
    so everything past the cap was unreachable however specific the query.

    A truncated list is invisible — it looks exactly like a small catalog,
    which is how this survived alongside a fix for the very same confusion in
    the stats card. Hence a test: the failure cannot be seen, only asserted.
    """
    from headroom.models.catalog import ColorwayEntry

    for i in range(40):
        db_session.add(ColorwayEntry(
            title=f"Odysea Hydro - Shade{i:02d}", model_name="Odysea Hydro",
            colorway=f"Shade{i:02d}", category="odysea", listing_count=1,
        ))
    await db_session.commit()

    models = (await client.get("/api/meta/colorways")).json()
    assert len(models) >= 1

    colorways = (
        await client.get("/api/meta/colorways", params={"model": "Odysea Hydro"})
    ).json()
    assert len(colorways) == 40, (
        f"picker saw {len(colorways)} of 40 — capped again"
    )
    # The tail specifically: the entries a cap removes are the ones nobody
    # notices are gone.
    assert any(c["value"] == "Shade39" for c in colorways), colorways[:3]


async def test_the_picker_reaches_a_family_named_hat(client, db_session):
    """A hat named for the FAMILY must still see the product's colorways.

    `model_name` comes from Claude reading a photo, which cannot show the
    sub-line, so it lands on `odysea hydro` while the harvested catalog holds
    `Odysea Packable Hydro`. Under exact equality those hats saw ZERO
    colorways at any limit — the picker looked empty and the catalog looked
    incomplete, which is how "the Colorway Catalog is missing so many
    colorways" was actually experienced.

    `_match_score` already solved this for purchases with MODEL_CONTAINED;
    the picker had nothing.
    """
    from headroom.models.catalog import ColorwayEntry

    db_session.add(ColorwayEntry(
        title="Odysea Packable Hydro - Hickory Denim",
        model_name="Odysea Packable Hydro", colorway="Hickory Denim",
        category="odysea", listing_count=3,
    ))
    db_session.add(ColorwayEntry(
        title="Trenches Icon Hydro - Camo", model_name="Trenches Icon Hydro",
        colorway="Camo", category="trenches", listing_count=2,
    ))
    await db_session.commit()

    got = (await client.get(
        "/api/meta/colorways", params={"model": "odysea hydro"}
    )).json()
    values = [c["value"] for c in got]
    assert "Hickory Denim" in values, values
    # Asymmetric: a different family must NOT be dragged in by a shared token.
    assert "Camo" not in values, values


async def test_the_preview_predicts_a_multi_line_import_exactly(client):
    """Preview and import share `_units_to_add` so they cannot disagree.

    An incidental autoflush was making them disagree anyway, and only in the
    import. `import_purchases` adds a Purchase per unit as it walks the batch;
    the dedupe SELECT autoflushed those pending rows, so units this very batch
    had just staged came back as `existing` AND were counted again in
    `staged` — subtracting the line twice. `preview_import` writes nothing, so
    it had no pending rows to flush and stayed correct.

    Two lines sharing (order_ref, title, price, size) with DIFFERENT
    quantities is what exposes it: with equal quantities the double
    subtraction clamps to zero and lands on the right answer by accident,
    which is why this went unnoticed.
    """
    items = [
        {"item_title": "A-Game Hydro - Coronado", "order_ref": "M900",
         "price": 79.0, "quantity": 1},
        {"item_title": "A-Game Hydro - Coronado", "order_ref": "M900",
         "price": 79.0, "quantity": 2},
    ]

    preview = (await client.post(
        "/api/admin/purchases/import?dry_run=true", json={"items": items}
    )).json()
    imported = (await client.post(
        "/api/admin/purchases/import", json={"items": items}
    )).json()

    assert imported["imported"] == preview["would_import"], (
        "the import disagreed with its own preview"
    )
    assert imported["imported"] == 2, "a unit of the second line was dropped"


# ---- model-name tiers ------------------------------------------------- #
#
# Exact equality left ~120 purchase units on this collection unmatched, and the
# cause is structural: `model_name` comes from Claude Vision reading a PHOTO,
# which cannot show the sub-line, so it lands on the generic family ("odysea
# hydro"). The order email states the full product ("Odysea Packable Hydro").
# The photo saw less than the receipt knew — which is the expected direction.


async def test_identical_model_names_score_highest():
    from headroom.services.catalog_service import MODEL_EXACT, _model_tier

    assert _model_tier("Trenches Icon Hydro", "Trenches Icon Hydro") == MODEL_EXACT


async def test_a_generic_hat_name_matches_a_specific_purchase():
    """The ~120-unit case. The receipt knows the sub-line; the photo does not."""
    from headroom.services.catalog_service import MODEL_CONTAINED, _model_tier

    for hat, purchase in [
        ("Odysea Hydro", "Odysea Packable Hydro"),
        ("Trenches Thermal", "Trenches Icon Infinite Thermal"),
        ("A-Game Hydro", "A-Game Icon Hydro"),
        ("Trenches Hydro", "Trenches Links Hydro"),
    ]:
        assert _model_tier(hat, purchase) == MODEL_CONTAINED, (hat, purchase)


async def test_exact_always_outranks_contained():
    """So a subset match only ever picks up what nothing better claimed."""
    from headroom.services.catalog_service import MODEL_CONTAINED, MODEL_EXACT

    assert MODEL_EXACT > MODEL_CONTAINED


async def test_the_subset_direction_is_not_symmetric():
    """A hat named MORE specifically than the receipt must NOT match.

    That would mean the photo knew something the receipt did not, which does
    not happen — and it would let one generic receipt line claim any specific
    hat in the family.
    """
    from headroom.services.catalog_service import _model_tier

    assert _model_tier("Trenches Icon Mill Pinya", "Trenches Icon") is None
    assert _model_tier("Odysea Packable Hydro", "Odysea Hydro") is None


async def test_hyphens_do_not_defeat_the_comparison():
    """`A-Game` and `A Game` are one product line; `X - Camo` is `X Camo`."""
    from headroom.services.catalog_service import MODEL_EXACT, _model_tier

    assert _model_tier("A-Game Hydro", "A Game Hydro") == MODEL_EXACT
    assert _model_tier("Trenches Thermal - Camo", "Trenches Thermal Camo") == MODEL_EXACT


async def test_unrelated_models_never_match():
    from headroom.services.catalog_service import _model_tier

    assert _model_tier("Odysea Hydro", "Trenches Thermal") is None
    assert _model_tier("", "Trenches Hydro") is None
    assert _model_tier("Trenches Hydro", "") is None


async def test_a_travel_case_never_matches_a_hat():
    """78 units of it in the real history — accessories must stay unmatched."""
    from headroom.services.catalog_service import _model_tier

    assert _model_tier("Trenches Icon Hydro", "3 Hat Travel Case") is None


# ---- the two properties the 2.52.0 release notes assert ----------------- #


def _maximum_matching(purchases, hats) -> int:
    """Reference maximum bipartite matching, by augmenting paths.

    Deliberately a SECOND implementation, not a call into the service: it
    answers "how many links are possible" with no notion of scoring, ordering
    or scarcity, so it can contradict the matcher. Kuhn's algorithm — for each
    purchase, walk its candidate hats and recursively bump whoever holds one.

    This exists because the release notes claim the matcher achieves the
    maximum possible, and that claim was measured once in a throwaway script.
    A number nobody can reproduce is a rumor.
    """
    from headroom.services.catalog_service import _match_score

    edges = {
        i: [j for j, h in enumerate(hats) if _match_score(p, h) is not None]
        for i, p in enumerate(purchases)
    }
    holder: dict[int, int] = {}   # hat index -> purchase index

    def _augment(i: int, seen: set[int]) -> bool:
        for j in edges[i]:
            if j in seen:
                continue
            seen.add(j)
            if j not in holder or _augment(holder[j], seen):
                holder[j] = i
                return True
        return False

    return sum(_augment(i, set()) for i in edges)


async def test_matching_achieves_the_maximum_possible(client, db_session):
    """Greedy + scarcity ordering must equal the true optimum, not approach it.

    The arrangement is the one that breaks naive greedy. Two hats of the same
    model differing only in size; a sizeless purchase can take EITHER, a
    Classic purchase can take only the Classic hat. Insert the sizeless line
    first, and in file order it takes the Classic hat on a tie-break, leaving
    the Classic line with nothing — one link where two were possible.

    Sabotage-checked: replacing `_by_scarcity` with file order fails this.
    """
    from headroom.models.catalog import Purchase
    from headroom.services.catalog_service import match_purchases_to_hats

    # Classic first, so it is also the tie-break winner for the sizeless line.
    await _hat_with(client, db_session, size="classic", model="A-Game Hydro")
    await _hat_with(client, db_session, size="small", model="A-Game Hydro")

    # Order matters: the unconstrained line is inserted first on purpose.
    db_session.add(Purchase(
        source="test", item_title="A-Game Hydro - Black",
        model_name="A-Game Hydro", colorway="Black", quantity=1, price=79.0,
    ))
    db_session.add(Purchase(
        source="test", item_title="A-Game Hydro - Black",
        model_name="A-Game Hydro", colorway="Black", size="classic",
        quantity=1, price=79.0,
    ))
    await db_session.commit()

    from sqlalchemy import select

    from headroom.models.hat import Hat
    purchases = list((await db_session.execute(select(Purchase))).scalars().all())
    hats = list((await db_session.execute(
        select(Hat).where(Hat.disposed_at.is_(None))
    )).scalars().all())
    best = _maximum_matching(purchases, hats)
    assert best == 2, "the fixture is meant to admit two links"

    result = await match_purchases_to_hats(db_session)

    assert result["matched"] == best, (
        f"matched {result['matched']} of a possible {best} — scarcity ordering "
        "is not achieving the optimum"
    )


async def test_the_preview_predicts_what_importing_actually_does(client, db_session):
    """A preview that under-reports the blast radius is worse than none.

    Importing runs the matcher over EVERY unmatched purchase, not just the
    lines in the file. Previewing only the file once reported "1 to import,
    0 would match" against a collection where the click then matched 144 and
    wrote 144 hat prices.
    """
    from headroom.models.catalog import Purchase
    from headroom.services.catalog_service import (
        import_purchases,
        match_purchases_to_hats,
        preview_import,
    )

    await _hat_with(client, db_session, size="classic", model="A-Game Hydro")
    await _hat_with(client, db_session, size="classic", model="Trenches Thermal")

    # A purchase already on record and unmatched — the backlog.
    db_session.add(Purchase(
        source="test", item_title="A-Game Hydro - Black",
        model_name="A-Game Hydro", colorway="Black", quantity=1, price=79.0,
    ))
    await db_session.commit()

    new = [{"item_title": "Trenches Thermal - Camo", "price": 89.0, "quantity": 1}]

    preview = await preview_import(db_session, new)
    # The file contributes one match; the backlog contributes the other, and
    # the preview must say so rather than quietly counting only the first.
    assert preview["would_import"] == 1
    assert preview["would_match"] == 1
    assert preview["would_match_backlog"] == 1
    assert preview["would_match_total"] == 2

    await import_purchases(db_session, new)
    result = await match_purchases_to_hats(db_session)

    assert result["matched"] == preview["would_match_total"], (
        f"preview promised {preview['would_match_total']} matches, import made "
        f"{result['matched']}"
    )


# ---- regressions from the real order history --------------------------- #

from headroom.models.catalog import Purchase  # noqa: E402
from headroom.models.hat import Hat  # noqa: E402
from headroom.services import catalog_service  # noqa: E402


def _hat(**kw):
    """A hat with just the fields matching reads."""
    h = Hat(condition="new", size=kw.pop("size", "classic"), style="a_game")
    for k, v in kw.items():
        setattr(h, k, v)
    for attr in ("colors", "colorway", "artist_series", "construction",
                 "purchase_price", "model_name"):
        if not hasattr(h, attr) or getattr(h, attr, None) is None:
            if attr == "colors":
                h.colors = []
    return h


async def test_a_construction_in_the_colorway_half_does_not_rule_the_hat_out():
    """melin model names read `<line> <construction>`; receipts may put that
    word in EITHER half of the title, and the gate only sees the model half.

    Real miss: hat "Eagle Denim" against "Eagle Mill Union - Hickory Denim".
    `denim` sits in the colorway half, so containment failed and a hat with the
    right line, series, size and price to the cent was thrown out before
    anything else was scored.
    """
    purchase = Purchase(
        item_title="Eagle Mill Union - Hickory Denim",
        model_name="Eagle Mill Union",
        colorway="Hickory Denim",
        size="classic",
        price=200.0,
    )
    hat = _hat(model_name="Eagle Denim", artist_series="Union",
               construction="Denim", colorway="Navy Denium",
               size="classic", purchase_price=200.0)
    hat.colors = []

    assert catalog_service._match_score(purchase, hat) is not None


async def test_a_price_typed_off_the_receipt_outweighs_a_colorway_typo():
    """A colorway is a description; a hand-entered price is a fact.

    Both sides stating a colorway and disagreeing normally rules a hat out.
    That is right when the colorway is all you have and wrong when the owner
    typed the purchase price off the same order confirmation the line came
    from — "Navy Denium" against "Hickory Denim" is someone's words for a
    color, $200.00 against $200.00 is corroboration.
    """
    purchase = Purchase(
        item_title="Eagle Mill Union - Hickory Denim",
        model_name="Eagle Mill Union", colorway="Hickory Denim",
        size="classic", price=200.0,
    )
    priced = _hat(model_name="Eagle Denim", colorway="Navy Denium",
                  size="classic", purchase_price=200.0)
    priced.colors = []
    unpriced = _hat(model_name="Eagle Denim", colorway="Navy Denium",
                    size="classic", purchase_price=None)
    unpriced.colors = []

    assert catalog_service._match_score(purchase, priced) is not None
    assert catalog_service._match_score(purchase, unpriced) is None, (
        "without the corroborating price, two disagreeing colorways still veto"
    )


async def test_a_contradicting_construction_still_rules_a_hat_out():
    """The gate can now look past the construction word, so disagreement has
    to veto — or a Thermal hat takes a Hydro receipt's price when no Hydro hat
    is free."""
    purchase = Purchase(
        item_title="A-Game Infinite Hydro - Black", model_name="A-Game Infinite Hydro",
        colorway="Black", size="classic", price=79.0,
    )
    thermal = _hat(model_name="A-Game Thermal", construction="Thermal", size="classic")
    thermal.colors = []

    assert catalog_service._match_score(purchase, thermal) is None


async def test_the_assignment_is_maximum_not_merely_greedy():
    """Greedy leaves real matches unclaimed; augmenting paths do not.

    Two purchases, two hats. The generic line fits both hats; the specific line
    fits only the second. Greedy in the wrong order hands the shared hat to the
    generic line and strands the specific one — which is exactly what cost
    three matches on the real 294-line history.
    """
    generic = Purchase(item_title="Odysea Hydro - Black", model_name="Odysea Hydro",
                       colorway=None, size=None, price=79.0)
    specific = Purchase(item_title="Odysea Hydro - Black", model_name="Odysea Hydro",
                        colorway=None, size="small", price=79.0)
    classic = _hat(model_name="Odysea Hydro", size="classic")
    small = _hat(model_name="Odysea Hydro", size="small")
    classic.colors = []
    small.colors = []

    assigned = catalog_service.assign_purchases([generic, specific], [classic, small])

    assert len(assigned) == 2, (
        "both purchases are satisfiable at once — the generic line must give "
        "up the small hat so the sized line can have it"
    )
    assert assigned[id(specific)].hat is small


# ---------------- the backlog nothing ever looks at again -------------- #


async def _hat_named(client, db_session, model_name, **over):
    """A hat Claude has identified but that carries no colorway yet."""
    from headroom.models.hat import Hat

    body = {"condition": "new", "size": "classic", "style": "a_game", **over}
    hat_id = (await client.post("/api/hats", json=body)).json()["id"]
    row = await db_session.get(Hat, hat_id)
    row.model_name = model_name
    await db_session.commit()
    return hat_id


async def test_the_unclaimed_backlog_is_visible_without_re_importing(client, db_session):
    """Matching runs at the end of an IMPORT and nowhere else.

    So a purchase that had no hat to match at import time is never looked at
    again — not when a better matcher ships, and not when a re-analysis finally
    gives a hat the `model_name` that would have paired them. On the real
    collection that left **17 colorways and 16 prices** sitting in orders that
    were already imported, while the shared-price card told the owner a
    colorway was the one thing only they could supply.

    Reproduced here in the order it actually happens: import first, hat second.
    """
    await client.post(
        "/api/admin/purchases/import",
        json={"items": [{"item_title": "Odysea Hydro - Rain Camo", "price": 79.0}]},
    )
    # Nothing to match at import time.
    assert (await client.get("/api/admin/purchases/unclaimed")).json()["colorways"] == 0

    # The hat shows up afterwards — a re-analysis naming it, or a late add.
    hat_id = await _hat_named(client, db_session, "Odysea Hydro")

    unclaimed = (await client.get("/api/admin/purchases/unclaimed")).json()
    assert unclaimed["colorways"] == 1, "the backlog now has something for this hat"
    assert unclaimed["prices"] == 1

    # And the existing action claims it — asserted on the HAT, not on an id list
    # in the projection. The count is only meaningful if it is a count of the
    # right hat, and the outcome proves that where an echoed id merely restates
    # what the same query already said.
    assert (await client.post("/api/admin/purchases/match")).json()["matched"] == 1
    assert (await client.get(f"/api/hats/{hat_id}")).json()["colorway"] == "Rain Camo"

    # Reporting only what is left, so the offer disappears once taken.
    assert (await client.get("/api/admin/purchases/unclaimed")).json()["colorways"] == 0


async def test_the_offer_counts_only_what_it_would_actually_fill(client, db_session):
    """A hat that already has a colorway is not an offer.

    Without this the callout would promise work it does not do — the matcher
    links the purchase either way, but only writes a colorway into a blank.
    """
    from headroom.models.hat import Hat

    # Import FIRST, with no hats on the shelf — the order the real failure
    # happens in. An import runs matching itself, so importing last would leave
    # no backlog to measure and the test would pass for the wrong reason.
    await client.post("/api/admin/purchases/import", json={"items": [
        {"item_title": "Odysea Hydro - Rain Camo", "price": 79.0},
        {"item_title": "Trenches Icon Hydro - Deep Dive", "price": 79.0},
    ]})

    filled = await _hat_named(client, db_session, "Odysea Hydro")
    row = await db_session.get(Hat, filled)
    row.colorway = "Rain Camo"
    await db_session.commit()

    blank = await _hat_named(client, db_session, "Trenches Icon Hydro")

    unclaimed = (await client.get("/api/admin/purchases/unclaimed")).json()
    assert unclaimed["colorways"] == 1, "the filled hat is not an offer"

    # WHICH hat, proved by running the fill rather than by reading an id list
    # back out of the same query that produced the count. The blank gains a
    # colorway; the one that already had a colorway keeps its own.
    assert (await client.post("/api/admin/purchases/match")).json()["matched"] >= 1
    assert (await client.get(f"/api/hats/{blank}")).json()["colorway"] == "Deep Dive"
    assert (await client.get(f"/api/hats/{filled}")).json()["colorway"] == "Rain Camo"


async def test_reading_the_backlog_writes_nothing_even_in_one_session(client, db_session):
    """It is a GET driving the matcher's DRY RUN, so it must not link.

    Written at the service level deliberately. Two HTTP calls cannot detect
    this — each request gets its own session, so a dirty identity map is
    discarded with it and the test passes however broken the dry run is. The
    request-level version of this test survived sabotage; this one does not.

    What it pins is a PAIR, and neither half alone is a defect: today the dry
    run `continue`s before it mutates anything, AND it calls `expire_all()`
    before returning. Remove either one and this still passes — removing the
    mutation guard leaves nothing to discard, removing `expire_all` leaves
    nothing that mutated. It fails only in the state that is actually broken:
    a dry run that writes to the identity map and no longer expires it, where
    the next `commit()` on that session flushes a match nobody applied.
    """
    from headroom.models.hat import Hat
    from headroom.services import catalog_service

    hat_id = await _hat_named(client, db_session, "Odysea Hydro")
    await client.post(
        "/api/admin/purchases/import",
        json={"items": [{"item_title": "Odysea Hydro - Rain Camo", "price": 79.0}]},
    )
    # The import matched it already; unmatch to leave a real backlog.
    await client.post("/api/admin/purchases/unmatch-all")

    db_session.expire_all()
    assert (await db_session.get(Hat, hat_id)).colorway is None

    unclaimed = await catalog_service.unclaimed_from_purchases(db_session)
    assert unclaimed["colorways"] == 1, "there is something to offer"

    # The dangerous moment: anything the preview mutated would flush HERE.
    await db_session.commit()
    db_session.expire_all()

    assert (await db_session.get(Hat, hat_id)).colorway is None, (
        "reading the offer must not take it"
    )


async def test_the_backlog_requires_auth(anon_client):
    assert (await anon_client.get("/api/admin/purchases/unclaimed")).status_code == 401


# --------- validating an analyzer-read colorway against reality ---------- #


async def _catalog(db_session, pairs):
    from headroom.models.catalog import ColorwayEntry

    for model, colorway in pairs:
        db_session.add(ColorwayEntry(
            model_name=model, colorway=colorway,
            title=f"{model} - {colorway}", category="trenches",
        ))
    await db_session.commit()


async def test_a_colorway_is_accepted_only_when_the_product_is_real(client, db_session):
    """Claude reads a colorway off the hat, which is not the same as inferring
    one from its colors — but it is still a reading.

    A wrong colorway prices the hat as somebody else's product, which is
    strictly worse than the blank it replaced. Validating against the harvested
    catalog turns the answer into a lookup: whatever survives names a real good.

    Deliberately NOT done by handing Claude a candidate list — a menu invites a
    forced choice, and a wrong pick is indistinguishable from a right one. A
    validator applied afterwards can only ever reject.
    """
    from headroom.services.catalog_service import is_real_product

    await _catalog(db_session, [("Trenches Icon Hydro", "Deep Dive")])

    assert await is_real_product(db_session, "Trenches Icon Hydro", "Deep Dive")
    assert not await is_real_product(db_session, "Trenches Icon Hydro", "Hawaii 808 Camo"), (
        "a colorway melin does not sell for this model must be refused"
    )
    assert not await is_real_product(db_session, "Odysea Rope Hydro", "Deep Dive"), (
        "the right colorway on the wrong model is still not a product"
    )


async def test_a_single_word_colorway_does_not_validate_anything_containing_it(
    client, db_session
):
    """The shape that hid the leak: a ONE-TOKEN catalog colorway.

    The sibling test above passes under a broken validator, and it took two
    reviews to see why. Its catalog colorway is `Deep Dive` — two tokens — and
    the bug was containment (`catalog ⊆ hat`), which two tokens happen to
    defeat. Single-word colorways are the common case (Camo, Black, Navy,
    Bone), and every one of them validated anything that merely CONTAINED it:
    `{camo} ⊆ {hawaii, 808, camo}`, so `Hawaii 808 Camo` named a real product
    on the strength of a catalog that had never heard of it.

    That is the exact string the leaked-colorway repair produces, so the guard
    was blindest at precisely the input it was written for. And the cost is not
    a cosmetic false positive: `_apply_analyzed_colorway` WRITES what survives,
    and a stored colorway VETOES a purchase match in `_match_score` — the
    feature would have ruled hats out of their own receipts.

    Fixtures here are deliberately one token. A test whose fixture is more
    specific than production is a test that cannot see production's bug.
    """
    from headroom.services.catalog_service import is_real_product

    await _catalog(db_session, [("Odysea Rope Hydro", "Camo")])

    assert await is_real_product(db_session, "Odysea Rope Hydro", "Camo")
    assert not await is_real_product(
        db_session, "Odysea Rope Hydro", "Hawaii 808 Camo"
    ), "a colorway carrying words the catalog does not have names no product"
    assert not await is_real_product(db_session, "Odysea Rope Hydro", "Rain Camo"), (
        "adding a word to a real colorway does not make a second real product"
    )
    # The vaguer direction, which the previous fix closed — pinned here too, so
    # one test covers both ways this comparison has now been wrong.
    await _catalog(db_session, [("Trenches Icon Hydro", "Rain Camo")])
    assert not await is_real_product(db_session, "Trenches Icon Hydro", "Rain"), (
        "a colorway vaguer than the product is not that product"
    )


async def test_a_hat_named_for_the_family_still_validates(client, db_session):
    """`model_name` comes from a PHOTO, which cannot show the sub-line.

    So it lands on the family ("Odysea Hydro") where the catalog carries the
    full product ("Odysea Packable Hydro"). Token containment, the same
    asymmetry `_model_tier` uses — the hat's tokens must appear in the
    catalog's, never the reverse.
    """
    from headroom.services.catalog_service import is_real_product

    await _catalog(db_session, [("Odysea Packable Hydro", "Rain Camo")])

    assert await is_real_product(db_session, "Odysea Hydro", "Rain Camo")
    assert not await is_real_product(db_session, "Odysea Packable Rope Hydro", "Rain Camo"), (
        "a hat named MORE specifically than the catalog is not a match"
    )


async def test_a_missing_half_is_never_a_product(client, db_session):
    from headroom.services.catalog_service import is_real_product

    await _catalog(db_session, [("Trenches Icon Hydro", "Deep Dive")])

    assert not await is_real_product(db_session, "Trenches Icon Hydro", None)
    assert not await is_real_product(db_session, None, "Deep Dive")
    assert not await is_real_product(db_session, "Trenches Icon Hydro", "")


async def test_a_vaguer_colorway_than_the_product_is_refused(client, db_session):
    """The direction that was wrong, and the reason the guard existed at all.

    Containment on BOTH halves meant any SHORTER colorway validated: with only
    `Trenches Icon Hydro - Rain Camo` in the catalog, the colorways `Camo` and
    `Rain` both passed as real products. So the check rejected the specific
    readings it was meant to keep and accepted the vague ones it was meant to
    stop — precisely inverted.

    The two halves need OPPOSITE asymmetries. A model comes from a photo that
    cannot show the sub-line, so hat ⊆ catalog. A colorway is READ off the hat,
    so a correct reading is at least as specific as the catalog's: catalog ⊆
    hat.
    """
    from headroom.services.catalog_service import is_real_product

    await _catalog(db_session, [("Trenches Icon Hydro", "Rain Camo")])

    assert await is_real_product(db_session, "Trenches Icon Hydro", "Rain Camo"), (
        "the real product still validates"
    )
    assert not await is_real_product(db_session, "Trenches Icon Hydro", "Camo"), (
        "a colorway vaguer than the product is not that product"
    )
    assert not await is_real_product(db_session, "Trenches Icon Hydro", "Rain")
    # And the model half keeps its own, opposite asymmetry.
    assert await is_real_product(db_session, "Trenches Hydro", "Rain Camo"), (
        "a hat named for the family still matches the fuller catalog name"
    )
