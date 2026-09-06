"""End-to-end pipeline for analyzing a freshly-uploaded hat photo.

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
import time
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from headroom.config import settings
from headroom.models.hat import Hat, ResaleScope
from headroom.models.hat_color import HatColor
from headroom.schemas.hat import KNOWN_CONSTRUCTIONS, strip_constructions
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
from headroom.utils.photo import (
    THUMBS_DIR,
    export_derivative_path,
    make_export_image_async,
    make_thumbnail_async,
)
from headroom.services import vocabulary
from headroom.services import catalog_service
from sqlalchemy import select
from headroom.services import activity_service

logger = logging.getLogger(__name__)


# The steps a person can be told about, in the order they run. Kept as constants
# so the UI's labels and the writer can't drift apart.
STAGE_CUTOUT = "cutout"
STAGE_IDENTIFYING = "identifying"
STAGE_PRICING = "pricing"
STAGE_RESALE = "resale"


async def _publish_stage(db: AsyncSession, hat_id: int | None, stage: str | None) -> None:
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

    The sibling session is opened on the CALLER'S engine (`db.bind`), not the
    module-level `async_session`. That was the seam mistake `error_handler`
    documents, one layer down: in production the two are the same engine, but
    under test the module engine is deliberately unopenable, so every stage
    publish raised, was swallowed at DEBUG, and no test ever observed a stage
    being written — the writer of `analysis_stage` was covered and unconstrained.

    Best-effort: progress reporting must never be the thing that fails an
    analysis — but a failure is logged at WARNING, because a stage that never
    updates is the symptom an owner sees, and DEBUG is where symptoms hide.
    """
    if hat_id is None:
        return
    try:
        sibling = async_sessionmaker(bind=db.bind, expire_on_commit=False)
        async with sibling() as side:
            await side.execute(
                update(Hat)
                .where(Hat.id == hat_id)
                # Stamped by the SAME update that sets the stage, so the
                # two can never disagree about when this step began.
                .values(analysis_stage=stage, analysis_stage_at=datetime.now(timezone.utc))
            )
            await side.commit()
    except Exception as exc:  # noqa: BLE001 — cosmetic; never fail a run for it
        logger.warning("Could not publish analysis stage for hat=%s: %s", hat_id, exc)


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
    # Skipped when the input IS already a cutout. Uploads are normalized to JPEG
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
        await _publish_stage(db, hat.id, STAGE_CUTOUT)
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

    # Export derivative, generated HERE rather than lazily at export time.
    #
    # It used to be built on demand, once per hat, inside the export request —
    # on the event loop. A first export of a few hundred hats was therefore
    # several hundred full-resolution decodes and slow WebP encodes with the
    # app answering nothing throughout, and a peak allocation that a 1 GB
    # container running rembg cannot comfortably absorb. The download appeared
    # to do nothing, which is exactly what it looked like from outside.
    #
    # One hat's worth of work belongs where one hat is being processed. This
    # runs in the analysis worker, so it costs the upload nothing, and the
    # export becomes a zip of files that already exist.
    #
    # Not stored on the Hat: `export_derivative_path` derives it from the
    # canonical photo's own name, and a column would be a second source of
    # truth for a file that is regenerable and cache-like.
    await make_export_image_async(
        canonical_path, export_derivative_path(settings.upload_dir, hat.photo_path)
    )

    # Everything below interleaves DB reads (API key, model, eBay creds) with
    # slow network calls. With autoflush on, the FIRST of those reads flushes
    # the `photo_path` write above — which opens a SQLite write transaction, and
    # SQLite holds that lock until commit. The lock would therefore stay held
    # across the entire Claude + eBay + Melin sequence: minutes, worst case.
    # Every other writer in the process then waits out `busy_timeout` and fails
    # with "database is locked" — so adding a second hat while the first is
    # analyzing would error out. Deferring the flush shrinks the lock window to
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

        await _publish_stage(db, hat.id, STAGE_IDENTIFYING)
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
                "Hat analysis failed for hat=%s (rembg=%.2fs claude=%.2fs): %s",
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

        leaked = _apply_analysis(hat, analysis)
        await _canonicalize_analysis_text(db, hat)
        await _apply_analyzed_colorway(db, hat, analysis, leaked)
        await _publish_stage(db, hat.id, STAGE_PRICING)
        t_ebay0 = time.monotonic()
        await _refresh_ebay_comps(db, hat)
        await _publish_stage(db, hat.id, STAGE_RESALE)
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
            logger.info("eBay comp refresh skipped for hat=%s: %s", hat.id, exc)


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
        await _publish_stage(db, hat.id, STAGE_IDENTIFYING)
        try:
            analysis = await analyze_hat_image(
                photo_path, api_key, model=model_id, selected_style=hat.style,
                selected_construction=hat.construction,
                known_series=await _known_series(db),
            )
        except ClaudeAnalysisError as exc:
            logger.warning("Reanalysis failed for hat=%s: %s", hat.id, exc)
            hat.analysis_status = "error"
            hat.analysis_error = str(exc)
            hat.analyzed_at = datetime.now(timezone.utc)
            await run_fallback_analysis(
                db, hat, photo_path, reason=f"Claude analysis failed: {exc}"
            )
            return True

        leaked = _apply_analysis(hat, analysis)
        await _canonicalize_analysis_text(db, hat)
        await _apply_analyzed_colorway(db, hat, analysis, leaked)
        await _publish_stage(db, hat.id, STAGE_PRICING)
        await _refresh_ebay_comps(db, hat)
        await _publish_stage(db, hat.id, STAGE_RESALE)
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
        # `colorway` is what turns a line into a product: melin names its
        # goods `<Model> - <Colorway>`, so the two columns together identify
        # the exact item on the marketplace instead of the family it is in.
        stats = await fetch_resale_stats(
            hat.style, hat.model_name, condition=hat.condition, size=hat.size,
            colorway=hat.colorway, construction=hat.construction,
        )
    except MelinRecapError as exc:
        logger.info("Melin Recap stats skipped for hat=%s: %s", hat.id, exc)
        return
    if not stats:
        return
    # A person's own number outranks a scraped median, and a re-analysis must
    # not quietly overwrite it -- reanalyze runs on a schedule and on demand,
    # so anything it clobbers is gone without a prompt.
    if hat.resale_price_scope == ResaleScope.MANUAL:
        return
    hat.resale_price = stats["median"]
    scope = ResaleScope.MODEL if stats["sample"] == "model" else ResaleScope.CATEGORY
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
    # Name the LINE that was compared against, not just the word "model" — the
    # match is now a prefix of the hat's name, so "model listings" alone would
    # hide that an `Odysea Rope Hydro (WATERCOLOR)` was priced against every
    # `Odysea Rope Hydro`. Which is a fair comp, and worth being able to see.
    what = stats.get("matched") or scope
    hat.resale_price_source = (
        f"Melin Recap · median of {stats['count']} live "
        f"{qualifiers + ' ' if qualifiers else ''}{what} listings"
    )
    hat.resale_checked_at = datetime.now(timezone.utc)


