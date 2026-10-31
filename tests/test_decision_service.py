"""DecisionService fail-open behaviour (Rule 17), validation, privacy, and heuristic quality."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List

import pytest

from modelmesh.core.config.routing_config import DecisionProviderConfig, load_routing_config
from modelmesh.core.routing.smart.decision import service as service_mod
from modelmesh.core.routing.smart.decision.base import (
    DecisionProvider,
    DecisionRequest,
    DecisionResult,
    register_decision_provider,
)
from modelmesh.core.routing.smart.decision.heuristic import HeuristicDecisionProvider
from modelmesh.core.routing.smart.decision.mock import MockDecisionProvider
from modelmesh.core.routing.smart.decision.service import CircuitBreaker, DecisionService
from modelmesh.core.routing.smart.state_builder import build_decision_state
from modelmesh.core.storage import Storage
from modelmesh.core.types import Message

GOOD_ANSWERS: Dict[str, Any] = MockDecisionProvider().preset_answers


@register_decision_provider("fake_remote")
class FakeRemoteProvider(DecisionProvider):
    """Remote-flagged provider whose behaviour each test controls."""

    remote = True
    answers: Any = GOOD_ANSWERS
    calls: List[DecisionRequest] = []
    error: Exception | None = None

    def decide(self, request: DecisionRequest) -> DecisionResult:
        FakeRemoteProvider.calls.append(request)
        if FakeRemoteProvider.error is not None:
            raise FakeRemoteProvider.error
        return DecisionResult(answers=FakeRemoteProvider.answers, source="clef", provider_id=request.provider_id)


@pytest.fixture(autouse=True)
def _reset_fake() -> None:
    FakeRemoteProvider.answers = GOOD_ANSWERS
    FakeRemoteProvider.calls = []
    FakeRemoteProvider.error = None


def make_service(tmp_path: Path, send_prompt_text: bool = True, storage: Any = "default") -> DecisionService:
    cfg = load_routing_config()
    cfg.decision.providers.append(DecisionProviderConfig(id="fake", protocol="fake_remote", model="fake-model"))
    cfg.decision.active = "fake"
    cfg.decision.send_prompt_text = send_prompt_text
    if storage == "default":
        storage = Storage(tmp_path / "decision.db")
    return DecisionService(config=cfg, storage=storage)


def user(text: str) -> List[Message]:
    return [Message.from_text("user", text)]


def test_valid_remote_answer_is_used_and_cached(tmp_path: Path) -> None:
    svc = make_service(tmp_path)
    first = svc.get_decision(user("Explain monads"))
    second = svc.get_decision(user("Explain monads"))
    assert first.source == "clef"
    assert second.source == "cache"
    assert len(FakeRemoteProvider.calls) == 1


@pytest.mark.parametrize(
    "answers",
    [
        {"task": GOOD_ANSWERS["task"]},  # required keys missing
        {**GOOD_ANSWERS, "difficulty": 3},  # not an object
        {**GOOD_ANSWERS, "task": {"choice": "astrology"}},  # unknown choice
        {**GOOD_ANSWERS, "difficulty": {"score": "high"}},  # non-numeric
    ],
)
def test_invalid_answers_fall_back_to_heuristic(tmp_path: Path, answers: Dict[str, Any]) -> None:
    FakeRemoteProvider.answers = answers
    res = make_service(tmp_path).get_decision(user("Hello"))
    assert res.source == "heuristic_fallback"
    assert res.error


def test_out_of_range_scores_are_clamped(tmp_path: Path) -> None:
    FakeRemoteProvider.answers = {**GOOD_ANSWERS, "difficulty": {"score": 9, "confidence": 4}}
    res = make_service(tmp_path).get_decision(user("Hello"))
    assert res.source == "clef"
    assert res.answers["difficulty"] == {"score": 4.0, "confidence": 1.0}


def test_cache_write_error_keeps_good_decision(tmp_path: Path) -> None:
    class BrokenStorage:
        def get_decision_cache(self, key: str) -> None:
            return None

        def save_decision_cache(self, **kwargs: Any) -> None:
            raise RuntimeError("database is locked")

    svc = make_service(tmp_path, storage=BrokenStorage())
    for _ in range(4):
        assert svc.get_decision(user("Hello")).source == "clef"
    assert not svc._get_breaker("fake").is_open()


def test_state_building_error_falls_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(**kwargs: Any) -> None:
        raise ValueError("bad message")

    monkeypatch.setattr(service_mod, "build_decision_state", boom)
    res = make_service(tmp_path).get_decision(user("Hello"))
    assert res.source == "heuristic_fallback"


def test_unknown_active_provider_falls_back(tmp_path: Path) -> None:
    res = make_service(tmp_path).get_decision(user("Hello"), provider_override="nope")
    assert res.source == "heuristic_fallback"


def test_network_error_does_not_retry(tmp_path: Path) -> None:
    from modelmesh.core.errors import ProviderError

    FakeRemoteProvider.error = ProviderError("timeout", category="network")
    res = make_service(tmp_path).get_decision(user("Hello"))
    assert res.source == "heuristic_fallback"
    assert len(FakeRemoteProvider.calls) == 1


def test_privacy_mode_sends_nothing_remote_but_still_routes_hard_prompts(tmp_path: Path) -> None:
    svc = make_service(tmp_path, send_prompt_text=False)
    res = svc.get_decision(user("Prove rigorously that there are infinitely many primes, step by step."))
    assert FakeRemoteProvider.calls == []
    assert res.source == "heuristic"
    assert res.answers["task"]["choice"] == "math_reasoning"
    assert res.answers["difficulty"]["score"] >= 2.5


def test_circuit_breaker_half_open_single_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    now = [1000.0]
    monkeypatch.setattr(service_mod.time, "time", lambda: now[0])
    br = CircuitBreaker(failure_threshold=3, cooldown_seconds=60)
    for _ in range(3):
        br.record_failure()
    assert not br.allow_request()

    now[0] += 61
    assert br.allow_request()  # the one probe
    assert not br.allow_request()  # no second concurrent probe
    br.record_failure()  # failed probe re-opens at once
    assert not br.allow_request()

    now[0] += 61
    assert br.allow_request()
    br.record_success()
    assert br.allow_request() and br.allow_request()


@pytest.mark.parametrize(
    "text, task",
    [
        ("I trust you, thanks for the help", "chat_general"),
        ("That was an exceptional answer", "chat_general"),
        ("Fix this Python traceback: KeyError in my loop", "coding"),
        ("Write me a poem about autumn", "writing_creative"),
        ("Summarize this article in three bullet points", "summarization_extraction"),
    ],
)
def test_heuristic_task_classification(text: str, task: str) -> None:
    res = HeuristicDecisionProvider().decide(DecisionRequest(state="", questions={}, latest_text=text))
    assert res.answers["task"]["choice"] == task


def test_heuristic_greeting_is_trivial_even_with_tools_and_history() -> None:
    res = HeuristicDecisionProvider().decide(
        DecisionRequest(state="", questions={}, latest_text="hi", context={"tools_enabled": True, "history_messages": 6})
    )
    assert res.answers["difficulty"]["score"] <= 0.1


def test_heuristic_difficulty_orders_prompts() -> None:
    def diff(text: str) -> float:
        return HeuristicDecisionProvider().decide(DecisionRequest(state="", questions={}, latest_text=text)).answers["difficulty"]["score"]

    assert diff("hello") < diff("What's the capital of France?") < diff(
        "Design a lock-free concurrent queue in Rust and prove it is linearizable."
    )


def test_service_heuristic_ignores_code_in_earlier_assistant_turns(tmp_path: Path) -> None:
    cfg = load_routing_config()
    cfg.decision.active = "heuristic"
    svc = DecisionService(config=cfg)
    msgs = [
        Message.from_text("user", "show me a loop"),
        Message.from_text("assistant", "```python\nfor i in range(3): print(i)\n```"),
        Message.from_text("user", "thanks!"),
    ]
    res = svc.get_decision(msgs)
    assert res.answers["task"]["choice"] == "chat_general"
    assert res.answers["difficulty"]["score"] <= 0.1


def test_decision_state_is_bounded_and_labels_tool_messages() -> None:
    msgs = [
        Message.from_text("user", "a" * 5000),
        Message.from_text("tool", "scraped page text"),
        Message.from_text("user", "b" * 50_000),
    ]
    state, _ = build_decision_state(msgs, max_tokens=500)
    assert len(state) <= 500 * 3 + 50
    assert "Assistant: scraped" not in state


def test_cloudflare_adapter_uses_configured_url_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    import httpx

    from modelmesh.core.errors import ProviderError
    from modelmesh.core.routing.smart.decision.cloudflare import CloudflareDecisionAdapter

    fixture = json.loads((Path(__file__).parent / "fixtures" / "clef_response_synthetic.json").read_text("utf-8"))
    seen: List[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=fixture)

    monkeypatch.setenv("TEST_CF_ACCOUNT", "acct123")
    monkeypatch.setenv("TEST_CF_TOKEN", "tok-secret")
    adapter = CloudflareDecisionAdapter.from_config(
        DecisionProviderConfig(
            id="clef",
            protocol="cloudflare_decision",
            auth_env=["TEST_CF_ACCOUNT", "TEST_CF_TOKEN"],
            model="clef-x",
            base_url="https://example.test/accounts/{account_id}/run",
        )
    )
    adapter._client = httpx.Client(transport=httpx.MockTransport(handler))
    res = adapter.decide(DecisionRequest(state="s", questions={}, model="clef-x", provider_id="clef"))

    assert str(seen[0].url) == "https://example.test/accounts/acct123/run/clef-x"
    assert seen[0].headers["Authorization"] == "Bearer tok-secret"
    assert res.source == "clef"
    assert res.answers["task"]["choice"] == fixture["result"]["answers"]["task"]["choice"]

    adapter._client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(400, text="tok-secret echoed")))
    with pytest.raises(ProviderError) as exc_info:
        adapter.decide(DecisionRequest(state="s", questions={}, model="clef-x", provider_id="clef"))
    assert "tok-secret" not in str(exc_info.value)
