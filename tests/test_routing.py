"""Unit tests for ModelMesh routing strategies, fallback chains, and health tracking."""

from collections import Counter
import pytest

from modelmesh.core.engine import ChatEngine
from modelmesh.core.errors import (
    ContextLengthError,
    RateLimitError,
    RoutingError,
)
from modelmesh.core.registry import ModelRegistry
from modelmesh.core.routing.base import build_fallback_chain, get_strategy
from modelmesh.core.routing.features import (
    extract_request_features,
    filter_eligible_candidates,
)
from modelmesh.core.routing.health import EndpointHealthTracker
from modelmesh.core.routing.router import Router
from modelmesh.core.types import (
    Candidate,
    ChatRequest,
    EndpointConfig,
    ImagePart,
    Message,
    ModelConfig,
    ProviderConfig,
    StreamEventType,
    TextPart,
    ToolSpec,
)


def create_test_registry() -> ModelRegistry:
    """Creates a multi-model, multi-provider registry fixture."""
    reg = ModelRegistry()

    # Providers
    reg.add_provider(ProviderConfig(id="prov_a", protocol="mock"))
    reg.add_provider(ProviderConfig(id="prov_b", protocol="mock"))
    reg.add_provider(ProviderConfig(id="prov_c", protocol="mock"))

    # Model 1: Cheap model with 2 endpoints (prov_a: $0.05, prov_b: $0.08)
    reg.add_model(
        ModelConfig(
            id="model_cheap",
            display_name="Cheap Model",
            tier="cheap",
            context_window=32000,
            capabilities=["streaming", "tools"],
            endpoint_policy="priority",
            endpoints=[
                EndpointConfig(
                    id="cheap@prov_a",
                    provider="prov_a",
                    api_model="cheap-a",
                    price_in_per_mtok=0.05,
                    price_out_per_mtok=0.05,
                    priority=1,
                ),
                EndpointConfig(
                    id="cheap@prov_b",
                    provider="prov_b",
                    api_model="cheap-b",
                    price_in_per_mtok=0.08,
                    price_out_per_mtok=0.08,
                    priority=2,
                ),
            ],
        )
    )

    # Model 2: Premium model with 1 endpoint ($10.00), vision capability
    reg.add_model(
        ModelConfig(
            id="model_premium",
            display_name="Premium Model",
            tier="premium",
            context_window=128000,
            capabilities=["streaming", "tools", "vision"],
            endpoint_policy="priority",
            endpoints=[
                EndpointConfig(
                    id="prem@prov_c",
                    provider="prov_c",
                    api_model="prem-c",
                    price_in_per_mtok=10.0,
                    price_out_per_mtok=30.0,
                    priority=1,
                ),
            ],
        )
    )

    # Model 3: Mid model with 2 endpoints (prov_a: $2.0, prov_b: $1.5)
    reg.add_model(
        ModelConfig(
            id="model_mid",
            display_name="Mid Model",
            tier="mid",
            context_window=64000,
            capabilities=["streaming", "tools"],
            endpoint_policy="priority",
            endpoints=[
                EndpointConfig(
                    id="mid@prov_a",
                    provider="prov_a",
                    api_model="mid-a",
                    price_in_per_mtok=2.0,
                    price_out_per_mtok=4.0,
                    priority=1,
                ),
                EndpointConfig(
                    id="mid@prov_b",
                    provider="prov_b",
                    api_model="mid-b",
                    price_in_per_mtok=1.5,
                    price_out_per_mtok=3.0,
                    priority=2,
                ),
            ],
        )
    )

    return reg


def test_capability_filtering_vision() -> None:
    reg = create_test_registry()
    tracker = EndpointHealthTracker()

    # Request with vision
    req_vision = ChatRequest(
        messages=[
            Message(
                role="user",
                parts=[TextPart(text="Check"), ImagePart(media_type="image/png", data="abc")],
            )
        ]
    )

    eligible, rejections = filter_eligible_candidates(
        candidates=reg.candidates(),
        request=req_vision,
        health_tracker=tracker,
    )

    # Only model_premium supports vision
    assert len(eligible) == 1
    assert eligible[0].model_id == "model_premium"
    assert "cheap@prov_a" in rejections
    assert "Missing required capabilities" in rejections["cheap@prov_a"]


