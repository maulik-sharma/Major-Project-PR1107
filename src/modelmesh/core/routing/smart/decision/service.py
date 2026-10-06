"""DecisionService: orchestrates caching, timeouts, retries, circuit breaker, and fallbacks."""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from modelmesh.core.config.routing_config import SmartRoutingConfig
from modelmesh.core.errors import ProviderError
from modelmesh.core.routing.smart.decision.base import (
    DecisionProvider,
    DecisionRequest,
    DecisionResult,
    get_decision_provider,
)
from modelmesh.core.routing.smart.decision.cloudflare import CloudflareDecisionAdapter
from modelmesh.core.routing.smart.decision.heuristic import HeuristicDecisionProvider
from modelmesh.core.routing.smart.rubric import (
    build_rubric_questions,
    compute_rubric_hash,
)
from modelmesh.core.routing.smart.state_builder import build_decision_state
from modelmesh.core.storage import Storage
from modelmesh.core.types import Message, Usage

logger = logging.getLogger(__name__)


class CircuitBreaker:
    """Tracks consecutive provider failures and enforces a cooldown window."""

    def __init__(self, failure_threshold: int = 3, cooldown_seconds: float = 60.0) -> None:
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.consecutive_failures: int = 0
        self.last_failure_time: float = 0.0

    def is_open(self) -> bool:
        """True if the breaker is open (tripped) and cooldown has not elapsed."""
        if self.consecutive_failures >= self.failure_threshold:
            elapsed = time.time() - self.last_failure_time
            if elapsed < self.cooldown_seconds:
                return True
            # Half-open: reset to give one chance
            self.consecutive_failures = 0
        return False

    def record_success(self) -> None:
        self.consecutive_failures = 0

    def record_failure(self) -> None:
        self.consecutive_failures += 1
        self.last_failure_time = time.time()


class DecisionService:
    """High-level service coordinating decision models, cache, and fallbacks."""

    def __init__(
        self,
        config: SmartRoutingConfig,
        storage: Optional[Storage] = None,
    ) -> None:
        self.config = config
        self.storage = storage
        self._circuit_breakers: Dict[str, CircuitBreaker] = {}
        self._providers: Dict[str, DecisionProvider] = {}
        self._init_providers()

    def _init_providers(self) -> None:
        for pcfg in self.config.decision.providers:
            try:
                cls = get_decision_provider(pcfg.protocol)
                self._providers[pcfg.id] = cls()
            except Exception as exc:
                logger.warning(f"Could not initialize decision provider '{pcfg.id}': {exc}")
        if "heuristic" not in self._providers:
            self._providers["heuristic"] = HeuristicDecisionProvider()

    def _get_breaker(self, provider_id: str) -> CircuitBreaker:
        if provider_id not in self._circuit_breakers:
            self._circuit_breakers[provider_id] = CircuitBreaker()
        return self._circuit_breakers[provider_id]

    def get_decision(
        self,
        messages: List[Message],
        tools_enabled: bool = False,
        tools_count: int = 0,
        provider_override: Optional[str] = None,
    ) -> DecisionResult:
        """Obtain a decision result with cache, timeout, retries, and fallback."""
        start_time = time.perf_counter()

        # 1. Build bounded state
        state_text, state_hash, use_heuristic_only = build_decision_state(
            messages=messages,
            max_tokens=self.config.decision.max_state_tokens,
            tools_enabled=tools_enabled,
            tools_count=tools_count,
            send_prompt_text=self.config.decision.send_prompt_text,
        )

        rubric_questions = build_rubric_questions(self.config.rubric)
        rubric_hash = compute_rubric_hash(self.config.rubric)

        # 2. Privacy switch: bypass remote call if send_prompt_text is disabled
        if use_heuristic_only:
            heuristic_provider = self._providers.get("heuristic") or HeuristicDecisionProvider()
            req = DecisionRequest(
                state=state_text,
                questions=rubric_questions,
                provider_id="heuristic",
            )
            res = heuristic_provider.decide(req)
            res.source = "heuristic"
            return res

        active_id = provider_override or self.config.decision.active
        # Find active provider model name
        model_name = "clef-flash"
        for p in self.config.decision.providers:
            if p.id == active_id:
                model_name = p.model
                break

        # 3. Cache lookup
        cache_key = f"{active_id}:{model_name}:{rubric_hash}:{state_hash}"
        if self.storage is not None:
            cached = self.storage.get_decision_cache(cache_key)
            if cached and "answers" in cached:
                return DecisionResult(
                    answers=cached["answers"],
                    usage=Usage(input_tokens=0, output_tokens=0),
                    latency_ms=0.5,
                    provider_id=active_id,
                    model=model_name,
                    raw_response=cached,
                    source="cache",
                )

        # 4. Check circuit breaker
        breaker = self._get_breaker(active_id)
        if breaker.is_open():
            logger.info(f"Circuit breaker is open for decision provider '{active_id}'. Using heuristic fallback.")
            return self._fallback_heuristic(state_text, rubric_questions, active_id)

        # 5. Call active provider with 1 retry on network error
        active_provider = self._providers.get(active_id)
        if active_provider is None:
            return self._fallback_heuristic(state_text, rubric_questions, active_id)

        req = DecisionRequest(
            state=state_text,
            questions=rubric_questions,
            timeout_s=self.config.decision.timeout_s,
            model=model_name,
            provider_id=active_id,
        )

        max_attempts = 2
        for attempt in range(max_attempts):
            try:
                res = active_provider.decide(req)
                breaker.record_success()

                # Save to cache
                if self.storage is not None:
                    self.storage.save_decision_cache(
                        key=cache_key,
                        decision_provider=active_id,
                        rubric_version=self.config.rubric.version,
                        state_hash=state_hash,
                        answers=res.answers,
                        router_latency_ms=int(res.latency_ms),
                    )
                res.source = "clef"
                return res

            except ProviderError as exc:
                if exc.category == "network" and attempt == 0:
                    time.sleep(0.1)
                    continue  # Retry once for network glitch
                breaker.record_failure()
                logger.warning(f"Decision provider '{active_id}' failed: {exc}. Falling back to heuristic.")
                break
            except Exception as exc:
                breaker.record_failure()
                logger.warning(f"Unexpected error in decision provider '{active_id}': {exc}. Falling back to heuristic.")
                break

        return self._fallback_heuristic(state_text, rubric_questions, active_id)

    def _fallback_heuristic(
        self,
        state_text: str,
        rubric_questions: Dict[str, Dict[str, Any]],
        provider_id: str,
    ) -> DecisionResult:
        """Safely execute heuristic fallback without failing the turn (Rule 17)."""
        heuristic_provider = self._providers.get("heuristic") or HeuristicDecisionProvider()
        req = DecisionRequest(
            state=state_text,
            questions=rubric_questions,
            provider_id="heuristic",
        )
        res = heuristic_provider.decide(req)
        res.source = "heuristic_fallback"
        res.provider_id = provider_id
        return res

    def evaluate(
        self,
        request: Any,
        provider_override: Optional[str] = None,
    ) -> DecisionResult:
        """Convenience wrapper accepting a ChatRequest."""
        messages = getattr(request, "messages", [])
        tools = getattr(request, "tools", None)
        return self.get_decision(
            messages=messages,
            tools_enabled=bool(tools),
            tools_count=len(tools) if tools else 0,
            provider_override=provider_override,
        )

