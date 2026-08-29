"""Live progress for the sweeps behind "Re-price now" and the colorway refresh.

Both buttons start minutes of sequential external calls and neither could say
what it was doing. The harvest was the worse of the two: it returns 202 and
runs in the background, so its only trace was a log line — from the Settings
page a working harvest and a dead button looked identical.
"""

from __future__ import annotations

import pytest

from headroom.services import sweep_progress

pytestmark = pytest.mark.anyio


async def test_a_fresh_sweep_reports_itself_idle():
    p = sweep_progress.new("x")
    snap = p.snapshot()
    assert snap["running"] is False
    assert snap["done"] == 0 and snap["total"] == 0
    assert snap["pct"] == 0, "no division by zero on an untouched record"


async def test_progress_advances_and_names_what_it_is_on():
    """A bare count says the sweep is alive; the label says it is not wedged."""
    p = sweep_progress.new("x")
    p.begin(4)
    assert p.snapshot()["running"] is True

    p.advance("Odysea Rope Hydro")
    snap = p.snapshot()
    assert (snap["done"], snap["total"], snap["pct"]) == (1, 4, 25)
    assert snap["label"] == "Odysea Rope Hydro"


async def test_finishing_clears_running_and_the_label():
    p = sweep_progress.new("x")
    p.begin(2)
    p.advance("a")
    p.finish()
    snap = p.snapshot()
    assert snap["running"] is False
    assert snap["label"] is None, "nothing is being worked on once it has stopped"
    assert snap["finished_at"] is not None


async def test_an_error_outlives_the_run_that_produced_it():
    """The record has to be readable AFTER the thing stops — that is the point."""
    p = sweep_progress.new("x")
    p.begin(1)
    p.finish(error="Melin Recap query 429")
    snap = p.snapshot()
    assert snap["running"] is False
    assert snap["error"] == "Melin Recap query 429"


async def test_a_new_run_clears_the_previous_error_but_finishing_does_not():
    """Cleared on START, so a failure stays visible until something supersedes
    it. Clearing on finish would erase the failure at the moment it happened."""
    p = sweep_progress.new("x")
    p.begin(1)
    p.finish(error="boom")
    p.finish()  # a second finish must not wipe it
    assert p.snapshot()["error"] == "boom"

    p.begin(1)
    assert p.snapshot()["error"] is None


async def test_progress_never_exceeds_its_total():
    """A bar reading 241/235 reads as a bug in the thing being measured."""
    p = sweep_progress.new("x")
    p.begin(2)
    for _ in range(5):
        p.advance()
    snap = p.snapshot()
    assert snap["done"] == 2
    assert snap["pct"] == 100


async def test_repricing_exposes_progress_through_its_status(client):
    """The card reads this endpoint; a field it cannot see does not exist."""
    body = (await client.get("/api/admin/repricing")).json()
    assert "progress" in body
    assert body["progress"]["running"] is False


async def test_the_colorway_status_carries_harvest_progress(client):
    """The refresh returns 202, so this endpoint is the ONLY way to tell a
    running harvest from a button that did nothing."""
    body = (await client.get("/api/admin/colorways/status")).json()
    assert "progress" in body
    assert body["progress"]["running"] is False


async def test_a_sweep_that_raises_does_not_stay_running_forever(monkeypatch):
    """The failure mode this guards: `running` stuck true reads as permanently
    in flight, which is the exact false signal the record exists to remove."""
    from headroom.services import repricing

    async def _explode(db, hats, delay):
        raise RuntimeError("mid-sweep failure")

    monkeypatch.setattr(repricing, "_sweep", _explode)

    class _Factory:
        def __call__(self):
            return self

        async def __aenter__(self):
            return None

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(repricing, "_eligible_hats", lambda db, limit=None: _noop())

    async def _noop():
        return []

    with pytest.raises(RuntimeError):
        await repricing.reprice_once(session_factory=_Factory())

    assert repricing.progress.snapshot()["running"] is False, (
        "try/finally, not a happy-path call at the bottom of the loop"
    )
