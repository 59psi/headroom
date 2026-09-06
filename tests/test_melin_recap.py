import pytest

from headroom.services.melin_recap import (
    build_resale_pointer,
    is_melin,
    melin_recap_link,
)

# The autouse setup_db fixture in conftest is async, so every test in the
# suite needs the anyio plugin even when the test body itself is synchronous.
pytestmark = pytest.mark.anyio


async def test_is_melin_matches_case_insensitive():
    assert is_melin("Melin") is True
    assert is_melin("MELIN BRAND") is True
    assert is_melin("New Era") is False
    assert is_melin(None) is False
    assert is_melin("") is False


async def test_link_for_known_styles_uses_filter_param():
    url = melin_recap_link("a_game")
    assert "pub_category=aGame" in url
    assert "filter-change" in url


async def test_link_falls_back_for_unknown_style():
    url = melin_recap_link("beanie")
    assert url == "https://www.melinrecap.com/"


async def test_build_pointer_only_for_melin():
    assert build_resale_pointer("Melin", "odysea") == {
        "resale_price": None,
        "resale_price_source": "Melin Recap",
        "resale_price_url": "https://www.melinrecap.com/?mode=filter-change&pub_category=odysea",
    }
    assert build_resale_pointer("New Era", "fitted") is None
    assert build_resale_pointer(None, "a_game") is None


# ---------------------- live marketplace stats ------------------------ #


def _listing(
    title: str, cents: int | None, condition: str = "new_with_tags", size: str = "C"
) -> dict:
    """One marketplace listing. `condition` and `size` live in publicData and
    are what make a median comparable — see `fetch_resale_stats`."""
    attrs: dict = {"title": title, "publicData": {"condition": condition, "size": size}}
    if cents is not None:
        attrs["price"] = {"amount": cents, "currency": "USD"}
    return {"id": "x", "type": "listing", "attributes": attrs}


def _stub_query(monkeypatch, listings):
    captured: dict = {}

    async def _fake_query(params):
        captured.update(params)
        return listings

    monkeypatch.setattr(
        "headroom.services.melin_recap.query_listings", _fake_query
    )
    return captured


async def test_stats_median_over_category(monkeypatch):
    from headroom.services.melin_recap import fetch_resale_stats

    params = _stub_query(monkeypatch, [
        _listing("A-Game Hydro - Red", 8900),
        _listing("A-Game Scout - Grey", 5500),
        _listing("A-Game Classic - Navy", 7000),
        _listing("No price listing", None),
    ])
    stats = await fetch_resale_stats("a_game", None)
    assert params["pub_category"] == "aGame"
    # Field-wise, not whole-dict: the payload gains keys as the matcher learns
    # to scope, and an == here fails on additions that break nothing.
    assert stats["median"] == 70.0
    assert stats["count"] == 3
    assert stats["sample"] == "category"


async def test_stats_narrows_to_model_when_sample_big_enough(monkeypatch):
    from headroom.services.melin_recap import fetch_resale_stats

    _stub_query(monkeypatch, [
        _listing("A-Game Hydro - Red", 8000),
        _listing("A-Game Hydro - Gray", 9000),
        _listing("a-game hydro - Navy", 10000),
        _listing("A-Game Scout - Grey", 1000),
    ])
    stats = await fetch_resale_stats("a_game", "A-Game Hydro")
    assert stats["median"] == 90.0
    assert stats["count"] == 3
    assert stats["sample"] == "model"


async def test_stats_widens_when_model_sample_too_small(monkeypatch):
    from headroom.services.melin_recap import fetch_resale_stats

    _stub_query(monkeypatch, [
        _listing("A-Game Hydro - Red", 8000),
        _listing("A-Game Scout - Grey", 2000),
        _listing("A-Game Classic - Navy", 5000),
    ])
    stats = await fetch_resale_stats("a_game", "A-Game Hydro")
    assert stats["sample"] == "category"
    assert stats["count"] == 3
    assert stats["median"] == 50.0


async def test_stats_none_without_style_or_model(monkeypatch):
    from headroom.services.melin_recap import fetch_resale_stats

    _stub_query(monkeypatch, [])
    assert await fetch_resale_stats(None, None) is None


async def test_refresh_melin_resale_persists_median(monkeypatch):
    from headroom.models.hat import Hat
    from headroom.services.hat_analysis_pipeline import refresh_melin_resale

    _stub_query(monkeypatch, [
        _listing("A-Game Hydro - Red", 8000),
        _listing("A-Game Hydro - Gray", 9000),
        _listing("A-Game Hydro - Navy", 10000),
    ])
    hat = Hat(condition="new", size="classic", style="a_game", brand="Melin",
              model_name="A-Game Hydro")
    await refresh_melin_resale(hat)
    assert hat.resale_price == 90.0
    # The label NAMES the line compared against rather than saying "model".
    # The match is a prefix of the hat's name now, so "model listings" alone
    # would hide that an `Odysea Rope Hydro (WATERCOLOR)` was priced against
    # every `Odysea Rope Hydro` — a fair comp, and one worth being able to see.
    assert "median of 3 live A Game Hydro listings" in hat.resale_price_source
    assert hat.resale_checked_at is not None


