"""Deterministic mock decision provider for tests and offline simulation."""

from __future__ import annotations

from typing import Any, Dict, Optional

from modelmesh.core.routing.smart.decision.base import (
    DecisionProvider,
    DecisionRequest,
    DecisionResult,
    register_decision_provider,
)
from modelmesh.core.types import Usage


@register_decision_provider("mock")
class MockDecisionProvider(DecisionProvider):
    """Deterministic mock provider returning preset decision answers."""

    def __init__(self, preset_answers: Optional[Dict[str, Any]] = None) -> None:
        self.preset_answers = preset_answers or {
            "task": {
                "type": "choice",
                "choice": "coding",
                "probabilities": {"coding": 0.95},
                "confidence": 0.90,
            },
            "difficulty": {
                "type": "score",
                "score": 2.0,
                "confidence": 0.85,
            },
            "precision": {
                "type": "score",
                "score": 2.0,
                "confidence": 0.85,
            },
            "larger_model_benefit": {
                "type": "score",
                "score": 1.5,
                "confidence": 0.80,
            },
            "needs_reasoning": {
                "type": "noul",
                "noul": 0.20,
            },
            "task_changed": {
                "type": "noul",
                "noul": 0.10,
            },
        }

    def decide(self, request: DecisionRequest) -> DecisionResult:
        return DecisionResult(
            answers=dict(self.preset_answers),
            usage=Usage(input_tokens=150, output_tokens=0),
            latency_ms=1.5,
            provider_id=request.provider_id or "mock",
            model="decision-mock",
            raw_response={"answers": self.preset_answers},
            source="mock",
        )
