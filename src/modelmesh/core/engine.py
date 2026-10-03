"""ChatEngine orchestrating turn lifecycles, routing, fallback, and streaming."""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, Iterator, List, Optional

from modelmesh.core.cost import calculate_cost, estimate_request_tokens
from modelmesh.core.errors import ProviderError, RoutingError
from modelmesh.core.providers.base import get_adapter
from modelmesh.core.registry import ModelRegistry
from modelmesh.core.types import (
    Candidate,
    ChatRequest,
    RoutingDecision,
    StreamEvent,
    StreamEventType,
    Usage,
)


class ChatEngine:
    """Core engine driving conversation turns, provider dispatch, and failover."""

    def __init__(
        self,
        registry: ModelRegistry,
        router: Optional[Any] = None,
        storage: Optional[Any] = None,
    ) -> None:
        self.registry = registry
        self.router = router
        self.storage = storage

    def run_turn(
        self,
        request: ChatRequest,
        candidate: Optional[Candidate] = None,
        strategy_name: str = "manual",
        cancel_event: Optional[threading.Event] = None,
        conversation_id: Optional[str] = None,
    ) -> Iterator[StreamEvent]:
        """Execute a full conversation turn with routing, streaming, and fallback.

        Yields:
            StreamEvent instances for UI consumption and logging.
        """
        start_time = time.time()
        decision: Optional[RoutingDecision] = None
        candidates_to_try: List[Candidate] = []

        if candidate is not None:
            # Candidate explicitly pinned by caller
            candidates_to_try = [candidate]
            decision = RoutingDecision(
                chosen_candidate=candidate,
                fallback_chain=[],
                strategy_name="manual",
                reason=f"Manually selected endpoint '{candidate.endpoint_id}'.",
                request_features={"input_tokens_est": estimate_request_tokens(request)},
            )
        elif self.router is not None:
            # Route via strategy
            decision = self.router.route(request=request, strategy_name=strategy_name)
            candidates_to_try = [decision.chosen_candidate] + list(decision.fallback_chain)
        else:
            # Default fallback: pick first available candidate
            all_cands = self.registry.candidates()
            if not all_cands:
                raise RoutingError("No enabled candidates available in registry.")
            first_cand = all_cands[0]
            candidates_to_try = [first_cand] + all_cands[1:]
            decision = RoutingDecision(
                chosen_candidate=first_cand,
                fallback_chain=all_cands[1:],
                strategy_name=strategy_name,
                reason=f"Default selection of endpoint '{first_cand.endpoint_id}'.",
                request_features={"input_tokens_est": estimate_request_tokens(request)},
            )

        # Emit initial ROUTED event
        yield StreamEvent(
            type=StreamEventType.ROUTED,
            data={
                "candidate": decision.chosen_candidate,
                "strategy": decision.strategy_name,
                "reason": decision.reason,
                "decision_id": decision.decision_id,
            },
        )

        last_error: Optional[ProviderError] = None
        accumulated_text = ""
        accumulated_reasoning = ""
        final_usage: Optional[Usage] = None
        successful_candidate: Optional[Candidate] = None
        time_to_first_token: Optional[float] = None

        for idx, cand in enumerate(candidates_to_try):
            if cancel_event and cancel_event.is_set():
                return

            if idx > 0:
                # Emit FALLBACK event before trying next candidate
                yield StreamEvent(
                    type=StreamEventType.FALLBACK,
                    data={
                        "from_candidate": candidates_to_try[idx - 1],
                        "to_candidate": cand,
                        "error": str(last_error),
                    },
                )

            try:
                adapter = get_adapter(cand.protocol)
                stream_iter = adapter.stream_chat(
                    request=request,
                    candidate=cand,
                    cancel_event=cancel_event,
                )

                has_started_output = False
                for event in stream_iter:
                    if cancel_event and cancel_event.is_set():
                        return

                    if event.type == StreamEventType.TEXT_DELTA and event.text:
                        if not has_started_output:
                            has_started_output = True
                            time_to_first_token = time.time() - start_time
                        accumulated_text += event.text
                    elif event.type == StreamEventType.REASONING_DELTA and event.reasoning:
                        accumulated_reasoning += event.reasoning
                    elif event.type == StreamEventType.USAGE and event.usage:
                        final_usage = event.usage

                    yield event

                successful_candidate = cand
                break  # Completed successfully

            except ProviderError as exc:
                last_error = exc
                # If output already started streaming, do not silently failover
                if accumulated_text:
                    yield StreamEvent(
                        type=StreamEventType.ERROR,
                        data={
                            "error": str(exc),
                            "category": exc.category,
                            "candidate": cand,
                            "partial_text": accumulated_text,
                        },
                    )
                    return

                # Check if this error should skip siblings of the same model
                if exc.should_skip_model_siblings:
                    # Filter out remaining endpoints belonging to the same model
                    candidates_to_try = [
                        c for c in candidates_to_try[idx + 1 :] if c.model_id != cand.model_id
                    ]
                continue

            except Exception as exc:
                last_error = ProviderError(
                    message=f"Unexpected error: {exc}",
                    category="unknown",
                    provider_id=cand.provider_id,
                    raw_error=exc,
                )
                if accumulated_text:
                    yield StreamEvent(
                        type=StreamEventType.ERROR,
                        data={
                            "error": str(last_error),
                            "category": "unknown",
                            "candidate": cand,
                        },
                    )
                    return
                continue

        total_latency = time.time() - start_time

        if successful_candidate is None:
            # All candidate attempts failed
            yield StreamEvent(
                type=StreamEventType.ERROR,
                data={
                    "error": str(last_error or "All candidates failed"),
                    "category": last_error.category if last_error else "unknown",
                },
            )
            return

        # Ensure usage is computed
        if final_usage is None:
            final_usage = Usage(
                input_tokens=estimate_request_tokens(request),
                output_tokens=max(1, len(accumulated_text) // 4),
                estimated=True,
            )

        cost_usd = calculate_cost(
            usage=final_usage,
            price_in_per_mtok=successful_candidate.price_in_per_mtok,
            price_out_per_mtok=successful_candidate.price_out_per_mtok,
        )

        # Log decision & usage in storage if available
        if self.storage is not None and decision is not None:
            self.storage.record_routing_log(
                decision=decision,
                chosen_candidate=successful_candidate,
                usage=final_usage,
                cost_usd=cost_usd,
                latency_ms=int(total_latency * 1000),
                ttft_ms=int((time_to_first_token or 0) * 1000),
                conversation_id=conversation_id,
            )

        yield StreamEvent(
            type=StreamEventType.DONE,
            usage=final_usage,
            finish_reason="stop",
            data={
                "candidate": successful_candidate,
                "cost_usd": cost_usd,
                "latency_sec": round(total_latency, 3),
                "ttft_sec": round(time_to_first_token or 0.0, 3),
            },
        )
