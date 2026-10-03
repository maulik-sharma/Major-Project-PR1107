"""Cheapest-first baseline routing strategy."""

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


@register_strategy("cheapest_first")
class CheapestFirstStrategy(Strategy):
    """Ranks models ascending by the estimated request cost of their cheapest endpoint."""

    def rank(
        self,
        eligible_candidates: List[Candidate],
        request: ChatRequest,
        features: Dict[str, Any],
        **kwargs: Any,
    ) -> RoutingDecision:
        if not eligible_candidates:
            raise RoutingError("No eligible candidates available for cheapest-first routing.")

        expected_output = kwargs.get("expected_output_tokens", 500)

        # Group candidates by model_id
        model_groups: Dict[str, List[Candidate]] = {}
        for c in eligible_candidates:
            model_groups.setdefault(c.model_id, []).append(c)

        # Calculate lowest endpoint cost for each model
        model_cheapest_costs: List[Tuple[float, str, List[Candidate]]] = []
        scores_summary: List[Dict[str, Any]] = []

        for m_id, cands in model_groups.items():
            # Endpoints within model ordered cheapest first
            ordered_cands = order_endpoints_for_model(cands, "cheapest", request)
            best_cand = ordered_cands[0]
            best_cost = estimate_request_cost(
                request,
                best_cand.price_in_per_mtok,
                best_cand.price_out_per_mtok,
                expected_output_tokens=expected_output,
            )
            model_cheapest_costs.append((best_cost, m_id, ordered_cands))
            scores_summary.append({
                "model_id": m_id,
                "cheapest_endpoint": best_cand.endpoint_id,
                "provider": best_cand.provider_id,
                "est_cost_usd": best_cost,
            })

        # Rank models ascending by cost, ties broken by model_id
        model_cheapest_costs.sort(key=lambda item: (item[0], item[1]))

        ordered_groups = [item[2] for item in model_cheapest_costs]
        chosen, fallback = build_fallback_chain(ordered_groups)

        chosen_cost = model_cheapest_costs[0][0]
        reason = (
            f"Cheapest-first picked model '{chosen.model_id}' via {chosen.provider_id} "
            f"(est. request cost ${chosen_cost:.6f})."
        )

        return RoutingDecision(
            chosen_candidate=chosen,
            fallback_chain=fallback,
            strategy_name="cheapest_first",
            reason=reason,
            eligible_candidates=scores_summary,
            request_features=features,
        )