def test_cheapest_first_strategy() -> None:
    reg = create_test_registry()
    router = Router(registry=reg)
    req = ChatRequest(messages=[Message.from_text("user", "Hello")])

    decision = router.route(request=req, strategy_name="cheapest_first")
    assert decision.strategy_name == "cheapest_first"
    assert decision.chosen_candidate.model_id == "model_cheap"
    assert decision.chosen_candidate.endpoint_id == "cheap@prov_a"

    # Verify fallback order: same model next (cheap@prov_b), then mid, then premium
    fb_ids = [c.endpoint_id for c in decision.fallback_chain]
    assert fb_ids[0] == "cheap@prov_b"
    assert "mid@prov_b" in fb_ids
    assert "prem@prov_c" == fb_ids[-1]


def test_expensive_first_strategy() -> None:
    reg = create_test_registry()
    router = Router(registry=reg)
    req = ChatRequest(messages=[Message.from_text("user", "Hello")])

    decision = router.route(request=req, strategy_name="expensive_first")
    assert decision.strategy_name == "expensive_first"
    assert decision.chosen_candidate.model_id == "model_premium"
    assert decision.chosen_candidate.endpoint_id == "prem@prov_c"


def test_random_strategy_uniformity_and_seeding() -> None:
    reg = create_test_registry()
    router = Router(registry=reg)
    req = ChatRequest(messages=[Message.from_text("user", "Hello")])

    # Test seed reproducibility
    dec1 = router.route(request=req, strategy_name="random", seed=42)
    dec2 = router.route(request=req, strategy_name="random", seed=42)
    assert dec1.chosen_candidate.endpoint_id == dec2.chosen_candidate.endpoint_id
    assert [c.endpoint_id for c in dec1.fallback_chain] == [c.endpoint_id for c in dec2.fallback_chain]

    # Test model uniformity across 600 draws
    counts = Counter()
    for s in range(600):
        d = router.route(request=req, strategy_name="random", seed=s)
        counts[d.chosen_candidate.model_id] += 1

    # With 3 models and 600 draws, each should be chosen roughly 200 times (+/- 50)
    for m in ["model_cheap", "model_mid", "model_premium"]:
        assert 140 <= counts[m] <= 260


def test_manual_pinned_endpoint_and_model() -> None:
    reg = create_test_registry()
    router = Router(registry=reg)
    req = ChatRequest(messages=[Message.from_text("user", "Hello")])

    # Pin specific endpoint -> failover disabled
    dec = router.route(request=req, strategy_name="manual", pinned_endpoint_id="mid@prov_b")
    assert dec.chosen_candidate.endpoint_id == "mid@prov_b"
    assert dec.fallback_chain == []

    # Pin model only -> fallback chain only contains sibling endpoints for the same model
    dec_m = router.route(request=req, strategy_name="manual", pinned_model_id="model_cheap")
    assert dec_m.chosen_candidate.model_id == "model_cheap"
    assert dec_m.chosen_candidate.endpoint_id == "cheap@prov_a"
    assert [c.endpoint_id for c in dec_m.fallback_chain] == ["cheap@prov_b"]


def test_endpoint_health_cooldown() -> None:
    reg = create_test_registry()
    tracker = EndpointHealthTracker(failure_threshold=3, cooldown_seconds=60.0)
    router = Router(registry=reg, health_tracker=tracker)
    req = ChatRequest(messages=[Message.from_text("user", "Hello")])

    # Record 2 failures -> still healthy
    tracker.record_failure("cheap@prov_a")
    tracker.record_failure("cheap@prov_a")
    assert tracker.is_healthy("cheap@prov_a")

    # 3rd failure -> marked unhealthy
    tracker.record_failure("cheap@prov_a")
    assert not tracker.is_healthy("cheap@prov_a")

    # Cheapest strategy should now skip cheap@prov_a and pick cheap@prov_b
    dec = router.route(request=req, strategy_name="cheapest_first")
    assert dec.chosen_candidate.endpoint_id == "cheap@prov_b"

    # Recovery on success
    tracker.record_success("cheap@prov_a")
    assert tracker.is_healthy("cheap@prov_a")
    dec2 = router.route(request=req, strategy_name="cheapest_first")
    assert dec2.chosen_candidate.endpoint_id == "cheap@prov_a"


