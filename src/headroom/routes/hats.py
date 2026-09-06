import logging
import asyncio
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Response, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.config import settings
from headroom.database import get_db
from headroom.models.hat_color import HatColor
from headroom.schemas.hat import (
    ColorsUpdate,
    HatAssign,
    HatCreate,
    HatDispose,
    HatRead,
    HatUpdate,
    WearCreate,
)
from headroom.services import analysis_queue, hat_service, settings_service
from headroom.services.color_extraction import normalize_color_name, normalize_hex_name
from headroom.services.hat_analysis_pipeline import (
    finalize_hat_photo,
    reanalyze_existing_photo,
)
from headroom.utils.photo import (
    export_derivative_path,
    generate_filename,
    process_image_async,
    validate_image_content_type,
)
from headroom.utils.upload import copy_upload_capped

from headroom.models.wear_log import WearLog
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/hats", tags=["hats"])


def hat_to_read(hat) -> HatRead:
    """Hat ORM object -> HatRead. Every field maps by name off a column or one
    of the model's derived properties, so there is nothing to hand-copy."""
    return HatRead.model_validate(hat)


@router.post("", response_model=HatRead, status_code=201)
async def create_hat(data: HatCreate, db: AsyncSession = Depends(get_db)):
    hat = await hat_service.create_hat(db, data)
    return hat_to_read(hat)


