"""Every door a hat's data comes in through validates, audits and restores it.

Grouped by door: the PUT, the colors PUT, the wear taps, the photo upload, the
re-cut. Each was a path that bypassed a rule another path enforced — a NOT
NULL column reached with null, a date rule on one of three writers, a write
the activity log never saw, a temp file a 413 left behind.
"""

from __future__ import annotations

import io
import json
from datetime import date, datetime, timedelta, timezone

import pytest
from PIL import Image
from sqlalchemy import select

pytestmark = pytest.mark.anyio


async def _hat(client, **fields) -> dict:
    resp = await client.post(
        "/api/hats", json={"condition": "new", "size": "classic", "style": "a_game", **fields}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _kinds(client, *, limit: int = 100) -> list[str]:
    return [r["kind"] for r in (await client.get(f"/api/admin/activity-log?limit={limit}")).json()]


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (40, 90, 200)).save(buf, "JPEG")
    return buf.getvalue()


# ---- PUT /api/hats/{id} ------------------------------------------------ #


@pytest.mark.parametrize("field", ["condition", "size", "style", "limited_edition"])
async def test_null_for_a_required_column_is_a_422_not_a_500(client, field):
    """Omitted means "leave it"; these columns have no null. An explicit null
    used to reach the commit and come back as an IntegrityError — a 500 and
    an `error.unhandled` row for a malformed request."""
    hat = await _hat(client)

    resp = await client.put(f"/api/hats/{hat['id']}", json={field: None})

    assert resp.status_code == 422, resp.text
    assert "error.unhandled" not in await _kinds(client)
    # And omitting it is still fine.
    assert (await client.put(f"/api/hats/{hat['id']}", json={})).status_code == 200


async def test_a_future_last_worn_date_is_refused_on_every_door(client):
    """The rule lived on the wear tap alone. The PUT and the create stored
    2099-01-01, and since a wear only moves the date forward, no real wear
    could ever correct it."""
    hat = await _hat(client)

    assert (
        await client.put(f"/api/hats/{hat['id']}", json={"date_last_worn": "2099-01-01"})
    ).status_code == 422
    assert (
        await client.post(
            "/api/hats",
            json={"condition": "new", "size": "classic", "style": "a_game",
                  "date_last_worn": "2099-01-01"},
        )
    ).status_code == 422
    assert (
        await client.post(f"/api/hats/{hat['id']}/wear", json={"worn_at": "2099-01-01"})
    ).status_code == 422
    # A real date still goes through.
    assert (
        await client.put(f"/api/hats/{hat['id']}", json={"date_last_worn": "2024-01-01"})
    ).status_code == 200


async def test_tomorrow_by_utc_is_allowed_whatever_the_hosts_zone(monkeypatch):
    """The bound is UTC's date plus one — the latest calendar day it is
    anywhere. It read the HOST's `date.today()`, so on a machine at UTC-12 a
    client's genuine "tomorrow" (by UTC) was refused as the future."""
    from headroom.schemas import hat as hat_schema

    utc_now = datetime(2026, 9, 28, 6, 0, tzinfo=timezone.utc)

    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return utc_now if tz is not None else utc_now.replace(tzinfo=None)

    class _HostDate(date):
        @classmethod
        def today(cls):
            return date(2026, 9, 27)  # a host twelve hours behind UTC

    monkeypatch.setattr(hat_schema, "datetime", _FrozenDatetime)
    monkeypatch.setattr(hat_schema, "date", _HostDate)

    assert hat_schema.WearCreate(worn_at="2026-09-29").worn_at == date(2026, 9, 29)
    with pytest.raises(ValueError):
        hat_schema.WearCreate(worn_at="2026-09-30")


# ---- PUT /api/hats/{id}/colors ----------------------------------------- #


async def test_color_text_is_cleaned_and_capped_like_every_other_name(client):
    hat = await _hat(client)

    stored = await client.put(
        f"/api/hats/{hat['id']}/colors",
        json={"colors": [{"color_name": "evi‮l\u0000 ", "general_color": "gre‮en",
                          "hex_value": "#FF0000", "tier": "accent"}]},
    )
    assert stored.status_code == 200, stored.text
    color = stored.json()["colors"][0]
    assert color["color_name"] == "evil"
    assert color["general_color"] == "green"
    assert color["hex_value"] == "#ff0000"
    assert color["tier"] == "accent"

    too_long = await client.put(
        f"/api/hats/{hat['id']}/colors",
        json={"colors": [{"color_name": "x" * 51, "hex_value": "#ff0000"}]},
    )
    assert too_long.status_code == 422


