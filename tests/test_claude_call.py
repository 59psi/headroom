"""The Claude Vision call itself — request shape and failure translation.

`claude_analysis` sat at 57%, and the gap was `analyze_hat_image`: the most
expensive, most externally-dependent call in the app, and the one nothing
exercised. Everything else stubs it at the seam (which is right — the house
rule is that the suite never calls a live API), with the consequence that the
seam's own contract went unchecked.

Two things are worth pinning. The REQUEST, because owner-stated facts are sent
as ground truth and a hat coming back mis-identified because its construction
was silently dropped is invisible from the outside — that exact bug shipped
once. And the FAILURE TRANSLATION, because every caller catches
`ClaudeAnalysisError` and degrades; anything else escaping takes the run down.

The client is replaced through `_anthropic_client`, the ONE seam that builds
an `AsyncAnthropic` — the same seam `test_claude_call_shape.py` uses to drive
the real SDK against an in-memory transport. This file used to patch the
`AsyncAnthropic` name itself, which was a second seam for one call and one the
module could stop honoring without any test noticing. No key is needed and no
request leaves the process.
"""

from __future__ import annotations

import base64

import pytest
from PIL import Image

from headroom.services import claude_analysis
from headroom.services.claude_analysis import ClaudeAnalysisError

pytestmark = pytest.mark.anyio


def _photo(tmp_path):
    path = tmp_path / "hat.jpg"
    Image.new("RGB", (64, 64), (30, 40, 90)).save(path, "JPEG")
    return path


class _Block:
    type = "tool_use"

    def __init__(self, payload):
        self.input = payload


class _Message:
    def __init__(self, payload):
        self.content = [_Block(payload)]


_GOOD = {
    "brand": "Melin", "logo_detected": None, "construction": None,
    "artist_series": None, "model_name": "A-Game", "model_confidence": "high",
    "style_descriptor": "snapback", "design_notes": "notes",
    "estimated_new_price_usd": 79.0,
    "colors": [{"name": "navy", "hex": "#1c2541", "tier": "primary"}],
}


def _stub_client(monkeypatch, *, payload=None, raises=None, capture=None):
    class _Messages:
        async def create(self, **kw):
            if capture is not None:
                capture.update(kw)
            if raises is not None:
                raise raises
            return _Message(payload if payload is not None else _GOOD)

    class _Client:
        def __init__(self, **_kw):
            self.messages = _Messages()

        # The real client is used as `async with`, so the pool it owns is
        # closed after each analysis; the stub has to speak the same protocol.
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(claude_analysis, "_anthropic_client", lambda api_key, timeout, **kw: _Client())


# ---- the request ------------------------------------------------------ #


async def test_a_missing_key_never_reaches_the_network(tmp_path):
    """Checked before the client is built, so an unconfigured install cannot
    accidentally issue an unauthenticated request."""
    with pytest.raises(ClaudeAnalysisError, match="No Anthropic API key"):
        await claude_analysis.analyze_hat_image(_photo(tmp_path), "")


async def test_the_photo_is_sent_as_base64_with_its_media_type(monkeypatch, tmp_path):
    capture: dict = {}
    _stub_client(monkeypatch, capture=capture)
    photo = _photo(tmp_path)

    await claude_analysis.analyze_hat_image(photo, "sk-ant-test")

    image = capture["messages"][0]["content"][0]
    assert image["source"]["media_type"] == "image/jpeg"
    assert base64.b64decode(image["source"]["data"]) == photo.read_bytes()


async def test_the_owners_stated_construction_is_sent_as_ground_truth(
    monkeypatch, tmp_path
):
    """This is the bug that shipped in 2.17.

    The construction was never sent, so a hat the owner had recorded as
    Thermal came back named "A-Game HYDROLite" — right field, wrong name in
    the one a person actually reads.
    """
    capture: dict = {}
    _stub_client(monkeypatch, capture=capture)

    await claude_analysis.analyze_hat_image(
        _photo(tmp_path), "sk-ant-test",
        selected_style="a_game", selected_construction="Thermal",
    )

    text = capture["messages"][0]["content"][1]["text"]
    assert "Thermal" in text


