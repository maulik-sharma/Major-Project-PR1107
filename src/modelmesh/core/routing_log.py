"""Routing-log persistence and the plain-data routing metadata sent to the UI."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from modelmesh.core.types import Candidate, RoutingDecision, Usage


def answered_below_bar(features: Dict[str, Any], answered_by: Candidate) -> bool:
    """True if Smart picked below the bar, or failover landed on a below-bar model (spec 4.5)."""
    if features.get("below_bar"):
        return True
    admitted = features.get("admitted_model_ids") or []
    return bool(admitted) and answered_by.model_id not in admitted


def routing_metadata(decision: RoutingDecision, answered_by: Optional[Candidate] = None) -> Dict[str, Any]:
    """Build JSON-safe routing details for the UI (badges, notices, insights panel)."""
    f = decision.request_features or {}
    smart = f.get("smart_decision") or {}
    admitted = set(f.get("admitted_model_ids") or [])
    meta: Dict[str, Any] = {
        "strategy": decision.strategy_name,
        "reason": decision.reason,
        "decision_id": decision.decision_id,
        "decision_source": f.get("decision_source"),
        "decision_error": f.get("decision_error"),
        "notices": list(f.get("notices") or []),
        "below_bar": answered_below_bar(f, answered_by) if answered_by else bool(f.get("below_bar")),
    }
    if decision.strategy_name != "smart_clef":
        return meta

    answers = smart.get("answers") or {}
    meta.update({
        "task": f.get("task"),
        "difficulty": (answers.get("difficulty") or {}).get("score"),
        "precision": (answers.get("precision") or {}).get("score"),
        "need": f.get("need"),
        "bar": f.get("bar"),
        "metric_used": f.get("metric_used"),
        "lacking_metric_models": list(f.get("lacking_metric_models") or []),
        "chosen_q": f.get("chosen_q"),
        "router_latency_ms": f.get("router_latency_ms"),
        "stickiness_outcome": f.get("stickiness_outcome"),
        "profile": f.get("profile"),
        "candidates": [
            {
                "model_id": c.get("model_id"),
                "q": c.get("q"),
                "admitted": c.get("model_id") in admitted,
            }
            for c in _unique_models(decision.eligible_candidates)
        ],
    })
    return meta


def _unique_models(rows: list) -> list:
    seen: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        seen.setdefault(row.get("model_id"), row)
    return list(seen.values())


def record_turn(
    storage: Any,
    decision: RoutingDecision,
    answered_by: Candidate,
    usage: Usage,
    cost_usd: float,
    latency_ms: int,
    ttft_ms: int,
    conversation_id: Optional[str],
) -> None:
    """Write one routing_log row (with Smart fields when Smart routed the turn)."""
    features = decision.request_features or {}
    smart_dec = features.get("smart_decision")
    common = dict(
        decision=decision,
        chosen_candidate=answered_by,
        usage=usage,
        cost_usd=cost_usd,
        latency_ms=latency_ms,
        ttft_ms=ttft_ms,
        conversation_id=conversation_id,
    )
    if smart_dec is None and decision.strategy_name != "smart_clef":
        storage.record_routing_log(**common)
        return
    storage.record_smart_routing_log(
        **common,
        decision_source=features.get("decision_source", "none"),
        decision_provider_id=features.get("decision_provider_id"),
        rubric_version=features.get("rubric_version"),
        decision_json=json.dumps(smart_dec.get("answers", {})) if isinstance(smart_dec, dict) else None,
        need=features.get("need"),
        bar=features.get("bar"),
        metric_used=features.get("metric_used"),
        score_snapshot_id=features.get("score_snapshot_id"),
        chosen_q=features.get("chosen_q"),
        chosen_score=features.get("chosen_score"),
        below_bar=answered_below_bar(features, answered_by),
        router_latency_ms=int(features.get("router_latency_ms") or 0),
        router_cost_usd=float(features.get("router_cost_usd") or 0.0),
        stickiness_outcome=features.get("stickiness_outcome"),
    )