@pytest.mark.parametrize(
    "bad",
    [
        {"color_name": "navy", "hex_value": "javascript:alert(1)"},
        {"color_name": "navy", "hex_value": "#12"},
        {"color_name": "navy", "hex_value": "#123456", "tier": "banana"},
    ],
)
async def test_a_color_that_is_not_a_color_is_refused(client, bad):
    hat = await _hat(client)

    resp = await client.put(f"/api/hats/{hat['id']}/colors", json={"colors": [bad]})

    assert resp.status_code == 422, resp.text


async def test_hex_spellings_are_normalized_rather_than_refused(client):
    hat = await _hat(client)

    resp = await client.put(
        f"/api/hats/{hat['id']}/colors",
        json={"colors": [{"color_name": "a", "hex_value": "8CB9E1"},
                         {"color_name": "b", "hex_value": "#abc"}]},
    )

    assert resp.status_code == 200, resp.text
    assert [c["hex_value"] for c in resp.json()["colors"]] == ["#8cb9e1", "#aabbcc"]


async def test_the_palette_is_bounded(client):
    """3,000 rows in one body were accepted."""
    from headroom.schemas.hat import MAX_COLORS_PER_HAT

    hat = await _hat(client)
    body = {"colors": [{"color_name": f"c{i}", "hex_value": "#123456"}
                       for i in range(MAX_COLORS_PER_HAT + 1)]}

    assert (await client.put(f"/api/hats/{hat['id']}/colors", json=body)).status_code == 422


async def test_rank_is_optional_and_a_blank_name_takes_the_palette_name(client):
    """`dominance_rank` was REQUIRED and then thrown away. And a blank name is
    named after its hex, not stored as nothing."""
    from headroom.services.color_extraction import normalize_hex_name

    hat = await _hat(client)

    resp = await client.put(
        f"/api/hats/{hat['id']}/colors",
        json={"colors": [{"color_name": "   ", "hex_value": "#ff0000"}]},
    )

    assert resp.status_code == 200, resp.text
    color = resp.json()["colors"][0]
    assert color["color_name"] == normalize_hex_name("#ff0000", "")
    assert color["dominance_rank"] == 1


async def test_a_colors_edit_is_audited(client):
    hat = await _hat(client)
    await client.put(
        f"/api/hats/{hat['id']}/colors",
        json={"colors": [{"color_name": "navy", "hex_value": "#1c2541"}]},
    )

    rows = (await client.get("/api/admin/activity-log?limit=20")).json()
    edit = next(r for r in rows if r["kind"] == "hat.colors_updated")
    assert edit["entity_id"] == hat["id"]
    assert json.loads(edit["details"])["colors"] == ["navy"]


# ---- the wear taps ----------------------------------------------------- #


async def test_a_tap_with_no_date_lands_on_the_servers_own_day(client):
    """Not UTC's: `owner_today` is the host's calendar day, which is the
    owner's when the box is in their house (`TZ`)."""
    from headroom.services import hat_service

    hat = await _hat(client)

    body = (await client.post(f"/api/hats/{hat['id']}/wear", json={})).json()

    assert body["date_last_worn"] == hat_service.owner_today().isoformat()


async def test_owner_today_follows_the_hosts_zone(monkeypatch):
    from headroom.services import hat_service

    class _Frozen(datetime):
        """03:00 UTC on the 28th, on a host at UTC-7 — 20:00 on the 27th."""

        @classmethod
        def now(cls, tz=None):
            return cls(2026, 9, 28, 3, 0, tzinfo=timezone.utc)

        def astimezone(self, tz=None):
            host = timezone(timedelta(hours=-7))
            return datetime.astimezone(self, tz or host)

    monkeypatch.setattr(hat_service, "datetime", _Frozen)

    assert hat_service.owner_today() == date(2026, 9, 27)


async def test_undoing_a_tap_restores_the_date_it_replaced(client):
    """A hand-entered last-worn date, tapped over by mistake and undone, was
    erased: the undo treated the wear log as the only source of the date."""
    hat = await _hat(client)
    await client.put(f"/api/hats/{hat['id']}", json={"date_last_worn": "2024-01-01"})

    tapped = (await client.post(f"/api/hats/{hat['id']}/wear", json={"worn_at": "2025-06-01"})).json()
    assert tapped["date_last_worn"] == "2025-06-01"

    undone = (await client.delete(f"/api/hats/{hat['id']}/wear/latest")).json()
    assert undone["date_last_worn"] == "2024-01-01"
    assert undone["wear_count"] == 0