#: Reasons that genuinely mean "there is no key to call with". Anything else
#: — a billing failure, a network error, a model rejecting the request — means
#: the key exists and something else went wrong.
_MISSING_KEY_MARKERS = ("not configured", "no api key", "no anthropic key")


def fallback_message(reason: str, provided: list[str]) -> str:
    """The `analysis_error` text for a hat that fell back to basic ID.

    A pure function so the ADVICE can be tested without a photo, a cutout or a
    database — which is why the rule was wrong for as long as it was.

    The advice has to match the reason. It used to append "Add a Claude API
    key" unconditionally, so when the Anthropic ACCOUNT RAN OUT OF CREDIT —
    key present, valid, working minutes earlier — every hat told its owner to
    add the key they already had. A 235-hat collection sat like that for three
    days, because the banner was the only thing on screen and the true reason
    lived in a field the fallback branch never rendered.
    """
    if any(m in reason.lower() for m in _MISSING_KEY_MARKERS):
        advice = "Add a Claude API key in Settings and Reanalyze for full identification."
    else:
        advice = "Reanalyze once the cause above is resolved for full identification."
    return f"{reason} — basic fallback applied ({', '.join(provided)}). {advice}"


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
            logger.warning("Fallback color extraction failed for hat=%s: %s", hat.id, exc)

    brand: str | None = None
    google_key, _gsrc = await settings_service.get_google_vision_key(db)
    if google_key:
        try:
            logo = await detect_brand_logo(photo_path, google_key)
            if logo:
                brand = logo[0]
        except GoogleVisionError as exc:
            logger.info("Fallback logo detection skipped for hat=%s: %s", hat.id, exc)

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
    hat.analysis_error = fallback_message(reason, provided)
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
    if hat.resale_price_scope == ResaleScope.MANUAL:
        return
    hat.resale_price = pointer["resale_price"]
    hat.resale_price_source = pointer["resale_price_source"]
    hat.resale_price_scope = None
    hat.resale_checked_at = datetime.now(timezone.utc)


