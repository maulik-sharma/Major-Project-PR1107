"""Smart Clef decision-based routing strategy."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from modelmesh.core.config.routing_config import SmartRoutingConfig, load_routing_config
from modelmesh.core.cost import estimate_request_tokens
from modelmesh.core.routing.base import Strategy, register_strategy
from modelmesh.core.routing.smart.scoring import compute_bar, compute_need
from modelmesh.core.routing.smart.selector import select_smart_candidate
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
        # 1. Extract decision result from features
        decision_data: Dict[str, Any] = features.get("smart_decision", {})
        answers = decision_data.get("answers", {})
        decision_source = decision_data.get("source", "heuristic_fallback")
        decision_provider_id = decision_data.get("provider_id", "clef-flash")
        decision_latency_ms = decision_data.get("latency_ms", 0.0)

        # 2. Extract answer dimensions
        task_choice = answers.get("task", {}).get("choice", "chat_general") if isinstance(answers.get("task"), dict) else "chat_general"
        needs_reasoning_noul = answers.get("needs_reasoning", {}).get("noul", 0.0) if isinstance(answers.get("needs_reasoning"), dict) else 0.0

        # 3. Resolve metric
        metric = self.config.metric_by_task.get(task_choice, self.config.metric_by_task.get("default", "intelligence"))

        # 4. Compute quality need and bar
        effective_bias = bias_override
        if effective_bias is None and profile and profile in self.config.profiles:
            effective_bias = self.config.profiles[profile].bias
        if effective_bias is None:
            effective_bias = self.config.need.bias

        need = compute_need(
            answers=answers,
            need_config=self.config.need,
            bias_override=effective_bias,
        )
        bar = compute_bar(need=need, slack=self.config.need.slack)

        # 5. Resolve effective scores for candidate models
        active_snapshot = snapshot_override or self.snapshot
        effective_scores_map: Dict[str, EffectiveScores] = {}
        for c in eligible_candidates:
            if c.model_id not in effective_scores_map:
                effective_scores_map[c.model_id] = resolve_effective_scores(c.model_config, active_snapshot)

        # 6. Estimate token counts
        tokens_in_est = estimate_request_tokens(request)
        tokens_out_est = int(request.max_tokens or 1000)

        # 7. Execute pure selection
        chosen, fallback_chain, select_meta = select_smart_candidate(
            candidates=eligible_candidates,
            effective_scores=effective_scores_map,
            metric=metric,
            need=need,
            bar=bar,
            task=task_choice,
            needs_reasoning=needs_reasoning_noul,
            pool_include=self.config.pool.include,
            pool_exclude=self.config.pool.exclude,
            unscored_policy=self.config.unscored_policy,
            tokens_in_est=tokens_in_est,
            tokens_out_est=tokens_out_est,
        )

        reason = (
            f"Smart routed to '{chosen.endpoint_id}' (need={need:.2f}, bar={bar:.2f}, "
            f"q={select_meta['chosen_q']:.2f}, task={task_choice}, source={decision_source})"
        )

        all_meta = dict(features)
        all_meta.update({
            "smart_decision": decision_data,
            "decision_source": decision_source,
            "decision_provider_id": decision_provider_id,
            "rubric_version": self.config.rubric.version,
            "need": need,
            "bar": bar,
            "metric_used": metric,
            "task": task_choice,
            "chosen_q": select_meta["chosen_q"],
            "chosen_score": select_meta["chosen_score"],
            "below_bar": select_meta["below_bar"],
            "router_latency_ms": decision_latency_ms,
            "estimated_cost_usd": select_meta["estimated_cost_usd"],
        })

        return RoutingDecision(
            chosen_candidate=chosen,
            fallback_chain=fallback_chain,
            strategy_name=self.name,
            reason=reason,
            eligible_candidates=[
                {"endpoint_id": c.endpoint_id, "model_id": c.model_id, "q": select_meta["q_scores"].get(c.model_id, 0.0)}
                for c in eligible_candidates
            ],
            request_features=all_meta,
        )
