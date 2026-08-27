from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import ColumnElement

from headroom.models.case import Case
from headroom.models.hat import Hat
from headroom.models.room import Room
from headroom.schemas.hat import (
    KNOWN_CONSTRUCTIONS,
    HatCreate,
    HatDispose,
    HatUpdate,
    construction_from_flags,
    is_beanie_style,
)
from headroom.services import capacity as capacity_rules
from headroom.services import retail_pricing
from headroom.services import vocabulary
from headroom.services.activity_service import log_and_commit

# Re-exported for the tests and callers that referenced them here first; the
# rule itself lives in `capacity` so the picker and the validator agree.
MAX_REGULAR = capacity_rules.MAX_REGULAR
MAX_BEANIE = capacity_rules.MAX_BEANIE

# Disposition `via` values accepted by the API.
DISPOSITION_VIAS = {"sold", "gifted", "lost", "trashed", "trade"}


def _hat_loads():
    """The eager-load set every Hat query needs (CLAUDE.md: always selectinload).
    One definition — it was copy-pasted at three call sites, so adding a
    relationship meant remembering all three. `wear_logs` is deliberately absent:
    the model already declares it `lazy="selectin"`.
    """
    return (
        selectinload(Hat.case).selectinload(Case.room),
        selectinload(Hat.direct_room),
        selectinload(Hat.colors),
    )

async def _reload_hat(db: AsyncSession, hat_id: int) -> Hat:
    db.expire_all()
    result = await db.execute(
        select(Hat)
        .options(*_hat_loads())
        .where(Hat.id == hat_id)
    )
    return result.scalar_one()


async def _get_next_position(db: AsyncSession, case_id: int) -> int:
    result = await db.execute(
        select(func.coalesce(func.max(Hat.position_in_case), 0)).where(
            Hat.case_id == case_id, Hat.disposed_at.is_(None)
        )
    )
    return result.scalar_one() + 1


async def normalize_existing_colors(db: AsyncSession) -> int:
    """One-time data fix: snap general_color onto the curated palette.

    Claude-era rows stored its free-text name in both color_name and
    general_color, so filters depended on Claude's phrasing ("sky blue" vs
    "light blue"). Recomputes general_color from the stored hex; color_name
    keeps the original phrasing. Idempotent — safe to re-run.
    """
    from headroom.models.hat_color import HatColor
    from headroom.services.color_extraction import normalize_hex_name

    result = await db.execute(select(HatColor))
    changed = 0
    for row in result.scalars().all():
        if not row.hex_value:
            continue
        norm = normalize_hex_name(row.hex_value, row.general_color or row.color_name)
        if norm != row.general_color:
            row.general_color = norm
            changed += 1
    await db.commit()
    return changed


async def _validate_capacity(
    db: AsyncSession, case_id: int, is_beanie: bool, exclude_hat_id: int | None = None
) -> None:
    # Disposed hats no longer occupy a slot.
    query = select(Hat).where(Hat.case_id == case_id, Hat.disposed_at.is_(None))
    if exclude_hat_id:
        query = query.where(Hat.id != exclude_hat_id)
    result = await db.execute(query)
    hats = list(result.scalars().all())

    if hats:
        existing_has_beanies = any(h.is_beanie for h in hats)
        existing_has_regular = any(not h.is_beanie for h in hats)
        if is_beanie and existing_has_regular:
            raise HTTPException(
                status_code=409,
                detail="Case already contains regular hats — cannot mix types",
            )
        if not is_beanie and existing_has_beanies:
            raise HTTPException(
                status_code=409,
                detail="Case already contains beanies — cannot mix types",
            )

    beanie_count = sum(1 for h in hats if h.is_beanie)
    regular_count = len(hats) - beanie_count

    # Per-case capacity override wins over the type default. Same rule the
    # picker renders — see `services/capacity`.
    case = await db.get(Case, case_id)
    room = capacity_rules.evaluate(
        capacity=case.capacity if case else None,
        beanie_count=beanie_count,
        regular_count=regular_count,
    )
    # The refusal quotes the HARD limit, not the nominal one. A case at 3 of 3
    # still accepts a fourth — it just becomes overfull — so reporting "max 3"
    # while accepting the save would be the picker and the server disagreeing
    # again, in the message rather than the behavior.
    if is_beanie and not room.accepts_beanie:
        raise HTTPException(
            status_code=409,
            detail=f"Case has reached max beanie capacity ({room.limit_beanie})",
        )
    if not is_beanie and not room.accepts_regular:
        raise HTTPException(
            status_code=409,
            detail=f"Case has reached max regular hat capacity ({room.limit_regular})",
        )


