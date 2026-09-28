"""The pipeline's own degrade paths, driven through the pipeline.

The promise: each step (bg-removal, Claude, eBay) can fail without breaking the
others, and eBay errors are logged but never block. The services' seams are
tested for raising their own error types (`test_service_degradation.py`);
nothing drove those errors back THROUGH the pipeline, so its catches could be
narrowed to the wrong type — or deleted — with the whole suite green. These
tests fail when that happens.

No live API anywhere: Claude is stubbed at `analyze_hat_image`, eBay at
`find_comps` or its transport, the marketplace at its transport.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image
from sqlalchemy import select

from headroom.config import settings
from headroom.models.hat import Hat
from headroom.services import hat_analysis_pipeline, melin_recap
from headroom.services.claude_analysis import AnalyzedColor, ClaudeAnalysisError, HatAnalysis

# Captured at IMPORT time, before conftest's autouse `no_live_melin_marketplace`
# swaps the module attribute — the same move `test_service_degradation.py`
# makes. The real function's network is stubbed one level down, per test.
_real_query_listings = melin_recap.query_listings

pytestmark = pytest.mark.anyio


def _jpeg() -> io.BytesIO:
    buf = io.BytesIO()
    Image.new("RGB", (200, 200), (0, 0, 200)).save(buf, "JPEG")
    buf.seek(0)
    return buf


def _analysis(model_name: str | None = "A-Game") -> HatAnalysis:
    return HatAnalysis(
        brand="Melin",
        model_name=model_name,
        model_confidence="high",
        style_descriptor="snapback",
        design_notes="notes",
        estimated_new_price_usd=None,
        colors=[AnalyzedColor(name="navy", hex="#1c2541", tier="primary")],
    )


@pytest.fixture
def claude_answers(monkeypatch):
    """A configured key and an analyzer that succeeds — the paid step done."""
    answer = {"analysis": _analysis()}

    async def _key(_db):
        return "sk-ant-fixture", "database"

    async def _analyze(*_a, **_kw):
        return answer["analysis"]

    monkeypatch.setattr("headroom.services.settings_service.get_anthropic_key", _key)
    monkeypatch.setattr("headroom.services.claude_analysis.analyze_hat_image", _analyze)
    return answer


async def _upload(client) -> dict:
    created = await client.post(
        "/api/hats", json={"condition": "new", "size": "classic", "style": "a_game"}
    )
    hat_id = created.json()["id"]
    resp = await client.post(
        f"/api/hats/{hat_id}/photo", files={"photo": ("hat.jpg", _jpeg(), "image/jpeg")}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---- after a paid analysis, nothing downstream may throw it away ----------- #


async def test_an_ebay_failure_keeps_the_analysis(client, claude_answers, monkeypatch):
    from headroom.services.ebay_service import EbayError

    async def _ebay_down(*_a, **_kw):
        raise EbayError("Browse API 503: service unavailable")

    monkeypatch.setattr("headroom.services.ebay_service.find_comps", _ebay_down)

    data = await _upload(client)

    assert data["analysis_status"] == "ok", data["analysis_error"]
    assert (data["brand"], data["model_name"]) == ("Melin", "A-Game")
    assert [c["color_name"] for c in data["colors"]] == ["navy"]


async def test_a_malformed_marketplace_reply_keeps_the_analysis(client, claude_answers, monkeypatch):
    """Measured before the fix: a 200 HTML page from the marketplace turned a
    successful Claude analysis into `error` with brand, model and colors gone
    (and, through the import worker, deleted the hat). It is now a
    marketplace outage like any other: link, no price, analysis intact."""

    class _Html:
        status_code = 200
        text = "<html>captive portal</html>"

        def json(self):
            raise ValueError("Expecting value: line 1 column 1 (char 0)")

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        async def get(self, *_a, **_kw):
            return _Html()

    async def _token(_client, force=False):
        return "tok"

    monkeypatch.setattr(melin_recap, "query_listings", _real_query_listings)
    monkeypatch.setattr(melin_recap, "_get_anon_token", _token)
    monkeypatch.setattr(melin_recap.httpx, "AsyncClient", lambda **_kw: _Client())

    data = await _upload(client)

    assert data["analysis_status"] == "ok", data["analysis_error"]
    assert (data["brand"], data["model_name"]) == ("Melin", "A-Game")
    assert [c["color_name"] for c in data["colors"]] == ["navy"]
    assert data["resale_price"] is None
    assert "melinrecap.com" in data["resale_price_url"]


async def test_ebay_is_not_asked_without_a_model(client, claude_answers, monkeypatch):
    """Without a model the search falls back to the style — the price of the
    whole line written onto this hat as its comparable."""
    claude_answers["analysis"] = _analysis(model_name=None)
    asked: list = []

    async def _find_comps(*_a, **kw):
        asked.append(kw)
        return {}

    monkeypatch.setattr("headroom.services.ebay_service.find_comps", _find_comps)

    data = await _upload(client)

    assert data["analysis_status"] == "ok"
    assert asked == [], "eBay was searched for a hat with no model"


async def test_comps_write_their_five_columns_and_nothing_else(client, claude_answers, monkeypatch):
    """The pipeline wrote comps with its own `setattr` over whatever keys came
    back, where the admin refresh used `hat_service.apply_ebay_comps`. One
    writer: a service answering with a key more cannot reach the hat."""
    async def _find_comps(*_a, **_kw):
        return {"ebay_median_price": 42.0, "ebay_listing_count": 3, "brand": "Not Melin"}

    monkeypatch.setattr("headroom.services.ebay_service.find_comps", _find_comps)

    data = await _upload(client)

    assert (data["ebay_median_price"], data["ebay_listing_count"]) == (42.0, 3)
    assert data["brand"] == "Melin"


# ---- one analysis sequence, two entry points -------------------------------- #


async def test_a_claude_error_on_reanalysis_is_a_result(db_session, tmp_path, monkeypatch):
    """False from `reanalyze_existing_photo` means "nothing to show" and the
    route answers it with a 400. A Claude failure is a result — the hat
    carries the error, and a fallback where one exists."""
    async def _key(_db):
        return "sk-ant-fixture", "database"

    async def _boom(*_a, **_kw):
        raise ClaudeAnalysisError("Anthropic API error: overloaded")

    monkeypatch.setattr("headroom.services.settings_service.get_anthropic_key", _key)
    monkeypatch.setattr("headroom.services.claude_analysis.analyze_hat_image", _boom)
    hat = Hat(condition="new", size="classic", style="a_game")
    db_session.add(hat)
    await db_session.commit()
    photo = tmp_path / "hat.jpg"
    Image.new("RGB", (64, 64), (0, 0, 200)).save(photo, "JPEG")

    applied = await hat_analysis_pipeline.reanalyze_existing_photo(db_session, hat, photo)

    assert applied is True
    assert hat.analysis_status == "error"
    assert "overloaded" in hat.analysis_error


async def test_both_entry_points_stamp_a_keyless_run_alike(db_session, tmp_path):
    """The upload path stamped `skipped`, the reason and a time on a keyless
    run; the re-analysis copy of the same branch stamped nothing, so a hat
    re-analyzed with no key and nothing to fall back on kept whatever status
    it had before. One sequence now, one set of stamps."""
    results = []
    for entry in ("finalize", "reanalyze"):
        hat = Hat(condition="new", size="classic", style="a_game", analysis_status="ok")
        db_session.add(hat)
        await db_session.commit()
        photo = settings.upload_dir / "hats" / f"{entry}.jpg"
        Image.new("RGB", (64, 64), (0, 0, 200)).save(photo, "JPEG")
        if entry == "finalize":
            await hat_analysis_pipeline.finalize_hat_photo(db_session, hat, photo)
        else:
            applied = await hat_analysis_pipeline.reanalyze_existing_photo(db_session, hat, photo)
            assert applied is False, "no key and no mask: nothing to show"
        results.append((hat.analysis_status, hat.analysis_error, hat.analyzed_at is not None))

    assert results[0] == results[1] == ("skipped", "No Anthropic API key configured.", True)


async def test_a_recut_clears_the_stage_it_published(client, monkeypatch, db_session):
    """"Redo cutout" publishes a stage while it runs and must clear it. The
    API masks the stage on any non-pending hat, so only the column shows
    whether the clear happened — and a stale stage is what the next
    re-analysis would display until its first step replaced it."""

    async def _remove(_input, output_path):
        out = output_path.with_suffix(".png")
        img = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
        for x in range(20, 80):
            for y in range(20, 80):
                img.putpixel((x, y), (200, 30, 90, 255))
        img.save(out, "PNG")
        return out

    monkeypatch.setattr("headroom.services.background_removal.remove_background", _remove)
    data = await _upload(client)
    assert data["original_path"], "the fixture must produce a cutout and keep an original"

    resp = await client.post(f"/api/hats/{data['id']}/recut")
    assert resp.status_code == 200, resp.text

    stage = (
        await db_session.execute(select(Hat.analysis_stage).where(Hat.id == data["id"]))
    ).scalar_one()
    assert stage is None, f"the re-cut left its stage behind: {stage!r}"
