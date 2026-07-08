# Analysis fallback: mask-based colors + Google Vision brand detection

**Date:** 2026-07-07 · **Status:** approved (design discussed in-session)

## Problem

Without an Anthropic API key, uploaded hats get `analysis_status="skipped"` and
no colors, brand, model, or price. There is no fallback of any kind (the v0.1
colorthief extractor was removed when Claude Vision became the analyzer). The
owner wants a solid fallback that (a) uses the previously-discussed
Google-connected option and (b) **must reject background colors — only colors
from the hat itself count**.

## Decisions (made with the owner)

- Scope: **colors + brand logo**. No model name, price, or design notes from
  the fallback — those stay empty until a Claude key exists and Reanalyze runs.
- Trigger: fallback fires when **no Anthropic key is configured AND when a
  Claude call fails** (outage, bad key, rate limit).
- Background rejection: colors are extracted **locally from the rembg cutout's
  alpha mask** (only pixels with alpha ≥ 200). The mask *is* the segmentation —
  strictly more accurate than any API-side guess. Google Vision is used only
  for `LOGO_DETECTION` (brand), which the mask cannot provide.
  - Consequence: color swatches work with **zero keys configured**; only the
    brand guess requires a Google Cloud Vision API key.
  - Consequence: if rembg failed for a photo (no alpha mask), no fallback
    colors are produced — we never extract colors from a background-contaminated
    frame.

## Components

1. `services/color_extraction.py` — `extract_hat_colors(png_path) -> list[ExtractedColor]`.
   Pillow-only: thumbnail ≤128px, keep RGBA pixels with alpha ≥ 200, quantize
   (median cut), rank by pixel count, dedupe by nearest-palette-name, return up
   to 3 as tiers primary/secondary/tertiary. Curated ~24-name palette maps RGB →
   human name (fills both `color_name` and `general_color`, like the Claude path).
   Returns `[]` for non-alpha images or too-few opaque pixels.
2. `services/google_vision.py` — `detect_brand_logo(image_path, api_key) ->
   (brand, score) | None` via REST `images:annotate` + API key (no SDK, no
   service account; httpx like ebay_service). Confidence threshold 0.6.
   `GoogleVisionError` on HTTP/API errors; callers log and continue.
3. `services/settings_service.py` — `get/set/clear_google_vision_key`, DB >
   env (`HEADROOM_GOOGLE_VISION_API_KEY`), same pattern as the Anthropic key.
4. `hat_analysis_pipeline.py` — `run_fallback_analysis(db, hat, photo_path,
   reason)`: applies colors + brand, sets `analysis_status="fallback"` (plain
   string column — no migration) and an explanatory `analysis_error`; returns
   False (leaving prior skipped/error state) when it produced nothing. Called
   from the no-key branch and the ClaudeAnalysisError branch of
   `finalize_hat_photo`, and from the reanalyze route (which no longer 400s
   when fallback data is obtainable). eBay comps stay Claude-gated (need a
   model name).
5. Routes: `GET/PUT/DELETE /api/settings/google-vision-key` (reuses
   `ApiKeyStatus`/`ApiKeyUpdate`; mutations admin-guarded).
6. Frontend: Google Vision key card on Settings (clone of the Claude card,
   query key `['settings', 'google-vision-key']`); `fallback` branch in
   HatDetailPage's `AnalysisStatus` pill + `.hr-analysis-status.fallback` CSS +
   info banner; reanalyze button enabled for `skipped`/`fallback` states.

## Error handling

Every fallback sub-step is best-effort: color extraction failure → log, no
colors; Google error → log, no brand. If both yield nothing, prior behavior
(`skipped`/`error`) is preserved byte-for-byte. The fallback never raises out
of the pipeline.

## Testing

No live APIs (existing test contract). Unit tests: synthetic RGBA fixtures for
extraction (background rejection asserted), palette mapping, Vision JSON
parsing via a stubbed transport seam. Pipeline tests: all four paths (no keys /
colors-only / colors+brand / Claude-error → fallback catches) plus
reanalyze-without-key. Settings route tests mirror the Anthropic key tests.

## Docs

README (fallback subsection + env-var row + Google key how-to), docker-compose
commented env line, CLAUDE.md (services, statuses, query keys), CHANGELOG
0.7.0, version bump both manifests. No setup-script change: httpx and Pillow
are already dependencies.