@router.get("", response_model=list[HatRead])
async def list_hats(
    response: Response,
    case_id: int | None = Query(None),
    style: str | None = Query(None),
    condition: str | None = Query(None),
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
    return [hat_to_read(h) for h in hats]


@router.get("/{hat_id}", response_model=HatRead)
async def get_hat(hat_id: int, db: AsyncSession = Depends(get_db)):
    hat = await hat_service.get_hat(db, hat_id)
    return hat_to_read(hat)


@router.put("/{hat_id}", response_model=HatRead)
async def update_hat(
    hat_id: int, data: HatUpdate, db: AsyncSession = Depends(get_db)
):
    hat = await hat_service.update_hat(db, hat_id, data)
    return hat_to_read(hat)


@router.delete("/{hat_id}", status_code=204)
async def delete_hat(hat_id: int, db: AsyncSession = Depends(get_db)):
    await hat_service.delete_hat(db, hat_id)


@router.patch("/{hat_id}/assign", response_model=HatRead)
async def assign_hat(
    hat_id: int, data: HatAssign, db: AsyncSession = Depends(get_db)
):
    hat = await hat_service.assign_hat(db, hat_id, data.case_id, data.room_id)
    return hat_to_read(hat)


@router.post("/{hat_id}/dispose", response_model=HatRead)
async def dispose_hat(
    hat_id: int, data: HatDispose, db: AsyncSession = Depends(get_db)
):
    """Mark a hat as sold/gifted/lost/trashed/trade. Soft delete — undoable."""
    hat = await hat_service.dispose_hat(db, hat_id, data)
    return hat_to_read(hat)


@router.delete("/{hat_id}/dispose", response_model=HatRead)
async def undispose_hat(hat_id: int, db: AsyncSession = Depends(get_db)):
    """Restore a previously-disposed hat back to active status."""
    hat = await hat_service.undispose_hat(db, hat_id)
    return hat_to_read(hat)


@router.put("/{hat_id}/colors", response_model=HatRead)
async def update_hat_colors(
    hat_id: int, data: ColorsUpdate, db: AsyncSession = Depends(get_db)
):
    hat = await hat_service.get_hat(db, hat_id)

    for color in list(hat.colors):
        await db.delete(color)

    # Rank by position, ignoring whatever the client sent. Ranks are the only
    # handle the UI has on a row — it edits and removes BY rank — so a duplicate
    # makes one tap hit two colors, and a gap invites one: the add path picks
    # `colors.length + 1`, which collides the moment the ranks aren't dense
    # (ranks [1,3] + length 2 → 3). Storing them verbatim let that state persist.
    # Position is already the client's intended order, so this is authoritative
    # rather than a guess.
    for rank, c in enumerate(data.colors, start=1):
        # An explicitly-typed general_color is a CORRECTION and must win. This
        # used to derive the name from the hex whenever a hex was present, so
        # editing a mis-detected color to "green" while its (wrong) gray hex
        # stayed put simply re-derived "gray" and overwrote the fix — the edit
        # looked like it silently reverted. Only fall back to the hex when the
        # field is blank. Names still snap to the palette's spelling so the
        # general_color chip search keeps matching.
        general = (
            normalize_color_name(c.general_color)
            if (c.general_color or "").strip()
            else (normalize_hex_name(c.hex_value, c.color_name) if c.hex_value else "")
        )
        db.add(HatColor(
            hat_id=hat.id,
            color_name=c.color_name,
            general_color=general,
            hex_value=c.hex_value,
            dominance_rank=rank,
            tier=c.tier or "primary",
        ))

    await db.commit()
    db.expire_all()
    return hat_to_read(await hat_service.get_hat(db, hat_id))


@router.post("/{hat_id}/photo", response_model=HatRead)
async def upload_hat_photo(
    hat_id: int,
    photo: UploadFile,
    db: AsyncSession = Depends(get_db),
):
    if not validate_image_content_type(photo.content_type):
        raise HTTPException(status_code=400, detail="Invalid image type")

    hat = await hat_service.get_hat(db, hat_id)

    upload_dir = settings.upload_dir / "hats"
    upload_dir.mkdir(parents=True, exist_ok=True)

    filename = generate_filename(photo.filename or "photo.jpg")
    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(filename).suffix) as tmp:
        tmp_path = Path(tmp.name)
    # Off the event loop, like the bulk-import and share-target routes: a 20 MB
    # phone photo spooling through a `SpooledTemporaryFile` onto an SD card is
    # not instant, and this was the one single-file route still doing it inline.
    with tmp_path.open("wb") as fh:
        await asyncio.to_thread(copy_upload_capped, photo, fh, what="Photo")

    output_path = upload_dir / filename
    try:
        final_path = await process_image_async(tmp_path, output_path)
    finally:
        tmp_path.unlink(missing_ok=True)

    # Delete the outgoing photo and everything derived from it. Missing any of
    # these leaves orphaned files on disk and, worse, a `thumb_path` pointing at
    # the previous hat's thumbnail — the grid would show the old picture.
    #
    # The export derivative is NOT named by a column, so it cannot be picked up
    # by iterating the paths on the hat: it is derived from the canonical
    # photo's filename. 2.24.0 added it and this loop kept deleting three
    # things, so every re-shot hat leaked an 800px WebP. No stale-image risk
    # (the cache is mtime-checked against its source) — just a slow leak on a Pi.
    if hat.photo_path:
        export_derivative_path(settings.upload_dir, hat.photo_path).unlink(missing_ok=True)
    for stale in (hat.photo_path, hat.original_path, hat.thumb_path):
        if stale:
            (settings.upload_dir / stale).unlink(missing_ok=True)
    hat.original_path = None
    hat.thumb_path = None

    # The photo itself is saved and shown immediately; the slow part (rembg →
    # Claude → eBay → Melin) is handed to the analysis worker so this request
    # returns in milliseconds instead of minutes and you can keep adding hats.
    # `enqueue` returning False means nothing is draining the queue, in which
    # case we run inline rather than leave the hat 'pending' forever.
    hat.photo_path = f"hats/{final_path.name}"
    hat.analysis_status = analysis_queue.PENDING
    hat.analysis_error = None
    hat.analyzed_at = None
    await db.commit()

    if not analysis_queue.enqueue(hat.id):
        # No worker means no boot sweep either, so an unhandled failure here
        # would strand the hat on 'pending' with the UI spinning forever and no
        # endpoint able to clear it. Stamp the terminal status the worker would
        # have. The photo itself saved fine, so this stays a 200 — a failed
        # analysis is what `analysis_status` exists to report.
        await _run_inline(db, hat_id, "analysis", finalize_hat_photo(db, hat, final_path))

    db.expire_all()
    return hat_to_read(await hat_service.get_hat(db, hat_id))


