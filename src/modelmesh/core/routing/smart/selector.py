"""Pure selection logic for Smart routing (admitted set, cheapest pick, fallback chain).

No I/O (Rule 18): plain data in, plain data out.
"""

from __future__ import annotations

import fnmatch
from typing import Any, Dict, List, Optional, Tuple

from modelmesh.core.errors import RoutingError
from modelmesh.core.routing.base import sort_endpoints
from modelmesh.core.routing.smart.scoring import normalize_scores_to_quality
from modelmesh.core.scores.snapshots import EffectiveScores
from modelmesh.core.types import Candidate

# Where an unscored model of each tier lands in the scored pool under `tier_default`.
_TIER_QUANTILES = {"cheap": 0.25, "mid": 0.5, "premium": 0.75}


def _matches_any_pattern(val: str, patterns: List[str]) -> bool:
    return any(fnmatch.fnmatch(val, pat) for pat in patterns)


def _estimate_cost(cand: Candidate, tokens_in: int, tokens_out: int) -> float:
    return (
        (cand.price_in_per_mtok * tokens_in)
        + (cand.price_out_per_mtok * tokens_out)
    ) / 1_000_000.0


def _metric_value(eff: Optional[EffectiveScores], metric: str) -> Optional[float]:
    if eff is None:
        return None
    return {"coding": eff.coding, "agentic": eff.agentic}.get(metric, eff.intelligence)


