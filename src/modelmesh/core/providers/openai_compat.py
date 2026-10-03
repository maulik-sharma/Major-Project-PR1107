"""OpenAI-compatible provider adapter for ModelMesh.

Supports OpenAI, Google Gemini (via OpenAI endpoint), Groq, OpenRouter,
DeepSeek, Together, Mistral, Ollama, LM Studio, vLLM, and any compliant server.
"""

from __future__ import annotations

import json
import threading
from typing import Any, Dict, Iterator, List, Optional

import openai
from openai import OpenAI
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


def _get_api_key(provider: ProviderConfig) -> str:
    """Resolve API key for a provider, defaulting to 'dummy-key' for local providers."""
    for var_name in provider.auth_env:
        val = get_env_key(var_name)
        if val:
            return val
    # If no auth_env (e.g. Ollama/local), OpenAI SDK still expects a non-empty string
    return "ollama"


def _create_client(provider: ProviderConfig, http_client: Optional[httpx.Client] = None) -> OpenAI:
    """Instantiate an OpenAI client configured for the provider."""
    api_key = _get_api_key(provider)
    base_url = provider.base_url or "https://api.openai.com/v1"
    timeout = httpx.Timeout(
        connect=provider.connect_timeout,
        read=provider.read_timeout,
        write=provider.read_timeout,
        pool=10.0,
    )
    client = http_client or httpx.Client(timeout=timeout)
    return OpenAI(
        api_key=api_key,
        base_url=base_url,
        http_client=client,
        default_headers=provider.extra_headers or None,
    )


def _convert_messages_to_openai(request: ChatRequest) -> List[Dict[str, Any]]:
    """Convert canonical messages to OpenAI Chat Completions payload format."""
    openai_msgs: List[Dict[str, Any]] = []

    if request.system_prompt:
        openai_msgs.append({"role": "system", "content": request.system_prompt})

    for msg in request.messages:
        # Check if message has multiple parts (e.g. multimodal)
        has_images = any(isinstance(p, ImagePart) for p in msg.parts)
        if not has_images:
            content_str = msg.text_content()
            msg_dict: Dict[str, Any] = {
                "role": msg.role,
                "content": content_str,
            }
        else:
            parts_payload: List[Dict[str, Any]] = []
            for part in msg.parts:
                if isinstance(part, TextPart):
                    parts_payload.append({"type": "text", "text": part.text})
                elif isinstance(part, ImagePart):
                    parts_payload.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{part.media_type};base64,{part.data}"
                        },
                    })
            msg_dict = {
                "role": msg.role,
                "content": parts_payload,
            }

        if msg.tool_call_id:
            msg_dict["tool_call_id"] = msg.tool_call_id

        if msg.tool_calls:
            msg_dict["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments),
                    },
                }
                for tc in msg.tool_calls
            ]

        openai_msgs.append(msg_dict)

    return openai_msgs


def _convert_tools_to_openai(tools: List[ToolSpec]) -> List[Dict[str, Any]]:
    """Convert canonical ToolSpec list to OpenAI function schema format."""
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in tools
    ]


def map_openai_exception(exc: Exception, provider_id: str) -> ProviderError:
    """Map OpenAI SDK exceptions to normalized ProviderError instances."""
    msg = str(exc)
    status_code = getattr(exc, "status_code", None)
    if status_code is None and hasattr(exc, "response") and exc.response is not None:
        status_code = getattr(exc.response, "status_code", None)
        try:
            msg = f"{msg}: {exc.response.text}"
        except Exception:
            pass

    # Detect context length issues in message text or body
    lower_msg = msg.lower()
    if (
        "maximum context length" in lower_msg
        or "context_length_exceeded" in lower_msg
        or "prompt is too long" in lower_msg
        or "too many tokens" in lower_msg
    ):
        return ContextLengthError(
            message=msg,
            provider_id=provider_id,
            status_code=status_code or 400,
            raw_error=exc,
        )

    if isinstance(exc, openai.AuthenticationError) or status_code == 401:
        return AuthError(message=msg, provider_id=provider_id, status_code=status_code, raw_error=exc)
    elif isinstance(exc, openai.RateLimitError) or status_code == 429:
        return RateLimitError(message=msg, provider_id=provider_id, status_code=status_code, raw_error=exc)
    elif isinstance(exc, openai.BadRequestError) or status_code == 400:
        return BadRequestError(message=msg, provider_id=provider_id, status_code=status_code, raw_error=exc)
    elif isinstance(exc, (openai.APIConnectionError, openai.APITimeoutError)):
        return NetworkError(message=msg, provider_id=provider_id, status_code=status_code, raw_error=exc)
    elif isinstance(exc, openai.InternalServerError) or (status_code and status_code >= 500):
        return ServerError(message=msg, provider_id=provider_id, status_code=status_code, raw_error=exc)

    return ProviderError(
        message=msg,
        category="unknown",
        retryable=False,
        provider_id=provider_id,
        status_code=status_code,
        raw_error=exc,
    )


