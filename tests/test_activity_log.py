"""Tests for the append-only activity log."""

import pytest

pytestmark = pytest.mark.anyio


async def test_creating_a_hat_emits_log(client):
    created = (await client.post(
        "/api/hats", json={"condition": "new", "size": "classic", "style": "a_game"}
    )).json()
    resp = await client.get("/api/admin/activity-log")
    assert resp.status_code == 200
    rows = resp.json()
    # Tie the audit row to THIS hat — not merely "a hat.created row exists
    # somewhere". A logger that fired with the wrong entity_id (or twice) would
    # sail past a bare membership check but is exactly the audit bug that matters.
    created_rows = [
        r for r in rows
        if r["kind"] == "hat.created" and r["entity_id"] == created["id"]
    ]
    assert len(created_rows) == 1, rows
    assert created_rows[0]["entity_type"] == "hat"


async def test_dispose_emits_log_with_via(client):
    hat = (await client.post(
        "/api/hats", json={"condition": "new", "size": "classic", "style": "a_game"}
    )).json()
    await client.post(f"/api/hats/{hat['id']}/dispose", json={"via": "sold", "price": 50})
    resp = await client.get("/api/admin/activity-log?kind=hat.disposed")
    rows = resp.json()
    assert len(rows) == 1
    assert "sold" in rows[0]["summary"].lower()
    assert rows[0]["entity_id"] == hat["id"]


def _unwritable_audit_row(monkeypatch):
    """Make the NEXT audit row fail at commit — the audit transaction's own
    failure, as a "database is locked" would be, after the change it records
    has already committed."""
    from headroom.models.activity_log import ActivityLog
    from headroom.services import activity_service

    async def _bad_row(db, **_kw):
        db.add(ActivityLog(kind=None, entity_type="system", summary="unwritable"))

    monkeypatch.setattr(activity_service, "log_activity", _bad_row)


async def test_a_failed_audit_commit_leaves_the_session_usable(db_session, monkeypatch):
    """`log_and_commit` swallows the audit commit's failure — and must roll
    back, or the caller's session is stuck in a failed transaction and the
    very next query raises (`PendingRollbackError`)."""
    from sqlalchemy import select

    from headroom.models.hat import Hat
    from headroom.services import activity_service

    _unwritable_audit_row(monkeypatch)

    await activity_service.log_and_commit(db_session, kind="x", entity_type="system")

    assert (await db_session.execute(select(Hat.id))).all() == []


async def test_a_settings_change_is_not_a_500_when_only_its_audit_row_fails(
    client, monkeypatch
):
    """The model is saved before the audit row is written; a failed audit
    commit turned that saved change into a 500, and a retry."""
    _unwritable_audit_row(monkeypatch)

    resp = await client.put("/api/settings/model", json={"model_id": "claude-opus-5"})

    assert resp.status_code == 200, resp.text
    assert resp.json()["model_id"] == "claude-opus-5"


async def test_every_writer_goes_through_the_audit_seam(client, monkeypatch):
    """`activity_service.log_activity` is the seam the audit tests patch (see
    `_unwritable_audit_row`). A caller that imported it by NAME kept the
    original after the patch — the purchase import did — so a test of its
    audit failure would have exercised nothing."""
    from headroom.services import activity_service

    seen: list[str] = []
    real = activity_service.log_activity

    async def _spy(db, **kw):
        seen.append(kw["kind"])
        await real(db, **kw)

    monkeypatch.setattr(activity_service, "log_activity", _spy)

    resp = await client.post("/api/admin/purchases/import", json={"items": [{
        "item_title": "A-Game Hydro - Black", "price": 89.0, "size": "Classic",
        "order_ref": "900", "quantity": 1,
    }]})

    assert resp.status_code == 200, resp.text
    assert "purchase.imported" in seen, seen


async def _updated_rows(db_session, hat_id):
    import json

    from sqlalchemy import select

    from headroom.models.activity_log import ActivityLog

    db_session.expire_all()
    rows = (await db_session.execute(
        select(ActivityLog)
        .where(ActivityLog.kind == "hat.updated", ActivityLog.entity_id == hat_id)
        .order_by(ActivityLog.id)
    )).scalars().all()
    return [json.loads(r.details) for r in rows]


async def _notes_hat(client, db_session):
    """A hat whose notes already say something — written directly, so no
    audit row of its own precedes the session under test."""
    from sqlalchemy import update

    from headroom.models.hat import Hat

    hat = (await client.post("/api/hats", json={
        "condition": "new", "size": "classic", "style": "a_game",
    })).json()
    await db_session.execute(update(Hat).where(Hat.id == hat["id"]).values(owner_notes="Gift from Sam."))
    await db_session.commit()
    return hat["id"]


async def test_a_notes_editing_session_is_one_audit_row(client, db_session):
    """The notes box autosaves on each pause in typing; a paragraph typed in
    bursts wrote a full-text row per pause. One session is one row — the
    first, whose `previous` is the text from before the session."""
    hat_id = await _notes_hat(client, db_session)
    for text in ("Gift from Sam. Worn", "Gift from Sam. Worn to the", "Gift from Sam. Worn to the lake."):
        resp = await client.put(f"/api/hats/{hat_id}", json={"owner_notes": text})
        assert resp.status_code == 200, resp.text

    rows = await _updated_rows(db_session, hat_id)
    assert rows == [{"fields": ["owner_notes"], "previous": {"owner_notes": "Gift from Sam."}}]


async def test_another_change_between_notes_saves_starts_a_new_record(client, db_session):
    hat_id = await _notes_hat(client, db_session)
    await client.put(f"/api/hats/{hat_id}", json={"owner_notes": "a"})
    await client.put(f"/api/hats/{hat_id}", json={"brand": "melin"})
    await client.put(f"/api/hats/{hat_id}", json={"owner_notes": "ab"})

    fields = [r["fields"] for r in await _updated_rows(db_session, hat_id)]
    assert fields == [["owner_notes"], ["brand"], ["owner_notes"]]


async def test_a_notes_save_after_a_long_pause_is_its_own_record(client, db_session):
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import update

    from headroom.models.activity_log import ActivityLog
    from headroom.services import hat_service

    hat_id = await _notes_hat(client, db_session)
    await client.put(f"/api/hats/{hat_id}", json={"owner_notes": "first session"})
    # Age the session's row past the window.
    long_ago = datetime.now(timezone.utc) - hat_service.NOTES_SESSION - timedelta(minutes=1)
    await db_session.execute(
        update(ActivityLog).where(ActivityLog.entity_id == hat_id).values(occurred_at=long_ago)
    )
    await db_session.commit()
    await client.put(f"/api/hats/{hat_id}", json={"owner_notes": "second session"})

    previous = [r["previous"] for r in await _updated_rows(db_session, hat_id)]
    assert previous == [{"owner_notes": "Gift from Sam."}, {"owner_notes": "first session"}]


async def test_count_endpoint(client):
    before = (await client.get("/api/admin/activity-log/count")).json()["count"]
    await client.post(
        "/api/hats", json={"condition": "new", "size": "classic", "style": "a_game"}
    )
    resp = await client.get("/api/admin/activity-log/count")
    assert resp.status_code == 200
    # Exactly one more row than before — a `>= 1` passed on the login row the
    # fixture writes, whether or not creating a hat was audited at all.
    assert resp.json()["count"] == before + 1
