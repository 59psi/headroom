"""Google Cloud Vision logo detection — fallback brand identification.

Used only when Claude analysis is unavailable. REST + API key deliberately
(no google-cloud-vision SDK, no service-account JSON): one POST to
`images:annotate` with LOGO_DETECTION, mirroring how ebay_service talks to
eBay. The API key follows the house pattern — DB-stored (Settings UI) wins
over the HEADROOM_GOOGLE_VISION_API_KEY env var.

Errors raise GoogleVisionError; the pipeline logs and continues without a
brand rather than failing the upload. EVERY failure this module can meet is
that one type — a transport error, a non-200, a 200 whose body is not JSON (a
captive portal or a proxy's error page answers 200 with HTML), a reply whose
shape is not the documented one, and a stored key no HTTP header can carry.
The pipeline catches `GoogleVisionError` specifically, so anything else that
escaped used to take the whole fallback down with it: the mask colors it had
already extracted were thrown away, and a bulk import deleted the hat.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from pathlib import Path

import httpx

from headroom.config import settings

logger = logging.getLogger(__name__)


def _read_image_b64(image_path) -> str:
    """Read and base64-encode a photo; sync, meant to run under `to_thread`."""
    return base64.b64encode(image_path.read_bytes()).decode("ascii")


_ENDPOINT = "https://vision.googleapis.com/v1/images:annotate"
# Below this Vision score a "logo" is usually a false hit on embroidery.
_MIN_SCORE = 0.6


class GoogleVisionError(Exception):
    pass


async def _annotate(payload: dict, api_key: str) -> dict:
    """Single seam for the HTTP call — tests stub this.

    The key goes in the `X-Goog-Api-Key` HEADER, not `?key=`. As a query
    parameter it ends up in the request URL — and httpx logs the full URL at
    INFO on every call, so the key was printed in clear text into the
    container log each time a hat fell back to Vision. Logs get shipped,
    pasted into issues and read over shoulders; a URL is not a private place
    to put a credential, and Google documents the header for exactly this.

    Returns the decoded body, which is always a dict; anything else raises
    `GoogleVisionError` (see the module docstring for why that is the only
    type allowed out).
    """
    try:
        async with httpx.AsyncClient(timeout=settings.http_timeout) as client:
            resp = await client.post(
                _ENDPOINT, headers={"X-Goog-Api-Key": api_key}, json=payload
            )
    except UnicodeError as exc:
        # A header value has to be ASCII, and httpx refuses one that is not
        # while building the request. A key pasted with a zero-width space or
        # a directional mark in it looks fine in the Settings field and fails
        # here on every hat. Naming the cause is the whole fix available at
        # this layer; the key has to be re-entered.
        raise GoogleVisionError(
            "The stored Google Vision key contains characters an HTTP header"
            " cannot carry — re-enter it in Settings."
        ) from exc
    if resp.status_code != 200:
        detail = ""
        try:
            body = resp.json()
            error = body.get("error") if isinstance(body, dict) else None
            detail = error.get("message", "") if isinstance(error, dict) else ""
        except ValueError:
            detail = resp.text[:200]
        raise GoogleVisionError(f"Vision API {resp.status_code}: {detail}")
    try:
        data = resp.json()
    except ValueError as exc:
        raise GoogleVisionError(
            "Vision API answered 200 with a body that is not JSON"
            " (a proxy or captive portal in the way?)"
        ) from exc
    if not isinstance(data, dict):
        raise GoogleVisionError(
            f"Vision API answered with a JSON {type(data).__name__}, not an object"
        )
    return data


def _usable_logo(annotation: object) -> tuple[str, float] | None:
    """One logo annotation as (description, score), or None if it is not one.

    Skipped rather than fatal: one malformed entry beside a well-formed one
    should not cost the good one. A score must be a real number — `"0.9"` is
    malformed, not 0.9, and `True >= 0.6` would pass a comparison it has no
    business in — and a description must have text in it.
    """
    if not isinstance(annotation, dict):
        return None
    score = annotation.get("score", 0)
    description = annotation.get("description")
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        return None
    if not isinstance(description, str) or not description.strip():
        return None
    return description.strip(), float(score)


async def detect_brand_logo(
    image_path: Path, api_key: str
) -> tuple[str, float] | None:
    """Return (brand, score) for the most confident logo, or None.

    None means "no logo confidently detected" — a normal outcome for plain
    hats, not an error.

    A missing file is also None rather than an exception. This is the fallback
    path: it exists to salvage something when the primary analyzer is
    unavailable, so it must never be the thing that takes the run down. The
    photo can genuinely disappear mid-run when a replacement upload deletes it.
    """
    try:
        # Off the event loop, like the Claude path — a full-resolution cutout
        # is megabytes, and read+encode on the loop stalls every other request.
        content = await asyncio.to_thread(_read_image_b64, image_path)
    except OSError as exc:
        logger.warning("Vision logo detection skipped, unreadable %s: %s", image_path, exc)
        return None
    payload = {
        "requests": [
            {
                "image": {"content": content},
                "features": [{"type": "LOGO_DETECTION", "maxResults": 3}],
            }
        ]
    }
    try:
        data = await _annotate(payload, api_key)
    except GoogleVisionError:
        raise
    except httpx.HTTPError as exc:
        raise GoogleVisionError(f"Vision API request failed: {exc}") from exc

    # The documented shape, checked rather than assumed: `{"responses":
    # [{"logoAnnotations": [...]}]}`. A reply that is JSON but not that shape
    # is a failure of the call — typed, so the fallback logs it and carries on
    # with the colors it already has.
    responses = data.get("responses") or [{}]
    if not isinstance(responses, list) or not isinstance(responses[0], dict):
        raise GoogleVisionError("Vision API reply has no readable `responses` entry")
    response = responses[0]
    if "error" in response:
        error = response["error"]
        message = error.get("message", "unknown") if isinstance(error, dict) else error
        raise GoogleVisionError(f"Vision API error: {message}")

    annotations = response.get("logoAnnotations") or []
    if not isinstance(annotations, list):
        raise GoogleVisionError("Vision API reply's `logoAnnotations` is not a list")
    logos = [logo for logo in map(_usable_logo, annotations) if logo]
    best = max(logos, key=lambda logo: logo[1], default=None)
    if best and best[1] >= _MIN_SCORE:
        return best
    return None
