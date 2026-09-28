import logging
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta, timezone

from pydantic import ValidationError
from sqlalchemy import case, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import ColumnElement

from headroom.config import settings as cfg
from headroom.models.case import Case
from headroom.models.catalog import Purchase
from headroom.models.hat import Hat, ResaleScope
from headroom.models.hat_color import HatColor
from headroom.models.room import Room
from headroom.models.wear_log import WearLog
from headroom.schemas.hat import (
    KNOWN_CONSTRUCTIONS,
    AnalysisStatus,
    ColorTagWrite,
    HatCreate,
    HatDispose,
    HatUpdate,
    construction_from_flags,
    is_beanie_style,
)
from headroom.services import (
    activity_service,
    construction_audit,
    ebay_service,
    errors,
    retail_pricing,
    vocabulary,
)
from headroom.services import capacity as capacity_rules
from headroom.services.color_extraction import normalize_color_name, normalize_hex_name
from headroom.utils.photo import (
    THUMBS_DIR,
    export_derivative_path,
    make_export_image_async,
    make_thumbnail_async,
)

logger = logging.getLogger(__name__)


def hat_loads():
    """The eager-load set every Hat query needs — relationships are loaded with
    `selectinload`, never lazily, on an async session.

    One definition, PUBLIC. It was copy-pasted at three call sites inside this
    module, then restated by hand in six other services — three of which had
    dropped `direct_room` and were saved only by the mapper's `lazy="selectin"`.
    Any query that returns hats splats this. `wear_logs` is deliberately
    absent: what a hat read shows is the count, and the wear functions below
    query `WearLog` themselves rather than depending on how the relationship
    happens to be loaded.
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
        .options(*hat_loads())
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
    """Refuse (`errors.Conflict`) a hat the case cannot take."""
    refusal = await _capacity_refusal(db, case_id, is_beanie, exclude_hat_id)
    if refusal is not None:
        raise errors.Conflict(refusal)


async def _capacity_refusal(
    db: AsyncSession, case_id: int, is_beanie: bool, exclude_hat_id: int | None = None
) -> str | None:
    """Why the case cannot take this hat, or None when it can.

    A question with an answer rather than a check that raises, because one
    caller — restoring a disposed hat — has a perfectly good plan B when the
    answer is no, and used to get there by catching its own HTTP 409.
    """
    # Disposed hats no longer occupy a slot.
    query = select(Hat).where(Hat.case_id == case_id, Hat.disposed_at.is_(None))
    if exclude_hat_id:
        query = query.where(Hat.id != exclude_hat_id)
    result = await db.execute(query)
    hats = list(result.scalars().all())

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
    # Type exclusivity is decided by `evaluate` — the ONE rule the picker
    # also renders — not re-derived here. This function used to carry its own
    # copy of "a case holds beanies OR regular hats", ahead of the call, so
    # the read model and the write path could have disagreed about the one
    # thing a 409 on save exists to prevent. Only the WORDING is decided here.
    if is_beanie and not room.accepts_beanie:
        return (
            "Case already contains regular hats — cannot mix types"
            if regular_count
            else f"Case has reached max beanie capacity ({room.limit_beanie})"
        )
    if not is_beanie and not room.accepts_regular:
        return (
            "Case already contains beanies — cannot mix types"
            if beanie_count
            else f"Case has reached max regular hat capacity ({room.limit_regular})"
        )
    return None


async def create_hat(db: AsyncSession, data: HatCreate) -> Hat:
    # Under the placement lock even when no case is named: which branch runs
    # is decided inside, and a hat created straight into a case is the
    # concurrent-creates race (six accepted into a 3-hat case, five at one
    # position) — see `capacity.placement_lock`.
    async with capacity_rules.placement_lock():
        return await _create_hat_locked(db, data)


async def _create_hat_locked(db: AsyncSession, data: HatCreate) -> Hat:
    is_beanie = is_beanie_style(data.style)
    position = None

    if data.case_id is not None:
        case = await db.get(Case, data.case_id)
        if not case:
            raise errors.NotFound("Case not found")
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
            raise errors.NotFound("Room not found")

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
        ),
        source=construction_audit.OWNER_SOURCE,
    )
    db.add(hat)
    await db.commit()
    await activity_service.log_and_commit(
        db, kind="hat.created", entity_type="hat", entity_id=hat.id,
        summary=f"Hat #{hat.id} created · style={data.style} size={data.size}",
    )
    return await _reload_hat(db, hat.id)


def _hat_list_filters(
    case_id: int | None, style: str | None, condition: str | None, status: str
) -> tuple:
    """The WHERE clauses `list_hats` and `count_hats` must share.

    Two copies would let `X-Total-Count` describe a different set from the page
    it is counting — which is worse than no count, because the disagreement is
    invisible until someone adds a filter to one and not the other.
    `status == "all"` deliberately adds nothing.
    """
    clauses = []
    if case_id is not None:
        clauses.append(Hat.case_id == case_id)
    if style:
        clauses.append(Hat.style == style)
    if condition:
        clauses.append(Hat.condition == condition)
    if status == "active":
        clauses.append(Hat.disposed_at.is_(None))
    elif status == "disposed":
        clauses.append(Hat.disposed_at.is_not(None))
    return tuple(clauses)


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
        .options(*hat_loads())
        .where(*_hat_list_filters(case_id, style, condition, status))
    )
    query = query.order_by(Hat.id).offset(offset).limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_hat_or_none(db: AsyncSession, hat_id: int) -> Hat | None:
    """The hat with its relationships loaded, or None — for callers holding
    an id that may no longer resolve (the import worker adopting a hat a
    previous attempt created), where a 404 is the wrong shape of answer."""
    result = await db.execute(
        select(Hat)
        .options(*hat_loads())
        .where(Hat.id == hat_id)
    )
    return result.scalar_one_or_none()


async def get_hat(db: AsyncSession, hat_id: int) -> Hat:
    hat = await get_hat_or_none(db, hat_id)
    if not hat:
        raise errors.NotFound("Hat not found")
    return hat


async def ensure_case_accepts(db: AsyncSession, case_id: int, style: str) -> None:
    """Refuse up front a case a hat of `style` could not be created into.

    For callers that commit to work BEFORE the hat exists — the bulk import
    spools every photo to disk and queues them, and only the worker, minutes
    later, called `create_hat`. A case id that did not exist, or one already
    full, therefore surfaced as N failed items after a 750 MB upload had been
    accepted with a 202. `create_hat` still checks under the placement lock;
    this is the early answer, not the authoritative one.
    """
    if await db.get(Case, case_id) is None:
        raise errors.NotFound("Case not found")
    await _validate_capacity(db, case_id, is_beanie_style(style))


#: How long one notes-editing session runs, as the audit log counts it.
NOTES_SESSION = timedelta(minutes=10)


async def _continues_notes_session(db: AsyncSession, hat_id: int, changed_fields: list[str]) -> bool:
    """Whether this save is more of a notes edit the log already records.

    The notes box autosaves on every pause in typing (~900 ms), and each save
    is a PUT that changed `owner_notes` — so a paragraph typed in bursts wrote
    a "Hat #N updated" row per pause, each carrying the whole previous text,
    crowding the Recent activity card and the retention table with one edit.

    A notes-only save within `NOTES_SESSION` of a notes-only row that is this
    hat's newest is the same session, and is not logged again. The row that
    stands is the session's FIRST, whose `previous` is the text from before
    the session began — the one worth being able to go back to. Nothing is
    rewritten: the log stays append-only. Any other field, any other row in
    between, or a longer pause starts a new record.
    """
    if changed_fields != ["owner_notes"]:
        return False
    last = await activity_service.latest_for(db, "hat", hat_id)
    if last is None or last.kind != "hat.updated":
        return False
    if activity_service.details_of(last).get("fields") != ["owner_notes"]:
        return False
    return last.occurred_at >= datetime.now(timezone.utc) - NOTES_SESSION


def _price_changed(stored: float | None, sent: float | None) -> bool:
    """Is `sent` a different number from `stored`? Same value → not a change."""
    if stored is None or sent is None:
        return stored is not sent
    return abs(stored - sent) > 0.005


async def update_hat(db: AsyncSession, hat_id: int, data: HatUpdate) -> Hat:
    hat = await get_hat(db, hat_id)
    update_data = data.model_dump(exclude_unset=True)
    # Every field SENT; narrowed to the ones that actually changed once the
    # writes below have run.
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
            # A type flip changes what the case holds; it competes with every
            # other placement writer for the same occupancy count.
            async with capacity_rules.placement_lock():
                await _validate_capacity(db, hat.case_id, new_is_beanie, exclude_hat_id=hat.id)
                hat.is_beanie = new_is_beanie
                await db.commit()
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
            ),
            source=construction_audit.OWNER_SOURCE,
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
            hat.set_construction(legacy_text, source=construction_audit.OWNER_SOURCE)

    if update_data.get("artist_series"):
        update_data["artist_series"] = await vocabulary.canonicalize(
            db, Hat.artist_series, update_data["artist_series"]
        )
    # Colorway is free text with the same failure mode — "heather grey" typed
    # beside a stored "Heather Grey" splits the picker feed and, worse, the
    # token-set EQUALITY `is_real_product` and `_product_comp` apply to it is
    # case-folded only by luck of casing. The analysis path canonicalized it;
    # this path and the purchase matcher wrote straight through.
    if update_data.get("colorway"):
        update_data["colorway"] = await vocabulary.canonicalize(
            db, Hat.colorway, update_data["colorway"]
        )

    # A resale price that arrived in a PUT came from a person, and that is the
    # one thing valuation must not discount or let a later analysis overwrite.
    # Recorded here rather than in the route because this is the only writer
    # every client path funnels through.
    #
    # A price EQUAL to the one already stored is not a new fact. The SPA's
    # form used to send every price back on every save, which stamped a
    # scraped median `manual` when a note was edited (the 2.57 bug); the SPA
    # was fixed to send only what changed, and this is the server's half of
    # the same rule, for every other client: restating the value the hat
    # already holds leaves its provenance alone. A DIFFERENT value, or a
    # value where there was none, is the person speaking.
    #
    # An entered retail price came from a tag or an order confirmation, so it
    # outranks both the table and Claude — and must survive the next analysis.
    # Same rule, same reason, as `resale_price` below.
    if "estimated_new_price" in update_data and _price_changed(
        hat.estimated_new_price, update_data["estimated_new_price"]
    ):
        hat.estimated_new_price_source = (
            retail_pricing.MANUAL_SOURCE
            if update_data["estimated_new_price"] is not None else None
        )

    if "resale_price" in update_data and _price_changed(
        hat.resale_price, update_data["resale_price"]
    ):
        hat.resale_price_scope = (
            ResaleScope.MANUAL if update_data["resale_price"] is not None else None
        )
        hat.resale_price_source = (
            "Entered manually" if update_data["resale_price"] is not None else None
        )

    for field, value in update_data.items():
        setattr(hat, field, value)

    # Log what CHANGED, not what was sent. The Edit form PUTs every field, so
    # "the keys in the body" named `construction` on a save that only touched
    # the notes — and `construction_audit.owner_set_hat_ids` reads a
    # `hat.updated` row naming `construction` as proof the owner typed it. An
    # untouched analyzer guess re-sent by the form was thereby promoted to the
    # owner's answer and shielded from the audit's Clear, exactly the
    # promotion `Hat.set_construction` refuses for the same re-send. Compared
    # after the writes, so a value the vocabulary snapped back onto the stored
    # spelling reads as unchanged too.
    changed_fields = [f for f in changed_fields if getattr(hat, f, None) != previous[f]]
    previous = {f: previous[f] for f in changed_fields}

    await db.commit()
    if changed_fields and not await _continues_notes_session(db, hat_id, changed_fields):
        await activity_service.log_and_commit(
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
    # Give the receipt back. `purchases.hat_id` has no database-enforced
    # foreign key (no `PRAGMA foreign_keys`), so deleting a hat left its
    # purchase pointing at a row that no longer existed: the purchases list
    # still showed the link, `match?dry_run` found nothing to do and
    # `unclaimed` reported nothing to fill — a real price, orphaned forever.
    # Unlinked, the next matching run can hand it to the hat that replaces
    # this one (a re-shot duplicate is the common reason for a delete).
    await db.execute(
        update(Purchase).where(Purchase.hat_id == hat_id).values(hat_id=None)
    )
    await db.delete(hat)
    await db.commit()
    await activity_service.log_and_commit(
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
    async with capacity_rules.placement_lock():
        return await _assign_hat_locked(db, hat_id, case_id, room_id)


async def _assign_hat_locked(
    db: AsyncSession,
    hat_id: int,
    case_id: int | None,
    room_id: int | None,
) -> Hat:
    hat = await get_hat(db, hat_id)

    if case_id is not None:
        case = await db.get(Case, case_id)
        if not case:
            raise errors.NotFound("Case not found")
        await _validate_capacity(db, case_id, hat.is_beanie)
        position = await _get_next_position(db, case_id)
        hat.case_id = case_id
        hat.position_in_case = position
        hat.direct_room_id = None
        where = f"assigned to case {case_id}"
    elif room_id is not None:
        room = await db.get(Room, room_id)
        if not room:
            raise errors.NotFound("Room not found")
        # Through the model's one writer of "no longer in a case", not by
        # hand — this function carried two more copies of the three-column
        # write `Hat.detach_from_case` was created to be the only home of.
        hat.detach_from_case(room_id)
        where = f"placed in room {room_id} with no case"
    else:
        hat.detach_from_case(None)
        where = "unassigned"

    await db.commit()
    await activity_service.log_and_commit(
        db, kind="hat.assigned", entity_type="hat", entity_id=hat_id,
        summary=f"Hat #{hat_id} {where}",
    )
    return await _reload_hat(db, hat_id)


async def dispose_hat(db: AsyncSession, hat_id: int, data: HatDispose) -> Hat:
    """Soft-delete a hat. Takes the whole `HatDispose` — the five fields always
    travel together, so unpacking them into kwargs only created a clump to
    re-assemble at the call site."""
    # `via` is a `DisposedVia`; an unknown value never reaches here — the schema
    # rejects it with a 422 like every other enum field.
    via = str(data.via)
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
    await activity_service.log_and_commit(
        db, kind="hat.disposed", entity_type="hat", entity_id=hat_id,
        summary=f"Hat #{hat_id} disposed via {via}"
                + (f" for ${data.price:.2f}" if data.price else ""),
        details={"via": via, "price": data.price, "to": data.to},
    )
    return await _reload_hat(db, hat_id)


async def undispose_hat(db: AsyncSession, hat_id: int) -> Hat:
    # Restoring into a case takes a slot; same lock as every other placement.
    async with capacity_rules.placement_lock():
        return await _undispose_hat_locked(db, hat_id)


async def _undispose_hat_locked(db: AsyncSession, hat_id: int) -> Hat:
    hat = await get_hat(db, hat_id)
    if hat.disposed_at is None:
        return hat
    # If the original case is still around AND has space, the hat returns
    # there. Otherwise it comes back loose in the case's room.
    #
    # The placement is decided BEFORE the disposal is cleared. Clearing first
    # made the hat active at its OLD position for the duration of the next
    # query — an autoflush emitted `UPDATE hats SET disposed_at = NULL` while
    # another hat sat at that slot, which the unique index on active
    # positions refuses. While still disposed the hat is invisible to
    # `_validate_capacity` and `_get_next_position` (both filter on
    # `disposed_at IS NULL`), so the decision below sees exactly the
    # occupancy it should.
    target_case_id = hat.case_id
    if target_case_id is not None:
        # The case may have been deleted while this hat was disposed —
        # `_capacity_refusal` counts hats, and a case with no hats looks
        # exactly like an empty one whether or not the row still exists, so
        # it cannot catch this on its own. Without the check the hat comes
        # back pointing at a case id that resolves to nothing, and every
        # read that walks `hat.case.room` gets None where it expects a room.
        target_case = await db.get(Case, target_case_id)
        fits = target_case is not None and await _capacity_refusal(
            db, target_case_id, hat.is_beanie, exclude_hat_id=hat.id
        ) is None
        if fits:
            # Reassign to a fresh slot: the hat's old position may have been
            # taken by another hat added while it was disposed. Keeping the
            # stale position_in_case would duplicate display IDs / QR labels.
            hat.position_in_case = await _get_next_position(db, target_case_id)
        else:
            # Gone, or doesn't fit any more (the case filled up while this hat
            # was disposed, or its capacity was lowered). Come back loose in
            # the case's room rather than nowhere: `detach_from_case` is the
            # one definition of that, and skipping it here is what made a
            # restore into a full case silently un-room the hat. The 8 -> 6
            # beanie change in 2.57.0 widened this from rare to routine.
            #
            # A plain branch, not an exception handler: this used to raise its
            # own HTTP 404 and catch it alongside `_validate_capacity`'s 409,
            # so an HTTP status stood in for a placement decision.
            hat.detach_from_case(target_case.room_id if target_case else None)
    hat.disposed_at = None
    hat.disposed_via = None
    hat.disposed_price = None
    hat.disposed_to = None
    hat.disposed_notes = None
    await db.commit()
    await activity_service.log_and_commit(
        db, kind="hat.undisposed", entity_type="hat", entity_id=hat_id,
        summary=f"Hat #{hat_id} restored from disposed state",
    )
    return await _reload_hat(db, hat_id)


#: Audit kinds for the writes below, named once so a test or a filter that
#: looks one up cannot drift from the spelling that writes it.
KIND_COLORS = "hat.colors_updated"
KIND_PHOTO = "hat.photo_replaced"
KIND_WORN = "hat.worn"
KIND_WEAR_UNDONE = "hat.wear_undone"

#: `Hat.colors_source` for a palette a PERSON set (`set_colors`, i.e.
#: `PUT /api/hats/{id}/colors`); NULL means analysis wrote the colors. Owned
#: here beside its one reader, `replace_analysis_colors` — the gate every
#: analysis path writes colors through — the way `construction_audit.
#: OWNER_SOURCE` sits beside the audit that skips on it. Not in the pipeline:
#: the pipeline imports this module for the color rules, so a constant there
#: would make the writer (`set_colors`) import its own importer.
COLORS_OWNER_SOURCE = "owner"

#: `hat_colors.color_name` is String(50), and `ColorTagWrite` refuses more.
_COLOR_NAME_MAX = 50


def _color_rows(colors: Sequence[ColorTagWrite]) -> list[HatColor]:
    """The stored rows for a palette, ranked by position — for every writer.

    The owner's edit and both analysis paths used to build rows three ways,
    and only the edit applied the rules below; analysis wrote whatever came
    back, so a stored row could hold what the edit form would refuse.
    """
    rows = []
    for rank, c in enumerate(colors, start=1):
        # An explicitly-typed general_color is a CORRECTION and must win. This
        # used to derive the name from the hex whenever a hex was present, so
        # editing a mis-detected color to "green" while its (wrong) gray hex
        # stayed put simply re-derived "gray" and overwrote the fix — the edit
        # looked like it silently reverted. Only fall back to the hex when the
        # field is blank. Names still snap to the palette's spelling so the
        # general_color chip search keeps matching.
        from_hex = normalize_hex_name(c.hex_value, "")
        general = normalize_color_name(c.general_color) if c.general_color else from_hex
        rows.append(HatColor(
            color_name=c.color_name or from_hex,
            general_color=general,
            hex_value=c.hex_value,
            dominance_rank=rank,
            tier=c.tier.value,
        ))
    return rows


def analysis_color(
    name: str | None, hex_value: str, tier: str, *, general: str | None = None
) -> ColorTagWrite | None:
    """An analyzer's color as the wire type the owner's edits go through.

    So every stored row round-trips through `ColorTagWrite`: the name cleaned
    like any other and trimmed to the column (an analyzer is not a client to
    be refused, so an over-long name is cut rather than rejected). The tool
    schema already pins hex and tier, but it is a request to the model, not a
    guarantee — a color the wire type still refuses is dropped, logged,
    rather than stored or allowed to fail the whole analysis.
    `general=None` derives the palette name from the hex.
    """
    try:
        return ColorTagWrite(
            color_name=(name or "").strip()[:_COLOR_NAME_MAX] or None,
            general_color=general,
            hex_value=hex_value,
            tier=tier,
        )
    except ValidationError as exc:
        logger.warning(
            "Dropped an analyzed color the wire type refuses (%r, %r, %r): %s",
            name, hex_value, tier, exc.errors()[0]["msg"] if exc.errors() else exc,
        )
        return None


def replace_analysis_colors(hat: Hat, colors: Sequence[ColorTagWrite]) -> bool:
    """Replace `hat`'s palette with an analysis's, unless the owner set it.

    The one gate every analysis color write goes through — Claude's and the
    fallback's. False, with nothing written, when the palette is the owner's
    (`COLORS_OWNER_SOURCE`): their correction sticks through any re-analysis,
    the way a manual price does. Mutates `hat`; the caller commits.
    """
    if hat.colors_source == COLORS_OWNER_SOURCE:
        return False
    hat.colors.clear()
    hat.colors.extend(_color_rows(colors))
    return True


async def set_colors(db: AsyncSession, hat_id: int, colors: Sequence[ColorTagWrite]) -> Hat:
    """Replace a hat's palette with `colors`, ranked by position.

    Rank by position, ignoring whatever the client sent. Ranks are the only
    handle the UI has on a row — it edits and removes BY rank — so a duplicate
    makes one tap hit two colors, and a gap invites one: the add path picks
    `colors.length + 1`, which collides the moment the ranks aren't dense
    (ranks [1,3] + length 2 → 3). Storing them verbatim let that state
    persist. Position is already the client's intended order, so this is
    authoritative rather than a guess.

    Lived in the route, which is why it was the one hat edit the activity log
    never saw: every other hat write funnels through this module and is
    audited here.

    Setting a palette makes it the OWNER's (`colors_source`), so a later
    re-analysis leaves it alone; an empty list hands the colors back to
    analysis. A person correcting "gray" to "forest green" and then tapping
    Reanalyze used to get the analyzer's gray back, with nothing saying why.
    """
    hat = await get_hat(db, hat_id)
    previous = [c.color_name for c in sorted(hat.colors, key=lambda c: c.dominance_rank)]
    for color in list(hat.colors):
        await db.delete(color)

    rows = _color_rows(colors)
    for row in rows:
        row.hat_id = hat.id
        db.add(row)
    stored = [row.color_name for row in rows]
    hat.colors_source = COLORS_OWNER_SOURCE if rows else None

    await db.commit()
    await activity_service.log_and_commit(
        db, kind=KIND_COLORS, entity_type="hat", entity_id=hat_id,
        summary=f"Hat #{hat_id} colors edited",
        details={"previous": previous, "colors": stored},
    )
    return await _reload_hat(db, hat_id)


async def replace_photo(db: AsyncSession, hat_id: int, photo_rel: str) -> Hat:
    """Make `photo_rel` (under the upload dir) the hat's photo and mark it for analysis.

    Deletes the outgoing photo and everything derived from it. Missing any of
    these leaves orphaned files on disk and, worse, a `thumb_path` pointing at
    the previous hat's thumbnail — the grid would show the old picture.

    The export derivative is NOT named by a column, so it cannot be picked up
    by iterating the paths on the hat: it is derived from the canonical
    photo's filename. 2.24.0 added it and this loop kept deleting three
    things, so every re-shot hat leaked an 800px WebP. No stale-image risk
    (the cache is mtime-checked against its source) — just a slow leak on a Pi.

    The caller queues (or runs) the analysis; this only records the photo.
    """
    hat = await get_hat(db, hat_id)
    if hat.photo_path:
        export_derivative_path(cfg.upload_dir, hat.photo_path).unlink(missing_ok=True)
    for stale in (hat.photo_path, hat.original_path, hat.thumb_path):
        if stale:
            (cfg.upload_dir / stale).unlink(missing_ok=True)
    hat.original_path = None
    hat.thumb_path = None
    hat.photo_path = photo_rel
    hat.analysis_status = AnalysisStatus.pending.value
    hat.analysis_error = None
    hat.analyzed_at = None
    await db.commit()
    await activity_service.log_and_commit(
        db, kind=KIND_PHOTO, entity_type="hat", entity_id=hat_id,
        summary=f"Hat #{hat_id} photo replaced",
    )
    return await _reload_hat(db, hat_id)


def owner_today() -> date:
    """The calendar day a wear with no stated date lands on: the box's own day.

    A person's "today", not a timestamp — which is why this is not the
    `datetime.now(timezone.utc)` convention. That rule is for instants; a UTC
    calendar day logged every tap after 17:00 in California as TOMORROW, and
    the once-a-day idempotency then split the owner's day at 5 pm.

    The best answer is the client's, and the app sends it (`WearCreate.
    worn_at`). This is the fallback for a client that doesn't — the iOS
    Shortcut, a script — and it follows the host's zone (`TZ`), which on a
    box in the owner's house is the owner's day. Unset, it is UTC, exactly
    what it was before.
    """
    return datetime.now(timezone.utc).astimezone().date()


async def log_wear(db: AsyncSession, hat_id: int, worn_at: date | None = None) -> Hat:
    """One tap: "wearing this today". Idempotent per day.

    Appends to the wear log and moves `date_last_worn` forward — never back,
    so a backdated wear adds to the count without pretending to be the most
    recent. The wear row keeps the date the tap REPLACED
    (`WearLog.date_last_worn_before`): `date_last_worn` is also typed by hand,
    and a hand-typed date has no wear row behind it for an undo to fall back on.
    """
    hat = await get_hat(db, hat_id)
    if hat.disposed_at is not None:
        raise errors.Conflict("Hat is disposed")
    day = worn_at or owner_today()
    if day in await _wear_days(db, hat_id):
        return hat

    previous = hat.date_last_worn
    db.add(WearLog(hat_id=hat.id, worn_at=day, date_last_worn_before=previous))
    if previous is None or day > previous:
        hat.date_last_worn = day
    # Same transaction as the wear itself, not `log_and_commit`: the audit row
    # says a wear happened, so it exists exactly when the wear does — a tap
    # that loses the same-day race below leaves neither behind.
    await activity_service.log_activity(
        db, kind=KIND_WORN, entity_type="hat", entity_id=hat_id,
        summary=f"Hat #{hat_id} worn {day.isoformat()}",
        details={
            "worn_at": day.isoformat(),
            "previous_date_last_worn": previous.isoformat() if previous else None,
        },
    )
    try:
        await db.commit()
    except IntegrityError:
        # A concurrent tap won the same-day slot (uq_wear_hat_day) — the day
        # is already logged, so this tap is simply a no-op.
        await db.rollback()
    return await _reload_hat(db, hat_id)


async def _wear_days(db: AsyncSession, hat_id: int) -> set[date]:
    """The days a hat has a wear logged — queried, not read off `Hat.wear_logs`,
    which no hat query loads (reads need only the count)."""
    return set(
        (await db.execute(select(WearLog.worn_at).where(WearLog.hat_id == hat_id))).scalars()
    )


async def undo_wear(db: AsyncSession, hat_id: int) -> Hat:
    """Undo the most recent wear entry (mis-taps happen) — and ONLY that.

    `date_last_worn` goes back to what it would have been without the tap:
    the latest remaining wear, or the date the tap replaced (kept on the wear
    row itself), whichever is later. It used to be "the previous wear, else
    nothing", which treated the wear log as the only source of the date — so
    a hand-entered last-worn date, tapped over by mistake and undone, was
    simply erased. And a date the undone wear did not set (typed since, or
    later than the wear) is not touched at all.

    The replaced date was first recovered from the tap's activity-log row,
    which erased the hand-typed date all over again once the retention prune
    took that row — 90 days by default, one if the operator says so.
    """
    hat = await get_hat(db, hat_id)
    logs = list(
        (
            await db.execute(
                select(WearLog).where(WearLog.hat_id == hat_id).order_by(WearLog.worn_at)
            )
        ).scalars()
    )
    if not logs:
        raise errors.NotFound("No wear entries to undo")
    latest = logs[-1]
    if hat.date_last_worn == latest.worn_at:
        candidates = [w.worn_at for w in logs[:-1]]
        if latest.date_last_worn_before is not None:
            candidates.append(latest.date_last_worn_before)
        hat.date_last_worn = max(candidates, default=None)
    await db.delete(latest)
    await activity_service.log_activity(
        db, kind=KIND_WEAR_UNDONE, entity_type="hat", entity_id=hat_id,
        summary=f"Hat #{hat_id} wear on {latest.worn_at.isoformat()} undone",
    )
    await db.commit()
    return await _reload_hat(db, hat_id)


#: The columns an eBay comps block writes — `ebay_service.find_comps`' keys.
EBAY_COMP_FIELDS = (
    "ebay_avg_price",
    "ebay_median_price",
    "ebay_listing_count",
    "ebay_search_url",
    "ebay_checked_at",
)


def apply_ebay_comps(hat: Hat, comps: Mapping[str, object]) -> None:
    """Write a comps block onto `hat` — these five columns and nothing else.

    Named columns rather than `setattr` over whatever keys arrived: a service
    returning one key more would otherwise write it onto the hat unseen.
    """
    for field in EBAY_COMP_FIELDS:
        setattr(hat, field, comps.get(field))


async def refresh_ebay_comps(db: AsyncSession, hat_id: int) -> Hat:
    """Re-query eBay for one hat and persist the comps. `ebay_service.EbayError`
    propagates — the caller decides what an unreachable marketplace means."""
    hat = await get_hat(db, hat_id)
    comps = await ebay_service.find_comps(
        db, brand=hat.brand, model=hat.model_name, style=hat.style,
    )
    apply_ebay_comps(hat, comps)
    await db.commit()
    return await _reload_hat(db, hat_id)


async def backfill_thumbnails(db: AsyncSession, limit: int = 5000) -> int:
    """Generate the gallery thumbnail for hats that predate them.

    Runs off the boot path as a background task: it is pure image work over
    every existing photo, which on a Pi is slow enough that doing it inline
    would delay the app becoming reachable.

    Idempotent — only touches hats with a photo and no usable thumbnail, so a
    restart mid-run picks up where it left off rather than redoing everything.
    """
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


async def count_hats(
    db: AsyncSession,
    case_id: int | None = None,
    style: str | None = None,
    condition: str | None = None,
    status: str = "active",
) -> int:
    """How many hats a `list_hats` call would match if it were not capped.

    A SQL COUNT over the same filters, so `X-Total-Count` cannot disagree with
    the page beneath it. Exists because the list route's 1000-row ceiling is
    reached silently: the whole-collection views filter client-side, so a
    truncated response looks like missing hats and a smaller collection rather
    than like a short page.
    """
    query = select(func.count(Hat.id)).where(
        *_hat_list_filters(case_id, style, condition, status)
    )
    return int((await db.execute(query)).scalar() or 0)


async def list_by_analysis_status(
    db: AsyncSession, status: str, limit: int = 50, newest_first: bool = False
) -> list[Hat]:
    """Hats in a given `analysis_status`, for the admin queue and error views.

    Lives here rather than in the admin routes so the one place that knows how
    to load a Hat (`hat_loads`) stays the one place that does. Entities, not
    columns: `display_id` is a derived property that walks `hat.case`, so it
    cannot be selected — and it is the label a person actually recognizes.
    """
    query = select(Hat).options(*hat_loads()).where(Hat.analysis_status == status)
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


#: Cap on the per-hat list a run detail returns. A run covers the whole
#: collection, so the unbounded list is hundreds of rows nobody scrolls. The
#: failures sort first because they are what a run gets opened for, and the
#: totals beside the list are SQL COUNTs — never `len()` of this capped list.
JOB_HAT_LIMIT = 100


async def list_for_analysis_job(
    db: AsyncSession, job_id: int, limit: int = JOB_HAT_LIMIT
) -> list[Hat]:
    """The hats still tagged to one run, worst first.

    Entities rather than columns, and here rather than in the admin routes, for
    the reason `list_by_analysis_status` gives: `display_id` walks `hat.case`,
    so it cannot be selected, and it is the label a person recognizes.

    "Still tagged" is the whole caveat. `analysis_job_id` is one column and
    `create_job` overwrites it, so a hat belongs to the LATEST run that covered
    it — an older run's rows drain away as newer runs claim them. The caller
    pairs this with `count_for_analysis_job` and says so, rather than letting a
    shrinking list read as a run that did nothing.
    """
    query = (
        select(Hat)
        .options(*hat_loads())
        .where(Hat.analysis_job_id == job_id)
        .order_by(
            # Failures first: a finished run is opened to find out what broke.
            case((Hat.analysis_error.is_not(None), 0), else_=1),
            Hat.analyzed_at.desc().nulls_first(),
            Hat.id,
        )
    )
    result = await db.execute(query.limit(max(1, min(limit, JOB_HAT_LIMIT))))
    return list(result.scalars().all())


async def count_for_analysis_job(db: AsyncSession, job_id: int) -> tuple[int, int]:
    """(hats still tagged to this run, how many of those carry a failure).

    A COUNT, not `len()` of the capped list above — the mistake this codebase
    has now made four separate times.
    """
    row = (
        await db.execute(
            select(
                func.count(Hat.id),
                func.count(Hat.id).filter(*failed_analysis_filters()),
            ).where(Hat.analysis_job_id == job_id)
        )
    ).one()
    return int(row[0] or 0), int(row[1] or 0)


async def count_by_analysis_status(db: AsyncSession, status: str) -> int:
    """How many hats sit in one analysis status."""
    result = await db.execute(
        select(func.count(Hat.id)).where(Hat.analysis_status == status)
    )
    return int(result.scalar() or 0)


def _alarming_failure_filters(expected: str | None) -> tuple[ColumnElement[bool], ...]:
    """`failed_analysis_filters`, minus failures that begin with `expected`.

    For the nav badge and the error list, which say "go look". On an install
    with no Claude key at all, every photographed hat carries "No Anthropic
    API key configured…" — a normal outcome of the Basic ID the docs say is
    enough ("Nothing is mandatory"), not N failures: three keyless uploads put
    a red "3 hats failed analysis" on the Settings tab. The failures card
    still shows those hats, as ONE group whose `unretryable_reason` is the
    single "Add a key" nudge. The caller decides what is expected
    (`analysis_job_service.expected_failure_prefix`), because that depends on
    the key as configured now, which this module does not read.
    """
    filters = failed_analysis_filters()
    if not expected:
        return filters
    return (*filters, ~Hat.analysis_error.startswith(expected, autoescape=True))


async def list_failed_analyses(
    db: AsyncSession, limit: int = 20, newest_first: bool = True, *, expected: str | None = None
) -> list[Hat]:
    """Hats whose analysis FAILED — by `failed_analysis_filters`, not by status.

    The nav badge and the Settings error list both used
    `analysis_status == "error"`, which is the predicate the docstring on
    `failed_analysis_filters` exists to warn against, six hundred lines up in
    this same file. The two disagreed in exactly the case that matters most:
    when Claude is unreachable the pipeline degrades to **`fallback`**, not
    `error`, so during a total analysis outage the badge read **0** while the
    failures card read every hat in the collection. The one signal that is
    supposed to say "go look" was silent precisely when everything had broken.

    `skipped` (no API key) is the same shape. Carrying a failure string is the
    whole test, and it is what gets cleared on success — so it is the field
    that tracks whether a failure is still outstanding.

    `expected` names a failure text that is not a problem on this install —
    see `_alarming_failure_filters`.
    """
    query = (
        select(Hat)
        .options(*hat_loads())
        .where(*_alarming_failure_filters(expected))
    )
    if newest_first:
        query = query.order_by(Hat.analyzed_at.desc().nulls_last(), Hat.id.desc())
    else:
        query = query.order_by(Hat.id)
    result = await db.execute(query.limit(max(1, min(limit, 100))))
    return list(result.scalars().all())


async def count_failed_analyses(db: AsyncSession, *, expected: str | None = None) -> int:
    """How many hats carry an outstanding analysis failure. Backs the nav badge.

    A SQL COUNT over the whole set, never `len()` of the capped list above —
    the badge is a count and a truncated one would be a lie. Same `expected`
    exclusion as the list, so the badge counts what the list shows.
    """
    result = await db.execute(
        select(func.count(Hat.id)).where(*_alarming_failure_filters(expected))
    )
    return int(result.scalar() or 0)