async def create_hat(db: AsyncSession, data: HatCreate) -> Hat:
    is_beanie = is_beanie_style(data.style)
    position = None

    if data.case_id is not None:
        case = await db.get(Case, data.case_id)
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")
        await _validate_capacity(db, data.case_id, is_beanie)
        position = await _get_next_position(db, data.case_id)
    elif data.room_id is not None:
        # Checked for the same reason `assign_hat` checks it, and it was
        # missing here: the migration adds `direct_room_id` without a FK clause
        # (SQLite cannot add one to an existing table), so an unknown id is
        # accepted by the database and the hat ends up "in" a room that does
        # not exist — reporting no room at all, which looks like the placement
        # simply didn't take.
        if not await db.get(Room, data.room_id):
            raise HTTPException(status_code=404, detail="Room not found")

    hat = Hat(
        case_id=data.case_id,
        position_in_case=position,
        # Only meaningful with no case — a cased hat's room is its case's.
        direct_room_id=None if data.case_id is not None else data.room_id,
        limited_edition=data.limited_edition,
        condition=data.condition,
        size=data.size,
        style=data.style,
        date_last_worn=data.date_last_worn,
        is_beanie=is_beanie,
        # Empty string from an untouched form field means "not stated", same as
        # omitting it — storing "" would make the hat look annotated when the
        # owner never typed anything.
        # Canonicalized so "Neon"/"NEON"/"neon" converge on the spelling
        # already recorded — free text without this becomes five collections
        # that never find each other in search.
        artist_series=await vocabulary.canonicalize(db, Hat.artist_series, data.artist_series),
        model_name=data.model_name or None,
        purchase_price=data.purchase_price,
        purchased_at=data.purchased_at,
    )
    # After construction so the derived flags are set from the text, not left
    # at their column defaults.
    hat.set_construction(
        await vocabulary.canonicalize(
            db, Hat.construction, data.construction, known=KNOWN_CONSTRUCTIONS
        )
    )
    db.add(hat)
    await db.commit()
    await log_and_commit(
        db, kind="hat.created", entity_type="hat", entity_id=hat.id,
        summary=f"Hat #{hat.id} created · style={data.style} size={data.size}",
    )
    return await _reload_hat(db, hat.id)


async def list_hats(
    db: AsyncSession,
    case_id: int | None = None,
    style: str | None = None,
    condition: str | None = None,
    status: str = "active",
    offset: int = 0,
    limit: int = 50,
) -> list[Hat]:
    query = (
        select(Hat)
        .options(*_hat_loads())
    )
    if case_id is not None:
        query = query.where(Hat.case_id == case_id)
    if style:
        query = query.where(Hat.style == style)
    if condition:
        query = query.where(Hat.condition == condition)
    if status == "active":
        query = query.where(Hat.disposed_at.is_(None))
    elif status == "disposed":
        query = query.where(Hat.disposed_at.is_not(None))
    # status == "all" → no filter
    query = query.order_by(Hat.id).offset(offset).limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_hat(db: AsyncSession, hat_id: int) -> Hat:
    result = await db.execute(
        select(Hat)
        .options(*_hat_loads())
        .where(Hat.id == hat_id)
    )
    hat = result.scalar_one_or_none()
    if not hat:
        raise HTTPException(status_code=404, detail="Hat not found")
    return hat