@register_adapter("openai_compat")
class OpenAICompatAdapter(ProviderAdapter):
    """Adapter for OpenAI and all OpenAI-compatible API servers."""

    def stream_chat(
        self,
        request: ChatRequest,
        candidate: Candidate,
        cancel_event: Optional[threading.Event] = None,
    ) -> Iterator[StreamEvent]:
        client = _create_client(candidate.provider_config)
        messages = _convert_messages_to_openai(request)
        quirks = candidate.effective_quirks

        kwargs: Dict[str, Any] = {
            "model": candidate.api_model,
            "messages": messages,
            "stream": True,
        }

        # Handle tools
        if request.tools and "tools" in candidate.effective_capabilities:
            kwargs["tools"] = _convert_tools_to_openai(request.tools)

        # Handle temperature (if supported by quirks)
        if request.temperature is not None and quirks.get("supports_temperature", True):
            kwargs["temperature"] = request.temperature

        # Handle max tokens parameter name
        max_tokens_key = quirks.get("max_tokens_param", "max_tokens")
        if request.max_tokens is not None:
            kwargs[max_tokens_key] = request.max_tokens

        # Attempt to request stream usage if not disabled by quirks
        if quirks.get("supports_stream_options", True):
            kwargs["stream_options"] = {"include_usage": True}

        accumulated_text = ""
        accumulated_reasoning = ""
        tool_call_builders: Dict[int, Dict[str, Any]] = {}
        reported_usage: Optional[Usage] = None

        try:
            response = client.chat.completions.create(**kwargs)

            for chunk in response:
                if cancel_event and cancel_event.is_set():
                    try:
                        response.close()
                    except Exception:
                        pass
                    return

                # Check usage block in chunk
                if hasattr(chunk, "usage") and chunk.usage:
                    u = chunk.usage
                    cached = getattr(getattr(u, "prompt_tokens_details", None), "cached_tokens", 0) or 0
                    reasoning_tok = getattr(getattr(u, "completion_tokens_details", None), "reasoning_tokens", 0) or 0
                    reported_usage = Usage(
                        input_tokens=u.prompt_tokens or 0,
                        output_tokens=u.completion_tokens or 0,
                        cached_tokens=cached,
                        reasoning_tokens=reasoning_tok,
                        estimated=False,
                    )
                    yield StreamEvent(type=StreamEventType.USAGE, usage=reported_usage)

                if not chunk.choices:
                    continue

                choice = chunk.choices[0]
                delta = choice.delta

                # Reasoning delta (DeepSeek, OpenRouter, vLLM)
                reasoning = getattr(delta, "reasoning", None) or getattr(delta, "reasoning_content", None)
                if reasoning:
                    accumulated_reasoning += reasoning
                    yield StreamEvent(type=StreamEventType.REASONING_DELTA, reasoning=reasoning)

                # Text delta
                if delta.content:
                    accumulated_text += delta.content
                    yield StreamEvent(type=StreamEventType.TEXT_DELTA, text=delta.content)

                # Tool call chunks
                if delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index if tc_delta.index is not None else 0
                        if idx not in tool_call_builders:
                            tool_call_builders[idx] = {
                                "id": tc_delta.id or f"call_{idx}",
                                "name": tc_delta.function.name if tc_delta.function and tc_delta.function.name else "",
                                "arguments": "",
                            }
                        else:
                            if tc_delta.id:
                                tool_call_builders[idx]["id"] = tc_delta.id
                            if tc_delta.function and tc_delta.function.name:
                                tool_call_builders[idx]["name"] += tc_delta.function.name

                        if tc_delta.function and tc_delta.function.arguments:
                            tool_call_builders[idx]["arguments"] += tc_delta.function.arguments

        except Exception as exc:
            raise map_openai_exception(exc, candidate.provider_id) from exc

        # Emit accumulated tool calls
        for idx in sorted(tool_call_builders.keys()):
            tc_data = tool_call_builders[idx]
            args_str = tc_data["arguments"]
            try:
                args_dict = json.loads(args_str) if args_str else {}
            except Exception:
                args_dict = {"raw_arguments": args_str}

            yield StreamEvent(
                type=StreamEventType.TOOL_CALL,
                tool_call=ToolCall(
                    id=tc_data["id"],
                    name=tc_data["name"],
                    arguments=args_dict,
                ),
            )

        # Fallback usage estimation if provider did not stream usage
        if reported_usage is None:
            est_in = estimate_request_tokens(request)
            est_out = estimate_tokens(accumulated_text)
            reported_usage = Usage(
                input_tokens=est_in,
                output_tokens=est_out,
                estimated=True,
            )
            yield StreamEvent(type=StreamEventType.USAGE, usage=reported_usage)

        yield StreamEvent(type=StreamEventType.DONE, finish_reason="stop")

    def list_models(self, provider: ProviderConfig) -> List[str]:
        """Query GET /models from the provider."""
        client = _create_client(provider)
        try:
            resp = client.models.list()
            return [m.id for m in resp.data]
        except Exception as exc:
            raise map_openai_exception(exc, provider.id) from exc

    def test_connection(self, provider: ProviderConfig) -> bool:
        """Perform a simple models list check to verify authentication and connectivity."""
        client = _create_client(provider)
        try:
            client.models.list()
            return True
        except Exception as exc:
            raise map_openai_exception(exc, provider.id) from exc
