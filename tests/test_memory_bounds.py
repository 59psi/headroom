"""The memory and concurrency bounds that keep this app inside a Pi.

conftest stubs `remove_background` out entirely — rembg's model is 179MB and
loading it per test run is not viable — and that stub is why an entire class of
bug was invisible to the suite. A real container death during a hat upload was
diagnosed from source rather than caught here, and every precondition
(uncapped decode, unbounded concurrent inference, no memory ceiling) had been
sitting in the code, green, for releases.

These test the bounds WITHOUT the model: the semaphore, the upload caps and the
spool-to-disk paths are all plain control flow, so a fake inference that simply
records how many callers are inside it at once exercises the thing that
actually failed. That is the part the stub was hiding — not the segmentation.
"""

from __future__ import annotations

import asyncio
import io

import pytest
from PIL import Image

from headroom.services import background_removal

pytestmark = pytest.mark.anyio

# conftest replaces `background_removal.remove_background` with a no-op for the
# whole suite — that stub is precisely what hid this class of bug. Capture the
# real coroutine at import, before the fixture swaps it, so these tests
# exercise the actual bound rather than the stand-in.
_REAL_REMOVE_BACKGROUND = background_removal.remove_background


@pytest.fixture(autouse=True)
def _reset_semaphore():
    """The bound is a module-global; don't let one test's value leak."""
    background_removal._inference_sem = None
    yield
    background_removal._inference_sem = None


def _jpeg(size=(80, 80)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (40, 90, 200)).save(buf, "JPEG")
    return buf.getvalue()


class _ConcurrencyProbe:
    """Stands in for the ONNX inference and records peak overlap."""

    def __init__(self) -> None:
        self.active = 0
        self.peak = 0

    def __call__(self, input_path, output_path):
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            # Long enough that a second caller would overlap if nothing stopped
            # it — the whole point is that something does.
            import time

            time.sleep(0.05)
        finally:
            self.active -= 1
        return output_path.with_suffix(".png")


async def test_inference_is_serialized_across_all_callers(monkeypatch, tmp_path):
    """Both workers reach this function and nothing else stops them colliding.

    A 179MB model plus a full-resolution decode, twice at once, on a 1GB Pi is
    the allocation that reaches the OOM killer. The lock was previously removed
    for throughput, which with two single-consumer producers bought a factor of
    at most two.
    """
    probe = _ConcurrencyProbe()
    monkeypatch.setattr(background_removal, "_remove_sync", probe)
    monkeypatch.setattr(background_removal, "_session", object())

    await asyncio.gather(*[
        _REAL_REMOVE_BACKGROUND(tmp_path / f"in{i}.jpg", tmp_path / f"out{i}")
        for i in range(4)
    ])

    assert probe.peak == 1, f"{probe.peak} inferences ran at once; the bound is 1"


async def test_the_bound_is_configurable(monkeypatch, tmp_path):
    """Real hardware should be able to use more of itself."""
    monkeypatch.setenv("HEADROOM_REMBG_CONCURRENCY", "3")
    probe = _ConcurrencyProbe()
    monkeypatch.setattr(background_removal, "_remove_sync", probe)
    monkeypatch.setattr(background_removal, "_session", object())

    await asyncio.gather(*[
        _REAL_REMOVE_BACKGROUND(tmp_path / f"in{i}.jpg", tmp_path / f"out{i}")
        for i in range(6)
    ])

    assert probe.peak > 1, "the env override did not raise the bound"
    assert probe.peak <= 3, f"{probe.peak} exceeded the configured ceiling of 3"


async def test_a_bad_concurrency_value_falls_back_rather_than_crashing(monkeypatch):
    """Config must never be able to take the app down at boot."""
    monkeypatch.setenv("HEADROOM_REMBG_CONCURRENCY", "not-a-number")
    assert background_removal._concurrency() >= 1

    monkeypatch.setenv("HEADROOM_REMBG_CONCURRENCY", "0")
    assert background_removal._concurrency() == 1, "zero would deadlock every upload"


async def test_oversize_hat_photo_is_refused_not_decoded(client, monkeypatch):
    """The exact route implicated in the crash, and the one with no cap at all.

    Rejected on the way in, so Pillow never decodes it — a cap enforced after
    the decode would protect nothing.
    """
    from headroom.utils import upload

    monkeypatch.setattr(upload, "MAX_PHOTO_BYTES", 2048)

    created = await client.post(
        "/api/hats", json={"condition": "new", "size": "classic", "style": "a_game"}
    )
    hat_id = created.json()["id"]

    big = b"\xff\xd8\xff" + b"\x00" * 8192
    resp = await client.post(
        f"/api/hats/{hat_id}/photo", files={"photo": ("big.jpg", big, "image/jpeg")}
    )

    assert resp.status_code == 413
    assert "limit" in resp.json()["detail"].lower()


