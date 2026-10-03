"""Tests for the Mock provider adapter and ChatEngine."""

import threading
from modelmesh.core.engine import ChatEngine
from modelmesh.core.errors import RateLimitError
from modelmesh.core.providers.base import get_adapter
from modelmesh.core.registry import ModelRegistry
from modelmesh.core.types import (
    Candidate,
    ChatRequest,
    EndpointConfig,
    Message,
    ModelConfig,
    ProviderConfig,
    StreamEventType,
    ToolSpec,
)


def create_mock_registry() -> ModelRegistry:
    reg = ModelRegistry()
    provider = ProviderConfig(id="mock", protocol="mock")
    reg.add_provider(provider)

    model = ModelConfig(
        id="mock-model",
        display_name="Mock Model",
        endpoints=[
            EndpointConfig(
                id="mock-model@mock",
                provider="mock",
                api_model="mock-instant",
                price_in_per_mtok=0.01,
                price_out_per_mtok=0.02,
            )
        ],
    )
    reg.add_model(model)
    return reg


def test_mock_adapter_streaming() -> None:
    adapter = get_adapter("mock")
    assert adapter.test_connection(ProviderConfig(id="mock", protocol="mock"))
    assert len(adapter.list_models(ProviderConfig(id="mock", protocol="mock"))) > 0

    reg = create_mock_registry()
    cand = reg.candidates()[0]
    req = ChatRequest(messages=[Message.from_text(role="user", text="Ping")])

    events = list(adapter.stream_chat(request=req, candidate=cand))
    types = [e.type for e in events]
    assert StreamEventType.TEXT_DELTA in types
    assert StreamEventType.USAGE in types
    assert StreamEventType.DONE in types

    accumulated = "".join(e.text for e in events if e.type == StreamEventType.TEXT_DELTA and e.text)
    assert "Mock reply" in accumulated


def test_mock_adapter_simulated_error() -> None:
    reg = ModelRegistry()
    reg.add_provider(ProviderConfig(id="mock", protocol="mock"))
    model = ModelConfig(
        id="mock-err-model",
        display_name="Mock Error Model",
        endpoints=[
            EndpointConfig(
                id="mock-err@mock",
                provider="mock",
                api_model="mock-instant",
                quirks={"simulate_error": "rate_limit"},
            )
        ],
    )
    reg.add_model(model)
    cand = reg.candidates()[0]
    adapter = get_adapter("mock")
    req = ChatRequest(messages=[Message.from_text(role="user", text="Ping")])

    try:
        list(adapter.stream_chat(request=req, candidate=cand))
        assert False, "Should have raised RateLimitError"
    except RateLimitError as exc:
        assert exc.category == "rate_limit"
        assert exc.provider_id == "mock"


def test_mock_adapter_cancellation() -> None:
    reg = create_mock_registry()
    cand = reg.candidates()[0]
    adapter = get_adapter("mock")
    req = ChatRequest(messages=[Message.from_text(role="user", text="Ping")])

    cancel_event = threading.Event()
    cancel_event.set()  # Cancel immediately

    events = list(adapter.stream_chat(request=req, candidate=cand, cancel_event=cancel_event))
    assert len(events) == 0  # Stopped before any chunk


def test_engine_run_turn_with_mock() -> None:
    reg = create_mock_registry()
    engine = ChatEngine(registry=reg)
    req = ChatRequest(messages=[Message.from_text(role="user", text="Hello engine")])

    events = list(engine.run_turn(request=req))
    event_types = [e.type for e in events]

    assert StreamEventType.ROUTED == event_types[0]
    assert StreamEventType.DONE == event_types[-1]

    # Verify done event metadata
    done_event = events[-1]
    assert "cost_usd" in done_event.data
    assert "latency_sec" in done_event.data