async def test_refresh_degrades_silently_when_api_unreachable():
    """Autouse conftest stub raises MelinRecapError — old link-only behavior."""
    from headroom.models.hat import Hat
    from headroom.services.hat_analysis_pipeline import refresh_melin_resale

    hat = Hat(condition="new", size="classic", style="a_game", brand="Melin")
    await refresh_melin_resale(hat)
    assert hat.resale_price is None


async def test_refresh_skips_non_melin():
    from headroom.models.hat import Hat
    from headroom.services.hat_analysis_pipeline import refresh_melin_resale

    hat = Hat(condition="new", size="classic", style="a_game", brand="New Era")
    await refresh_melin_resale(hat)
    assert hat.resale_price is None
    assert hat.resale_checked_at is None


# ---------------- scope: what the price is a price OF ----------------- #
#
# Valuation branches on `resale_price_scope` because the three cases are
# different measurements, not degrees of confidence in one: a category median
# is the going rate for a whole style, and treating it as this hat's value gave
# every hat in a category the same number.


async def test_scope_records_model_when_listings_match_the_model(monkeypatch):
    from headroom.models.hat import Hat
    from headroom.services.hat_analysis_pipeline import refresh_melin_resale

    _stub_query(monkeypatch, [
        _listing("A-Game Hydro - Red", 8000),
        _listing("A-Game Hydro - Gray", 9000),
        _listing("A-Game Hydro - Navy", 10000),
    ])
    hat = Hat(condition="new", size="classic", style="a_game", brand="Melin",
              model_name="A-Game Hydro")
    await refresh_melin_resale(hat)
    assert hat.resale_price_scope == "model"


async def test_scope_records_category_when_the_model_sample_is_too_small(monkeypatch):
    from headroom.models.hat import Hat
    from headroom.services.hat_analysis_pipeline import refresh_melin_resale

    _stub_query(monkeypatch, [
        _listing("A-Game Hydro - Red", 8000),
        _listing("A-Game Scout - Grey", 2000),
        _listing("A-Game Classic - Navy", 5000),
    ])
    hat = Hat(condition="new", size="classic", style="a_game", brand="Melin",
              model_name="A-Game Hydro")
    await refresh_melin_resale(hat)
    assert hat.resale_price_scope == "category"
    assert "live category listings" in hat.resale_price_source


async def test_manual_resale_price_survives_a_refresh(monkeypatch):
    """A number a person typed outranks a scraped median.

    Reanalysis runs unattended from the bulk queue, so anything it overwrites
    is gone with no prompt and nothing to restore it from.
    """
    from headroom.models.hat import Hat
    from headroom.services.hat_analysis_pipeline import refresh_melin_resale

    _stub_query(monkeypatch, [
        _listing("A-Game Hydro - Red", 8000),
        _listing("A-Game Hydro - Gray", 9000),
        _listing("A-Game Hydro - Navy", 10000),
    ])
    hat = Hat(condition="new", size="classic", style="a_game", brand="Melin",
              model_name="A-Game Hydro", resale_price=250.0,
              resale_price_scope="manual")
    await refresh_melin_resale(hat)
    assert hat.resale_price == 250.0
    assert hat.resale_price_scope == "manual"


async def test_manual_resale_price_survives_the_pointer_pass():
    """`_apply_resale_pointer` assigns a None price by construction.

    It ran on every analysis of a Melin hat and relied on the live refresh
    putting a number back afterwards. When the marketplace API is unreachable
    it doesn't — so a hand-entered price vanished on any reanalysis that
    happened to coincide with an outage.
    """
    from headroom.models.hat import Hat
    from headroom.services.hat_analysis_pipeline import _apply_resale_pointer

    hat = Hat(condition="new", size="classic", style="a_game", brand="Melin",
              resale_price=250.0, resale_price_scope="manual")
    _apply_resale_pointer(hat)
    assert hat.resale_price == 250.0
    # The deep link is still refreshed — it is safe to replace and useful.
    assert hat.resale_price_url


async def test_editing_resale_price_marks_it_manual(client):
    """The PUT path is the only place a person's own price enters."""
    created = await client.post("/api/hats", json={
        "condition": "new", "size": "classic", "style": "a_game",
    })
    hat_id = created.json()["id"]

    resp = await client.put(f"/api/hats/{hat_id}", json={"resale_price": 175.0})
    assert resp.status_code == 200
    assert resp.json()["resale_price"] == 175.0
    assert resp.json()["resale_price_scope"] == "manual"

    # Clearing it must drop the marker too, or the hat keeps claiming a manual
    # price it no longer has and blocks every future refresh.
    cleared = await client.put(f"/api/hats/{hat_id}", json={"resale_price": None})
    assert cleared.json()["resale_price_scope"] is None


