"""Expensive-first baseline routing strategy."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from modelmesh.core.cost import estimate_request_cost
from modelmesh.core.errors import RoutingError
from modelmesh.core.routing.base import (
    Strategy,
    build_fallback_chain,
    order_endpoints_for_model,
    register_strategy,
)
from modelmesh.core.types import Candidate, ChatRequest, RoutingDecision


@register_strategy("expensive_first")
class ExpensiveFirstStrategy(Strategy):
    """Ranks models descending by the cost of their baseline endpoint."""

    def rank(
        self,
        eligible_candidates: List[Candidate],
        request: ChatRequest,
        features: Dict[str, Any],
        **kwargs: Any,
    ) -> RoutingDecision:
        if not eligible_candidates:
            raise RoutingError("No eligible candidates available for expensive-first routing.")

        expected_output = kwargs.get("expected_output_tokens", 500)

        # Group candidates by model_id
        model_groups: Dict[str, List[Candidate]] = {}
        for c in eligible_candidates:
            model_groups.setdefault(c.model_id, []).append(c)

        model_costs: List[Tuple[float, str, List[Candidate]]] = []
        scores_summary: List[Dict[str, Any]] = []

        for m_id, cands in model_groups.items():
            # For model ranking, find its cheapest endpoint so rank does not depend on an outlier provider
            cheapest_ordered = order_endpoints_for_model(cands, "cheapest", request)
            cheapest_cand = cheapest_ordered[0]
            baseline_cost = estimate_request_cost(
                request,
                cheapest_cand.price_in_per_mtok,
                cheapest_cand.price_out_per_mtok,
                expected_output_tokens=expected_output,
            )

            # Endpoints within model ordered by model's endpoint_policy
            policy = cands[0].model_config.endpoint_policy
            policy_ordered = order_endpoints_for_model(cands, policy, request)

            model_costs.append((baseline_cost, m_id, policy_ordered))
            scores_summary.append({
                "model_id": m_id,
                "baseline_cost_usd": baseline_cost,
                "endpoints_count": len(cands),
            })

        # Rank models descending by baseline cost, ties broken by model_id
        model_costs.sort(key=lambda item: (-item[0], item[1]))

        ordered_groups = [item[2] for item in model_costs]
        chosen, fallback = build_fallback_chain(ordered_groups)

        chosen_cost = model_costs[0][0]
        reason = (
            f"Expensive-first picked premium model '{chosen.model_id}' via {chosen.provider_id} "
            f"(baseline model cost ${chosen_cost:.6f})."
        )

        return RoutingDecision(
            chosen_candidate=chosen,
            fallback_chain=fallback,
            strategy_name="expensive_first",
            reason=reason,
            eligible_candidates=scores_summary,
            request_features=features,
        )
