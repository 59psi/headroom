from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from headroom.models.app_setting import AppSetting
from headroom.models.case import Case
from headroom.models.hat import Hat
from headroom.schemas.case import (
    CaseCreate,
    CaseDetail,
    CaseRead,
    CaseType,
    CaseUpdate,
    HatSummary,
)
from headroom.services import activity_service, errors, retail_pricing, room_service
from headroom.services import capacity as capacity_rules


def _active_hats(case: Case) -> list[Hat]:
    """The hats a case actually holds, in shelf order.

    Disposed hats free their slot, so they must not count toward occupancy —
    `hat_service._capacity_refusal` filters them, and a read model that didn't
    would show a case as fuller than the validator considers it. `Case.hats`
    carries them anyway (`dispose_hat` keeps `case_id` for history), which is
    why this filter exists once rather than at each use.
    """
    return sorted(
        (h for h in (case.hats or []) if h.disposed_at is None),
        key=lambda h: (h.position_in_case is None, h.position_in_case or 0, h.id),
    )


def case_read(case: Case) -> CaseRead:
    """Case ORM object (hats and room loaded) → `CaseRead`.

    Lives with the service rather than in `routes/cases`, where `rooms` had
    to import it from another route module to render a room's cases.
    """
    hats = _active_hats(case)
    beanie_count = sum(1 for h in hats if h.is_beanie)
    room = capacity_rules.evaluate(
        capacity=case.capacity,
        beanie_count=beanie_count,
        regular_count=len(hats) - beanie_count,
    )
    return CaseRead(
        id=case.id,
        case_type=case.case_type,
        sequence_number=case.sequence_number,
        display_id=case.display_id,
        capacity=case.capacity,
        retail_price=retail_pricing.CASE_RETAIL,
        hat_count=len(hats),
        beanie_count=beanie_count,
        regular_count=len(hats) - beanie_count,
        room_id=case.room_id,
        room_name=case.room.name if case.room else None,
        # Up to four hat thumbnails, so the Cases grid can show what is
        # actually IN a case rather than a photo of the case's exterior —
        # every case looks the same from outside.
        hat_thumbs=[
            h.thumb_path or h.photo_path
            for h in hats
            if (h.thumb_path or h.photo_path)
        ][:4],
        accepts_regular=room.accepts_regular,
        accepts_beanie=room.accepts_beanie,
        free_regular=room.free_regular,
        free_beanie=room.free_beanie,
        # One flag rather than per-type: a case is type-exclusive, so at most
        # one of these can be true and two booleans would only invite a UI
        # that checks the wrong one.
        overfull=room.overfull_beanie if beanie_count else room.overfull_regular,
        nominal_capacity=room.max_beanie if beanie_count else room.max_regular,
        nominal_regular=room.max_regular,
        nominal_beanie=room.max_beanie,
        created_at=case.created_at,
        updated_at=case.updated_at,
    )


def case_detail(case: Case) -> CaseDetail:
    """`CaseRead` plus the hat list, from the same filtered, ordered hats.

    Derived from `case_read` rather than restating every field (they drifted
    apart too easily). The list is `_active_hats` for the reason the counts
    are: it used to list a sold hat as present under a header that counted
    it gone.
    """
    return CaseDetail(
        **case_read(case).model_dump(),
        hats=[HatSummary.model_validate(h) for h in _active_hats(case)],
    )


async def _reload_case(db: AsyncSession, case_id: int) -> Case:
    db.expire_all()
    result = await db.execute(
        select(Case)
        .options(selectinload(Case.hats), selectinload(Case.room))
        .where(Case.id == case_id)
    )
    return result.scalar_one()


def _make_display_id(case_type: CaseType, seq: int) -> str:
    prefix = "A" if case_type == CaseType.archive else "D"
    return f"{prefix}-{seq:03d}"


#: The highest sequence number each case type has ever RELEASED — given up by
#: a retype or a delete — kept in `app_settings`. A case's display id is what
#: its printed label and its NFC tag point at (`/t/c/D-002`), and neither can
#: be rewritten. Numbering by "highest number in use, plus one" handed a
#: retyped or deleted case's number to the next new case of that type, so the
#: old label went on scanning and opened a DIFFERENT case — the silent wrong
#: answer `tag_service` keys hat tags on an immutable id to avoid.
#:
#: Every number ever issued is either still in use or was released through
#: one of those two paths (they are the only writers that take a number away
#: from a case), so "above both the highest in use and the highest released"
#: is "never issued before", with no record needed at issue time — and it
#: covers cases that predate this record from their first retype or delete.
#: Only numbers released before the record existed are beyond recovering.
_RELEASED_KEYS: dict[CaseType, str] = {
    CaseType.archive: "case_seq_released_archive",
    CaseType.daily_wear: "case_seq_released_daily_wear",
}


