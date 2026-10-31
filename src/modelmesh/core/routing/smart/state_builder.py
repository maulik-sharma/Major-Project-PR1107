"""State builder to assemble compact, bounded prompt context for decision models."""

from __future__ import annotations

import hashlib
from typing import List

from modelmesh.core.types import ImagePart, Message

# Rough characters-per-token used to turn max_state_tokens into a character budget.
_CHARS_PER_TOKEN = 3
_HISTORY_MESSAGES = 4
_HISTORY_CHARS = 300
_ROLE_LABELS = {"user": "User", "assistant": "Assistant", "tool": "Tool result", "system": "System"}


def truncate_text(text: str, max_chars: int = 6000) -> str:
    """Truncate text keeping head and tail if it exceeds max_chars."""
    if len(text) <= max_chars:
        return text
    if max_chars < 60:
        return text[:max_chars]
    half = max_chars // 2 - 20
    return f"{text[:half]}\n...[truncated]...\n{text[-half:]}"


def latest_user_text(messages: List[Message]) -> str:
    """Return the text of the most recent user message (empty if none)."""
    for msg in reversed(messages):
        if msg.role == "user":
            return msg.text_content()
    return ""


def build_decision_state(
    messages: List[Message],
    max_tokens: int = 2000,
    tools_enabled: bool = False,
    tools_count: int = 0,
) -> tuple[str, str]:
    """Assemble a bounded conversation state string for a remote decision model.

    The whole state (context line, history and latest message) fits within
    roughly ``max_tokens`` tokens; the latest message gets whatever budget
    the other sections leave.

    Returns:
        Tuple of (state_text, state_hash).
    """
    if not messages:
        return ("Latest User Message:\n(empty)", hashlib.sha256(b"").hexdigest()[:16])

    budget = max(200, max_tokens * _CHARS_PER_TOKEN)

    history_lines: List[str] = []
    for m in messages[:-1][-_HISTORY_MESSAGES:]:
        txt = m.text_content().strip()
        if not txt and m.tool_calls:
            txt = f"[Tool calls: {', '.join(tc.name for tc in m.tool_calls)}]"
        if txt:
            trimmed = txt[:_HISTORY_CHARS] + ("..." if len(txt) > _HISTORY_CHARS else "")
            history_lines.append(f"{_ROLE_LABELS.get(m.role, m.role.title())}: {trimmed}")

    metadata: List[str] = []
    if tools_enabled or tools_count > 0:
        metadata.append(f"[Tools Available: {tools_count}]")
    if any(isinstance(p, ImagePart) for m in messages for p in m.parts):
        metadata.append("[Images Attached: Yes]")

    sections: List[str] = []
    if metadata:
        sections.append("Context: " + " ".join(metadata))
    if history_lines:
        sections.append("Conversation History:\n" + "\n".join(history_lines))

    header = "Latest User Message:\n"
    used = sum(len(s) + 2 for s in sections) + len(header)
    if used > budget // 2 and history_lines:
        # History must never crowd out the message being routed.
        sections = [s for s in sections if not s.startswith("Conversation History")]
        used = sum(len(s) + 2 for s in sections) + len(header)
    latest = truncate_text(latest_user_text(messages), max_chars=max(60, budget - used))
    sections.append(header + latest)

    full_state = "\n\n".join(sections)
    state_hash = hashlib.sha256(full_state.encode("utf-8")).hexdigest()[:16]
    return (full_state, state_hash)
