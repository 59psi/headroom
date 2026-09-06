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


@pytest.fixture(autouse=True)
def _fresh_progress(monkeypatch):
    """`repricing.progress` and `catalog_service.progress` are module globals
    that several tests below drive to a failed state and leave there — `error`
    deliberately outlives `finish()`, so without this the failure of one test
    was visible to the next module's status assertions."""
    from headroom.services import catalog_service, repricing

    monkeypatch.setattr(repricing, "progress", sweep_progress.SweepProgress())
    monkeypatch.setattr(catalog_service, "progress", sweep_progress.SweepProgress())


async def test_a_fresh_sweep_reports_itself_idle():
    p = sweep_progress.SweepProgress()
    snap = p.snapshot()
    assert snap["running"] is False
    assert snap["done"] == 0 and snap["total"] == 0
    assert snap["pct"] == 0, "no division by zero on an untouched record"


async def test_progress_advances_and_names_what_it_is_on():
    """A bare count says the sweep is alive; the label says it is not wedged."""
    p = sweep_progress.SweepProgress()
    p.begin(4)
    assert p.snapshot()["running"] is True

    p.advance("Odysea Rope Hydro")
    snap = p.snapshot()
    assert (snap["done"], snap["total"], snap["pct"]) == (1, 4, 25)
    assert snap["label"] == "Odysea Rope Hydro"


async def test_finishing_clears_running_and_the_label():
    p = sweep_progress.SweepProgress()
    p.begin(2)
    p.advance("a")
    p.finish()
    snap = p.snapshot()
    assert snap["running"] is False
    assert snap["label"] is None, "nothing is being worked on once it has stopped"
    assert snap["finished_at"] is not None


async def test_an_error_outlives_the_run_that_produced_it():
    """The record has to be readable AFTER the thing stops — that is the point."""
    p = sweep_progress.SweepProgress()
    p.begin(1)
    p.finish(error="Melin Recap query 429")
    snap = p.snapshot()
    assert snap["running"] is False
    assert snap["error"] == "Melin Recap query 429"


async def test_a_new_run_clears_the_previous_error_but_finishing_does_not():
    """Cleared on START, so a failure stays visible until something supersedes
    it. Clearing on finish would erase the failure at the moment it happened."""
    p = sweep_progress.SweepProgress()
    p.begin(1)
    p.finish(error="boom")
    p.finish()  # a second finish must not wipe it
    assert p.snapshot()["error"] == "boom"

    p.begin(1)
    assert p.snapshot()["error"] is None


async def test_progress_never_exceeds_its_total():
    """A bar reading 241/235 reads as a bug in the thing being measured."""
    p = sweep_progress.SweepProgress()
    p.begin(2)
    for _ in range(5):
        p.advance()
    snap = p.snapshot()
    assert snap["done"] == 2
    assert snap["pct"] == 100


async def test_a_unit_is_named_before_it_starts_and_counted_after_it_ends():
    """Naming and counting are two events. `advance(label)` did both, and every
    caller called it BEFORE the unit's work — so the bar read 100% for the whole
    last category, and "3 of 12 · Odysea" meant Odysea had not started."""
    p = sweep_progress.SweepProgress()
    p.begin(2)
    p.start_unit("aGame")
    snap = p.snapshot()
    assert snap["done"] == 0 and snap["label"] == "aGame", "named, not yet counted"
    p.advance()
    p.start_unit("odysea")
    snap = p.snapshot()
    assert snap["done"] == 1 and snap["label"] == "odysea"
    assert snap["pct"] == 50, "the last unit is in flight, not finished"
    p.advance()
    assert p.snapshot()["done"] == 2


async def test_the_repricing_sweep_counts_a_hat_only_once_it_is_done(client, db_session, monkeypatch):
    """Through the real loop: the progress seen DURING the last hat's marketplace
    call is one short of the total, with that hat named."""
    from headroom.models.hat import Hat
    from headroom.services import repricing

    for _ in range(2):
        await client.post("/api/hats", json={"condition": "new", "size": "classic", "style": "a_game"})
    hats = (await db_session.execute(__import__("sqlalchemy").select(Hat))).scalars().all()
    for h in hats:
        h.brand = "melin"
        h.model_name = "A-Game Hydro"
    await db_session.commit()

    seen: list[tuple[int, str | None]] = []

    async def _observe(hat):
        snap = repricing.progress.snapshot()
        seen.append((snap["done"], snap["label"]))

    monkeypatch.setattr(
        "headroom.services.hat_analysis_pipeline.refresh_melin_resale", _observe
    )
    repricing.progress.begin(len(hats))
    await repricing._sweep(db_session, hats, delay=0)
    repricing.progress.finish()

    assert [d for d, _ in seen] == [0, 1], "counted after each hat, not before"
    assert all(label == "A-Game Hydro" for _, label in seen), "named while in flight"


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

    monkeypatch.setattr(repricing, "_eligible_hats", lambda db, limit=None, **kw: _noop())

    async def _noop():
        return []

    with pytest.raises(RuntimeError):
        await repricing.reprice_once(session_factory=_Factory())

    snap = repricing.progress.snapshot()
    assert snap["running"] is False, (
        "try/finally, not a happy-path call at the bottom of the loop"
    )
    # The first version of this only asserted `running`, and passed against a
    # bare `finally: finish()` that could never set `error` — so a crashed
    # sweep reported `running: false, error: null`, byte-identical to a clean
    # one, while the UI carried an unreachable failure branch and two frontend
    # tests mocked a state the server could not emit.
    assert snap["error"] is not None, "a failed sweep must SAY it failed"
    assert "mid-sweep failure" in snap["error"]


async def test_a_failed_harvest_records_why(monkeypatch):
    """Same defect, other sweep. This one runs behind a 202 with nobody
    watching, so an unrecorded failure renders as an idle card — the exact
    "dead button" state the module exists to distinguish."""
    from headroom.services import catalog_service

    async def _explode(db, now):
        raise RuntimeError("Melin Recap query 429")

    monkeypatch.setattr(catalog_service, "_harvest", _explode)

    with pytest.raises(RuntimeError):
        await catalog_service.harvest_catalog(None)

    snap = catalog_service.progress.snapshot()
    assert snap["running"] is False
    assert snap["error"] == "Melin Recap query 429"


async def test_a_canceled_sweep_does_not_stay_running_forever(monkeypatch):
    """`except Exception` is not enough: CancelledError is a BaseException.

    "Re-price now" is a ~50s blocking POST, so a phone disconnecting mid-sweep
    cancels the task — and the version that shipped left `running` true
    permanently, with the card polling a phantom sweep every 2s. That is the
    exact false signal this record exists to remove, reintroduced by replacing
    `try/finally` with `try/except Exception`.
    """
    import asyncio

    from headroom.services import repricing

    async def _hang(db, hats, delay):
        await asyncio.sleep(30)

    async def _three(db, limit=None, **kw):
        return [1, 2, 3]

    monkeypatch.setattr(repricing, "_sweep", _hang)
    monkeypatch.setattr(repricing, "_eligible_hats", _three)

    class _Factory:
        def __call__(self):
            return self

        async def __aenter__(self):
            return None

        async def __aexit__(self, *exc):
            return False

    task = asyncio.create_task(repricing.reprice_once(session_factory=_Factory()))
    await asyncio.sleep(0.05)
    assert repricing.progress.snapshot()["running"] is True

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert repricing.progress.snapshot()["running"] is False, (
        "a canceled sweep must not report itself as still in flight"
    )