# Words that mean "no construction identified" rather than naming one.
_NON_ANSWERS = frozenset({"standard", "none", "n/a", "na", "unknown", "regular"})


def _apply_construction(hat: Hat, construction: str | None) -> None:
    """Never write a construction from analysis. Construction is owner-only.

    This used to fill the field whenever it was empty, on the reasoning that a
    blank is not an answer worth protecting. That was wrong, and the function's
    own previous docstring said why without following it through: Claude reads
    HYDRO and HYDROLite off a photo **unreliably** — the distinguishing
    features are bonded seams, a gel-welded logo and a sweatband, none of which
    survive a single front-on shot. It was already established that letting it
    *correct* a stated value replaced right answers with wrong ones. Letting it
    fill a blank is the same coin toss; the only difference is that there was
    no prior value to notice being lost.

    Two things since made a wrong guess expensive rather than cosmetic:

    * **It moves money.** `retail_pricing` prices HYDRO at $79 and HYDROLite at
      $99, so a guess that skews HYDROLite over-prices the hat by $20 and the
      collection by that times however many.
    * **It hides hats.** Construction became a filter, so a mislabeled hat is
      absent from the filtered view rather than merely wrong in a detail pane.

    An empty construction is an honest "nobody has looked yet". A guessed one
    is indistinguishable from a fact the owner entered, and there is no column
    recording which it was. So: blank stays blank until a person fills it in.

    Kept as a function rather than deleting the call, so the one place this
    decision lives is greppable and the reasoning travels with it.
    """
    return


