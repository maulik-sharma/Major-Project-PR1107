"""Owns the single active chat turn: worker lifecycle, live rendering, and persistence.

Each turn remembers its own conversation and assistant message id, so signals
that arrive after the user switched chats are saved to the right conversation
and never painted into the wrong one.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QObject, pyqtSignal

from modelmesh.core.formatting import extract_reasoning_and_content
from modelmesh.core.types import ChatRequest, Message
from modelmesh.ui.workers import ChatWorker

logger = logging.getLogger(__name__)


@dataclass
class _Turn:
    worker: ChatWorker
    conversation_id: str
    msg_id: str
    visible: bool = True  # False once the user switched away from its conversation
    text: str = ""
    reasoning: str = ""
    routed: Dict[str, Any] = field(default_factory=dict)
    tool_events: List[Dict[str, Any]] = field(default_factory=list)
    fallbacks: List[Dict[str, Any]] = field(default_factory=list)
    outcome: Optional[str] = None  # "done" | "error"; None means stopped/cancelled


class TurnController(QObject):
    """Starts, streams, stops, and saves chat turns, one at a time."""

    busy_changed = pyqtSignal(bool)
    status = pyqtSignal(str)
    cost_added = pyqtSignal(float)

    def __init__(self, engine: Any, storage: Any, chat_view: Any, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.engine = engine
        self.storage = storage
        self.chat_view = chat_view
        self._turn: Optional[_Turn] = None
        self._turns: Dict[Any, _Turn] = {}  # worker -> turn, until its thread exits

    @property
    def is_busy(self) -> bool:
        """True from start() until the worker thread has fully exited."""
        return self._turn is not None

    @property
    def active_conversation_id(self) -> Optional[str]:
        return self._turn.conversation_id if self._turn else None

    def start(
        self,
        request: ChatRequest,
        conversation_id: str,
        strategy_name: str,
        pinned_model_id: Optional[str] = None,
        pinned_endpoint_id: Optional[str] = None,
        profile: Optional[str] = None,
    ) -> bool:
        """Start a turn. Returns False (and does nothing) if one is already running."""
        if self._turn is not None:
            self.status.emit("Please wait for the current reply to finish, or press Stop.")
            return False

        worker = ChatWorker(
            engine=self.engine,
            request=request,
            strategy_name=strategy_name,
            pinned_model_id=pinned_model_id,
            pinned_endpoint_id=pinned_endpoint_id,
            conversation_id=conversation_id,
            profile=profile,
        )
        turn = _Turn(worker=worker, conversation_id=conversation_id, msg_id=str(uuid.uuid4()))
        self._turn = turn

        # Bound methods of this GUI-thread QObject: Qt queues every call onto the GUI thread.
        self._turns[worker] = turn
        worker.routed.connect(self._slot_routed)
        worker.fallback.connect(self._slot_fallback)
        worker.text_delta.connect(self._slot_text)
        worker.reasoning_delta.connect(self._slot_reasoning)
        worker.tool_start.connect(self._slot_tool_start)
        worker.tool_result.connect(self._slot_tool_result)
        worker.finished_turn.connect(self._slot_done)
        worker.error_occurred.connect(self._slot_error)
        worker.finished.connect(self._slot_thread_finished)

        self.busy_changed.emit(True)
        self.status.emit("Routing and generating reply...")
        worker.start()
        return True

    def stop(self) -> None:
        """User pressed Stop: cancel; cleanup happens when the thread exits."""
        if self._turn is not None:
            self._turn.worker.stop()
            self.status.emit("Stopping...")

    def detach(self) -> None:
        """The view is switching conversations: cancel, stop painting, and free the slot.

        The old worker drains in the background and saves only to its own conversation.
        """
        if self._turn is not None:
            turn = self._turn
            turn.visible = False
            turn.worker.stop()
            self._turn = None
            self.busy_changed.emit(False)

    def shutdown(self, timeout_ms: int = 3000) -> None:
        """Cancel and wait for every worker still running (window closing)."""
        for turn in list(self._turns.values()):
            turn.visible = False
            turn.worker.stop()
        for turn in list(self._turns.values()):
            if not turn.worker.wait(timeout_ms):
                logger.warning("Chat worker did not stop within %d ms", timeout_ms)

    # --- worker signal slots: map the sending worker back to its turn ---

    def _sender_turn(self) -> Optional[_Turn]:
        return self._turns.get(self.sender())

    def _slot_routed(self, d: Dict[str, Any]) -> None:
        if (t := self._sender_turn()) is not None:
            self._on_routed(t, d)

    def _slot_fallback(self, d: Dict[str, Any]) -> None:
        if (t := self._sender_turn()) is not None:
            self._on_fallback(t, d)

    def _slot_text(self, chunk: str) -> None:
        if (t := self._sender_turn()) is not None:
            self._on_text(t, chunk)

    def _slot_reasoning(self, chunk: str) -> None:
        if (t := self._sender_turn()) is not None:
            self._on_reasoning(t, chunk)

    def _slot_tool_start(self, d: Dict[str, Any]) -> None:
        if (t := self._sender_turn()) is not None:
            self._on_tool_start(t, d)

    def _slot_tool_result(self, d: Dict[str, Any]) -> None:
        if (t := self._sender_turn()) is not None:
            self._on_tool_result(t, d)

    def _slot_done(self, d: Dict[str, Any]) -> None:
        if (t := self._sender_turn()) is not None:
            self._on_done(t, d)

    def _slot_error(self, d: Dict[str, Any]) -> None:
        if (t := self._sender_turn()) is not None:
            self._on_error(t, d)

    def _slot_thread_finished(self) -> None:
        if (t := self._sender_turn()) is not None:
            self._on_thread_finished(t)

    # --- handlers (all ignore stale turns for display) ---

    def _live(self, turn: _Turn) -> bool:
        return turn is self._turn and turn.visible

    def _on_routed(self, turn: _Turn, data: Dict[str, Any]) -> None:
        turn.routed = data
        if self._live(turn):
            self.chat_view.start_assistant_message(
                turn.msg_id,
                model_name=data.get("model_id", ""),
                provider_name=data.get("provider_id", ""),
                strategy_name=data.get("strategy", ""),
                reason=data.get("reason", ""),
                metadata=data.get("metadata", {}),
            )
            self.status.emit(f"Streaming from '{data.get('model_id')}' via {data.get('provider_id')}...")

    def _on_fallback(self, turn: _Turn, data: Dict[str, Any]) -> None:
        turn.fallbacks.append(data)
        if self._live(turn):
            self.chat_view.show_fallback_notice(
                data.get("from_endpoint_id", ""), data.get("to_endpoint_id", ""), data.get("error", "")
            )

    def _on_text(self, turn: _Turn, chunk: str) -> None:
        turn.text += chunk
        if self._live(turn):
            self.chat_view.append_token(turn.msg_id, chunk)

    def _on_reasoning(self, turn: _Turn, chunk: str) -> None:
        turn.reasoning += chunk
        if self._live(turn):
            self.chat_view.append_reasoning(turn.msg_id, chunk)

    def _on_tool_start(self, turn: _Turn, data: Dict[str, Any]) -> None:
        turn.tool_events.append({"id": data.get("id", ""), "name": data.get("name", ""),
                                 "arguments": data.get("arguments", {})})
        if self._live(turn):
            self.chat_view.add_tool_card(turn.msg_id, data.get("id", ""), data.get("name", ""), data.get("arguments", {}))
            self.status.emit(f"Executing tool '{data.get('name')}'...")

    def _on_tool_result(self, turn: _Turn, data: Dict[str, Any]) -> None:
        for event in reversed(turn.tool_events):
            if event["id"] == data.get("id", "") and "success" not in event:
                event.update(result=data.get("result"), error=data.get("error"),
                             success=data.get("success", True), duration_ms=data.get("duration_ms", 0))
                break
        if self._live(turn):
            self.chat_view.update_tool_result(
                turn.msg_id, data.get("id", ""), data.get("name", ""), data.get("result"),
                data.get("error"), data.get("success", True), data.get("duration_ms", 0),
            )

    def _on_done(self, turn: _Turn, data: Dict[str, Any]) -> None:
        turn.outcome = "done"
        self._save(turn, data, status="complete")
        cost = float(data.get("cost_usd") or 0.0)
        self.cost_added.emit(cost)
        if self._live(turn):
            self.chat_view.finish_assistant_message(turn.msg_id, data)
            self.status.emit(
                f"Turn complete · {data.get('tokens_in', 0)} in / {data.get('tokens_out', 0)} out · ${cost:.5f}"
            )

    def _on_error(self, turn: _Turn, data: Dict[str, Any]) -> None:
        turn.outcome = "error"
        if turn.text:
            self._save(turn, {}, status="error")
        if self._live(turn):
            self._ensure_bubble(turn)
            self.chat_view.finish_assistant_message(turn.msg_id, self._partial_meta(turn))
            self.chat_view.show_error(turn.msg_id, data.get("error", "Unknown error"), data.get("category", "unknown"))
            self.status.emit("Error during generation.")

    def _on_thread_finished(self, turn: _Turn) -> None:
        if turn.outcome is None:
            # Stopped by the user or by a conversation switch: keep what was streamed.
            if turn.text:
                self._save(turn, {}, status="stopped")
            if self._live(turn):
                self._ensure_bubble(turn)
                self.chat_view.finish_assistant_message(turn.msg_id, {**self._partial_meta(turn), "stopped": True})
                self.status.emit("Generation stopped.")
        self._turns.pop(turn.worker, None)
        if turn is self._turn:
            self._turn = None
            self.busy_changed.emit(False)
        turn.worker.deleteLater()

    # --- helpers ---

    def _ensure_bubble(self, turn: _Turn) -> None:
        if not turn.routed:  # failed before routing: create a bubble to hang the error on
            turn.routed = {"strategy": turn.worker.strategy_name}
            self.chat_view.start_assistant_message(turn.msg_id, strategy_name=turn.worker.strategy_name)

    def _partial_meta(self, turn: _Turn) -> Dict[str, Any]:
        r = turn.routed
        return {
            "model_id": r.get("model_id", ""),
            "provider_id": r.get("provider_id", ""),
            "strategy": r.get("strategy", ""),
            "reason": r.get("reason", ""),
            "metadata": r.get("metadata", {}),
        }

    def _save(self, turn: _Turn, data: Dict[str, Any], status: str) -> None:
        """Persist the assistant reply to the turn's own conversation."""
        reasoning, text = extract_reasoning_and_content(
            raw_text=turn.text, explicit_reasoning=turn.reasoning, is_streaming=False
        )
        msg = Message.from_text("assistant", text)
        msg.id = turn.msg_id
        msg.reasoning = reasoning or None
        msg.meta = {
            "strategy": data.get("strategy") or turn.routed.get("strategy"),
            "reason": data.get("reason") or turn.routed.get("reason"),
            "routing": data.get("metadata") or turn.routed.get("metadata") or {},
            "tool_events": turn.tool_events,
            "fallbacks": turn.fallbacks,
        }
        try:
            self.storage.save_message(
                message=msg,
                conversation_id=turn.conversation_id,
                model_id=data.get("model_id") or turn.routed.get("model_id"),
                endpoint_id=data.get("endpoint_id") or turn.routed.get("endpoint_id"),
                provider_id=data.get("provider_id") or turn.routed.get("provider_id"),
                tokens_in=data.get("tokens_in", 0),
                tokens_out=data.get("tokens_out", 0),
                cost=float(data.get("cost_usd") or 0.0),
                latency_ms=int((data.get("latency_sec") or 0) * 1000),
                status=status,
            )
        except Exception as exc:  # e.g. the conversation was deleted mid-stream
            logger.warning("Could not save reply to conversation %s: %s", turn.conversation_id, exc)
