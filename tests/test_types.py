"""Unit tests for canonical types and error normalization."""

import pytest
from modelmesh.core.errors import (
    AuthError,
    BadRequestError,
    ContextLengthError,
    NetworkError,
    ProviderError,
    RateLimitError,
    ServerError,
    sanitize_error_message,
)
from modelmesh.core.types import (
    Candidate,
    ChatRequest,
    EndpointConfig,
    ImagePart,
    Message,
    ModelConfig,
    ProviderConfig,
    TextPart,
    ToolCall,
    ToolSpec,
    Usage,
)


def test_text_and_image_parts_roundtrip() -> None:
    text_part = TextPart(text="Hello world")
    d_text = text_part.to_dict()
    assert d_text == {"type": "text", "text": "Hello world"}
    assert TextPart.from_dict(d_text) == text_part

    img_part = ImagePart(media_type="image/jpeg", data="base64data...")
    d_img = img_part.to_dict()
    assert d_img["type"] == "image"
    assert d_img["media_type"] == "image/jpeg"
    assert ImagePart.from_dict(d_img) == img_part


def test_tool_spec_and_call_roundtrip() -> None:
    spec = ToolSpec(
        name="calculator",
        description="Calculates arithmetic expressions",
        parameters={"type": "object", "properties": {"expression": {"type": "string"}}},
    )
    d_spec = spec.to_dict()
    assert ToolSpec.from_dict(d_spec) == spec

    call = ToolCall(id="call_123", name="calculator", arguments={"expression": "2 + 2"})
    d_call = call.to_dict()
    assert ToolCall.from_dict(d_call) == call


def test_message_roundtrip_and_helpers() -> None:
    msg = Message.from_text(role="user", text="Tell me a joke", meta={"source": "test"})
    assert msg.text_content() == "Tell me a joke"
    assert msg.role == "user"

    d_msg = msg.to_dict()
    reconstructed = Message.from_dict(d_msg)
    assert reconstructed.id == msg.id
    assert reconstructed.role == msg.role
    assert reconstructed.text_content() == "Tell me a joke"
    assert reconstructed.meta == {"source": "test"}


def test_chat_request_derived_capabilities() -> None:
    msg1 = Message.from_text(role="user", text="Hi")
    req1 = ChatRequest(messages=[msg1])
    assert req1.required_capabilities == {"streaming"}

    # With tool
    spec = ToolSpec(name="test", description="test tool")
    req2 = ChatRequest(messages=[msg1], tools=[spec])
    assert "tools" in req2.required_capabilities

    # With image
    img_msg = Message(
        role="user",
        parts=[TextPart(text="Check this"), ImagePart(media_type="image/png", data="abc")],
    )
    req3 = ChatRequest(messages=[img_msg])
    assert "vision" in req3.required_capabilities


def test_usage_total_and_roundtrip() -> None:
    u = Usage(input_tokens=100, output_tokens=50, cached_tokens=20, reasoning_tokens=10)
    assert u.total_tokens == 150
    d = u.to_dict()
    reconstructed = Usage.from_dict(d)
    assert reconstructed.input_tokens == 100
    assert reconstructed.output_tokens == 50
    assert reconstructed.cached_tokens == 20
    assert reconstructed.reasoning_tokens == 10


def test_candidate_resolution_overrides() -> None:
    provider = ProviderConfig(id="groq", protocol="openai_compat")
    model = ModelConfig(
        id="llama3-8b",
        display_name="Llama 3 8B",
        tier="cheap",
        context_window=8192,
        max_output=2048,
        capabilities=["streaming", "tools"],
    )
    # Endpoint overrides context_window and capabilities, leaves max_output default
    endpoint = EndpointConfig(
        id="llama3-8b@groq",
        provider="groq",
        api_model="llama-3-8b-8192",
        price_in_per_mtok=0.05,
        price_out_per_mtok=0.08,
        priority=1,
        context_window=16384,
        capabilities=["streaming", "tools", "vision"],
        quirks={"supports_temperature": True},
    )

    cand = Candidate.resolve(model, endpoint, provider)
    assert cand.model_id == "llama3-8b"
    assert cand.endpoint_id == "llama3-8b@groq"
    assert cand.provider_id == "groq"
    assert cand.effective_context_window == 16384
    assert cand.effective_max_output == 2048  # From model default
    assert cand.effective_capabilities == {"streaming", "tools", "vision"}
    assert cand.effective_quirks == {"supports_temperature": True}
    assert cand.price_in_per_mtok == 0.05
    assert cand.price_out_per_mtok == 0.08


def test_sanitize_error_message() -> None:
    err_text = "Failed with key sk-123456789012345678901234 and gsk_abcdefghijklmnopqrstuvwxyz"
    sanitized = sanitize_error_message(err_text)
    assert "sk-1234" not in sanitized
    assert "gsk_abc" not in sanitized
    assert "[REDACTED_KEY]" in sanitized


def test_provider_errors_classification() -> None:
    auth_err = AuthError("Invalid auth token", provider_id="openai")
    assert auth_err.category == "auth"
    assert not auth_err.retryable
    assert not auth_err.should_skip_model_siblings

    rate_err = RateLimitError("Rate limit reached", provider_id="groq")
    assert rate_err.category == "rate_limit"
    assert rate_err.retryable
    assert not rate_err.should_skip_model_siblings

    ctx_err = ContextLengthError("Context window exceeded", provider_id="anthropic")
    assert ctx_err.category == "context_length"
    assert not ctx_err.retryable
    assert ctx_err.should_skip_model_siblings  # Model-level issue skips siblings

    bad_req = BadRequestError("Bad parameter", provider_id="ollama")
    assert bad_req.category == "bad_request"
    assert bad_req.should_skip_model_siblings

    net_err = NetworkError("Connection timed out", provider_id="together")
    assert net_err.category == "network"
    assert net_err.retryable

    srv_err = ServerError("500 Internal Error", provider_id="gemini")
    assert srv_err.category == "server"
    assert srv_err.retryable