def test_engine_failover_same_model_first() -> None:
    """Test that a simulated provider outage falls over to the same model on another provider."""
    reg = ModelRegistry()
    reg.add_provider(ProviderConfig(id="prov_a", protocol="mock"))
    reg.add_provider(ProviderConfig(id="prov_b", protocol="mock"))

    reg.add_model(
        ModelConfig(
            id="multi_model",
            display_name="Multi Model",
            endpoints=[
                EndpointConfig(
                    id="multi@prov_a",
                    provider="prov_a",
                    api_model="multi-a",
                    priority=1,
                    quirks={"simulate_error": "rate_limit"},  # Prov A fails
                ),
                EndpointConfig(
                    id="multi@prov_b",
                    provider="prov_b",
                    api_model="multi-b",
                    priority=2,  # Prov B succeeds
                ),
            ],
        )
    )

    router = Router(registry=reg)
    engine = ChatEngine(registry=reg, router=router)
    req = ChatRequest(messages=[Message.from_text("user", "Testing failover")])

    events = list(engine.run_turn(request=req, strategy_name="manual", pinned_model_id="multi_model"))

    event_types = [e.type for e in events]
    assert StreamEventType.ROUTED in event_types
    assert StreamEventType.FALLBACK in event_types
    assert StreamEventType.DONE in event_types

    # Find fallback event
    fallback_ev = next(e for e in events if e.type == StreamEventType.FALLBACK)
    assert fallback_ev.data["from_candidate"].endpoint_id == "multi@prov_a"
    assert fallback_ev.data["to_candidate"].endpoint_id == "multi@prov_b"

    # Final completed candidate was multi@prov_b
    done_ev = next(e for e in events if e.type == StreamEventType.DONE)
    assert done_ev.data["candidate"].endpoint_id == "multi@prov_b"


def test_engine_failover_model_error_skips_siblings() -> None:
    """Test that a context length error skips sibling endpoints of the same model in auto routing."""
    reg = ModelRegistry()
    reg.add_provider(ProviderConfig(id="prov_a", protocol="mock"))
    reg.add_provider(ProviderConfig(id="prov_b", protocol="mock"))
    reg.add_provider(ProviderConfig(id="prov_c", protocol="mock"))

    reg.add_model(
        ModelConfig(
            id="model_1",
            display_name="Model 1",
            endpoints=[
                EndpointConfig(
                    id="m1@prov_a",
                    provider="prov_a",
                    api_model="m1-a",
                    priority=1,
                    price_in_per_mtok=0.1,
                    price_out_per_mtok=0.1,
                    quirks={"simulate_error": "context_length"},  # Context error on m1
                ),
                EndpointConfig(
                    id="m1@prov_b",
                    provider="prov_b",
                    api_model="m1-b",
                    priority=2,
                    price_in_per_mtok=0.2,
                    price_out_per_mtok=0.2,
                ),
            ],
        )
    )
    reg.add_model(
        ModelConfig(
            id="model_2",
            display_name="Model 2",
            endpoints=[
                EndpointConfig(
                    id="m2@prov_c",
                    provider="prov_c",
                    api_model="m2-c",
                    priority=1,
                    price_in_per_mtok=0.5,
                    price_out_per_mtok=0.5,
                )
            ],
        )
    )

    router = Router(registry=reg)
    engine = ChatEngine(registry=reg, router=router)
    req = ChatRequest(messages=[Message.from_text("user", "Big request")])

    # In dynamic cheapest_first, cross-model failover is enabled
    events = list(engine.run_turn(request=req, strategy_name="cheapest_first"))

    # Because context_length skips siblings, m1@prov_b is skipped and m2@prov_c is tried
    fallback_events = [e for e in events if e.type == StreamEventType.FALLBACK]
    assert len(fallback_events) == 1
    assert fallback_events[0].data["from_candidate"].endpoint_id == "m1@prov_a"
    assert fallback_events[0].data["to_candidate"].endpoint_id == "m2@prov_c"

    done_ev = next(e for e in events if e.type == StreamEventType.DONE)
    assert done_ev.data["candidate"].endpoint_id == "m2@prov_c"


