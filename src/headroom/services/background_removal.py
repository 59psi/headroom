"""Background removal for hat photos using rembg (ONNX-based).

The default model is `isnet-general-use`. It used to be `u2netp` (4.7MB), chosen
for Pi-friendliness, but that model's low capacity loses *thin protruding
structures* — and a hat is mostly one blob (the crown) with exactly one thin
protrusion (the bill). u2netp reliably kept the crown and trimmed the bill,
producing cutouts of hats with no brim.

The cost is size and time: ~179MB and a slower inference. That became an
acceptable trade once analysis moved off the request path into
`analysis_queue` — nothing is waiting on it, so accuracy beats latency here.
Set `HEADROOM_REMBG_MODEL` to go back ('u2netp', 'silueta') or heavier
('birefnet-general'); the Docker image pre-caches whatever `REMBG_MODEL` names.

Concurrency: rembg sessions wrap an `onnxruntime.InferenceSession`, which is
thread-safe for `Run()` calls when invoked through `asyncio.to_thread`. We
intentionally do NOT serialize calls behind a process-global lock — that would
defeat the entire reason to offload to a thread. The previous implementation
held an `asyncio.Lock` here, which made all uploads queue one-at-a-time even
when multiple worker threads were available.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from PIL import Image

logger = logging.getLogger(__name__)

_MODEL_NAME = os.environ.get("HEADROOM_REMBG_MODEL", "isnet-general-use")
_session = None
# Single-shot lock used ONLY around lazy session creation, not around inference.
# The session itself is reentrant once initialised.
_init_lock = asyncio.Lock()


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

    final_path = output_path.with_suffix(".png")
    cut.save(final_path, "PNG", optimize=True)
    return final_path


async def remove_background(input_path: Path, output_path: Path) -> Path | None:
    """Run rembg in a worker thread; return new path or None on failure.

    First call serializes briefly while the ONNX session loads (under
    `_init_lock`). Subsequent calls run concurrently across whatever worker
    threads asyncio's default executor provides.
    """
    try:
        # Init the session under a lock to avoid two concurrent first-callers
        # creating two sessions and racing on the model file.
        if _session is None:
            async with _init_lock:
                if _session is None:
                    await asyncio.to_thread(_get_session)
        return await asyncio.to_thread(_remove_sync, input_path, output_path)
    except Exception as exc:  # noqa: BLE001 — surface to caller, never crash upload
        logger.warning("Background removal failed for %s: %s", input_path, exc)
        return None