def _quantile(values: List[float], q: float) -> float:
    """Linear-interpolated quantile of a non-empty list."""
    ordered = sorted(values)
    pos = q * (len(ordered) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def filter_pool(
    candidates: List[Candidate],
    task: str,
    pool_include: List[str],
    pool_exclude: List[str],
) -> Tuple[List[Candidate], bool]:
    """Apply routable, admitted_tasks, and include/exclude rules.

    Returns (pool, include_ignored). An include list that matches nothing is ignored.
    """
    base: List[Candidate] = []
    for c in candidates:
        routing = c.model_config.routing
        if not routing.routable:
            continue
        if "all" not in routing.admitted_tasks and task not in routing.admitted_tasks:
            continue
        if _matches_any_pattern(c.model_id, pool_exclude) or _matches_any_pattern(c.endpoint_id, pool_exclude):
            continue
        base.append(c)

    included = [
        c for c in base
        if _matches_any_pattern(c.model_id, pool_include) or _matches_any_pattern(c.endpoint_id, pool_include)
    ]
    if included:
        return included, False
    return base, bool(base)


def resolve_pool_scores(
    pool: List[Candidate],
    effective_scores: Dict[str, EffectiveScores],
    metric: str,
    unscored_policy: str,
) -> Tuple[Dict[str, float], str, List[str]]:
    """Score each model in the pool on one scale.

    The task metric (coding/agentic) is used only if every scored model has it;
    otherwise the whole pool is scored on intelligence, so real and missing
    sub-indices are never mixed.

    Returns (raw_scores by model_id, metric_used, estimated model_ids).
    """
    model_ids = list(dict.fromkeys(c.model_id for c in pool))
    scored_any = [m for m in model_ids if (effective_scores.get(m) and not effective_scores[m].is_unscored)]

    metric_used = metric
    if metric != "intelligence":
        if not scored_any or any(_metric_value(effective_scores.get(m), metric) is None for m in scored_any):
            metric_used = "intelligence"

    raw: Dict[str, float] = {}
    for m in model_ids:
        val = _metric_value(effective_scores.get(m), metric_used)
        if val is not None:
            raw[m] = val

    estimated: List[str] = []
    if unscored_policy == "tier_default" and raw:
        values = list(raw.values())
        tiers = {c.model_id: c.tier for c in pool}
        for m in model_ids:
            if m not in raw:
                raw[m] = _quantile(values, _TIER_QUANTILES.get(tiers.get(m, "mid"), 0.5))
                estimated.append(m)
    return raw, metric_used, estimated


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
    pool, include_ignored = filter_pool(candidates, task, inc_patterns, exc_patterns)
    if not pool:
        raise RoutingError(
            f"Smart routing pool is empty after routable/admitted_tasks filters and "
            f"pool.exclude {exc_patterns} in routing.yaml."
        )

    def cost(c: Candidate) -> float:
        return _estimate_cost(c, tokens_in_est, tokens_out_est)

    notices: List[str] = []
    if include_ignored:
        notices.append(f"pool.include {inc_patterns} matched no eligible model and was ignored.")

    raw_scores, metric_used, estimated = resolve_pool_scores(pool, effective_scores, metric, unscored_policy)
    if metric_used != metric:
        notices.append(f"Not every candidate has a '{metric}' score; ranked on intelligence instead.")

    scored = [c for c in pool if c.model_id in raw_scores]
    unscored_ids = sorted({c.model_id for c in pool} - set(raw_scores))

    if not scored:
        # Spec 4.7: no scored model -> cheapest-first with a visible notice.
        notices.append("No candidate has a quality score; picked the cheapest model instead.")
        ordered = sorted(pool, key=lambda c: (cost(c), c.priority, c.endpoint_id))
        chosen = ordered[0]
        return chosen, ordered[1:], {
            "chosen_q": None,
            "chosen_score": None,
            "need": need,
            "bar": bar,
            "metric_used": None,
            "below_bar": False,
            "estimated_cost_usd": cost(chosen),
            "q_scores": {},
            "admitted_count": 0,
            "pool_count": len(pool),
            "scores_available": False,
            "unscored_models": unscored_ids,
            "estimated_score_models": [],
            "notices": notices,
        }

    q_map = normalize_scores_to_quality(raw_scores)

    admitted = [c for c in scored if q_map[c.model_id] >= bar]
    below = [c for c in scored if q_map[c.model_id] < bar]

    # Soft reasoning preference (spec 4.2)
    if needs_reasoning >= 0.5:
        reasoning = [c for c in admitted if "reasoning" in c.effective_capabilities]
        if reasoning:
            below = below + [c for c in admitted if c not in reasoning]
            admitted = reasoning

    # The top model always has q = 1, so this only triggers with a negative slack.
    below_bar = not admitted
    if below_bar:
        top_q = max(q_map.values())
        admitted = [c for c in scored if q_map[c.model_id] >= top_q]
        below = [c for c in scored if c not in admitted]

    # Cheapest first; ties (e.g. several $0 models) break by higher q (spec 4.4).
    admitted.sort(key=lambda c: (cost(c), -q_map[c.model_id], c.priority, c.endpoint_id))
    below.sort(key=lambda c: (-q_map[c.model_id], cost(c), c.endpoint_id))

    chosen = admitted[0]
    siblings = sort_endpoints(
        [c for c in pool if c.model_id == chosen.model_id and c.endpoint_id != chosen.endpoint_id],
        chosen.model_config.endpoint_policy,
        cost,
    )
    fallback_chain = (
        siblings
        + [c for c in admitted if c.model_id != chosen.model_id]
        + [c for c in below if c.model_id != chosen.model_id]
    )

    if estimated:
        notices.append(f"Estimated scores from tier for unscored models: {', '.join(sorted(estimated))}.")

    metadata: Dict[str, Any] = {
        "chosen_q": q_map[chosen.model_id],
        "chosen_score": raw_scores[chosen.model_id],
        "need": need,
        "bar": bar,
        "metric_used": metric_used,
        "below_bar": below_bar,
        "estimated_cost_usd": cost(chosen),
        "q_scores": q_map,
        "admitted_count": len(admitted),
        "admitted_model_ids": sorted({c.model_id for c in admitted}),
        "pool_count": len(pool),
        "scores_available": True,
        "unscored_models": unscored_ids,
        "estimated_score_models": sorted(estimated),
        "notices": notices,
    }
    return chosen, fallback_chain, metadata
