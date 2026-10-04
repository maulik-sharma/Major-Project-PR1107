"""WebEngine-based chat transcript view with smooth markdown & code rendering."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QObject, QTimer, QUrl, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor, QDesktopServices
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineCore import QWebEnginePage
from PyQt6.QtWebEngineWidgets import QWebEngineView


class CustomWebEnginePage(QWebEnginePage):
    """Custom WebEnginePage that intercepts navigation to external URLs."""

    def acceptNavigationRequest(
        self, url: QUrl, _type: QWebEnginePage.NavigationType, isMainFrame: bool
    ) -> bool:
        if _type == QWebEnginePage.NavigationType.NavigationTypeLinkClicked:
            QDesktopServices.openUrl(url)
            return False
        return super().acceptNavigationRequest(url, _type, isMainFrame)


class ChatBridge(QObject):
    """Bridge for bi-directional communication between Python and JavaScript."""

    ready = pyqtSignal()
    copy_requested = pyqtSignal(str)
    regenerate_requested = pyqtSignal(str)
    suggestion_clicked = pyqtSignal(str)
    link_clicked = pyqtSignal(str)

    @pyqtSlot()
    def on_ready(self) -> None:
        self.ready.emit()

    @pyqtSlot(str)
    def on_copy(self, text: str) -> None:
        self.copy_requested.emit(text)

    @pyqtSlot(str)
    def on_regenerate(self, message_id: str) -> None:
        self.regenerate_requested.emit(message_id)

    @pyqtSlot(str)
    def on_suggestion_clicked(self, prompt: str) -> None:
        self.suggestion_clicked.emit(prompt)

    @pyqtSlot(str)
    def on_open_link(self, url: str) -> None:
        self.link_clicked.emit(url)


class ChatView(QWebEngineView):
    """PyQt6 QWebEngineView wrapper for modern chat transcript rendering."""

    regenerate_requested = pyqtSignal(str)
    suggestion_clicked = pyqtSignal(str)

    def __init__(self, parent: Optional[Any] = None) -> None:
        super().__init__(parent)

        self._page = CustomWebEnginePage(self)
        self.setPage(self._page)
        self.page().setBackgroundColor(QColor("#141417"))
        self.setStyleSheet("background-color: #141417; border: none;")

        self.bridge = ChatBridge()
        self.bridge.regenerate_requested.connect(self.regenerate_requested)
        self.bridge.suggestion_clicked.connect(self.suggestion_clicked)

        self._channel = QWebChannel(self.page())
        self._channel.registerObject("pyBridge", self.bridge)
        self.page().setWebChannel(self._channel)

        # Buffering timer for high-frequency token streams (~35ms batching)
        self._pending_tokens: Dict[str, str] = {}
        self._pending_reasoning: Dict[str, str] = {}
        self._stream_timer = QTimer(self)
        self._stream_timer.setInterval(35)
        self._stream_timer.timeout.connect(self._flush_stream_buffers)
        self._stream_timer.start()

        # Load chat.html
        self._is_page_loaded = False
        self._queued_js: List[str] = []
        self.loadFinished.connect(self._on_load_finished)

        html_path = Path(__file__).parent / "web" / "chat.html"
        self.load(QUrl.fromLocalFile(str(html_path.resolve())))

    def _on_load_finished(self, ok: bool) -> None:
        self._is_page_loaded = True
        for script in self._queued_js:
            self.page().runJavaScript(script)
        self._queued_js.clear()

    def _flush_stream_buffers(self) -> None:
        """Batch flush token deltas to JavaScript to prevent UI stutter."""
        if self._pending_reasoning:
            for msg_id, text in list(self._pending_reasoning.items()):
                if text:
                    self._run_js("append_reasoning_chunk", msg_id, text)
            self._pending_reasoning.clear()

        if self._pending_tokens:
            for msg_id, text in list(self._pending_tokens.items()):
                if text:
                    self._run_js("append_text_chunk", msg_id, text)
            self._pending_tokens.clear()

    def _run_js(self, func_name: str, *args: Any) -> None:
        """Safely invoke a JavaScript function with JSON-encoded arguments."""
        encoded_args = [json.dumps(a) for a in args]
        script = f"if (typeof window['{func_name}'] === 'function') {{ window['{func_name}']({', '.join(encoded_args)}); }}"
        if self._is_page_loaded:
            self.page().runJavaScript(script)
        else:
            self._queued_js.append(script)

    def add_user_message(
        self,
        msg_id: str,
        text: str,
        parts: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Add a user message bubble."""
        self._run_js("add_user_message", msg_id, text, parts or [])

    def start_assistant_message(
        self,
        msg_id: str,
        model_name: str = "",
        provider_name: str = "",
        strategy_name: str = "",
        reason: str = "",
    ) -> None:
        """Initialize an assistant message block."""
        self._run_js(
            "start_assistant_message",
            msg_id,
            model_name,
            provider_name,
            strategy_name,
            reason,
        )

    def append_token(self, msg_id: str, token: str) -> None:
        """Queue a text delta to be flushed."""
        self._pending_tokens[msg_id] = self._pending_tokens.get(msg_id, "") + token

    def append_reasoning(self, msg_id: str, reasoning: str) -> None:
        """Queue a reasoning delta to be flushed."""
        self._pending_reasoning[msg_id] = self._pending_reasoning.get(msg_id, "") + reasoning

    def add_tool_card(
        self,
        msg_id: str,
        tool_id: str,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> None:
        """Render a tool call card."""
        args_json = json.dumps(arguments, indent=2)
        self._run_js("add_tool_card", msg_id, tool_id, tool_name, args_json)

    def finish_assistant_message(self, msg_id: str, meta: Dict[str, Any]) -> None:
        """Flush remaining deltas and finalize message chips."""
        self._flush_stream_buffers()
        self._run_js("finish_assistant_message", msg_id, meta)

    def show_fallback_notice(
        self,
        from_candidate: str,
        to_candidate: str,
        reason: str = "",
    ) -> None:
        """Display an automated failover banner."""
        self._run_js("show_fallback_notice", from_candidate, to_candidate, reason)

    def show_error(
        self,
        msg_id: str,
        error_msg: str,
        category: str = "unknown",
    ) -> None:
        """Display an error notification."""
        self._flush_stream_buffers()
        self._run_js("set_error", msg_id, error_msg, category)

    def clear(self) -> None:
        """Clear all messages and show empty state."""
        self._pending_tokens.clear()
        self._pending_reasoning.clear()
        self._run_js("clear_chat")

    def set_theme(self, theme_name: str) -> None:
        """Switch dark / light theme in chat view."""
        self._run_js("set_theme", theme_name)