async def test_the_replaced_date_outlives_the_activity_log(client, db_session):
    """The date a tap replaced is the wear row's to keep, not the audit trail's.

    It was first recovered from the tap's `hat.worn` activity row — and the
    activity log is pruned by age, so once retention took that row, undoing
    the tap erased the hand-typed date exactly as before the fix. Deleting
    every activity row here is what `prune_activity` does to rows past the
    window.
    """
    from sqlalchemy import delete

    from headroom.models.activity_log import ActivityLog

    hat = await _hat(client)
    await client.put(f"/api/hats/{hat['id']}", json={"date_last_worn": "2024-01-01"})
    await client.post(f"/api/hats/{hat['id']}/wear", json={"worn_at": "2025-06-01"})
    await db_session.execute(delete(ActivityLog))
    await db_session.commit()

    undone = (await client.delete(f"/api/hats/{hat['id']}/wear/latest")).json()

    assert undone["date_last_worn"] == "2024-01-01"


async def test_undo_keeps_a_later_backdated_wear_over_the_replaced_date(client):
    hat = await _hat(client)
    await client.post(f"/api/hats/{hat['id']}/wear", json={"worn_at": "2025-06-01"})
    await client.post(f"/api/hats/{hat['id']}/wear", json={"worn_at": "2025-01-05"})

    undone = (await client.delete(f"/api/hats/{hat['id']}/wear/latest")).json()

    assert undone["date_last_worn"] == "2025-01-05"


async def test_undo_leaves_a_date_the_undone_wear_did_not_set(client):
    hat = await _hat(client)
    await client.post(f"/api/hats/{hat['id']}/wear", json={"worn_at": "2025-06-01"})
    await client.put(f"/api/hats/{hat['id']}", json={"date_last_worn": "2025-07-04"})

    undone = (await client.delete(f"/api/hats/{hat['id']}/wear/latest")).json()

    assert undone["date_last_worn"] == "2025-07-04"


async def test_wear_taps_and_undos_are_audited(client):
    hat = await _hat(client)
    await client.post(f"/api/hats/{hat['id']}/wear", json={"worn_at": "2025-06-01"})
    await client.delete(f"/api/hats/{hat['id']}/wear/latest")

    kinds = await _kinds(client)
    assert "hat.worn" in kinds
    assert "hat.wear_undone" in kinds


# ---- the photo upload -------------------------------------------------- #


async def test_an_oversize_photo_leaves_no_temp_file_behind(client, monkeypatch, tmp_path):
    """The temp file was created OUTSIDE the `try` that deleted it, so every
    413 left a file the size of the cap in the temp dir — on a Pi, the SD card."""
    import tempfile

    from headroom.utils import upload as upload_utils

    spool = tmp_path / "spool"
    spool.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(spool))
    monkeypatch.setattr(upload_utils, "MAX_PHOTO_BYTES", 1024)
    hat = await _hat(client)

    resp = await client.post(
        f"/api/hats/{hat['id']}/photo",
        files={"photo": ("big.jpg", io.BytesIO(b"x" * 8192), "image/jpeg")},
    )

    assert resp.status_code == 413
    assert list(spool.iterdir()) == []


async def test_a_photo_upload_is_audited(client):
    hat = await _hat(client)

    resp = await client.post(
        f"/api/hats/{hat['id']}/photo", files={"photo": ("h.jpg", _jpeg(), "image/jpeg")}
    )

    assert resp.status_code == 200, resp.text
    assert "hat.photo_replaced" in await _kinds(client)


# ---- the re-cut -------------------------------------------------------- #


async def test_a_recut_in_flight_publishes_its_stage(client, db_session):
    """A re-cut leaves the analysis record — status included — alone, so a
    stage keyed on `pending` alone was hidden for its whole run: the page
    showed the uncut original with no sign anything was happening, and had
    no reason to poll."""
    from headroom.models.hat import Hat

    hat = await _hat(client)
    row = (await db_session.execute(select(Hat).where(Hat.id == hat["id"]))).scalar_one()
    row.original_path = "hats/original.jpg"
    row.photo_path = "hats/original.jpg"  # what `/recut` points it at
    row.analysis_status = "ok"
    row.analysis_stage = "cutout"
    await db_session.commit()

    during = (await client.get(f"/api/hats/{hat['id']}")).json()
    assert during["analysis_stage"] == "cutout"

    row.photo_path = "hats/original.png"  # the new cutout landed
    await db_session.commit()
    after = (await client.get(f"/api/hats/{hat['id']}")).json()
    assert after["analysis_stage"] is None, "a stale stage must not outlive the work"


