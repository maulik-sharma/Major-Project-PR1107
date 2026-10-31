"""Smart Clef decision-based routing strategy."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from modelmesh.core.config.routing_config import SmartRoutingConfig, load_routing_config
from modelmesh.core.cost import estimate_request_tokens, expected_output_tokens
from modelmesh.core.routing.base import Strategy, register_strategy
from modelmesh.core.routing.smart.scoring import compute_bar, compute_need
from modelmesh.core.routing.smart.selector import select_smart_candidate
from modelmesh.core.routing.smart.stickiness import apply_stickiness
from modelmesh.core.scores.snapshots import (
    EffectiveScores,
    ScoreSnapshot,
    resolve_effective_scores,
)
from modelmesh.core.types import Candidate, ChatRequest, RoutingDecision


@register_strategy("smart_clef")
class SmartClefStrategy(Strategy):
    """Smart routing strategy driven by Clef-flash decision evaluations and AA model scores."""

    name = "smart_clef"
    needs_decision = True

    def __init__(
        self,
        config: Optional[SmartRoutingConfig] = None,
        snapshot: Optional[ScoreSnapshot] = None,
    ) -> None:
        self._custom_config = config
        self.snapshot = snapshot

    @property
    def config(self) -> SmartRoutingConfig:
        """Return explicit injected config or dynamically reload latest config from disk."""
        if self._custom_config is not None:
            return self._custom_config
        return load_routing_config()

    def rank(
        self,
        eligible_candidates: List[Candidate],
        request: ChatRequest,
        features: Dict[str, Any],
        profile: Optional[str] = None,
        bias_override: Optional[float] = None,
        snapshot_override: Optional[ScoreSnapshot] = None,
        **kwargs: Any,
    ) -> RoutingDecision:
        cfg = self.config  # Read once so need and bar come from the same file.

        # 1. Extract decision result from features
        decision_data: Dict[str, Any] = features.get("smart_decision", {})
        answers = decision_data.get("answers", {})
        decision_source = decision_data.get("source", "heuristic_fallback")
        decision_provider_id = decision_data.get("provider_id")
        decision_latency_ms = decision_data.get("latency_ms", 0.0)

        # 2. Extract answer dimensions (unknown task labels count as general chat)
        task_obj = answers.get("task")
        task_choice = task_obj.get("choice", "chat_general") if isinstance(task_obj, dict) else "chat_general"
        task_options = cfg.rubric.questions.get("task")
        if task_options and task_options.options and task_choice not in task_options.options:
            task_choice = "chat_general"
        needs_reasoning_noul = _noul(answers, "needs_reasoning")

        # 3. Resolve metric
        metric = cfg.metric_by_task.get(task_choice, cfg.metric_by_task.get("default", "intelligence"))

        # 4. Compute quality need and bar
        effective_bias = bias_override
        if effective_bias is None and profile and profile in cfg.profiles:
            effective_bias = cfg.profiles[profile].bias
        if effective_bias is None:
            effective_bias = cfg.need.bias

        need = compute_need(
            answers=answers,
            need_config=cfg.need,
            bias_override=effective_bias,
        )
        bar = compute_bar(need=need, slack=cfg.need.slack)

        # 5. Resolve effective scores for candidate models
        active_snapshot = snapshot_override or self.snapshot
        effective_scores_map: Dict[str, EffectiveScores] = {}
        for c in eligible_candidates:
            if c.model_id not in effective_scores_map:
                effective_scores_map[c.model_id] = resolve_effective_scores(c.model_config, active_snapshot)

        # 6. Estimate token counts
        tokens_in_est = estimate_request_tokens(request)
        tokens_out_est = expected_output_tokens(request)

        # 7. Execute pure selection
        chosen, fallback_chain, select_meta = select_smart_candidate(
            candidates=eligible_candidates,
            effective_scores=effective_scores_map,
            metric=metric,
            need=need,
            bar=bar,
            task=task_choice,
            needs_reasoning=needs_reasoning_noul,
            pool_include=cfg.pool.include,
            pool_exclude=cfg.pool.exclude,
            unscored_policy=cfg.unscored_policy,
            tokens_in_est=tokens_in_est,
            tokens_out_est=tokens_out_est,
        )

        # 8. Session stickiness (never on the first message of a conversation)
        stickiness_outcome: Optional[str] = None
        sticky_model_id: Optional[str] = kwargs.get("sticky_model_id")
        if cfg.stickiness.enabled and select_meta["scores_available"]:
            costs = {
                c.endpoint_id: (c.price_in_per_mtok * tokens_in_est + c.price_out_per_mtok * tokens_out_est) / 1e6
                for c in [chosen] + fallback_chain
            }
            chosen, fallback_chain, stickiness_outcome = apply_stickiness(
                chosen=chosen,
                fallback_chain=fallback_chain,
                sticky_model_id=sticky_model_id,
                q_scores=select_meta["q_scores"],
                bar=bar,
                task_changed=_noul(answers, "task_changed"),
                task_changed_threshold=cfg.stickiness.task_changed_threshold,
                stay_unless_cost_ratio=cfg.stickiness.stay_unless_cost_ratio,
                cost_of=costs,
            )

        chosen_q = select_meta["q_scores"].get(chosen.model_id) if select_meta["scores_available"] else None
        if select_meta["scores_available"]:
            reason = (
                f"Smart routed to '{chosen.endpoint_id}' (need={need:.2f}, bar={bar:.2f}, "
                f"q={chosen_q:.2f}, task={task_choice}, source={decision_source})"
            )
        else:
            reason = f"Smart routing had no quality scores; cheapest model '{chosen.endpoint_id}' chosen."

        all_meta = dict(features)
        all_meta.update({
            "smart_decision": decision_data,
            "decision_source": decision_source,
            "decision_provider_id": decision_provider_id,
            "decision_error": decision_data.get("error"),
            "rubric_version": cfg.rubric.version,
            "need": need,
            "bar": bar,
            "metric_used": select_meta["metric_used"],
            "task": task_choice,
            "chosen_q": chosen_q,
            "chosen_score": select_meta["chosen_score"],
            "below_bar": select_meta["below_bar"],
            "admitted_model_ids": select_meta.get("admitted_model_ids", []),
            "router_latency_ms": decision_latency_ms,
            # Free-tier decision providers report no price, so the router call is logged at $0.
            "router_cost_usd": 0.0,
            "score_snapshot_id": active_snapshot.id if active_snapshot is not None else None,
            "score_snapshot_note": kwargs.get("snapshot_note"),
            "stickiness_outcome": stickiness_outcome,
            "estimated_cost_usd": select_meta["estimated_cost_usd"],
            "notices": select_meta["notices"],
            "profile": profile,
        })

        return RoutingDecision(
            chosen_candidate=chosen,
            fallback_chain=fallback_chain,
            strategy_name=self.name,
            reason=reason,
            eligible_candidates=[
                {"endpoint_id": c.endpoint_id, "model_id": c.model_id, "q": select_meta["q_scores"].get(c.model_id)}
                for c in eligible_candidates
            ],
            request_features=all_meta,
        )


def _noul(answers: Dict[str, Any], key: str) -> float:
    """Return a yes/no probability answer, or 0.0 if absent."""
    obj = answers.get(key)
    return float(obj.get("noul", 0.0)) if isinstance(obj, dict) else 0.0
