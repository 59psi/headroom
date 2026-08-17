"""Bounded reads of uploaded files.

Every upload route needs the same guarantee: a client cannot make this process
allocate an unbounded amount of memory or disk. The bulk-import route grew its
own version of this after a review; the three single-file photo routes never
got one, which mattered because what follows an upload here is a full-resolution
Pillow decode and a resident ~179 MB rembg model on a Raspberry Pi with no
container memory limit. One oversized photo is enough to reach the OOM killer,
and the kernel kills the process without giving the app a chance to log why.

So: one definition, used by all four.
"""

from __future__ import annotations

from typing import BinaryIO

from fastapi import HTTPException, UploadFile

# Generous next to a phone photo (a 12MP HEIC is ~3-5 MB) and small enough that
# the decode that follows stays bounded on a 1 GB Pi.
MAX_PHOTO_BYTES = 20 * 1024 * 1024

_CHUNK = 1024 * 1024


async def read_capped(upload: UploadFile, cap: int) -> bytes:
    """Read an upload in chunks, stopping just past `cap` bytes.

    A file larger than the limit comes back at ~cap+1 rather than fully
    resident, so a caller can still detect it as oversize (`len > cap`) without
    a single huge file ballooning memory. Lenient by design: the bulk-import
    worker records oversize items as skipped rather than failing the batch.
    """
    chunks: list[bytes] = []
    size = 0
    while True:
        chunk = await upload.read(_CHUNK)
        if not chunk:
            break
        chunks.append(chunk)
        size += len(chunk)
        if size > cap:
            break
    return b"".join(chunks)


def copy_upload_capped(
    upload: UploadFile,
    dest: BinaryIO,
    cap: int | None = None,
    what: str = "Photo",
) -> int:
    """Stream an upload to `dest`, aborting with 413 past `cap`. Returns bytes written.

    `cap=None` means "the module default", read at CALL time. A default of
    `cap: int = MAX_PHOTO_BYTES` would bind the value when this function is
    defined, so the limit could never be changed afterwards — which also makes
    it untestable, and an untestable limit is how the last one went missing.

    Streams rather than reading into memory, because the destination is a temp
    file and buffering the whole thing first would reintroduce the exact
    allocation this exists to prevent. Strict rather than lenient — a single
    named upload that is too big is a request to reject, not a batch item to
    skip.
    """
    limit = MAX_PHOTO_BYTES if cap is None else cap
    written = 0
    while True:
        chunk = upload.file.read(_CHUNK)
        if not chunk:
            break
        written += len(chunk)
        if written > limit:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"{what} exceeds the {limit // 1024 // 1024} MB limit. "
                    "Try a smaller image."
                ),
            )
        dest.write(chunk)
    return written
