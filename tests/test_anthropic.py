"""Unit and mocked tests for the Anthropic Claude provider adapter."""

import httpx
import pytest
import respx

from modelmesh.core.errors import (
    AuthError,
    BadRequestError,
    ContextLengthError,
    NetworkError,
    RateLimitError,
    ServerError,
)
from modelmesh.core.providers.anthropic import (
    _convert_messages_to_anthropic,
    _convert_tools_to_anthropic,
    map_anthropic_exception,
)
from modelmesh.core.providers.base import get_adapter
from modelmesh.core.types import (
    Candidate,
    ChatRequest,
    EndpointConfig,
    ImagePart,
    Message,
    ModelConfig,
    ProviderConfig,
    StreamEventType,
    TextPart,
    ToolCall,
    ToolSpec,
)


def create_anthropic_candidate() -> Candidate:
    prov = ProviderConfig(
        id="test-anthropic",
        protocol="anthropic",
        base_url="https://api.anthropic.test",
        auth_env=["TEST_ANTHROPIC_KEY"],
    )
    model = ModelConfig(
        id="claude-3-5-sonnet",
        display_name="Claude 3.5 Sonnet",
        capabilities=["streaming", "tools", "vision"],
    )
    ep = EndpointConfig(
        id="claude-3-5-sonnet@anthropic",
        provider="test-anthropic",
        api_model="claude-3-5-sonnet-20241022",
        price_in_per_mtok=3.0,
        price_out_per_mtok=15.0,
    )
    return Candidate.resolve(model, ep, prov)


def test_anthropic_message_conversion() -> None:
    req = ChatRequest(
        system_prompt="You are Claude.",
        messages=[
            Message(role="system", parts=[TextPart(text="Follow safety guidelines.")]),
            Message.from_text("user", "Hello Claude!"),
            Message(
                role="assistant",
                parts=[TextPart(text="I can check that.")],
                tool_calls=[ToolCall(id="toolu_123", name="calc", arguments={"x": 5})],
            ),
            Message(
                role="tool",
                parts=[TextPart(text="Result: 25")],
                tool_call_id="toolu_123",
            ),
            Message(
                role="user",
                parts=[TextPart(text="See image:"), ImagePart(media_type="image/png", data="abc1234")],
            ),
        ],
    )

    sys_prompt, anthropic_msgs = _convert_messages_to_anthropic(req)
    assert sys_prompt == "You are Claude.\n\nFollow safety guidelines."
    assert len(anthropic_msgs) == 4

    # Message 1: user
    assert anthropic_msgs[0]["role"] == "user"
    assert anthropic_msgs[0]["content"][0]["text"] == "Hello Claude!"

    # Message 2: assistant with tool_use block
    assert anthropic_msgs[1]["role"] == "assistant"
    assert anthropic_msgs[1]["content"][1]["type"] == "tool_use"
    assert anthropic_msgs[1]["content"][1]["id"] == "toolu_123"

    # Message 3: tool result in user role
    assert anthropic_msgs[2]["role"] == "user"
    assert anthropic_msgs[2]["content"][0]["type"] == "tool_result"
    assert anthropic_msgs[2]["content"][0]["tool_use_id"] == "toolu_123"

    # Message 4: user with image block
    assert anthropic_msgs[3]["role"] == "user"
    assert anthropic_msgs[3]["content"][1]["type"] == "image"
    assert anthropic_msgs[3]["content"][1]["source"]["data"] == "abc1234"


def test_anthropic_tools_conversion() -> None:
    specs = [
        ToolSpec(
            name="calculator",
            description="Evaluates math",
            parameters={"type": "object", "properties": {"exp": {"type": "string"}}},
        )
    ]
    tools = _convert_tools_to_anthropic(specs)
    assert len(tools) == 1
    assert tools[0]["name"] == "calculator"
    assert tools[0]["input_schema"]["properties"]["exp"]["type"] == "string"


def test_anthropic_error_mapping() -> None:
    req_dummy = httpx.Request("POST", "https://api.anthropic.test/v1/messages")

    # 401
    resp_401 = httpx.Response(401, json={"error": {"message": "Invalid API key"}}, request=req_dummy)
    err_401 = httpx.HTTPStatusError("401", request=req_dummy, response=resp_401)
    mapped_401 = map_anthropic_exception(err_401, "anthropic")
    assert isinstance(mapped_401, AuthError)

    # 429
    resp_429 = httpx.Response(429, json={"error": {"message": "Rate limit exceeded"}}, request=req_dummy)
    err_429 = httpx.HTTPStatusError("429", request=req_dummy, response=resp_429)
    mapped_429 = map_anthropic_exception(err_429, "anthropic")
    assert isinstance(mapped_429, RateLimitError)

    # Context length
    resp_ctx = httpx.Response(400, json={"error": {"message": "prompt is too long"}}, request=req_dummy)
    err_ctx = httpx.HTTPStatusError("400", request=req_dummy, response=resp_ctx)
    mapped_ctx = map_anthropic_exception(err_ctx, "anthropic")
    assert isinstance(mapped_ctx, ContextLengthError)
    assert mapped_ctx.should_skip_model_siblings is True