async def test_a_failed_inline_recut_does_not_report_a_cut_in_progress(client, monkeypatch):
    """With no worker the re-cut runs inline; if it fails, nothing is running,
    so the stage must not survive to read as a cut that never finishes — and
    the hat goes back to the cutout it had, rather than keeping the uncut
    original the re-cut pointed it at. The analysis record is a re-cut's to
    leave alone, failure included: stamping it `error` put a hat whose
    analysis was fine on the failed-analyses badge."""
    from headroom.services import hat_analysis_pipeline

    async def _cutout(input_path, output_path):
        out = output_path.with_suffix(".png")
        Image.new("RGBA", (32, 32), (200, 30, 90, 255)).save(out, "PNG")
        return out

    monkeypatch.setattr("headroom.services.background_removal.remove_background", _cutout)
    hat = await _hat(client)
    uploaded = (await client.post(
        f"/api/hats/{hat['id']}/photo", files={"photo": ("h.jpg", _jpeg(), "image/jpeg")}
    )).json()
    assert uploaded["original_path"], "precondition: an original was kept"

    async def _boom(*_a, **_k):
        raise RuntimeError("rembg exploded")

    monkeypatch.setattr(hat_analysis_pipeline, "finalize_hat_photo", _boom)

    body = (await client.post(f"/api/hats/{hat['id']}/recut")).json()

    assert body["analysis_stage"] is None
    assert body["photo_path"] == uploaded["photo_path"], "the cutout it had"
    assert body["analysis_status"] == uploaded["analysis_status"]


# ---- cases and rooms --------------------------------------------------- #


async def test_case_thumbnails_follow_shelf_order(client, db_session):
    """`hat_thumbs` came out of an unordered relationship; the comment said
    "newest-first-ish (id order)". It is shelf order now — the order the
    display ids run — which differs from id order once a hat is restored."""
    from headroom.models.hat import Hat

    case = (await client.post("/api/cases", json={"case_type": "archive"})).json()
    first = await _hat(client, case_id=case["id"])
    second = await _hat(client, case_id=case["id"])
    for h, name in ((first, "first"), (second, "second")):
        row = (await db_session.execute(select(Hat).where(Hat.id == h["id"]))).scalar_one()
        row.photo_path = f"hats/{name}.png"
    await db_session.commit()
    # Dispose and restore the FIRST hat: it comes back at the end of the shelf.
    await client.post(f"/api/hats/{first['id']}/dispose", json={"via": "gifted"})
    await client.delete(f"/api/hats/{first['id']}/dispose")

    listed = next(c for c in (await client.get("/api/cases")).json() if c["id"] == case["id"])

    assert listed["hat_thumbs"] == ["hats/second.png", "hats/first.png"]


async def test_every_room_response_counts_its_loose_hats(client):
    """The rename and set-default responses reported `loose_hat_count: 0` from
    a parameter default, for a room with hats on its shelf."""
    room = (await client.post("/api/rooms", json={"name": "Closet"})).json()
    for _ in range(2):
        await _hat(client, room_id=room["id"])

    renamed = (await client.put(f"/api/rooms/{room['id']}", json={"name": "Hall"})).json()
    defaulted = (await client.post(f"/api/rooms/{room['id']}/default")).json()

    assert renamed["loose_hat_count"] == 2
    assert defaulted["loose_hat_count"] == 2


async def test_a_retype_racing_creates_takes_its_own_sequence_number(file_client):
    """A retype allocates a display id — read-then-write, the race
    `create_case` serializes. Outside the placement lock a retype and a
    create of the target type took the same `D-00N` and one died on the
    unique `display_id` (a 500)."""
    import asyncio

    archives = [
        (await file_client.post("/api/cases", json={"case_type": "archive"})).json()["display_id"]
        for _ in range(3)
    ]

    responses = await asyncio.gather(
        *[file_client.put(f"/api/cases/{d}", json={"case_type": "daily_wear"}) for d in archives],
        *[file_client.post("/api/cases", json={"case_type": "daily_wear"}) for _ in range(3)],
    )

    assert all(r.status_code in (200, 201) for r in responses), [r.text for r in responses]
    ids = [r.json()["display_id"] for r in responses]
    assert len(set(ids)) == 6, ids


async def test_room_renames_and_case_edits_are_audited(client):
    room = (await client.post("/api/rooms", json={"name": "Closet"})).json()
    case = (await client.post("/api/cases", json={"case_type": "archive"})).json()

    await client.put(f"/api/rooms/{room['id']}", json={"name": "Hall"})
    await client.put(f"/api/cases/{case['display_id']}", json={"capacity": 2})

    kinds = await _kinds(client)
    assert "room.renamed" in kinds
    assert "case.updated" in kinds
