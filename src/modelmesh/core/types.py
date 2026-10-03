"""Canonical provider-neutral data types for ModelMesh."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Set, Union


Role = Literal["system", "user", "assistant", "tool"]
Tier = Literal["cheap", "mid", "premium"]
EndpointPolicy = Literal["priority", "cheapest", "fastest"]
Capability = Literal["streaming", "tools", "vision", "reasoning", "json_mode"]


@dataclass
class TextPart:
    """A textual part of a message."""
    text: str
    type: Literal["text"] = "text"

    def to_dict(self) -> Dict[str, Any]:
        return {"type": self.type, "text": self.text}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TextPart:
        return cls(text=data.get("text", ""))


@dataclass
class ImagePart:
    """An image part of a message (base64 encoded)."""
    media_type: str
    data: str  # Base64 encoded image string
    type: Literal["image"] = "image"

    def to_dict(self) -> Dict[str, Any]:
        return {"type": self.type, "media_type": self.media_type, "data": self.data}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ImagePart:
        return cls(
            media_type=data.get("media_type", "image/png"),
            data=data.get("data", ""),
        )


ContentPart = Union[TextPart, ImagePart]


@dataclass
class ToolSpec:
    """Specification of an invokable tool."""
    name: str
    description: str
    parameters: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ToolSpec:
        return cls(
            name=data["name"],
            description=data.get("description", ""),
            parameters=data.get("parameters", {}),
        )


@dataclass
class ToolCall:
    """A tool call requested by an LLM."""
    id: str
    name: str
    arguments: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "arguments": self.arguments,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ToolCall:
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            arguments=data.get("arguments", {}),
        )


@dataclass
class Usage:
    """Token usage and cache statistics for a model call."""
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    reasoning_tokens: int = 0
    estimated: bool = False

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def to_dict(self) -> Dict[str, Any]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cached_tokens": self.cached_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "estimated": self.estimated,
            "total_tokens": self.total_tokens,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Usage:
        return cls(
            input_tokens=data.get("input_tokens", 0),
            output_tokens=data.get("output_tokens", 0),
            cached_tokens=data.get("cached_tokens", 0),
            reasoning_tokens=data.get("reasoning_tokens", 0),
            estimated=data.get("estimated", False),
        )


@dataclass
class Message:
    """A canonical conversation message."""
    role: Role
    parts: List[ContentPart] = field(default_factory=list)
    tool_calls: List[ToolCall] = field(default_factory=list)
    tool_call_id: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: float = field(default_factory=time.time)

    def text_content(self) -> str:
        """Extract concatenated text from all TextParts."""
        return "".join(part.text for part in self.parts if isinstance(part, TextPart))

    @classmethod
    def from_text(
        cls,
        role: Role,
        text: str,
        meta: Optional[Dict[str, Any]] = None,
        msg_id: Optional[str] = None,
    ) -> Message:
        """Convenience constructor from raw text."""
        kwargs: Dict[str, Any] = {
            "role": role,
            "parts": [TextPart(text=text)],
            "meta": meta or {},
        }
        if msg_id:
            kwargs["id"] = msg_id
        return cls(**kwargs)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "role": self.role,
            "parts": [p.to_dict() for p in self.parts],
            "tool_calls": [tc.to_dict() for tc in self.tool_calls],
            "tool_call_id": self.tool_call_id,
            "meta": self.meta,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Message:
        raw_parts = data.get("parts", [])
        parts: List[ContentPart] = []
        for p in raw_parts:
            if p.get("type") == "image":
                parts.append(ImagePart.from_dict(p))
            else:
                parts.append(TextPart.from_dict(p))

        raw_tool_calls = data.get("tool_calls", [])
        tool_calls = [ToolCall.from_dict(tc) for tc in raw_tool_calls]

        return cls(
            role=data.get("role", "user"),
            parts=parts,
            tool_calls=tool_calls,
            tool_call_id=data.get("tool_call_id"),
            meta=data.get("meta", {}),
            id=data.get("id", str(uuid.uuid4())),
            created_at=data.get("created_at", time.time()),
        )


@dataclass
class ChatRequest:
    """Canonical request passed to providers and routers."""
    messages: List[Message]
    system_prompt: Optional[str] = None
    tools: List[ToolSpec] = field(default_factory=list)
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    extra_params: Dict[str, Any] = field(default_factory=dict)
    required_capabilities: Set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        if not self.required_capabilities:
            caps: Set[str] = {"streaming"}
            if self.tools:
                caps.add("tools")
            for msg in self.messages:
                for part in msg.parts:
                    if isinstance(part, ImagePart):
                        caps.add("vision")
            self.required_capabilities = caps


class StreamEventType(str, Enum):
    """Event types yielded during stream processing."""
    TEXT_DELTA = "text_delta"
    REASONING_DELTA = "reasoning_delta"
    TOOL_CALL = "tool_call"
    USAGE = "usage"
    DONE = "done"
    ROUTED = "routed"
    FALLBACK = "fallback"
    TOOL_START = "tool_start"
    TOOL_RESULT = "tool_result"
    ERROR = "error"


@dataclass
class StreamEvent:
    """A single event emitted during chat streaming."""
    type: StreamEventType
    text: Optional[str] = None
    reasoning: Optional[str] = None
    tool_call: Optional[ToolCall] = None
    usage: Optional[Usage] = None
    finish_reason: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderConfig:
    """Configuration for an LLM provider."""
    id: str
    protocol: str  # "openai_compat", "anthropic", "mock", "bedrock"
    base_url: Optional[str] = None
    auth_env: List[str] = field(default_factory=list)
    options: Dict[str, Any] = field(default_factory=dict)
    connect_timeout: float = 10.0
    read_timeout: float = 120.0
    extra_headers: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "protocol": self.protocol,
            "base_url": self.base_url,
            "auth_env": self.auth_env,
            "options": self.options,
            "connect_timeout": self.connect_timeout,
            "read_timeout": self.read_timeout,
            "extra_headers": self.extra_headers,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ProviderConfig:
        return cls(
            id=data["id"],
            protocol=data["protocol"],
            base_url=data.get("base_url"),
            auth_env=data.get("auth_env", []),
            options=data.get("options", {}),
            connect_timeout=float(data.get("connect_timeout", 10.0)),
            read_timeout=float(data.get("read_timeout", 120.0)),
            extra_headers=data.get("extra_headers", {}),
        )


@dataclass
class EndpointConfig:
    """Configuration for a provider's endpoint serving a model."""
    id: str
    provider: str
    api_model: str
    price_in_per_mtok: float = 0.0
    price_out_per_mtok: float = 0.0
    priority: int = 1
    enabled: bool = True
    context_window: Optional[int] = None
    max_output: Optional[int] = None
    capabilities: Optional[List[str]] = None
    quirks: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "id": self.id,
            "provider": self.provider,
            "api_model": self.api_model,
            "price_in_per_mtok": self.price_in_per_mtok,
            "price_out_per_mtok": self.price_out_per_mtok,
            "priority": self.priority,
            "enabled": self.enabled,
            "quirks": self.quirks,
        }
        if self.context_window is not None:
            data["context_window"] = self.context_window
        if self.max_output is not None:
            data["max_output"] = self.max_output
        if self.capabilities is not None:
            data["capabilities"] = self.capabilities
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> EndpointConfig:
        return cls(
            id=data["id"],
            provider=data["provider"],
            api_model=data["api_model"],
            price_in_per_mtok=float(data.get("price_in_per_mtok", 0.0)),
            price_out_per_mtok=float(data.get("price_out_per_mtok", 0.0)),
            priority=int(data.get("priority", 1)),
            enabled=data.get("enabled", True),
            context_window=data.get("context_window"),
            max_output=data.get("max_output"),
            capabilities=data.get("capabilities"),
            quirks=data.get("quirks", {}),
        )