def test_engine_manual_mode_no_cross_model_failover() -> None:
    """Test that manual routing never falls over to a different model."""
    reg = ModelRegistry()
    reg.add_provider(ProviderConfig(id="prov_a", protocol="mock"))
    reg.add_provider(ProviderConfig(id="prov_b", protocol="mock"))

    reg.add_model(
        ModelConfig(
            id="model_1",
            display_name="Model 1",
            endpoints=[
                EndpointConfig(
                    id="m1@prov_a",
                    provider="prov_a",
                    api_model="m1-a",
                    priority=1,
                    quirks={"simulate_error": "rate_limit"},
                ),
            ],
        )
    )
    reg.add_model(
        ModelConfig(
            id="model_2",
            display_name="Model 2",
            endpoints=[
                EndpointConfig(
                    id="m2@prov_b",
                    provider="prov_b",
                    api_model="m2-b",
                    priority=1,
                )
            ],
        )
    )

    router = Router(registry=reg)
    engine = ChatEngine(registry=reg, router=router)
    req = ChatRequest(messages=[Message.from_text("user", "Hello")])

    events = list(engine.run_turn(request=req, strategy_name="manual", pinned_model_id="model_1"))

    # Should NOT fall back to model_2; should emit error
    event_types = [e.type for e in events]
    assert StreamEventType.ERROR in event_types
    assert StreamEventType.DONE not in event_types
    assert StreamEventType.FALLBACK not in event_types


def test_auto_strategy_excludes_mock_when_real_providers_exist(monkeypatch) -> None:
    """Test that auto routing strategies filter out mock candidates when real candidates exist."""
    # Mock environment variable for real provider auth
    monkeypatch.setenv("DUMMY_KEY", "dummy-secret-value")

    reg = ModelRegistry()
    reg.add_provider(ProviderConfig(id="real_prov", protocol="openai_compat", auth_env=["DUMMY_KEY"]))
    reg.add_provider(ProviderConfig(id="mock_prov", protocol="mock"))

    # Real model ($5/Mtok)
    reg.add_model(
        ModelConfig(
            id="real_model",
            display_name="Real Flagship Model",
            endpoints=[
                EndpointConfig(
                    id="real@real_prov",
                    provider="real_prov",
                    api_model="real-v1",
                    price_in_per_mtok=5.0,
                    price_out_per_mtok=5.0,
                )
            ],
        )
    )

    # Mock model ($20/Mtok - more expensive)
    reg.add_model(
        ModelConfig(
            id="mock_expensive",
            display_name="Mock Expensive Model",
            endpoints=[
                EndpointConfig(
                    id="mock@mock_prov",
                    provider="mock_prov",
                    api_model="mock-exp",
                    price_in_per_mtok=20.0,
                    price_out_per_mtok=20.0,
                )
            ],
        )
    )

    router = Router(registry=reg)
    req = ChatRequest(messages=[Message.from_text("user", "Hello router")])

    # In expensive_first, even though mock is $20 and real is $5, auto strategy MUST pick the real model!
    decision = router.route(request=req, strategy_name="expensive_first")
    assert decision.chosen_candidate.model_id == "real_model"
    assert all(c.model_id != "mock_expensive" for c in decision.fallback_chain)

    # In manual mode, user can specifically request the mock model
    manual_decision = router.route(request=req, strategy_name="manual", pinned_model_id="mock_expensive")
    assert manual_decision.chosen_candidate.model_id == "mock_expensive"

