"""DecisionService: orchestrates caching, circuit breaking, validation, and fallbacks.

Rule 17: ``get_decision`` never raises. Any failure on the way to a remote
decision (state building, cache, breaker, network, invalid output) falls
back to the local heuristic with ``source="heuristic_fallback"``.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

from modelmesh.core.config.routing_config import DecisionProviderConfig, SmartRoutingConfig
from modelmesh.core.routing.smart.decision.base import (
    DecisionProvider,
    DecisionRequest,
    DecisionResult,
    get_decision_provider,
)
from modelmesh.core.routing.smart.decision.heuristic import HeuristicDecisionProvider
from modelmesh.core.routing.smart.decision.validation import validate_answers
from modelmesh.core.routing.smart.rubric import (
    build_rubric_questions,
    compute_rubric_hash,
)
from modelmesh.core.routing.smart.state_builder import build_decision_state, latest_user_text
from modelmesh.core.storage import Storage
from modelmesh.core.types import ImagePart, Message, Usage

logger = logging.getLogger(__name__)

# Importing registers the adapters with the decision-provider registry.
from modelmesh.core.routing.smart.decision import cloudflare as _cloudflare  # noqa: E402,F401
from modelmesh.core.routing.smart.decision import mock as _mock  # noqa: E402,F401


class CircuitBreaker:
    """Thread-safe breaker: opens after repeated failures, then allows one probe."""

    def __init__(self, failure_threshold: int = 3, cooldown_seconds: float = 60.0) -> None:
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._failures = 0
        self._opened_at: Optional[float] = None
        self._probing = False
        self._lock = threading.Lock()

    def allow_request(self) -> bool:
        """Return True if a call may go out (closed, or the single half-open probe)."""
        with self._lock:
            if self._opened_at is None:
                return True
            if time.time() - self._opened_at < self.cooldown_seconds or self._probing:
                return False
            self._probing = True
            return True

    def is_open(self) -> bool:
        """True while the breaker is open and its cooldown has not elapsed."""
        with self._lock:
            return self._opened_at is not None and time.time() - self._opened_at < self.cooldown_seconds

    def record_success(self) -> None:
        """Close the breaker."""
        with self._lock:
            self._failures = 0
            self._opened_at = None
            self._probing = False

    def record_failure(self) -> None:
        """Count a failure; a failed half-open probe re-opens the breaker immediately."""
        with self._lock:
            self._failures += 1
            if self._probing or self._failures >= self.failure_threshold:
                self._opened_at = time.time()
            self._probing = False


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
        self._provider_configs: Dict[str, DecisionProviderConfig] = {}
        self._heuristic = HeuristicDecisionProvider()
        self._init_providers()

    def _init_providers(self) -> None:
        for pcfg in self.config.decision.providers:
            self._provider_configs[pcfg.id] = pcfg
            try:
                cls = get_decision_provider(pcfg.protocol)
                self._providers[pcfg.id] = cls.from_config(pcfg)
            except Exception as exc:
                logger.warning("Could not initialize decision provider '%s': %s", pcfg.id, exc)

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
        """Obtain a decision. Never raises: falls back to the heuristic on any failure."""
        active_id = provider_override or self.config.decision.active
        try:
            return self._get_decision(messages, tools_enabled, tools_count, active_id)
        except Exception as exc:
            logger.warning("Decision via '%s' failed: %s. Using heuristic fallback.", active_id, exc)
            return self._fallback(messages, tools_enabled, tools_count, active_id, str(exc))

    def _get_decision(
        self,
        messages: List[Message],
        tools_enabled: bool,
        tools_count: int,
        active_id: str,
    ) -> DecisionResult:
        provider = self._providers.get(active_id)
        if provider is None:
            raise LookupError(f"Decision provider '{active_id}' is not configured")

        # Local providers (heuristic, mock) need no cache, breaker, or privacy gate.
        if not provider.remote:
            return provider.decide(self._local_request(messages, tools_enabled, tools_count, active_id))

        # Privacy switch (Rule 19): no prompt text ever goes to a remote provider.
        if not self.config.decision.send_prompt_text:
            res = self._heuristic.decide(self._local_request(messages, tools_enabled, tools_count, "heuristic"))
            res.source = "heuristic"
            return res

        state_text, state_hash = build_decision_state(
            messages=messages,
            max_tokens=self.config.decision.max_state_tokens,
            tools_enabled=tools_enabled,
            tools_count=tools_count,
        )
        rubric_questions = build_rubric_questions(self.config.rubric)
        rubric_hash = compute_rubric_hash(self.config.rubric)
        model_name = self._provider_configs[active_id].model
        cache_key = f"{active_id}:{model_name}:{rubric_hash}:{state_hash}"

        cached = self._read_cache(cache_key)
        if cached is not None:
            return DecisionResult(
                answers=cached,
                source="cache",
                usage=Usage(input_tokens=0, output_tokens=0),
                latency_ms=0.5,
                provider_id=active_id,
                model=model_name,
            )

        breaker = self._get_breaker(active_id)
        if not breaker.allow_request():
            raise RuntimeError(f"Circuit breaker open for '{active_id}'")

        req = DecisionRequest(
            state=state_text,
            questions=rubric_questions,
            timeout_s=self.config.decision.timeout_s,
            model=model_name,
            provider_id=active_id,
        )
        try:
            res = provider.decide(req)
            res.answers = validate_answers(res.answers, self.config.rubric)
        except Exception:
            breaker.record_failure()
            raise
        breaker.record_success()

        self._write_cache(cache_key, active_id, state_hash, res)
        return res

    def _local_request(
        self,
        messages: List[Message],
        tools_enabled: bool,
        tools_count: int,
        provider_id: str,
    ) -> DecisionRequest:
        """Build a request for an on-device provider: it may read the real latest message."""
        has_images = any(isinstance(p, ImagePart) for m in messages for p in m.parts)
        return DecisionRequest(
            state="",
            questions=build_rubric_questions(self.config.rubric),
            provider_id=provider_id,
            latest_text=latest_user_text(messages),
            context={
                "tools_enabled": tools_enabled,
                "tools_count": tools_count,
                "history_messages": max(0, len(messages) - 1),
                "has_images": has_images,
            },
        )

    def _read_cache(self, key: str) -> Optional[Dict[str, Any]]:
        """Return validated cached answers, or None on miss or any cache problem."""
        if self.storage is None:
            return None
        try:
            cached = self.storage.get_decision_cache(key)
            if cached and "answers" in cached:
                return validate_answers(cached["answers"], self.config.rubric)
        except Exception as exc:
            logger.warning("Decision cache read failed: %s", exc)
        return None

    def _write_cache(self, key: str, provider_id: str, state_hash: str, res: DecisionResult) -> None:
        """Best-effort cache write; a storage error never discards a good decision."""
        if self.storage is None:
            return
        try:
            self.storage.save_decision_cache(
                key=key,
                decision_provider=provider_id,
                rubric_version=self.config.rubric.version,
                state_hash=state_hash,
                answers=res.answers,
                router_latency_ms=int(res.latency_ms),
            )
        except Exception as exc:
            logger.warning("Decision cache write failed: %s", exc)

    def _fallback(
        self,
        messages: List[Message],
        tools_enabled: bool,
        tools_count: int,
        provider_id: str,
        error: str,
    ) -> DecisionResult:
        """Heuristic fallback (Rule 17). Uses neutral answers if even the heuristic fails."""
        try:
            res = self._heuristic.decide(self._local_request(messages, tools_enabled, tools_count, "heuristic"))
        except Exception as exc:
            logger.error("Heuristic fallback failed: %s", exc)
            res = DecisionResult(answers=_neutral_answers(), source="heuristic_fallback", model="heuristic")
        res.source = "heuristic_fallback"
        res.provider_id = provider_id
        res.error = error
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


def _neutral_answers() -> Dict[str, Any]:
    """Middle-of-the-road answers used only if the heuristic itself crashes."""
    return {
        "task": {"type": "choice", "choice": "chat_general", "confidence": 0.5},
        "difficulty": {"type": "score", "score": 2.0, "confidence": 0.5},
        "precision": {"type": "score", "score": 1.5, "confidence": 0.5},
        "larger_model_benefit": {"type": "score", "score": 1.5, "confidence": 0.5},
    }