async def update_hat(db: AsyncSession, hat_id: int, data: HatUpdate) -> Hat:
    hat = await get_hat(db, hat_id)
    update_data = data.model_dump(exclude_unset=True)
    changed_fields = list(update_data.keys())
    # Captured BEFORE the writes below. The audit row used to record only which
    # field names changed, which is enough to say something happened and
    # useless for undoing it — when analysis overwrote a construction the owner
    # had typed, nothing anywhere held the value it replaced. Previous values
    # make the log a record you can actually reverse.
    previous = {f: getattr(hat, f, None) for f in changed_fields}

    if "style" in update_data:
        new_is_beanie = is_beanie_style(update_data["style"])
        if new_is_beanie != hat.is_beanie and hat.case_id is not None:
            await _validate_capacity(db, hat.case_id, new_is_beanie, exclude_hat_id=hat.id)
        hat.is_beanie = new_is_beanie

    # `construction` owns `hydro`/`hydrolite`, so it goes through the model's
    # setter rather than the blind loop below.
    #
    # A pre-2.11 client sends the flags instead, and resolving those needs the
    # hat: `{"hydrolite": false}` means "clear HYDROLite", so it must leave a
    # hat whose construction is HYDRO alone. Each flag therefore falls back to
    # the hat's current value rather than to False. An explicit `construction`
    # always wins — a modern client sending both is stating the text.
    legacy_sent = {"hydrolite", "hydro"} & set(update_data)
    hydrolite = update_data.pop("hydrolite", None)
    hydro = update_data.pop("hydro", None)
    if "construction" in update_data:
        hat.set_construction(
            await vocabulary.canonicalize(
                db, Hat.construction, update_data.pop("construction"),
                known=KNOWN_CONSTRUCTIONS,
            )
        )
    elif legacy_sent:
        # `elif` on the CONSTRUCTION test, which is the thing it is an
        # alternative to: an explicit `construction` wins, and the flags are
        # the fallback for a client too old to send one.
        #
        # It used to hang off the `artist_series` branch below — so any legacy
        # client that sent a hydro flag *alongside* an artist series had the
        # flag silently dropped, and one that sent it alone happened to work.
        # Two unrelated fields, one `elif`, and a bug that only appears in
        # combination.
        wants_lite = hat.hydrolite if hydrolite is None else hydrolite
        wants_hydro = hat.hydro if hydro is None else hydro
        legacy_text = construction_from_flags(wants_lite, wants_hydro)
        # Only let the booleans clear a construction they can actually express.
        # A hat recorded as "Waxed Canvas" has both flags false already, so a
        # legacy client sending `hydro: false` is not talking about the canvas
        # — it is restating a default. Treating that as "clear the field" threw
        # away a fabric the client had no way of knowing existed, which is the
        # old two-value vocabulary silently overwriting the richer one that
        # replaced it.
        if legacy_text is not None or hat.hydro or hat.hydrolite:
            hat.set_construction(legacy_text)

    if update_data.get("artist_series"):
        update_data["artist_series"] = await vocabulary.canonicalize(
            db, Hat.artist_series, update_data["artist_series"]
        )

    # A resale price that arrived in a PUT came from a person, and that is the
    # one thing valuation must not discount or let a later analysis overwrite.
    # Recorded here rather than in the route because this is the only writer
    # every client path funnels through.
    # An entered retail price came from a tag or an order confirmation, so it
    # outranks both the table and Claude — and must survive the next analysis.
    # Same rule, same reason, as `resale_price` below.
    if "estimated_new_price" in update_data:
        hat.estimated_new_price_source = (
            retail_pricing.MANUAL_SOURCE
            if update_data["estimated_new_price"] is not None else None
        )

    if "resale_price" in update_data:
        hat.resale_price_scope = (
            "manual" if update_data["resale_price"] is not None else None
        )
        hat.resale_price_source = (
            "Entered manually" if update_data["resale_price"] is not None else None
        )

    for field, value in update_data.items():
        setattr(hat, field, value)

    await db.commit()
    if changed_fields:
        await log_and_commit(
            db, kind="hat.updated", entity_type="hat", entity_id=hat_id,
            summary=f"Hat #{hat_id} updated",
            details={
                "fields": changed_fields,
                # str() because these land in a JSON column and a date or
                # Decimal would otherwise fail to serialize and lose the whole
                # audit row — a partial record beats none.
                "previous": {k: (None if v is None else str(v)) for k, v in previous.items()},
            },
        )
    return await _reload_hat(db, hat_id)


