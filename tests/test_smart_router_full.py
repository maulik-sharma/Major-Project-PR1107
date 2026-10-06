"""Comprehensive unit tests covering all components of Phase 1 SmartRouter."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List
import pytest

from modelmesh.core.config.routing_config import (
    DecisionConfig,
    NeedConfig,
    PoolConfig,
    RubricConfig,
    SmartRoutingConfig,
    load_routing_config,
)
from modelmesh.core.engine import ChatEngine
from modelmesh.core.registry import ModelRegistry
from modelmesh.core.routing.router import Router
from modelmesh.core.routing.smart.decision.base import (
    DecisionRequest,
    DecisionResult,
)
from modelmesh.core.routing.smart.decision.cloudflare import CloudflareDecisionAdapter
from modelmesh.core.routing.smart.decision.heuristic import HeuristicDecisionProvider
from modelmesh.core.routing.smart.decision.mock import MockDecisionProvider
from modelmesh.core.routing.smart.decision.service import DecisionService
from modelmesh.core.routing.smart.rubric import build_rubric_questions, compute_rubric_hash
from modelmesh.core.routing.smart.scoring import (
    compute_bar,
    compute_need,
    normalize_scores_to_quality,
)
from modelmesh.core.routing.smart.selector import select_smart_candidate
from modelmesh.core.routing.smart.state_builder import build_decision_state
from modelmesh.core.routing.smart.strategy import SmartClefStrategy
from modelmesh.core.scores.matcher import suggest_model_slugs
from modelmesh.core.scores.snapshots import (
    EffectiveScores,
    ScoreSnapshot,
    ScoreStore,
    resolve_effective_scores,
)
from modelmesh.core.storage import Storage
from modelmesh.core.types import (
    Candidate,
    ChatRequest,
    EndpointConfig,
    ManualScoresConfig,
    Message,
    ModelConfig,
    ModelScoresConfig,
    TextPart,
)


@pytest.fixture
def synthetic_snapshot() -> ScoreSnapshot:
    models_list = [
        {
            "slug": "anthropic/claude-3-5-sonnet",
            "name": "Claude 3.5 Sonnet",
            "evaluations": {
                "artificial_analysis_intelligence_index": 88.0,
                "artificial_analysis_coding_index": 92.0,
                "artificial_analysis_agentic_index": 90.0,
            },
        },
        {
            "slug": "openai/gpt-4o-mini",
            "name": "GPT-4o Mini",
            "evaluations": {
                "artificial_analysis_intelligence_index": 74.0,
                "artificial_analysis_coding_index": 76.0,
                "artificial_analysis_agentic_index": 75.0,
            },
        },
        {
            "slug": "google/gemma-2-2b",
            "name": "Gemma 2 2B",
            "evaluations": {
                "artificial_analysis_intelligence_index": 52.0,
                "artificial_analysis_coding_index": 48.0,
                "artificial_analysis_agentic_index": 45.0,
            },
        },
        {
            "slug": "meta-llama/llama-3.3-70b-instruct",
            "name": "Llama 3.3 70B Instruct",
            "evaluations": {
                "artificial_analysis_intelligence_index": 80.0,
                "artificial_analysis_coding_index": 82.0,
                "artificial_analysis_agentic_index": 79.0,
            },
        },
    ]
    return ScoreSnapshot.from_raw(
        models_list=models_list,
        index_version="v2",
        source="artificial_analysis",
        rate_limit_remaining=95,
        snapshot_id="test-snap-001",
    )



def test_effective_score_priority_and_unscored(synthetic_snapshot: ScoreSnapshot):
    # 1. Linked model without manual overrides
    m1 = ModelConfig(
        id="claude-3-5-sonnet",
        display_name="Claude 3.5 Sonnet",
        tier="premium",
        scores=ModelScoresConfig(aa_slug="anthropic/claude-3-5-sonnet"),
    )
    eff1 = resolve_effective_scores(m1, synthetic_snapshot)
    assert not eff1.is_unscored
    assert eff1.source == "snapshot"
    assert eff1.intelligence == 88.0
    assert eff1.coding == 92.0

    # 2. Model with manual override taking precedence over snapshot
    m2 = ModelConfig(
        id="claude-3-5-sonnet-custom",
        display_name="Claude 3.5 Sonnet Custom",
        tier="premium",
        scores=ModelScoresConfig(
            aa_slug="anthropic/claude-3-5-sonnet",
            manual=ManualScoresConfig(coding=99.0),
        ),
    )
    eff2 = resolve_effective_scores(m2, synthetic_snapshot)
    assert eff2.source == "manual"
    assert eff2.coding == 99.0
    assert eff2.intelligence == 88.0

    # 3. Unlinked model with no overrides
    m3 = ModelConfig(
        id="local-unknown-model",
        display_name="Local Model",
        tier="cheap",
    )
    eff3 = resolve_effective_scores(m3, synthetic_snapshot)
    assert eff3.is_unscored
    assert eff3.source == "unscored"


def test_fuzzy_matcher():
    available = [
        "anthropic/claude-3-5-sonnet",
        "openai/gpt-4o",
        "openai/gpt-4o-mini",
        "meta-llama/llama-3.3-70b-instruct",
    ]
    suggs = suggest_model_slugs("gpt-4o-mini", available, limit=2)
    assert len(suggs) >= 1
    assert any(s.get("slug") == "openai/gpt-4o-mini" for s in suggs)


def test_heuristic_provider_consistency():
    prov = HeuristicDecisionProvider()
    req = DecisionRequest(
        state="[user]\n```python\ndef solve(): pass\n```",
        questions=build_rubric_questions(load_routing_config().rubric),
        model="clef-flash",
    )
    res = prov.decide(req)
    assert res.source == "heuristic"
    assert "task" in res.answers
    assert res.answers["task"].get("choice") == "coding"
    assert res.answers["difficulty"].get("score") is not None


def test_decision_service_fail_open(tmp_path: Path):
    storage = Storage(tmp_path / "test_breaker.db")
    config = load_routing_config()
    # Mock a service with invalid credentials to test fallback
    service = DecisionService(config=config, storage=storage)

    req = ChatRequest(
        messages=[Message(role="user", parts=[TextPart(text="Hello world")])]
    )
    res = service.evaluate(req, provider_override="clef-flash")
    # Rule 17: Never fail turn; fall back to heuristic
    assert res.source in ("heuristic_fallback", "heuristic", "mock")
    assert "task" in res.answers
    assert res.answers["task"].get("choice") in ("chat_general", "writing", "factual_lookup")


def test_smart_strategy_end_to_end(tmp_path: Path, synthetic_snapshot: ScoreSnapshot):
    from modelmesh.core.types import ProviderConfig

    storage = Storage(tmp_path / "test_smart_e2e.db")
    store = ScoreStore(storage)
    store.save_snapshot(synthetic_snapshot)

    reg = ModelRegistry()
    reg.add_provider(ProviderConfig(id="openai", protocol="openai_compat"))
    reg.add_provider(ProviderConfig(id="anthropic", protocol="anthropic"))


    m_micro = ModelConfig(
        id="gemma-2-2b",
        display_name="Gemma 2 2B",
        tier="cheap",
        scores=ModelScoresConfig(aa_slug="google/gemma-2-2b"),
    )
    m_micro.endpoints.append(
        EndpointConfig(id="ep-micro", provider="openai", api_model="gemma-2-2b", price_in_per_mtok=0.04, price_out_per_mtok=0.08, priority=1)
    )

    m_cheap = ModelConfig(
        id="gpt-4o-mini",
        display_name="GPT-4o Mini",
        tier="cheap",
        scores=ModelScoresConfig(aa_slug="openai/gpt-4o-mini"),
    )
    m_cheap.endpoints.append(
        EndpointConfig(id="ep-cheap", provider="openai", api_model="gpt-4o-mini", price_in_per_mtok=0.15, price_out_per_mtok=0.60, priority=1)
    )

    m_strong = ModelConfig(
        id="claude-3-5-sonnet",
        display_name="Claude 3.5 Sonnet",
        tier="premium",
        scores=ModelScoresConfig(aa_slug="anthropic/claude-3-5-sonnet"),
    )
    m_strong.endpoints.append(
        EndpointConfig(id="ep-strong", provider="anthropic", api_model="claude-3-5-sonnet", price_in_per_mtok=3.0, price_out_per_mtok=15.0, priority=1)
    )

    reg.add_model(m_micro)
    reg.add_model(m_cheap)
    reg.add_model(m_strong)


    router = Router(registry=reg, storage=storage)

    # 1. Trivial greeting prompt -> Should route to cheap tier model (gpt-4o-mini)
    req_easy = ChatRequest(
        messages=[Message(role="user", parts=[TextPart(text="Hi")])]
    )
    dec_easy = router.route(req_easy, strategy_name="smart_clef")
    assert dec_easy.chosen_candidate.model_id in ("gpt-4o-mini", "gemma-2-2b")
    assert dec_easy.request_features["task"] == "chat_general"

    # 2. Ultra-hard complex distributed systems coding prompt -> Should route to claude-3-5-sonnet
    req_hard = ChatRequest(
        messages=[Message(role="user", parts=[TextPart(text="```rust\n" + ("// Complex distributed raft consensus implementation\n" * 20) + "\n// Fix complex deadlock, split-brain scenario, and distributed consensus state machine correctness proof\n```")])]
    )
    dec_hard = router.route(req_hard, strategy_name="smart_clef")
    assert dec_hard.chosen_candidate.model_id == "claude-3-5-sonnet"
    assert dec_hard.request_features["task"] == "coding"