async def test_restating_the_stored_price_does_not_make_it_manual(client, db_session):
    """The SPA sends only what changed; every OTHER client is covered here.

    A client that echoes the whole hat back — the 2.57 shape — used to turn
    a scraped `model`-scoped median into a `manual` price by saving a note.
    Same number in, same provenance out. A different number is the person.
    """
    from sqlalchemy import update as sa_update

    from headroom.models.hat import Hat

    created = await client.post("/api/hats", json={
        "condition": "new", "size": "classic", "style": "a_game",
    })
    hat_id = created.json()["id"]
    await db_session.execute(sa_update(Hat).where(Hat.id == hat_id).values(
        resale_price=85.0, resale_price_scope="model",
        resale_price_source="median of 18 live listings",
        estimated_new_price=79.0, estimated_new_price_source="melin retail",
    ))
    await db_session.commit()

    echoed = await client.put(f"/api/hats/{hat_id}", json={
        "resale_price": 85.0, "estimated_new_price": 79.0, "owner_notes": "still mine",
    })
    assert echoed.status_code == 200, echoed.text
    body = echoed.json()
    assert body["resale_price_scope"] == "model"
    assert body["resale_price_source"] == "median of 18 live listings"
    assert body["estimated_new_price_source"] == "melin retail"
    assert body["owner_notes"] == "still mine"

    changed = (await client.put(f"/api/hats/{hat_id}", json={"resale_price": 90.0})).json()
    assert changed["resale_price_scope"] == "manual"
    assert changed["resale_price_source"] == "Entered manually"


# ------------- condition- and size-matched comparables (v2.21) --------- #
#
# The listed price IS the sale price here: fixed-price marketplace, automatic
# drops, no negotiation. So comparability comes from FILTERING, not from
# discounting. This used to median across every condition and leave the caller
# to multiply by a guessed factor — guesses that measured wrong against 706
# live listings (new-without-tags is 0.95 of new-with-tags, not 0.92; worn is
# 0.82, not 0.78) and were never needed with the real number in the feed.


async def test_median_is_scoped_to_the_hats_condition(monkeypatch):
    from headroom.services.melin_recap import fetch_resale_stats

    _stub_query(monkeypatch, [
        _listing("A-Game Hydro - Red", 10000, condition="new_with_tags"),
        _listing("A-Game Hydro - Gray", 10000, condition="new_with_tags"),
        _listing("A-Game Hydro - Navy", 10000, condition="new_with_tags"),
        _listing("A-Game Hydro - Bone", 5000, condition="excellent"),
        _listing("A-Game Hydro - Tan", 5000, condition="excellent"),
        _listing("A-Game Hydro - Sand", 5000, condition="excellent"),
    ])
    worn = await fetch_resale_stats("a_game", "A-Game Hydro", condition="worn")
    assert worn["median"] == 50.0, "a worn hat is priced against worn listings"
    assert worn["condition_matched"] is True

    tagged = await fetch_resale_stats("a_game", "A-Game Hydro", condition="new_with_tags")
    assert tagged["median"] == 100.0
    # Before this, both got one median across everything — 75 apiece.


async def test_size_narrows_further_when_the_sample_allows(monkeypatch):
    from headroom.services.melin_recap import fetch_resale_stats

    _stub_query(monkeypatch, [
        _listing("A-Game Hydro - A", 12000, size="XL"),
        _listing("A-Game Hydro - B", 12000, size="XL"),
        _listing("A-Game Hydro - C", 12000, size="XL"),
        _listing("A-Game Hydro - D", 6000, size="C"),
        _listing("A-Game Hydro - E", 6000, size="C"),
        _listing("A-Game Hydro - F", 6000, size="C"),
    ])
    stats = await fetch_resale_stats(
        "a_game", "A-Game Hydro", condition="new_with_tags", size="x_large"
    )
    assert stats["median"] == 120.0
    assert stats["size_matched"] is True


async def test_it_widens_rather_than_answering_from_one_listing(monkeypatch):
    """Falling back beats answering from a sample too small to mean anything."""
    from headroom.services.melin_recap import fetch_resale_stats

    _stub_query(monkeypatch, [
        _listing("A-Game Hydro - A", 9000, condition="new_with_tags", size="XL"),
        _listing("A-Game Hydro - B", 6000, condition="new_with_tags", size="C"),
        _listing("A-Game Hydro - C", 6000, condition="new_with_tags", size="C"),
        _listing("A-Game Hydro - D", 6000, condition="new_with_tags", size="C"),
    ])
    # Only ONE x_large — too few, so size is dropped and condition is kept.
    stats = await fetch_resale_stats(
        "a_game", "A-Game Hydro", condition="new_with_tags", size="x_large"
    )
    assert stats["size_matched"] is False
    assert stats["condition_matched"] is True
    assert stats["count"] == 4


