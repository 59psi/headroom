"""Periodic re-pricing — the sweep that keeps appraisals current.

Before this existed, `refresh_melin_resale` was reachable only from inside the
analysis pipeline, so a hat's value moved only when that hat was ANALYZED. On
the real deployment every appraisal sat frozen at the date of the last bulk
re-analysis, and the only way to move them was to re-analyze the collection —
a Claude vision call per hat to fetch a marketplace median that needs no Claude.

The coupling also chained two unrelated failures: when the Anthropic balance
ran out, Claude raised, the pipeline fell back and returned, and the price
refresh below it never ran. Prices stopped because identification stopped.

Nothing here touches the network: `refresh_melin_resale` is stubbed at the
module the sweep imports it from.
"""

from __future__ import annotations

from datetime import datetime, timezone

import asyncio
import contextlib

import pytest

from headroom.models.hat import Hat
from headroom.services import repricing

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _fresh_health():
    repricing._health = repricing.RepricingHealth()
    yield
    repricing._health = repricing.RepricingHealth()


@pytest.fixture(autouse=True)
def _no_pacing(monkeypatch):
    """The inter-hat delay is real behavior, not something to sit through."""
    monkeypatch.setattr(repricing, "repricing_delay_seconds", lambda: 0.0)


@pytest.fixture(autouse=True)
async def _free_slot():
    """No sweep — and no claim — may outlive the test that started it.

    Two module globals leak across tests here. The claim is one: it is a plain
    bool, so a test that leaves it held makes every later one see a sweep in
    flight and refuse, which reads as a failure in whatever ran next rather
    than in whatever leaked.

    The task is the other, and it arrived with `create_task`. `/repricing/run-all`
    no longer runs inside the request, so a sweep can still be mid-flight when
    the test returns — and `setup_db` drops every table on teardown, leaving a
    detached coroutine querying a schema that no longer exists. It would fail
    into `record_failure` and be swallowed, surfacing later as an unrelated
    flake. Awaiting them here is what makes that impossible rather than
    unlikely.
    """
    repricing.release_full_sweep()
    yield
    from headroom.routes.admin import repricing as repricing_routes

    for task in list(repricing_routes._running_sweeps):
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
    repricing.release_full_sweep()


async def _drain_sweeps():
    """Await every in-flight background sweep, deterministically.

    Polling `full_sweep_in_flight()` with `await asyncio.sleep(0)` is NOT a
    wait. It yields to the event loop and runs whatever is already ready, but it
    does not wait for I/O — and a sweep sitting on an aiosqlite worker thread is
    exactly that. The poll burns its whole iteration budget in microseconds and
    reports the sweep unfinished. It passed on a fast local machine and failed
    in CI, which is the signature of a timing assumption rather than a wait.

    `create_task` hands back the task, so there is nothing to poll for: await it.
    """
    from headroom.routes.admin import repricing as repricing_routes

    for task in list(repricing_routes._running_sweeps):
        # Bounded, so a sweep that genuinely wedges fails here with a timeout
        # instead of hanging until the CI job is killed with no useful output.
        await asyncio.wait_for(task, timeout=30)


def _factory(session):
    """Hand `reprice_once` the test session without closing it."""
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _f():
        yield session

    return _f


def _hat(**over) -> Hat:
    fields = dict(
        brand="melin", model_name="Odysea Hydro", style="cap",
        condition="excellent", size="classic",
    )
    fields.update(over)
    return Hat(**fields)


async def test_manual_prices_are_never_swept(db_session):
    """An owner's own number outranks a scraped median.

    `refresh_melin_resale` already refuses to overwrite one. Excluding it from
    the QUERY as well is what makes a protected hat cost no API call at all —
    on a collection where most prices are hand-entered, the difference is the
    whole sweep.
    """
    db_session.add(_hat(resale_price_scope="manual", resale_price=120.0))
    db_session.add(_hat(resale_price_scope="model", resale_price=80.0))
    db_session.add(_hat(resale_price_scope=None))
    await db_session.commit()

    eligible = await repricing._eligible_hats(db_session)
    scopes = sorted(str(h.resale_price_scope) for h in eligible)
    assert scopes == ["None", "model"], scopes


