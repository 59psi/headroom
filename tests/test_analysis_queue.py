"""The queued photo-analysis path.

The rest of the suite runs with `HEADROOM_ANALYSIS_WORKER_ENABLED=false`, which
exercises the inline fallback. This file is the only place the worker actually
runs, so it is the only place the "upload returns immediately, analysis lands
later" contract is checked at all.

The worker resolves sessions through `analysis_queue.async_session` (module
scope, the real engine), so every test here patches that to the test factory
BEFORE `start_worker` — the boot sweep queries on the way up.
"""

import asyncio
import io

import pytest
from PIL import Image

from headroom.services import analysis_queue
from headroom.services.claude_analysis import AnalyzedColor, HatAnalysis

pytestmark = pytest.mark.anyio


def _jpeg(color=(40, 90, 200)) -> bytes:
    img = Image.new("RGB", (120, 120), color)
    buf = io.BytesIO()
    img.save(buf, "JPEG")
    return buf.getvalue()


@pytest.fixture
def stub_claude(monkeypatch):
    """Give the pipeline a key + a canned Claude reply so it reaches 'ok'."""
    async def _fake_get_key(_db):
        return "sk-ant-test", "database"

    async def _fake_analyze(_path, _key, model=None, selected_style=None, **_kw):
        return HatAnalysis(
            brand="Melin", model_name="A-Game Hydro", model_confidence="high",
            style_descriptor="snapback", design_notes="Queued-path fixture.",
            estimated_new_price_usd=60.0,
            colors=[AnalyzedColor(name="navy", hex="#1c2541", tier="primary")],
            raw=None,
        )

    monkeypatch.setattr(
        "headroom.services.settings_service.get_anthropic_key", _fake_get_key
    )
    monkeypatch.setattr(
        "headroom.services.hat_analysis_pipeline.analyze_hat_image", _fake_analyze
    )


@pytest.fixture
async def worker(monkeypatch):
    """Run a real analysis worker against the test database."""
    from tests.conftest import test_session_factory

    monkeypatch.setattr(analysis_queue, "async_session", test_session_factory)
    await analysis_queue.start_worker()
    try:
        yield analysis_queue
    finally:
        await analysis_queue.stop_worker()