async def test_an_unknown_marketplace_condition_counts_as_worn(monkeypatch):
    """An unrecognized condition is certainly not new. Guessing "new" would
    quietly inflate every valuation that used it."""
    from headroom.services.melin_recap import fetch_resale_stats

    _stub_query(monkeypatch, [
        _listing("A-Game Hydro - A", 4000, condition="beat_to_hell"),
        _listing("A-Game Hydro - B", 4000, condition="good"),
        _listing("A-Game Hydro - C", 4000, condition="fair"),
    ])
    stats = await fetch_resale_stats("a_game", "A-Game Hydro", condition="worn")
    assert stats["condition_matched"] is True
    assert stats["median"] == 40.0


async def test_no_condition_given_still_works(monkeypatch):
    """Back-compat: a caller that states no condition gets the old behavior."""
    from headroom.services.melin_recap import fetch_resale_stats

    _stub_query(monkeypatch, [
        _listing("A-Game Hydro - A", 8000),
        _listing("A-Game Hydro - B", 9000),
        _listing("A-Game Hydro - C", 10000),
    ])
    stats = await fetch_resale_stats("a_game", "A-Game Hydro")
    assert stats["median"] == 90.0
    assert stats["condition_matched"] is False


async def test_the_source_label_names_what_was_matched(monkeypatch):
    """"median of 8 live listings" gives no way to tell a figure drawn from
    this exact hat in this condition from one drawn from the whole category."""
    from headroom.models.hat import Hat
    from headroom.services.hat_analysis_pipeline import refresh_melin_resale

    _stub_query(monkeypatch, [
        _listing("A-Game Hydro - A", 8000, condition="excellent", size="C"),
        _listing("A-Game Hydro - B", 9000, condition="excellent", size="C"),
        _listing("A-Game Hydro - C", 10000, condition="excellent", size="C"),
    ])
    hat = Hat(condition="worn", size="classic", style="a_game", brand="Melin",
              model_name="A-Game Hydro")
    await refresh_melin_resale(hat)
    assert hat.resale_price == 90.0
    assert "classic" in hat.resale_price_source
    assert "worn" in hat.resale_price_source
    # Names the line, not the bare word "model" — see the note in
    # test_refresh_melin_resale_persists_median.
    assert "A Game Hydro listings" in hat.resale_price_source
    assert "category" not in hat.resale_price_source


# --------------------------------------------------------------------------- #
# Pricing against the right comparables
#
# Reported as "the resale values are all very wrong". Three separate defects,
# measured against the live marketplace on the real collection:
#
#   * One unpaginated page. The odysea category holds 436 listings; the query
#     read 100 and called it the market. `meta.totalItems` was in every
#     response and discarded.
#   * Punctuation glued to tokens, so `Odysea Hydro "Have More Fun"` demanded
#     `"have` and `fun"` — strings in no listing title, guaranteeing zero
#     matches.
#   * No step between "every token matches" and "the whole category", so 28
#     different hats were all priced at the identical $115.00.
# --------------------------------------------------------------------------- #


def _stub_pages(monkeypatch, pages):
    """Serve a different page per call, so pagination is actually exercised."""
    calls: list[dict] = []

    async def _fake_query(params):
        calls.append(dict(params))
        idx = int(params.get("page", 1)) - 1
        return pages[idx] if idx < len(pages) else []

    monkeypatch.setattr("headroom.services.melin_recap.query_listings", _fake_query)
    return calls


async def test_every_page_of_the_category_is_read_not_just_the_first(monkeypatch):
    """The odysea category has 436 listings and the app was reading 100.

    Every Odysea in the collection was then priced off whichever quarter the
    API happened to return first — which is how 28 different hats landed on
    the identical $115.00.
    """
    import headroom.services.melin_recap as mr

    monkeypatch.setattr(mr, "PAGE_SIZE", 2)
    calls = _stub_pages(monkeypatch, [
        [_listing("Odysea Rope Hydro - A", 7000), _listing("Odysea Rope Hydro - B", 8000)],
        [_listing("Odysea Rope Hydro - C", 9000), _listing("Odysea Rope Hydro - D", 10000)],
        [_listing("Odysea Rope Hydro - E", 20000)],  # short page ends the walk
    ])

    rows = await mr.query_all_listings({"pub_category": "odysea"})

    assert len(rows) == 5, "a short page ends the walk; everything before it counts"
    assert [c["page"] for c in calls] == [1, 2, 3]
    assert len(calls) == 3, "must stop at the short page, not keep asking forever"


async def test_the_page_walk_is_bounded(monkeypatch):
    """Somebody else's public API — a full page every time must not loop away."""
    import headroom.services.melin_recap as mr

    monkeypatch.setattr(mr, "PAGE_SIZE", 1)
    calls = _stub_pages(monkeypatch, [[_listing(f"Odysea {i}", 7000)] for i in range(50)])

    await mr.query_all_listings({"pub_category": "odysea"}, max_pages=4)
    assert len(calls) == 4