async def test_the_logo_route_is_capped_too(client, monkeypatch):
    """Every single-file route, not just the one that crashed.

    Bulk import got this cap after an earlier review; its siblings were left
    uncapped, which is how the gap survived to become an incident. The case
    photo route was one of them and no longer exists — cases show a collage of
    their hats instead — so the remaining single-file uploads are the hat photo
    (covered above) and this one.
    """
    from headroom.utils import upload

    monkeypatch.setattr(upload, "MAX_PHOTO_BYTES", 2048)
    big = b"\xff\xd8\xff" + b"\x00" * 8192

    logo_resp = await client.post(
        "/api/settings/logo", files={"photo": ("big.png", big, "image/png")}
    )
    assert logo_resp.status_code == 413


async def test_a_photo_within_the_cap_still_works(client):
    """A cap that rejects real photos is worse than no cap."""
    created = await client.post(
        "/api/hats", json={"condition": "new", "size": "classic", "style": "a_game"}
    )
    hat_id = created.json()["id"]

    resp = await client.post(
        f"/api/hats/{hat_id}/photo", files={"photo": ("ok.jpg", _jpeg(), "image/jpeg")}
    )

    assert resp.status_code == 200
    assert resp.json()["photo_path"]


async def test_bulk_import_hands_the_worker_paths_not_bytes(client, monkeypatch):
    """Peak memory must be one file, not the batch.

    The route used to accumulate every blob in a list and check the total
    afterwards, so a full batch was resident at once — above the container's
    memory limit. Asserting on the type is asserting on the bound: bytes in
    this argument means the whole batch was held.
    """
    from pathlib import Path

    from headroom.services import import_service

    seen: list[tuple[str, object]] = []
    real_create = import_service.create_job

    async def spy(db, *, files, defaults=None):
        seen.extend(files)
        return await real_create(db, files=files, defaults=defaults)

    monkeypatch.setattr(import_service, "create_job", spy)

    resp = await client.post(
        "/api/hats/import",
        files=[
            ("photos", ("a.jpg", _jpeg(), "image/jpeg")),
            ("photos", ("b.jpg", _jpeg(), "image/jpeg")),
        ],
    )

    assert resp.status_code == 202
    assert len(seen) == 2
    for _name, payload in seen:
        assert isinstance(payload, Path), "the batch was buffered in memory"


async def test_upload_temp_files_are_not_left_behind(client):
    """An abandoned or rejected batch must not strand photos in temp space."""
    import tempfile
    from pathlib import Path

    before = {p.name for p in Path(tempfile.gettempdir()).glob("headroom-upload-*")}
    await client.post(
        "/api/hats/import",
        files=[("photos", ("a.jpg", _jpeg(), "image/jpeg"))],
    )
    after = {p.name for p in Path(tempfile.gettempdir()).glob("headroom-upload-*")}

    assert after == before


async def test_the_share_target_spools_to_disk_and_caps_each_file(client, monkeypatch):
    """The Android share target was BOTH unbounded and broken.

    It read whole files into memory (`await f.read()`) and handed `create_job`
    bytes — but `create_job` takes PATHS: it calls `source.stat()` and
    `shutil.copy2(source, ...)`, so every share raised AttributeError on the
    first file. Nothing covered the handler, so it stayed that way. CLAUDE.md
    meanwhile claimed "every upload route streams through `utils/upload.py`".
    """
    from headroom.utils import upload

    monkeypatch.setattr(upload, "MAX_PHOTO_BYTES", 2048)
    # Since 2.57.2 the route spools with the SHARED helper and caps on the
    # import service's own per-file limit, so there is one number to pin here
    # rather than a route-local copy of it.
    monkeypatch.setattr("headroom.services.import_service.MAX_BYTES_PER_FILE", 2048)

    small = b"\xff\xd8\xff" + b"\x00" * 128
    big = b"\xff\xd8\xff" + b"\x00" * 8192

    resp = await client.post(
        "/share",
        files=[
            ("photos", ("ok.jpg", small, "image/jpeg")),
            ("photos", ("huge.jpg", big, "image/jpeg")),
            ("photos", ("notes.txt", b"nope", "text/plain")),
        ],
        follow_redirects=False,
    )
    # A redirect at all means it did not blow up on the first file.
    assert resp.status_code == 303, resp.text
    assert "/hats/import?job=" in resp.headers["location"]

    job_id = int(resp.headers["location"].split("job=")[1])
    job = (await client.get(f"/api/hats/import/{job_id}")).json()
    names = {i["filename"]: i["status"] for i in job["items"]}
    assert names.get("ok.jpg") == "queued"
    # Oversize is recorded, not silently dropped and not fatal to the batch.
    assert names.get("huge.jpg") == "error"
    # The non-image never became an item at all.
    assert "notes.txt" not in names


async def test_share_target_with_no_usable_files_redirects_instead_of_failing(client):
    resp = await client.post(
        "/share",
        files=[("photos", ("notes.txt", b"nope", "text/plain"))],
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/hats/import"
