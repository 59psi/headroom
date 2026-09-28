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
from pathlib import Path, PurePosixPath

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from headroom.config import settings
from headroom.models.hat import Hat, ResaleScope
from headroom.schemas.hat import KNOWN_CONSTRUCTIONS, AnalysisStatus, strip_constructions

# Every collaborator is imported as a MODULE and called through it at run time
# (`claude_analysis.analyze_hat_image(...)`). Those calls are the seams the
# tests patch, and a `from … import` of the function froze this module's own
# copy: a test had to patch the pipeline's name AND the owner's, and
# `conftest` stubbed rembg in both places for exactly that reason.
from headroom.services import (
    activity_service,
    background_removal,
    catalog_service,
    claude_analysis,
    color_extraction,
    ebay_service,
    google_vision,
    hat_service,
    melin_recap,
    naming,
    retail_pricing,
    settings_service,
    vocabulary,
)
from headroom.utils.photo import (
    THUMBS_DIR,
    export_derivative_path,
    make_export_image_async,
    make_thumbnail_async,
)

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
    *,
    cutout_only: bool = False,
) -> Hat:
    """Apply background removal + Claude analysis to a freshly-saved JPEG.

    The transparent PNG (if produced) replaces the JPEG as the canonical photo.
    Mutates `hat` in place. Caller is responsible for the final commit.

    `cutout_only` stops after the cutout and its derivatives: the photo is
    re-cut, the thumbnail and export image regenerated, and NOTHING the
    analyzer wrote is touched. "Redo cutout" ran the whole pipeline until
    2.79 — a Claude call per press, and the owner's own `model_name` and
    `design_notes` overwritten by the analyzer's — while the docs said it
    spent no call.

    A re-cut's stage is cleared in a `finally`, whatever happens. `HatRead`
    reports the stage for as long as the photo is the uncut original, so a
    cut that raised used to leave `analysis_stage='cutout'` behind and the
    page polling a "Cutting out…" that nothing was doing. A re-cut that
    produced no cutout goes back to the one it had (`abandon_recut`) instead
    of promoting the original JPEG, background and all, to the hat's photo
    and overwriting the old cutout's thumbnail with it.
    """
    if not cutout_only:
        canonical_path, t_rembg = await _cut_and_derive(db, hat, processed_jpeg_path)
        await _analyze(db, hat, canonical_path, t_rembg=t_rembg)
        return hat
    try:
        cut = await _cut_and_derive(db, hat, processed_jpeg_path, recut=True)
    finally:
        await _publish_stage(db, hat.id, None)
    if cut is None:
        abandon_recut(hat)
        logger.warning(
            "hat=%s re-cut produced no cutout; kept the one it had", hat.id
        )
        return hat
    logger.info("hat=%s re-cut · rembg=%.2fs (analysis untouched)", hat.id, cut[1])
    return hat


def _recut_target(original_rel: str) -> str:
    """Where a cut of the retained original lands: `hats/<stem>.png`.

    `finalize_hat_photo` cuts to `<dir>/<stem>` and `background_removal`
    appends `.png`, so the cutout always sits beside its original under the
    same stem — which is what lets a failed re-cut find the previous one.
    """
    return str(PurePosixPath(original_rel).with_suffix(".png"))


def abandon_recut(hat: Hat) -> bool:
    """Put a hat whose re-cut did not finish back on the cutout it had.

    A re-cut points `photo_path` at the retained original and commits that
    before the cut starts (the route does, so the page can show it running),
    so every way it can fail — rembg producing nothing, a derivative raising,
    the worker crashing — used to leave the uncut JPEG as the hat's photo
    and the stage reading "cutout" forever. `photo_path == original_path` is
    the re-cut-in-progress state `HatRead` keys on, and only that state is
    touched: the photo goes back to the cutout beside the original when it
    is still on disk (a cut that wrote it and then failed on a thumbnail
    leaves the NEW one there, which is just as good), and the stage clears.
    The analysis record is left alone, as a re-cut always leaves it.

    Returns True when the hat was mid-re-cut. Mutates `hat`; caller commits.
    """
    if not hat.original_path or hat.photo_path != hat.original_path:
        return False
    previous = _recut_target(hat.original_path)
    if (settings.upload_dir / previous).is_file():
        hat.photo_path = previous
    hat.analysis_stage = None
    hat.analysis_stage_at = None
    return True


