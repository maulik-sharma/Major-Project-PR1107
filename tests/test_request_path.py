"""Request path: stalled streams and Stop, out-of-credits providers, streamed tool-call assembly."""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from typing import Iterator, List, Optional

import httpx
import pytest

from modelmesh.core.engine import ChatEngine
from modelmesh.core.errors import BillingError, ProviderError, friendly_error
from modelmesh.core.providers.anthropic import map_anthropic_exception
from modelmesh.core.providers.base import ProviderAdapter, register_adapter
from modelmesh.core.providers.openai_compat import _tool_call_key, map_openai_exception
from modelmesh.core.registry import ModelRegistry
from modelmesh.core.routing.router import Router
from modelmesh.core.streaming import iterate_cancellable
from modelmesh.core.types import (
    Candidate,
    ChatRequest,
    EndpointConfig,
    Message,
    ModelConfig,
    ProviderConfig,
    StreamEvent,
    StreamEventType,
)

CALLS: List[str] = []


@register_adapter("stall_test")
class StallAdapter(ProviderAdapter):
    """Accepts the request, then never sends anything (ignores cancel, like a blocked socket read)."""

    def stream_chat(self, request: ChatRequest, candidate: Candidate,
                    cancel_event: Optional[threading.Event] = None) -> Iterator[StreamEvent]:
        CALLS.append(candidate.endpoint_id)
        time.sleep(5)
        yield StreamEvent(type=StreamEventType.DONE)

    def list_models(self, provider: ProviderConfig) -> List[str]:
        return []

    def map_error(self, exc: Exception, provider_id: str) -> Exception:
        return exc


@register_adapter("broke_test")
class BrokeAdapter(StallAdapter):
    """Every request fails because the account has no credits."""

    def stream_chat(self, request: ChatRequest, candidate: Candidate,
                    cancel_event: Optional[threading.Event] = None) -> Iterator[StreamEvent]:
        CALLS.append(candidate.endpoint_id)
        raise BillingError("no credits remaining", provider_id=candidate.provider_id)
        yield  # pragma: no cover


@register_adapter("ok_test")
class OkAdapter(StallAdapter):
    """Answers immediately."""

    def stream_chat(self, request: ChatRequest, candidate: Candidate,
                    cancel_event: Optional[threading.Event] = None) -> Iterator[StreamEvent]:
        CALLS.append(candidate.endpoint_id)
        yield StreamEvent(type=StreamEventType.TEXT_DELTA, text="hello")
        yield StreamEvent(type=StreamEventType.DONE)


def _engine(models: List[tuple]) -> ChatEngine:
    """models: (model_id, provider_id, protocol, price_out)."""
    reg = ModelRegistry()
    for prov, proto in {(m[1], m[2]) for m in models}:
        reg.add_provider(ProviderConfig(id=prov, protocol=proto))
    for mid, prov, _, price in models:
        reg.add_model(ModelConfig(id=mid, display_name=mid, capabilities=["streaming"], endpoints=[
            EndpointConfig(id=f"{mid}@{prov}", provider=prov, api_model=mid, price_out_per_mtok=price)]))
    return ChatEngine(registry=reg, router=Router(registry=reg))


def _request() -> ChatRequest:
    return ChatRequest(messages=[Message.from_text("user", "hi")])


def test_iterate_cancellable_returns_promptly_on_cancel() -> None:
    cancel = threading.Event()

    def stalled() -> Iterator[int]:
        yield 1
        time.sleep(5)
        yield 2

    t0 = time.time()
    got = []
    for item in iterate_cancellable(stalled, cancel, poll_seconds=0.02):
        got.append(item)
        threading.Timer(0.1, cancel.set).start()
    assert got == [1] and time.time() - t0 < 1.0


def test_iterate_cancellable_reraises_errors() -> None:
    def boom() -> Iterator[int]:
        raise ValueError("bad")
        yield 0  # pragma: no cover

    with pytest.raises(ValueError):
        list(iterate_cancellable(boom, threading.Event()))


def test_stop_ends_a_stalled_turn_quickly() -> None:
    engine = _engine([("stuck", "slowprov", "stall_test", 1.0)])
    cancel = threading.Event()
    threading.Timer(0.3, cancel.set).start()
    t0 = time.time()
    events = list(engine.run_turn(_request(), strategy_name="cheapest_first", cancel_event=cancel))
    assert time.time() - t0 < 1.5
    assert not any(e.type == StreamEventType.DONE for e in events)


def test_out_of_credits_skips_the_whole_provider() -> None:
    CALLS.clear()
    engine = _engine([
        ("a1", "broke", "broke_test", 1.0), ("a2", "broke", "broke_test", 2.0),
        ("a3", "broke", "broke_test", 3.0), ("good", "fine", "ok_test", 9.0),
    ])
    events = list(engine.run_turn(_request(), strategy_name="cheapest_first"))
    assert any(e.type == StreamEventType.DONE for e in events)
    assert CALLS == ["a1@broke", "good@fine"]  # a2/a3 not tried after the billing failure

    CALLS.clear()
    list(engine.run_turn(_request(), strategy_name="cheapest_first"))
    assert CALLS == ["good@fine"]  # next turn: provider still skipped


def test_all_providers_broke_reports_billing_kind() -> None:
    engine = _engine([("a1", "broke", "broke_test", 1.0)])
    errors = [e for e in engine.run_turn(_request(), strategy_name="cheapest_first") if e.type == StreamEventType.ERROR]
    assert errors and errors[-1].data["kind"] == "billing"
    message, _, category = friendly_error(errors[-1].data["error"], errors[-1].data["category"], "billing")
    assert category == "auth" and "out of credits" in message


def _http_error(status: int, message: str) -> httpx.HTTPStatusError:
    req = httpx.Request("POST", "https://api.test/v1/chat/completions")
    resp = httpx.Response(status, json={"error": {"message": message}}, request=req)
    return httpx.HTTPStatusError(str(status), request=req, response=resp)


def test_credit_errors_map_to_billing() -> None:
    oa = map_openai_exception(_http_error(429, "You have no credits remaining. insufficient_quota"), "openai")
    an = map_anthropic_exception(_http_error(400, "Your credit balance is too low to access the API"), "anthropic")
    for err in (oa, an):
        assert isinstance(err, BillingError) and err.category == "auth" and err.kind == "billing"
    plain = map_openai_exception(_http_error(429, "Rate limit reached"), "openai")
    assert isinstance(plain, ProviderError) and plain.category == "rate_limit" and plain.kind is None


def _delta(index: Optional[int], call_id: Optional[str], name: str = "", args: str = "") -> SimpleNamespace:
    return SimpleNamespace(index=index, id=call_id, function=SimpleNamespace(name=name, arguments=args))


def test_parallel_tool_calls_without_index_stay_separate() -> None:
    builders: dict = {}
    for d in [_delta(None, "c1", "web_search", '{"q": 1}'), _delta(None, "c2", "get_time", "{}")]:
        key = _tool_call_key(d, builders)
        builders.setdefault(key, {"id": d.id, "name": d.function.name, "arguments": d.function.arguments})
    assert [b["name"] for b in builders.values()] == ["web_search", "get_time"]


def test_indexed_fragments_still_assemble() -> None:
    builders: dict = {0: {"id": "c1", "name": "web_search", "arguments": '{"q"'}}
    assert _tool_call_key(_delta(0, None, args=': 1}'), builders) == 0
    assert _tool_call_key(_delta(None, None, args="more"), builders) == 0
