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
thread-safe for `Run()` calls when invoked through `asyncio.to_thread`. Calls
are nonetheless bounded by a semaphore, default ONE at a time.

An earlier version held an `asyncio.Lock` here; it was removed on the grounds
that serializing "defeats the entire reason to offload to a thread". That
argument weighed throughput and omitted memory, and it also mis-stated the
topology: there are exactly two producers in this app — `analysis_queue` and
`import_service` — and each is a single-consumer worker, so dropping the lock
bought a factor of at most TWO. What it cost was a doubling of peak memory, on
a Raspberry Pi, for the largest allocation the process makes (a ~179 MB model
plus a full-resolution decode). Nothing waits on this work — it moved off the
request path precisely so latency stopped mattering — so trading that
throughput back for a bounded footprint is the right way round.

`HEADROOM_REMBG_CONCURRENCY` raises the bound for anyone running this on real
hardware.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from PIL import Image

from headroom.config import env_int

logger = logging.getLogger(__name__)

_MODEL_NAME = os.environ.get("HEADROOM_REMBG_MODEL", "isnet-general-use")
_session = None
# Single-shot lock used ONLY around lazy session creation, not around inference.
# The session itself is reentrant once initialized.
_init_lock = asyncio.Lock()

# How many inferences may be in flight at once, across ALL callers. Created
# lazily because a module-level Semaphore binds to whichever event loop happens
# to be running at import time, which is not the app's loop under pytest.
_inference_sem: asyncio.Semaphore | None = None


def _concurrency() -> int:
    """Bound on concurrent inferences.

    Read ONCE, when `_get_inference_sem` first builds the semaphore — a test
    that wants a different bound must reset `_inference_sem` to None first.
    """
    return max(1, env_int("HEADROOM_REMBG_CONCURRENCY", 1))


def _get_inference_sem() -> asyncio.Semaphore:
    global _inference_sem
    if _inference_sem is None:
        _inference_sem = asyncio.Semaphore(_concurrency())
    return _inference_sem


def _get_session():
    """Lazy import + lazy session creation. rembg pulls onnxruntime on import."""
    global _session
    if _session is None:
        from rembg import new_session  # noqa: PLC0415 — defer heavy import
        _session = new_session(_MODEL_NAME)
    return _session


# Alpha below the floor is background; at or above the ceiling the model was
# confident. Everything between is stretched up to opaque rather than judged.
# The ceiling is 128 on purpose — that is where rembg's own `post_process_mask`
# put its cutoff, so this is the same boundary used to *keep* pixels instead of
# to delete them.
_ALPHA_FLOOR = 25
_ALPHA_CEIL = 128


def _harden_alpha(cut):
    """Make a soft mask opaque without throwing away what it was unsure about.

    A saliency model returns confidence per pixel, and the hat's thin bill is
    exactly where it is least sure. Two ways to read that mask, and the obvious
    one is a trap:

    * Use it raw and mid-confidence regions render semi-transparent, so the hat
      looks washed out — "ghosted" — against the near-black canvas.
    * Binarize it (rembg's `post_process_mask`: blur, then threshold at 127) and
      the ghosting goes, but every pixel the model was less than ~50% sure about
      is *deleted*. Measured on a synthetic brim: at confidence 128 about 76% of
      it survives, at 120 that collapses to 6%, and by 40 the brim is gone
      entirely. That turns "faint bill" into "no bill" — worse than the problem
      it fixes, and indistinguishable from the low-capacity-model bug we changed
      the default model to avoid.

    So ramp instead of threshold: clearly-background pixels go to zero, and
    anything above that is scaled up to opaque. A brim the model saw at 39%
    opacity comes out at 73% — present and solid rather than ghosted or gone.
    """
    if cut.mode != "RGBA":
        return cut

    import numpy as np  # noqa: PLC0415 — already a rembg dependency

    alpha = np.asarray(cut.getchannel("A"), dtype=np.float32)
    ramped = np.clip((alpha - _ALPHA_FLOOR) / (_ALPHA_CEIL - _ALPHA_FLOOR), 0.0, 1.0)
    cut.putalpha(Image.fromarray((ramped * 255.0).astype(np.uint8), mode="L"))
    return cut


def _remove_sync(input_path: Path, output_path: Path) -> Path:
    from rembg import remove  # noqa: PLC0415

    session = _get_session()
    with Image.open(input_path) as src:
        # rembg works best from RGBA / RGB Pillow images
        if src.mode not in ("RGB", "RGBA"):
            src = src.convert("RGBA")
        cut = _harden_alpha(remove(src, session=session))

    final_path = output_path.with_suffix(".png")
    cut.save(final_path, "PNG", optimize=True)
    return final_path


async def remove_background(input_path: Path, output_path: Path) -> Path | None:
    """Run rembg in a worker thread; return new path or None on failure.

    First call serializes briefly while the ONNX session loads (under
    `_init_lock`). Inference then runs under `_get_inference_sem()`, which
    bounds how many of these can be resident at once across every caller —
    both background workers reach this function, and nothing else stops them
    arriving together.
    """
    try:
        # Init the session under a lock to avoid two concurrent first-callers
        # creating two sessions and racing on the model file.
        if _session is None:
            async with _init_lock:
                if _session is None:
                    await asyncio.to_thread(_get_session)
        async with _get_inference_sem():
            return await asyncio.to_thread(_remove_sync, input_path, output_path)
    except Exception as exc:  # noqa: BLE001 — surface to caller, never crash upload
        logger.warning("Background removal failed for %s: %s", input_path, exc)
        return None
