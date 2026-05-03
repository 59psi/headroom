"""Vision-based hat analysis powered by Claude.

Sends a hat photo to Claude Sonnet 4.6, requests structured output via tool-use
(brand, model, style descriptor, colors with tier, estimated retail price, design
notes, and a confidence label). Uses prompt caching for the system prompt so
repeated analysis calls are cheap.
"""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from anthropic import APIError, AsyncAnthropic
from anthropic._exceptions import AuthenticationError

from headroom.config import settings as config_settings

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are an expert hat appraiser and stylist.

You specialise in identifying premium hat brands and their specific models.
You are particularly knowledgeable about Melin hats, whose model lines include
A-Game, Odysea, Trenches, Coronado, Eagle, Compass, Legend, Caddy, Coast, and
their seasonal collabs. You also know New Era, '47 Brand, Goorin, Brixton,
Hurley, Patagonia, Stetson, and most other modern lifestyle hat brands.

When given a single hat photo you will:
  1. Identify the brand if possible (look for embroidered logos, hangtags,
     liner prints, distinctive shapes).
  2. Identify the specific model name when the brand has named lines.
  3. Describe the silhouette / style (e.g. "fitted snapback", "5-panel
     trucker", "cuffed beanie").
  4. Extract the dominant primary, secondary, and tertiary colors with both
     a human-friendly name ("navy", "burnt orange") and an approximate hex.
  5. Estimate the original new retail price in USD using your knowledge of
     the brand's typical pricing tiers.
  6. Add a 1–2 sentence design notes blurb.

Always respond by calling the `record_hat_analysis` tool. Never reply in plain
text. If you genuinely cannot tell something, set the field to null and lower
the confidence rating.
"""


HAT_ANALYSIS_TOOL = {
    "name": "record_hat_analysis",
    "description": (
        "Record the structured analysis of a hat photo. Always call exactly once."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "brand": {
                "type": ["string", "null"],
                "description": "Brand name (e.g. 'Melin', 'New Era'). Null if unknown.",
            },
            "model_name": {
                "type": ["string", "null"],
                "description": (
                    "Specific product name within the brand (e.g. 'A-Game Hydro')."
                    " Null if unknown."
                ),
            },
            "model_confidence": {
                "type": "string",
                "enum": ["high", "medium", "low"],
                "description": "How confident you are in the brand+model identification.",
            },
            "style_descriptor": {
                "type": "string",
                "description": (
                    "Short silhouette descriptor: 'fitted snapback', 'trucker', "
                    "'5-panel', 'cuffed beanie', etc."
                ),
            },
            "design_notes": {
                "type": "string",
                "description": "1-2 sentence design observations.",
            },
            "estimated_new_price_usd": {
                "type": ["number", "null"],
                "description": "Best-effort original retail price in USD, or null.",
            },
            "colors": {
                "type": "array",
                "minItems": 1,
                "maxItems": 5,
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Human-friendly color name (e.g. 'navy').",
                        },
                        "hex": {
                            "type": "string",
                            "pattern": "^#[0-9a-fA-F]{6}$",
                            "description": "Approximate hex value (#rrggbb).",
                        },
                        "tier": {
                            "type": "string",
                            "enum": ["primary", "secondary", "tertiary", "accent"],
                        },
                    },
                    "required": ["name", "hex", "tier"],
                },
            },
        },
        "required": [
            "brand",
            "model_name",
            "model_confidence",
            "style_descriptor",
            "design_notes",
            "estimated_new_price_usd",
            "colors",
        ],
    },
}


@dataclass
class AnalyzedColor:
    name: str
    hex: str
    tier: str


@dataclass
class HatAnalysis:
    brand: str | None
    model_name: str | None
    model_confidence: str
    style_descriptor: str
    design_notes: str
    estimated_new_price_usd: float | None
    colors: list[AnalyzedColor] = field(default_factory=list)
    raw: dict | None = None


class ClaudeAnalysisError(Exception):
    """Raised when Claude analysis fails for a recoverable reason."""


def _read_image_b64(image_path: Path) -> tuple[str, str]:
    raw = image_path.read_bytes()
    suffix = image_path.suffix.lower()
    media_type = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(suffix, "image/jpeg")
    return base64.standard_b64encode(raw).decode("ascii"), media_type


async def analyze_hat_image(image_path: Path, api_key: str) -> HatAnalysis:
    """Call Claude vision and return a structured HatAnalysis.

    Raises ClaudeAnalysisError on any recoverable failure (auth, parse, etc.).
    """
    if not api_key:
        raise ClaudeAnalysisError("No Anthropic API key configured.")

    b64, media_type = _read_image_b64(image_path)

    client = AsyncAnthropic(api_key=api_key, timeout=config_settings.http_timeout)

    try:
        message = await client.messages.create(
            model=config_settings.anthropic_model,
            max_tokens=1024,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            tools=[HAT_ANALYSIS_TOOL],
            tool_choice={"type": "tool", "name": "record_hat_analysis"},
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": "Analyze this hat photo using the tool.",
                        },
                    ],
                }
            ],
        )
    except AuthenticationError as exc:
        raise ClaudeAnalysisError("Invalid Anthropic API key.") from exc
    except APIError as exc:
        raise ClaudeAnalysisError(f"Anthropic API error: {exc}") from exc
    except Exception as exc:
        raise ClaudeAnalysisError(f"Unexpected analysis failure: {exc}") from exc

    tool_block = next(
        (b for b in message.content if getattr(b, "type", None) == "tool_use"), None
    )
    if tool_block is None:
        raise ClaudeAnalysisError("Claude did not return a tool_use block.")

    payload = tool_block.input
    try:
        # tool_use input may be a dict already (anthropic SDK >= 0.40)
        if isinstance(payload, str):
            payload = json.loads(payload)
        colors = [
            AnalyzedColor(name=c["name"], hex=c["hex"], tier=c.get("tier", "primary"))
            for c in payload.get("colors", [])
        ]
        return HatAnalysis(
            brand=payload.get("brand"),
            model_name=payload.get("model_name"),
            model_confidence=payload.get("model_confidence", "low"),
            style_descriptor=payload.get("style_descriptor", ""),
            design_notes=payload.get("design_notes", ""),
            estimated_new_price_usd=payload.get("estimated_new_price_usd"),
            colors=colors,
            raw=payload if isinstance(payload, dict) else None,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ClaudeAnalysisError(f"Could not parse Claude response: {exc}") from exc


async def verify_api_key(api_key: str) -> tuple[bool, str]:
    """Cheap reachability check for an API key. Returns (ok, message)."""
    if not api_key:
        return False, "No API key provided."
    client = AsyncAnthropic(api_key=api_key, timeout=10.0)
    try:
        await client.messages.create(
            model=config_settings.anthropic_model,
            max_tokens=4,
            messages=[{"role": "user", "content": "ping"}],
        )
        return True, "Key is valid."
    except AuthenticationError:
        return False, "Authentication failed — check the key."
    except APIError as exc:
        return False, f"API error: {exc}"
    except Exception as exc:  # noqa: BLE001 — surfaced to UI
        return False, f"Unexpected error: {exc}"
