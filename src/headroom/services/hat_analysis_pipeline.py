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
import time
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from headroom.config import settings
from headroom.models.hat import Hat
from headroom.models.hat_color import HatColor
from headroom.services import settings_service
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

logger = logging.getLogger(__name__)


async def finalize_hat_photo(
    db: AsyncSession,
    hat: Hat,
    processed_jpeg_path: Path,
) -> Hat:
    """Apply background removal + Claude analysis to a freshly-saved JPEG.

    The transparent PNG (if produced) replaces the JPEG as the canonical photo.
    Mutates `hat` in place. Caller is responsible for the final commit.
    """
    upload_dir = settings.upload_dir
    photo_dir = processed_jpeg_path.parent

    # 1. Background removal → transparent PNG, swap as canonical
    t_rembg0 = time.monotonic()
    cutout_target = photo_dir / processed_jpeg_path.stem
    transparent_path = await remove_background(processed_jpeg_path, cutout_target)
    t_rembg = time.monotonic() - t_rembg0
    if transparent_path is not None and transparent_path.exists():
        # Drop the JPEG, keep the PNG
        if transparent_path.resolve() != processed_jpeg_path.resolve():
            processed_jpeg_path.unlink(missing_ok=True)
        canonical_path = transparent_path
    else:
        canonical_path = processed_jpeg_path

    hat.photo_path = f"hats/{canonical_path.name}"

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

    t_claude0 = time.monotonic()
    try:
        analysis: HatAnalysis = await analyze_hat_image(
            canonical_path, api_key,
            model=model_id, selected_style=hat.style,
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
    t_ebay0 = time.monotonic()
    await _refresh_ebay_comps(db, hat)
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
    api_key, _source = await settings_service.get_anthropic_key(db)
    if not api_key:
        return await run_fallback_analysis(
            db, hat, photo_path, reason="No Anthropic API key configured"
        )

    model_id, _msrc = await settings_service.get_anthropic_model(db)
    try:
        analysis = await analyze_hat_image(
            photo_path, api_key, model=model_id, selected_style=hat.style
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
    await _refresh_ebay_comps(db, hat)
    await refresh_melin_resale(hat)
    return True


async def refresh_melin_resale(hat: Hat) -> None:
    """Fill resale_price with a live Melin Recap median. Best-effort.

    Runs for Melin hats only; leaves the deep-link pointer fields alone and
    the price null when the marketplace API is unreachable (the pre-live
    behavior).
    """
    if not is_melin(hat.brand):
        return
    try:
        stats = await fetch_resale_stats(hat.style, hat.model_name)
    except MelinRecapError as exc:
        logger.info("Melin Recap stats skipped for hat %s: %s", hat.id, exc)
        return
    if not stats:
        return
    hat.resale_price = stats["median"]
    scope = "model" if stats["sample"] == "model" else "style"
    hat.resale_price_source = (
        f"Melin Recap · median of {stats['count']} live {scope} listings"
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
        provided.append("brand via Google logo detection")
        pointer = build_resale_pointer(hat.brand, hat.style)
        if pointer:
            hat.resale_price = pointer["resale_price"]
            hat.resale_price_source = pointer["resale_price_source"]
            hat.resale_price_url = pointer["resale_price_url"]
            hat.resale_checked_at = datetime.now(timezone.utc)
        await refresh_melin_resale(hat)

    hat.analysis_status = "fallback"
    hat.analysis_error = (
        f"{reason} — basic fallback applied ({', '.join(provided)}). "
        "Add a Claude API key and Reanalyze for full identification."
    )
    hat.analyzed_at = datetime.now(timezone.utc)
    return True


def _apply_analysis(hat: Hat, analysis: HatAnalysis) -> None:
    hat.brand = analysis.brand
    hat.model_name = analysis.model_name
    hat.model_confidence = analysis.model_confidence
    hat.style_descriptor = analysis.style_descriptor
    hat.design_notes = analysis.design_notes
    hat.estimated_new_price = analysis.estimated_new_price_usd
    hat.estimated_new_price_source = "Claude Vision"
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
    pointer = build_resale_pointer(hat.brand, hat.style)
    if pointer:
        hat.resale_price = pointer["resale_price"]
        hat.resale_price_source = pointer["resale_price_source"]
        hat.resale_price_url = pointer["resale_price_url"]
        hat.resale_checked_at = datetime.now(timezone.utc)
