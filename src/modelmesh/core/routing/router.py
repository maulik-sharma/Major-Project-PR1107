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
        decision_service: Optional[Any] = None,
        storage: Optional[Any] = None,
    ) -> None:
        self.registry = registry
        self.health_tracker = health_tracker or EndpointHealthTracker()
        self.storage = storage
        self._decision_service = decision_service

    @property
    def decision_service(self) -> Any:
        if self._decision_service is None:
            from modelmesh.core.config.routing_config import load_routing_config
            from modelmesh.core.routing.smart.decision.service import DecisionService
            cfg = load_routing_config()
            self._decision_service = DecisionService(config=cfg, storage=self.storage)
        return self._decision_service

    def route(
        self,
        request: ChatRequest,
        strategy_name: str = "cheapest_first",
        pinned_model_id: Optional[str] = None,
        pinned_endpoint_id: Optional[str] = None,
        seed: Optional[int] = None,
        **kwargs: Any,
    ) -> RoutingDecision:
        """Filter candidates, execute the requested strategy, and return a decision."""
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

        # Support alias 'auto' -> 'smart_clef'
        effective_strategy_name = "smart_clef" if strategy_name == "auto" else strategy_name
        strategy = get_strategy(effective_strategy_name)

        # If strategy needs decision (Smart Router), perform decision call before ranking
        if getattr(strategy, "needs_decision", False):
            if "smart_decision" not in features:
                if "smart_decision" in kwargs:
                    features["smart_decision"] = kwargs["smart_decision"]
                else:
                    dec_res = self.decision_service.get_decision(
                        messages=request.messages,
                        tools_enabled=bool(request.tools),
                        tools_count=len(request.tools),
                    )
                    features["smart_decision"] = {
                        "answers": dec_res.answers,
                        "source": dec_res.source,
                        "provider_id": dec_res.provider_id,
                        "model": dec_res.model,
                        "latency_ms": dec_res.latency_ms,
                        "usage": dec_res.usage.to_dict(),
                    }

            # Fetch latest snapshot from score store if available
            if self.storage is not None and "snapshot_override" not in kwargs:
                from modelmesh.core.scores.snapshots import ScoreStore
                store = ScoreStore(self.storage)
                kwargs["snapshot_override"] = store.get_latest_snapshot()

        decision = strategy.rank(
            eligible_candidates=eligible,
            request=request,
            features=features,
            pinned_model_id=pinned_model_id,
            pinned_endpoint_id=pinned_endpoint_id,
            seed=seed,
            rejections=rejections,
            **kwargs,
        )

        return decision
