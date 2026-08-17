"""Tests for the bulk-import endpoints (job lifecycle)."""

import asyncio
import io

import pytest
from PIL import Image

from headroom.services.claude_analysis import AnalyzedColor, HatAnalysis

pytestmark = pytest.mark.anyio


def _jpeg(color=(180, 60, 200)) -> bytes:
    img = Image.new("RGB", (200, 200), color)
    buf = io.BytesIO()
    img.save(buf, "JPEG")
    return buf.getvalue()


@pytest.fixture
def stub_pipeline(monkeypatch):
    """Stub Claude + key for the import worker so jobs can complete."""
    async def _fake_get_key(_db):
        return "sk-ant-test", "database"

    async def _fake_analyze(_path, _key, model=None, selected_style=None, **_kw):  # noqa: ARG001
        return HatAnalysis(
            brand="Melin",
            model_name="A-Game Hydro",
            model_confidence="high",
            style_descriptor="snapback",
            design_notes="Test fixture hat.",
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


async def test_create_import_job_returns_id(client):
    resp = await client.post(
        "/api/hats/import",
        files=[("photos", ("a.jpg", _jpeg(), "image/jpeg"))],
        data={"condition": "new", "size": "classic", "style": "a_game"},
    )
    assert resp.status_code == 202
    body = resp.json()
    assert "id" in body
    assert body["total"] == 1


async def test_get_job_includes_items(client):
    create = await client.post(
        "/api/hats/import",
        files=[
            ("photos", ("a.jpg", _jpeg(), "image/jpeg")),
            ("photos", ("b.jpg", _jpeg(color=(30, 30, 100)), "image/jpeg")),
        ],
        data={"condition": "new", "size": "classic", "style": "a_game"},
    )
    job_id = create.json()["id"]

    resp = await client.get(f"/api/hats/import/{job_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert len(body["items"]) == 2
    assert all(it["filename"] in ("a.jpg", "b.jpg") for it in body["items"])


async def test_invalid_content_type_rejected(client):
    resp = await client.post(
        "/api/hats/import",
        files=[("photos", ("a.txt", b"not an image", "text/plain"))],
        data={},
    )
    assert resp.status_code == 400


async def test_cancel_marks_queued_items_cancelled(client):
    """Worker is not started in tests, so items stay queued — perfect for cancel."""
    create = await client.post(
        "/api/hats/import",
        files=[("photos", ("a.jpg", _jpeg(), "image/jpeg"))],
        data={},
    )
    job_id = create.json()["id"]
    resp = await client.delete(f"/api/hats/import/{job_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "cancelled"
    assert all(it["status"] == "cancelled" for it in body["items"])


@pytest.mark.anyio
async def test_new_hat_defaults_are_shared_by_every_entry_point():
    """Three paths create hats without full details — the bulk-import form, its
    worker fallback, and the Android share target. They used to restate
    ("new", "classic", "a_game") independently, so a change to one silently
    diverged the others: photos shared from a phone would land differently than
    the same photos bulk-imported. Pin them to the single source.
    """
    import inspect as _inspect

    from headroom.routes import import_jobs, share
    from headroom.schemas.hat import HAT_DEFAULTS
    from headroom.services import import_service

    # The form endpoint's declared defaults.
    params = _inspect.signature(import_jobs.create_import_job).parameters
    for field in ("condition", "size", "style"):
        assert params[field].default == HAT_DEFAULTS[field], (
            f"import_jobs.create_import_job {field} default drifted from HAT_DEFAULTS"
        )

    # The share target and the worker fallback both read the same dict.
    assert "HAT_DEFAULTS" in _inspect.getsource(share.share_target)
    assert "HAT_DEFAULTS" in _inspect.getsource(import_service._process_item)

    # And the values are real enum members, not typos.
    from headroom.schemas.hat import HatCondition, HatSize, HatStyle

    HatCondition(HAT_DEFAULTS["condition"])
    HatSize(HAT_DEFAULTS["size"])
    HatStyle(HAT_DEFAULTS["style"])