def _as_seq(row: AppSetting | None) -> int:
    return int(row.value) if row is not None and row.value and row.value.isdigit() else 0


async def _release(db: AsyncSession, case_type: CaseType, seq: int) -> None:
    """Record that `seq` has been given up, so it is never issued again.

    In the caller's transaction — the number is retired in the same commit
    that takes it off its case, and a save that fails retires nothing.
    """
    key = _RELEASED_KEYS[case_type]
    row = await db.get(AppSetting, key)
    if row is None:
        db.add(AppSetting(key=key, value=str(seq)))
    elif _as_seq(row) < seq:
        row.value = str(seq)


async def get_next_sequence(db: AsyncSession, case_type: CaseType) -> int:
    """The next number for `case_type` — one that has never been issued.

    Above both the highest number in use and the highest ever released (see
    `_RELEASED_KEYS`). Read-then-write with the save that follows: callers
    hold `capacity.placement_lock()`.
    """
    in_use = (
        await db.execute(
            select(func.coalesce(func.max(Case.sequence_number), 0)).where(
                Case.case_type == case_type
            )
        )
    ).scalar_one()
    released = _as_seq(await db.get(AppSetting, _RELEASED_KEYS[case_type]))
    return max(in_use, released) + 1


async def create_case(db: AsyncSession, data: CaseCreate) -> Case:
    # `get_next_sequence` is read-then-write like every placement decision:
    # six concurrent creates used to be one case and five 500s on the unique
    # `display_id`. Serialized under the shelf-wide lock instead.
    async with capacity_rules.placement_lock():
        return await _create_case_locked(db, data)


async def _create_case_locked(db: AsyncSession, data: CaseCreate) -> Case:
    seq = await get_next_sequence(db, data.case_type)
    display_id = _make_display_id(data.case_type, seq)
    room_id = data.room_id
    if room_id is None:
        room_id = await room_service.get_default_room_id(db)
    elif not await room_service.room_exists(db, room_id):
        # Defense in depth behind the frontend fix. Nothing enforces this at the
        # DB level (no `PRAGMA foreign_keys`), so an id for a room that isn't
        # there used to be written straight through — and the symptoms never
        # named the cause: the case reported its room as "Unknown", and the room
        # it should have been in reported zero cases.
        raise errors.NotFound(f"Room {room_id} not found")
    case = Case(
        case_type=data.case_type,
        sequence_number=seq,
        display_id=display_id,
        room_id=room_id,
        capacity=data.capacity,
    )
    db.add(case)
    await db.commit()
    await activity_service.log_and_commit(
        db, kind="case.created", entity_type="case", entity_id=case.id,
        summary=f"Case {display_id} created in room {room_id}",
    )
    return await _reload_case(db, case.id)


async def list_cases(db: AsyncSession) -> list[Case]:
    result = await db.execute(
        select(Case)
        .options(selectinload(Case.hats), selectinload(Case.room))
        .order_by(Case.display_id)
    )
    return list(result.scalars().all())


async def get_case_by_display_id(db: AsyncSession, display_id: str) -> Case:
    result = await db.execute(
        select(Case)
        .options(selectinload(Case.hats), selectinload(Case.room))
        .where(Case.display_id == display_id.upper())
    )
    case = result.scalar_one_or_none()
    if not case:
        raise errors.NotFound("Case not found")
    return case


async def update_case(
    db: AsyncSession, display_id: str, data: CaseUpdate
) -> Case:
    # A retype allocates a sequence number — read-then-write, the same race
    # `create_case` serializes. Outside the lock, a retype racing a create of
    # the target type both took the same `D-00N` and one died on the unique
    # `display_id`. Held for the whole edit so the number and the save agree.
    async with capacity_rules.placement_lock():
        return await _update_case_locked(db, display_id, data)


