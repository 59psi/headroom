"""The long-form write-up: what a hat IS, not what it looks like.

`design_notes` is one sentence from the vision pass describing the object in
front of the camera. This is the other half — several paragraphs about the
collection or collab the hat belongs to, what that drop was, and where this
particular colourway sits within it. It is written whenever the hat is
analysed, re-analysed, or has its collection changed, because the collection
is the fact that makes the rest of it worth writing.

**On invention.** This app gives Claude no web access, so "look up the
collection" means its own knowledge plus the facts we hand it. A niche melin
artist-series drop is exactly the kind of subject a model will happily invent
a release date, an athlete's biography and an edition size for. The prompt
below is therefore built around one rule — say what you don't know — and the
grounding block hands over everything the database already holds so there is
less blank space to fill. `STORY_SYSTEM_PROMPT` is the whole defence; treat
edits to it as a change to what the app asserts about real products.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

from anthropic import AsyncAnthropic, APIError, AuthenticationError
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from headroom.config import settings as config_settings
from headroom.database import async_session
from headroom.models.hat import Hat
from headroom.services.claude_analysis import ClaudeAnalysisError, _read_image_b64

logger = logging.getLogger(__name__)

# Long enough for several paragraphs, short enough that a runaway generation
# costs a known amount. ~1500 tokens is comfortably over the target length.
_MAX_TOKENS = 1500

STORY_SYSTEM_PROMPT = """You are writing a short reference entry about one hat \
in a private collection, for the person who owns it.

Write 2-4 short paragraphs covering, in this order:
1. What this hat is — the model, its construction, and what that construction \
actually does for the wearer.
2. The collection, collab or artist series it belongs to, if one is named \
below: who or what it is, and what that partnership or line is about.
3. What makes THIS example distinctive — its colourway, its logo treatment, \
what the photo shows.

Rules, in order of importance:

