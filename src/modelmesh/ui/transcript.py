"""Rendering of stored conversations into the chat view, and history clean-up for requests."""

from __future__ import annotations

from typing import Any, Dict, List

from modelmesh.core.attachments import split_user_parts
from modelmesh.core.formatting import extract_reasoning_and_content
from modelmesh.core.types import ImagePart, Message


def display_parts(parts: List[Any]) -> List[Dict[str, Any]]:
    """Attachment parts as the chat view shows them: images inline, files as name chips."""
    shown: List[Dict[str, Any]] = []
    for p in parts:
        if isinstance(p, ImagePart):
            shown.append(p.to_dict())
        elif getattr(p, "name", None):
            shown.append({"type": "file", "name": p.name})
    return shown


def render_conversation(chat_view: Any, messages: List[Message]) -> None:
    """Paint a stored conversation, including tool cards and routing notices."""
    for msg in messages:
        if msg.role == "user":
            text, attached = split_user_parts(msg.parts)
            chat_view.add_user_message(msg.id, text, display_parts(attached))
        elif msg.role == "assistant":
            _render_assistant(chat_view, msg)


def _render_assistant(chat_view: Any, msg: Message) -> None:
    meta = msg.meta or {}
    routing = meta.get("routing") or {}
    reasoning, text = extract_reasoning_and_content(
        raw_text=msg.text_content(), explicit_reasoning=msg.reasoning or "", is_streaming=False
    )
    chat_view.start_assistant_message(
        msg.id,
        model_name=meta.get("model_id") or "",
        provider_name=meta.get("provider_id") or "",
        strategy_name=meta.get("strategy") or "",
        reason=meta.get("reason") or "",
        metadata=routing,
    )
    for fb in meta.get("fallbacks") or []:
        chat_view.show_fallback_notice(fb.get("from_endpoint_id", ""), fb.get("to_endpoint_id", ""), fb.get("error", ""))
    for ev in meta.get("tool_events") or []:
        chat_view.add_tool_card(msg.id, ev.get("id", ""), ev.get("name", ""), ev.get("arguments", {}))
        if "success" in ev:
            chat_view.update_tool_result(
                msg.id, ev.get("id", ""), ev.get("name", ""), ev.get("result"),
                ev.get("error"), ev.get("success", True), ev.get("duration_ms", 0),
            )
    if reasoning:
        chat_view.append_reasoning(msg.id, reasoning)
    chat_view.append_token(msg.id, text)
    chat_view.finish_assistant_message(msg.id, {
        "model_id": meta.get("model_id"),
        "provider_id": meta.get("provider_id"),
        "strategy": meta.get("strategy"),
        "reason": meta.get("reason"),
        "metadata": routing,
        "tokens_in": meta.get("tokens_in"),
        "tokens_out": meta.get("tokens_out"),
        "cost_usd": meta.get("cost"),
        "latency_sec": (meta.get("latency_ms") or 0) / 1000.0,
        "stopped": meta.get("status") == "stopped",
    })


def request_history(messages: List[Message]) -> List[Message]:
    """Messages to send to a model: drop user turns that never got a reply (failed turns),
    except the latest one, so providers never see two user messages in a row."""
    cleaned: List[Message] = []
    for i, msg in enumerate(messages):
        is_last = i == len(messages) - 1
        nxt = messages[i + 1] if not is_last else None
        if msg.role == "user" and not is_last and nxt is not None and nxt.role == "user":
            continue
        cleaned.append(msg)
    return cleaned
