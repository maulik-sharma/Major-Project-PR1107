"""Selector edge cases (spec 4.4, 4.5, 4.7), stickiness (4.6), and end-to-end knob sensitivity."""

from __future__ import annotations

from typing import Dict, List, Optional

import pytest

from modelmesh.core.config.routing_config import SmartRoutingConfig
from modelmesh.core.routing.smart.selector import select_smart_candidate
from modelmesh.core.routing.smart.stickiness import apply_stickiness
from modelmesh.core.routing.smart.strategy import SmartClefStrategy
from modelmesh.core.scores.snapshots import EffectiveScores
from modelmesh.core.types import Candidate, ChatRequest, EndpointConfig, Message, ModelConfig, ProviderConfig


def cand(
    model_id: str,
    price_out: float,
    tier: str = "mid",
    endpoint: str = "prov",
    priority: int = 1,
    policy: str = "priority",
) -> Candidate:
    m = ModelConfig(id=model_id, display_name=model_id, tier=tier, endpoint_policy=policy)  # type: ignore[arg-type]
    ep = EndpointConfig(
        id=f"{model_id}@{endpoint}",
        provider=endpoint,
        api_model=f"api-{model_id}",
        price_in_per_mtok=0.0,
        price_out_per_mtok=price_out,
        priority=priority,
    )
    return Candidate.resolve(model=m, endpoint=ep, provider=ProviderConfig(id=endpoint, protocol="mock"))


def scores(intel: Optional[float] = None, coding: Optional[float] = None) -> EffectiveScores:
    unscored = intel is None and coding is None
    return EffectiveScores(intelligence=intel, coding=coding, is_unscored=unscored, source="unscored" if unscored else "manual")


def select(cands: List[Candidate], eff: Dict[str, EffectiveScores], bar: float, metric: str = "intelligence", **kw):  # type: ignore[no-untyped-def]
    return select_smart_candidate(candidates=cands, effective_scores=eff, metric=metric, need=bar + 0.1, bar=bar, **kw)


def test_unscored_model_is_excluded_by_default() -> None:
    cands = [cand("cheap_unscored", 0.0, tier="premium"), cand("weak", 1.0), cand("strong", 5.0)]
    eff = {"weak": scores(10), "strong": scores(60)}
    chosen, chain, meta = select(cands, eff, bar=0.9)
    assert chosen.model_id == "strong"
    assert "cheap_unscored" not in {c.model_id for c in chain}
    assert meta["unscored_models"] == ["cheap_unscored"]


def test_tier_default_uses_pool_quantiles_not_fixed_numbers() -> None:
    cands = [cand("unscored_premium", 0.0, tier="premium"), cand("weak", 1.0), cand("strong", 5.0)]
    eff = {"weak": scores(10), "strong": scores(60)}
    chosen, _, meta = select(cands, eff, bar=0.9, unscored_policy="tier_default")
    # 75th percentile of [10, 60] = 47.5 -> q = 0.75, below a 0.9 bar: it must not beat the real top model.
    assert chosen.model_id == "strong"
    assert meta["q_scores"]["unscored_premium"] == pytest.approx(0.75)
    assert meta["estimated_score_models"] == ["unscored_premium"]


def test_no_scored_models_falls_back_to_cheapest_with_notice() -> None:
    cands = [cand("a", 3.0), cand("b", 0.5), cand("c", 9.0)]
    chosen, chain, meta = select(cands, {}, bar=0.8)
    assert chosen.model_id == "b"
    assert meta["scores_available"] is False
    assert any("cheapest" in n for n in meta["notices"])


def test_mixed_coding_coverage_ranks_whole_pool_on_intelligence() -> None:
    cands = [cand("benchmarked", 5.0), cand("unbenchmarked", 1.0)]
    eff = {"benchmarked": scores(intel=40, coding=85), "unbenchmarked": scores(intel=50)}
    chosen, _, meta = select(cands, eff, bar=0.9, metric="coding")
    assert meta["metric_used"] == "intelligence"
    assert chosen.model_id == "unbenchmarked"  # higher intelligence, not 85-vs-50 apples to oranges


def test_full_coding_coverage_uses_coding_metric() -> None:
    cands = [cand("a", 5.0), cand("b", 1.0)]
    eff = {"a": scores(intel=40, coding=85), "b": scores(intel=50, coding=30)}
    chosen, _, meta = select(cands, eff, bar=0.9, metric="coding")
    assert meta["metric_used"] == "coding"
    assert chosen.model_id == "a"


