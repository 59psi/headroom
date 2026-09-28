from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.database import get_db
from headroom.routes._api import DomainErrorRoute
from headroom.schemas.case import CaseCreate, CaseDetail, CaseRead, CaseUpdate
from headroom.services import case_service

router = APIRouter(prefix="/api/cases", tags=["cases"], route_class=DomainErrorRoute)


@router.post("", response_model=CaseRead, status_code=201)
async def create_case(data: CaseCreate, db: AsyncSession = Depends(get_db)):
    case = await case_service.create_case(db, data)
    return case_service.case_read(case)


@router.get("", response_model=list[CaseRead])
async def list_cases(db: AsyncSession = Depends(get_db)):
    cases = await case_service.list_cases(db)
    return [case_service.case_read(c) for c in cases]


@router.get("/{display_id}", response_model=CaseDetail)
async def get_case(display_id: str, db: AsyncSession = Depends(get_db)):
    case = await case_service.get_case_by_display_id(db, display_id)
    return case_service.case_detail(case)


@router.put("/{display_id}", response_model=CaseRead)
async def update_case(
    display_id: str, data: CaseUpdate, db: AsyncSession = Depends(get_db)
):
    case = await case_service.update_case(db, display_id, data)
    return case_service.case_read(case)


@router.delete("/{display_id}", status_code=204)
async def delete_case(display_id: str, db: AsyncSession = Depends(get_db)):
    await case_service.delete_case(db, display_id)


# NOTE: there is deliberately no case-photo upload route.
# Every case looks identical from the outside, so a photo of one carried no
# information; `CaseRead.hat_thumbs` and the CaseCollage component show what is
# INSIDE instead. The grid switched to that, but the detail and edit pages kept
# their uploaders and this route kept serving them — a case with three hats in
# it rendered a screen-filling "NO PHOTO" box above its own contents.
