"""The inventory report — the document that goes to an insurer.

`report_service` sat at 53% with `render_report` and `_row_html` uncovered,
which is a strange thing to leave untested: it is the one output whose whole
purpose is to be read by somebody outside the app, and the only place the
valuation rule is rendered server-side rather than in TypeScript.

`tests/test_valuation_parity.py` already pins the two implementations to the
same constants. What it cannot see is whether the report actually CALLS them,
which is exactly the drift that happened once before — the report carried a
fourth private ranking that labelled a scraped median "manual" and fell
through to undiscounted retail.
"""

from __future__ import annotations

import pytest

from headroom.services import report_service, valuation

pytestmark = pytest.mark.anyio


async def _hat(client, **fields):
    resp = await client.post("/api/hats", json={
        "condition": "new", "size": "classic", "style": "a_game", **fields
    })
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _render(**kw):
    from tests.conftest import test_session_factory

    async with test_session_factory() as db:
        return await report_service.render_report(db, **kw)


async def test_the_report_is_a_standalone_page(client):
    await _hat(client, model_name="A-Game Hydro")

    html = await _render()

    assert html.lstrip().lower().startswith("<!doctype html")
    assert "</html>" in html
    # Printable via the browser, so it must carry its own styling rather than
    # rely on the SPA's stylesheet, which it is not served alongside.
    assert "<style" in html


async def test_every_active_hat_appears(client):
    await _hat(client, model_name="Coronado")
    await _hat(client, model_name="Odysea")

    html = await _render()

    assert "Coronado" in html
    assert "Odysea" in html


async def test_disposed_hats_are_excluded_by_default(client):
    hat_id = await _hat(client, model_name="SoldHat")
    resp = await client.post(f"/api/hats/{hat_id}/dispose", json={"via": "sold"})
    assert resp.status_code == 200, resp.text

    assert "SoldHat" not in await _render()
    assert "SoldHat" in await _render(include_disposed=True)


async def test_the_report_values_hats_through_the_shared_rule(client, db_session):
    """Not a fourth private ranking.

    The report once had its own, and it labelled a scraped median as "manual"
    and fell through to undiscounted retail — valuing a worn hat at the price
    of a new one, in the document that goes to an insurer.
    """
    from headroom.models.hat import Hat

    hat_id = await _hat(client, model_name="Priced")
    row = await db_session.get(Hat, hat_id)
    row.resale_price = 123.0
    row.resale_price_scope = "manual"
    await db_session.commit()

    html = await _render()

    assert "$123" in html
    # The basis label comes from the shared vocabulary, not a local string.
    assert valuation.BASIS_LABEL["manual"] in html


async def test_an_unpriced_hat_shows_a_dash_and_not_a_zero(client, db_session):
    """`value_hat` returns None rather than 0 for exactly this reason.

    A zero in a hat's valuation column is a claim that the hat is worthless;
    a dash says nobody has priced it, which is the truth. Asserted on the ROW
    rather than the page, because the collection TOTAL of an unpriced
    collection legitimately is $0 — a sum and a per-hat value are different
    claims, and a page-wide search would conflate them.
    """
    from headroom.models.hat import Hat

    hat_id = await _hat(client, model_name="Unpriced")
    row = await db_session.get(Hat, hat_id)

    cells = report_service._row_html(row, include_photos=False)

    assert "—" in cells
    assert "$0" not in cells


async def test_photos_can_be_left_out(client, db_session):
    """`include_photos=False` exists because the photo-laden version is slow
    to print and enormous as a PDF."""
    from headroom.models.hat import Hat

    hat_id = await _hat(client, model_name="WithPhoto")
    row = await db_session.get(Hat, hat_id)
    row.photo_path = "hats/example.png"
    await db_session.commit()

    assert "hats/example.png" in await _render(include_photos=True)
    assert "hats/example.png" not in await _render(include_photos=False)


async def test_free_text_is_escaped(client):
    """A hat name is user input and the report is HTML.

    Nothing here is served to a third party today, but the file is downloaded,
    mailed and opened in browsers — so an unescaped `<script>` in a model name
    is a real hazard rather than a theoretical one.
    """
    await _hat(client, model_name="<script>alert(1)</script>")

    html = await _render()

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


async def test_the_report_states_the_version_that_made_it(client):
    """An inventory document with no provenance is hard to trust a year later."""
    await _hat(client)

    html = await _render()

    assert report_service._version_label() in html


async def test_an_empty_collection_still_renders(client):
    """A fresh install must not 500 on the reports page."""
    html = await _render()

    assert "</html>" in html