async def test_punctuation_does_not_make_a_model_unmatchable(monkeypatch):
    """`Odysea Hydro "Have More Fun"` demanded the tokens `"have` and `fun"`.

    No listing title contains those, so the model tier matched nothing and the
    hat fell silently to a category median — indistinguishable, in the UI, from
    a real appraisal.
    """
    from headroom.services.melin_recap import fetch_resale_stats

    _stub_query(monkeypatch, [
        _listing("Odysea Hydro - Have More Fun", 8000),
        _listing("Odysea Hydro - Have More Fun", 9000),
        _listing("Odysea Hydro - Have More Fun", 10000),
        _listing("Odysea Rope - Black", 2000),
        _listing("Odysea Stacked - Gray", 2000),
    ])

    stats = await fetch_resale_stats("odysea", 'Odysea Hydro "Have More Fun"')
    assert stats["sample"] == "model"
    assert stats["count"] == 3
    assert stats["median"] == 90.0


async def test_an_unmatchable_design_falls_to_its_LINE_not_the_category(monkeypatch):
    """The missing rung.

    `Odysea Rope Hydro (WATERCOLOR)` has no listings of that exact artwork, so
    the old code jumped straight to the median of all 436 Odyseas. Dropping one
    token lands on `Odysea Rope Hydro` — same product, different colorway,
    which is a real comparable.
    """
    from headroom.services.melin_recap import fetch_resale_stats

    _stub_query(monkeypatch, [
        _listing("Odysea Rope Hydro - Black", 7000),
        _listing("Odysea Rope Hydro - Sand", 8000),
        _listing("Odysea Rope Hydro - Navy", 9000),
        _listing("Odysea Stacked Thermal - Camo", 30000),
        _listing("Odysea Brimless - Red", 1000),
        _listing("Odysea Coast - Blue", 1000),
    ])

    stats = await fetch_resale_stats("odysea", "Odysea Rope Hydro (WATERCOLOR)")
    assert stats["sample"] == "model"
    assert stats["matched"] == "Odysea Rope Hydro"
    assert stats["count"] == 3
    assert stats["median"] == 80.0, (
        "the line's own median — not the category's, which the outliers skew"
    )


async def test_a_prefix_that_selects_the_whole_category_is_reported_as_category(
    monkeypatch,
):
    """Honesty about how broad the comparison really was.

    Token count cannot decide this: for an `a_game` hat the prefix `a game` has
    two tokens and still selects the entire aGame category. Asking whether the
    prefix excluded anything answers the same question from the data.
    """
    from headroom.services.melin_recap import fetch_resale_stats

    _stub_query(monkeypatch, [
        _listing("A-Game Hydro - Red", 8000),
        _listing("A-Game Scout - Grey", 2000),
        _listing("A-Game Classic - Navy", 5000),
    ])

    stats = await fetch_resale_stats("a_game", "A-Game Hydro")
    assert stats["sample"] == "category"
    assert stats["matched"] is None, (
        "`a game` matched every listing here, so it is the category wearing a "
        "model's name"
    )


async def test_condition_is_kept_while_the_model_is_shortened(monkeypatch):
    """Condition comes off a listing as a fact; the model prefix is a guess
    about naming. So the guess is relaxed first."""
    from headroom.services.melin_recap import fetch_resale_stats

    _stub_query(monkeypatch, [
        _listing("Odysea Rope Hydro - A", 5000, condition="worn"),
        _listing("Odysea Rope Hydro - B", 6000, condition="worn"),
        _listing("Odysea Rope Hydro - C", 7000, condition="worn"),
        _listing("Odysea Rope Hydro Watercolor - D", 30000, condition="new_with_tags"),
    ])

    stats = await fetch_resale_stats("odysea", "Odysea Rope Hydro Watercolor", "worn")
    assert stats["condition_matched"] is True
    assert stats["median"] == 60.0, "the worn line, not the one tagged example"


# --------------------------------------------------------------------------- #
# Pricing against melin's OWN product
#
# "can't you just get prices from recap?" — yes. Every listing publishes
# `shopifyProductName` ("Trenches Icon Hydro - Prismatic") and a structured
# `selectedVariantOptions.color`, on 986 of 986 listings across 510 distinct
# products. Pricing ignored all of it and token-matched the freeform title, so a
# short line matched everything in it and 76 hats shared one price.
# --------------------------------------------------------------------------- #


def _product(cents, name, color, condition="new_with_tags", size="C"):
    """A listing as the marketplace really sends one.

    The `title` mirrors `shopifyProductName` because that is what the real
    payload does — an earlier version passed a stub title, which quietly made
    the title-matching ladder unable to match anything and turned a fall-through
    assertion into a fixture artifact.
    """
    li = _listing(name, cents, condition=condition, size=size)
    li["attributes"]["publicData"]["shopifyProductName"] = name
    li["attributes"]["publicData"]["selectedVariantOptions"] = {"color": color}
    return li


