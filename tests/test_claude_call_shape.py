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
    """A forced `tool_choice` makes this impossible where the model allows
    forcing; under `auto` it is merely unlikely. The parser copes either way."""
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


# ---- the request shape a model will actually accept ----------------------- #

_ANSWER = {
    "brand": "melin", "logo_detected": None, "artist_series": None,
    "model_name": "Odysea Hydro", "colorway": None, "model_confidence": "high",
    "style_descriptor": "structured", "design_notes": "",
    "estimated_new_price_usd": None,
    "colors": [{"name": "Black", "hex": "#0a141e", "tier": "primary"}],
}


@pytest.mark.parametrize(
    ("model", "forced"),
    [
        ("claude-sonnet-5", True),
        ("claude-opus-5", True),
        ("claude-fable-5", True),
        ("claude-haiku-4-5-20251001", True),
        ("claude-opus-4-6", True),
        # These three answer a forced tool choice with a 400.
        ("claude-fable-5-1", False),
        ("claude-mythos-5-1", False),
        # `claude-opus-5` + "-5" — must not pass for a dated Opus 5.
        ("claude-opus-5-5", False),
        # Anything this build has not heard of gets the choice every model accepts.
        ("claude-someday-9", False),
    ],
)
async def test_the_tool_is_forced_only_where_the_model_allows_it(
    monkeypatch, hat_photo, model, forced
):
    """Fable 5.1 was on the Settings roster as "most capable", and every
    analysis sent it `tool_choice: {type: "tool"}`, which it rejects with a
    400 — so every hat fell back to basic ID. Unlisted models get `auto`
    (plus room for the thinking those models always do); listed ones keep the
    forced call's guarantee."""
    seen = _wire(monkeypatch, lambda req: httpx2.Response(200, json=_tool_use_response(_ANSWER)))

    await claude_analysis.analyze_hat_image(hat_photo, api_key="sk-ant-test", model=model)

    body = json.loads(seen[0].content)
    if forced:
        assert body["tool_choice"] == {"type": "tool", "name": "record_hat_analysis"}
        assert body["max_tokens"] == 1024
    else:
        assert body["tool_choice"] == {"type": "auto"}
        assert body["max_tokens"] > 1024, "thinking tokens count against max_tokens"
    # The instruction to call the tool is what `auto` relies on.
    assert "Always respond by calling the `record_hat_analysis` tool" in body["system"][0]["text"]


@pytest.mark.parametrize(("model", "max_tokens"), [("claude-sonnet-5", 1024), ("claude-fable-5-1", 8192)])
async def test_the_wait_fits_the_answer_the_request_allows(monkeypatch, hat_photo, model, max_tokens):
    """A non-streaming request sends nothing back until the whole answer is
    written, so its timeout is a cap on generation time. The `auto` path
    allows 8192 tokens because those models think first, and the 30 s
    `http_timeout` that fits a 1024-token forced call cut it off part-way —
    and the SDK retries a timeout, paying for each abandoned attempt."""
    timeouts: list[float] = []

    def fake_client(api_key, timeout, **kw):
        timeouts.append(timeout)
        return AsyncAnthropic(
            api_key=api_key, timeout=timeout, max_retries=0,
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(
                lambda req: httpx2.Response(200, json=_tool_use_response(_ANSWER))
            )),
        )

    monkeypatch.setattr(claude_analysis, "_anthropic_client", fake_client)
    await claude_analysis.analyze_hat_image(hat_photo, api_key="sk-ant-test", model=model)

    # The SDK's own budget for a non-streaming request: an hour per 128k
    # output tokens. Never less than the configured timeout.
    from headroom.config import settings

    assert timeouts == [max(settings.http_timeout, 3600 * max_tokens / 128_000)]
    assert max_tokens == 1024 or timeouts[0] > 200


@pytest.mark.parametrize("model", ["claude-sonnet-5", "claude-fable-5-1"])
async def test_the_key_test_sends_the_request_an_analysis_sends(monkeypatch, hat_photo, model):
    """The Test button sent a bare ping with no tools, so a model that
    rejects the ANALYSIS request's shape tested "OK" and then failed every
    hat. It now sends the same system prompt, tool and tool choice."""
    seen = _wire(monkeypatch, lambda req: httpx2.Response(200, json=_tool_use_response(_ANSWER)))

    await claude_analysis.analyze_hat_image(hat_photo, api_key="sk-ant-test", model=model)
    good, detail = await claude_analysis.verify_api_key("sk-ant-test", model)

    assert good is True, detail
    analysis, test = (json.loads(r.content) for r in seen)
    for field in ("model", "system", "tools", "tool_choice"):
        assert test[field] == analysis[field], f"Test's {field} differs from the analysis request"


async def test_a_refused_request_shape_fails_the_key_test(monkeypatch):
    """And when the model refuses that shape, Test says so instead of "OK"."""
    _wire(monkeypatch, lambda req: httpx2.Response(400, json={
        "type": "error",
        "error": {"type": "invalid_request_error",
                  "message": 'tool_choice: type "tool" and "any" are not supported for this model.'},
    }))

    good, detail = await claude_analysis.verify_api_key("sk-ant-test", "claude-sonnet-5")

    assert good is False
    assert "tool_choice" in detail


async def test_a_tool_input_that_is_not_an_object_is_an_analysis_error(monkeypatch, hat_photo):
    """The parser's `.get` calls assume an object. A list raised
    AttributeError, which is not in the parse handler — so it escaped the
    pipeline's `ClaudeAnalysisError` handling and failed the run instead of
    falling back."""
    _wire(monkeypatch, lambda req: httpx2.Response(200, json=_tool_use_response(["not", "an", "object"])))

    with pytest.raises(claude_analysis.ClaudeAnalysisError, match="not an object"):
        await claude_analysis.analyze_hat_image(hat_photo, api_key="sk-ant-test")


async def test_a_reply_without_a_tool_call_names_why(monkeypatch, hat_photo):
    """Under `auto` a missing call is possible, and the stop reason is the
    diagnosis — `max_tokens` means thinking used the room."""
    reply = _tool_use_response({})
    reply["content"] = [{"type": "thinking", "thinking": "", "signature": "sig"}]
    reply["stop_reason"] = "max_tokens"
    _wire(monkeypatch, lambda req: httpx2.Response(200, json=reply))

    with pytest.raises(claude_analysis.ClaudeAnalysisError, match="max_tokens"):
        await claude_analysis.analyze_hat_image(
            hat_photo, api_key="sk-ant-test", model="claude-fable-5-1"
        )


async def test_each_analysis_logs_its_cache_counts(monkeypatch, hat_photo, caplog):
    """Whether the cache breakpoint does anything depends on the model's
    minimum cacheable prefix, and the API is silent when it does not. The
    counts in the log are how an owner can tell."""
    reply = _tool_use_response(_ANSWER)
    reply["usage"] = {
        "input_tokens": 1200, "output_tokens": 300,
        "cache_read_input_tokens": 2480, "cache_creation_input_tokens": 0,
    }
    _wire(monkeypatch, lambda req: httpx2.Response(200, json=reply))
    caplog.set_level("INFO", logger="headroom.services.claude_analysis")

    await claude_analysis.analyze_hat_image(hat_photo, api_key="sk-ant-test")

    assert any(
        "cache_read=2480" in r.getMessage() and "cache_write=0" in r.getMessage()
        for r in caplog.records
    ), [r.getMessage() for r in caplog.records]