def test_free_model_ties_break_by_quality_not_priority() -> None:
    cands = [cand("weak_free", 0.0, priority=1), cand("strong_free", 0.0, priority=2), cand("paid", 9.0)]
    eff = {"weak_free": scores(10), "strong_free": scores(50), "paid": scores(60)}
    chosen, _, _ = select(cands, eff, bar=0.0)
    assert chosen.model_id == "strong_free"


def test_sibling_endpoints_follow_endpoint_policy() -> None:
    a1 = cand("m", 5.0, endpoint="p1", policy="cheapest")
    a2 = cand("m", 1.0, endpoint="p2", policy="cheapest")
    a3 = cand("m", 3.0, endpoint="p3", policy="cheapest")
    chosen, chain, _ = select([a1, a2, a3], {"m": scores(50)}, bar=0.0)
    assert [chosen.endpoint_id] + [c.endpoint_id for c in chain] == ["m@p2", "m@p3", "m@p1"]


def test_stickiness_keeps_current_model_while_it_clears_the_bar() -> None:
    cheap, mid = cand("cheap", 1.0), cand("mid", 2.0)
    q = {"cheap": 0.6, "mid": 0.8}
    costs = {"cheap@prov": 1.0, "mid@prov": 2.0}
    chosen, chain, outcome = apply_stickiness(cheap, [mid], "mid", q, 0.5, 0.1, 0.6, 4.0, costs)
    assert (chosen.model_id, outcome) == ("mid", "kept")
    assert chain[0].model_id == "cheap"


def test_stickiness_upgrades_when_current_model_falls_below_bar() -> None:
    strong, weak = cand("strong", 5.0), cand("weak", 1.0)
    chosen, _, outcome = apply_stickiness(strong, [weak], "weak", {"strong": 1.0, "weak": 0.2}, 0.7, 0.0, 0.6, 4.0, {})
    assert (chosen.model_id, outcome) == ("strong", "upgraded")


def test_stickiness_switches_on_task_change_when_much_cheaper() -> None:
    cheap, pricey = cand("cheap", 1.0), cand("pricey", 10.0)
    costs = {"cheap@prov": 1.0, "pricey@prov": 10.0}
    chosen, _, outcome = apply_stickiness(cheap, [pricey], "pricey", {"cheap": 0.5, "pricey": 1.0}, 0.3, 0.9, 0.6, 4.0, costs)
    assert (chosen.model_id, outcome) == ("cheap", "switched_on_task_change")


def test_first_message_has_no_stickiness() -> None:
    c = cand("a", 1.0)
    assert apply_stickiness(c, [], None, {"a": 1.0}, 0.0, 0.0, 0.6, 4.0, {})[2] is None


def _route(bias: float = 0.0, slack: float = 0.1, difficulty: float = 2.0) -> str:
    """Route one request through the Smart strategy with fixed answers and synthetic scores."""
    cfg = SmartRoutingConfig()
    cfg.need.bias = bias
    cfg.need.slack = slack
    cands = [cand("small", 0.2), cand("medium", 2.0), cand("large", 15.0)]
    for c, s in zip(cands, (10.0, 35.0, 60.0)):
        c.model_config.scores.manual.intelligence = s
    answers = {
        "task": {"type": "choice", "choice": "chat_general", "confidence": 0.9},
        "difficulty": {"type": "score", "score": difficulty, "confidence": 0.9},
        "precision": {"type": "score", "score": difficulty * 0.75, "confidence": 0.9},
        "larger_model_benefit": {"type": "score", "score": difficulty * 0.75, "confidence": 0.9},
    }
    decision = SmartClefStrategy(config=cfg).rank(
        eligible_candidates=cands,
        request=ChatRequest(messages=[Message.from_text("user", "x")]),
        features={"smart_decision": {"answers": answers, "source": "mock"}},
    )
    return decision.chosen_candidate.model_id


