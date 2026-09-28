import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Response, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.config import settings
from headroom.database import get_db
from headroom.routes import _uploads
from headroom.routes._api import DomainErrorRoute
from headroom.schemas.hat import (
    ColorsUpdate,
    HatAssign,
    HatCondition,
    HatCreate,
    HatDispose,
    HatRead,
    HatStyle,
    HatUpdate,
    WearCreate,
)
from headroom.services import analysis_queue, hat_analysis_pipeline, hat_service, settings_service
from headroom.utils import photo as photo_utils

logger = logging.getLogger(__name__)

# `{hat_id:int}` on every path below, not a bare `{hat_id}`: a segment that
# only matches digits cannot swallow `/api/hats/import`, so the bulk-import
# routes no longer depend on being registered first. The ordering rule in
# `routes/__init__.py` used to be the only thing keeping `GET /api/hats/import`
# from answering 422 "hat_id is not an integer" — and nothing tested it.
router = APIRouter(prefix="/api/hats", tags=["hats"], route_class=DomainErrorRoute)


@router.post("", response_model=HatRead, status_code=201)
async def create_hat(data: HatCreate, db: AsyncSession = Depends(get_db)):
    hat = await hat_service.create_hat(db, data)
    return HatRead.model_validate(hat)


@router.get("", response_model=list[HatRead])
async def list_hats(
    response: Response,
    case_id: int | None = Query(None),
    # Typed, like `status` beside them: `?style=A-Game` (what the page prints)
    # used to answer 200 with nothing, indistinguishable from "no such hats",
    # where every other malformed filter here answers 422.
    style: HatStyle | None = Query(None),
    condition: HatCondition | None = Query(None),
    status: str = Query("active", pattern="^(active|disposed|all)$"),
    offset: int = Query(0, ge=0),
    # The ceiling is what the whole-collection views need: the Hats grid,
    # Valuation totals and the Home carousel all filter client-side, so a page
    # that stops short does not look truncated — it looks like hats vanished and
    # like the collection is worth less than it is. 1000 is well past a personal
    # collection while still bounding the response.
    limit: int = Query(50, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    hats = await hat_service.list_hats(db, case_id, style, condition, status, offset, limit)
    # A cap that is reached silently is a wrong number, not a short page. The
    # whole-collection views filter client-side, so a truncated response does
    # not look truncated — it looks like hats vanished and like the collection
    # is worth less than it is. `X-Total-Count` is a header rather than an
    # envelope because the body is a bare list that several callers consume
    # directly; reshaping it to add a total would be a breaking change to
    # solve a reporting problem.
    total = await hat_service.count_hats(db, case_id, style, condition, status)
    response.headers["X-Total-Count"] = str(total)
    # Warn only when a page was actually cut short of the total. The old
    # condition was `len(hats) == limit`, which is every full page — and once
    # the frontend started paging at 1000 (`listEveryHat`), every whole-
    # collection load of a >1000-hat shelf logged a false alarm about a
    # truncation the client was already handling.
    if len(hats) == limit and offset + limit < total:
        logger.warning(
            "GET /api/hats page of %d at offset=%d stopped short of %d total — a client "
            "that does not page will compute a wrong total",
            limit, offset, total,
        )
    return [HatRead.model_validate(h) for h in hats]


@router.get("/{hat_id:int}", response_model=HatRead)
async def get_hat(hat_id: int, db: AsyncSession = Depends(get_db)):
    return HatRead.model_validate(await hat_service.get_hat(db, hat_id))


@router.put("/{hat_id:int}", response_model=HatRead)
async def update_hat(
    hat_id: int, data: HatUpdate, db: AsyncSession = Depends(get_db)
):
    return HatRead.model_validate(await hat_service.update_hat(db, hat_id, data))


@router.delete("/{hat_id:int}", status_code=204)
async def delete_hat(hat_id: int, db: AsyncSession = Depends(get_db)):
    await hat_service.delete_hat(db, hat_id)


@router.patch("/{hat_id:int}/assign", response_model=HatRead)
async def assign_hat(
    hat_id: int, data: HatAssign, db: AsyncSession = Depends(get_db)
):
    hat = await hat_service.assign_hat(db, hat_id, data.case_id, data.room_id)
    return HatRead.model_validate(hat)


@router.post("/{hat_id:int}/dispose", response_model=HatRead)
async def dispose_hat(
    hat_id: int, data: HatDispose, db: AsyncSession = Depends(get_db)
):
    """Mark a hat as sold/gifted/lost/trashed/trade. Soft delete — undoable."""
    return HatRead.model_validate(await hat_service.dispose_hat(db, hat_id, data))


@router.delete("/{hat_id:int}/dispose", response_model=HatRead)
async def undispose_hat(hat_id: int, db: AsyncSession = Depends(get_db)):
    """Restore a previously-disposed hat back to active status."""
    return HatRead.model_validate(await hat_service.undispose_hat(db, hat_id))


@router.put("/{hat_id:int}/colors", response_model=HatRead)
async def update_hat_colors(
    hat_id: int, data: ColorsUpdate, db: AsyncSession = Depends(get_db)
):
    """Replace the hat's colors, ranked by their order in the body.

    `dominance_rank` in the body is ignored — see `hat_service.set_colors`.
    """
    return HatRead.model_validate(await hat_service.set_colors(db, hat_id, data.colors))


@router.post("/{hat_id:int}/photo", response_model=HatRead)
async def upload_hat_photo(
    hat_id: int,
    photo: UploadFile,
    db: AsyncSession = Depends(get_db),
):
    if not photo_utils.validate_image_content_type(photo.content_type):
        raise HTTPException(status_code=400, detail="Invalid image type")

    # 404 before a byte is spooled or decoded.
    await hat_service.get_hat(db, hat_id)

    upload_dir = settings.upload_dir / "hats"
    upload_dir.mkdir(parents=True, exist_ok=True)

    filename = photo_utils.generate_filename(photo.filename or "photo.jpg")
    output_path = upload_dir / filename
    async with _uploads.spooled_upload(photo, suffix=Path(filename).suffix, what="Photo") as tmp_path:
        try:
            final_path = await photo_utils.process_image_async(tmp_path, output_path)
        except photo_utils.UnreadableImage as exc:
            # The content-type check above reads a header the client chose;
            # this is the real gate. Unhandled, it was a 500 and an
            # `error.unhandled` row for an HTML file named `.png` — a client
            # error filed as an incident, on the one route that did not catch
            # what the logo route already caught.
            raise HTTPException(
                status_code=400, detail=photo_utils.UNREADABLE_IMAGE_DETAIL
            ) from exc

    # The photo itself is saved and shown immediately; the slow part (rembg →
    # Claude → eBay → Melin) is handed to the analysis worker so this request
    # returns in milliseconds instead of minutes and you can keep adding hats.
    # `enqueue` returning False means nothing is draining the queue, in which
    # case we run inline rather than leave the hat 'pending' forever.
    hat = await hat_service.replace_photo(db, hat_id, f"hats/{final_path.name}")

    if not analysis_queue.enqueue(hat.id):
        # No worker means no boot sweep either, so an unhandled failure here
        # would strand the hat on 'pending' with the UI spinning forever and no
        # endpoint able to clear it. Stamp the terminal status the worker would
        # have. The photo itself saved fine, so this stays a 200 — a failed
        # analysis is what `analysis_status` exists to report.
        await _run_inline(
            db, hat_id, "analysis",
            hat_analysis_pipeline.finalize_hat_photo(db, hat, final_path),
        )

    db.expire_all()
    return HatRead.model_validate(await hat_service.get_hat(db, hat_id))


@router.post("/{hat_id:int}/recut", response_model=HatRead)
async def recut_hat(hat_id: int, db: AsyncSession = Depends(get_db)):
    """Redo background removal from the retained original photo.

    The stored cutout can never be re-segmented — running rembg on an already
    transparent image eats the alpha and trims the bill a little more each pass,
    which is why `finalize_hat_photo` refuses to. So a re-cut has to start from
    the original JPEG, which is exactly why it is now kept.

    Implemented by pointing `photo_path` back at that original and queueing
    the pipeline in `cutout_only` mode: it sees a `.jpg`, cuts it, overwrites
    the old PNG in place, regenerates the thumbnail and export derivative, and
    STOPS. It used to run the whole pipeline — a Claude call per press, the
    analyzer's `model_name` and `design_notes` written over the owner's edits
    — which is not what "Redo cutout" says and not what the docs promised.
    The analysis record (`analysis_status`, `analyzed_at`, the error text) is
    therefore left exactly as it was; only the stage is published, and
    `HatRead` reports it while the photo is still the uncut original, so the
    page can show the cut in progress and knows to keep polling.
    """
    hat = await hat_service.get_hat(db, hat_id)
    if not hat.original_path:
        raise HTTPException(
            status_code=400,
            detail=(
                "No original was kept for this hat — it was analyzed before"
                " originals were retained. Re-upload the photo instead."
            ),
        )
    original = settings.upload_dir / hat.original_path
    if not original.exists():
        raise HTTPException(status_code=404, detail="Original photo missing on disk")

    hat.photo_path = hat.original_path
    hat.analysis_stage = hat_analysis_pipeline.STAGE_CUTOUT
    await db.commit()

    if not analysis_queue.enqueue(hat.id, cutout_only=True):
        await _run_inline(
            db, hat_id, "re-cut",
            hat_analysis_pipeline.finalize_hat_photo(db, hat, original, cutout_only=True),
            cutout_only=True,
        )

    db.expire_all()
    return HatRead.model_validate(await hat_service.get_hat(db, hat_id))


async def _run_inline(
    db: AsyncSession, hat_id: int, what: str, step, *, cutout_only: bool = False
) -> None:
    """Run a pipeline step with no worker behind it, and never strand the hat.

    Three routes fall back to running the pipeline inline when `enqueue()`
    returns False. Each had its own copy of this try/except — until the third
    (re-analyze) had none, and a failure there left `analysis_status='pending'`
    forever. One definition: on failure, roll back, record exactly what the
    worker would have (`analysis_queue.record_failure` — the same function,
    so the two paths cannot disagree again), and commit that.
    """
    try:
        await step
        await db.commit()
    except Exception as exc:
        logger.exception("Inline %s failed for hat=%s: %s", what, hat_id, exc)
        await db.rollback()
        hat = await hat_service.get_hat(db, hat_id)
        analysis_queue.record_failure(hat, exc, cutout_only=cutout_only)
        await db.commit()


@router.post("/{hat_id:int}/reanalyze", response_model=HatRead)
async def reanalyze_hat(hat_id: int, db: AsyncSession = Depends(get_db)):
    """Re-run Claude analysis against the current photo without re-uploading.

    Shares the analysis choreography with the upload pipeline
    (`reanalyze_existing_photo`) — bg removal is skipped since the stored photo
    is already the canonical cutout.
    """
    hat = await hat_service.get_hat(db, hat_id)
    if not hat.photo_path:
        raise HTTPException(status_code=400, detail="Hat has no photo to analyze")
    photo_path = settings.upload_dir / hat.photo_path
    if not photo_path.exists():
        raise HTTPException(status_code=404, detail="Photo file missing on disk")

    # Queue only the slow case. With a Claude key configured this is the same
    # multi-minute sequence the upload path had, so it goes to the worker. With
    # no key it's just local fallback color extraction — fast, and running it
    # inline is what preserves the 400 below, which can only be decided by
    # actually attempting the fallback.
    api_key, _source = await settings_service.get_anthropic_key(db)
    if api_key:
        hat.analysis_status = analysis_queue.PENDING
        hat.analysis_error = None
        hat.analyzed_at = None
        await db.commit()
        if analysis_queue.enqueue(hat.id):
            db.expire_all()
            return HatRead.model_validate(await hat_service.get_hat(db, hat_id))
        # Worker off: the hat is already `pending`, so this is the third inline
        # path and needs the same guard as the other two. It had none —
        # `reanalyze_existing_photo` catches only `ClaudeAnalysisError`, so any
        # other failure 500'd and left the hat `pending` forever with no error.
        await _run_inline(
            db, hat_id, "re-analysis",
            hat_analysis_pipeline.reanalyze_existing_photo(db, hat, photo_path),
        )
        db.expire_all()
        return HatRead.model_validate(await hat_service.get_hat(db, hat_id))

    # No key: local fallback only. The hat was never marked pending, so a
    # failure here cannot strand it; the 400 below is decided by attempting it.
    applied = await hat_analysis_pipeline.reanalyze_existing_photo(db, hat, photo_path)
    if not applied:
        raise HTTPException(
            status_code=400,
            detail="No Anthropic API key configured (and no fallback data available)",
        )
    await db.commit()
    db.expire_all()
    return HatRead.model_validate(await hat_service.get_hat(db, hat_id))


@router.post("/{hat_id:int}/wear", response_model=HatRead)
async def log_wear(
    hat_id: int, data: WearCreate, db: AsyncSession = Depends(get_db)
):
    """One tap: "wearing this today". Appends to the wear log and bumps
    date_last_worn. Idempotent per day — a second tap the same day is a no-op.

    Send `worn_at` as the wearer's own calendar day; omitted, the server's
    day is used (`hat_service.owner_today`)."""
    return HatRead.model_validate(await hat_service.log_wear(db, hat_id, data.worn_at))


@router.delete("/{hat_id:int}/wear/latest", response_model=HatRead)
async def undo_wear(hat_id: int, db: AsyncSession = Depends(get_db)):
    """Undo the most recent wear entry (mis-taps happen)."""
    return HatRead.model_validate(await hat_service.undo_wear(db, hat_id))
