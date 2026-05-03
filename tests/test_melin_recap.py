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