async def test_a_hat_is_priced_against_its_own_product_not_its_line(monkeypatch):
    """The whole point. Two colorways of one line are different goods."""
    from headroom.services.melin_recap import fetch_resale_stats

    _stub_query(monkeypatch, [
        _product(6700, "Trenches Icon Hydro - Faded Black", "Faded Black"),
        _product(6800, "Trenches Icon Hydro - Faded Black", "Faded Black"),
        _product(12000, "Trenches Icon Hydro - Prismatic", "Prismatic"),
        _product(12000, "Trenches Icon Hydro - Prismatic", "Prismatic"),
        _product(9000, "Trenches Icon Hydro - Navy", "Navy"),
    ])

    stats = await fetch_resale_stats(
        "trenches", "Trenches Icon Hydro", "new_with_tags", "classic",
        colorway="Faded Black",
    )
    assert stats["matched"] == "Trenches Icon Hydro - Faded Black"
    assert stats["median"] == 67.5, "its own colorway, not the line's median"
    assert stats["count"] == 2
    assert stats["sample"] == "model"


async def test_a_colorway_token_may_not_be_satisfied_by_the_model_half(monkeypatch):
    """`<Model> - <Colorway>` has two halves and they mean different things.

    The product match used to union the hat's model tokens with its colorway
    tokens and test the whole set against the whole product name. That let a
    token satisfy the WRONG side: a hat whose model is `Trenches Hydro` and
    whose colorway is `Icon` produced `{trenches, hydro, icon}`, which is a
    subset of `Trenches Icon Hydro - Camo` — so the hat priced as a product
    whose colorway is Camo, purely because "icon" appears in the model half.

    melin's naming convention is the reason this module can price a hat as its
    own item at all; ignoring which half a word came from throws that away.
    Here the only Camo listing is expensive and the Icon ones are cheap, so a
    cross-half match is visible in the number rather than only in the label.
    """
    from headroom.services.melin_recap import fetch_resale_stats

    _stub_query(monkeypatch, [
        _product(20000, "Trenches Icon Hydro - Camo", "Camo"),
        _product(6000, "Trenches Hydro - Icon", "Icon"),
        _product(6000, "Trenches Hydro - Icon", "Icon"),
    ])

    stats = await fetch_resale_stats(
        "trenches", "Trenches Hydro", "new_with_tags", "classic", colorway="Icon",
    )
    assert stats["matched"] == "Trenches Hydro - Icon", (
        "the product whose COLORWAY half is Icon — not the one that merely "
        "contains the word in its model half"
    )
    assert stats["median"] == 60.0


async def test_a_single_word_colorway_is_not_every_colorway_containing_it(monkeypatch):
    """The colorway half is matched by EQUALITY, not containment.

    `Camo`, `Rain Camo` and `Hawaii 808 Camo` are three products. Under token
    containment a hat whose colorway is `Camo` matched all three — under the
    `_MAX_PRODUCTS` ceiling, so it was still called a product match — and was
    priced as their combined median, labeled as its own item. Single-word
    colorways are the common case (Camo, Black, Navy, Bone), so this was the
    typical shape, not an edge. `catalog_service.is_real_product` already used
    equality for the same reason; the two validators now agree. The expensive
    Rain Camo rows make a leak visible in the number, not only the label.
    """
    from headroom.services.melin_recap import fetch_resale_stats

    _stub_query(monkeypatch, [
        _product(6000, "Trenches Icon Hydro - Camo", "Camo"),
        _product(6200, "Trenches Icon Hydro - Camo", "Camo"),
        _product(20000, "Trenches Icon Hydro - Rain Camo", "Rain Camo"),
        _product(20000, "Trenches Icon Hydro - Hawaii 808 Camo", "Hawaii 808 Camo"),
    ])

    stats = await fetch_resale_stats(
        "trenches", "Trenches Icon Hydro", "new_with_tags", "classic", colorway="Camo",
    )
    assert stats["matched"] == "Trenches Icon Hydro - Camo"
    assert stats["median"] == 61.0, "Camo's own two listings, not the Rain/808 ones"
    assert stats["count"] == 2


async def test_one_live_listing_of_the_right_product_beats_a_line_median(monkeypatch):
    """No minimum sample for a product match.

    On a fixed-price marketplace one listing of THIS product is a better answer
    than the median of a line it merely belongs to — and `count` is published,
    so a thin sample is visible rather than disguised.
    """
    from headroom.services.melin_recap import fetch_resale_stats

    _stub_query(monkeypatch, [
        _product(9950, "Trenches Icon Hydro - Prismatic", "Prismatic"),
        _product(5000, "Trenches Icon Hydro - Black", "Black"),
        _product(5000, "Trenches Icon Hydro - Navy", "Navy"),
        _product(5000, "Trenches Icon Hydro - Sand", "Sand"),
    ])

    stats = await fetch_resale_stats(
        "trenches", "Trenches Icon Hydro", "new_with_tags", "classic",
        colorway="Prismatic",
    )
    assert stats["median"] == 99.5
    assert stats["count"] == 1, "thin, and said so"