@router.post("/{hat_id}/recut", response_model=HatRead)
async def recut_hat(hat_id: int, db: AsyncSession = Depends(get_db)):
    """Redo background removal from the retained original photo.

    The stored cutout can never be re-segmented — running rembg on an already
    transparent image eats the alpha and trims the bill a little more each pass,
    which is why `finalize_hat_photo` refuses to. So a re-cut has to start from
    the original JPEG, which is exactly why it is now kept.

    Implemented by pointing `photo_path` back at that original and queueing:
    the pipeline then sees a `.jpg`, cuts it, and overwrites the old PNG in
    place. No special-casing anywhere — it is the upload path, run again.
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
    hat.analysis_status = analysis_queue.PENDING
    hat.analysis_error = None
    hat.analyzed_at = None
    await db.commit()

    if not analysis_queue.enqueue(hat.id):
        await _run_inline(db, hat_id, "re-cut", finalize_hat_photo(db, hat, original))

    db.expire_all()
    return hat_to_read(await hat_service.get_hat(db, hat_id))


async def _run_inline(db: AsyncSession, hat_id: int, what: str, step) -> None:
    """Run a pipeline step with no worker behind it, and never strand the hat.

    Three routes fall back to running the pipeline inline when `enqueue()`
    returns False. Each had its own copy of this try/except — until the third
    (re-analyze) had none, and a failure there left `analysis_status='pending'`
    forever. One definition: on failure, roll back, stamp the terminal status
    the worker would have written, and commit that.
    """
    try:
        await step
        await db.commit()
    except Exception as exc:
        logger.exception("Inline %s failed for hat=%s: %s", what, hat_id, exc)
        await db.rollback()
        hat = await hat_service.get_hat(db, hat_id)
        analysis_queue.stamp_failure(hat, exc)
        await db.commit()


@router.post("/{hat_id}/reanalyze", response_model=HatRead)
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
            return hat_to_read(await hat_service.get_hat(db, hat_id))
        # Worker off: the hat is already `pending`, so this is the third inline
        # path and needs the same guard as the other two. It had none —
        # `reanalyze_existing_photo` catches only `ClaudeAnalysisError`, so any
        # other failure 500'd and left the hat `pending` forever with no error.
        await _run_inline(
            db, hat_id, "re-analysis", reanalyze_existing_photo(db, hat, photo_path)
        )
        db.expire_all()
        return hat_to_read(await hat_service.get_hat(db, hat_id))

    # No key: local fallback only. The hat was never marked pending, so a
    # failure here cannot strand it; the 400 below is decided by attempting it.
    applied = await reanalyze_existing_photo(db, hat, photo_path)
    if not applied:
        raise HTTPException(
            status_code=400,
            detail="No Anthropic API key configured (and no fallback data available)",
        )
    await db.commit()
    db.expire_all()
    return hat_to_read(await hat_service.get_hat(db, hat_id))

@router.post("/{hat_id}/wear", response_model=HatRead)
async def log_wear(
    hat_id: int, data: WearCreate, db: AsyncSession = Depends(get_db)
):
    """One tap: "wearing this today". Appends to the wear log and bumps
    date_last_worn. Idempotent per day — a second tap the same day is a no-op."""

    hat = await hat_service.get_hat(db, hat_id)
    if hat.disposed_at is not None:
        raise HTTPException(status_code=409, detail="Hat is disposed")
    worn_at = data.worn_at or datetime.now(timezone.utc).date()
    already = any(w.worn_at == worn_at for w in (hat.wear_logs or []))
    if not already:
        db.add(WearLog(hat_id=hat.id, worn_at=worn_at))
        if hat.date_last_worn is None or worn_at > hat.date_last_worn:
            hat.date_last_worn = worn_at
        try:
            await db.commit()
        except IntegrityError:
            # A concurrent tap won the same-day slot (uq_wear_hat_day) — the
            # day is already logged, so this tap is simply a no-op.
            await db.rollback()
        db.expire_all()
    return hat_to_read(await hat_service.get_hat(db, hat_id))


@router.delete("/{hat_id}/wear/latest", response_model=HatRead)
async def undo_wear(hat_id: int, db: AsyncSession = Depends(get_db)):
    """Undo the most recent wear entry (mis-taps happen)."""
    hat = await hat_service.get_hat(db, hat_id)
    logs = sorted(hat.wear_logs or [], key=lambda w: w.worn_at)
    if not logs:
        raise HTTPException(status_code=404, detail="No wear entries to undo")
    await db.delete(logs[-1])
    hat.date_last_worn = logs[-2].worn_at if len(logs) > 1 else None
    await db.commit()
    db.expire_all()
    return hat_to_read(await hat_service.get_hat(db, hat_id))

