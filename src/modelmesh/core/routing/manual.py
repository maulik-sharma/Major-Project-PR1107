"""Manual routing strategy respecting user model and endpoint selections."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from modelmesh.core.errors import RoutingError
from modelmesh.core.routing.base import (
    Strategy,
    order_endpoints_for_model,
    register_strategy,
)
from modelmesh.core.types import Candidate, ChatRequest, RoutingDecision


@register_strategy("manual")
class ManualStrategy(Strategy):
    """User manually selects a model or pins a specific endpoint with no cross-model failover."""

    def rank(
        self,
        eligible_candidates: List[Candidate],
        request: ChatRequest,
        features: Dict[str, Any],
        **kwargs: Any,
    ) -> RoutingDecision:
        if not eligible_candidates:
            raise RoutingError("No eligible candidates available for manual routing.")

        pinned_endpoint_id: Optional[str] = kwargs.get("pinned_endpoint_id")
        pinned_model_id: Optional[str] = kwargs.get("pinned_model_id")

        # Group candidates by model_id
        model_groups: Dict[str, List[Candidate]] = {}
        for c in eligible_candidates:
            model_groups.setdefault(c.model_id, []).append(c)

        chosen: Candidate
        fallback: List[Candidate] = []
        reason: str = ""

        if pinned_endpoint_id:
            # Pinned specific endpoint: strict selection with NO failover
            target_cand = next(
                (c for c in eligible_candidates if c.endpoint_id == pinned_endpoint_id),
                None,
            )
            if not target_cand:
                raise RoutingError(
                    f"Pinned endpoint '{pinned_endpoint_id}' is not eligible for this request."
                )

            chosen = target_cand
            # In manual pinned endpoint mode, failover to other endpoints/models is disabled
            fallback = []
            reason = f"Manually pinned endpoint '{target_cand.endpoint_id}' on {target_cand.provider_id} (failover disabled)."

        elif pinned_model_id:
            # Pinned logical model: allow failover across providers serving the SAME model only
            if pinned_model_id not in model_groups:
                raise RoutingError(
                    f"Selected model '{pinned_model_id}' is not eligible for this request."
                )

            target_cands = model_groups[pinned_model_id]
            policy = target_cands[0].model_config.endpoint_policy
            ordered_cands = order_endpoints_for_model(target_cands, policy, request)

            chosen = ordered_cands[0]
            # Sibling endpoints of the SAME model are allowed in fallback chain, but NO other models
            fallback = ordered_cands[1:]
            reason = (
                f"Manually selected model '{pinned_model_id}' on provider '{chosen.provider_id}' "
                f"({len(fallback)} sibling provider endpoints available for same-model failover)."
            )

        else:
            # Default to first model; sibling endpoints only
            first_model_id = list(model_groups.keys())[0]
            first_cands = model_groups[first_model_id]
            policy = first_cands[0].model_config.endpoint_policy
            ordered_cands = order_endpoints_for_model(first_cands, policy, request)

            chosen = ordered_cands[0]
            fallback = ordered_cands[1:]
            reason = f"Manual selection of model '{first_model_id}' on {chosen.provider_id}."

        return RoutingDecision(
            chosen_candidate=chosen,
            fallback_chain=fallback,
            strategy_name="manual",
            reason=reason,
            eligible_candidates=[{"endpoint_id": c.endpoint_id, "model_id": c.model_id} for c in eligible_candidates],
            request_features=features,
        )
