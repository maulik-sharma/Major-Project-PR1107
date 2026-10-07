"""Worker thread driving synchronous engine turns and dispatching signals to the UI."""

from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QThread, pyqtSignal

from modelmesh.core.engine import ChatEngine
from modelmesh.core.types import (
    Candidate,
    ChatRequest,
    ImagePart,
    Message,
    StreamEvent,
    StreamEventType,
    TextPart,
)


class ChatWorker(QThread):
    """QThread running ChatEngine.run_turn synchronously off the UI thread."""

    started_turn = pyqtSignal(dict)
    routed = pyqtSignal(dict)
    fallback = pyqtSignal(dict)
    text_delta = pyqtSignal(str)
    reasoning_delta = pyqtSignal(str)
    tool_call = pyqtSignal(dict)
    tool_start = pyqtSignal(dict)
    tool_result = pyqtSignal(dict)
    usage = pyqtSignal(dict)
    finished_turn = pyqtSignal(dict)
    error_occurred = pyqtSignal(dict)

    def __init__(
        self,
        engine: ChatEngine,
        request: ChatRequest,
        strategy_name: str = "manual",
        pinned_model_id: Optional[str] = None,
        pinned_endpoint_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        parent: Optional[Any] = None,
    ) -> None:
        super().__init__(parent)
        self.engine = engine
        self.request = request
        self.strategy_name = strategy_name
        self.pinned_model_id = pinned_model_id
        self.pinned_endpoint_id = pinned_endpoint_id
        self.conversation_id = conversation_id
        self.cancel_event = threading.Event()

    def stop(self) -> None:
        """Signal the running turn to cancel immediately."""
        self.cancel_event.set()

    def run(self) -> None:
        """Execute turn generator and emit signals with plain data payloads."""
        self.started_turn.emit({
            "conversation_id": self.conversation_id,
            "strategy": self.strategy_name,
        })

        try:
            stream_iter = self.engine.run_turn(
                request=self.request,
                strategy_name=self.strategy_name,
                cancel_event=self.cancel_event,
                conversation_id=self.conversation_id,
                pinned_model_id=self.pinned_model_id,
                pinned_endpoint_id=self.pinned_endpoint_id,
            )

            for event in stream_iter:
                if self.cancel_event.is_set():
                    break

                if event.type == StreamEventType.ROUTED:
                    cand = event.data.get("candidate")
                    self.routed.emit({
                        "model_id": cand.model_id if cand else "",
                        "endpoint_id": cand.endpoint_id if cand else "",
                        "provider_id": cand.provider_id if cand else "",
                        "strategy": event.data.get("strategy", self.strategy_name),
                        "reason": event.data.get("reason", ""),
                        "decision_id": event.data.get("decision_id", ""),
                        "metadata": event.data.get("metadata", {}),
                    })

                elif event.type == StreamEventType.FALLBACK:
                    from_c = event.data.get("from_candidate")
                    to_c = event.data.get("to_candidate")
                    self.fallback.emit({
                        "from_endpoint_id": from_c.endpoint_id if from_c else "",
                        "to_endpoint_id": to_c.endpoint_id if to_c else "",
                        "error": event.data.get("error", ""),
                    })

                elif event.type == StreamEventType.TEXT_DELTA and event.text:
                    self.text_delta.emit(event.text)

                elif event.type == StreamEventType.REASONING_DELTA and event.reasoning:
                    self.reasoning_delta.emit(event.reasoning)

                elif event.type == StreamEventType.TOOL_CALL and event.tool_call:
                    self.tool_call.emit({
                        "id": event.tool_call.id,
                        "name": event.tool_call.name,
                        "arguments": event.tool_call.arguments,
                    })

                elif event.type == StreamEventType.TOOL_START and event.data:
                    self.tool_start.emit(event.data)

                elif event.type == StreamEventType.TOOL_RESULT and event.data:
                    self.tool_result.emit(event.data)

                elif event.type == StreamEventType.USAGE and event.usage:
                    self.usage.emit({
                        "input_tokens": event.usage.input_tokens,
                        "output_tokens": event.usage.output_tokens,
                        "cached_tokens": event.usage.cached_tokens,
                        "reasoning_tokens": event.usage.reasoning_tokens,
                        "estimated": event.usage.estimated,
                    })

                elif event.type == StreamEventType.DONE:
                    cand = event.data.get("candidate") if event.data else None
                    self.finished_turn.emit({
                        "model_id": cand.model_id if cand else "",
                        "endpoint_id": cand.endpoint_id if cand else "",
                        "provider_id": cand.provider_id if cand else "",
                        "cost_usd": event.data.get("cost_usd", 0.0) if event.data else 0.0,
                        "latency_sec": event.data.get("latency_sec", 0.0) if event.data else 0.0,
                        "tokens_in": event.usage.input_tokens if event.usage else 0,
                        "tokens_out": event.usage.output_tokens if event.usage else 0,
                        "strategy": event.data.get("strategy", self.strategy_name) if event.data else self.strategy_name,
                        "reason": event.data.get("reason", "") if event.data else "",
                        "decision_id": event.data.get("decision_id", "") if event.data else "",
                        "metadata": event.data.get("metadata", {}) if event.data else {},
                    })

                elif event.type == StreamEventType.ERROR:
                    self.error_occurred.emit({
                        "error": event.data.get("error", "Unknown error"),
                        "category": event.data.get("category", "unknown"),
                    })

        except Exception as exc:
            self.error_occurred.emit({
                "error": str(exc),
                "category": "unknown",
            })


