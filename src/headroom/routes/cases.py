from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.database import get_db
from headroom.schemas.case import CaseCreate, CaseDetail, CaseRead, CaseUpdate, HatSummary
from headroom.services import capacity as capacity_rules
from headroom.services import case_service
from headroom.services import retail_pricing

router = APIRouter(prefix="/api/cases", tags=["cases"])


def case_to_read(case) -> CaseRead:
    # Disposed hats free their slot, so they must not count toward occupancy —
    # `_validate_capacity` filters them, and a read model that didn't would
    # show a case as fuller than the validator considers it.
    hats = [h for h in (case.hats or []) if h.disposed_at is None]
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
        room_name=case.room.name if case.room else "Unknown",
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


def _case_to_detail(case) -> CaseDetail:
    # CaseDetail is CaseRead plus the hat list — derive the shared fields rather
    # than restating every one of them (they drifted apart too easily).
    #
    # Disposed hats are filtered here exactly as `case_to_read` filters them
    # out of `hat_count`/`hat_thumbs` forty lines up. They were not, so the
    # case page listed a sold hat as present under a header that counted it
    # gone. `dispose_hat` keeps `case_id` on purpose (a "previously held" view
    # may want it one day); until something renders that, it is not on show.
    return CaseDetail(
        **case_to_read(case).model_dump(),
        hats=[
            HatSummary(
                id=h.id,
                display_id=h.display_id,
                style=h.style,
                is_beanie=h.is_beanie,
                photo_path=h.photo_path,
                thumb_path=h.thumb_path,
            )
            for h in (case.hats or [])
            if h.disposed_at is None
        ],
    )


@router.post("", response_model=CaseRead, status_code=201)
async def create_case(data: CaseCreate, db: AsyncSession = Depends(get_db)):
    case = await case_service.create_case(db, data)
    return case_to_read(case)


@router.get("", response_model=list[CaseRead])
async def list_cases(db: AsyncSession = Depends(get_db)):
    cases = await case_service.list_cases(db)
    return [case_to_read(c) for c in cases]


@router.get("/{display_id}", response_model=CaseDetail)
async def get_case(display_id: str, db: AsyncSession = Depends(get_db)):
    case = await case_service.get_case_by_display_id(db, display_id)
    return _case_to_detail(case)


@router.put("/{display_id}", response_model=CaseRead)
async def update_case(
    display_id: str, data: CaseUpdate, db: AsyncSession = Depends(get_db)
):
    case = await case_service.update_case(db, display_id, data)
    return case_to_read(case)


@router.delete("/{display_id}", status_code=204)
async def delete_case(display_id: str, db: AsyncSession = Depends(get_db)):
    await case_service.delete_case(db, display_id)


# NOTE: there is deliberately no case-photo upload route.
# Every case looks identical from the outside, so a photo of one carried no
# information; `CaseRead.hat_thumbs` and the CaseCollage component show what is
# INSIDE instead. The grid switched to that, but the detail and edit pages kept
# their uploaders and this route kept serving them — a case with three hats in
# it rendered a screen-filling "NO PHOTO" box above its own contents.