async def delete_hat(db: AsyncSession, hat_id: int) -> None:
    hat = await get_hat(db, hat_id)
    await db.delete(hat)
    await db.commit()
    await log_and_commit(
        db, kind="hat.deleted", entity_type="hat", entity_id=hat_id,
        summary=f"Hat #{hat_id} permanently deleted",
    )


async def assign_hat(
    db: AsyncSession,
    hat_id: int,
    case_id: int | None,
    room_id: int | None = None,
) -> Hat:
    """Put a hat in a case, in a room with no case, or nowhere.

    A case and a direct room are mutually exclusive, and this is the one place
    that holds that: a cased hat's room IS its case's room, so keeping a second
    answer alongside it is keeping something that can disagree. Setting either
    clears the other.

    `case_id` wins if both arrive — it is the more specific placement, and a
    caller sending both has not said which they meant.
    """
    hat = await get_hat(db, hat_id)

    if case_id is not None:
        case = await db.get(Case, case_id)
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")
        await _validate_capacity(db, case_id, hat.is_beanie)
        position = await _get_next_position(db, case_id)
        hat.case_id = case_id
        hat.position_in_case = position
        hat.direct_room_id = None
        where = f"assigned to case {case_id}"
    elif room_id is not None:
        room = await db.get(Room, room_id)
        if not room:
            raise HTTPException(status_code=404, detail="Room not found")
        hat.case_id = None
        hat.position_in_case = None
        hat.direct_room_id = room_id
        where = f"placed in room {room_id} with no case"
    else:
        hat.case_id = None
        hat.position_in_case = None
        hat.direct_room_id = None
        where = "unassigned"

    await db.commit()
    await log_and_commit(
        db, kind="hat.assigned", entity_type="hat", entity_id=hat_id,
        summary=f"Hat #{hat_id} {where}",
    )
    return await _reload_hat(db, hat_id)


async def dispose_hat(db: AsyncSession, hat_id: int, data: HatDispose) -> Hat:
    """Soft-delete a hat. Takes the whole `HatDispose` — the five fields always
    travel together, so unpacking them into kwargs only created a clump to
    re-assemble at the call site."""
    via = data.via
    if via not in DISPOSITION_VIAS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid disposal kind. Must be one of: {', '.join(sorted(DISPOSITION_VIAS))}",
        )
    hat = await get_hat(db, hat_id)
    hat.disposed_at = data.disposed_at or datetime.now(timezone.utc)
    hat.disposed_via = via
    hat.disposed_price = data.price
    hat.disposed_to = data.to
    hat.disposed_notes = data.notes
    # Free the case slot — disposed hats stay tied to their last case for
    # history but no longer count against capacity (see _validate_capacity).
    # We deliberately don't unassign so the case detail page can show
    # "previously held" hats if we want that later. Capacity check ignores
    # disposed hats already.
    await db.commit()
    await log_and_commit(
        db, kind="hat.disposed", entity_type="hat", entity_id=hat_id,
        summary=f"Hat #{hat_id} disposed via {via}"
                + (f" for ${data.price:.2f}" if data.price else ""),
        details={"via": via, "price": data.price, "to": data.to},
    )
    return await _reload_hat(db, hat_id)