async def test_disposed_hats_are_never_swept(db_session):
    """They have left the collection; re-pricing them is work for nobody."""
    db_session.add(_hat(disposed_at=datetime.now(timezone.utc)))
    db_session.add(_hat())
    await db_session.commit()

    eligible = await repricing._eligible_hats(db_session)
    assert len(eligible) == 1
    assert eligible[0].disposed_at is None


async def test_stalest_prices_are_swept_first(db_session):
    """A sweep cut short by a restart or a batch cap must still make progress.

    Oldest-checked-first means the hats that have gone longest without a price
    are the ones a partial run reaches. Newest-first would re-do the freshest
    prices forever and never reach the stale tail.
    """
    old = _hat(model_name="Old", resale_checked_at=datetime(2026, 1, 1))
    recent = _hat(model_name="Recent", resale_checked_at=datetime(2026, 8, 1))
    never = _hat(model_name="Never", resale_checked_at=None)
    for h in (recent, old, never):
        db_session.add(h)
    await db_session.commit()

    order = [h.model_name for h in await repricing._eligible_hats(db_session)]
    assert order[0] == "Never", order  # nulls first — never priced is stalest
    assert order.index("Old") < order.index("Recent"), order


async def test_a_sweep_counts_prices_that_CHANGED_not_hats_visited(
    client, db_session, monkeypatch
):
    """A sweep that checks 234 hats and moves none is a working sweep.

    Reporting the visit count would make a flat market look like busy work, and
    (worse) would look identical to a sweep that is silently failing to write.
    """
    from headroom.services import hat_analysis_pipeline

    db_session.add(_hat(model_name="Moves", resale_price=50.0))
    db_session.add(_hat(model_name="Stays", resale_price=50.0))
    await db_session.commit()

    async def fake_refresh(hat):
        if hat.model_name == "Moves":
            hat.resale_price = 99.0

    monkeypatch.setattr(hat_analysis_pipeline, "refresh_melin_resale", fake_refresh)

    resp = await client.post("/api/admin/repricing/run")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["considered"] == 2, body
    assert body["repriced"] == 1, body


async def test_one_unreachable_listing_does_not_stop_the_sweep(
    client, db_session, monkeypatch
):
    """Best-effort per hat, like every other outward call in this app."""
    from headroom.services import hat_analysis_pipeline

    db_session.add(_hat(model_name="Boom", resale_price=10.0))
    db_session.add(_hat(model_name="Fine", resale_price=10.0))
    await db_session.commit()

    async def fake_refresh(hat):
        if hat.model_name == "Boom":
            raise RuntimeError("marketplace unreachable")
        hat.resale_price = 42.0

    monkeypatch.setattr(hat_analysis_pipeline, "refresh_melin_resale", fake_refresh)

    body = (await client.post("/api/admin/repricing/run")).json()
    assert body["considered"] == 2, body
    assert body["repriced"] == 1, body


async def test_status_reports_the_last_sweep(client, db_session, monkeypatch):
    """A list of prices cannot distinguish "nothing changed" from "nothing ran"."""
    from headroom.services import hat_analysis_pipeline

    db_session.add(_hat(resale_price=10.0))
    await db_session.commit()

    async def fake_refresh(hat):
        hat.resale_price = 77.0

    monkeypatch.setattr(hat_analysis_pipeline, "refresh_melin_resale", fake_refresh)

    before = (await client.get("/api/admin/repricing")).json()
    assert before["last_success_at"] is None
    # conftest disables the scheduler suite-wide; the manual run must work anyway,
    # because turning the background task off should not remove the ability to
    # refresh prices on purpose.
    assert before["enabled"] is False

    await client.post("/api/admin/repricing/run")

    after = (await client.get("/api/admin/repricing")).json()
    assert after["last_success_at"] is not None
    assert after["last_repriced"] == 1
    assert after["consecutive_failures"] == 0


