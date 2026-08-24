"""Google Cloud Vision logo detection — fallback brand identification.

Used only when Claude analysis is unavailable. REST + API key deliberately
(no google-cloud-vision SDK, no service-account JSON): one POST to
`images:annotate` with LOGO_DETECTION, mirroring how ebay_service talks to
eBay. The API key follows the house pattern — DB-stored (Settings UI) wins
over the HEADROOM_GOOGLE_VISION_API_KEY env var.

Errors raise GoogleVisionError; the pipeline logs and continues without a
brand rather than failing the upload.
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path

import httpx

from headroom.config import settings

logger = logging.getLogger(__name__)

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
    """
    async with httpx.AsyncClient(timeout=settings.http_timeout) as client:
        resp = await client.post(
            _ENDPOINT, headers={"X-Goog-Api-Key": api_key}, json=payload
        )
    if resp.status_code != 200:
        detail = ""
        try:
            detail = resp.json().get("error", {}).get("message", "")
        except ValueError:
            detail = resp.text[:200]
        raise GoogleVisionError(f"Vision API {resp.status_code}: {detail}")
    return resp.json()


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
        raw = image_path.read_bytes()
    except OSError as exc:
        logger.warning("Vision logo detection skipped, unreadable %s: %s", image_path, exc)
        return None
    content = base64.b64encode(raw).decode("ascii")
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

    response = (data.get("responses") or [{}])[0]
    if "error" in response:
        raise GoogleVisionError(
            f"Vision API error: {response['error'].get('message', 'unknown')}"
        )

    annotations = response.get("logoAnnotations") or []
    best = max(annotations, key=lambda a: a.get("score", 0), default=None)
    if best and best.get("score", 0) >= _MIN_SCORE and best.get("description"):
        return best["description"].strip(), best["score"]
    return None
