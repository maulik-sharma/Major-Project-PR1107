"""State builder to assemble compact, bounded prompt context for decision models."""

from __future__ import annotations

import hashlib
from typing import List, Optional

from modelmesh.core.types import ImagePart, Message


def truncate_text(text: str, max_chars: int = 6000) -> str:
    """Truncate text keeping head and tail if it exceeds max_chars."""
    if len(text) <= max_chars:
        return text
    half = max_chars // 2 - 20
    head = text[:half]
    tail = text[-half:]
    return f"{head}\n...[truncated]...\n{tail}"


def build_decision_state(
    messages: List[Message],
    max_tokens: int = 2000,
    tools_enabled: bool = False,
    tools_count: int = 0,
    send_prompt_text: bool = True,
) -> tuple[str, str, bool]:
    """Assemble a bounded conversation state string for decision evaluation.

    Returns:
        Tuple of (state_text, state_hash, use_heuristic_only).
    """
    if not send_prompt_text:
        return (
            "[PRIVACY_MODE: Prompt text withheld by user privacy switch]",
            "privacy_mode_hash",
            True,
        )

    if not messages:
        return ("User: (empty)", hashlib.sha256(b"").hexdigest()[:16], False)

    # 1. Latest message
    latest_msg = messages[-1]
    latest_text = truncate_text(latest_msg.text_content(), max_chars=max_tokens * 3)

    # 2. History context (previous 2-3 turns)
    history_lines: List[str] = []
    prior_messages = messages[:-1][-4:]  # Up to 4 prior turns
    for m in prior_messages:
        role_tag = "User" if m.role == "user" else "Assistant"
        txt = m.text_content().strip()
        if not txt and m.tool_calls:
            txt = f"[Tool calls: {', '.join(tc.name for tc in m.tool_calls)}]"
        trimmed_txt = txt[:300] + ("..." if len(txt) > 300 else "")
        if trimmed_txt:
            history_lines.append(f"{role_tag}: {trimmed_txt}")

    # 3. Facts that change routing
    has_image = any(
        isinstance(p, ImagePart) for m in messages for p in m.parts
    )
    metadata_lines: List[str] = []
    if tools_enabled or tools_count > 0:
        metadata_lines.append(f"[Tools Available: {tools_count}]")
    if has_image:
        metadata_lines.append("[Images Attached: Yes]")

    sections: List[str] = []
    if metadata_lines:
        sections.append("Context: " + " ".join(metadata_lines))
    if history_lines:
        sections.append("Conversation History:\n" + "\n".join(history_lines))
    sections.append(f"Latest User Message:\n{latest_text}")

    full_state = "\n\n".join(sections)
    state_hash = hashlib.sha256(full_state.encode("utf-8")).hexdigest()[:16]

    return (full_state, state_hash, False)