def test_difficulty_bias_and_slack_change_the_chosen_model() -> None:
    # q: small=0, medium=0.5, large=1 (min-max over the pool)
    assert _route(difficulty=0.0) == "small"
    assert _route(difficulty=2.0) == "medium"  # need ~0.52, bar ~0.42
    assert _route(difficulty=4.0) == "large"
    assert _route(difficulty=1.0) == "medium"  # need ~0.26, bar ~0.16
    assert _route(difficulty=1.0, bias=-0.2) == "small"  # bar drops to 0
    assert _route(difficulty=2.0, bias=0.2) == "large"  # bar ~0.62 > medium's 0.5
    assert _route(difficulty=1.0, slack=0.3) == "small"  # wider slack admits the cheapest


def arena(intel: Optional[float], **ratings: float) -> EffectiveScores:
    return EffectiveScores(intelligence=intel, arena=dict(ratings), is_unscored=False, source="snapshot")


CODING_PREFS = ["arena_coding", "coding", "intelligence"]


def test_preferred_metric_used_when_it_covers_enough_of_the_pool() -> None:
    cands = [cand("a", 5.0), cand("b", 3.0), cand("c", 1.0), cand("tiny", 0.0)]
    eff = {
        "a": arena(50, coding=1500), "b": arena(40, coding=1450),
        "c": arena(30, coding=1400), "tiny": arena(60),  # high AA score but no arena rating
    }
    chosen, chain, meta = select(cands, eff, bar=0.9, metric=CODING_PREFS)
    assert meta["metric_used"] == "arena_coding"
    assert meta["lacking_metric_models"] == ["tiny"]
    assert chosen.model_id == "a"
    assert "tiny" not in {c.model_id for c in chain}


def test_falls_through_to_next_metric_when_coverage_is_low() -> None:
    cands = [cand("a", 5.0), cand("b", 3.0), cand("c", 1.0)]
    eff = {"a": arena(50, coding=1500), "b": arena(40), "c": arena(30)}
    _, _, meta = select(cands, eff, bar=0.0, metric=CODING_PREFS)
    assert meta["metric_used"] == "intelligence"
    assert meta["lacking_metric_models"] == []


def test_widest_metric_wins_when_none_reaches_threshold() -> None:
    cands = [cand(x, 1.0) for x in "abcd"]
    eff = {"a": arena(None, coding=1), "b": arena(None, coding=2), "c": arena(9), "d": arena(None, overall=5)}
    _, _, meta = select(cands, eff, bar=0.0, metric=["arena_coding", "intelligence", "arena_overall"], min_coverage=0.9)
    assert meta["metric_used"] == "arena_coding"
    assert meta["lacking_metric_models"] == ["c", "d"]


def test_strategy_reads_metric_preferences_from_config() -> None:
    cfg = SmartRoutingConfig()
    cfg.metric_by_task = {"chat_general": ["arena_overall", "intelligence"], "default": ["intelligence"]}
    cands = [cand("cheap", 0.0), cand("pricey", 9.0)]
    for c, (intel, elo) in zip(cands, [(80, 1300), (20, 1500)]):
        c.model_config.scores.manual.intelligence = intel
        c.model_config.scores.manual.arena_text_elo = elo
    request = ChatRequest(messages=[Message.from_text("user", "hi")])
    features = {"smart_decision": {"answers": {
        "task": {"choice": "chat_general"}, "difficulty": {"score": 4},
        "precision": {"score": 3}, "larger_model_benefit": {"score": 3},
    }, "source": "heuristic"}}
    decision = SmartClefStrategy(config=cfg).rank(cands, request, features)
    assert decision.request_features["metric_used"] == "arena_overall"
    assert decision.chosen_candidate.model_id == "pricey"


def test_unranked_candidates_say_why() -> None:
    cfg = SmartRoutingConfig()
    ranked, manual, unscored = cand("ranked", 1.0), cand("manual", 0.0), cand("unscored", 0.5)
    ranked.model_config.scores.manual.intelligence = 40
    manual.model_config.scores.manual.intelligence = 60
    manual.model_config.routing.routable = False
    request = ChatRequest(messages=[Message.from_text("user", "hi")])
    features = {"smart_decision": {"answers": {"task": {"choice": "chat_general"}}, "source": "heuristic"}}
    decision = SmartClefStrategy(config=cfg).rank([ranked, manual, unscored], request, features)
    notes = {c["model_id"]: c["note"] for c in decision.eligible_candidates}
    assert notes == {"ranked": None, "manual": "Manual only (no price)", "unscored": "No score"}
