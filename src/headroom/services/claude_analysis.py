"""Vision-based hat analysis powered by Claude.

Sends a hat photo to the configured Claude model, requests structured output via tool-use
(brand, model, style descriptor, colors with tier, estimated retail price, design
notes, and a confidence label). Uses prompt caching for the system prompt so
repeated analysis calls are cheap.
"""

from __future__ import annotations

import base64
import json
import logging
from collections.abc import Sequence
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
     liner prints, distinctive shapes). Separately record `logo_detected`
     ONLY when a mark is genuinely visible in frame, naming the mark and its
     owning brand — that field is evidence, while `brand` may be an inference.
  2. Identify the specific model name when the brand has named lines. If it is
     a signature collaboration or artist series, name the collaborator in
     `artist_series` — melin names these for the partner (e.g. "Skye Walker",
     "melin x OluKai"). Leave it null rather than guessing.
  3. Describe the silhouette / style (e.g. "fitted snapback", "5-panel
     trucker", "cuffed beanie").
  4. Extract the dominant primary, secondary, and tertiary colors with both
     a human-friendly name ("navy", "burnt orange") and an approximate hex.
  5. Estimate the original new retail price in USD. See PRICING below — an
     unanchored guess here runs about half of what these hats actually cost.
  6. Add a 1–2 sentence design notes blurb.

PRICING — for melin, the app looks the price up and will OVERRIDE you:
melin retail is keyed on CONSTRUCTION and shape, and the app holds a table of
it (HYDRO $79, HYDROLite $99, beanies $79, Aviator from $99). You do not need
to get those right and should not agonise over them.

What the table cannot see is the EXCEPTIONS, and that is what your estimate is
for: collabs, artist series, limited runs, the Mill straw line ($99-$180) and
Thermal Aviators ($139-$179) all sell above the base. Your number is kept only
when it is HIGHER than the base for the construction, so:
  * If the hat looks like a plain current-season cap, a base-level number is
    fine and will simply be replaced by the table.
  * If it is visibly a collab, an artist series, a straw/Mill piece or a
    cold-weather Aviator, say so with a number ABOVE $99 — that is the case
    where you are adding information the table does not have.
An estimate under $60 for a melin is almost certainly wrong. Do not read the
model line (A-Game, Odysea, Trenches, Coronado, Eagle, Compass, Legend, Caddy,
Coast, The Shore) as a price signal; read the construction.

For other brands, use your own knowledge of their tiers: a New Era 59FIFTY is
around $40–$50, '47 Brand around $30, Goorin around $40–$60, Stetson wool and
felt well above $100.

CRITICAL — what the owner already told you:
The owner may state the model line (e.g. "Melin Trenches") and/or the
construction (e.g. "Thermal"). Both come from someone holding the hat and
reading its tag, so both are GROUND TRUTH and outrank what you think you see.

Identify the specific variant *within* what they stated. Do not pick a
different model line, and do not propose a different construction — HYDRO vs
HYDROLite vs Thermal turns on bonded seams, a gel-welded logo and the
sweatband, none of which are reliably legible in a single photo, so your guess
there is weak evidence against their direct observation.

One part of that IS reliably legible, and it is a falsifier rather than an
identification: **visible stitching on the panel or crown seams means the hat
is not HYDROLite.** HYDROLite seams are bonded and show no thread. A negative
like this is worth far more than a positive guess, because it can be checked
against what the photo actually shows rather than inferred from an overall
impression — and "looks lightweight and technical" describes HYDRO just as
well, which is how HYDROLite became the default wrong answer.

This binds `model_name` too. If they said Thermal, do not return a model_name
containing "HYDROLite" — that contradicts them in the one field they will read
and repeat. If the photo seems inconsistent with what they stated, prefer their
answer and lower model_confidence to "low".

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
            "logo_detected": {
                "type": ["string", "null"],
                "description": (
                    "ONLY if a logo, wordmark or monogram is actually VISIBLE in"
                    " the photo: describe the mark and name the brand that owns"
                    " it, e.g. 'Melin — M monogram, front panel' or"
                    " \"New Era — flag on the left panel\". Null if no mark is"
                    " legible. Do NOT fill this in from an inference about the"
                    " brand — this field records what is visible, not what you"
                    " concluded."
                ),
            },
            "construction": {
                "type": ["string", "null"],
                "description": (
                    "ADVISORY — this value is NOT stored. Construction is"
                    " owner-stated in Headroom, because it cannot be read off a"
                    " photo reliably and a wrong guess both moves money (HYDRO"
                    " $79 vs HYDROLite $99) and hides hats from a filter."
                    " Answer null unless the owner has stated one below, in"
                    " which case repeat it verbatim."
                    " The field still matters for one reason: whatever you"
                    " conclude must appear HERE and never inside model_name,"
                    " which IS stored and is the name a person reads."
                    " RULE: if you can see STITCHING along the panel seams, the"
                    " crown seams or around the brim edge, it is NOT HYDROLite —"
                    " HYDROLite seams are bonded and show no thread at all."
                    " Apply this as a hard exclusion, and do not answer"
                    " 'HYDROLite' merely because a hat looks lightweight or"
                    " technical: that describes HYDRO too, and defaulting to"
                    " HYDROLite is the specific error this rule exists to stop."
                ),
            },
            "artist_series": {
                "type": ["string", "null"],
                "description": (
                    "If this is a signature collaboration or artist series, name"
                    " the collaborator — melin brands these as Signature"
                    " Collaborations / Special Projects and names them for the"
                    " partner, e.g. 'Skye Walker', 'melin x OluKai',"
                    " 'melin x Austin Gamblers'. Tells: a bespoke woven or"
                    " leather patch instead of the standard mark, illustrated"
                    " artwork, a co-branded logo lockup, or a printed interior"
                    " lining. Name the artist or partner, NOT the model. Null"
                    " unless you can actually identify the collaboration —"
                    " guessing here is worse than leaving it empty."
                ),
            },
            "model_name": {
                "type": ["string", "null"],
                "description": (
                    "Specific product name within the brand (e.g. 'A-Game Hydro')."
                    " If the owner stated a model line or a construction, this"
                    " MUST agree with them: for a Trenches in Thermal, 'Trenches"
                    " Thermal' or 'Thermal Trenches Icon' are right and"
                    " 'A-Game HYDROLite' is wrong on both counts. Naming a"
                    " different build here contradicts what they recorded even"
                    " though it is a separate field, and this is the name they"
                    " will read and quote. Null if unknown."
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
            "logo_detected",
            # `construction` is deliberately NOT required. It is advisory, never
            # stored, and demanding an answer for a field that gets discarded
            # invites a confident guess where null is the honest reply.
            "artist_series",
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
    # Defaulted, unlike the fields above: the tool schema still REQUIRES Claude
    # to answer (null is a valid answer), but a caller or fixture that doesn't
    # care about logos shouldn't have to say so — and dataclass ordering forces
    # every defaulted field below the undefaulted ones regardless.
    logo_detected: str | None = None
    # Free-form since 2.11 — "HYDRO", "HYDROLite", "Thermal", or whatever the
    # tag says. Was a three-value enum; the tool schema above is the contract.
    # Null means "could not tell", which leaves the stored value untouched.
    construction: str | None = None
    artist_series: str | None = None
    colors: list[AnalyzedColor] = field(default_factory=list)
    raw: dict | None = None


class ClaudeAnalysisError(Exception):
    """Raised when Claude analysis fails for a recoverable reason."""


def _read_image_b64(image_path: Path) -> tuple[str, str]:
    """Read and encode the photo, as a typed failure rather than an OSError.

    The file can legitimately vanish underneath a run: replacing a hat's photo
    deletes the previous one, and analysis of that previous photo may still be
    in flight. Letting a bare `FileNotFoundError` escape made that case much
    worse than it looks — it propagated past the pipeline's `ClaudeAnalysisError`
    handling to the queue's generic crash handler, which stamped the hat
    `error`, and the correctly-queued run for the NEW photo then found a
    non-pending status and returned without doing anything. The correction was
    dropped silently and permanently.
    """
    try:
        raw = image_path.read_bytes()
    except OSError as exc:
        raise ClaudeAnalysisError(f"Could not read {image_path.name}: {exc}") from exc
    suffix = image_path.suffix.lower()
    media_type = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(suffix, "image/jpeg")
    return base64.standard_b64encode(raw).decode("ascii"), media_type


def _owner_context(
    selected_style: str | None,
    selected_construction: str | None,
    known_series: Sequence[str] = (),
) -> str:
    """The prompt sentence carrying what the OWNER already stated.

    Both are ground truth: they came from someone holding the hat and reading
    its tag, which beats anything inferable from one photo. Construction
    especially — HYDRO vs HYDROLite vs Thermal turns on bonded seams, a
    gel-welded logo and a sweatband, none of which reliably survive a front-on
    shot, so an unguided guess is close to a coin toss.

    Construction was previously not sent at all. The analyser could not
    contradict the stored value (the pipeline stopped applying it), but it
    still folded its own guess into `model_name` — so a hat the owner recorded
    as Thermal came back named "A-Game HYDROLite", which reads as the app
    overruling them and is wrong in the one field they'd quote to someone.

    `known_series` is different in kind: not ground truth about THIS hat, but
    what the collection already contains. It is sent because a series name is
    not something a photo reliably shows — a collab is often identifiable only
    by a small woven label or an embroidery style — so an analyser recalling
    them unaided misses most of them, and the ones it does catch come back in
    whatever spelling it chose. Passing the names the owner has already
    curated turns recall into recognition and pins the spelling.

    The framing has to stay careful, because a candidate list invites a forced
    choice: it is stated as what the collection happens to contain, NOT a set
    of options, with an explicit instruction that null beats a wrong match.
    """
    facts: list[str] = []
    if selected_style and selected_style != "beanie":
        # Style enum values use underscores ("a_game"); render them with
        # spaces and Title Case so the prompt reads naturally.
        pretty = selected_style.replace("_", " ").title()
        facts.append(f"the model line is **{pretty}**")
    if selected_construction:
        facts.append(f"the construction is **{selected_construction}**")

    parts: list[str] = []
    if facts:
        parts.append(
            "The owner has the hat in hand and states that "
            + " and ".join(facts)
            + ". Treat that as ground truth: identify the specific variant within"
            " it, and do NOT substitute a different model line or construction —"
            " including inside `model_name`, which must agree with what the owner"
            " stated rather than naming a build you think you see."
        )

    series_line = _known_series_context(known_series)
    if series_line:
        parts.append(series_line)

    if not parts:
        return "Analyze this hat photo using the tool."

    parts.append("Use the tool to record your analysis.")
    return " ".join(parts)


#: How many known series names to put in the prompt. Far above a personal
#: collection's real count; a bound only so the prompt cannot grow without
#: limit. When it does bite, the prompt SAYS the list is partial rather than
#: presenting a truncated list as if it were everything.
MAX_KNOWN_SERIES = 120


def _known_series_context(known_series: Sequence[str]) -> str:
    """The sentence listing series the collection already uses, or ''."""
    names = [s.strip() for s in known_series if s and s.strip()]
    if not names:
        return ""

    shown, truncated = names[:MAX_KNOWN_SERIES], len(names) > MAX_KNOWN_SERIES
    listed = ", ".join(shown)
    tail = ", among others" if truncated else ""

    return (
        f"For reference, this collection already uses these series and"
        f" collaboration names: {listed}{tail}. If this hat belongs to one of"
        " them, write that name spelled EXACTLY as given so it matches. If it"
        " is a different series, name it as printed on the hat. This is a"
        " record of what the collection happens to contain, NOT a list to"
        " choose from: if the hat is not a collab or artist series at all,"
        " return null for `artist_series`. A wrong match is worse than an"
        " empty field."
    )


async def analyze_hat_image(
    image_path: Path,
    api_key: str,
    model: str | None = None,
    selected_style: str | None = None,
    selected_construction: str | None = None,
    known_series: Sequence[str] = (),
) -> HatAnalysis:
    """Call Claude vision and return a structured HatAnalysis.

    `model` overrides the default. `selected_style` and `selected_construction`
    are what the owner already recorded — both are passed as ground truth, so
    the analysis identifies a variant *within* them rather than proposing a
    rival answer. `known_series` are the collaboration/artist-series names the
    collection already uses, sent so a series the owner has already named
    elsewhere is recognised rather than recalled, and comes back in the
    spelling already on record. Raises ClaudeAnalysisError on any recoverable failure (auth,
    parse, etc.).
    """
    if not api_key:
        raise ClaudeAnalysisError("No Anthropic API key configured.")

    b64, media_type = _read_image_b64(image_path)

    client = AsyncAnthropic(api_key=api_key, timeout=config_settings.http_timeout)
    model_id = model or config_settings.anthropic_model

    user_text = _owner_context(selected_style, selected_construction, known_series)

    try:
        message = await client.messages.create(
            model=model_id,
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
                            "text": user_text,
                        },
                    ],
                }
            ],
        )
    # Logged here, not only where the caller happens to catch it. This module
    # declared a logger and never used it, so the most expensive and most
    # externally-dependent call in the app was the one with no voice of its
    # own: a failing key or a rate limit was visible only as a status on a hat.
    # The message text is safe — the key is never in it.
    except AuthenticationError as exc:
        logger.warning("Claude auth rejected for %s: %s", image_path.name, exc)
        raise ClaudeAnalysisError("Invalid Anthropic API key.") from exc
    except APIError as exc:
        logger.warning("Claude API error for %s: %s", image_path.name, exc)
        raise ClaudeAnalysisError(f"Anthropic API error: {exc}") from exc
    except Exception as exc:
        logger.exception("Claude analysis failed unexpectedly for %s", image_path.name)
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
            logo_detected=payload.get("logo_detected"),
            construction=payload.get("construction"),
            artist_series=payload.get("artist_series"),
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


async def verify_api_key(api_key: str, model: str | None = None) -> tuple[bool, str]:
    """Cheap reachability check for a key + model combo. Returns (ok, message)."""
    if not api_key:
        return False, "No API key provided."
    client = AsyncAnthropic(api_key=api_key, timeout=10.0)
    model_id = model or config_settings.anthropic_model
    try:
        await client.messages.create(
            model=model_id,
            max_tokens=4,
            messages=[{"role": "user", "content": "ping"}],
        )
        return True, f"OK — model '{model_id}' reachable."
    except AuthenticationError:
        return False, "Authentication failed — check the key."
    except APIError as exc:
        return False, f"API error (model '{model_id}'): {exc}"
    except Exception as exc:  # noqa: BLE001 — surfaced to UI
        return False, f"Unexpected error: {exc}"
