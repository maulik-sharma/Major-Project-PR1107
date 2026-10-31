"""Chat transcript (QtWebEngine) safety: untrusted text must render as text, never as HTML."""

from __future__ import annotations

import json
from typing import Any

import pytest
from PyQt6.QtCore import QEventLoop, QTimer

from modelmesh.ui.chat_view import ChatView

PAYLOAD = '<img src=x onerror="window.__pwned=1">'


def _wait(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def _eval(view: ChatView, script: str) -> Any:
    result: dict = {}
    loop = QEventLoop()

    def done(value: Any) -> None:
        result["v"] = value
        loop.quit()

    view.page().runJavaScript(script, done)
    QTimer.singleShot(5000, loop.quit)
    loop.exec()
    return result.get("v")


@pytest.fixture
def view(qapp: Any) -> ChatView:
    v = ChatView()
    for _ in range(100):
        if v._is_page_loaded:
            break
        _wait(50)
    if not v._is_page_loaded:
        pytest.skip("QtWebEngine page did not load in this environment")
    return v


def test_untrusted_strings_render_as_text(view: ChatView) -> None:
    view.add_user_message("u1", PAYLOAD)
    view.start_assistant_message("a1", PAYLOAD, PAYLOAD, "smart_clef", PAYLOAD, {"notices": [PAYLOAD]})
    view.add_tool_card("a1", "call_0", PAYLOAD, {"q": PAYLOAD})
    view.update_tool_result("a1", "call_0", "fetch_url", PAYLOAD, None, True, 5)
    view.add_tool_card("a1", "call_1", "read_text_file", {})
    view.update_tool_result("a1", "call_1", "read_text_file", None, PAYLOAD, False, 5)
    view.show_fallback_notice(PAYLOAD, PAYLOAD, PAYLOAD)
    view.finish_assistant_message("a1", {
        "model_id": PAYLOAD,
        "metadata": {
            "strategy": "smart_clef", "need": 0.5, "task": PAYLOAD,
            "decision_source": "heuristic_fallback", "decision_error": PAYLOAD,
            "candidates": [{"model_id": PAYLOAD, "q": 1, "admitted": True}],
        },
    })
    view.show_error("a1", PAYLOAD, "unknown")
    _wait(300)

    assert _eval(view, "document.querySelectorAll('#chat-container img').length") == 0
    assert _eval(view, "window.__pwned === 1") is False
    text = _eval(view, "document.getElementById('chat-container').innerText")
    assert text.count("onerror") >= 8  # shown literally in every place it was passed


def test_heuristic_fallback_notice_and_attribution_shown(view: ChatView) -> None:
    meta = {"strategy": "smart_clef", "need": 0.4, "decision_source": "heuristic_fallback",
            "decision_error": "Circuit breaker open", "candidates": []}
    view.start_assistant_message("a2", "m", "p", "smart_clef", "r", meta)
    view.finish_assistant_message("a2", {"model_id": "m", "metadata": meta})
    _wait(300)
    text = _eval(view, "document.getElementById('msg-a2').innerText")
    assert "Heuristic fallback" in text
    assert "decision service was unavailable" in text
    assert "Model scores: Artificial Analysis" in _eval(
        view, "document.getElementById('insights-a2').innerText || document.getElementById('insights-a2').textContent"
    )


def test_tool_cards_are_scoped_per_message(view: ChatView) -> None:
    for msg in ("m1", "m2"):
        view.start_assistant_message(msg, "m", "p", "manual", "")
        view.add_tool_card(msg, "call_0", "calculator", {})
    view.update_tool_result("m2", "call_0", "calculator", "42", None, True, 1)
    _wait(300)
    first = _eval(view, "document.getElementById('msg-m1').querySelector('.tool-status').textContent")
    second = _eval(view, "document.getElementById('msg-m2').querySelector('.tool-status').textContent")
    assert first == "Running..."
    assert second.startswith("Success")


def test_streaming_closes_tilde_and_long_fences(view: ChatView) -> None:
    view.start_assistant_message("s1", "m", "p", "manual", "")
    view.append_token("s1", "Here:\n~~~python\nx = 1\n")
    _wait(300)
    assert _eval(view, "document.getElementById('content-s1').querySelectorAll('pre').length") == 1


def test_code_is_highlighted_once_reply_finishes(view: ChatView) -> None:
    view.start_assistant_message("h1", "m", "p", "manual", "")
    view.append_token("h1", "```python\ndef f():\n    return 1\n```\n")
    _wait(300)
    assert _eval(view, "document.querySelectorAll('#content-h1 code[data-highlighted]').length") == 0
    view.finish_assistant_message("h1", {"model_id": "m"})
    _wait(300)
    assert _eval(view, "document.querySelectorAll('#content-h1 code[data-highlighted]').length") == 1