async def undispose_hat(db: AsyncSession, hat_id: int) -> Hat:
    hat = await get_hat(db, hat_id)
    if hat.disposed_at is None:
        return hat
    # If the original case is still around AND has space, the hat returns
    # there. Otherwise it becomes unassigned.
    target_case_id = hat.case_id
    hat.disposed_at = None
    hat.disposed_via = None
    hat.disposed_price = None
    hat.disposed_to = None
    hat.disposed_notes = None
    if target_case_id is not None:
        try:
            # The case may have been deleted while this hat was disposed —
            # `_validate_capacity` counts hats, and a case with no hats looks
            # exactly like an empty one whether or not the row still exists, so
            # it cannot catch this on its own. Without the check the hat comes
            # back pointing at a case id that resolves to nothing, and every
            # read that walks `hat.case.room` gets None where it expects a room.
            if await db.get(Case, target_case_id) is None:
                raise HTTPException(status_code=404, detail="Case no longer exists")
            await _validate_capacity(db, target_case_id, hat.is_beanie, exclude_hat_id=hat.id)
            # Reassign to a fresh slot: the hat's old position may have been
            # taken by another hat added while it was disposed. Keeping the
            # stale position_in_case would duplicate display IDs / QR labels.
            hat.position_in_case = await _get_next_position(db, target_case_id)
        except HTTPException:
            # Doesn't fit any more (the case filled up while this hat was
            # disposed, or its capacity was lowered). Come back loose in the
            # case's room rather than nowhere: `detach_from_case` is the one
            # definition of that, and skipping it here is what made a restore
            # into a full case silently un-room the hat. The 8 -> 6 beanie
            # change in 2.57.0 widened this from rare to routine.
            room_id = None
            if target_case_id is not None:
                target_case = await db.get(Case, target_case_id)
                room_id = target_case.room_id if target_case else None
            hat.detach_from_case(room_id)
    await db.commit()
    await log_and_commit(
        db, kind="hat.undisposed", entity_type="hat", entity_id=hat_id,
        summary=f"Hat #{hat_id} restored from disposed state",
    )
    return await _reload_hat(db, hat_id)


