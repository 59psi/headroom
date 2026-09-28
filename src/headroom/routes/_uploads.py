"""Spooling uploads to disk: the one place a route turns an `UploadFile` into files.

Four routes take uploads and each carried its own copy of the surrounding
choreography — the temp file, the off-loop copy, the cleanup, the batch loop
with its running total. The copies drifted in exactly the way copies do:

* `POST /api/hats/{id}/photo` created its temp file OUTSIDE the `try` whose
  `finally` deleted it, so every 413 from the size cap left a 20 MB file behind
  in the temp dir — on a Pi, the SD card `utils/disk.py` exists to watch. The
  logo route, written later, had the same steps in the right order.
* The bulk-import route and the share target ran the same batch loop with
  different staging names, and the share target's total cap could be deleted
  with the whole suite still green.

What differs between the routes is POLICY, so that is all a caller states.
The byte-level copy stays in `utils/upload.py`; this module only owns where the
bytes go and when they are cleaned up.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import HTTPException, UploadFile

from headroom.services import import_service
from headroom.utils import photo as photo_utils
from headroom.utils import upload as upload_utils

logger = logging.getLogger(__name__)


@asynccontextmanager
async def spooled_upload(upload: UploadFile, *, suffix: str, what: str) -> AsyncIterator[Path]:
    """One upload, capped, on disk for the duration of the block — then gone.

    The temp file is created and removed by the same `try`/`finally`, so no
    exit — the 413 from the cap, a decode failure, a disconnect — can leave it
    behind. The copy runs off the event loop: a 20 MB phone photo spooling
    onto an SD card is not instant.
    """
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        path = Path(tmp.name)
    try:
        with path.open("wb") as fh:
            await asyncio.to_thread(upload_utils.copy_upload_capped, upload, fh, what=what)
        yield path
    finally:
        path.unlink(missing_ok=True)


async def spool_batch(
    uploads: Sequence[UploadFile],
    staging: Path,
    *,
    strict: bool,
    default_name: str,
) -> list[tuple[str, Path]]:
    """Write each image upload into `staging`; return `(original name, path)` pairs.

    Bounded twice, per file (`import_service.MAX_BYTES_PER_FILE`, truncating —
    `create_job` records an oversize file as an errored item rather than
    rejecting its batch) and per batch (`import_service.MAX_TOTAL_UPLOAD_BYTES`).
    A per-file cap is not a cap: the share sheet will hand over a whole camera
    roll selection, and 100 x 20 MB is 2 GB on an SD card in one request.

    `strict` is the only policy difference between the two doors:

    * strict (the upload form) — a non-image or an over-total batch is the
      caller's mistake and answers 400 / 413 before anything is queued;
    * lenient (the Android share target, which cannot show an error page) —
      non-images are skipped and an over-total batch keeps its leading files.

    Staged under an index, never the client's filename: the name is recorded
    for display, not used as a path.
    """
    files: list[tuple[str, Path]] = []
    total = 0
    for index, upload in enumerate(uploads):
        if not photo_utils.validate_image_content_type(upload.content_type):
            if strict:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid content type for {upload.filename}: {upload.content_type}",
                )
            logger.info("Upload batch skipped a non-image: %s", upload.content_type)
            continue
        dest = staging / f"{index:04d}"
        with dest.open("wb") as out:
            written = await asyncio.to_thread(
                upload_utils.copy_upload_truncating, upload, out, import_service.MAX_BYTES_PER_FILE
            )
        total += written
        if total > import_service.MAX_TOTAL_UPLOAD_BYTES:
            dest.unlink(missing_ok=True)
            limit_mb = import_service.MAX_TOTAL_UPLOAD_BYTES // 1024 // 1024
            if strict:
                raise HTTPException(
                    status_code=413,
                    detail=(
                        f"Upload batch exceeds {limit_mb} MB in total — split it into "
                        "smaller batches."
                    ),
                )
            logger.warning(
                "Upload batch over %d MB — keeping the first %d file(s)", limit_mb, len(files)
            )
            break
        files.append((Path(upload.filename or default_name).name, dest))
    return files