async def test_without_a_colorway_there_is_no_product_to_identify(monkeypatch):
    """A hat with no colorway names a LINE. Calling that a product match is how
    319 listings across 131 products became one hat's 'exact' price."""
    from headroom.services.melin_recap import fetch_resale_stats

    _stub_query(monkeypatch, [
        _product(6000, "Trenches Icon Hydro - Black", "Black"),
        _product(8000, "Trenches Icon Hydro - Navy", "Navy"),
        _product(10000, "Trenches Icon Hydro - Sand", "Sand"),
    ])

    stats = await fetch_resale_stats(
        "trenches", "Trenches Icon Hydro", "new_with_tags", "classic", colorway=None,
    )
    # The numbers alone do not distinguish the two paths here — with the guard
    # removed the product tier also matches all three and returns the same
    # median, so an assertion on `median` passes either way. What separates
    # them is WHAT was matched: the ladder names the line, the product tier
    # names goods, and a melin product name always carries its colorway.
    assert stats["matched"] == "Trenches Icon Hydro"
    assert " - " not in (stats["matched"] or ""), (
        "a line, not a product — without a colorway there is no item to name"
    )


async def test_matching_too_many_products_is_not_a_product_match(monkeypatch):
    """Tokens that select a whole shelf named a line, not an item."""
    from headroom.services.melin_recap import fetch_resale_stats

    _stub_query(monkeypatch, [
        _product(6000, f"Trenches Icon Hydro - Camo {i}", "Camo") for i in range(6)
    ])

    stats = await fetch_resale_stats(
        "trenches", "Trenches Icon Hydro", "new_with_tags", "classic", colorway="Camo",
    )
    assert stats["matched"] != "Trenches Icon Hydro - Camo 0"


async def test_a_stated_construction_vetoes_a_rival_product(monkeypatch):
    """melin sells Icon Hydro and Icon Thermal as different goods at different
    prices. Measured on the real collection, without this veto a hat matched
    `Trenches Icon Thermal - Military` and moved $82.50 to $65.00 on one
    listing of the wrong product. Same veto `catalog_service` already applies.
    """
    from headroom.services.melin_recap import fetch_resale_stats

    _stub_query(monkeypatch, [
        _product(6500, "Trenches Icon Thermal - Military", "Military"),
        _product(8000, "Trenches Icon Hydro - Black", "Black"),
        _product(8500, "Trenches Icon Hydro - Navy", "Navy"),
        _product(9000, "Trenches Icon Hydro - Sand", "Sand"),
    ])

    stats = await fetch_resale_stats(
        "trenches", "Trenches Icon", "new_with_tags", "classic",
        colorway="Military", construction="HYDRO",
    )
    assert stats["matched"] != "Trenches Icon Thermal - Military", (
        "a HYDRO hat must never be priced off a Thermal"
    )


async def test_a_blank_construction_vetoes_nothing(monkeypatch):
    """A blank construction is "nobody has looked", which rules nothing out —
    the same reading `_apply_construction` documents."""
    from headroom.services.melin_recap import fetch_resale_stats

    _stub_query(monkeypatch, [
        _product(6500, "Trenches Icon Thermal - Military", "Military"),
    ])

    stats = await fetch_resale_stats(
        "trenches", "Trenches Icon", "new_with_tags", "classic",
        colorway="Military", construction=None,
    )
    assert stats["matched"] == "Trenches Icon Thermal - Military"


async def test_a_construction_word_in_the_COLORWAY_half_vetoes_nothing(monkeypatch):
    """The inversion that shipped in 2.71.0.

    `Denim`, `Canvas`, `Suede`, `Linen` and `Corduroy` are constructions AND
    common colorway words, and melin names products `<Model> - <Colorway>`.
    Reading the whole string made `Trenches Icon Hydro - Denim` look like a
    Denim product, so a HYDRO hat was vetoed from its OWN item and fell back to
    the line median — a correctly recorded construction made pricing WORSE than
    leaving it blank. CLAUDE.md documents this trap with this same example.
    """
    from headroom.services.melin_recap import fetch_resale_stats

    _stub_query(monkeypatch, [
        _product(8200, "Trenches Icon Hydro - Denim", "Denim"),
        _product(8300, "Trenches Icon Hydro - Denim", "Denim"),
        _product(5000, "Trenches Icon Hydro - Black", "Black"),
        _product(5000, "Trenches Icon Hydro - Navy", "Navy"),
    ])

    stats = await fetch_resale_stats(
        "trenches", "Trenches Icon Hydro", "new_with_tags", "classic",
        colorway="Denim", construction="HYDRO",
    )
    assert stats["matched"] == "Trenches Icon Hydro - Denim"
    assert stats["median"] == 82.5


