"""Token estimation and cost calculations for ModelMesh."""

from __future__ import annotations

from typing import Optional
from modelmesh.core.types import ChatRequest, ImagePart, TextPart, Usage


def estimate_tokens(text: str) -> int:
    """Fast character-based heuristic token estimator (~4 characters per token)."""
    if not text:
        return 0
    return max(1, len(text) // 4)


def estimate_request_tokens(request: ChatRequest) -> int:
    """Estimate total input tokens for a ChatRequest."""
    total = 0
    if request.system_prompt:
        total += estimate_tokens(request.system_prompt)

    for msg in request.messages:
        for part in msg.parts:
            if isinstance(part, TextPart):
                total += estimate_tokens(part.text)
            elif isinstance(part, ImagePart):
                # Standard ~85-170 tokens estimate per low/high-res image tile
                total += 1000

    # Extra baseline overhead for message framing
    total += len(request.messages) * 4
    return total


def calculate_cost(
    usage: Usage,
    price_in_per_mtok: float,
    price_out_per_mtok: float,
) -> float:
    """Calculate the estimated USD cost for token usage.

    Args:
        usage: Token counts.
        price_in_per_mtok: Price in USD per 1 Million input tokens.
        price_out_per_mtok: Price in USD per 1 Million output tokens.

    Returns:
        Cost in USD rounded to 6 decimal places.
    """
    cost_in = (usage.input_tokens / 1_000_000.0) * price_in_per_mtok
    cost_out = (usage.output_tokens / 1_000_000.0) * price_out_per_mtok
    return round(cost_in + cost_out, 6)


def estimate_request_cost(
    request: ChatRequest,
    price_in_per_mtok: float,
    price_out_per_mtok: float,
    expected_output_tokens: int = 500,
) -> float:
    """Estimate total cost of a request before execution for routing comparison."""
    est_in = estimate_request_tokens(request)
    usage = Usage(input_tokens=est_in, output_tokens=expected_output_tokens, estimated=True)
    return calculate_cost(usage, price_in_per_mtok, price_out_per_mtok)