async def _hat_with_photo(client) -> dict:
    hat = (await client.post(
        "/api/hats", json={"condition": "new", "size": "classic", "style": "a_game"}
    )).json()
    resp = await client.post(
        f"/api/hats/{hat['id']}/photo",
        files={"photo": ("h.jpg", _jpeg(), "image/jpeg")},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _drain(timeout=10.0):
    await asyncio.wait_for(analysis_queue._queue.join(), timeout=timeout)


async def test_upload_returns_pending_then_the_worker_finishes_it(
    client, worker, stub_claude
):
    """The whole point: the request comes back before analysis has run."""
    body = await _hat_with_photo(client)
    # Returned without waiting for rembg/Claude — this is what stops the UI
    # looking hung, and it must be true in the response itself, not eventually.
    assert body["analysis_status"] == "pending"
    assert body["photo_path"], "photo must be saved and viewable immediately"

    await _drain()

    after = (await client.get(f"/api/hats/{body['id']}")).json()
    assert after["analysis_status"] == "ok"
    assert after["brand"] == "Melin"


async def test_upload_runs_inline_when_no_worker_is_draining(client, stub_claude):
    """Work is never silently dropped when the worker is off or dead.

    Without this the 'pending' write would be the last thing that ever happened
    to the hat, and it would spin in the UI forever.
    """
    assert not analysis_queue.worker_alive()
    body = await _hat_with_photo(client)
    assert body["analysis_status"] == "ok"
    assert body["brand"] == "Melin"


async def test_a_crashing_hat_is_marked_errored_and_the_worker_survives(
    client, worker, stub_claude, monkeypatch
):
    """One bad photo must not strand itself OR kill the queue behind it."""
    calls = {"n": 0}
    real = analysis_queue.finalize_hat_photo

    async def _boom_once(db, hat, path):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("rembg exploded")
        return await real(db, hat, path)

    monkeypatch.setattr(analysis_queue, "finalize_hat_photo", _boom_once)

    first = await _hat_with_photo(client)
    await _drain()
    first_after = (await client.get(f"/api/hats/{first['id']}")).json()
    # Errored, NOT left pending — a hat stuck 'pending' spins in the UI forever.
    assert first_after["analysis_status"] == "error"
    assert "rembg exploded" in (first_after["analysis_error"] or "")

    # The worker is still alive and still draining.
    assert analysis_queue.worker_alive()
    second = await _hat_with_photo(client)
    await _drain()
    second_after = (await client.get(f"/api/hats/{second['id']}")).json()
    assert second_after["analysis_status"] == "ok"


async def test_boot_recovery_requeues_hats_stranded_pending(client, monkeypatch):
    """A crash mid-analysis must cost a retry, not a permanently spinning hat."""
    from tests.conftest import test_session_factory

    hat = (await client.post(
        "/api/hats", json={"condition": "new", "size": "classic", "style": "a_game"}
    )).json()
    # Simulate the pre-crash state: photo saved, marked pending, never analyzed.
    await client.put(f"/api/hats/{hat['id']}", json={})
    from headroom.models.hat import Hat
    async with test_session_factory() as db:
        row = await db.get(Hat, hat["id"])
        row.analysis_status = analysis_queue.PENDING
        await db.commit()

    monkeypatch.setattr(analysis_queue, "async_session", test_session_factory)
    await analysis_queue.start_worker()
    try:
        # The sweep must have found it and put it back on the queue.
        await _drain()
        after = (await client.get(f"/api/hats/{hat['id']}")).json()
        # No photo on disk, so it resolves to 'error' rather than staying
        # pending — the point is that the boot sweep TOUCHED it at all.
        assert after["analysis_status"] != analysis_queue.PENDING
    finally:
        await analysis_queue.stop_worker()


@pytest.mark.anyio
async def test_inline_failure_marks_the_hat_instead_of_stranding_it(
    client, monkeypatch
):
    """With no worker, a pipeline crash must still reach a terminal status.

    `enqueue()` returns False when nothing is draining the queue, so the route
    runs the pipeline inline — and in that mode there is no worker to catch the
    exception and no boot sweep to revisit the hat. An unhandled failure left
    `analysis_status='pending'` forever, with the UI spinning and no endpoint
    able to clear it short of re-uploading.
    """
    async def _boom(*_a, **_k):
        raise RuntimeError("pipeline exploded")

    monkeypatch.setattr(
        "headroom.routes.hats.finalize_hat_photo", _boom
    )

    created = await client.post(
        "/api/hats", json={"condition": "new", "size": "classic", "style": "a_game"}
    )
    hat_id = created.json()["id"]

    resp = await client.post(
        f"/api/hats/{hat_id}/photo",
        files={"photo": ("h.jpg", _jpeg(), "image/jpeg")},
    )

    # The photo itself saved fine, so this is a success with a failed analysis —
    # which is exactly what analysis_status exists to report.
    assert resp.status_code == 200
    assert resp.json()["analysis_status"] == "error"
    assert "pipeline exploded" in (resp.json()["analysis_error"] or "")


async def test_an_inline_reanalyze_failure_marks_the_hat_instead_of_stranding_it(
    client, stub_claude, monkeypatch
):
    """The THIRD inline path, which had no guard.

    Upload and re-cut each caught an inline pipeline failure and stamped the
    terminal status; `/reanalyze` marked the hat `pending`, ran
    `reanalyze_existing_photo` with no worker behind it, and let anything but
    a `ClaudeAnalysisError` escape as a 500 — leaving the hat `pending` forever
    with no error text and nothing to clear it. Same guard, same test shape.
    """
    created = await client.post(
        "/api/hats", json={"condition": "new", "size": "classic", "style": "a_game"}
    )
    hat_id = created.json()["id"]
    assert (
        await client.post(
            f"/api/hats/{hat_id}/photo", files={"photo": ("h.jpg", _jpeg(), "image/jpeg")}
        )
    ).status_code == 200

    async def _boom(*_a, **_k):
        raise RuntimeError("reanalysis exploded")

    monkeypatch.setattr("headroom.routes.hats.reanalyze_existing_photo", _boom)

    resp = await client.post(f"/api/hats/{hat_id}/reanalyze")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["analysis_status"] == "error", "never left on pending"
    assert "reanalysis exploded" in (body["analysis_error"] or "")