async def test_a_construction_in_the_MODEL_half_still_vetoes(monkeypatch):
    """Only the colorway half is exempt — the model half is the claim."""
    from headroom.services.melin_recap import fetch_resale_stats

    _stub_query(monkeypatch, [
        _product(6500, "Trenches Icon Denim - Black", "Black"),
        _product(8000, "Trenches Icon Hydro - Sand", "Sand"),
        _product(8000, "Trenches Icon Hydro - Navy", "Navy"),
        _product(8000, "Trenches Icon Hydro - Gray", "Gray"),
    ])

    stats = await fetch_resale_stats(
        "trenches", "Trenches Icon", "new_with_tags", "classic",
        colorway="Black", construction="HYDRO",
    )
    assert stats["matched"] != "Trenches Icon Denim - Black"


async def test_hydro_and_hydrolite_veto_each_other(monkeypatch):
    """`HYDRO` is a SUBSTRING of `HYDROLite` and they are different products at
    different prices — the confusion CLAUDE.md warns about repeatedly."""
    from headroom.services.melin_recap import _rival_construction

    assert _rival_construction("Trenches Icon HYDROLite - Black", "HYDRO") is True
    assert _rival_construction("Trenches Icon Hydro - Black", "HYDROLite") is True
    assert _rival_construction("Trenches Icon Hydro - Black", "HYDRO") is False


async def test_a_product_naming_no_construction_contradicts_nothing(monkeypatch):
    """Veto on CONTRADICTION, not absence — the test `catalog_service` applies.

    `Trenches Icon - Denim` is the case that discriminates BOTH halves of this
    fix at once, and picking a plain color here would have pinned neither:

      * whole-string reading  -> theirs={Denim}, mine={HYDRO}, no overlap -> VETO
      * model-half reading    -> theirs={},                            -> no veto

    So a product that names no construction in its model half, with a
    construction WORD as its colorway, is the only shape that fails if either
    the split or the contradiction rule is reverted.
    """
    from headroom.services.melin_recap import _rival_construction

    assert _rival_construction("Trenches Icon - Denim", "HYDRO") is False
    assert _rival_construction("Trenches Icon - Black", "HYDRO") is False


async def test_the_source_names_only_the_products_that_set_the_number(monkeypatch):
    """`products` was computed BEFORE the condition/size narrowing, so a hat
    priced by one listing was labeled with three — including a Thermal that
    had no part in it."""
    from headroom.services.melin_recap import fetch_resale_stats

    _stub_query(monkeypatch, [
        _product(9000, "Trenches Icon Hydro - Maroon", "Maroon", condition="new_with_tags"),
        _product(4000, "Trenches Icon Hydro - Heather Maroon", "Maroon", condition="worn"),
    ])

    stats = await fetch_resale_stats(
        "trenches", "Trenches Icon Hydro", "new_with_tags", "classic", colorway="Maroon",
    )
    assert stats["count"] == 1
    assert stats["matched"] == "Trenches Icon Hydro - Maroon", (
        "the worn Heather Maroon did not price this hat and must not be cited"
    )


from headroom.services.melin_recap import query_listings as _REAL_QUERY_LISTINGS


async def test_the_pages_of_one_sweep_share_one_connection_pool(monkeypatch):
    """`query_all_listings` opened a new `httpx.AsyncClient` — a TCP + TLS
    handshake — per page: six per pricing call, up to 450 per harvest. Inside
    `shared_client()` every page reuses one pool, while `query_listings(params)`
    keeps the one-argument signature fourteen stubs rely on. Below the stub is
    one level down, at `_query_with`, so the real `query_listings` runs and the
    client it was handed is what gets counted."""
    import headroom.services.melin_recap as mr

    built: list[int] = []
    used: list[int] = []
    real_client = mr.httpx.AsyncClient

    class _CountingClient(real_client):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            built.append(id(self))

    class _Resp:
        status_code = 200

        def __init__(self, rows):
            self._rows = rows

        def json(self):
            return {"data": self._rows}

    async def _fake_query_with(client, params):
        used.append(id(client))
        page = params["page"]
        return _Resp([{"n": page}] * (mr.PAGE_SIZE if page < 3 else 1))

    monkeypatch.setattr(mr.httpx, "AsyncClient", _CountingClient)
    monkeypatch.setattr(mr, "_query_with", _fake_query_with)
    # The autouse network guard replaces `query_listings` wholesale; this test
    # needs the REAL one to run (its network is stubbed one level down), so
    # restore the original for this test only. Still no live call: `_query_with`
    # is the fake above.
    monkeypatch.setattr(mr, "query_listings", _REAL_QUERY_LISTINGS)

    rows = await mr.query_all_listings({"pub_category": "odysea"})

    assert len(rows) == 2 * mr.PAGE_SIZE + 1, "three pages were read"
    assert len(used) == 3
    assert len(built) == 1, f"one pool for the sweep, not one per page: {len(built)}"
    assert len(set(used)) == 1

    # Outside a sweep a lone call still gets (and closes) its own client.
    built.clear()
    await mr.query_listings({"pub_category": "odysea", "page": 3})
    assert len(built) == 1
