"""End-to-end pipeline for analysing a freshly-uploaded hat photo.

Steps:
  1. Process upload (resize / convert to JPEG) — handled by photo utils.
  2. Remove background → transparent PNG (this becomes the canonical photo).
  3. Call Claude Vision for brand / model / colors / price / notes.
  4. Build Melin Recap deep-link if applicable.
  5. Persist analysis results onto the Hat row (caller commits).

The pipeline degrades gracefully: any single step can fail without breaking
the others. If Claude is not configured (or errors), a best-effort fallback
runs instead: dominant colors from the rembg cutout's alpha mask (hat pixels
only — never the background) plus a Google Vision logo-based brand guess when
that key is configured. Fallback data lands as `analysis_status='fallback'`;
if the fallback produces nothing the hat gets `skipped`/`error` as before.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from headroom.config import settings
from headroom.database import async_session
from headroom.models.hat import Hat
from headroom.models.hat_color import HatColor
from headroom.schemas.hat import KNOWN_CONSTRUCTIONS
from headroom.services import retail_pricing, settings_service
from headroom.services.background_removal import remove_background
from headroom.services.claude_analysis import (
    ClaudeAnalysisError,
    HatAnalysis,
    analyze_hat_image,
)
from headroom.services.color_extraction import extract_hat_colors, normalize_hex_name
from headroom.services.ebay_service import EbayError, find_comps
from headroom.services.google_vision import GoogleVisionError, detect_brand_logo
from headroom.services.melin_recap import (
    MelinRecapError,
    build_resale_pointer,
    fetch_resale_stats,
    is_melin,
)
from headroom.utils.photo import THUMBS_DIR, make_thumbnail_async

logger = logging.getLogger(__name__)


# The steps a person can be told about, in the order they run. Kept as constants
# so the UI's labels and the writer can't drift apart.
STAGE_CUTOUT = "cutout"
STAGE_IDENTIFYING = "identifying"
STAGE_PRICING = "pricing"
STAGE_RESALE = "resale"


async def _publish_stage(hat_id: int | None, stage: str | None) -> None:
    """Say which step is running, so the UI can beat a bare "Analyzing…".

    Deliberately a SEPARATE session doing one targeted UPDATE, rather than a
    commit on the pipeline's own session. Two reasons, and both are load-bearing:

    * The pipeline sets `photo_path` early and commits only at the end, so that
      the queue can throw the whole run away if the photo was replaced while it
      ran. Committing mid-pipeline would persist that stale path and defeat the
      guard.
    * It is not the write-lock hazard `no_autoflush` guards against — that is a
      transaction opened by an incidental flush and then held across minutes of
      network calls. This takes the lock and gives it straight back, before the
      slow call begins.

    Best-effort: progress reporting must never be the thing that fails an
    analysis.
    """
    if hat_id is None:
        return
    try:
        async with async_session() as db:
            await db.execute(
                update(Hat).where(Hat.id == hat_id).values(analysis_stage=stage)
            )
            await db.commit()
    except Exception as exc:  # noqa: BLE001 — cosmetic; never fail a run for it
        logger.debug("Could not publish analysis stage for hat %s: %s", hat_id, exc)


async def finalize_hat_photo(
    db: AsyncSession,
    hat: Hat,
    processed_jpeg_path: Path,
) -> Hat:
    """Apply background removal + Claude analysis to a freshly-saved JPEG.

    The transparent PNG (if produced) replaces the JPEG as the canonical photo.
    Mutates `hat` in place. Caller is responsible for the final commit.
    """
    photo_dir = processed_jpeg_path.parent

    # 1. Background removal → transparent PNG, swap as canonical.
    #
    # Skipped when the input IS already a cutout. Uploads are normalised to JPEG
    # before they reach here, so a .png input can only be a photo that has been
    # through rembg already — which is exactly what the reanalyze path hands us.
    # Re-running it there is destructive, not merely wasteful: `cutout_target`
    # is the stem, `_remove_sync` appends ".png", so the output path resolves to
    # the *input file*. rembg would re-segment an image whose background is
    # already transparent and write the result back over the only copy, eating
    # further into the alpha and trimming a little more of the bill on every
    # pass. That is the progressive fading — each Reanalyze made it worse.
    t_rembg = 0.0
    canonical_path = processed_jpeg_path
    if processed_jpeg_path.suffix.lower() != ".png":
        await _publish_stage(hat.id, STAGE_CUTOUT)
        t_rembg0 = time.monotonic()
        cutout_target = photo_dir / processed_jpeg_path.stem
        transparent_path = await remove_background(processed_jpeg_path, cutout_target)
        t_rembg = time.monotonic() - t_rembg0
        if transparent_path is not None and transparent_path.exists():
            # Keep the JPEG rather than deleting it. It is the ONLY thing a
            # re-cut can work from: the cutout can't be re-segmented (that path
            # is destructive — see above), so without the original a poor
            # cutout could only ever be fixed by re-uploading the photo. It
            # stays beside the PNG rather than moving, so a re-cut runs through
            # exactly this code path again with nothing special-cased.
            if transparent_path.resolve() != processed_jpeg_path.resolve():
                hat.original_path = f"hats/{processed_jpeg_path.name}"
            canonical_path = transparent_path

    hat.photo_path = f"hats/{canonical_path.name}"

    # Gallery derivative. Best-effort: a missing thumbnail costs bandwidth, a
    # failed upload costs the hat.
    thumb = await make_thumbnail_async(
        canonical_path, photo_dir / THUMBS_DIR / canonical_path.stem
    )
    hat.thumb_path = f"hats/{THUMBS_DIR}/{thumb.name}" if thumb else None

    # Everything below interleaves DB reads (API key, model, eBay creds) with
    # slow network calls. With autoflush on, the FIRST of those reads flushes
    # the `photo_path` write above — which opens a SQLite write transaction, and
    # SQLite holds that lock until commit. The lock would therefore stay held
    # across the entire Claude + eBay + Melin sequence: minutes, worst case.
    # Every other writer in the process then waits out `busy_timeout` and fails
    # with "database is locked" — so adding a second hat while the first is
    # analysing would error out. Deferring the flush shrinks the lock window to
    # the caller's commit. Safe because nothing in here re-queries the hat row;
    # the pending change only has to be visible at commit time.
    with db.no_autoflush:
        # 2. Claude analysis
        api_key, _source = await settings_service.get_anthropic_key(db)
        if not api_key:
            hat.analysis_status = "skipped"
            hat.analysis_error = "No Anthropic API key configured."
            hat.analyzed_at = datetime.now(timezone.utc)
            await run_fallback_analysis(
                db, hat, canonical_path, reason="No Anthropic API key configured"
            )
            return hat

        model_id, _model_source = await settings_service.get_anthropic_model(db)

        await _publish_stage(hat.id, STAGE_IDENTIFYING)
        t_claude0 = time.monotonic()
        try:
            analysis: HatAnalysis = await analyze_hat_image(
                canonical_path, api_key,
                model=model_id, selected_style=hat.style,
                selected_construction=hat.construction,
                known_series=await _known_series(db),
            )
        except ClaudeAnalysisError as exc:
            logger.warning(
                "Hat analysis failed for hat %s (rembg=%.2fs claude=%.2fs): %s",
                hat.id, t_rembg, time.monotonic() - t_claude0, exc,
            )
            hat.analysis_status = "error"
            hat.analysis_error = str(exc)
            hat.analyzed_at = datetime.now(timezone.utc)
            await run_fallback_analysis(
                db, hat, canonical_path, reason=f"Claude analysis failed: {exc}"
            )
            return hat
        t_claude = time.monotonic() - t_claude0

        _apply_analysis(hat, analysis)
        await _canonicalize_analysis_text(db, hat)
        await _publish_stage(hat.id, STAGE_PRICING)
        t_ebay0 = time.monotonic()
        await _refresh_ebay_comps(db, hat)
        await _publish_stage(hat.id, STAGE_RESALE)
        await refresh_melin_resale(hat)
    logger.info(
        "hat=%s analyzed · rembg=%.2fs claude=%.2fs ebay+resale=%.2fs status=%s",
        hat.id, t_rembg, t_claude, time.monotonic() - t_ebay0, hat.analysis_status,
    )
    return hat


async def _refresh_ebay_comps(db: AsyncSession, hat: Hat) -> None:
    """Best-effort eBay comparable-listings refresh — never fails the caller."""
    if hat.brand and hat.model_name:
        try:
            comps = await find_comps(db, brand=hat.brand, model=hat.model_name, style=hat.style)
            for k, v in comps.items():
                setattr(hat, k, v)
        except EbayError as exc:
            logger.info("eBay comp refresh skipped for hat %s: %s", hat.id, exc)


async def reanalyze_existing_photo(
    db: AsyncSession, hat: Hat, photo_path: Path
) -> bool:
    """Re-run analysis against an already-processed cutout — no bg removal.

    Shares the key-check → Claude → apply → eBay → resale choreography (with
    graceful fallback) with finalize_hat_photo, instead of the route hand-rolling
    its own drifting copy. Mutates `hat`; caller commits. Returns False only when
    there is no Claude key AND the fallback produced nothing (caller → HTTP 400).
    """
    # Same SQLite write-lock hazard `finalize_hat_photo` guards against, and for
    # the same reason: once `_apply_analysis` dirties the hat, the next DB read
    # (eBay creds, or the Google Vision key on the fallback path) autoflushes,
    # which opens a write transaction SQLite holds until commit — across the
    # eBay OAuth + Browse calls and two 30s Melin requests. Every other writer
    # then waits out `busy_timeout` and fails with "database is locked", so
    # tapping "wearing this today" during a reanalysis would 500.
    with db.no_autoflush:
        api_key, _source = await settings_service.get_anthropic_key(db)
        if not api_key:
            return await run_fallback_analysis(
                db, hat, photo_path, reason="No Anthropic API key configured"
            )

        model_id, _msrc = await settings_service.get_anthropic_model(db)
        await _publish_stage(hat.id, STAGE_IDENTIFYING)
        try:
            analysis = await analyze_hat_image(
                photo_path, api_key, model=model_id, selected_style=hat.style,
                selected_construction=hat.construction,
                known_series=await _known_series(db),
            )
        except ClaudeAnalysisError as exc:
            logger.warning("Reanalysis failed for hat %s: %s", hat.id, exc)
            hat.analysis_status = "error"
            hat.analysis_error = str(exc)
            hat.analyzed_at = datetime.now(timezone.utc)
            await run_fallback_analysis(
                db, hat, photo_path, reason=f"Claude analysis failed: {exc}"
            )
            return True

        _apply_analysis(hat, analysis)
        await _canonicalize_analysis_text(db, hat)
        await _publish_stage(hat.id, STAGE_PRICING)
        await _refresh_ebay_comps(db, hat)
        await _publish_stage(hat.id, STAGE_RESALE)
        await refresh_melin_resale(hat)
        return True


# For the resale source label. The stored values are snake_case enum names;
# these read as English in the middle of a sentence.
_CONDITION_WORDS: dict[str, str] = {
    "new_with_tags": "new-with-tags",
    "new": "new-without-tags",
    "worn": "worn",
}


async def refresh_melin_resale(hat: Hat) -> None:
    """Fill resale_price with a live Melin Recap median. Best-effort.

    Runs for Melin hats only; leaves the deep-link pointer fields alone and
    the price null when the marketplace API is unreachable (the pre-live
    behavior).
    """
    if not is_melin(hat.brand):
        return
    try:
        # Condition and size are the hat's own, so the median comes back from
        # listings of the same thing in the same shape rather than from the
        # whole category averaged together and adjusted by a guess.
        stats = await fetch_resale_stats(
            hat.style, hat.model_name, condition=hat.condition, size=hat.size
        )
    except MelinRecapError as exc:
        logger.info("Melin Recap stats skipped for hat %s: %s", hat.id, exc)
        return
    if not stats:
        return
    # A person's own number outranks a scraped median, and a re-analysis must
    # not quietly overwrite it -- reanalyze runs on a schedule and on demand,
    # so anything it clobbers is gone without a prompt.
    if hat.resale_price_scope == "manual":
        return
    hat.resale_price = stats["median"]
    scope = "model" if stats["sample"] == "model" else "category"
    hat.resale_price_scope = scope
    # Name what was actually matched. "median of 8 live listings" gives no way
    # to tell a figure drawn from this exact hat in this exact condition from
    # one drawn from the whole category — and those deserve different trust.
    qualifiers = " ".join(
        part for part in (
            hat.size.replace("_", "-") if stats["size_matched"] and hat.size else "",
            _CONDITION_WORDS.get(hat.condition, "") if stats["condition_matched"] else "",
        ) if part
    )
    hat.resale_price_source = (
        f"Melin Recap · median of {stats['count']} live "
        f"{qualifiers + ' ' if qualifiers else ''}{scope} listings"
    )
    hat.resale_checked_at = datetime.now(timezone.utc)


async def run_fallback_analysis(
    db: AsyncSession, hat: Hat, photo_path: Path, *, reason: str
) -> bool:
    """Best-effort analysis without Claude: mask colors + Google logo brand.

    Colors come only from the rembg cutout's alpha mask (background rejected
    by construction); a PNG suffix is the marker that a cutout exists. Brand
    comes from Google Vision logo detection when that key is configured.

    Mutates `hat` and sets `analysis_status='fallback'` only if at least one
    piece of data was obtained; otherwise leaves the hat untouched (caller's
    skipped/error state stands) and returns False. Never raises.
    """
    colors = []
    if photo_path.suffix.lower() == ".png":
        try:
            colors = await asyncio.to_thread(extract_hat_colors, photo_path)
        except Exception as exc:  # noqa: BLE001 — fallback must never break uploads
            logger.warning("Fallback color extraction failed for hat %s: %s", hat.id, exc)

    brand: str | None = None
    google_key, _gsrc = await settings_service.get_google_vision_key(db)
    if google_key:
        try:
            logo = await detect_brand_logo(photo_path, google_key)
            if logo:
                brand = logo[0]
        except GoogleVisionError as exc:
            logger.info("Fallback logo detection skipped for hat %s: %s", hat.id, exc)

    if not colors and not brand:
        return False

    provided = []
    if colors:
        hat.colors.clear()
        for rank, color in enumerate(colors, start=1):
            hat.colors.append(
                HatColor(
                    color_name=color.name,
                    general_color=color.name,
                    hex_value=color.hex,
                    dominance_rank=rank,
                    tier=color.tier,
                )
            )
        provided.append("colors from photo cutout")
    if brand:
        hat.brand = brand
        # Google Vision's LOGO_DETECTION only fires on a mark it actually saw,
        # so this path is evidence by construction — exactly what the field
        # records. Naming the source keeps it honest about who found it.
        hat.logo_detected = f"{brand} — logo detected by Google Vision"
        provided.append("brand via Google logo detection")
        _apply_resale_pointer(hat)
        await refresh_melin_resale(hat)

    hat.analysis_status = "fallback"
    hat.analysis_error = (
        f"{reason} — basic fallback applied ({', '.join(provided)}). "
        "Add a Claude API key and Reanalyze for full identification."
    )
    hat.analyzed_at = datetime.now(timezone.utc)
    return True


def _apply_resale_pointer(hat: Hat) -> None:
    """Attach the resale deep link + pointer price when the brand qualifies.

    Shared by the Claude path and the logo-detection fallback — both learn the
    brand and then need exactly this.
    """
    pointer = build_resale_pointer(hat.brand, hat.style)
    if not pointer:
        return
    # The deep link is always safe to refresh. The PRICE is not: the pointer's
    # is None by construction, so assigning it unconditionally erased whatever
    # was in the column and relied on refresh_melin_resale() putting a number
    # back. When the marketplace API is unreachable it doesn't, and a price a
    # person had typed in was gone with nothing logged -- on a path that also
    # runs unattended from the reanalyze-all queue.
    hat.resale_price_url = pointer["resale_price_url"]
    if hat.resale_price_scope == "manual":
        return
    hat.resale_price = pointer["resale_price"]
    hat.resale_price_source = pointer["resale_price_source"]
    hat.resale_price_scope = None
    hat.resale_checked_at = datetime.now(timezone.utc)


# Words that mean "no construction identified" rather than naming one.
_NON_ANSWERS = frozenset({"standard", "none", "n/a", "na", "unknown", "regular"})


def _apply_construction(hat: Hat, construction: str | None) -> None:
    """Fill in the construction only when nobody has stated one.

    Claude never overwrites a construction that is already recorded. It was
    briefly allowed to — the idea being that naming a fabric is a positive
    identification and should correct a stale value — but in practice it reads
    HYDRO and HYDROLite off a photo unreliably (the distinguishing features are
    bonded seams, a gel-welded logo and a sweatband, none of which survive a
    single front-on shot), so "correcting" mostly meant replacing a right answer
    from the person holding the hat with a wrong one from a photo.

    The owner always wins. Clearing the field makes it eligible again, which is
    the deliberate way to ask for a re-identification.

    `_NON_ANSWERS` exists because the old tool schema was an enum whose "I
    can't tell" member was the literal string "standard". A model still
    answering that way — a cached prompt, a fine-tune, a future edit that
    reinstates it — must not get "standard" written down as if it were a fabric.
    """
    if hat.construction:
        return
    if construction and construction.strip().casefold() not in _NON_ANSWERS:
        hat.set_construction(construction)


def _strip_contradicting_construction(
    model_name: str | None, construction: str | None
) -> str | None:
    """Drop a construction from the model name that the hat isn't.

    melin names read "<line> <construction>" — "A-Game Hydro", "Coronado
    HYDROLite" — so a model name can assert a build all by itself. A hat the
    owner recorded as Thermal, analysed before that value was sent to Claude,
    kept a stored name like "A-Game HYDROLite": the construction field was
    right and the name a person actually reads was wrong.

    Re-analysis now sends the owner's construction as ground truth, so a fresh
    answer arrives correct. This covers the remaining case — Claude returning
    null, which leaves the previous, contradicting name in place — so a full
    rescan repairs old rows instead of preserving them.

    Removes rather than substitutes. Rewriting "A-Game HYDROLite" to "A-Game
    Thermal" would be inventing a product name; "A-Game" is merely less
    specific, and true.

    Word boundaries matter: "HYDRO" must NOT match inside "HYDROLite", or a
    genuine HYDROLite hat would be left reading "Coronado Lite".
    """
    if not model_name or not construction:
        return model_name

    own = construction.casefold()
    cleaned = model_name
    for known in KNOWN_CONSTRUCTIONS:
        if known.casefold() == own:
            continue
        cleaned = re.sub(rf"\b{re.escape(known)}\b", " ", cleaned, flags=re.IGNORECASE)

    cleaned = " ".join(cleaned.split())
    if cleaned != model_name:
        logger.info(
            "Model name %r contradicted construction %r; corrected to %r",
            model_name, construction, cleaned or None,
        )
    return cleaned or None


def _keep_on_null(incoming: str | None, current: str | None) -> str | None:
    """A non-answer from Claude leaves what's already there alone.

    `brand`, `model_name` and `artist_series` are all hand-editable on the Edit
    Hat form, and the tool schema tells Claude to return null rather than guess
    — most emphatically for `artist_series` ("guessing here is worse than
    leaving it empty"). Passing that null straight through would erase what the
    owner typed every time they tapped Reanalyze, which is precisely the
    special-edition case they typed it in for. A real answer still wins, so
    Claude can still correct an earlier identification.

    `logo_detected` deliberately does NOT go through here: it records what is
    visible in *this* photo, so null there is an answer, not a gap.
    """
    return incoming if incoming else current


async def _known_series(db) -> list[str]:
    """Series/collab names the collection already uses, for the prompt.

    A series is rarely legible in a photo — often it's a woven label or an
    embroidery style — so an analyser recalling them unaided misses most of
    them. Sending the ones already on record turns recall into recognition.
    """
    from headroom.services import vocabulary

    return await vocabulary.distinct_values(db, Hat.artist_series)


async def _canonicalize_analysis_text(db, hat: Hat) -> None:
    """Snap analysis-written free text to the spelling already on record.

    `hat_service` canonicalises on the client write path, but the ANALYSIS path
    wrote straight through — so Claude returning "skye walker" created a second
    entry beside the owner's "Skye Walker". Nothing looks wrong afterwards:
    both hats have *a* series, and the split only shows up as two near-identical
    rows in the autocomplete, the Stats collab chart and the filters. That is
    exactly the fragmentation `vocabulary` exists to prevent, and it was
    prevented on one of the two paths that write these fields.

    Run AFTER `_apply_analysis`, so it also covers a construction Claude filled
    in on a hat that had none.
    """
    from headroom.schemas.hat import KNOWN_CONSTRUCTIONS
    from headroom.services import vocabulary

    if hat.artist_series:
        hat.artist_series = await vocabulary.canonicalize(
            db, Hat.artist_series, hat.artist_series
        )
    if hat.construction:
        canonical = await vocabulary.canonicalize(
            db, Hat.construction, hat.construction, known=KNOWN_CONSTRUCTIONS
        )
        # Through the setter: `construction` owns the hydro/hydrolite flags,
        # and assigning the column directly is what lets them drift.
        if canonical != hat.construction:
            hat.set_construction(canonical)


def _apply_analysis(hat: Hat, analysis: HatAnalysis) -> None:
    hat.brand = _keep_on_null(analysis.brand, hat.brand)
    hat.logo_detected = analysis.logo_detected
    hat.artist_series = _keep_on_null(analysis.artist_series, hat.artist_series)
    _apply_construction(hat, analysis.construction)
    hat.model_name = _strip_contradicting_construction(
        _keep_on_null(analysis.model_name, hat.model_name), hat.construction
    )
    hat.model_confidence = analysis.model_confidence
    hat.style_descriptor = analysis.style_descriptor
    hat.design_notes = analysis.design_notes
    # Looked up, not guessed. A photo cannot show a price, so asking Claude for
    # one made the prompt's anchors the real answer — and they were years stale.
    # `resolve_retail` also refuses to overwrite a price a person entered, the
    # same protection `resale_price_scope == "manual"` already has.
    hat.estimated_new_price, hat.estimated_new_price_source = retail_pricing.resolve_retail(
        hat.style,
        hat.construction,
        estimate=analysis.estimated_new_price_usd,
        current=hat.estimated_new_price,
        current_source=hat.estimated_new_price_source,
    )
    hat.analysis_status = "ok"
    hat.analysis_error = None
    hat.analyzed_at = datetime.now(timezone.utc)

    # Replace colors. color_name keeps Claude's phrasing ("heather slate");
    # general_color snaps to the curated palette via the hex so the color
    # filter chips match consistently regardless of naming whims.
    hat.colors.clear()
    for rank, color in enumerate(analysis.colors, start=1):
        hat.colors.append(
            HatColor(
                color_name=color.name,
                general_color=normalize_hex_name(color.hex, color.name),
                hex_value=color.hex,
                dominance_rank=rank,
                tier=color.tier,
            )
        )

    # Resale pointer (Melin only, by current rules)
    _apply_resale_pointer(hat)
