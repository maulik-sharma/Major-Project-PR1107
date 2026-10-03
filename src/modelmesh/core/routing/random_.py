"""Random baseline routing strategy (uniform model sampling)."""

from __future__ import annotations

import random
from typing import Any, Dict, List, Optional

from modelmesh.core.errors import RoutingError
from modelmesh.core.routing.base import (
    Strategy,
    build_fallback_chain,
    order_endpoints_for_model,
    register_strategy,
)
from modelmesh.core.types import Candidate, ChatRequest, RoutingDecision


@register_strategy("random")
class RandomStrategy(Strategy):
    """Uniformly samples among eligible models, then applies endpoint policy."""

    def rank(
        self,
        eligible_candidates: List[Candidate],
        request: ChatRequest,
        features: Dict[str, Any],
        **kwargs: Any,
    ) -> RoutingDecision:
        if not eligible_candidates:
            raise RoutingError("No eligible candidates available for random routing.")

        seed: Optional[int] = kwargs.get("seed")
        rng = random.Random(seed)

        # Group by model_id to avoid bias towards models with many endpoints
        model_groups: Dict[str, List[Candidate]] = {}
        for c in eligible_candidates:
            model_groups.setdefault(c.model_id, []).append(c)

        model_ids = sorted(list(model_groups.keys()))  # deterministic baseline before shuffle
        rng.shuffle(model_ids)

        ordered_groups: List[List[Candidate]] = []
        for m_id in model_ids:
            cands = model_groups[m_id]
            policy = cands[0].model_config.endpoint_policy
            ordered_cands = order_endpoints_for_model(cands, policy, request)
            ordered_groups.append(ordered_cands)

        chosen, fallback = build_fallback_chain(ordered_groups)

        reason = (
            f"Randomly chosen model '{chosen.model_id}' on provider '{chosen.provider_id}' "
            f"(uniform draw from {len(model_ids)} eligible models, seed={seed})."
        )

        return RoutingDecision(
            chosen_candidate=chosen,
            fallback_chain=fallback,
            strategy_name="random",
            reason=reason,
            eligible_candidates=[{"endpoint_id": c.endpoint_id, "model_id": c.model_id} for c in eligible_candidates],
            request_features=features,
            seed=seed,
        )
