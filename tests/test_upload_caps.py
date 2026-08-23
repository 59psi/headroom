"""The upload size caps — a security control that nothing exercised.

`utils/upload.py` sat at 62%, and the uncovered lines were the body of
`copy_upload_capped`: the chunk loop and the 413. Its own docstring says an
untestable limit "is how the last one went missing", which was true and was
still not being tested.

What it protects is specific. What follows an upload here is a full-resolution
Pillow decode plus a resident ~179 MB rembg model in a 1 GB container, so one
oversized photo reaches the OOM killer — and the kernel kills the process
without letting the app log why.
"""

from __future__ import annotations

import io

import pytest
from fastapi import HTTPException, UploadFile

from headroom.utils import upload as up

pytestmark = pytest.mark.anyio


def _upload(data: bytes, name: str = "hat.jpg") -> UploadFile:
    return UploadFile(filename=name, file=io.BytesIO(data))


# ---- copy_upload_capped (strict, 413) --------------------------------- #


async def test_a_file_under_the_cap_is_written_whole():
    payload = b"x" * 4096
    dest = io.BytesIO()

    written = up.copy_upload_capped(_upload(payload), dest, cap=8192)

    assert written == len(payload)
    assert dest.getvalue() == payload


async def test_a_file_over_the_cap_is_refused_with_413():
    dest = io.BytesIO()

    with pytest.raises(HTTPException) as excinfo:
        up.copy_upload_capped(_upload(b"x" * 5000), dest, cap=1024)

    assert excinfo.value.status_code == 413


async def test_the_413_says_the_limit_in_megabytes_and_what_to_do():
    """A cap the user cannot see is a cap they cannot work around."""
    dest = io.BytesIO()

    with pytest.raises(HTTPException) as excinfo:
        up.copy_upload_capped(
            _upload(b"x" * (3 * 1024 * 1024)), dest, cap=2 * 1024 * 1024, what="Logo"
        )

    detail = excinfo.value.detail
    assert "Logo" in detail
    assert "2 MB" in detail
    assert "smaller" in detail


async def test_the_cap_is_read_at_call_time_not_at_definition():
    """`cap=None` means "the module default", resolved when called.

    Writing it as `cap: int = MAX_PHOTO_BYTES` would bind the value at import,
    so the limit could never be changed afterwards — and, as the docstring
    notes, an untestable limit is how the previous one went missing.
    """
    dest = io.BytesIO()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(up, "MAX_PHOTO_BYTES", 64)
        with pytest.raises(HTTPException) as excinfo:
            up.copy_upload_capped(_upload(b"x" * 512), dest)

    assert excinfo.value.status_code == 413


async def test_an_empty_upload_is_allowed_and_writes_nothing():
    """Zero bytes is a malformed upload for a ROUTE to reject, not a cap
    violation — conflating the two would give a confusing 413."""
    dest = io.BytesIO()

    assert up.copy_upload_capped(_upload(b""), dest, cap=1024) == 0
    assert dest.getvalue() == b""


async def test_nothing_past_the_limit_reaches_the_destination():
    """The point is bounded RESOURCE USE, not just a bounded return value.

    A version that wrote every chunk and checked the total afterwards would
    pass a naive assertion on the exception while still having spooled the
    whole oversize file to disk.
    """
    dest = io.BytesIO()

    with pytest.raises(HTTPException):
        up.copy_upload_capped(_upload(b"x" * (4 * up._CHUNK)), dest, cap=up._CHUNK)

    assert len(dest.getvalue()) <= up._CHUNK


# ---- read_capped (lenient, for bulk import) --------------------------- #


async def test_read_capped_returns_a_short_file_intact():
    payload = b"y" * 2048

    assert await up.read_capped(_upload(payload), 8192) == payload


async def test_read_capped_stops_just_past_the_cap():
    """Lenient by design — the bulk worker records oversize items as skipped
    rather than failing the whole batch — but it must still stop reading.

    The contract is "detectable as oversize without becoming resident": the
    caller checks `len > cap`, so it needs at least cap+1 bytes and nothing
    like the whole file.
    """
    cap = up._CHUNK
    data = b"z" * (6 * cap)

    got = await up.read_capped(_upload(data), cap)

    assert len(got) > cap, "caller could not detect this as oversize"
    assert len(got) < len(data), "the whole oversize file was read into memory"


async def test_the_two_helpers_disagree_on_purpose():
    """One raises, one returns. That asymmetry is the design, not an accident.

    A single named upload that is too big is a request to REJECT; one item in
    a hundred-file batch is an item to skip. Collapsing them would make bulk
    import fail entirely on one bad photo.
    """
    dest = io.BytesIO()

    with pytest.raises(HTTPException):
        up.copy_upload_capped(_upload(b"a" * 4096), dest, cap=16)

    assert await up.read_capped(_upload(b"a" * 4096), 16)  # no raise


# ---- the route that uses it ------------------------------------------- #


async def test_an_oversize_hat_photo_gets_a_413_from_the_api(client, monkeypatch):
    """End to end, because the cap only matters where it is wired in."""
    monkeypatch.setattr(up, "MAX_PHOTO_BYTES", 1024)
    hat_id = (await client.post("/api/hats", json={
        "condition": "new", "size": "classic", "style": "a_game",
    })).json()["id"]

    resp = await client.post(
        f"/api/hats/{hat_id}/photo",
        files={"photo": ("big.jpg", io.BytesIO(b"x" * 8192), "image/jpeg")},
    )

    assert resp.status_code == 413
