"""DecisionProvider abstract base class and data contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import time
from typing import Any, Callable, Dict, List, Optional, Type

from modelmesh.core.errors import ProviderError
from modelmesh.core.types import Usage


@dataclass
class DecisionRequest:
    """Canonical request passed to decision providers."""
    state: str
    questions: Dict[str, Dict[str, Any]]
    timeout_s: float = 1.5
    images: Optional[List[str]] = None
    model: str = ""
    provider_id: str = ""
    # Local-only signals for the heuristic; never sent to a remote provider.
    latest_text: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DecisionResult:
    """Normalized response produced by a decision provider.

    ``source`` is required so a new provider can never be mislabelled:
    "clef", "heuristic", "heuristic_fallback", "cache" or "mock".
    """
    answers: Dict[str, Any]
    source: str
    usage: Usage = field(default_factory=Usage)
    latency_ms: float = 0.0
    provider_id: str = "heuristic"
    model: str = ""
    raw_response: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None  # why a fallback happened, if it did


class DecisionProvider(ABC):
    """Abstract protocol for fast System One decision models."""

    #: True if the provider sends the state to a remote service (privacy switch applies).
    remote: bool = False

    @classmethod
    def from_config(cls, config: Any) -> "DecisionProvider":
        """Build the provider from its ``DecisionProviderConfig``. Override if it needs settings."""
        return cls()

    @abstractmethod
    def decide(self, request: DecisionRequest) -> DecisionResult:
        """Evaluate the structured state and questions, returning calibrated judgments."""
        raise NotImplementedError


_DECISION_PROVIDERS: Dict[str, Type[DecisionProvider]] = {}


def register_decision_provider(protocol: str) -> Callable[[Type[DecisionProvider]], Type[DecisionProvider]]:
    """Decorator to register a decision provider implementation."""
    def decorator(cls: Type[DecisionProvider]) -> Type[DecisionProvider]:
        _DECISION_PROVIDERS[protocol] = cls
        return cls
    return decorator


def get_decision_provider(protocol: str) -> Type[DecisionProvider]:
    """Retrieve the decision provider class for a given protocol ID."""
    if protocol not in _DECISION_PROVIDERS:
        raise ProviderError(
            message=f"No decision provider registered for protocol '{protocol}'. Available: {list(_DECISION_PROVIDERS.keys())}",
            category="bad_request",
            provider_id=protocol,
            retryable=False,
        )
    return _DECISION_PROVIDERS[protocol]
