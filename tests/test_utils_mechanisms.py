"""`utils/` mechanisms that exist once, and have to work from the first call.

HEIC decoding used to be switched on inside `process_image`, so Pillow could
read an iPhone photo only after some hat photo had been processed in the same
process — a HEIC logo uploaded first after a restart was a 400, and the same
file a 200 a minute later. The other three are single definitions that used to
be two copies each: the WebP encoder, the upload read loop and the free-space
percentage.
"""

from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

import pillow_heif
import pytest
from PIL import Image

from headroom.utils import disk, photo, upload

pytestmark = pytest.mark.anyio


def _heic(path: Path) -> Path:
    # `from_pillow(...).save` encodes without touching Pillow's opener
    # registry, so writing the fixture proves nothing about reading it.
    pillow_heif.from_pillow(Image.new("RGB", (48, 32), (200, 30, 90))).save(path, quality=80)
    return path


async def test_a_fresh_process_decodes_heic_before_any_photo_is_processed(tmp_path):
    """In a new interpreter, with nothing but `utils.photo` imported: the
    state every restart leaves the app in."""
    heic = _heic(tmp_path / "logo.heic")
    probe = (
        "import sys\n"
        "from headroom.utils import photo\n"
        "with photo.decoded_image(__import__('pathlib').Path(sys.argv[1])) as img:\n"
        "    print(img.size)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe, str(heic)],
        env={
            "HEADROOM_DATABASE_URL": "sqlite+aiosqlite:////nonexistent/heic-probe.db",
            "PATH": "/usr/bin:/bin",
        },
        capture_output=True, text=True, timeout=120, check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    assert result.stdout.strip() == "(48, 32)"


async def test_a_heic_logo_uploads(client, tmp_path):
    heic = _heic(tmp_path / "logo.heic").read_bytes()
    resp = await client.post(
        "/api/settings/logo", files={"photo": ("logo.heic", heic, "image/heic")}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["logo_path"] == "branding/logo.png"


# ---- one WebP encoder --------------------------------------------------------- #


async def test_both_derivatives_go_through_the_one_encoder(monkeypatch, tmp_path):
    calls = []

    def _record(source, dest, **kwargs):
        calls.append(kwargs)
        return dest.with_suffix(".webp")

    monkeypatch.setattr(photo, "_encode_webp", _record)
    photo.make_thumbnail(tmp_path / "a.png", tmp_path / "t" / "a")
    photo.make_export_image(tmp_path / "a.png", tmp_path / "e" / "a")
    assert [(c["dimension"], c["quality"], c["method"]) for c in calls] == [
        (photo.THUMB_DIMENSION, 80, 4),
        (photo.EXPORT_DIMENSION, photo.EXPORT_QUALITY, 6),
    ]


async def test_the_encoder_keeps_alpha_and_bounds_the_size(tmp_path):
    src = tmp_path / "cutout.png"
    Image.new("RGBA", (1200, 600), (255, 0, 0, 0)).save(src)
    out = photo.make_export_image(src, tmp_path / "export" / "cutout")
    with Image.open(out) as img:
        assert img.format == "WEBP"
        assert max(img.size) == photo.EXPORT_DIMENSION
        assert img.mode == "RGBA"


# ---- one upload read loop ---------------------------------------------------- #


class _Upload:
    def __init__(self, data: bytes):
        self.file = io.BytesIO(data)


async def test_both_copiers_read_through_the_one_loop(monkeypatch):
    seen = []
    real = upload._chunks

    def _spy(u):
        seen.append(u)
        return real(u)

    monkeypatch.setattr(upload, "_chunks", _spy)
    upload.copy_upload_truncating(_Upload(b"x" * 10), io.BytesIO(), 100)
    upload.copy_upload_capped(_Upload(b"x" * 10), io.BytesIO(), cap=100)
    assert len(seen) == 2


async def test_the_loop_reports_a_running_total():
    chunks = list(upload._chunks(_Upload(b"x" * (upload._CHUNK + 5))))
    assert [total for _, total in chunks] == [upload._CHUNK, upload._CHUNK + 5]


# ---- one free-space percentage ----------------------------------------------- #


async def test_low_is_decided_on_the_unrounded_share(monkeypatch, tmp_path):
    """14.96% free under a 15% threshold is low. The card rounds it to 15.0
    for display; the decision must not."""
    from collections import namedtuple

    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(disk.shutil, "disk_usage", lambda _p: usage(10_000, 8_504, 1_496))
    monkeypatch.setenv("HEADROOM_DISK_WARN_PCT", "15")
    monkeypatch.setenv("HEADROOM_DISK_MIN_FREE_MB", "0")
    status = disk.check(tmp_path)
    assert status.free_pct == 15.0
    assert status.low is True
    assert disk.percent_free(0, 0) == 0.0
