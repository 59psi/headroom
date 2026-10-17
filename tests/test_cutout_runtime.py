"""Cutouts on the runtime the image actually ships: a read-only venv.

From 2.79.0 to 2.83.1 every cutout failed in the container. rembg imports
pymatting, whose numba kernels compile at import with `cache=True`; numba
writes that cache beside the source, the venv became root-owned on a
read-only root filesystem, and numba then raises rather than compile
uncached. The pipeline treated it as the documented degrade — keep the JPEG —
logged one WARNING per photo, and reported the analysis `ok`. Nothing else
said so for six weeks.

The suite stubs rembg out (conftest), so these test what surrounds it: that
a failure is loud, that boot says up front whether cutouts can run, and that
the image gives numba somewhere to write. CI's docker job runs a real cutout
under the production constraints, which is the half a unit test cannot.
"""

from __future__ import annotations

import logging

import pytest

from headroom.services import background_removal

pytestmark = pytest.mark.anyio

# conftest replaces `remove_background` for the whole suite; keep the real one.
_REAL_REMOVE_BACKGROUND = background_removal.remove_background

_NUMBA_ERROR = (
    "cannot cache function '_make_tree': no locator available for file "
    "'/opt/venv/lib/python3.14/site-packages/pymatting/util/kdtree.py'"
)


def _raise_numba():
    raise RuntimeError(_NUMBA_ERROR)


async def test_warm_up_reports_a_broken_import_as_an_error(monkeypatch, caplog):
    monkeypatch.setattr(background_removal, "_import_rembg", _raise_numba)

    with caplog.at_level(logging.INFO, logger=background_removal.__name__):
        assert await background_removal.warm_up() is False

    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors, "a cutout runtime that cannot load must be an ERROR at boot"
    assert "no locator available" in errors[0].getMessage()


async def test_warm_up_says_when_cutouts_are_ready(monkeypatch, caplog):
    calls = []
    monkeypatch.setattr(background_removal, "_import_rembg", lambda: calls.append(1))

    with caplog.at_level(logging.INFO, logger=background_removal.__name__):
        assert await background_removal.warm_up() is True

    assert calls == [1], "warm_up must perform the import, not just report"
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


async def test_a_failed_cutout_is_logged_as_an_error(monkeypatch, tmp_path, caplog):
    """The photo is kept and the analysis still says `ok`, so this log line is
    the only record that the hat has no cutout. At WARNING it read as noise."""
    monkeypatch.setattr(background_removal, "_session", object())

    def _broken(_input, _output):
        raise RuntimeError(_NUMBA_ERROR)

    monkeypatch.setattr(background_removal, "_remove_sync", _broken)

    with caplog.at_level(logging.WARNING, logger=background_removal.__name__):
        result = await _REAL_REMOVE_BACKGROUND(tmp_path / "in.jpg", tmp_path / "out")

    assert result is None, "a failed cut must still degrade, never crash the upload"
    assert [r.levelno for r in caplog.records] == [logging.ERROR]
