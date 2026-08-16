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

    async def _fake_analyze(_path, _key, model=None, selected_style=None):  # noqa: ARG001
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
    # Simulate the pre-crash state: photo saved, marked pending, never analysed.
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
