"""The backup gate's question — "has the collection changed?" — answered from
rows, not from the database file's size and mtime.

Against the file, the nightly re-pricing sweep (which stamps every hat it
consults, price moved or not), the shutdown WAL checkpoint, the retention
prune and every login all read as changes, so a scheduled backup was written
every day and the fixed-size window covered days instead of changes.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import text

from headroom.models.activity_log import ActivityLog
from headroom.models.hat import Hat
from headroom.models.user import AuthSession, PasskeyCredential, User
from headroom.services import collection_fingerprint, hat_analysis_pipeline, repricing

pytestmark = pytest.mark.anyio


def _path(engine) -> Path:
    return Path(engine.url.database)


async def _seed_hat(factory) -> int:
    async with factory() as db:
        hat = Hat(
            brand="melin", model_name="Odysea Hydro", style="cap",
            condition="excellent", size="classic", resale_price=80.0,
            # Long ago, so the sweep's UPDATE visibly moves the `onupdate`
            # stamp — a same-second insert and sweep would leave it equal.
            updated_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        )
        db.add(hat)
        await db.commit()
        return hat.id


async def test_a_sweep_that_moved_no_price_is_not_a_change(file_engine, monkeypatch):
    """The reported case: 'consulted, unchanged' for every hat, and the gate
    still saw a new database because every hat got a fresh stamp."""
    engine, factory = file_engine
    await _seed_hat(factory)
    before = collection_fingerprint.digest(_path(engine))

    async def consulted_unchanged(hat):
        return hat_analysis_pipeline.RESALE_PRICED

    monkeypatch.setattr(hat_analysis_pipeline, "refresh_melin_resale", consulted_unchanged)
    monkeypatch.setenv("HEADROOM_REPRICING_DELAY_SECONDS", "0")
    repriced, considered = await repricing.reprice_once(factory)
    assert (repriced, considered) == (0, 1), "the premise: consulted, nothing moved"

    async with factory() as db:
        stamped = (await db.execute(text("SELECT resale_checked_at FROM hats"))).scalar_one()
    assert stamped is not None, "the premise: the sweep did write the stamp"

    assert collection_fingerprint.digest(_path(engine)) == before


async def test_a_sweep_whose_listing_count_moved_but_not_its_price_is_not_a_change(
    file_engine, monkeypatch
):
    """Through the REAL resale writer. It rewrites the price's source label on
    every consult — "median of 8 live … listings" — and the count in it moves
    with every listing that comes or goes on a live marketplace, median
    unchanged. So a sweep that moved no price still reopened the gate most
    nights, the same days-not-changes window the stamp exclusion removed."""
    from headroom.services import melin_recap

    engine, factory = file_engine
    await _seed_hat(factory)
    listings = {"count": 8}

    async def stats(*_a, **_kw):
        return {
            "median": 80.0, "count": listings["count"], "sample": "model",
            "size_matched": False, "condition_matched": False,
        }

    monkeypatch.setattr(melin_recap, "fetch_resale_stats", stats)
    monkeypatch.setenv("HEADROOM_REPRICING_DELAY_SECONDS", "0")
    await repricing.reprice_once(factory)
    before = collection_fingerprint.digest(_path(engine))

    listings["count"] = 9
    await repricing.reprice_once(factory)

    async with factory() as db:
        source = (await db.execute(text("SELECT resale_price_source FROM hats"))).scalar_one()
    assert "median of 9" in source, "the premise: the label was rewritten"
    assert collection_fingerprint.digest(_path(engine)) == before


async def test_a_sweep_that_moved_a_price_is_a_change(file_engine, monkeypatch):
    engine, factory = file_engine
    await _seed_hat(factory)
    before = collection_fingerprint.digest(_path(engine))

    async def moved(hat):
        hat.resale_price = 95.0
        return hat_analysis_pipeline.RESALE_PRICED

    monkeypatch.setattr(hat_analysis_pipeline, "refresh_melin_resale", moved)
    monkeypatch.setenv("HEADROOM_REPRICING_DELAY_SECONDS", "0")
    await repricing.reprice_once(factory)

    assert collection_fingerprint.digest(_path(engine)) != before


async def test_bookkeeping_and_a_checkpoint_are_not_changes(file_engine):
    """Logins, audit rows, a passkey's counter and the shutdown checkpoint all
    rewrite the file; none of them changes what a restore would give back."""
    engine, factory = file_engine
    await _seed_hat(factory)
    async with factory() as db:
        user = User(username="owner", password_hash="x", api_token="hr_t")
        db.add(user)
        await db.commit()
        passkey = PasskeyCredential(
            user_id=user.id, credential_id="cred", public_key="key", sign_count=1
        )
        db.add(passkey)
        await db.commit()
    before = collection_fingerprint.digest(_path(engine))

    async with factory() as db:
        db.add(AuthSession(
            id="s1", user_id=user.id,
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        ))
        db.add(ActivityLog(kind="auth.login", entity_type="system", summary="login"))
        cred = await db.get(PasskeyCredential, passkey.id)
        cred.sign_count += 1
        await db.commit()
        await db.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))

    assert collection_fingerprint.digest(_path(engine)) == before


async def test_a_real_edit_is_a_change(file_engine):
    engine, factory = file_engine
    hat_id = await _seed_hat(factory)
    before = collection_fingerprint.digest(_path(engine))

    async with factory() as db:
        hat = await db.get(Hat, hat_id)
        hat.owner_notes = "found at the swap meet"
        await db.commit()

    assert collection_fingerprint.digest(_path(engine)) != before


async def test_a_deleted_row_is_a_change(file_engine):
    engine, factory = file_engine
    hat_id = await _seed_hat(factory)
    before = collection_fingerprint.digest(_path(engine))

    async with factory() as db:
        await db.delete(await db.get(Hat, hat_id))
        await db.commit()

    assert collection_fingerprint.digest(_path(engine)) != before
