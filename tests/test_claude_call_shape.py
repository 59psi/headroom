"""The Claude Vision call, through the real SDK, against an in-memory transport.

Every other test that touches analysis stubs `analyze_hat_image` — correctly,
since they are about what the pipeline does with an answer. The cost is that
nothing exercised the request this app actually sends or the response parsing
it actually does, so the SDK could change under us with the suite green. It
did: `anthropic` 0.122 → 1.2.0 is a major release that removed request
parameters and re-exports, and the only reason the upgrade was safe is that
this file was written to find out.

`httpx2.MockTransport` sits where the network would be. The SDK serializes our
kwargs into the wire request — that is what the handler inspects — and parses
the canned wire response into the `Message` our code reads. No mocking of
the SDK itself: a mock of `messages.create` would pass regardless of what the
SDK does with `system=[...cache_control...]`, `tool_choice`, or an image block.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx2
import pytest
from anthropic import AsyncAnthropic
from PIL import Image

from headroom.services import claude_analysis

pytestmark = pytest.mark.anyio


def _tool_use_response(tool_input: dict) -> dict:
    """The Messages API wire shape for a forced tool call."""
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-5",
        "stop_reason": "tool_use",
        "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 10},
        "content": [
            {"type": "tool_use", "id": "toolu_test", "name": "record_hat_analysis", "input": tool_input},
        ],
    }


def _wire(monkeypatch, responder):
    """Route the SDK at `responder(request) -> httpx2.Response`, capturing requests."""
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return responder(request)

    def fake_client(api_key, timeout, **kw):
        return AsyncAnthropic(
            api_key=api_key, timeout=timeout,
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
            max_retries=0,
        )

    monkeypatch.setattr(claude_analysis, "_anthropic_client", fake_client)
    return seen


@pytest.fixture
def hat_photo(tmp_path) -> Path:
    path = tmp_path / "hat.png"
    Image.new("RGBA", (8, 8), (10, 20, 30, 255)).save(path)
    return path


async def test_the_request_we_send_is_the_one_the_prompt_engineering_assumes(monkeypatch, hat_photo):
    """What goes over the wire, asserted on the wire.

    The cached system prompt, the forced tool, and the image-then-text order
    are each load-bearing (`SYSTEM_PROMPT` is cached across every hat; the
    tool choice is what guarantees a structured answer; the owner context
    follows the image). None was checked anywhere before this.
    """
    answer = {
        "brand": "melin", "logo_detected": "melin M", "artist_series": None,
        "model_name": "Odysea Hydro", "colorway": "Black", "model_confidence": "high",
        "style_descriptor": "structured", "design_notes": "",
        "estimated_new_price_usd": 79.0,
        "colors": [{"name": "Black", "hex": "#0a141e", "tier": "primary"}],
    }
    seen = _wire(monkeypatch, lambda req: httpx2.Response(200, json=_tool_use_response(answer)))

    result = await claude_analysis.analyze_hat_image(
        hat_photo, api_key="sk-ant-test", model="claude-sonnet-5",
        selected_style="odysea", known_series=["Links"],
    )

    assert len(seen) == 1
    req = seen[0]
    assert req.url.path == "/v1/messages"
    assert req.headers["x-api-key"] == "sk-ant-test"
    body = json.loads(req.content)

    assert body["model"] == "claude-sonnet-5"
    assert body["tool_choice"] == {"type": "tool", "name": "record_hat_analysis"}
    assert [t["name"] for t in body["tools"]] == ["record_hat_analysis"]
    # The system prompt is sent as a cached block — a cache miss on every hat
    # is the whole bill for a bulk re-analysis.
    assert body["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert body["system"][0]["text"] == claude_analysis.SYSTEM_PROMPT

    content = body["messages"][0]["content"]
    assert [c["type"] for c in content] == ["image", "text"], "image first, then the owner's facts"
    assert content[0]["source"]["media_type"] == "image/png"
    assert base64.b64decode(content[0]["source"]["data"])[:8] == b"\x89PNG\r\n\x1a\n"
    assert "odysea" in content[1]["text"].lower()
    assert "Links" in content[1]["text"], "the known series must reach the prompt"

    # And the SDK's parse of the wire response is what our code reads.
    assert result.model_name == "Odysea Hydro"
    assert result.colorway == "Black"
    assert result.estimated_new_price_usd == 79.0
    assert [c.hex for c in result.colors] == ["#0a141e"]
    assert result.raw == answer


async def test_a_text_only_answer_is_an_analysis_error_not_a_crash(monkeypatch, hat_photo):
    """`tool_choice` should make this impossible; the parser must still cope."""
    reply = _tool_use_response({})
    reply["content"] = [{"type": "text", "text": "I cannot see a hat."}]
    reply["stop_reason"] = "end_turn"
    _wire(monkeypatch, lambda req: httpx2.Response(200, json=reply))

    with pytest.raises(claude_analysis.ClaudeAnalysisError, match="tool_use"):
        await claude_analysis.analyze_hat_image(hat_photo, api_key="sk-ant-test")


async def test_a_rejected_key_is_reported_as_such(monkeypatch, hat_photo):
    """401 → `AuthenticationError` → the message the settings card shows.

    This is the exception whose import moved off a private module path in
    this change; the pipeline's "Invalid Anthropic API key" message depends
    on catching the right class.
    """
    _wire(monkeypatch, lambda req: httpx2.Response(
        401, json={"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}},
    ))

    with pytest.raises(claude_analysis.ClaudeAnalysisError, match="Invalid Anthropic API key"):
        await claude_analysis.analyze_hat_image(hat_photo, api_key="sk-ant-wrong")


async def test_an_overloaded_api_is_an_api_error_with_the_status_in_it(monkeypatch, hat_photo):
    """529 is the failure a bulk run actually meets; the retry card groups on this text."""
    _wire(monkeypatch, lambda req: httpx2.Response(
        529, json={"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}},
    ))

    with pytest.raises(claude_analysis.ClaudeAnalysisError, match="Anthropic API error"):
        await claude_analysis.analyze_hat_image(hat_photo, api_key="sk-ant-test")


async def test_verify_api_key_reports_the_outcome_without_raising(monkeypatch):
    """The settings card's Test button, both ways, through the same seam."""
    ok_reply = _tool_use_response({})
    ok_reply["content"] = [{"type": "text", "text": "ok"}]
    ok_reply["stop_reason"] = "end_turn"
    _wire(monkeypatch, lambda req: httpx2.Response(200, json=ok_reply))
    good, detail = await claude_analysis.verify_api_key("sk-ant-test")
    assert good is True, detail

    _wire(monkeypatch, lambda req: httpx2.Response(
        401, json={"type": "error", "error": {"type": "authentication_error", "message": "nope"}},
    ))
    good, detail = await claude_analysis.verify_api_key("sk-ant-wrong")
    assert good is False
    assert detail
