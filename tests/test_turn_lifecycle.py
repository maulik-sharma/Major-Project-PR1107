"""Chat turn lifecycle in the main window: streaming state, stop, switching chats, retry, attachments."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Iterator, List, Optional

import pytest
from PyQt6.QtWidgets import QApplication

from modelmesh.core.attachments import Attachment, load_attachment
from modelmesh.core.engine import ChatEngine
from modelmesh.core.providers.base import ProviderAdapter, register_adapter
from modelmesh.core.registry import ModelRegistry
from modelmesh.core.routing.router import Router
from modelmesh.core.storage import Storage
from modelmesh.core.types import (
    Candidate,
    ChatRequest,
    EndpointConfig,

    ModelConfig,
    ProviderConfig,
    StreamEvent,
    StreamEventType,
    TextPart,
    Usage,
)
from modelmesh.ui.main_window import MainWindow

GATE = threading.Event()  # tests open it to let the slow reply finish

@register_adapter("slow_test")
class SlowAdapter(ProviderAdapter):
    """Streams one chunk, then waits for GATE (or cancel) before finishing."""

    def stream_chat(
        self,
        request: ChatRequest,
        candidate: Candidate,
        cancel_event: Optional[threading.Event] = None,
    ) -> Iterator[StreamEvent]:
        yield StreamEvent(type=StreamEventType.TEXT_DELTA, text="partial ")
        while not GATE.is_set():
            if cancel_event is not None and cancel_event.is_set():
                return
            time.sleep(0.01)
        yield StreamEvent(type=StreamEventType.TEXT_DELTA, text="answer")
        yield StreamEvent(type=StreamEventType.USAGE, usage=Usage(input_tokens=5, output_tokens=2))
        yield StreamEvent(type=StreamEventType.DONE, finish_reason="stop")

    def list_models(self, provider: ProviderConfig) -> List[str]:
        return []

    def map_error(self, exc: Exception, provider_id: str) -> Exception:
        return exc

def pump(app: QApplication, until: Any, timeout_s: float = 5.0) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        app.processEvents()
        if until():
            return
        time.sleep(0.01)
    raise AssertionError("condition not reached")

@pytest.fixture
def window(qapp: QApplication, tmp_path: Path) -> Iterator[MainWindow]:
    GATE.clear()
    reg = ModelRegistry()
    reg.add_provider(ProviderConfig(id="slowprov", protocol="slow_test"))
    reg.add_model(ModelConfig(
        id="slow-model", display_name="Slow", capabilities=["streaming"],
        endpoints=[EndpointConfig(id="slow-model@slowprov", provider="slowprov", api_model="x")],
    ))
    storage = Storage(tmp_path / "turns.db")
    router = Router(registry=reg)
    win = MainWindow(registry=reg, router=router, engine=ChatEngine(registry=reg, router=router, storage=storage),
                     storage=storage)
    win.strategy_combo.setCurrentIndex(win.strategy_combo.findData("cheapest_first"))
    yield win
    GATE.set()
    win.close()

def idle(win: MainWindow) -> bool:
    return not win.turns.is_busy and not win.turns._turns

def test_enter_during_stream_does_not_start_second_turn(window: MainWindow, qapp: QApplication) -> None:
    window._on_send_message("first", [])
    pump(qapp, lambda: window.composer._is_streaming)
    window.composer.text_input.setPlainText("second")
    window.composer.text_input.send_pressed.emit()  # Enter key path
    assert window.composer.text_input.toPlainText() == "second"  # not consumed
    GATE.set()
    pump(qapp, lambda: idle(window))
    roles = [m.role for m in window.storage.get_messages(window.current_conversation_id)]
    assert roles == ["user", "assistant"]

def test_stop_resets_composer_and_keeps_partial_reply(window: MainWindow, qapp: QApplication) -> None:
    window._on_send_message("tell me", [])
    pump(qapp, lambda: window.composer._is_streaming)
    window.composer.action_btn.click()  # Stop
    pump(qapp, lambda: idle(window))
    assert window.composer._is_streaming is False
    msgs = window.storage.get_messages(window.current_conversation_id)
    assert msgs[-1].role == "assistant"
    assert msgs[-1].meta.get("status") == "stopped"
    assert "partial" in msgs[-1].text_content()

def test_switching_chats_mid_stream_saves_to_original_conversation(window: MainWindow, qapp: QApplication) -> None:
    window._on_send_message("in chat A", [])
    conv_a = window.current_conversation_id
    pump(qapp, lambda: window.composer._is_streaming)
    window._on_new_chat()
    conv_b = window.current_conversation_id
    assert conv_b != conv_a
    assert window.composer._is_streaming is False  # composer usable in the new chat
    pump(qapp, lambda: idle(window))
    assert window.storage.get_messages(conv_b) == []
    assert [m.role for m in window.storage.get_messages(conv_a)] == ["user", "assistant"]

def test_reclicking_open_chat_does_not_interrupt_stream(window: MainWindow, qapp: QApplication) -> None:
    window._on_send_message("hello", [])
    pump(qapp, lambda: window.composer._is_streaming)
    window._on_conversation_selected(window.current_conversation_id)
    assert window.turns.is_busy
    GATE.set()
    pump(qapp, lambda: idle(window))
    msgs = window.storage.get_messages(window.current_conversation_id)
    assert msgs[-1].meta.get("status") == "complete"
    assert msgs[-1].text_content() == "partial answer"

def test_retry_replaces_last_reply_without_duplicating_user_message(window: MainWindow, qapp: QApplication) -> None:
    GATE.set()
    window._on_send_message("question", [])
    pump(qapp, lambda: idle(window))
    first_reply = window.storage.get_messages(window.current_conversation_id)[-1]
    window._on_regenerate(first_reply.id)
    pump(qapp, lambda: idle(window))
    msgs = window.storage.get_messages(window.current_conversation_id)
    assert [m.role for m in msgs] == ["user", "assistant"]
    assert msgs[-1].id != first_reply.id

def test_attachments_load_and_send_without_crashing(window: MainWindow, qapp: QApplication, tmp_path: Path) -> None:
    txt = tmp_path / "notes.txt"
    txt.write_text("remember the milk", encoding="utf-8")
    png = tmp_path / "pic.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    window.composer._load_attachments([txt, png])
    pump(qapp, lambda: len(window.composer._attachments) == 2 and not window.composer._attachment_workers)
    assert "~" in window.composer.token_caption.text()

    GATE.set()
    window.composer.text_input.setPlainText("see attached")
    window.composer.action_btn.click()
    pump(qapp, lambda: idle(window))
    user = window.storage.get_messages(window.current_conversation_id)[0]
    names = {getattr(p, "name", None) for p in user.parts}
    assert {"notes.txt", "pic.png"} <= names
    assert any(isinstance(p, TextPart) and p.text == "see attached" and not p.name for p in user.parts)

def test_load_attachment_names_parts(tmp_path: Path) -> None:
    f = tmp_path / "a.py"
    f.write_text("print(1)", encoding="utf-8")
    att = load_attachment(f)
    assert isinstance(att, Attachment) and att.name == "a.py" and att.part.name == "a.py"
    assert att.estimated_tokens() > 0