async def backfill_thumbnails(db: AsyncSession, limit: int = 5000) -> int:
    """Generate the gallery thumbnail for hats that predate them.

    Runs off the boot path as a background task: it is pure image work over
    every existing photo, which on a Pi is slow enough that doing it inline
    would delay the app becoming reachable.

    Idempotent — only touches hats with a photo and no usable thumbnail, so a
    restart mid-run picks up where it left off rather than redoing everything.
    """
    from headroom.config import settings as cfg  # noqa: PLC0415
    from headroom.utils.photo import THUMBS_DIR, make_thumbnail_async  # noqa: PLC0415

    hats = (
        (
            await db.execute(
                select(Hat)
                .where(Hat.photo_path.is_not(None), Hat.thumb_path.is_(None))
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )

    made = 0
    for hat in hats:
        source = cfg.upload_dir / hat.photo_path
        if not source.exists():
            continue
        thumb = await make_thumbnail_async(
            source, cfg.upload_dir / "hats" / THUMBS_DIR / source.stem
        )
        if thumb is not None:
            hat.thumb_path = f"hats/{THUMBS_DIR}/{thumb.name}"
            made += 1
    if made:
        await db.commit()
    return made


async def backfill_export_images(db: AsyncSession, limit: int = 5000) -> int:
    """Generate the 800px export derivative for hats that predate it.

    The companion to generating it at upload time. Without this, the first
    export after upgrading still pays for every hat already in the collection
    — which on a few hundred hats is the several-minute stall the change was
    meant to remove, just moved to a slightly later date.

    Writes no database column: the file's existence IS the record, and
    `export_derivative_path` derives its name from the photo's. That makes the
    sweep naturally idempotent and resumable, so a restart mid-run costs
    nothing, and it means a re-cut photo regenerates on its own (the export's
    mtime check sees a newer source).

    Deliberately does NOT hold a write transaction: it only reads hat rows and
    writes files, so nothing here can block another writer on SQLite's single
    write lock while it grinds through hundreds of images.
    """
    from headroom.config import settings as cfg  # noqa: PLC0415
    from headroom.utils.photo import (  # noqa: PLC0415
        export_derivative_path,
        make_export_image_async,
    )

    rows = (
        (
            await db.execute(
                select(Hat).where(Hat.photo_path.is_not(None)).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    # Snapshot the paths and let go of the ORM objects. The loop below is
    # minutes of image work; holding a session open across it for no reason is
    # how an incidental lazy load turns into a lock nobody expected.
    photos = [h.photo_path for h in rows if h.photo_path]

    made = 0
    for photo_rel in photos:
        source = cfg.upload_dir / photo_rel
        if not source.exists():
            continue
        cache = export_derivative_path(cfg.upload_dir, photo_rel)
        try:
            if cache.exists() and cache.stat().st_mtime >= source.stat().st_mtime:
                continue
        except OSError:
            pass
        if await make_export_image_async(source, cache) is not None:
            made += 1
    return made


async def list_by_analysis_status(
    db: AsyncSession, status: str, limit: int = 50, newest_first: bool = False
) -> list[Hat]:
    """Hats in a given `analysis_status`, for the admin queue and error views.

    Lives here rather than in the admin routes so the one place that knows how
    to load a Hat (`_hat_loads`) stays the one place that does. Entities, not
    columns: `display_id` is a derived property that walks `hat.case`, so it
    cannot be selected — and it is the label a person actually recognizes.
    """
    query = select(Hat).options(*_hat_loads()).where(Hat.analysis_status == status)
    if newest_first:
        query = query.order_by(Hat.analyzed_at.desc().nulls_last(), Hat.id.desc())
    else:
        query = query.order_by(Hat.id)
    result = await db.execute(query.limit(max(1, min(limit, 100))))
    return list(result.scalars().all())


def reanalyzable_filters() -> tuple[ColumnElement[bool], ...]:
    """Which rows a re-analysis run may touch at all, as SQL clauses.

    One definition, three callers: the whole-collection run, the retry-failed
    run, and `analysis_job_service.ids_for_failure_reason`, which maps a
    failure group back to its hats. A second copy would drift, and the copy
    that fell behind would queue hats the pipeline then refuses — a run
    reporting work it cannot do.
    """
    return (Hat.photo_path.is_not(None), Hat.disposed_at.is_(None))


def failed_analysis_filters() -> tuple[ColumnElement[bool], ...]:
    """Which rows count as having FAILED analysis.

    Carrying a failure string is the whole test, and it is deliberately the
    same one `analysis_job_service.recent_failures` groups by — so "retry these
    21" covers exactly the 21 the failures card is complaining about. A button
    whose count disagrees with the list above it is worse than no button.

    Keying on `analysis_status` instead would not work. `skipped` (no API key)
    and `fallback` (Claude failed, colors came from the cutout) both carry a
    reason and both want retrying, so the set is not one status; and the text
    is what gets cleared on success, which makes it the field that actually
    tracks whether the failure is still outstanding.
    """
    return (Hat.analysis_error.is_not(None), Hat.analysis_error != "")


async def ids_for_reanalysis(db: AsyncSession, *, failed_only: bool = False) -> list[int]:
    """Ids of EVERY hat a bulk re-analysis covers: any hat with a photo.

    Ids rather than entities: the caller hands these to a queue, and the
    routes↔worker boundary passes identifiers so a worker never holds an ORM
    object from someone else's session.

    `failed_only` narrows the run to hats that failed last time — the retry
    path. It is a narrowing of THIS query rather than a query of its own so
    that the exclusions below keep applying to it: a disposed hat that failed
    analysis a year ago is still disposed, and retrying it still spends a
    Claude call on inventory that is gone.

    Disposed hats are excluded — they are gone, and re-pricing them spends
    Claude calls on inventory that is no longer owned. That is the only
    exclusion.

    There used to be an `only_priced_by_claude` filter, exposed as a checkbox
    reading "Leave hand-entered prices alone" and defaulting to ON. It was
    already redundant — a Manual price is protected unconditionally, by
    `retail_pricing.resolve_retail` and by the two `resale_price_scope ==
    "manual"` guards in the pipeline — so it never spared anything that was not
    already safe.

    What it did do was silently shrink the run. Before 2.27 nearly every hat
    was priced by Claude, so "only the Claude-priced ones" was very nearly all
    of them and the option looked harmless. 2.27 moved the majority to the
    retail table (`source = "melin retail"`), and the same filter then matched
    only the remainder Claude still prices — 45 hats out of 234 in a real
    collection — under a button that says "Re-analyze every hat".
    """
    stmt = select(Hat.id).where(*reanalyzable_filters())
    if failed_only:
        stmt = stmt.where(*failed_analysis_filters())
    return list((await db.execute(stmt.order_by(Hat.id))).scalars().all())


async def count_by_analysis_status(db: AsyncSession, status: str) -> int:
    """How many hats sit in one analysis status. Backs the nav error badge."""
    result = await db.execute(
        select(func.count(Hat.id)).where(Hat.analysis_status == status)
    )
    return int(result.scalar() or 0)
