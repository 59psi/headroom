"""Series names the owner enters must feed forward into future analyses.

Two halves, and only one of them existed:

* **Typing** a series already learned — `GET /api/meta/collections` returns
  every value in use and the Add/Edit form offers it as a combobox.
* **Analysis** did not. `analyze_hat_image` received the owner's style and
  construction but never the series already on record, so Claude was asked to
  recall a collab from a photo unaided. A series is usually a woven label or an
  embroidery style rather than anything legible, so most were simply missed —
  and the ones it did catch were written verbatim, landing *beside* the owner's
  spelling rather than onto it, because the analysis write path was the one
  place `vocabulary.canonicalize` never ran.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from headroom.models.hat import Hat
from headroom.services.claude_analysis import (
    MAX_KNOWN_SERIES,
    _known_series_context,
    _owner_context,
)
from headroom.services.hat_analysis_pipeline import (
    _canonicalize_analysis_text,
    _known_series,
)

pytestmark = pytest.mark.anyio


async def _hat(client, **fields):
    resp = await client.post(
        "/api/hats",
        json={"condition": "new", "size": "classic", "style": "a_game", **fields},
    )
    assert resp.status_code == 201
    return resp.json()["id"]


# ------------------------------ the prompt -------------------------------- #


async def test_known_series_are_offered_to_the_analyser():
    text = _owner_context("a_game", None, ["Skye Walker", "Jeremy Collins"])
    assert "Skye Walker" in text
    assert "Jeremy Collins" in text


async def test_the_list_is_framed_as_a_record_not_a_menu():
    """A candidate list invites a forced choice, and that would be worse than
    the misses it fixes — a wrong series looks exactly like a right one."""
    text = _known_series_context(["Skye Walker"])
    assert "NOT a list to choose from" in text
    assert "return null" in text
    assert "worse than an empty field" in text


async def test_exact_spelling_is_demanded():
    """The point is to converge on the owner's spelling, not add a variant."""
    assert "EXACTLY" in _known_series_context(["Skye Walker"])


async def test_no_series_means_no_sentence():
    """An empty collection must not gain a dangling 'these names: .' clause."""
    assert _known_series_context([]) == ""
    assert _known_series_context(["", "   "]) == ""
    assert _owner_context(None, None, []) == "Analyze this hat photo using the tool."


async def test_series_context_survives_without_owner_facts():
    """The halves are independent: a hat with no stated style still gets the
    list, and the prompt still ends with the tool instruction."""
    text = _owner_context(None, None, ["Skye Walker"])
    assert "Skye Walker" in text
    assert text.endswith("Use the tool to record your analysis.")


async def test_owner_facts_are_not_displaced_by_the_series_list():
    text = _owner_context("a_game", "HYDROLite", ["Skye Walker"])
    assert "HYDROLite" in text and "ground truth" in text
    assert "Skye Walker" in text


async def test_a_truncated_list_says_so():
    """No silent caps: a partial list presented as complete would teach the
    analyser that anything absent from it must be a new series."""
    many = [f"Series {i:03d}" for i in range(MAX_KNOWN_SERIES + 10)]
    text = _known_series_context(many)
    assert "among others" in text
    assert text.count("Series ") == MAX_KNOWN_SERIES


async def test_a_complete_list_does_not_claim_to_be_partial():
    assert "among others" not in _known_series_context(["Only One"])


# --------------------------- feeding it forward --------------------------- #


async def test_meta_collections_learns_what_the_owner_entered(client):
    await _hat(client, artist_series="Skye Walker")
    assert "Skye Walker" in (await client.get("/api/meta/collections")).json()


async def test_the_pipeline_reads_the_series_in_use(client, db_session):
    """What `_known_series` hands the prompt is what the collection contains."""
    await _hat(client, artist_series="Skye Walker")
    await _hat(client, artist_series="Jeremy Collins")

    names = await _known_series(db_session)

    assert set(names) >= {"Skye Walker", "Jeremy Collins"}


async def test_an_analysis_written_series_snaps_onto_the_owners_spelling(
    client, db_session
):
    """The half that makes the other half safe.

    Once the known names are in the prompt, an echo in the wrong casing would
    otherwise create exactly the duplicate this feature exists to prevent — and
    silently, since both hats end up with *a* series and the split only shows
    as two near-identical rows in the autocomplete, the Stats collab chart and
    the filters.
    """
    await _hat(client, artist_series="Skye Walker")
    second = await _hat(client)

    hat = (await db_session.execute(select(Hat).where(Hat.id == second))).scalar_one()
    hat.artist_series = "skye walker"  # what an unguided analyser hands back
    await _canonicalize_analysis_text(db_session, hat)

    assert hat.artist_series == "Skye Walker"
    await db_session.commit()

    collections = (await client.get("/api/meta/collections")).json()
    assert collections.count("Skye Walker") == 1
    assert "skye walker" not in collections


async def test_canonicalising_leaves_a_genuinely_new_series_alone(client, db_session):
    """Convergence must not become capture: an unrelated name stays as typed."""
    await _hat(client, artist_series="Skye Walker")
    second = await _hat(client)

    hat = (await db_session.execute(select(Hat).where(Hat.id == second))).scalar_one()
    hat.artist_series = "Jeremy Collins"
    await _canonicalize_analysis_text(db_session, hat)

    assert hat.artist_series == "Jeremy Collins"


async def test_canonicalising_a_construction_keeps_the_derived_flags_honest(
    client, db_session
):
    """`construction` owns `hydro`/`hydrolite`, so it must go through the
    setter — assigning the column directly is what lets them drift."""
    hat_id = await _hat(client)

    hat = (await db_session.execute(select(Hat).where(Hat.id == hat_id))).scalar_one()
    hat.set_construction("hydrolite")  # analyser casing
    await _canonicalize_analysis_text(db_session, hat)

    assert hat.construction == "HYDROLite", "curated spelling should win"
    assert hat.hydrolite is True
    assert hat.hydro is False, "HYDRO must not match inside HYDROLite"


async def test_canonicalising_is_a_no_op_for_an_unanalysed_hat(client, db_session):
    hat_id = await _hat(client)
    hat = (await db_session.execute(select(Hat).where(Hat.id == hat_id))).scalar_one()

    await _canonicalize_analysis_text(db_session, hat)

    assert hat.artist_series is None
    assert hat.construction is None
