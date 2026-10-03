"""Anthropic Claude provider adapter for ModelMesh."""

from __future__ import annotations

import threading
from typing import Any, Dict, Iterator, List, Optional, Tuple

import anthropic
from anthropic import Anthropic
import httpx

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
from modelmesh.core.keys import get_env_key
from modelmesh.core.providers.base import ProviderAdapter, register_adapter
from modelmesh.core.types import (
    Candidate,
    ChatRequest,
    ImagePart,
    Message,
    ProviderConfig,
    StreamEvent,
    StreamEventType,
    TextPart,
    ToolCall,
    ToolSpec,
    Usage,
)


def _get_anthropic_api_key(provider: ProviderConfig) -> str:
    """Retrieve Anthropic API key from provider auth_env or default dummy."""
    for var in provider.auth_env:
        val = get_env_key(var)
        if val:
            return val
    return "dummy-anthropic-key"


def _create_anthropic_client(
    provider: ProviderConfig,
    http_client: Optional[httpx.Client] = None,
) -> Anthropic:
    """Instantiate an Anthropic client."""
    api_key = _get_anthropic_api_key(provider)
    timeout = httpx.Timeout(
        connect=provider.connect_timeout,
        read=provider.read_timeout,
        write=provider.read_timeout,
        pool=10.0,
    )
    client = http_client or httpx.Client(timeout=timeout)
    return Anthropic(
        api_key=api_key,
        base_url=provider.base_url or "https://api.anthropic.com",
        http_client=client,
        default_headers=provider.extra_headers or None,
    )


def _convert_messages_to_anthropic(
    request: ChatRequest,
) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    """Convert canonical messages to Anthropic format (separate system prompt and typed content blocks)."""
    system_prompt = request.system_prompt
    anthropic_msgs: List[Dict[str, Any]] = []

    for msg in request.messages:
        if msg.role == "system":
            # Extra system messages appended to system prompt
            text = msg.text_content()
            if system_prompt:
                system_prompt += "\n\n" + text
            else:
                system_prompt = text
            continue

        if msg.role == "tool":
            # Tool results are represented as tool_result content blocks in a user message
            anthropic_msgs.append({
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": msg.tool_call_id or "",
                        "content": msg.text_content(),
                    }
                ],
            })
            continue

        # User or Assistant message
        blocks: List[Dict[str, Any]] = []
        for part in msg.parts:
            if isinstance(part, TextPart):
                if part.text:
                    blocks.append({"type": "text", "text": part.text})
            elif isinstance(part, ImagePart):
                blocks.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": part.media_type,
                        "data": part.data,
                    },
                })

        if msg.tool_calls:
            for tc in msg.tool_calls:
                blocks.append({
                    "type": "tool_use",
                    "id": tc.id,
                    "name": tc.name,
                    "input": tc.arguments,
                })

        # Anthropic requires non-empty content
        if not blocks:
            blocks = [{"type": "text", "text": " "}]

        anthropic_msgs.append({
            "role": msg.role,
            "content": blocks,
        })

    return system_prompt, anthropic_msgs


def _convert_tools_to_anthropic(tools: List[ToolSpec]) -> List[Dict[str, Any]]:
    """Convert ToolSpec list to Anthropic tool definitions format."""
    return [
        {
            "name": t.name,
            "description": t.description,
            "input_schema": t.parameters or {"type": "object"},
        }
        for t in tools
    ]