async def test_repricing_status_requires_auth(anon_client):
    assert (await anon_client.get("/api/admin/repricing")).status_code == 401
    assert (await anon_client.post("/api/admin/repricing/run")).status_code == 401


async def test_the_scheduler_does_not_start_when_disabled(monkeypatch):
    monkeypatch.setenv("HEADROOM_REPRICING_ENABLED", "false")
    assert await repricing.start_repricing() is None


async def test_repricing_is_independent_of_analysis(db_session):
    """The point of the whole module.

    A hat whose analysis failed — no key, expired balance, unreadable photo —
    is still perfectly re-priceable: the marketplace lookup keys on style,
    model_name, condition and size, all of which are already in the database.
    """
    db_session.add(_hat(analysis_status="fallback", analysis_error="credit balance too low"))
    await db_session.commit()

    eligible = await repricing._eligible_hats(db_session)
    assert len(eligible) == 1
    assert eligible[0].analysis_status == "fallback"


# ---- what the adversarial review caught -------------------------------- #


async def test_a_manual_run_does_not_clear_a_standing_scheduler_failure(
    client, db_session, monkeypatch
):
    """Clicking a button proves the code works, not that the loop is alive.

    `record_success` used to zero `consecutive_failures` and clear
    `last_error` unconditionally, so a sweep failing nightly for a month read
    "swept just now, 0 failures" after one press — hiding exactly the dead-task
    condition the health record exists to expose.
    """
    from headroom.services import hat_analysis_pipeline

    db_session.add(_hat(resale_price=10.0))
    await db_session.commit()

    async def fake_refresh(hat):
        hat.resale_price = 55.0

    monkeypatch.setattr(hat_analysis_pipeline, "refresh_melin_resale", fake_refresh)

    repricing.health().record_failure("MelinRecapError: 429 Too Many Requests")
    repricing.health().record_failure("MelinRecapError: 429 Too Many Requests")

    await client.post("/api/admin/repricing/run")

    after = (await client.get("/api/admin/repricing")).json()
    assert after["consecutive_failures"] == 2, after
    assert "429" in (after["last_error"] or ""), after
    # ...while still reporting that the manual sweep itself worked.
    assert after["last_repriced"] == 1


async def test_a_scheduled_sweep_does_clear_the_alarm(db_session, monkeypatch):
    """The scheduler recovering is the one thing that means recovery."""
    repricing.health().record_failure("boom")
    repricing.health().record_success(3, 10, scheduled=True)

    assert repricing.health().consecutive_failures == 0
    assert repricing.health().last_error is None


async def test_a_failing_manual_run_is_recorded_not_swallowed(
    client, db_session, monkeypatch
):
    """A manual sweep that fails forever must not leave the last success showing."""
    async def boom(session_factory=None, limit=None):
        raise RuntimeError("marketplace down")

    monkeypatch.setattr(repricing, "reprice_once", boom)

    # The handler records and then RE-RAISES, so the traceback still reaches
    # the container log (CLAUDE.md: "Starlette re-raises"). Under
    # ASGITransport that surfaces here rather than as a 500 — the contract
    # being pinned is "recorded, then raised", not the status code.
    with pytest.raises(RuntimeError, match="marketplace down"):
        await client.post("/api/admin/repricing/run")

    after = repricing.health()
    assert after.consecutive_failures == 1
    assert "marketplace down" in (after.last_error or "")