@dataclass
class ModelConfig:
    """Logical LLM configuration representing a model across endpoints."""
    id: str
    display_name: str
    tier: Tier = "mid"
    context_window: int = 128000
    max_output: int = 4096
    capabilities: List[str] = field(default_factory=lambda: ["streaming"])
    local: bool = False
    enabled: bool = True
    endpoint_policy: EndpointPolicy = "priority"
    endpoints: List[EndpointConfig] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "tier": self.tier,
            "context_window": self.context_window,
            "max_output": self.max_output,
            "capabilities": self.capabilities,
            "local": self.local,
            "enabled": self.enabled,
            "endpoint_policy": self.endpoint_policy,
            "endpoints": [ep.to_dict() for ep in self.endpoints],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ModelConfig:
        return cls(
            id=data["id"],
            display_name=data.get("display_name", data["id"]),
            tier=data.get("tier", "mid"),
            context_window=int(data.get("context_window", 128000)),
            max_output=int(data.get("max_output", 4096)),
            capabilities=data.get("capabilities", ["streaming"]),
            local=data.get("local", False),
            enabled=data.get("enabled", True),
            endpoint_policy=data.get("endpoint_policy", "priority"),
            endpoints=[EndpointConfig.from_dict(ep) for ep in data.get("endpoints", [])],
        )


@dataclass
class Candidate:
    """A fully resolved (Model, Endpoint, Provider) candidate."""
    model_id: str
    model_display_name: str
    tier: Tier
    local: bool
    endpoint_id: str
    provider_id: str
    protocol: str
    api_model: str
    price_in_per_mtok: float
    price_out_per_mtok: float
    priority: int
    effective_context_window: int
    effective_max_output: int
    effective_capabilities: Set[str]
    effective_quirks: Dict[str, Any]
    provider_config: ProviderConfig
    endpoint_config: EndpointConfig
    model_config: ModelConfig

    @classmethod
    def resolve(
        cls,
        model: ModelConfig,
        endpoint: EndpointConfig,
        provider: ProviderConfig,
    ) -> Candidate:
        """Build a candidate with endpoint overrides taking precedence."""
        ctx_win = (
            endpoint.context_window
            if endpoint.context_window is not None
            else model.context_window
        )
        max_out = (
            endpoint.max_output
            if endpoint.max_output is not None
            else model.max_output
        )
        caps = (
            set(endpoint.capabilities)
            if endpoint.capabilities is not None
            else set(model.capabilities)
        )
        # Merge quirks
        quirks = dict(endpoint.quirks)

        return cls(
            model_id=model.id,
            model_display_name=model.display_name,
            tier=model.tier,
            local=model.local,
            endpoint_id=endpoint.id,
            provider_id=provider.id,
            protocol=provider.protocol,
            api_model=endpoint.api_model,
            price_in_per_mtok=endpoint.price_in_per_mtok,
            price_out_per_mtok=endpoint.price_out_per_mtok,
            priority=endpoint.priority,
            effective_context_window=ctx_win,
            effective_max_output=max_out,
            effective_capabilities=caps,
            effective_quirks=quirks,
            provider_config=provider,
            endpoint_config=endpoint,
            model_config=model,
        )


@dataclass
class RoutingDecision:
    """Outcome of the routing strategy for a single turn."""
    chosen_candidate: Candidate
    fallback_chain: List[Candidate]
    strategy_name: str
    reason: str
    eligible_candidates: List[Dict[str, Any]] = field(default_factory=list)
    request_features: Dict[str, Any] = field(default_factory=dict)
    seed: Optional[int] = None
    decision_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: float = field(default_factory=time.time)
