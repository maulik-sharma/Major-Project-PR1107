"""Strategy abstract base class and helper algorithms for candidate ranking."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional, Tuple, Type

from modelmesh.core.cost import estimate_request_cost
from modelmesh.core.errors import RegistryError
from modelmesh.core.types import Candidate, ChatRequest, RoutingDecision


def sort_endpoints(
    model_candidates: List[Candidate],
    policy: str,
    cost_of: Callable[[Candidate], float],
) -> List[Candidate]:
    """Order one model's endpoints by its endpoint policy (pure).

    - ``cheapest``: estimated cost, then priority.
    - ``fastest``: ``quirks.latency_ms`` if configured (unknown = last), then priority.
      Observed latency from the routing log is not used yet.
    - ``priority`` (default): priority, then price, then id.
    """
    if policy == "cheapest":
        return sorted(model_candidates, key=lambda c: (cost_of(c), c.priority, c.endpoint_id))
    if policy == "fastest":
        def latency(c: Candidate) -> float:
            raw = c.endpoint_config.quirks.get("latency_ms")
            return float(raw) if isinstance(raw, (int, float)) else float("inf")

        return sorted(model_candidates, key=lambda c: (latency(c), c.priority, c.endpoint_id))
    return sorted(
        model_candidates,
        key=lambda c: (c.priority, c.price_in_per_mtok, c.price_out_per_mtok, c.endpoint_id),
    )


def order_endpoints_for_model(
    model_candidates: List[Candidate],
    policy: str,
    request: ChatRequest,
) -> List[Candidate]:
    """Order candidate endpoints for a single model according to its endpoint policy.

    Args:
        model_candidates: List of Candidate objects sharing the same model_id.
        policy: 'priority', 'cheapest', or 'fastest'.
        request: The ChatRequest (used for cost estimations).

    Returns:
        Sorted list of Candidates.
    """
    return sort_endpoints(
        model_candidates,
        policy,
        lambda c: estimate_request_cost(request, c.price_in_per_mtok, c.price_out_per_mtok),
    )


def build_fallback_chain(
    ordered_model_groups: List[List[Candidate]],
) -> Tuple[Candidate, List[Candidate]]:
    """Build chosen candidate and fallback chain enforcing same-model-first.

    Args:
        ordered_model_groups: Ordered list of models, each containing its ordered endpoints.

    Returns:
        (chosen_candidate, fallback_chain).
    """
    if not ordered_model_groups or not ordered_model_groups[0]:
        raise RegistryError("Cannot build fallback chain: no model groups provided.")

    chosen_cand = ordered_model_groups[0][0]
    # Sibling endpoints of chosen model come first in fallback chain
    same_model_fallbacks = ordered_model_groups[0][1:]

    # Remaining models' endpoints follow
    other_models_fallbacks: List[Candidate] = []
    for group in ordered_model_groups[1:]:
        other_models_fallbacks.extend(group)

    fallback_chain = same_model_fallbacks + other_models_fallbacks
    return chosen_cand, fallback_chain


class Strategy(ABC):
    """Abstract base class for all routing strategies."""

    name: str
    needs_decision: bool = False

    @abstractmethod
    def rank(
        self,
        eligible_candidates: List[Candidate],
        request: ChatRequest,
        features: Dict[str, Any],
        **kwargs: Any,
    ) -> RoutingDecision:
        """Rank eligible candidates and produce a RoutingDecision.

        Args:
            eligible_candidates: Non-empty list of eligible Candidate objects.
            request: The ChatRequest to be routed.
            features: Extracted request features dict.
            **kwargs: Extra parameters like seed, pinned_model_id, pinned_endpoint_id.

        Returns:
            RoutingDecision instance.
        """
        pass


_STRATEGY_REGISTRY: Dict[str, Strategy] = {}


def register_strategy(name: str) -> Callable[[Type[Strategy]], Type[Strategy]]:
    """Decorator to register a Strategy implementation."""
    def decorator(cls: Type[Strategy]) -> Type[Strategy]:
        cls.name = name
        _STRATEGY_REGISTRY[name] = cls()
        return cls
    return decorator


def get_strategy(name: str) -> Strategy:
    """Retrieve a registered strategy by name."""
    strat = _STRATEGY_REGISTRY.get(name)
    if not strat:
        raise RegistryError(
            f"Unknown routing strategy '{name}'. Available strategies: {list(_STRATEGY_REGISTRY.keys())}"
        )
    return strat


def list_strategies() -> List[str]:
    """List names of all registered strategies."""
    return list(_STRATEGY_REGISTRY.keys())