async def test_unpriceable_hats_do_not_starve_the_queue(db_session, monkeypatch):
    """The ordering must ADVANCE, or a capped sweep never reaches the tail.

    `refresh_melin_resale` sets `resale_checked_at` only when it finds
    listings — it returns early for a non-melin brand, an API error, or an
    empty result. Ordered `nulls_first`, those hats keep a NULL timestamp
    forever and permanently own the head of the queue, so every capped sweep
    re-visits the same never-priceable rows and never gets past them.
    """
    from headroom.services import hat_analysis_pipeline

    for i in range(3):
        db_session.add(_hat(model_name=f"Dud{i}", brand="not-melin"))
    await db_session.commit()

    async def never_prices(hat):
        return  # exactly what a non-melin brand or an empty result does

    monkeypatch.setattr(hat_analysis_pipeline, "refresh_melin_resale", never_prices)

    first = [h.model_name for h in await repricing._eligible_hats(db_session, limit=2)]
    await repricing.reprice_once(session_factory=_factory(db_session), limit=2)
    db_session.expire_all()
    second = [h.model_name for h in await repricing._eligible_hats(db_session, limit=2)]

    assert first != second, (
        f"the queue did not advance: swept {first}, next sweep offers {second}"
    )


async def test_a_manual_run_is_bounded_and_says_what_is_left(
    client, db_session, monkeypatch
):
    """Uncapped this is a four-minute HTTP request — a dead spinner on a phone."""
    from headroom.services import hat_analysis_pipeline

    monkeypatch.setattr(repricing, "MANUAL_SWEEP_LIMIT", 2)
    for i in range(5):
        db_session.add(_hat(model_name=f"H{i}"))
    await db_session.commit()

    async def fake_refresh(hat):
        return

    monkeypatch.setattr(hat_analysis_pipeline, "refresh_melin_resale", fake_refresh)

    body = (await client.post("/api/admin/repricing/run")).json()
    assert body["considered"] == 2, body
    assert body["remaining"] == 5, body  # a COUNT, not len() of the capped list


# ------------- "Re-price all": the whole shelf, off the request -------------- #
#
# `/repricing/run` is bounded to MANUAL_SWEEP_LIMIT and that bound is right for
# it: it runs inline because the caller wants the number back, and uncapped that
# is a multi-minute request against somebody else's public API — a dead spinner,
# then a proxy timeout, after which the result is discarded and nothing is
# recorded. The mistake was that blocking was the ONLY option, so re-pricing
# everything meant pressing repeatedly or waiting for the 24h scheduler.


async def test_re_pricing_everything_covers_more_than_the_bounded_run(
    client, db_session, monkeypatch
):
    """The point of the endpoint: no MANUAL_SWEEP_LIMIT.

    Carries a CONTROL — the bounded run over the same shelf — because asserting
    only that the background sweep touched everything passes just as well if the
    limit were removed from BOTH, which would reintroduce the timeout this
    endpoint exists to avoid.
    """
    from headroom.services import hat_analysis_pipeline, repricing

    monkeypatch.setattr(repricing, "MANUAL_SWEEP_LIMIT", 2)
    for i in range(5):
        db_session.add(_hat(model_name=f"Hat{i}", resale_price=10.0))
    await db_session.commit()

    seen: list[str] = []

    async def fake_refresh(hat):
        seen.append(hat.model_name)

    monkeypatch.setattr(hat_analysis_pipeline, "refresh_melin_resale", fake_refresh)

    bounded = (await client.post("/api/admin/repricing/run")).json()
    assert bounded["considered"] == 2, "the inline run stays bounded"

    seen.clear()
    resp = await client.post("/api/admin/repricing/run-all")
    assert resp.status_code == 202, resp.text
    assert resp.json() == {"started": True, "already_running": False}
    # The sweep is a `create_task`, so the 202 does not wait for it — that is
    # the point of the endpoint, and it is why this has to drain rather than
    # read `seen` straight after the response. It used to work by accident:
    # httpx's ASGI transport awaits BackgroundTasks, which made every request
    # here synchronous and hid the race the sibling test is named for.
    await _drain_sweeps()
    assert len(seen) == 5, "the background sweep covers the whole shelf"


