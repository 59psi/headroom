"""Background removal for hat photos using rembg (ONNX-based).

The default model is `u2netp` — a 4.7MB lightweight U²-Net designed for edge
devices like a Raspberry Pi. Heavier models can be selected via the
`HEADROOM_REMBG_MODEL` env var (e.g. 'u2net', 'silueta', 'isnet-general-use').
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from PIL import Image

logger = logging.getLogger(__name__)

_MODEL_NAME = os.environ.get("HEADROOM_REMBG_MODEL", "u2netp")
_session = None
_session_lock = asyncio.Lock()


def _get_session():
    """Lazy import + lazy session creation. rembg pulls onnxruntime on import."""
    global _session
    if _session is None:
        from rembg import new_session  # noqa: PLC0415 — defer heavy import
        _session = new_session(_MODEL_NAME)
    return _session


def _remove_sync(input_path: Path, output_path: Path) -> Path:
    from rembg import remove  # noqa: PLC0415

    session = _get_session()
    with Image.open(input_path) as src:
        # rembg works best from RGBA / RGB Pillow images
        if src.mode not in ("RGB", "RGBA"):
            src = src.convert("RGBA")
        cut = remove(src, session=session)

    # Always save as PNG to preserve alpha
    final_path = output_path.with_suffix(".png")
    cut.save(final_path, "PNG", optimize=True)
    return final_path


async def remove_background(input_path: Path, output_path: Path) -> Path | None:
    """Run rembg in a thread; return new path or None on failure.

    Caller decides whether to fall back to the original on None.
    """
    try:
        async with _session_lock:
            return await asyncio.to_thread(_remove_sync, input_path, output_path)
    except Exception as exc:  # noqa: BLE001 — surface to caller, never crash upload
        logger.warning("Background removal failed for %s: %s", input_path, exc)
        return None
