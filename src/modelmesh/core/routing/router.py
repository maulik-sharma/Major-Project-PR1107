"""Main Router component orchestrating candidate filtering and strategy selection."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from modelmesh.core.errors import RoutingError
from modelmesh.core.registry import ModelRegistry
from modelmesh.core.routing.base import get_strategy
from modelmesh.core.routing.features import (
    COOLING_DOWN_REASON,
    extract_request_features,
    filter_eligible_candidates,
)
from modelmesh.core.routing.health import EndpointHealthTracker
from modelmesh.core.routing.smart.decision.base import DecisionRequest
from modelmesh.core.routing.smart.decision.heuristic import HeuristicDecisionProvider
from modelmesh.core.routing.smart.state_builder import latest_user_text
from modelmesh.core.types import Candidate, ChatRequest, RoutingDecision

logger = logging.getLogger(__name__)


class Router:
    """Evaluates requests against registered candidates using configured strategies."""

    def __init__(
        self,
        registry: ModelRegistry,
        health_tracker: Optional[EndpointHealthTracker] = None,
        decision_service: Optional[Any] = None,
        storage: Optional[Any] = None,
        safety_margin_tokens: int = 500,
    ) -> None:
        self.registry = registry
        self.health_tracker = health_tracker or EndpointHealthTracker()
        self.storage = storage
        self.safety_margin_tokens = safety_margin_tokens
        self._decision_service = decision_service
        self._snapshot_cache: Optional[Tuple[str, Any]] = None

    @property
    def decision_service(self) -> Any:
        if self._decision_service is None:
            from modelmesh.core.config.routing_config import load_routing_config
            from modelmesh.core.routing.smart.decision.service import DecisionService
            cfg = load_routing_config()
            self._decision_service = DecisionService(config=cfg, storage=self.storage)
        return self._decision_service

    def reload_config(self) -> None:
        """Reset cached decision service to reload updated routing configuration."""
        self._decision_service = None

    def apply_settings(self, cooldown_seconds: float, safety_margin_tokens: int) -> None:
        """Apply user router settings and forget health state (keys may have changed)."""
        self.health_tracker.cooldown_seconds = cooldown_seconds
        self.safety_margin_tokens = safety_margin_tokens
        self.health_tracker.clear_blacklist()

    def _decide(self, request: ChatRequest) -> Dict[str, Any]:
        """Run the decision service; never raises (Rule 17)."""
        try:
            res = self.decision_service.get_decision(
                messages=request.messages,
                tools_enabled=bool(request.tools),
                tools_count=len(request.tools),
            )
        except Exception as exc:  # e.g. routing.yaml unreadable while building the service
            logger.warning("Decision service unavailable: %s. Using heuristic fallback.", exc)
            res = HeuristicDecisionProvider().decide(
                DecisionRequest(state="", questions={}, latest_text=latest_user_text(request.messages))
            )
            res.source = "heuristic_fallback"
            res.error = str(exc)
        return {
            "answers": res.answers,
            "source": res.source,
            "provider_id": res.provider_id,
            "model": res.model,
            "latency_ms": res.latency_ms,
            "usage": res.usage.to_dict(),
            "error": res.error,
        }

    def _latest_snapshot(self) -> Optional[Any]:
        """Return the newest score snapshot, parsing it only when its id changes."""
        from modelmesh.core.scores.snapshots import ScoreStore

        try:
            store = ScoreStore(self.storage)
            latest_id = store.get_latest_snapshot_id()
            if latest_id is None:
                return None
            if self._snapshot_cache is None or self._snapshot_cache[0] != latest_id:
                self._snapshot_cache = (latest_id, store.get_latest_snapshot())
            return self._snapshot_cache[1]
        except Exception as exc:
            logger.warning("Could not load score snapshot: %s", exc)
            return None

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
            safety_margin_tokens=self.safety_margin_tokens,
        )

        # An explicit pin overrides the cooldown hint (but never an auth blacklist).
        if pinned_model_id or pinned_endpoint_id:
            for cand in all_candidates:
                pinned = cand.endpoint_id == pinned_endpoint_id or (
                    not pinned_endpoint_id and cand.model_id == pinned_model_id
                )
                if pinned and rejections.get(cand.endpoint_id) == COOLING_DOWN_REASON:
                    rejections.pop(cand.endpoint_id)
                    eligible.append(cand)

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
                    features["smart_decision"] = self._decide(request)

            if self.storage is not None and "snapshot_override" not in kwargs:
                kwargs["snapshot_override"] = self._latest_snapshot()

        decision = strategy.rank(
            eligible_candidates=eligible,
            request=request,
            features=features,
            pinned_model_id=pinned_model_id,
            pinned_endpoint_id=pinned_endpoint_id,
            seed=seed,
            rejections=rejections,
            all_candidates=all_candidates,
            **kwargs,
        )

        return decision