async def test_a_second_press_does_not_start_a_second_sweep(client, monkeypatch):
    """Two presses against the real endpoint, in the window the guard exists for.

    This test has been wrong twice, in two different ways, and BOTH versions
    passed while the guard they named was broken. Worth recording, because the
    failure mode is the same each time: the arrangement quietly moved to a
    moment where even a broken guard looks right.

    v1 pre-called `progress.begin()` — the one arrangement that cannot fail,
    since it makes the sweep visible before the second request arrives. Nothing
    in production does that.

    v2 replaced it with two real requests and then asserted `started is True`
    for BOTH and `swept == 6`: that each press swept the whole shelf, which is
    the opposite of the name on the door. It passed identically with the old
    `progress.running` guard restored, because httpx's ASGI transport awaits
    BackgroundTasks — so the two requests were strictly sequential and there was
    never a race to lose. The comment explaining that sat in the test, reading
    as a justification rather than the admission it was.

    v3 held the sweep open at its first HAT. That fails under sabotage, but for
    the wrong reason: a hat is reached AFTER `progress.begin()`, so the old
    guard correctly refused there too, and only the drained-slot assertion
    caught it.

    The window that matters is **claimed and scheduled, but not yet begun** —
    the only moment when `progress.running` is False while a sweep is genuinely
    on its way. So `reprice_once` is stubbed to block before it, and the test
    ASSERTS it is in that window before pressing again.
    """
    gate = asyncio.Event()
    entered = asyncio.Event()
    calls = 0

    async def held_sweep(*a, **kw):
        # Blocks BEFORE `progress.begin()`. That is the whole point: the window
        # this guard closes is "claimed and scheduled, but not yet begun", and
        # it is the ONLY window in which `progress.running` is still False while
        # a sweep is genuinely on its way. Holding the sweep open at its first
        # HAT — which an earlier draft of this test did — is already past
        # `begin()`, so a progress-guard looks correct there and the test proves
        # nothing about the race it is named for.
        nonlocal calls
        calls += 1
        entered.set()
        await gate.wait()
        return (0, 0)

    monkeypatch.setattr(repricing, "reprice_once", held_sweep)

    first = await client.post("/api/admin/repricing/run-all")
    assert first.json() == {"started": True, "already_running": False}

    await asyncio.wait_for(entered.wait(), timeout=2)
    # The discriminator. If this is ever True here, the arrangement has drifted
    # back to testing the easy case and the assertion below stops meaning
    # anything — so it is asserted, not assumed.
    assert repricing.progress.snapshot()["running"] is False, (
        "the sweep must be in flight but not yet begun, or this is not the race"
    )

    second = await client.post("/api/admin/repricing/run-all")
    assert second.json() == {"started": False, "already_running": True}

    gate.set()
    await _drain_sweeps()
    assert not repricing.full_sweep_in_flight(), "the slot was never released"
    assert calls == 1, "the shelf was swept once, not twice"


async def test_the_scheduled_sweep_holds_the_slot_the_buttons_check(
    client, monkeypatch
):
    """The nightly sweep is a full sweep and must claim like any other.

    The claim was written for two presses of one button, so it asked what that
    button does and never what else takes `_sweep_lock`. `_loop()` does — for
    minutes, every cycle, unattended — and while it ran the slot read free.
    "Re-price all" would start a second full pass (the one thing it promises to
    refuse), and "Re-price now" would skip its 409 and block on the lock for the
    whole nightly run, which is the dead spinner and proxy timeout its own cap
    exists to prevent. Both routes asserted a property the code did not have.

    `reprice_once` is stubbed rather than run: what changed is the loop's claim
    around it, and calling the real one would reach for the module-level
    `async_session` — the wrong database, the mistake `error_handler` documents.
    """
    import contextlib

    entered = asyncio.Event()
    gate = asyncio.Event()

    async def held_sweep(*a, **kw):
        entered.set()
        await gate.wait()
        return (0, 0)

    monkeypatch.setattr(repricing, "reprice_once", held_sweep)

    loop_task = asyncio.create_task(repricing._loop())
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        assert repricing.full_sweep_in_flight(), "the scheduled sweep did not claim"

        assert (await client.post("/api/admin/repricing/run-all")).json() == {
            "started": False,
            "already_running": True,
        }
        assert (await client.post("/api/admin/repricing/run")).status_code == 409
    finally:
        gate.set()
        loop_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await loop_task

    # A cancelled scheduler must release, or shutdown leaves the slot held and
    # every later press is refused for the life of the process.
    assert not repricing.full_sweep_in_flight()


