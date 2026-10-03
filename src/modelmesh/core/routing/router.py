"""Main Router component orchestrating candidate filtering and strategy selection."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from modelmesh.core.errors import RoutingError
from modelmesh.core.registry import ModelRegistry
from modelmesh.core.routing.base import get_strategy
from modelmesh.core.routing.features import (
    extract_request_features,
    filter_eligible_candidates,
)
from modelmesh.core.routing.health import EndpointHealthTracker
from modelmesh.core.types import Candidate, ChatRequest, RoutingDecision


class Router:
    """Evaluates requests against registered candidates using configured strategies."""

    def __init__(
        self,
        registry: ModelRegistry,
        health_tracker: Optional[EndpointHealthTracker] = None,
    ) -> None:
        self.registry = registry
        self.health_tracker = health_tracker or EndpointHealthTracker()

    def route(
        self,
        request: ChatRequest,
        strategy_name: str = "cheapest_first",
        pinned_model_id: Optional[str] = None,
        pinned_endpoint_id: Optional[str] = None,
        seed: Optional[int] = None,
        **kwargs: Any,
    ) -> RoutingDecision:
        """Filter candidates, execute the requested strategy, and return a decision.

        Args:
            request: The incoming ChatRequest.
            strategy_name: Name of the strategy ('manual', 'random', 'cheapest_first', 'expensive_first').
            pinned_model_id: Optional model ID to force (manual mode).
            pinned_endpoint_id: Optional endpoint ID to force (manual mode).
            seed: Optional seed for reproducible random selection.
            **kwargs: Extra parameters passed to strategies.

        Returns:
            RoutingDecision object with chosen candidate and fallback chain.

        Raises:
            RoutingError: If no candidate satisfies the request requirements.
        """
        all_candidates = self.registry.candidates(enabled_only=True)
        if not all_candidates:
            raise RoutingError("No enabled models or endpoints available in registry.")

        features = extract_request_features(request)
        eligible, rejections = filter_eligible_candidates(
            candidates=all_candidates,
            request=request,
            health_tracker=self.health_tracker,
        )

        if not eligible:
            reasons_summary = "; ".join(f"{ep}: {reason}" for ep, reason in rejections.items())
            raise RoutingError(
                f"No eligible candidates satisfied request requirements. Rejections: {reasons_summary}"
            )

        # For auto strategies (non-manual), prioritize real providers over mock
        if strategy_name != "manual" and not pinned_model_id and not pinned_endpoint_id:
            real_candidates = [c for c in eligible if c.protocol != "mock"]
            if real_candidates:
                eligible = real_candidates

        strategy = get_strategy(strategy_name)

        decision = strategy.rank(
            eligible_candidates=eligible,
            request=request,
            features=features,
            pinned_model_id=pinned_model_id,
            pinned_endpoint_id=pinned_endpoint_id,
            seed=seed,
            **kwargs,
        )

        return decision
