"""Manual routing strategy respecting user model and endpoint selections."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from modelmesh.core.errors import RoutingError
from modelmesh.core.routing.base import (
    Strategy,
    build_fallback_chain,
    order_endpoints_for_model,
    register_strategy,
)
from modelmesh.core.types import Candidate, ChatRequest, RoutingDecision


@register_strategy("manual")
class ManualStrategy(Strategy):
    """User manually selects a model and optionally pins an endpoint."""

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

        ordered_groups: List[List[Candidate]] = []
        reason = ""

        if pinned_endpoint_id:
            # Pinned specific endpoint
            target_cand = next(
                (c for c in eligible_candidates if c.endpoint_id == pinned_endpoint_id),
                None,
            )
            if not target_cand:
                raise RoutingError(
                    f"Pinned endpoint '{pinned_endpoint_id}' is not eligible for this request."
                )

            # Sibling endpoints of same model
            model_cands = model_groups[target_cand.model_id]
            policy = target_cand.model_config.endpoint_policy
            ordered_siblings = order_endpoints_for_model(
                [c for c in model_cands if c.endpoint_id != pinned_endpoint_id],
                policy,
                request,
            )
            ordered_groups.append([target_cand] + ordered_siblings)

            # Append other models
            for m_id, cands in model_groups.items():
                if m_id != target_cand.model_id:
                    ordered_groups.append(
                        order_endpoints_for_model(cands, cands[0].model_config.endpoint_policy, request)
                    )

            reason = f"Manually pinned endpoint '{target_cand.endpoint_id}' on {target_cand.provider_id}."

        elif pinned_model_id:
            if pinned_model_id not in model_groups:
                raise RoutingError(
                    f"Selected model '{pinned_model_id}' is not eligible for this request."
                )

            target_cands = model_groups[pinned_model_id]
            policy = target_cands[0].model_config.endpoint_policy
            ordered_groups.append(order_endpoints_for_model(target_cands, policy, request))

            # Other models follow
            for m_id, cands in model_groups.items():
                if m_id != pinned_model_id:
                    ordered_groups.append(
                        order_endpoints_for_model(cands, cands[0].model_config.endpoint_policy, request)
                    )

            reason = f"Manually selected model '{pinned_model_id}' (ordered by '{policy}' endpoint policy)."

        else:
            # Default to first model
            first_model_id = list(model_groups.keys())[0]
            for m_id, cands in model_groups.items():
                policy = cands[0].model_config.endpoint_policy
                ordered_groups.append(order_endpoints_for_model(cands, policy, request))

            reason = f"Default selection of first available model '{first_model_id}'."

        chosen, fallback = build_fallback_chain(ordered_groups)

        return RoutingDecision(
            chosen_candidate=chosen,
            fallback_chain=fallback,
            strategy_name="manual",
            reason=reason,
            eligible_candidates=[{"endpoint_id": c.endpoint_id, "model_id": c.model_id} for c in eligible_candidates],
            request_features=features,
        )