- **Never invent a verifiable fact.** No release dates, edition sizes, retail \
prices, athlete or artist biographies, sponsorship details, or collaboration \
histories unless they are stated in the facts below or you genuinely know \
them. This is a real product and the owner will read this as true.
- **When you don't know the collection, say so in one short clause** and spend \
the paragraph on what the photo and the recorded facts actually support. \
"I don't have reliable information about this particular series" is a good \
sentence. A fabricated origin story is not.
- Prefer the specific over the flattering. No marketing copy, no "timeless \
classic", no second-person sales pitch.
- Plain prose. No headings, no bullet lists, no markdown. Paragraphs only.
"""


def _facts_block(hat: Hat) -> str:
    """Everything the database already knows, as ground truth for the model."""
    colors = ", ".join(
        f"{c.general_color or c.color_name} ({c.hex_value})"
        for c in sorted(hat.colors or [], key=lambda c: c.dominance_rank)
    )
    fields: list[tuple[str, object]] = [
        ("Brand", hat.brand),
        ("Model", hat.model_name),
        ("Collection / artist series", hat.artist_series),
        ("Colourway", hat.colorway),
        ("Construction", hat.construction),
        ("Shape", hat.style),
        ("Size", hat.size),
        ("Condition", hat.condition),
        ("Colours seen", colors or None),
        ("Logo seen", hat.logo_detected),
        ("Appearance", hat.design_notes),
    ]
    known = "\n".join(f"- {label}: {value}" for label, value in fields if value)
    return (
        "Facts on record for this hat. Treat these as true and do not "
        "contradict them:\n"
        f"{known}\n\n"
        + (
            "No collection or artist series is recorded for this hat, so do "
            "not speculate about one — write about the model and this example "
            "instead.\n"
            if not hat.artist_series
            else ""
        )
    )


async def write_story(
    hat: Hat,
    image_path: Path | None,
    api_key: str,
    model: str | None = None,
) -> str:
    """Generate the write-up for one hat. Raises ClaudeAnalysisError on failure.

    The photo is included when there is one: it is what keeps the third
    paragraph describing this hat rather than a generic example of the model.
    """
    if not api_key:
        raise ClaudeAnalysisError("No Anthropic API key configured.")

    content: list[dict] = []
    if image_path is not None and image_path.exists():
        b64, media_type = _read_image_b64(image_path)
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": b64},
        })
    content.append({"type": "text", "text": _facts_block(hat)})

    client = AsyncAnthropic(api_key=api_key, timeout=config_settings.http_timeout)
    try:
        message = await client.messages.create(
            model=model or config_settings.anthropic_model,
            max_tokens=_MAX_TOKENS,
            system=[{
                "type": "text",
                "text": STORY_SYSTEM_PROMPT,
                # Same prompt on every hat in a re-analyse sweep, so it caches.
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": content}],
        )
    except AuthenticationError as exc:
        logger.warning("Claude auth rejected writing story for hat %s: %s", hat.id, exc)
        raise ClaudeAnalysisError("Invalid Anthropic API key.") from exc
    except APIError as exc:
        logger.warning("Claude API error writing story for hat %s: %s", hat.id, exc)
        raise ClaudeAnalysisError(f"Anthropic API error: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 — never let this fail an analysis
        logger.warning("Story generation failed for hat %s: %s", hat.id, exc)
        raise ClaudeAnalysisError(f"Story generation failed: {exc}") from exc

    text = "\n\n".join(
        block.text.strip()
        for block in message.content
        if getattr(block, "type", None) == "text" and block.text.strip()
    ).strip()
    if not text:
        raise ClaudeAnalysisError("Claude returned an empty write-up.")
    return text


def apply_story(hat: Hat, text: str) -> None:
    """Store a freshly written story and clear the pending flag."""
    hat.story = text
    hat.story_generated_at = datetime.now(timezone.utc)
    hat.story_pending = False


# --------------------------- rewrite queue ---------------------------- #
# Changing a hat's collection is a PUT that must return immediately, but it is
# also the single most likely moment for the write-up to become wrong — the
# whole middle paragraph is about the collection. So the write is queued and a
# worker picks it up, exactly like `analysis_queue`, with the same durability
# rules: the loop survives any per-hat failure, and `story_pending` is a
# COLUMN so a restart mid-queue re-queues rather than stranding a hat with a
# write-up describing a collection it is no longer in.
#
# A second, separate queue rather than reusing the analysis one: re-running a
# full analysis to change one paragraph would repeat rembg, the vision call,
# the eBay lookup and two Melin requests — minutes of work, and it would
# overwrite fields the owner may have corrected by hand since.

_queue: asyncio.Queue[int] | None = None
_worker_task: asyncio.Task | None = None


def worker_alive() -> bool:
    return _worker_task is not None and not _worker_task.done()


def enqueue(hat_id: int) -> bool:
    """Queue a hat for a rewrite. False means nothing is draining the queue."""
    if _queue is None or not worker_alive():
        return False
    _queue.put_nowait(hat_id)
    return True


async def _process(hat_id: int) -> None:
    from headroom.services import settings_service

    async with async_session() as db:
        hat = (await db.execute(
            select(Hat).options(selectinload(Hat.colors)).where(Hat.id == hat_id)
        )).scalar_one_or_none()
        if hat is None or not hat.story_pending:
            return  # deleted, or another pass already wrote it

        api_key, _src = await settings_service.get_anthropic_key(db)
        if not api_key:
            # Nothing to do and nothing to retry on every boot forever.
            hat.story_pending = False
            await db.commit()
            return
        model_id, _ms = await settings_service.get_anthropic_model(db)

        image = None
        if hat.photo_path:
            candidate = config_settings.upload_dir / hat.photo_path
            image = candidate if candidate.exists() else None

        try:
            text = await write_story(hat, image, api_key, model=model_id)
        except ClaudeAnalysisError as exc:
            # Leave the OLD story in place — a stale write-up beats a blank
            # one — but stop the retry loop, or a permanently bad key means
            # every boot re-queues every hat.
            logger.info("Story rewrite failed for hat %s: %s", hat_id, exc)
            hat.story_pending = False
            await db.commit()
            return

        apply_story(hat, text)
        await db.commit()


async def _worker_loop() -> None:
    assert _queue is not None
    logger.info("Story worker started.")
    try:
        while True:
            hat_id = await _queue.get()
            try:
                await _process(hat_id)
            except Exception as exc:  # noqa: BLE001 — one bad hat must not kill it
                logger.exception("Story worker: unhandled error on hat %s: %s", hat_id, exc)
            finally:
                _queue.task_done()
    except asyncio.CancelledError:
        logger.info("Story worker cancelled.")
        raise


async def _recover_on_boot() -> None:
    assert _queue is not None
    async with async_session() as db:
        stranded = (await db.execute(
            select(Hat.id).where(Hat.story_pending.is_(True))
        )).scalars().all()
    for hat_id in stranded:
        _queue.put_nowait(hat_id)
    if stranded:
        logger.info("Re-queued %d hat(s) awaiting a write-up.", len(stranded))


async def start_worker() -> None:
    """Wire up the queue + worker. Called from app.lifespan."""
    global _queue, _worker_task
    _queue = asyncio.Queue()
    _worker_task = asyncio.create_task(_worker_loop())
    await _recover_on_boot()


async def stop_worker() -> None:
    global _queue, _worker_task
    if _worker_task is not None:
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass
        _worker_task = None
    _queue = None


def queue_depth() -> int:
    return _queue.qsize() if _queue is not None else 0
