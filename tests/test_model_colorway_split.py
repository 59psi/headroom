"""The analyzer had nowhere to put a colorway, so it put it in the model name.

melin names its goods `<Model> - <Colorway>`. The Claude tool schema carried
`model_name` and no `colorway`, so a colorway plainly readable off the hat —
embroidered, printed, on the woven label — was appended to `model_name`.

That field is the GATE for both purchase matching (`_model_tier` requires every
hat token to appear in the receipt) and product pricing (`_product_comp`
requires every model token to appear in the product). One foreign token makes a
hat unmatchable and unpriceable.

Measured on the real collection before the fix: **89 of 235** model names
matched no melin product at all, 35 carried a literal separator, and the
foreign tokens were colorway words — `camo`, `808`, `watercolor`, `gopro`,
`maui strong`. Splitting on the separator alone took usable names from **146 to
174 of 235** with no API call.
"""

from __future__ import annotations

import pytest

from headroom.services.hat_analysis_pipeline import _split_model_and_colorway

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize(
    ("stored", "model", "colorway"),
    [
        # The shapes actually found in the live collection.
        ("Trenches Hydro — Hawaii 808 Camo", "Trenches Hydro", "Hawaii 808 Camo"),
        ("Odysea Hydro — 23XI Racing", "Odysea Hydro", "23XI Racing"),
        ("Odysea Rope Hydro (WATERCOLOR)", "Odysea Rope Hydro", "WATERCOLOR"),
        ("Trenches Hydro (GoPro)", "Trenches Hydro", "GoPro"),
        ("Trenches (Curl Surf)", "Trenches", "Curl Surf"),
        ("A-Game Hydro - Heather Grey", "A-Game Hydro", "Heather Grey"),
        # Left alone: no separator means nothing marks where the model ends,
        # and guessing is how a correct name gets truncated.
        ("Trenches Icon Camo", "Trenches Icon Camo", None),
        ("Odysea Mesh Trucker", "Odysea Mesh Trucker", None),
        # A hyphenated model is NOT a separator — this is the trap.
        ("A-Game Hydro", "A-Game Hydro", None),
        ("A-Game", "A-Game", None),
        (None, None, None),
    ],
)
async def test_a_leaked_colorway_is_split_off_the_model(stored, model, colorway):
    assert _split_model_and_colorway(stored) == (model, colorway)


async def test_the_hyphen_in_a_game_is_not_a_separator():
    """The single most dangerous false positive.

    `A-Game` is a melin line and the most common one in the collection. A naive
    split on "-" turns it into model "A" plus colorway "Game", which matches no
    product and would break every A-Game hat — trading 35 broken names for a
    larger number of newly broken ones. Only a SPACED separator counts.
    """
    assert _split_model_and_colorway("A-Game Hydro") == ("A-Game Hydro", None)
    assert _split_model_and_colorway("A-Game HYDROLite") == ("A-Game HYDROLite", None)


async def test_the_backfill_repairs_stored_names_without_an_api_call(client, db_session):
    """Fixing the schema alone leaves a name depending on WHEN it was analyzed.

    Same reason `retail_pricing.backfill_retail_prices` exists, same one-time
    lifespan flag.
    """
    from headroom.models.hat import Hat
    from headroom.services.hat_analysis_pipeline import backfill_split_model_names

    async def _hat(model_name):
        body = {"condition": "new", "size": "classic", "style": "trenches"}
        hat_id = (await client.post("/api/hats", json=body)).json()["id"]
        row = await db_session.get(Hat, hat_id)
        row.model_name = model_name
        await db_session.commit()
        return hat_id

    leaked = await _hat("Trenches Hydro — Hawaii 808 Camo")
    clean = await _hat("Trenches Icon Hydro")
    a_game = await _hat("A-Game Hydro")

    changed = await backfill_split_model_names(db_session)
    assert changed == 1, "only the name carrying a separator is touched"

    db_session.expire_all()
    assert (await db_session.get(Hat, leaked)).model_name == "Trenches Hydro"
    assert (await db_session.get(Hat, clean)).model_name == "Trenches Icon Hydro"
    assert (await db_session.get(Hat, a_game)).model_name == "A-Game Hydro"


