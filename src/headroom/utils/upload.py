"""Bounded reads of uploaded files.

Every upload route needs the same guarantee: a client cannot make this process
allocate an unbounded amount of memory or disk. The bulk-import route grew its
own version of this after a review; the single-file photo routes never got one,
which mattered because what follows an upload here is a full-resolution Pillow
decode and a resident ~179 MB rembg model on a Raspberry Pi with a 1g limit.
One oversized photo is enough to reach the OOM killer, and the kernel kills the
process without giving the app a chance to log why.

Two functions, differing only in what they do when the cap is hit — 413 for a
single named file, truncate for one item in a batch — over ONE read loop
(`_chunks`), and ONE caller: `routes/_uploads.py`. Its `spooled_upload` spools
a single file through `copy_upload_capped`, and its `spool_batch` spools a
batch through `copy_upload_truncating`; the four upload routes (`hats`,
`settings`, `import_jobs`, `share`) go through those two and never read an
upload themselves.

A sentence here used to COUNT call sites, and was wrong for a long time: it
read "one definition, used by all four" while `import_jobs` and `share` each
carried a private copy of the same loop; every copy was individually correct,
so nothing ever failed and only this docstring was false. It then survived
the routes moving onto `_uploads.py`, still naming four callers that no
longer called here. `tests/test_upload_caps.py` asserts the call path rather
than trusting a sentence.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import BinaryIO

from fastapi import HTTPException, UploadFile

# Generous next to a phone photo (a 12MP HEIC is ~3-5 MB) and small enough that
# the decode that follows stays bounded on a 1 GB Pi. The ONE per-photo cap:
# bulk import's per-file limit is this number, not a second 20 MB that could
# drift from it, and `tests/test_documented_limits.py` pins it to USAGE.md.
MAX_PHOTO_BYTES = 20 * 1024 * 1024

_CHUNK = 1024 * 1024


def _chunks(upload: UploadFile) -> Iterator[tuple[bytes, int]]:
    """Each chunk of the upload with the running total INCLUDING it.

    The one read loop. The two copiers below differ only in what they do when
    the total passes the cap — and each used to carry its own copy of this
    loop, in a module whose point is "one definition".
    """
    total = 0
    while chunk := upload.file.read(_CHUNK):
        total += len(chunk)
        yield chunk, total


def copy_upload_truncating(upload: UploadFile, dest: BinaryIO, cap: int) -> int:
    """Stream an upload to `dest`, stopping just past `cap`. Returns bytes written.

    The LENIENT half of this module, for bulk import: one oversize photo in a
    batch of sixty is an item to record and move past, not a reason to reject
    the other fifty-nine. Its caller detects the truncation as `written > cap`.

    Streams to `dest` rather than returning bytes. There used to be a
    `read_capped` here that accumulated chunks into memory and returned them,
    and it was the version this module's docstring described — but the import
    route never called it: it carried a private copy that spooled to disk
    instead, which is strictly better (a batch upload never holds a photo in
    RAM) and left `read_capped` reachable only from its own tests. Promoted the
    copy, deleted the original; "one definition, used by all" is true again.

    Writes the chunk that crosses `cap` before stopping, so the return value
    (and the file) are strictly greater than `cap` — the signal the caller
    reads.
    """
    written = 0
    for chunk, written in _chunks(upload):
        dest.write(chunk)
        if written > cap:
            break
    return written


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
    for chunk, written in _chunks(upload):
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
