"""Pure selection logic for Smart routing (admitted set, cheapest pick, fallback chain)."""

from __future__ import annotations

import fnmatch
from typing import Any, Dict, List, Optional, Tuple

from modelmesh.core.errors import RoutingError
from modelmesh.core.routing.smart.scoring import normalize_scores_to_quality
from modelmesh.core.scores.snapshots import EffectiveScores
from modelmesh.core.types import Candidate, Tier


def _matches_any_pattern(val: str, patterns: List[str]) -> bool:
    return any(fnmatch.fnmatch(val, pat) for pat in patterns)


def _estimate_cost(cand: Candidate, tokens_in: int, tokens_out: int) -> float:
    return (
        (cand.price_in_per_mtok * tokens_in)
        + (cand.price_out_per_mtok * tokens_out)
    ) / 1_000_000.0


def select_smart_candidate(
    candidates: List[Candidate],
    effective_scores: Dict[str, EffectiveScores],
    metric: str,
    need: float,
    bar: float,
    task: str = "chat_general",
    needs_reasoning: float = 0.0,
    pool_include: Optional[List[str]] = None,
    pool_exclude: Optional[List[str]] = None,
    unscored_policy: str = "exclude",
    tokens_in_est: int = 500,
    tokens_out_est: int = 1000,
) -> Tuple[Candidate, List[Candidate], Dict[str, Any]]:
    """Select the cheapest eligible candidate clearing the quality bar.

    Returns:
        Tuple of (chosen_candidate, fallback_chain, selection_metadata).
    """
    if not candidates:
        raise RoutingError("No candidates available for smart routing selection.")

    inc_patterns = pool_include or ["*"]
    exc_patterns = pool_exclude or []

    # 1. Filter by routable flag, admitted tasks, and pool include/exclude
    pool_eligible: List[Candidate] = []
    has_any_include_match = False

    for c in candidates:
        mcfg = c.model_config
        # Check routable
        if not mcfg.routing.routable:
            continue
        # Check admitted tasks
        admitted = mcfg.routing.admitted_tasks
        if "all" not in admitted and task not in admitted:
            continue
        # Check exclusion
        if _matches_any_pattern(c.model_id, exc_patterns) or _matches_any_pattern(c.endpoint_id, exc_patterns):
            continue
        # Check inclusion
        matches_inc = _matches_any_pattern(c.model_id, inc_patterns) or _matches_any_pattern(c.endpoint_id, inc_patterns)
        if matches_inc:
            has_any_include_match = True
            pool_eligible.append(c)

    # If include list matched nothing, ignore include list (Part 4.7)
    if not has_any_include_match:
        for c in candidates:
            mcfg = c.model_config
            if not mcfg.routing.routable:
                continue
            admitted = mcfg.routing.admitted_tasks
            if "all" not in admitted and task not in admitted:
                continue
            if _matches_any_pattern(c.model_id, exc_patterns) or _matches_any_pattern(c.endpoint_id, exc_patterns):
                continue
            pool_eligible.append(c)

    if not pool_eligible:
        raise RoutingError(
            f"Candidate pool is empty after applying pool filters (include: {inc_patterns}, exclude: {exc_patterns})."
        )

    # 2. Score resolution and unscored handling
    scored_candidates: List[Candidate] = []
    raw_scores: Dict[str, float] = {}

    tier_default_scores = {"cheap": 20.0, "mid": 50.0, "premium": 80.0}

    for c in pool_eligible:
        eff = effective_scores.get(c.model_id)
        val: Optional[float] = None
        if eff and not eff.is_unscored:
            if metric == "coding" and eff.coding is not None:
                val = eff.coding
            elif metric == "agentic" and eff.agentic is not None:
                val = eff.agentic
            elif eff.intelligence is not None:
                val = eff.intelligence

        if val is None:
            if unscored_policy == "tier_default":
                val = tier_default_scores.get(c.tier, 40.0)
                raw_scores[c.model_id] = val
                scored_candidates.append(c)
            # else exclude unscored
        else:
            raw_scores[c.model_id] = val
            scored_candidates.append(c)

    # Fallback if no models scored: use tier-based default scores so that the
    # quality bar can still differentiate cheap vs mid vs premium models.
    if not scored_candidates:
        scored_candidates = list(pool_eligible)
        raw_scores = {
            c.model_id: tier_default_scores.get(c.tier, 40.0)
            for c in pool_eligible
        }

    # 3. Min-max normalize quality q in [0.0, 1.0]
    q_map = normalize_scores_to_quality(raw_scores)

    # 4. Filter by reasoning preference
    admitted_candidates = [c for c in scored_candidates if q_map.get(c.model_id, 0.0) >= bar]
    below_bar_candidates = [c for c in scored_candidates if q_map.get(c.model_id, 0.0) < bar]

    # If reasoning is requested and any admitted candidate supports reasoning
    if needs_reasoning >= 0.5:
        reasoning_admitted = [
            c for c in admitted_candidates if "reasoning" in c.effective_capabilities
        ]
        if reasoning_admitted:
            admitted_candidates = reasoning_admitted

    # If no candidate cleared the bar, admit the highest quality candidates
    below_bar = False
    if not admitted_candidates:
        below_bar = True
        max_q = max(q_map.values()) if q_map else 1.0
        admitted_candidates = [c for c in scored_candidates if q_map.get(c.model_id, 0.0) >= max_q - 0.01]
        below_bar_candidates = [c for c in scored_candidates if c not in admitted_candidates]

    # 5. Pick cheapest in admitted set
    def rank_key(cand: Candidate) -> tuple[float, int, float, str]:
        cost = _estimate_cost(cand, tokens_in_est, tokens_out_est)
        q = q_map.get(cand.model_id, 0.0)
        return (cost, cand.priority, -q, cand.endpoint_id)

    admitted_candidates.sort(key=rank_key)
    below_bar_candidates.sort(key=lambda c: (-q_map.get(c.model_id, 0.0), _estimate_cost(c, tokens_in_est, tokens_out_est)))

    chosen = admitted_candidates[0]

    # 6. Fallback chain:
    # 1. Other endpoints of chosen model
    # 2. Other admitted candidates
    # 3. Below-bar candidates (strongest first)
    same_model_fallbacks = [
        c for c in candidates if c.model_id == chosen.model_id and c.endpoint_id != chosen.endpoint_id and c in pool_eligible
    ]
    other_admitted_fallbacks = [c for c in admitted_candidates if c.model_id != chosen.model_id]
    other_below_bar_fallbacks = [c for c in below_bar_candidates if c.model_id != chosen.model_id]

    fallback_chain = same_model_fallbacks + other_admitted_fallbacks + other_below_bar_fallbacks

    metadata: Dict[str, Any] = {
        "chosen_q": q_map.get(chosen.model_id, 1.0),
        "chosen_score": raw_scores.get(chosen.model_id, 0.0),
        "need": need,
        "bar": bar,
        "metric_used": metric,
        "below_bar": below_bar,
        "estimated_cost_usd": _estimate_cost(chosen, tokens_in_est, tokens_out_est),
        "q_scores": q_map,
        "admitted_count": len(admitted_candidates),
        "pool_count": len(pool_eligible),
    }

    return chosen, fallback_chain, metadata