async def test_the_claim_refuses_a_second_sweep_while_one_is_queued(client):
    """The claim is taken SYNCHRONOUSLY in the handler, before the task runs.

    That is the whole fix: a guard reading `progress.running` cannot see a
    sweep that is queued but not yet started, and BackgroundTasks do not start
    until the response is sent.
    """
    from headroom.services import repricing

    assert repricing.claim_full_sweep() is True
    try:
        resp = await client.post("/api/admin/repricing/run-all")
        assert resp.status_code == 202
        assert resp.json() == {"started": False, "already_running": True}
    finally:
        repricing.release_full_sweep()

    # Released, so the next press is allowed again — a crashed sweep must not
    # refuse every later press for the life of the process.
    assert repricing.claim_full_sweep() is True
    repricing.release_full_sweep()


async def test_the_bounded_run_refuses_to_queue_behind_a_full_sweep(client):
    """A full sweep holds `_sweep_lock` for minutes, so running the bounded
    route inline during one would block on it — the multi-minute request, dead
    spinner and proxy timeout that route's own cap exists to prevent. The card
    disables the button; a direct call must not be able to walk into it."""
    from headroom.services import repricing

    assert repricing.claim_full_sweep() is True
    try:
        resp = await client.post("/api/admin/repricing/run")
        assert resp.status_code == 409, resp.text
    finally:
        repricing.release_full_sweep()


async def test_a_failed_background_sweep_is_recorded_not_swallowed(
    client, db_session, monkeypatch
):
    """Nobody is watching a background sweep, so a failure that vanished with
    the run could never be read — the same blindness the health record exists
    to remove."""
    from headroom.services import repricing

    db_session.add(_hat(model_name="Doomed", resale_price=10.0))
    await db_session.commit()

    async def boom(*a, **kw):
        raise RuntimeError("the whole sweep died")

    monkeypatch.setattr(repricing, "reprice_once", boom)

    resp = await client.post("/api/admin/repricing/run-all")
    assert resp.status_code == 202

    status = (await client.get("/api/admin/repricing")).json()
    assert "the whole sweep died" in (status["last_error"] or "")


async def test_a_manual_full_sweep_does_not_clear_a_standing_failure(
    client, db_session, monkeypatch
):
    """`scheduled=False`. A button press proves the code works, not that the
    background loop is alive — otherwise a sweep failing nightly for a month
    reads "swept just now, 0 failures" after one click, hiding exactly the
    dead-task condition the record exists to expose."""
    from headroom.services import hat_analysis_pipeline, repricing

    repricing.health().record_failure("nightly sweep has been dead for weeks")

    db_session.add(_hat(model_name="Fine", resale_price=10.0))
    await db_session.commit()

    async def fake_refresh(hat):
        hat.resale_price = 42.0

    monkeypatch.setattr(hat_analysis_pipeline, "refresh_melin_resale", fake_refresh)

    await client.post("/api/admin/repricing/run-all")

    status = (await client.get("/api/admin/repricing")).json()
    assert status["last_error"] == "nightly sweep has been dead for weeks"
    assert status["consecutive_failures"] == 1


async def test_the_full_sweep_requires_auth(anon_client):
    assert (await anon_client.post("/api/admin/repricing/run-all")).status_code == 401