def _strip_contradicting_construction(
    model_name: str | None, construction: str | None
) -> str | None:
    """Drop a construction from the model name that the hat isn't.

    melin names read "<line> <construction>" — "A-Game Hydro", "Coronado
    HYDROLite" — so a model name can assert a build all by itself. A hat the
    owner recorded as Thermal, analyzed before that value was sent to Claude,
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

    **With no construction stated, every construction is stripped.** melin
    names read "<line> <construction>", so leaving Claude's name intact would
    park its guess in `model_name` — the field a person actually reads — and
    this function's early return meant a blank construction protected nothing.
    Analysis no longer decides construction (see `_apply_construction`); a name
    asserting one is that same decision wearing a different column, and it is
    the one that gets quoted to somebody.

    Same principle as above: remove, don't substitute. "A-Game" is less
    specific than "A-Game HYDROLite" and, unlike it, known to be true. State
    the construction and re-analyze and the full name comes back.
    """
    if not model_name:
        return model_name

    if not construction:
        # Nothing confirmed, so nothing may be claimed.
        cleaned = strip_constructions(model_name)
        if cleaned != model_name:
            logger.info(
                "Model name %r asserted a construction nobody stated; corrected to %r",
                model_name, cleaned,
            )
        return cleaned

    cleaned = strip_constructions(model_name, keep=construction) or ""
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
    embroidery style — so an analyzer recalling them unaided misses most of
    them. Sending the ones already on record turns recall into recognition.
    """

    return await vocabulary.distinct_values(db, Hat.artist_series)


async def _apply_analyzed_colorway(
    db, hat: Hat, analysis: HatAnalysis, leaked: str | None = None
) -> None:
    """Fill a blank colorway from the analyzer, but only if it names a REAL product.

    Claude gained a `colorway` field in 2.74. Before it, the tool schema had no
    home for one, so a colorway read off the hat was appended to `model_name`
    — and `model_name` tokens are the gate for both purchase matching and
    product pricing. Measured on the real collection: 89 of 235 model names
    matched no melin product, the foreign tokens being colorway words like
    "camo", "808", "watercolor".

    Two guards, and both matter:

    * **Never overwrite.** A colorway already on the hat came from a matched
      receipt or from the owner, and both outrank a photo.
    * **Validate, do not trust.** `catalog_service.is_real_product` checks the
      pair against the harvested catalog, so a colorway that survives names a
      good melin actually sells. A wrong one would price this hat as somebody
      else's product, which is strictly worse than the blank it replaced —
      the same reasoning that keeps color-inferred colorways out entirely.
    """


    # `leaked` is the colorway half of a model name Claude wrote the old way,
    # split out by `_apply_analysis`. Claude's own field wins when it has one.
    candidate = analysis.colorway or leaked
    if hat.colorway or not candidate:
        return
    if await catalog_service.is_real_product(db, hat.model_name, candidate):
        # Snapped to the spelling already on record, like every other
        # analysis-written free-text field — see `_canonicalize_analysis_text`,
        # which does the same for artist_series and construction.
        hat.colorway = await vocabulary.canonicalize(db, Hat.colorway, candidate)


def _split_model_and_colorway(model_name: str | None) -> tuple[str | None, str | None]:
    """Split "Trenches Hydro — Hawaii 808" into its two halves.

    Defensive, and it repairs the shape at the source. The tool schema now
    forbids a separator in `model_name`, but 35 of 235 stored names carried
    one, and a model that agrees with no real product is the single most
    expensive thing this pipeline can write — every downstream gate is token
    containment on it.

    Only splits on an explicit separator. A name like "Trenches Icon Camo"
    carries a colorway word with nothing marking it, and guessing where the
    model ends is how a correct name gets truncated.
    """
    if not model_name:
        return model_name, None
    for sep in (" — ", " – ", " - "):
        if sep in model_name:
            model, _, colorway = model_name.partition(sep)
            return model.strip() or None, colorway.strip() or None
    if "(" in model_name and model_name.rstrip().endswith(")"):
        model, _, rest = model_name.partition("(")
        return model.strip() or None, rest.rstrip().rstrip(")").strip() or None
    return model_name, None


async def _canonicalize_analysis_text(db, hat: Hat) -> None:
    """Snap analysis-written free text to the spelling already on record.

    `hat_service` canonicalizes on the client write path, but the ANALYSIS path
    wrote straight through — so Claude returning "skye walker" created a second
    entry beside the owner's "Skye Walker". Nothing looks wrong afterwards:
    both hats have *a* series, and the split only shows up as two near-identical
    rows in the autocomplete, the Stats collab chart and the filters. That is
    exactly the fragmentation `vocabulary` exists to prevent, and it was
    prevented on one of the two paths that write these fields.

    Run AFTER `_apply_analysis`. Construction is NOT among the fields it can
    touch in practice — analysis never writes one (`_apply_construction` is a
    documented no-op) — so the `set_construction` branch below is reached only
    if a stored value needs its spelling snapped; `artist_series` and
    `colorway` are the fields this exists for.
    """

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


def _apply_analysis(hat: Hat, analysis: HatAnalysis) -> str | None:
    hat.brand = _keep_on_null(analysis.brand, hat.brand)
    hat.logo_detected = analysis.logo_detected
    hat.artist_series = _keep_on_null(analysis.artist_series, hat.artist_series)
    _apply_construction(hat, analysis.construction)
    model_name, leaked = _split_model_and_colorway(analysis.model_name)
    hat.model_name = _strip_contradicting_construction(
        _keep_on_null(model_name, hat.model_name), hat.construction
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

    # RETURNED rather than written back onto `analysis`. Mutating the argument
    # and having a different function read it two lines later at the call site
    # is a dependency nothing in either signature admits to — and this one is
    # temporal: swap the two calls and the colorway silently vanishes.
    return leaked


async def backfill_split_model_names(db) -> int:
    """Split a leaked colorway out of every stored `model_name`. Returns how many changed.

    Fixing the tool schema alone would leave a collection where a hat's model
    name depends on *when* it was analyzed — the same reason
    `retail_pricing.backfill_retail_prices` exists, and the same one-time
    lifespan flag.

    Measured on the real collection before this ran: 89 of 235 model names
    matched no melin product, and 35 carried a literal separator. Splitting on
    that separator alone takes usable names from **146 to 174 of 235**, without
    an API call — every one of those hats becomes matchable against its receipt
    and priceable against its own product.

    Only the MODEL half is written to `model_name`. The colorway half is not
    stored on the hat: `_apply_analyzed_colorway` gates on the harvested
    catalog, and measured against it **none** of the leaked halves validate —
    they are collab and limited-run drops ("Hawaii 808 Camo", "Maui Strong")
    that no longer appear on the resale market. Writing them anyway would be
    trusting a string precisely where there is no evidence for it, which is how
    a hat gets priced as somebody else's product.

    **Every change is written to the activity log with the ORIGINAL name, in the
    SAME transaction as the change**, and that is not decoration. This is the
    one repair in this app that destroys information rather than recomputing it:
    `retail_prices_v2` re-derives a price that can be re-derived again, but
    "Trenches (Curl Surf)" → "Trenches" discards the only record that the drop
    was a Curl Surf. It runs once, unattended, behind a flag, with no dry run,
    so the log is the undo — and it commits with the mutation rather than after
    it, because a window where the damage is durable and the record is not
    inverts the whole reason for keeping one.

    **The undo is time-bounded, and that is worth saying rather than implying
    otherwise.** `activity_service` prunes daily at
    `HEADROOM_ACTIVITY_LOG_RETENTION_DAYS` (default 90), so these rows age out
    like any others. The window is generous relative to the repair — it runs at
    the first boot after upgrading and the names are visible immediately — but
    "the log IS the undo" is only true for ninety days, and a backup taken
    before the upgrade is the durable copy.
    """


    hats = (
        await db.execute(select(Hat).where(Hat.model_name.is_not(None)))
    ).scalars().all()

    repaired: list[dict] = []
    for hat in hats:
        model, dropped = _split_model_and_colorway(hat.model_name)
        if dropped and model and model != hat.model_name:
            # `dropped`, not `colorway_dropped`. The suffix is usually a leaked
            # colorway, which is what this repair is for — but the splitter also
            # takes parentheses, and those hold sizes and pack counts as often
            # as artwork: "(Small)", "(S/M)", "(Classic)", "(2-Pack)". Removing
            # them from `model_name` is right either way (a size in the name
            # breaks token containment against the receipt), but recording a
            # size under a field called `colorway` states a classification
            # nothing here has made. Only `_apply_analyzed_colorway`'s catalog
            # check decides whether a string is a colorway, and it runs later.
            repaired.append({"hat_id": hat.id, "was": hat.model_name, "now": model,
                             "dropped": dropped})
            hat.model_name = model
    if repaired:
        # ONE commit, with the record inside it. This used to commit the
        # truncated names first and write the log row afterwards, so a crash
        # between the two — or a failure in the second commit — destroyed the
        # only copy of the original names with nothing recording what they were.
        # The record is this repair's undo; a window where the damage is durable
        # and the undo is not inverts the entire point of keeping one.
        # `log_activity` adds to the caller's transaction and never raises, so
        # this is atomic: either both land or neither does.
        await activity_service.log_activity(
            db, kind="hat.model_name_split", entity_type="system", entity_id=None,
            summary=f"Split a trailing colorway out of {len(repaired)} model name(s)",
            details={"repaired": repaired},
        )
        await db.commit()
    return len(repaired)
