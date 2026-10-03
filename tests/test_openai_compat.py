"""Unit and mocked HTTP tests for the OpenAI-compatible provider adapter."""

import json
import httpx
import pytest
import respx

from modelmesh.core.errors import (
    AuthError,
    ContextLengthError,
    RateLimitError,
    ServerError,
)
from modelmesh.core.providers.base import get_adapter
from modelmesh.core.providers.openai_compat import (
    _convert_messages_to_openai,
    _convert_tools_to_openai,
    map_openai_exception,
)
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


def create_openai_candidate() -> Candidate:
    prov = ProviderConfig(
        id="test-groq",
        protocol="openai_compat",
        base_url="https://api.groq.test/openai/v1",
        auth_env=["TEST_GROQ_KEY"],
    )
    model = ModelConfig(
        id="test-llama",
        display_name="Test Llama",
        capabilities=["streaming", "tools"],
    )
    ep = EndpointConfig(
        id="test-llama@groq",
        provider="test-groq",
        api_model="llama-3.1-8b-instant",
        price_in_per_mtok=0.05,
        price_out_per_mtok=0.08,
    )
    return Candidate.resolve(model, ep, prov)


def test_message_and_tools_conversion() -> None:
    req = ChatRequest(
        system_prompt="You are a helpful assistant.",
        messages=[
            Message.from_text("user", "Hello"),
            Message(
                role="assistant",
                parts=[TextPart(text="")],
                tool_calls=[ToolCall(id="call_1", name="calc", arguments={"expr": "1+1"})],
            ),
            Message(role="tool", parts=[TextPart(text="2")], tool_call_id="call_1"),
            Message(
                role="user",
                parts=[TextPart(text="Look"), ImagePart(media_type="image/jpeg", data="dGVzdA==")],
            ),
        ],
        tools=[ToolSpec(name="calc", description="calculator", parameters={"type": "object"})],
    )

    conv_msgs = _convert_messages_to_openai(req)
    assert len(conv_msgs) == 5
    assert conv_msgs[0] == {"role": "system", "content": "You are a helpful assistant."}
    assert conv_msgs[1] == {"role": "user", "content": "Hello"}
    assert conv_msgs[2]["role"] == "assistant"
    assert conv_msgs[2]["tool_calls"][0]["function"]["name"] == "calc"
    assert conv_msgs[3]["role"] == "tool"
    assert conv_msgs[3]["tool_call_id"] == "call_1"
    assert isinstance(conv_msgs[4]["content"], list)  # Multimodal

    conv_tools = _convert_tools_to_openai(req.tools)
    assert len(conv_tools) == 1
    assert conv_tools[0]["function"]["name"] == "calc"


def test_map_openai_exceptions() -> None:
    req_dummy = httpx.Request("POST", "https://api.test/v1/chat/completions")

    # 401 Auth Error
    resp_401 = httpx.Response(401, json={"error": {"message": "Invalid API key"}}, request=req_dummy)
    err_401 = httpx.HTTPStatusError("401", request=req_dummy, response=resp_401)
    mapped = map_openai_exception(err_401, "test-prov")
    assert isinstance(mapped, AuthError)
    assert mapped.category == "auth"

    # 429 Rate Limit
    resp_429 = httpx.Response(429, json={"error": {"message": "Rate limit reached"}}, request=req_dummy)
    err_429 = httpx.HTTPStatusError("429", request=req_dummy, response=resp_429)
    mapped_rl = map_openai_exception(err_429, "test-prov")
    assert isinstance(mapped_rl, RateLimitError)
    assert mapped_rl.category == "rate_limit"

    # Context length exceeded
    resp_ctx = httpx.Response(400, json={"error": {"message": "Maximum context length exceeded: 8192"}}, request=req_dummy)
    err_ctx = httpx.HTTPStatusError("400", request=req_dummy, response=resp_ctx)
    mapped_ctx = map_openai_exception(err_ctx, "test-prov")
    assert isinstance(mapped_ctx, ContextLengthError)
    assert mapped_ctx.category == "context_length"
    assert mapped_ctx.should_skip_model_siblings is True

    # 500 Server Error
    resp_500 = httpx.Response(500, json={"error": {"message": "Internal error"}}, request=req_dummy)
    err_500 = httpx.HTTPStatusError("500", request=req_dummy, response=resp_500)
    mapped_srv = map_openai_exception(err_500, "test-prov")
    assert isinstance(mapped_srv, ServerError)
    assert mapped_srv.category == "server"


@respx.mock
def test_openai_compat_streaming_respx(monkeypatch) -> None:
    monkeypatch.setenv("TEST_GROQ_KEY", "gsk_test_secret_key_123456789012345")
    candidate = create_openai_candidate()
    adapter = get_adapter("openai_compat")

    # Mock SSE stream
    sse_body = (
        'data: {"id":"chatcmpl-1","choices":[{"index":0,"delta":{"role":"assistant","content":"Hello"}}]}\n\n'
        'data: {"id":"chatcmpl-1","choices":[{"index":0,"delta":{"content":" there!"}}]}\n\n'
        'data: {"id":"chatcmpl-1","choices":[{"index":0,"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":10,"completion_tokens":2}}\n\n'
        "data: [DONE]\n\n"
    )

    respx.post("https://api.groq.test/openai/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            text=sse_body,
            headers={"content-type": "text/event-stream"},
        )
    )

    req = ChatRequest(messages=[Message.from_text("user", "Hi")])
    events = list(adapter.stream_chat(request=req, candidate=candidate))

    text_events = [e.text for e in events if e.type == StreamEventType.TEXT_DELTA]
    assert "".join(text_events) == "Hello there!"

    usage_events = [e.usage for e in events if e.type == StreamEventType.USAGE]
    assert len(usage_events) >= 1
    assert usage_events[0].input_tokens == 10
    assert usage_events[0].output_tokens == 2


@respx.mock
def test_openai_compat_tool_calling_stream(monkeypatch) -> None:
    monkeypatch.setenv("TEST_GROQ_KEY", "gsk_test_secret_key_123456789012345")
    candidate = create_openai_candidate()
    adapter = get_adapter("openai_compat")

    # Mock SSE stream with tool call fragments
    sse_body = (
        'data: {"id":"chatcmpl-2","choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"id":"call_abc","type":"function","function":{"name":"calculator","arguments":""}}]}}]}\n\n'
        'data: {"id":"chatcmpl-2","choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\\"expr\\""}}]}}]}\n\n'
        'data: {"id":"chatcmpl-2","choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"function":{"arguments":": \\"2+2\\"}"}}]}}]}\n\n'
        'data: {"id":"chatcmpl-2","choices":[{"index":0,"delta":{},"finish_reason":"tool_calls"}]}\n\n'
        "data: [DONE]\n\n"
    )

    respx.post("https://api.groq.test/openai/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            text=sse_body,
            headers={"content-type": "text/event-stream"},
        )
    )

    req = ChatRequest(
        messages=[Message.from_text("user", "What is 2+2?")],
        tools=[ToolSpec(name="calculator", description="calc", parameters={})],
    )
    events = list(adapter.stream_chat(request=req, candidate=candidate))

    tool_events = [e.tool_call for e in events if e.type == StreamEventType.TOOL_CALL]
    assert len(tool_events) == 1
    assert tool_events[0].id == "call_abc"
    assert tool_events[0].name == "calculator"
    assert tool_events[0].arguments == {"expr": "2+2"}
