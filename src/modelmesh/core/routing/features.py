"""Request feature extraction and per-candidate eligibility filtering."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from modelmesh.core.cost import estimate_request_tokens
from modelmesh.core.keys import has_provider_auth
from modelmesh.core.routing.health import EndpointHealthTracker
from modelmesh.core.types import Candidate, ChatRequest, ImagePart


def extract_request_features(request: ChatRequest) -> Dict[str, Any]:
    """Extract quantitative and categorical features from a ChatRequest."""
    has_images = any(
        isinstance(p, ImagePart)
        for msg in request.messages
        for p in msg.parts
    )
    has_tools = bool(request.tools)
    est_tokens = estimate_request_tokens(request)
    prompt_len = sum(len(msg.text_content()) for msg in request.messages)

    return {
        "has_images": has_images,
        "has_tools": has_tools,
        "estimated_input_tokens": est_tokens,
        "prompt_length_chars": prompt_len,
        "message_count": len(request.messages),
        "required_capabilities": list(request.required_capabilities),
    }


def filter_eligible_candidates(
    candidates: List[Candidate],
    request: ChatRequest,
    health_tracker: Optional[EndpointHealthTracker] = None,
    safety_margin_tokens: int = 500,
) -> Tuple[List[Candidate], Dict[str, str]]:
    """Filter candidates based on capability, context window, auth, and health.

    Args:
        candidates: List of all resolved candidates.
        request: The incoming ChatRequest.
        health_tracker: Optional tracker for endpoint failure cooldowns.
        safety_margin_tokens: Buffer added to estimated input tokens.

    Returns:
        Tuple of (eligible_candidates, rejection_reasons_by_endpoint_id).
    """
    est_tokens = estimate_request_tokens(request)
    required_caps = request.required_capabilities
    eligible: List[Candidate] = []
    rejections: Dict[str, str] = {}

    for cand in candidates:
        # Check enabled flags
        if not cand.model_config.enabled:
            rejections[cand.endpoint_id] = f"Model '{cand.model_id}' is disabled."
            continue
        if not cand.endpoint_config.enabled:
            rejections[cand.endpoint_id] = f"Endpoint '{cand.endpoint_id}' is disabled."
            continue

        # Check provider authentication credentials (unless local or mock)
        if not cand.local and cand.protocol != "mock":
            if not has_provider_auth(cand.provider_config.auth_env):
                rejections[cand.endpoint_id] = (
                    f"Missing credentials for provider '{cand.provider_id}' "
                    f"(requires env vars: {cand.provider_config.auth_env})."
                )
                continue

        # Check required capabilities
        missing_caps = required_caps - cand.effective_capabilities
        if missing_caps:
            rejections[cand.endpoint_id] = (
                f"Missing required capabilities: {list(missing_caps)} "
                f"(supports: {list(cand.effective_capabilities)})."
            )
            continue

        # Check context window limit
        if cand.effective_context_window < (est_tokens + safety_margin_tokens):
            rejections[cand.endpoint_id] = (
                f"Context window ({cand.effective_context_window}) too small for "
                f"estimated request ({est_tokens} + {safety_margin_tokens} margin)."
            )
            continue

        # Check session blacklist and health status
        if health_tracker is not None:
            if health_tracker.is_blacklisted(endpoint_id=cand.endpoint_id, model_id=cand.model_id):
                reason = health_tracker.get_blacklist_reason(
                    endpoint_id=cand.endpoint_id, model_id=cand.model_id
                ) or "Query failed earlier in this session"
                rejections[cand.endpoint_id] = f"Model '{cand.model_id}' is blacklisted for this session: {reason}"
                continue

            if not health_tracker.is_healthy(cand.endpoint_id, cand.model_id):
                rejections[cand.endpoint_id] = "Endpoint is temporarily cooling down after failures."
                continue

        eligible.append(cand)

    # If all otherwise-eligible candidates were rejected solely due to health cooldown (not blacklisted),
    # recover them so the user isn't completely stranded
    if not eligible and health_tracker is not None:
        health_rejected = [
            cand for cand in candidates
            if cand.endpoint_id in rejections
            and "cooling down" in rejections[cand.endpoint_id]
        ]
        if health_rejected:
            eligible = health_rejected
            for cand in eligible:
                rejections.pop(cand.endpoint_id, None)

    return eligible, rejections
