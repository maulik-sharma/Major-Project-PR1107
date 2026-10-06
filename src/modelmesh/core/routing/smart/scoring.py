"""Pure mathematical functions for need computation, quality normalization, and bar gating."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from modelmesh.core.config.routing_config import NeedConfig


def clamp(val: float, low: float = 0.0, high: float = 1.0) -> float:
    """Clamp a float value within [low, high]."""
    return max(low, min(val, high))


def compute_need(
    answers: Dict[str, Any],
    need_config: NeedConfig,
    bias_override: Optional[float] = None,
) -> float:
    """Compute the calibrated quality need in [0.0, 1.0] from decision answers.

    Formula:
      need_raw = w_d * (difficulty / 4) + w_p * (precision / 3) + w_b * (benefit / 3)
      need = clamp(need_raw + bias + uncertainty_k * (1 - confidence_difficulty), 0, 1)
    """
    diff_obj = answers.get("difficulty", {})
    prec_obj = answers.get("precision", {})
    bene_obj = answers.get("larger_model_benefit", {})

    diff_val = float(diff_obj.get("score", 1.0) if isinstance(diff_obj, dict) else diff_obj)
    prec_val = float(prec_obj.get("score", 1.0) if isinstance(prec_obj, dict) else prec_obj)
    bene_val = float(bene_obj.get("score", 1.0) if isinstance(bene_obj, dict) else bene_obj)

    conf_diff = float(diff_obj.get("confidence", 0.8) if isinstance(diff_obj, dict) else 0.8)

    w = need_config.weights
    w_sum = w.difficulty + w.precision + w.larger_model_benefit
    if w_sum <= 0:
        w_d, w_p, w_b = 0.5, 0.2, 0.3
    else:
        w_d, w_p, w_b = w.difficulty / w_sum, w.precision / w_sum, w.larger_model_benefit / w_sum

    need_raw = (
        w_d * (diff_val / 4.0)
        + w_p * (prec_val / 3.0)
        + w_b * (bene_val / 3.0)
    )

    bias = bias_override if bias_override is not None else need_config.bias
    uncertainty_term = need_config.uncertainty_k * (1.0 - conf_diff)

    return clamp(need_raw + bias + uncertainty_term, 0.0, 1.0)


def compute_bar(need: float, slack: float = 0.10) -> float:
    """Compute the admission bar: max(0.0, need - slack)."""
    return max(0.0, need - slack)


def normalize_scores_to_quality(
    scores: Dict[str, float],
) -> Dict[str, float]:
    """Min-max normalize a map of candidate model scores into quality q in [0.0, 1.0].

    Formula:
      q = (s - s_min) / (s_max - s_min)
      If s_max == s_min: q = 1.0 for all.
    """
    if not scores:
        return {}
    vals = list(scores.values())
    s_min = min(vals)
    s_max = max(vals)

    if s_max <= s_min:
        return {k: 1.0 for k in scores}

    return {
        k: round((v - s_min) / (s_max - s_min), 4)
        for k, v in scores.items()
    }
