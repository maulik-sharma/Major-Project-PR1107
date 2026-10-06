import json
import re
import threading
import time
from typing import Any, Dict, Iterator, List, Optional

from modelmesh.core.cost import calculate_cost, estimate_request_tokens
from modelmesh.core.errors import ProviderError, RoutingError
from modelmesh.core.providers.base import get_adapter
from modelmesh.core.registry import ModelRegistry
from modelmesh.core.skills import SkillLoader, get_load_skill_tool
from modelmesh.core.tools.registry import ToolExecutionResult, ToolRegistry
from modelmesh.core.types import (
    Candidate,
    ChatRequest,
    Message,
    RoutingDecision,
    StreamEvent,
    StreamEventType,
    TextPart,
    ToolCall,
    Usage,
)


class ChatEngine:
    """Core engine driving conversation turns, provider dispatch, tool loops, and failover."""

    def __init__(
        self,
        registry: ModelRegistry,
        router: Optional[Any] = None,
        storage: Optional[Any] = None,
        tool_registry: Optional[ToolRegistry] = None,
        skill_loader: Optional[SkillLoader] = None,
    ) -> None:
        self.registry = registry
        self.router = router
        self.storage = storage
        self.tool_registry = tool_registry
        self.skill_loader = skill_loader

    def run_turn(
        self,
        request: ChatRequest,
        candidate: Optional[Candidate] = None,
        strategy_name: str = "manual",
        cancel_event: Optional[threading.Event] = None,
        conversation_id: Optional[str] = None,
        pinned_model_id: Optional[str] = None,
        pinned_endpoint_id: Optional[str] = None,
        seed: Optional[int] = None,
    ) -> Iterator[StreamEvent]:
        """Execute a full conversation turn with routing, streaming, tool loop, and fallback.

        Yields:
            StreamEvent instances for UI consumption and logging.
        """
        start_time = time.time()
        decision: Optional[RoutingDecision] = None
        candidates_to_try: List[Candidate] = []

        # 1. Progressive Disclosure: Skills injection into system prompt
        effective_system_prompt = request.system_prompt
        effective_tools = list(request.tools)

        if self.skill_loader is not None:
            if self.tool_registry is not None and not self.tool_registry.has_tool("load_skill"):
                spec, handler = get_load_skill_tool(self.skill_loader)
                self.tool_registry.register(
                    name=spec.name,
                    description=spec.description,
                    parameters=spec.parameters,
                    func=handler,
                )

            skills_index = self.skill_loader.format_system_prompt_index()
            if skills_index:
                if effective_system_prompt:
                    effective_system_prompt = f"{effective_system_prompt}\n\n{skills_index}"
                else:
                    effective_system_prompt = skills_index

            # Check for explicit @<skill_name> mentions in the last message
            if request.messages:
                last_msg_text = request.messages[-1].text_content()
                for skill in self.skill_loader.list_skills(only_enabled=True):
                    pattern = rf"@\b{re.escape(skill.name)}\b"
                    if re.search(pattern, last_msg_text, re.IGNORECASE):
                        skill_instructions = f"Skill Instructions for '{skill.name}':\n{skill.body}"
                        if skill.resources:
                            res_list = ", ".join(skill.resources.keys())
                            skill_instructions += f"\n(Sub-resources: {res_list}. Use 'load_skill' to inspect.)"
                        if effective_system_prompt:
                            effective_system_prompt = f"{effective_system_prompt}\n\n{skill_instructions}"
                        else:
                            effective_system_prompt = skill_instructions

            if effective_tools and self.tool_registry is not None:
                if not any(t.name == "load_skill" for t in effective_tools):
                    spec = self.tool_registry.get_spec("load_skill")
                    if spec:
                        effective_tools.append(spec)

        current_messages = list(request.messages)
        current_request = ChatRequest(
            messages=current_messages,
            system_prompt=effective_system_prompt,
            tools=effective_tools,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            extra_params=request.extra_params,
            required_capabilities=request.required_capabilities,
        )

        if candidate is not None:
            # Candidate explicitly pinned by caller
            candidates_to_try = [candidate]
            decision = RoutingDecision(
                chosen_candidate=candidate,
                fallback_chain=[],
                strategy_name="manual",
                reason=f"Manually selected endpoint '{candidate.endpoint_id}'.",
                request_features={"input_tokens_est": estimate_request_tokens(current_request)},
            )
        elif self.router is not None:
            # Route via strategy
            decision = self.router.route(
                request=current_request,
                strategy_name=strategy_name,
                pinned_model_id=pinned_model_id,
                pinned_endpoint_id=pinned_endpoint_id,
                seed=seed,
            )
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
                request_features={"input_tokens_est": estimate_request_tokens(current_request)},
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
        last_failed_cand: Optional[Candidate] = None
        successful_candidate: Optional[Candidate] = None
        time_to_first_token: Optional[float] = None

        total_input_tokens = 0
        total_output_tokens = 0
        total_cached_tokens = 0
        total_reasoning_tokens = 0
        is_usage_estimated = False
        accumulated_turn_text = ""

        candidate_queue: List[Candidate] = list(candidates_to_try)

        while candidate_queue:
            if cancel_event and cancel_event.is_set():
                return

            cand = candidate_queue.pop(0)

            if last_failed_cand is not None:
                # Emit FALLBACK event before trying next candidate
                yield StreamEvent(
                    type=StreamEventType.FALLBACK,
                    data={
                        "from_candidate": last_failed_cand,
                        "to_candidate": cand,
                        "error": str(last_error),
                    },
                )

            max_tool_iterations = 8
            iteration = 0
            has_started_output = False
            candidate_failed = False

            while iteration < max_tool_iterations:
                if cancel_event and cancel_event.is_set():
                    return

                accumulated_text_iter = ""
                accumulated_reasoning_iter = ""
                tool_calls_this_iter: List[ToolCall] = []
                iter_usage: Optional[Usage] = None

                try:
                    adapter = get_adapter(cand.protocol)
                    stream_iter = adapter.stream_chat(
                        request=current_request,
                        candidate=cand,
                        cancel_event=cancel_event,
                    )

                    for event in stream_iter:
                        if cancel_event and cancel_event.is_set():
                            return

                        if event.type == StreamEventType.TEXT_DELTA and event.text:
                            if not has_started_output:
                                has_started_output = True
                                time_to_first_token = time.time() - start_time
                            accumulated_text_iter += event.text
                            accumulated_turn_text += event.text
                            yield event
                        elif event.type == StreamEventType.REASONING_DELTA and event.reasoning:
                            accumulated_reasoning_iter += event.reasoning
                            yield event
                        elif event.type == StreamEventType.USAGE and event.usage:
                            iter_usage = event.usage
                        elif event.type == StreamEventType.TOOL_CALL and event.tool_call:
                            tool_calls_this_iter.append(event.tool_call)
                            yield event

                except ProviderError as exc:
                    last_error = exc
                    last_failed_cand = cand
                    candidate_failed = True
                    if self.router is not None and hasattr(self.router, "health_tracker") and self.router.health_tracker:
                        self.router.health_tracker.record_failure(
                            endpoint_id=cand.endpoint_id,
                            model_id=cand.model_id,
                            reason=str(exc),
                        )

                    # If output already started streaming or iteration > 0, do not silently failover
                    if has_started_output or iteration > 0:
                        yield StreamEvent(
                            type=StreamEventType.ERROR,
                            data={
                                "error": str(exc),
                                "category": exc.category,
                                "candidate": cand,
                                "partial_text": accumulated_turn_text,
                            },
                        )
                        return

                    if exc.should_skip_model_siblings:
                        candidate_queue = [
                            c for c in candidate_queue if c.model_id != cand.model_id
                        ]
                    break

                except Exception as exc:
                    last_error = ProviderError(
                        message=f"Unexpected error: {exc}",
                        category="unknown",
                        provider_id=cand.provider_id,
                        raw_error=exc,
                    )
                    last_failed_cand = cand
                    candidate_failed = True
                    if self.router is not None and hasattr(self.router, "health_tracker") and self.router.health_tracker:
                        self.router.health_tracker.record_failure(
                            endpoint_id=cand.endpoint_id,
                            model_id=cand.model_id,
                            reason=str(last_error),
                        )

                    if has_started_output or iteration > 0:
                        yield StreamEvent(
                            type=StreamEventType.ERROR,
                            data={
                                "error": str(last_error),
                                "category": "unknown",
                                "candidate": cand,
                            },
                        )
                        return
                    break

                # Accumulate usage tokens
                if iter_usage:
                    total_input_tokens += iter_usage.input_tokens
                    total_output_tokens += iter_usage.output_tokens
                    total_cached_tokens += iter_usage.cached_tokens
                    total_reasoning_tokens += iter_usage.reasoning_tokens
                    if iter_usage.estimated:
                        is_usage_estimated = True
                else:
                    est_in = estimate_request_tokens(current_request)
                    est_out = max(1, len(accumulated_text_iter) // 4)
                    total_input_tokens += est_in
                    total_output_tokens += est_out
                    is_usage_estimated = True

                # Check if model requested tool calls
                if tool_calls_this_iter:
                    # Append assistant message with tool calls
                    assistant_msg = Message(
                        role="assistant",
                        parts=[TextPart(text=accumulated_text_iter)] if accumulated_text_iter else [],
                        tool_calls=tool_calls_this_iter,
                        reasoning=accumulated_reasoning_iter if accumulated_reasoning_iter else None,
                    )
                    current_messages.append(assistant_msg)

                    # Execute each tool call and collect results
                    for tc in tool_calls_this_iter:
                        if cancel_event and cancel_event.is_set():
                            return

                        yield StreamEvent(
                            type=StreamEventType.TOOL_START,
                            tool_call=tc,
                            data={"id": tc.id, "name": tc.name, "arguments": tc.arguments},
                        )

                        if self.tool_registry is not None:
                            result = self.tool_registry.execute(tc.name, tc.arguments)
                        else:
                            result = ToolExecutionResult(
                                tool_name=tc.name,
                                arguments=tc.arguments,
                                output=None,
                                success=False,
                                error="Tool registry not available.",
                                duration_ms=0,
                            )

                        yield StreamEvent(
                            type=StreamEventType.TOOL_RESULT,
                            tool_call=tc,
                            data={
                                "id": tc.id,
                                "name": tc.name,
                                "result": result.output,
                                "error": result.error,
                                "success": result.success,
                                "duration_ms": result.duration_ms,
                            },
                        )

                        if result.success:
                            res_str = json.dumps(result.output) if isinstance(result.output, (dict, list)) else str(result.output)
                        else:
                            res_str = f"Error: {result.error}"

                        current_messages.append(
                            Message(
                                role="tool",
                                tool_call_id=tc.id,
                                parts=[TextPart(text=res_str)],
                            )
                        )

                    # Prepare request for next tool loop iteration
                    current_request = ChatRequest(
                        messages=list(current_messages),
                        system_prompt=effective_system_prompt,
                        tools=effective_tools,
                        temperature=request.temperature,
                        max_tokens=request.max_tokens,
                        extra_params=request.extra_params,
                        required_capabilities=request.required_capabilities,
                    )
                    iteration += 1
                    if iteration >= max_tool_iterations:
                        successful_candidate = cand
                        break
                else:
                    # No tool calls: final answer reached
                    successful_candidate = cand
                    break

            if candidate_failed:
                continue

            if successful_candidate is not None:
                break

        total_latency = time.time() - start_time

        if successful_candidate is None:
            yield StreamEvent(
                type=StreamEventType.ERROR,
                data={
                    "error": str(last_error or "All candidates failed"),
                    "category": last_error.category if last_error else "unknown",
                },
            )
            return

        if self.router is not None and hasattr(self.router, "health_tracker") and self.router.health_tracker:
            self.router.health_tracker.record_success(
                endpoint_id=successful_candidate.endpoint_id,
                model_id=successful_candidate.model_id,
            )

        final_usage = Usage(
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
            cached_tokens=total_cached_tokens,
            reasoning_tokens=total_reasoning_tokens,
            estimated=is_usage_estimated,
        )

        cost_usd = calculate_cost(
            usage=final_usage,
            price_in_per_mtok=successful_candidate.price_in_per_mtok,
            price_out_per_mtok=successful_candidate.price_out_per_mtok,
        )

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
            type=StreamEventType.USAGE,
            usage=final_usage,
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
