"""End-to-end pipeline for analysing a freshly-uploaded hat photo.

Steps:
  1. Process upload (resize / convert to JPEG) — handled by photo utils.
  2. Remove background → transparent PNG (this becomes the canonical photo).
  3. Call Claude Vision for brand / model / colors / price / notes.
  4. Build Melin Recap deep-link if applicable.
  5. Persist analysis results onto the Hat row (caller commits).

The pipeline degrades gracefully: any single step can fail without breaking
the others. If Claude is not configured the upload still saves; the hat just
gets `analysis_status='skipped'`.
"""

from __future__ import annotations

import logging
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
from headroom.services.ebay_service import EbayError, find_comps
from headroom.services.melin_recap import build_resale_pointer

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
    cutout_target = photo_dir / processed_jpeg_path.stem
    transparent_path = await remove_background(processed_jpeg_path, cutout_target)
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
        return hat

    model_id, _model_source = await settings_service.get_anthropic_model(db)

    try:
        analysis: HatAnalysis = await analyze_hat_image(
            canonical_path, api_key,
            model=model_id, selected_style=hat.style,
        )
    except ClaudeAnalysisError as exc:
        logger.warning("Hat analysis failed for hat %s: %s", hat.id, exc)
        hat.analysis_status = "error"
        hat.analysis_error = str(exc)
        hat.analyzed_at = datetime.now(timezone.utc)
        return hat

    _apply_analysis(hat, analysis)

    # eBay comp refresh — best-effort, never fail the upload over it.
    if hat.brand and hat.model_name:
        try:
            comps = await find_comps(db, brand=hat.brand, model=hat.model_name, style=hat.style)
            for k, v in comps.items():
                setattr(hat, k, v)
        except EbayError as exc:
            logger.info("eBay comp refresh skipped for hat %s: %s", hat.id, exc)

    return hat


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

    # Replace colors
    hat.colors.clear()
    for rank, color in enumerate(analysis.colors, start=1):
        hat.colors.append(
            HatColor(
                color_name=color.name,
                general_color=color.name,
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
