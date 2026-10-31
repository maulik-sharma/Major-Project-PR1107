"""Validation and normalisation of decision-provider answers against the rubric."""

from __future__ import annotations

from typing import Any, Dict

from modelmesh.core.config.routing_config import RubricConfig

# Answers the need formula and selector cannot work without.
REQUIRED_ANSWERS = ("task", "difficulty", "precision", "larger_model_benefit")


class InvalidDecisionError(ValueError):
    """Raised when a decision provider returns answers that do not fit the rubric."""


def _clamp(val: float, low: float, high: float) -> float:
    return max(low, min(val, high))


def _as_float(obj: Dict[str, Any], key: str, qid: str) -> float:
    raw = obj.get(key)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise InvalidDecisionError(f"Answer '{qid}' has non-numeric '{key}': {raw!r}")
    return float(raw)


def validate_answers(answers: Any, rubric: RubricConfig) -> Dict[str, Any]:
    """Check decision answers against the rubric and return a clamped copy.

    - Required answers must be present and be objects.
    - ``choice`` answers must name one of the rubric's options.
    - ``score`` answers are clamped to ``[0, len(levels) - 1]``.
    - ``noul`` answers and any ``confidence`` are clamped to ``[0, 1]``.

    Raises:
        InvalidDecisionError: If the answers cannot be used safely.
    """
    if not isinstance(answers, dict):
        raise InvalidDecisionError("Decision answers must be an object.")

    missing = [qid for qid in REQUIRED_ANSWERS if qid in rubric.questions and qid not in answers]
    if missing:
        raise InvalidDecisionError(f"Decision answers missing required keys: {missing}")

    cleaned: Dict[str, Any] = {}
    for qid, question in rubric.questions.items():
        if qid not in answers:
            continue
        obj = answers[qid]
        if not isinstance(obj, dict):
            raise InvalidDecisionError(f"Answer '{qid}' must be an object, got {type(obj).__name__}.")
        out = dict(obj)

        if question.type == "choice":
            choice = obj.get("choice")
            if choice not in (question.options or {}):
                raise InvalidDecisionError(f"Answer '{qid}' has unknown choice: {choice!r}")
        elif question.type == "score":
            top = float(max(0, len(question.levels or []) - 1))
            out["score"] = _clamp(_as_float(obj, "score", qid), 0.0, top)
        elif question.type == "noul":
            out["noul"] = _clamp(_as_float(obj, "noul", qid), 0.0, 1.0)

        if "confidence" in obj:
            out["confidence"] = _clamp(_as_float(obj, "confidence", qid), 0.0, 1.0)
        cleaned[qid] = out

    return cleaned
