"""Mock provider adapter for unit testing and offline demo execution."""

from __future__ import annotations

import threading
import time
from typing import Iterator, List, Optional

from modelmesh.core.cost import estimate_request_tokens, estimate_tokens
from modelmesh.core.errors import (
    AuthError,
    BadRequestError,
    ContextLengthError,
    NetworkError,
    ProviderError,
    RateLimitError,
    ServerError,
)
from modelmesh.core.providers.base import ProviderAdapter, register_adapter
from modelmesh.core.types import (
    Candidate,
    ChatRequest,
    ProviderConfig,
    StreamEvent,
    StreamEventType,
    ToolCall,
    Usage,
)


@register_adapter("mock")
class MockAdapter(ProviderAdapter):
    """Deterministic offline adapter for unit testing and demo fallback."""

    def stream_chat(
        self,
        request: ChatRequest,
        candidate: Candidate,
        cancel_event: Optional[threading.Event] = None,
    ) -> Iterator[StreamEvent]:
        # Handle simulated error quirks if configured on endpoint
        quirks = candidate.effective_quirks
        simulated_err = quirks.get("simulate_error")
        if simulated_err:
            if simulated_err == "rate_limit":
                raise RateLimitError("Simulated 429 Rate Limit Exceeded", provider_id=candidate.provider_id)
            elif simulated_err == "auth":
                raise AuthError("Simulated 401 Invalid Key", provider_id=candidate.provider_id)
            elif simulated_err == "context_length":
                raise ContextLengthError("Simulated Context Length Exceeded", provider_id=candidate.provider_id)
            elif simulated_err == "server":
                raise ServerError("Simulated 500 Server Error", provider_id=candidate.provider_id)
            else:
                raise ProviderError(f"Simulated error: {simulated_err}", provider_id=candidate.provider_id)

        # Check if any tool calls should be simulated
        simulated_tool = quirks.get("simulate_tool_call")
        if simulated_tool and request.tools:
            # Emit tool call event
            yield StreamEvent(
                type=StreamEventType.TOOL_CALL,
                tool_call=ToolCall(
                    id="mock_call_1",
                    name=simulated_tool.get("name", "calculator"),
                    arguments=simulated_tool.get("args", {"expression": "100 * 42"}),
                ),
            )
            yield StreamEvent(
                type=StreamEventType.USAGE,
                usage=Usage(input_tokens=10, output_tokens=15),
            )
            yield StreamEvent(
                type=StreamEventType.DONE,
                finish_reason="tool_calls",
            )
            return

        # Prepare canned stream text
        last_user_msg = ""
        for msg in reversed(request.messages):
            if msg.role == "user":
                last_user_msg = msg.text_content()
                break

        canned_response = (
            f"[Mock reply from {candidate.model_id} via {candidate.provider_id}] "
            f"Received prompt: '{last_user_msg}'. ModelMesh offline router core is operating normally."
        )

        words = canned_response.split(" ")
        accumulated_text = ""

        # Emit simulated reasoning if model has reasoning capability
        if "reasoning" in candidate.effective_capabilities:
            reasoning_chunks = ["Analyzing request... ", "Formulating response structure... "]
            for r_chunk in reasoning_chunks:
                if cancel_event and cancel_event.is_set():
                    return
                yield StreamEvent(
                    type=StreamEventType.REASONING_DELTA,
                    reasoning=r_chunk,
                )

        # Stream words
        for i, word in enumerate(words):
            if cancel_event and cancel_event.is_set():
                return

            chunk = word + (" " if i < len(words) - 1 else "")
            accumulated_text += chunk
            yield StreamEvent(
                type=StreamEventType.TEXT_DELTA,
                text=chunk,
            )

        # Calculate usage
        input_tokens = estimate_request_tokens(request)
        output_tokens = estimate_tokens(accumulated_text)

        yield StreamEvent(
            type=StreamEventType.USAGE,
            usage=Usage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                estimated=False,
            ),
        )

        yield StreamEvent(
            type=StreamEventType.DONE,
            finish_reason="stop",
        )

    def list_models(self, provider: ProviderConfig) -> List[str]:
        return ["mock-instant", "mock-reasoning", "mock-vision"]

    def test_connection(self, provider: ProviderConfig) -> bool:
        return True
