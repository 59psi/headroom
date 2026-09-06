"""One tokenizer, one splitter, both sides of every comparison.

`catalog_service._model_tokens` split on whitespace while
`melin_recap.model_tokens` stripped punctuation, so `Odysea Hydro "Have More
Fun"` was priceable on the marketplace and unmatchable against its own
receipt; neither read a fullwidth `Ｏ`; the harvest split titles on `" - "`
only while the analyzer's repair split on em dashes too.
"""

from __future__ import annotations

import pytest

from headroom.services import catalog_service, melin_recap, naming
from headroom.services.hat_analysis_pipeline import _split_model_and_colorway

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize(
    "text, expected",
    [
        ('Odysea Hydro "Have More Fun"', ("odysea", "hydro", "have", "more", "fun")),
        ("A-Game Hydro", ("a", "game", "hydro")),
        ("Trenches Thermal - Camo", ("trenches", "thermal", "camo")),
        ("A—Game", ("a", "game")),
        ("Ｏdysea Ｈydro", ("odysea", "hydro")),
        ("  spaced   out ", ("spaced", "out")),
        ("", ()),
        (None, ()),
    ],
)
async def test_tokens_read_punctuation_dashes_and_fullwidth_as_separators(text, expected):
    assert naming.tokens(text) == expected


async def test_both_services_read_a_name_the_same_way():
    name = 'Odysea Hydro "Have More Fun" — Ｂlack'
    assert set(melin_recap.model_tokens(name)) == set(catalog_service._model_tokens(name))
    assert catalog_service._model_tokens(name) == naming.token_set(name)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("A-Game Hydro - Heather Grey", ("A-Game Hydro", "Heather Grey")),
        ("Trenches Hydro — Hawaii 808", ("Trenches Hydro", "Hawaii 808")),
        ("Trenches Hydro – Camo", ("Trenches Hydro", "Camo")),
        ("Odysea Rope Hydro (WATERCOLOR)", ("Odysea Rope Hydro", "WATERCOLOR")),
        ("Heather Ocean / Heather Charcoal", ("Heather Ocean / Heather Charcoal", None)),
        ("A-Game Hydro", ("A-Game Hydro", None)),
        (" - Black", (None, "Black")),
        ("Trenches -", ("Trenches -", None)),
        ("", (None, None)),
    ],
)
async def test_the_splitter_takes_spaced_separators_only(text, expected):
    assert naming.split_model_colorway(text) == expected


async def test_the_harvest_and_the_analyzer_repair_split_alike():
    for title in ("Trenches Hydro — Hawaii 808", "A-Game Hydro - Heather Grey", "Odysea Hydro"):
        assert catalog_service.parse_listing_title(title) == _split_model_and_colorway(title)


async def test_a_title_naming_no_model_does_not_file_a_colorway_under_an_empty_model():
    model, colorway = catalog_service.parse_listing_title(" - Black")
    assert model == "" and colorway is None