async def test_the_backfill_does_not_store_the_leaked_colorway(client, db_session):
    """The colorway half is dropped, not saved.

    `_apply_analyzed_colorway` accepts a colorway only when the pair names a
    real harvested product. Measured against the live catalog, NONE of the
    leaked halves do — they are collab and limited-run drops that no longer
    appear on the resale market. Storing them anyway would trust a string
    exactly where there is no evidence for it, and a wrong colorway prices the
    hat as somebody else's product.
    """
    from headroom.models.hat import Hat
    from headroom.services.hat_analysis_pipeline import backfill_split_model_names

    body = {"condition": "new", "size": "classic", "style": "trenches"}
    hat_id = (await client.post("/api/hats", json=body)).json()["id"]
    row = await db_session.get(Hat, hat_id)
    row.model_name = "Trenches Hydro — Hawaii 808 Camo"
    await db_session.commit()

    await backfill_split_model_names(db_session)

    db_session.expire_all()
    hat = await db_session.get(Hat, hat_id)
    assert hat.model_name == "Trenches Hydro"
    assert hat.colorway is None, "an unvalidated colorway is worse than a blank"


async def test_the_backfill_records_what_it_destroyed(client, db_session):
    """This is the one repair in the app that DESTROYS information.

    `retail_prices_v2` re-derives a price that can be re-derived again;
    "Trenches (Curl Surf)" -> "Trenches" discards the only record that the drop
    was a Curl Surf. It runs once, unattended, behind a flag, with no dry run —
    so the activity log is the undo, and without it the split is unrecoverable
    from inside the app.

    The record is written in the SAME transaction as the change. It used to
    commit the truncated names first and log afterwards, which left a window
    where the damage was durable and its only record was not — a crash there
    destroyed the names with nothing saying what they had been, which is the
    exact failure keeping a record is supposed to prevent.

    The field is `dropped`, not `colorway_dropped`: the splitter also takes
    parentheses, and those carry sizes and pack counts as often as artwork.
    Recording "(Small)" under a key called colorway would assert a
    classification nothing at this point has made.
    """
    import json

    from headroom.models.hat import Hat
    from headroom.services.hat_analysis_pipeline import backfill_split_model_names

    body = {"condition": "new", "size": "classic", "style": "trenches"}
    hat_id = (await client.post("/api/hats", json=body)).json()["id"]
    row = await db_session.get(Hat, hat_id)
    row.model_name = "Trenches (Curl Surf)"
    await db_session.commit()

    await backfill_split_model_names(db_session)

    rows = (await client.get("/api/admin/activity-log")).json()
    entry = next(r for r in rows if r["kind"] == "hat.model_name_split")
    repaired = json.loads(entry["details"])["repaired"]

    assert repaired == [{
        "hat_id": hat_id,
        "was": "Trenches (Curl Surf)",
        "now": "Trenches",
        "dropped": "Curl Surf",
    }], "the original name and the dropped half must both be recoverable"


async def test_the_record_and_the_damage_land_together(client, db_session, monkeypatch):
    """Atomicity, not ordering — pinned because the ordering bug was invisible.

    Committing the names and then logging leaves the destruction durable while
    its only undo is still uncommitted. Nothing observable distinguishes that
    from the correct version on a run that succeeds, which is why it survived
    a release: the test asserted the row EXISTS, and it did.

    Here the commit is made to fail. The names must still be intact — a repair
    that cannot record what it did must not do it.
    """
    from headroom.models.hat import Hat
    from headroom.services import activity_service
    from headroom.services.hat_analysis_pipeline import backfill_split_model_names

    body = {"condition": "new", "size": "classic", "style": "trenches"}
    hat_id = (await client.post("/api/hats", json=body)).json()["id"]
    row = await db_session.get(Hat, hat_id)
    row.model_name = "Trenches (Curl Surf)"
    await db_session.commit()

    async def refuse(*a, **kw):
        raise RuntimeError("could not record the repair")

    # Patched at `activity_service`, not at the pipeline: the backfill imports
    # the name inside the function, so a module-level rebind there is replaced
    # on every call and the patch would silently do nothing.
    monkeypatch.setattr(activity_service, "log_activity", refuse)

    with pytest.raises(RuntimeError):
        await backfill_split_model_names(db_session)
    await db_session.rollback()

    row = await db_session.get(Hat, hat_id)
    await db_session.refresh(row)
    assert row.model_name == "Trenches (Curl Surf)", (
        "the name must survive a repair that could not record itself"
    )


async def test_the_backfill_logs_nothing_when_it_changes_nothing(client, db_session):
    """An audit row for a no-op run is noise in the one log someone reads when
    something has gone wrong."""
    from headroom.models.hat import Hat
    from headroom.services.hat_analysis_pipeline import backfill_split_model_names

    body = {"condition": "new", "size": "classic", "style": "trenches"}
    hat_id = (await client.post("/api/hats", json=body)).json()["id"]
    row = await db_session.get(Hat, hat_id)
    row.model_name = "Trenches Icon Hydro"
    await db_session.commit()

    assert await backfill_split_model_names(db_session) == 0

    rows = (await client.get("/api/admin/activity-log")).json()
    assert not [r for r in rows if r["kind"] == "hat.model_name_split"]