async def _update_case_locked(
    db: AsyncSession, display_id: str, data: CaseUpdate
) -> Case:
    case = await get_case_by_display_id(db, display_id)
    before = {
        "display_id": case.display_id,
        "room_id": case.room_id,
        "capacity": case.capacity,
    }
    if data.case_type is not None and data.case_type != case.case_type:
        # The number this case gives up is retired, never handed to another
        # case — see `_RELEASED_KEYS`.
        await _release(db, case.case_type, case.sequence_number)
        seq = await get_next_sequence(db, data.case_type)
        case.case_type = data.case_type
        case.sequence_number = seq
        case.display_id = _make_display_id(data.case_type, seq)
    if data.room_id is not None:
        # Validated for the same reason as on create: nothing below this layer
        # enforces it, so an id for a missing room would orphan the case — and
        # this is the path used to *repair* an orphan, which makes silently
        # writing another bad id the worst possible failure here.
        if not await room_service.room_exists(db, data.room_id):
            raise errors.NotFound(f"Room {data.room_id} not found")
        case.room_id = data.room_id
    # Omitted vs explicit null. `if data.capacity is not None` treated both as
    # "leave it", so clearing the box in the Edit form — whose empty placeholder
    # promises the type default — changed nothing: a per-case override could be
    # set and never removed. A field the client SENT as null is a clear.
    if "capacity" in data.model_fields_set:
        case.capacity = data.capacity
    after = {
        "display_id": case.display_id,
        "room_id": case.room_id,
        "capacity": case.capacity,
    }
    await db.commit()
    changed = {k: v for k, v in before.items() if after[k] != v}
    if changed:
        # Audited like create and delete. A retype re-labels the case and a
        # move changes which room every hat in it is in — neither left a trace.
        await activity_service.log_and_commit(
            db, kind="case.updated", entity_type="case", entity_id=case.id,
            summary=f"Case {before['display_id']} updated · {', '.join(sorted(changed))}",
            details={"previous": changed},
        )
    return await _reload_case(db, case.id)


async def delete_case(db: AsyncSession, display_id: str) -> None:
    # Under the placement lock, like every other write that decides where
    # hats go or which numbers are taken: this files the case's hats into its
    # room and retires its number, and a create racing it must see both.
    async with capacity_rules.placement_lock():
        await _delete_case_locked(db, display_id)


async def _delete_case_locked(db: AsyncSession, display_id: str) -> None:
    case = await get_case_by_display_id(db, display_id)
    # Its number is retired with it, never re-issued — see `_RELEASED_KEYS`.
    await _release(db, case.case_type, case.sequence_number)
    # Detach every hat before deleting, keeping it IN THE ROOM the case was in.
    # Since 2.33 a hat can live in a room with no case, so "unassigned" and
    # "not in any room" stopped being the same state — clearing `case_id` alone
    # left these hats reachable from nowhere but the Hats list and search, which
    # reads as the shelf emptying itself. `room_service.delete_room` states the
    # same principle for the symmetric operation. The hats did not physically
    # move; only their container went.
    #
    # The room is VALIDATED first. This is the one place that wrote a room id
    # without checking, and `create_case` below documents why that matters:
    # nothing enforces it at the DB level, so a case orphaned by an older
    # version would hand every one of its hats a dangling `direct_room_id` —
    # `Hat.room` then resolves to None and the hat is in no room while the
    # column insists otherwise. Falling back to the default room keeps them
    # somewhere a person can actually find them.
    room_id = case.room_id
    if not await room_service.room_exists(db, room_id):
        room_id = await room_service.get_default_room_id(db)

    # `Case.hats` is unfiltered, so it includes DISPOSED hats. They keep their
    # disposition and must not be filed onto a shelf they are not on — and they
    # must not be counted in the audit line either, which is what made "N
    # hat(s) unassigned" wrong in both halves.
    active = [h for h in case.hats if h.disposed_at is None]
    for hat in active:
        hat.detach_from_case(room_id)
    for hat in case.hats:
        if hat.disposed_at is not None:
            # `None`, deliberately: a disposed hat is not filed onto a shelf it
            # is not on. Same writer as the active hats above — the model's.
            hat.detach_from_case(None)
    case_id = case.id
    await db.delete(case)
    await db.commit()
    await activity_service.log_and_commit(
        db, kind="case.deleted", entity_type="case", entity_id=case_id,
        # "moved to", not "unassigned" — the durable record has to name what
        # actually happened, and since 2.57.1 the hats keep their room.
        summary=f"Case {display_id} deleted · {len(active)} hat(s) moved to the room",
    )
