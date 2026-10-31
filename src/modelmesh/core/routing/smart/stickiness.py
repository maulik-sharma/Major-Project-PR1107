"""Session stickiness (spec 4.6). Pure: plain data in, plain data out."""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from modelmesh.core.types import Candidate


def apply_stickiness(
    chosen: Candidate,
    fallback_chain: List[Candidate],
    sticky_model_id: Optional[str],
    q_scores: Dict[str, float],
    bar: float,
    task_changed: float,
    task_changed_threshold: float,
    stay_unless_cost_ratio: float,
    cost_of: Dict[str, float],
) -> Tuple[Candidate, List[Candidate], Optional[str]]:
    """Keep the conversation's current model when it still clears the bar.

    - Current model still clears the bar: stay, unless the task changed and
      the new choice is cheaper by ``stay_unless_cost_ratio``.
    - Current model no longer clears the bar (or is gone): use the new choice.

    Args:
        cost_of: estimated request cost by endpoint id.

    Returns:
        (chosen, fallback_chain, outcome) where outcome is one of
        "kept", "upgraded", "downgraded", "switched_on_task_change", or None
        (no previous model in this conversation).
    """
    if not sticky_model_id:
        return chosen, fallback_chain, None
    if sticky_model_id == chosen.model_id:
        return chosen, fallback_chain, "kept"

    sticky_q = q_scores.get(sticky_model_id)
    sticky_cands = [c for c in fallback_chain if c.model_id == sticky_model_id]
    new_q = q_scores.get(chosen.model_id, 0.0)

    if sticky_q is None or not sticky_cands or sticky_q < bar:
        outcome = "upgraded" if sticky_q is None or new_q >= sticky_q else "downgraded"
        return chosen, fallback_chain, outcome

    sticky_cost = cost_of.get(sticky_cands[0].endpoint_id, 0.0)
    new_cost = cost_of.get(chosen.endpoint_id, 0.0)
    cheaper_by_ratio = new_cost <= 0.0 < sticky_cost or (
        new_cost > 0.0 and sticky_cost / new_cost >= stay_unless_cost_ratio
    )
    if task_changed >= task_changed_threshold and cheaper_by_ratio:
        return chosen, fallback_chain, "switched_on_task_change"

    # Stay: sticky model's endpoints first, then the original choice and the rest.
    rest = [c for c in fallback_chain if c.model_id != sticky_model_id]
    return sticky_cands[0], sticky_cands[1:] + [chosen] + rest, "kept"
