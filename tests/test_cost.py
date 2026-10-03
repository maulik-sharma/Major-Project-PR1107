"""Tests for token estimation and cost calculation."""

from modelmesh.core.cost import (
    calculate_cost,
    estimate_request_cost,
    estimate_request_tokens,
    estimate_tokens,
)
from modelmesh.core.types import ChatRequest, ImagePart, Message, TextPart, Usage


def test_estimate_tokens() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("hello") == 1
    assert estimate_tokens("a" * 40) == 10


def test_estimate_request_tokens_multimodal() -> None:
    req = ChatRequest(
        system_prompt="You are a helpful assistant.",
        messages=[
            Message.from_text(role="user", text="What is in this picture?"),
            Message(
                role="user",
                parts=[TextPart(text="Check"), ImagePart(media_type="image/png", data="abc")],
            ),
        ],
    )
    tokens = estimate_request_tokens(req)
    assert tokens > 1000  # Includes image baseline estimate


def test_calculate_cost() -> None:
    # 1M input tokens at $1.00, 1M output tokens at $3.00
    usage = Usage(input_tokens=1_000_000, output_tokens=1_000_000)
    cost = calculate_cost(usage, price_in_per_mtok=1.0, price_out_per_mtok=3.0)
    assert cost == 4.0

    # 10k in, 2k out on cheap model ($0.05 / $0.08)
    usage2 = Usage(input_tokens=10_000, output_tokens=2_000)
    cost2 = calculate_cost(usage2, price_in_per_mtok=0.05, price_out_per_mtok=0.08)
    assert cost2 == round((10000 / 1e6 * 0.05) + (2000 / 1e6 * 0.08), 6)


def test_estimate_request_cost() -> None:
    req = ChatRequest(messages=[Message.from_text(role="user", text="Tell me a joke")])
    cost = estimate_request_cost(req, price_in_per_mtok=1.0, price_out_per_mtok=2.0)
    assert cost > 0.0
