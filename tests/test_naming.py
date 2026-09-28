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


async def test_one_rule_for_same_name_across_matcher_vocabulary_and_duplicates():
    """Three normalizers disagreed: the tokens were accent-SENSITIVE, the
    vocabulary's fold accent-blind but punctuation-sensitive, and duplicate
    detection borrowed the vocabulary's. `Piña`/`Pina` was one colorway on
    write and two products to the matcher; `A-Game`/`A Game` one model to the
    matcher and two hats to the duplicate report."""
    assert naming.token_set("Piña") == naming.token_set("PINA") == frozenset({"pina"})
    assert naming.name_key("A-Game Hydro") == naming.name_key("a game  hydro") == "a game hydro"
    assert naming.name_key("Ｐiña") == "pina"
    # Ordered: a spelling is a sequence, not a bag of words.
    assert naming.name_key("Grey Heather") != naming.name_key("Heather Grey")


async def test_both_services_read_a_name_the_same_way():
    # Both services read names with `naming` directly — their wrappers
    # (`catalog_service._model_tokens`, `melin_recap.model_tokens`) are gone —
    # so this is checked by behavior: punctuation and a fullwidth letter in
    # the product name must not stop the hat matching it.
    listing = melin_recap.Listing(
        title="", price=50.0, condition=None, size=None,
        product='Odysea Hydro "Have More Fun" - Ｂlack',
    )
    comp = melin_recap._product_comp([listing], 'Odysea Hydro "Have More Fun"', "Black", None, None)
    assert comp is not None, "the marketplace read the name differently from `naming`"


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
        assert catalog_service.parse_listing_title(title) == naming.split_model_colorway(title)


async def test_a_title_naming_no_model_does_not_file_a_colorway_under_an_empty_model():
    model, colorway = catalog_service.parse_listing_title(" - Black")
    assert model == "" and colorway is None