class ScoresRefreshWorker(QThread):
    """QThread fetching fresh score snapshot from Artificial Analysis."""

    started_refresh = pyqtSignal()
    finished_refresh = pyqtSignal(dict)
    error_occurred = pyqtSignal(str)

    def __init__(
        self,
        api_key: Optional[str] = None,
        storage: Optional[Any] = None,
        parent: Optional[Any] = None,
    ) -> None:
        super().__init__(parent)
        self.api_key = api_key
        self.storage = storage

    def run(self) -> None:
        self.started_refresh.emit()
        try:
            from modelmesh.core.scores.aa_client import ArtificialAnalysisClient
            from modelmesh.core.scores.snapshots import ScoreStore
            from modelmesh.core.storage import get_default_storage

            client = ArtificialAnalysisClient(api_key=self.api_key)
            snapshot = client.fetch_snapshot()

            storage = self.storage or get_default_storage()
            store = ScoreStore(storage)
            store.save_snapshot(snapshot)

            self.finished_refresh.emit({
                "snapshot_id": snapshot.id,
                "models_count": len(snapshot.models_by_slug),
                "index_version": snapshot.index_version,
                "rate_limit_remaining": snapshot.rate_limit_remaining,
                "fetched_at": snapshot.fetched_at,
            })
        except Exception as exc:
            self.error_occurred.emit(str(exc))


class DecisionTestWorker(QThread):
    """QThread evaluating a test prompt against the DecisionService off the UI thread."""

    test_completed = pyqtSignal(dict)
    error_occurred = pyqtSignal(str)

    def __init__(
        self,
        prompt_text: str,
        provider_id: Optional[str] = None,
        storage: Optional[Any] = None,
        parent: Optional[Any] = None,
    ) -> None:
        super().__init__(parent)
        self.prompt_text = prompt_text
        self.provider_id = provider_id
        self.storage = storage

    def run(self) -> None:
        try:
            from modelmesh.core.config.routing_config import load_routing_config
            from modelmesh.core.routing.smart.decision.service import DecisionService
            from modelmesh.core.storage import get_default_storage
            from modelmesh.core.types import ChatRequest, Message, TextPart

            config = load_routing_config()
            storage = self.storage or get_default_storage()
            service = DecisionService(config=config, storage=storage)

            req = ChatRequest(
                messages=[Message(role="user", parts=[TextPart(text=self.prompt_text)])]
            )

            result = service.evaluate(
                request=req,
                provider_override=self.provider_id,
            )

            self.test_completed.emit({
                "source": result.source,
                "provider_id": result.provider_id,
                "model": result.model,
                "latency_ms": result.latency_ms,
                "cached": result.source == "cache",
                "answers": result.answers,
                "usage": {
                    "input_tokens": result.usage.input_tokens,
                    "output_tokens": result.usage.output_tokens,
                },
            })
        except Exception as exc:
            self.error_occurred.emit(str(exc))