def map_anthropic_exception(exc: Exception, provider_id: str) -> ProviderError:
    """Map Anthropic SDK exceptions to normalized ProviderError instances."""
    msg = str(exc)
    status_code = getattr(exc, "status_code", None)
    if status_code is None and hasattr(exc, "response") and exc.response is not None:
        status_code = getattr(exc.response, "status_code", None)
        try:
            msg = f"{msg}: {exc.response.text}"
        except Exception:
            pass

    lower_msg = msg.lower()
    if (
        "prompt is too long" in lower_msg
        or "maximum context length" in lower_msg
        or "context_length_exceeded" in lower_msg
    ):
        return ContextLengthError(
            message=msg,
            provider_id=provider_id,
            status_code=status_code or 400,
            raw_error=exc,
        )

    if isinstance(exc, anthropic.AuthenticationError) or status_code == 401:
        return AuthError(message=msg, provider_id=provider_id, status_code=status_code, raw_error=exc)
    elif isinstance(exc, anthropic.RateLimitError) or status_code == 429:
        return RateLimitError(message=msg, provider_id=provider_id, status_code=status_code, raw_error=exc)
    elif isinstance(exc, anthropic.BadRequestError) or status_code == 400:
        return BadRequestError(message=msg, provider_id=provider_id, status_code=status_code, raw_error=exc)
    elif isinstance(exc, (anthropic.APIConnectionError, anthropic.APITimeoutError)):
        return NetworkError(message=msg, provider_id=provider_id, status_code=status_code, raw_error=exc)
    elif isinstance(exc, anthropic.InternalServerError) or (status_code and status_code >= 500):
        return ServerError(message=msg, provider_id=provider_id, status_code=status_code, raw_error=exc)

    return ProviderError(
        message=msg,
        category="unknown",
        retryable=False,
        provider_id=provider_id,
        status_code=status_code,
        raw_error=exc,
    )


@register_adapter("anthropic")
class AnthropicAdapter(ProviderAdapter):
    """Adapter for native Anthropic Claude Messages API."""

    def stream_chat(
        self,
        request: ChatRequest,
        candidate: Candidate,
        cancel_event: Optional[threading.Event] = None,
    ) -> Iterator[StreamEvent]:
        client = _create_anthropic_client(candidate.provider_config)
        system_prompt, messages = _convert_messages_to_anthropic(request)

        # Anthropic requires max_tokens on every request
        max_tokens = request.max_tokens or candidate.effective_max_output or 4096

        kwargs: Dict[str, Any] = {
            "model": candidate.api_model,
            "messages": messages,
            "max_tokens": max_tokens,
        }

        if system_prompt:
            kwargs["system"] = system_prompt

        if request.temperature is not None:
            kwargs["temperature"] = request.temperature

        if request.tools and "tools" in candidate.effective_capabilities:
            kwargs["tools"] = _convert_tools_to_anthropic(request.tools)

        accumulated_text = ""
        input_tokens = 0
        output_tokens = 0

        try:
            with client.messages.stream(**kwargs) as stream:
                for text in stream.text_stream:
                    if cancel_event and cancel_event.is_set():
                        return
                    accumulated_text += text
                    yield StreamEvent(type=StreamEventType.TEXT_DELTA, text=text)

                # Get final message response for usage and tool calls
                final_msg = stream.get_final_message()
                if final_msg.usage:
                    input_tokens = final_msg.usage.input_tokens
                    output_tokens = final_msg.usage.output_tokens

                # Extract any tool calls from final message
                for block in final_msg.content:
                    if getattr(block, "type", None) == "tool_use":
                        yield StreamEvent(
                            type=StreamEventType.TOOL_CALL,
                            tool_call=ToolCall(
                                id=block.id,
                                name=block.name,
                                arguments=block.input if isinstance(block.input, dict) else {},
                            ),
                        )

        except Exception as exc:
            raise map_anthropic_exception(exc, candidate.provider_id) from exc

        # Emit final usage
        if input_tokens == 0:
            input_tokens = estimate_request_tokens(request)
        if output_tokens == 0:
            output_tokens = estimate_tokens(accumulated_text)

        yield StreamEvent(
            type=StreamEventType.USAGE,
            usage=Usage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                estimated=False,
            ),
        )

        yield StreamEvent(type=StreamEventType.DONE, finish_reason="stop")

    def list_models(self, provider: ProviderConfig) -> List[str]:
        """List standard Anthropic models."""
        client = _create_anthropic_client(provider)
        try:
            models_page = client.models.list()
            return [m.id for m in models_page.data]
        except Exception:
            # Fallback list if models.list() is unavailable
            return [
                "claude-3-5-sonnet-20241022",
                "claude-3-5-haiku-20241022",
                "claude-3-opus-20240229",
            ]

    def test_connection(self, provider: ProviderConfig) -> bool:
        """Perform lightweight check."""
        client = _create_anthropic_client(provider)
        try:
            client.models.list()
            return True
        except Exception as exc:
            raise map_anthropic_exception(exc, provider.id) from exc