async def test_known_series_are_offered_as_a_record_not_a_menu(monkeypatch, tmp_path):
    """A series is rarely legible in a photo, so an analyzer recalling them
    unaided misses most of them — but a candidate LIST invites a forced choice,
    and a wrong series is indistinguishable from a right one."""
    capture: dict = {}
    _stub_client(monkeypatch, capture=capture)

    await claude_analysis.analyze_hat_image(
        _photo(tmp_path), "sk-ant-test", known_series=["Skye Walker"],
    )

    text = capture["messages"][0]["content"][1]["text"]
    assert "Skye Walker" in text


async def test_the_tool_is_forced_so_the_reply_is_always_structured(
    monkeypatch, tmp_path
):
    """Prose would have to be parsed, and a parser for free text is a second
    failure mode on top of the one this call already has."""
    capture: dict = {}
    _stub_client(monkeypatch, capture=capture)

    await claude_analysis.analyze_hat_image(_photo(tmp_path), "sk-ant-test")

    assert capture["tool_choice"]["type"] == "tool"
    assert capture["tool_choice"]["name"] == "record_hat_analysis"


async def test_the_system_prompt_is_cached(monkeypatch, tmp_path):
    """It is long and identical on every call — a bulk re-analyze of 234 hats
    would otherwise pay for it 234 times."""
    capture: dict = {}
    _stub_client(monkeypatch, capture=capture)

    await claude_analysis.analyze_hat_image(_photo(tmp_path), "sk-ant-test")

    assert capture["system"][0]["cache_control"] == {"type": "ephemeral"}


# ---- the response ----------------------------------------------------- #


async def test_a_tool_reply_becomes_a_HatAnalysis(monkeypatch, tmp_path):
    _stub_client(monkeypatch)

    result = await claude_analysis.analyze_hat_image(_photo(tmp_path), "sk-ant-test")

    assert result.brand == "Melin"
    assert result.model_name == "A-Game"
    assert result.colors[0].hex == "#1c2541"


async def test_a_reply_with_no_tool_block_is_an_error(monkeypatch, tmp_path):
    """Forced tool use makes this near-impossible, which is exactly why it
    must not be handled by indexing `[0]` and raising IndexError instead."""
    class _Empty:
        content = []

    class _Messages:
        async def create(self, **_kw):
            return _Empty()

    class _Client:
        def __init__(self, **_kw):
            self.messages = _Messages()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(claude_analysis, "_anthropic_client", lambda api_key, timeout, **kw: _Client())

    with pytest.raises(ClaudeAnalysisError):
        await claude_analysis.analyze_hat_image(_photo(tmp_path), "sk-ant-test")


# ---- failure translation ---------------------------------------------- #


async def test_a_bad_key_is_reported_as_a_bad_key(monkeypatch, tmp_path):
    """"Invalid Anthropic API key" is actionable; a stack trace is not."""
    from anthropic import AuthenticationError

    err = AuthenticationError.__new__(AuthenticationError)
    Exception.__init__(err, "401 unauthorized")
    _stub_client(monkeypatch, raises=err)

    with pytest.raises(ClaudeAnalysisError, match="Invalid Anthropic API key"):
        await claude_analysis.analyze_hat_image(_photo(tmp_path), "sk-ant-bad")


async def test_any_unexpected_failure_is_still_a_ClaudeAnalysisError(
    monkeypatch, tmp_path
):
    """Every caller catches this one type and degrades.

    Anything else escaping takes the whole analysis run down instead of
    marking one hat, which on a bulk re-analyze is the difference between one
    failure and two hundred.
    """
    _stub_client(monkeypatch, raises=RuntimeError("something new"))

    with pytest.raises(ClaudeAnalysisError):
        await claude_analysis.analyze_hat_image(_photo(tmp_path), "sk-ant-test")


async def test_an_unreadable_photo_is_a_ClaudeAnalysisError(tmp_path):
    with pytest.raises(ClaudeAnalysisError):
        await claude_analysis.analyze_hat_image(tmp_path / "gone.jpg", "sk-ant-test")
