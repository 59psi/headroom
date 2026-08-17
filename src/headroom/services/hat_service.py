from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from headroom.models.case import Case
from headroom.models.hat import Hat
from headroom.schemas.hat import (
    HatCreate,
    HatDispose,
    HatStyle,
    HatUpdate,
    construction_from_flags,
)
from headroom.services.activity_service import log_and_commit

MAX_REGULAR = 4
MAX_BEANIE = 6

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

    # Per-case capacity override wins over the type default.
    case = await db.get(Case, case_id)
    # `is not None`, not truthiness: a per-case capacity of exactly 0 means
    # "this case holds nothing" and must be honoured, where `if case.capacity`
    # silently fell through to the type default and let 4 hats into a case
    # deliberately set to hold none.
    case_capacity = case.capacity if case and case.capacity is not None else None

    # Same reason as above — `or` would treat a capacity of 0 as unset.
    max_beanie = MAX_BEANIE if case_capacity is None else case_capacity
    max_regular = MAX_REGULAR if case_capacity is None else case_capacity
    if is_beanie and beanie_count >= max_beanie:
        raise HTTPException(
            status_code=409,
            detail=f"Case has reached max beanie capacity ({max_beanie})",
        )
    if not is_beanie and regular_count >= max_regular:
        raise HTTPException(
            status_code=409,
            detail=f"Case has reached max regular hat capacity ({max_regular})",
        )


async def create_hat(db: AsyncSession, data: HatCreate) -> Hat:
    is_beanie = data.style == HatStyle.beanie
    position = None

    if data.case_id is not None:
        case = await db.get(Case, data.case_id)
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")
        await _validate_capacity(db, data.case_id, is_beanie)
        position = await _get_next_position(db, data.case_id)

    hat = Hat(
        case_id=data.case_id,
        position_in_case=position,
        condition=data.condition,
        size=data.size,
        style=data.style,
        date_last_worn=data.date_last_worn,
        is_beanie=is_beanie,
        # Empty string from an untouched form field means "not stated", same as
        # omitting it — storing "" would make the hat look annotated when the
        # owner never typed anything.
        artist_series=data.artist_series or None,
        model_name=data.model_name or None,
    )
    # After construction so the derived flags are set from the text, not left
    # at their column defaults.
    hat.set_construction(data.construction)
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
        new_is_beanie = update_data["style"] == HatStyle.beanie
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
        hat.set_construction(update_data.pop("construction"))
    elif legacy_sent:
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
                # Decimal would otherwise fail to serialise and lose the whole
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


async def assign_hat(db: AsyncSession, hat_id: int, case_id: int | None) -> Hat:
    hat = await get_hat(db, hat_id)

    if case_id is not None:
        case = await db.get(Case, case_id)
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")
        await _validate_capacity(db, case_id, hat.is_beanie)
        position = await _get_next_position(db, case_id)
        hat.case_id = case_id
        hat.position_in_case = position
    else:
        hat.case_id = None
        hat.position_in_case = None

    await db.commit()
    await log_and_commit(
        db, kind="hat.assigned", entity_type="hat", entity_id=hat_id,
        summary=f"Hat #{hat_id} {'assigned to case ' + str(case_id) if case_id else 'unassigned'}",
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
            hat.case_id = None
            hat.position_in_case = None
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