async def abandon_interrupted_recuts(db: AsyncSession) -> int:
    """At boot, put every hat a restart caught mid-re-cut back on its cutout.

    Nothing runs before boot, so a hat still in the re-cut-in-progress state
    `HatRead` keys on (stage `cutout`, `photo_path == original_path`) is one
    whose cut died with the process — the queue that held it is in memory, and
    an inline cut dies with its request. Nothing else would ever finish or
    undo it: the boot sweep re-queues only `pending` hats, and a re-cut never
    sets that. `HatRead` reports the state as a cut in progress, so such a hat
    showed its uncut original under a spinner, and the page polled it every
    two seconds, forever. Pending hats are left to that boot sweep, which runs
    them in full. Every boot, whichever way analysis runs. Returns the count.
    """
    stranded = (
        await db.execute(
            select(Hat).where(
                Hat.analysis_stage == STAGE_CUTOUT,
                Hat.original_path.is_not(None),
                Hat.photo_path == Hat.original_path,
                or_(
                    Hat.analysis_status.is_(None),
                    Hat.analysis_status != AnalysisStatus.pending.value,
                ),
            )
        )
    ).scalars().all()
    restored = sum(1 for hat in stranded if abandon_recut(hat))
    if restored:
        await db.commit()
    return restored


async def _cut_and_derive(
    db: AsyncSession, hat: Hat, processed_jpeg_path: Path, *, recut: bool = False
) -> tuple[Path, float] | None:
    """Cutout, then the canonical photo's derivatives. `(canonical, rembg seconds)`.

    None only for a `recut` that produced no cutout: an upload whose rembg
    fails keeps its JPEG as the photo (the documented degrade), but a re-cut
    already HAS a cutout, and the JPEG must not replace it.
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
        transparent_path = await background_removal.remove_background(
            processed_jpeg_path, cutout_target
        )
        t_rembg = time.monotonic() - t_rembg0
        if recut and (transparent_path is None or not transparent_path.exists()):
            return None
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
    return canonical_path, t_rembg


async def reanalyze_existing_photo(
    db: AsyncSession, hat: Hat, photo_path: Path
) -> bool:
    """Re-run analysis against an already-processed cutout — no bg removal.

    Mutates `hat`; caller commits. Returns False only when there is no Claude
    key AND the fallback produced nothing (caller → HTTP 400). The analysis
    itself is `_analyze`, the same code `finalize_hat_photo` runs.
    """
    return await _analyze(db, hat, photo_path, t_rembg=0.0)


#: The reason recorded when there is no Claude key to call with. One constant,
#: because `fallback_message` used to recognize this case by searching the
#: reason for marker substrings — and the pipeline's own wording contained
#: none of them, so a keyless install was never once told to add a key.
NO_ANTHROPIC_KEY = "No Anthropic API key configured"


async def _analyze(db: AsyncSession, hat: Hat, photo_path: Path, *, t_rembg: float) -> bool:
    """Key check → Claude → apply → eBay → resale, with the fallback. Mutates `hat`.

    The one copy of the analysis sequence. `finalize_hat_photo` and
    `reanalyze_existing_photo` each carried their own, and a docstring claimed
    they shared one while the two drifted: the re-analysis copy stamped
    nothing on its no-key path and logged no timing line. The entry points
    now differ only in what they do BEFORE this — the cutout — and in what
    they return.

    Returns False only when there is no Claude key AND the fallback produced
    nothing; True whenever the hat now carries a result, including an `error`
    status (that is a result the owner can see and act on).
    """
    # Everything below interleaves DB reads (API key, model, eBay creds, the
    # Vision key) with slow network calls. With autoflush on, the FIRST of
    # those reads flushes the pending hat writes — `photo_path` on the upload
    # path, `_apply_analysis`'s fields on either — which opens a SQLite write
    # transaction that SQLite holds until commit. The lock would therefore
    # stay held across the entire Claude + eBay + Melin sequence: minutes,
    # worst case. Every other writer in the process then waits out
    # `busy_timeout` and fails with "database is locked" — adding a second hat
    # while the first analyzes, or tapping "wearing this today" during a
    # re-analysis, would error out. Deferring the flush shrinks the lock
    # window to the caller's commit. Safe because nothing in here re-queries
    # the hat row; the pending change only has to be visible at commit time.
    with db.no_autoflush:
        api_key, _source = await settings_service.get_anthropic_key(db)
        if not api_key:
            hat.analysis_status = "skipped"
            hat.analysis_error = f"{NO_ANTHROPIC_KEY}."
            hat.analyzed_at = datetime.now(timezone.utc)
            applied = await run_fallback_analysis(
                db, hat, photo_path, reason=NO_ANTHROPIC_KEY, missing_key=True
            )
            # The timing line, on this path too. A 24 s rembg run (minutes on
            # a Pi) used to leave no log line at all when no key was set —
            # the per-hat stage timing line appeared only when Claude ran.
            logger.info(
                "hat=%s analyzed · rembg=%.2fs claude=skipped (no key) status=%s",
                hat.id, t_rembg, hat.analysis_status,
            )
            return applied

        model_id, _model_source = await settings_service.get_anthropic_model(db)

        await _publish_stage(db, hat.id, STAGE_IDENTIFYING)
        t_claude0 = time.monotonic()
        try:
            analysis: claude_analysis.HatAnalysis = await claude_analysis.analyze_hat_image(
                photo_path, api_key,
                model=model_id, selected_style=hat.style,
                selected_construction=hat.construction,
                known_series=await _known_series(db),
            )
        except claude_analysis.ClaudeAnalysisError as exc:
            logger.warning(
                "Hat analysis failed for hat=%s (rembg=%.2fs claude=%.2fs): %s",
                hat.id, t_rembg, time.monotonic() - t_claude0, exc,
            )
            hat.analysis_status = "error"
            hat.analysis_error = str(exc)
            hat.analyzed_at = datetime.now(timezone.utc)
            await run_fallback_analysis(
                db, hat, photo_path, reason=f"Claude analysis failed: {exc}"
            )
            return True
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
    return True


async def _refresh_ebay_comps(db: AsyncSession, hat: Hat) -> None:
    """Best-effort eBay comparable-listings refresh — never fails the caller.

    Gated on brand AND model: without a model the search falls back to the
    style ("Melin a game hat"), which prices the whole line, not this hat.
    `find_comps` raises nothing but `EbayError`, so catching that one type is
    the whole degrade path.

    Written through `hat_service.apply_ebay_comps`, the one writer of those
    columns — the admin refresh already used it, and this path had its own
    `setattr` over whatever keys the service returned.
    """
    if hat.brand and hat.model_name:
        try:
            comps = await ebay_service.find_comps(
                db, brand=hat.brand, model=hat.model_name, style=hat.style
            )
            hat_service.apply_ebay_comps(hat, comps)
        except ebay_service.EbayError as exc:
            logger.info("eBay comp refresh skipped for hat=%s: %s", hat.id, exc)


# For the resale source label. The stored values are snake_case enum names;
# these read as English in the middle of a sentence.
_CONDITION_WORDS: dict[str, str] = {
    "new_with_tags": "new-with-tags",
    "new": "new-without-tags",
    "worn": "worn",
}


#: What `refresh_melin_resale` did. A sweep needs to tell "the marketplace
#: answered and had nothing" from "the marketplace could not be reached":
#: the first is a fact about the hat, the second a fact about the network,
#: and a nightly sweep in which EVERY lookup was the second used to record
#: itself as a success — `last_error` null, "0 of 234 hats changed price".
RESALE_PRICED = "priced"
RESALE_SKIPPED = "skipped"
RESALE_UNREACHABLE = "unreachable"


async def refresh_melin_resale(hat: Hat) -> str:
    """Fill resale_price with a live Melin Recap median. Best-effort.

    Runs for Melin hats only; leaves the deep-link pointer fields alone and
    the price null when the marketplace API is unreachable (the pre-live
    behavior). Returns one of `RESALE_PRICED`, `RESALE_SKIPPED` (not a melin
    hat, a manual price, or no listings) or `RESALE_UNREACHABLE`.
    """
    if not melin_recap.is_melin(hat.brand):
        return RESALE_SKIPPED
    # A person's own number outranks a scraped median, and a re-analysis must
    # not quietly overwrite it -- reanalyze runs on a schedule and on demand,
    # so anything it clobbers is gone without a prompt.
    #
    # Checked BEFORE the fetch. It used to sit after it, so every hand-priced
    # Melin hat still walked its whole category on the marketplace (five page
    # requests, measured) for a number that was then thrown away -- against
    # somebody else's public API, on a path `repricing` promises costs a
    # protected hat no API call at all.
    if hat.resale_price_scope == ResaleScope.MANUAL:
        return RESALE_SKIPPED
    try:
        # Condition and size are the hat's own, so the median comes back from
        # listings of the same thing in the same shape rather than from the
        # whole category averaged together and adjusted by a guess.
        # `colorway` is what turns a line into a product: melin names its
        # goods `<Model> - <Colorway>`, so the two columns together identify
        # the exact item on the marketplace instead of the family it is in.
        stats = await melin_recap.fetch_resale_stats(
            hat.style, hat.model_name, condition=hat.condition, size=hat.size,
            colorway=hat.colorway, construction=hat.construction,
        )
    except melin_recap.MelinRecapError as exc:
        logger.info("Melin Recap stats skipped for hat=%s: %s", hat.id, exc)
        return RESALE_UNREACHABLE
    if not stats:
        return RESALE_SKIPPED
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
    return RESALE_PRICED


def fallback_message(reason: str, provided: list[str], *, missing_key: bool = False) -> str:
    """The `analysis_error` text for a hat that fell back to basic ID.

    A pure function so the ADVICE can be tested without a photo, a cutout or a
    database — which is why the rule was wrong for as long as it was.

    The advice has to match the reason. It used to append "Add a Claude API
    key" unconditionally, so when the Anthropic ACCOUNT RAN OUT OF CREDIT —
    key present, valid, working minutes earlier — every hat told its owner to
    add the key they already had. A 235-hat collection sat like that for three
    days, because the banner was the only thing on screen and the true reason
    lived in a field the fallback branch never rendered.

    The fix for that then went wrong the other way: it recognized "no key" by
    searching the reason for marker substrings, and the pipeline's own reason
    (`NO_ANTHROPIC_KEY`) contained none of them, so the add-a-key advice
    never appeared at all. `missing_key` is now stated by the one caller that
    knows it — the branch that found no key — rather than inferred from
    prose. Defaulted to False because that is the harmless direction: telling
    an owner to resolve a stated cause is never wrong, telling them to add a
    key they have is the incident above.
    """
    if missing_key:
        advice = "Add a Claude API key in Settings and Reanalyze for full identification."
    else:
        advice = "Reanalyze once the cause above is resolved for full identification."
    return f"{reason} — basic fallback applied ({', '.join(provided)}). {advice}"


async def run_fallback_analysis(
    db: AsyncSession, hat: Hat, photo_path: Path, *, reason: str, missing_key: bool = False
) -> bool:
    """Best-effort analysis without Claude: mask colors + Google logo brand.

    Colors come only from the rembg cutout's alpha mask (background rejected
    by construction); a PNG suffix is the marker that a cutout exists. Brand
    comes from Google Vision logo detection when that key is configured.

    **Colors and a brand, nothing else** — the fallback design's scope. No
    model name, no design notes and NO PRICE: a Melin brand gets the resale
    deep link (`_apply_resale_link`), never a marketplace median. It used to
    call `refresh_melin_resale` here, so a hat identified by nothing but its
    logo was priced at the median of its whole style category — the
    line-level shared price 2.71/2.72 worked to remove — and, having no
    retail estimate, was valued at exactly that.

    Mutates `hat` and sets `analysis_status='fallback'` only if at least one
    piece of data was obtained; otherwise leaves the hat untouched (caller's
    skipped/error state stands) and returns False. Never raises.

    `missing_key` says the reason is that no Claude key exists; it selects
    the advice (see `fallback_message`).

    Colors the OWNER set are not colors obtained: they are kept
    (`hat_service.replace_analysis_colors` refuses to overwrite them), so they
    neither count toward "the fallback produced something" nor get announced
    as "colors from photo cutout" — the message would otherwise claim a write
    that did not happen.
    """
    colors = []
    if photo_path.suffix.lower() == ".png":
        try:
            colors = await asyncio.to_thread(color_extraction.extract_hat_colors, photo_path)
        except Exception as exc:  # noqa: BLE001 — fallback must never break uploads
            logger.warning("Fallback color extraction failed for hat=%s: %s", hat.id, exc)
    # `general_color` is the palette name itself: `extract_hat_colors` names
    # each color by its nearest palette entry, and the default color search
    # reads this column. Stated rather than left for `hat_service` to derive
    # from the hex — the derivation reaches the same entry today, and the
    # name the swatch shows and the name search matches should not depend on
    # two lookups continuing to agree.
    tags = [
        tag for tag in (
            hat_service.analysis_color(color.name, color.hex, color.tier, general=color.name)
            for color in colors
        ) if tag is not None
    ]

    brand = await _fallback_brand(db, hat, photo_path)

    # Decided before anything is written, so a fallback that obtained nothing
    # leaves the hat exactly as it was.
    colors_written = bool(tags) and hat.colors_source != hat_service.COLORS_OWNER_SOURCE
    if not colors_written and not brand:
        return False

    provided = []
    if colors_written:
        hat_service.replace_analysis_colors(hat, tags)
        provided.append("colors from photo cutout")
    if brand:
        hat.brand = brand
        # Google Vision's LOGO_DETECTION only fires on a mark it actually saw,
        # so this path is evidence by construction — exactly what the field
        # records. Naming the source keeps it honest about who found it.
        hat.logo_detected = f"{brand} — logo detected by Google Vision"
        provided.append("brand via Google logo detection")
        _apply_resale_link(hat)

    hat.analysis_status = "fallback"
    hat.analysis_error = fallback_message(reason, provided, missing_key=missing_key)
    hat.analyzed_at = datetime.now(timezone.utc)
    return True


async def _fallback_brand(db: AsyncSession, hat: Hat, photo_path: Path) -> str | None:
    """The logo-detected brand, or None — whatever Google Vision does.

    `detect_brand_logo` raises only `GoogleVisionError` for every failure the
    module can name (transport, status, a body that is not JSON, a reply of
    the wrong shape, a key no header can carry); that is the expected
    degrade, logged at INFO. The second handler is the backstop the "never
    raises" contract above rests on, for a failure nobody has named yet: an
    escape here throws away mask colors already extracted and, in a bulk
    import, deletes the hat. It logs the traceback, because an unnamed
    failure is a bug to be read, not a condition to be quiet about.
    """
    google_key, _gsrc = await settings_service.get_google_vision_key(db)
    if not google_key:
        return None
    try:
        logo = await google_vision.detect_brand_logo(photo_path, google_key)
    except google_vision.GoogleVisionError as exc:
        logger.info("Fallback logo detection skipped for hat=%s: %s", hat.id, exc)
        return None
    except Exception:  # the backstop described above — logged with its traceback
        logger.exception("Fallback logo detection failed unexpectedly for hat=%s", hat.id)
        return None
    return logo[0] if logo else None


def _apply_resale_link(hat: Hat) -> None:
    """Attach the resale deep link when the brand qualifies — and no price.

    The fallback's share of `_apply_resale_pointer`. It knows a brand from a
    logo and nothing more, so it writes no price and erases none either: a
    price already on the hat (typed, or left by an earlier full analysis)
    stays exactly as it was. Only a hat with no price at all gets the
    pointer's source label, which names the link ("Browse Melin Recap").
    """
    pointer = melin_recap.build_resale_pointer(hat.brand, hat.style)
    if not pointer:
        return
    hat.resale_price_url = pointer["resale_price_url"]
    if hat.resale_price is None:
        hat.resale_price_source = pointer["resale_price_source"]


def _apply_resale_pointer(hat: Hat) -> None:
    """Attach the resale deep link + pointer price when the brand qualifies.

    The Claude path's, run just before `refresh_melin_resale` fills the price.
    The logo-detection fallback used to share it and then price the hat too;
    it now takes the link alone (`_apply_resale_link`).
    """
    pointer = melin_recap.build_resale_pointer(hat.brand, hat.style)
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
    reads exactly like a fact the owner entered — `Hat.construction_source`
    now records which a value is, but only for values written since it
    existed, and every screen shows the value, not its source. So: blank stays
    blank until a person fills it in.

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
    db, hat: Hat, analysis: claude_analysis.HatAnalysis, leaked: str | None = None
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
        # and assigning the column directly is what lets them drift. With the
        # source it already has, stated: this is a respelling, not a new
        # answer. The setter keeps provenance on its own only across a change
        # of case, and the vocabulary also folds punctuation and accents — so
        # an owner's `brushed-cotton` snapping to `Brushed Cotton` came out as
        # nobody's, which the construction audit then treats as a guess.
        if canonical != hat.construction:
            hat.set_construction(canonical, source=hat.construction_source)


def _apply_analysis(hat: Hat, analysis: claude_analysis.HatAnalysis) -> str | None:
    hat.brand = _keep_on_null(analysis.brand, hat.brand)
    hat.logo_detected = analysis.logo_detected
    hat.artist_series = _keep_on_null(analysis.artist_series, hat.artist_series)
    _apply_construction(hat, analysis.construction)
    # Split "Trenches Hydro — Hawaii 808" into its two halves. Defensive, and
    # it repairs the shape at the source: the tool schema now forbids a
    # separator in `model_name`, but 35 of 235 stored names carried one, and
    # a model that agrees with no real product is the single most expensive
    # thing this pipeline can write — every downstream gate is token
    # containment on it. `naming` splits only on an explicit separator: a name
    # like "Trenches Icon Camo" carries a colorway word with nothing marking
    # it, and guessing where the model ends is how a correct name gets
    # truncated.
    model_name, leaked = naming.split_model_colorway(analysis.model_name)
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

    # Replace colors — unless the owner set them (`replace_analysis_colors`
    # keeps a person's palette through any re-analysis). color_name keeps
    # Claude's phrasing ("heather slate"); general_color is left to derive
    # from the hex, which snaps it to the curated palette so the color filter
    # chips match consistently regardless of naming whims. An answer with no
    # usable color says nothing about the palette, so it replaces nothing.
    tags = [
        tag for tag in (
            hat_service.analysis_color(color.name, color.hex, color.tier)
            for color in analysis.colors
        ) if tag is not None
    ]
    if tags:
        hat_service.replace_analysis_colors(hat, tags)

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
        model, dropped = naming.split_model_colorway(hat.model_name)
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
