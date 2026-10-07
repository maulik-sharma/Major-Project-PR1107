"""Robust text, reasoning, and markdown formatting utilities for ModelMesh."""

from __future__ import annotations

import re
from typing import Optional, Tuple


# Tags commonly used by thinking / reasoning models
REASONING_TAG_NAMES = ("thought", "think", "reasoning", "reflection", "scratchpad")

# Common patterns where an LLM transitions from internal scratchpad notes to its actual user-facing answer
TRANSITION_PATTERNS = [
    # Explicit horizontal divider
    r"\n\s*(?:---|===|\*\*\*)\s*\n+",
    # Transition phrases
    r"\n\s*(?:Here is (?:the|my) (?:response|answer|evaluation|score|summary|analysis|review|breakdown)|Let's write (?:the|a) (?:response|answer)|I will format (?:the|my) (?:output|response)|Final (?:Response|Answer|Verdict|Evaluation|Score):|Response:|Answer:)\s*[:\n]+",
    # Clear Markdown Header starts (e.g., # Title, ## Section, **Header, etc.)
    r"\n\s*(?:#{1,4}\s+|\*\*(?:ATS Score|Executive Summary|Summary|Evaluation|Overview|Verdict|Final|Result|Score|Answer|Solution|Breakdown))",
]


def extract_reasoning_and_content(
    raw_text: str,
    explicit_reasoning: Optional[str] = None,
    is_streaming: bool = False,
) -> Tuple[str, str]:
    """Robustly extract thinking / scratchpad notes and separate from visible response.

    Handles:
    - Standard closed XML tags (<thought>...</thought>, <think>...</think>, etc.)
    - Multiple reasoning blocks
    - Streaming unclosed tags
    - Models that emit an unclosed <thought> without closing tag and transition directly into the answer
    - Models that put the entire response inside <thought>

    Returns:
        (reasoning_str, content_str)
    """
    reasoning_parts = (
        [explicit_reasoning.strip()]
        if explicit_reasoning and explicit_reasoning.strip()
        else []
    )
    content = raw_text or ""

    # 1. Extract closed tags
    tag_names_re = "|".join(REASONING_TAG_NAMES)
    closed_tag_pattern = rf"<({tag_names_re})>(.*?)</\1>"

    def _replace_closed(match: re.Match) -> str:
        thought_body = match.group(2).strip()
        if thought_body:
            reasoning_parts.append(thought_body)
        return ""

    content = re.sub(
        closed_tag_pattern, _replace_closed, content, flags=re.DOTALL | re.IGNORECASE
    ).strip()

    # 2. Check for unclosed tag (<thought>... without matching </thought>)
    unclosed_tag_pattern = rf"<({tag_names_re})>(.*)$"
    unclosed_match = re.search(
        unclosed_tag_pattern, content, flags=re.DOTALL | re.IGNORECASE
    )

    if unclosed_match:
        prefix = content[: unclosed_match.start()].strip()
        unclosed_body = unclosed_match.group(2).strip()

        if is_streaming:
            # While actively streaming, check if transition marker already appeared
            split_idx = _find_transition_split(unclosed_body)
            if split_idx is not None:
                thought_part = unclosed_body[:split_idx].strip()
                ans_part = unclosed_body[split_idx:].strip()
                ans_part = re.sub(r"^(?:---|===|\*\*\*)\s*", "", ans_part).strip()
                if thought_part:
                    reasoning_parts.append(thought_part)
                content = (prefix + "\n\n" + ans_part).strip() if prefix else ans_part
            else:
                if unclosed_body:
                    reasoning_parts.append(unclosed_body)
                content = prefix
        else:
            # Streaming is finished or static load: must resolve intelligently
            split_idx = _find_transition_split(unclosed_body)
            if split_idx is not None:
                thought_part = unclosed_body[:split_idx].strip()
                ans_part = unclosed_body[split_idx:].strip()
                ans_part = re.sub(r"^(?:---|===|\*\*\*)\s*", "", ans_part).strip()
                if thought_part:
                    reasoning_parts.append(thought_part)
                content = (prefix + "\n\n" + ans_part).strip() if prefix else ans_part
            else:
                # No transition found. If prefix is non-empty, unclosed body is thought.
                # If prefix is empty, model emitted entire response in unclosed tag -> treat as content!
                if prefix:
                    if unclosed_body:
                        reasoning_parts.append(unclosed_body)
                    content = prefix
                else:
                    content = unclosed_body

    # Final safety check: if content is completely empty but reasoning was found,
    # and streaming is done, promote reasoning or extract answer so response is never blank!
    if not is_streaming and not content.strip() and reasoning_parts:
        all_reasoning = "\n\n".join(reasoning_parts).strip()
        split_idx = _find_transition_split(all_reasoning)
        if split_idx is not None:
            thought_part = all_reasoning[:split_idx].strip()
            ans_part = all_reasoning[split_idx:].strip()
            ans_part = re.sub(r"^(?:---|===|\*\*\*)\s*", "", ans_part).strip()
            return thought_part, ans_part
        else:
            # If still nothing in content, promote entire body as content so user sees output
            return "", all_reasoning

    final_reasoning = "\n\n".join(r for r in reasoning_parts if r).strip()
    return final_reasoning, content.strip()


def _find_transition_split(text: str) -> Optional[int]:
    """Find the best split point where internal thinking transitions to user response."""
    if not text:
        return None

    for pat in TRANSITION_PATTERNS:
        matches = list(re.finditer(pat, text, flags=re.IGNORECASE))
        if matches:
            for m in matches:
                if m.start() > 20 or "---" in m.group(0) or "===" in m.group(0):
                    return m.start()
    return None


def get_base_system_prompt(now: Optional[datetime.datetime] = None) -> str:
    """Generate the standard token-efficient base system prompt with dynamic temporal grounding."""
    import datetime

    current = now or datetime.datetime.now().astimezone()
    date_str = current.strftime("%A, %B %d, %Y")
    return (
        f"You are ModelMesh, an intelligent AI assistant.\n"
        f"Current date: {date_str}\n\n"
        f"Guidelines:\n"
        f"- Be direct, accurate, and concise. Avoid unnecessary conversational filler or pleasantries.\n"
        f"- Format responses cleanly using Markdown, syntax-highlighted code blocks, and LaTeX for math ($...$ or $$...$$).\n"
        f"- When addressing recent events, product releases, or time-sensitive topics, anchor your reasoning and search queries to the current date.\n"
        f"- Proactively invoke available tools (such as web search, file operations, calculation, datetime, and skill inspection) whenever real-time information, workspace actions, or computation are required."
    )

