"""Unit tests for robust thinking, reasoning, and content formatting."""

from modelmesh.core.formatting import extract_reasoning_and_content


def test_standard_closed_thought_tags() -> None:
    raw = "<thought>1. Parse input\n2. Compute result</thought>The final answer is 42."
    reasoning, content = extract_reasoning_and_content(raw)
    assert reasoning == "1. Parse input\n2. Compute result"
    assert content == "The final answer is 42."


def test_multiple_reasoning_blocks() -> None:
    raw = (
        "<think>Initial setup</think>"
        "Here is step 1."
        "<thought>Checking edge cases</thought>"
        "Here is step 2."
    )
    reasoning, content = extract_reasoning_and_content(raw)
    assert "Initial setup" in reasoning
    assert "Checking edge cases" in reasoning
    assert "Here is step 1." in content
    assert "Here is step 2." in content


def test_unclosed_thought_with_transition_marker() -> None:
    # Real-world scenario from conversation 4e57c27a
    raw = (
        "<thought>* Target: Give ATS score\n"
        "- LaTeX is clean\n"
        "Score: 94/100.\n"
        "I'll format the output as a professional evaluation.\n\n"
        "---\n"
        "**ATS Score Estimate: 94/100**\n\n"
        "### **Executive Summary**\n"
        "This is a top-tier technical resume."
    )
    reasoning, content = extract_reasoning_and_content(raw, is_streaming=False)
    assert "Target: Give ATS score" in reasoning
    assert "LaTeX is clean" in reasoning
    assert "**ATS Score Estimate: 94/100**" in content
    assert "### **Executive Summary**" in content
    assert "This is a top-tier technical resume." in content


def test_unclosed_thought_with_header_transition() -> None:
    raw = (
        "<thought>Analyzing the problem.\n"
        "Let's write the response.\n\n"
        "# Solution Overview\n"
        "Here is the complete implementation."
    )
    reasoning, content = extract_reasoning_and_content(raw, is_streaming=False)
    assert "Analyzing the problem." in reasoning
    assert "# Solution Overview" in content
    assert "Here is the complete implementation." in content


def test_unclosed_thought_without_transition_promotes_to_content() -> None:
    # If the model put everything inside <thought> by mistake without clear split
    raw = "<thought>Hello! How can I assist you with your project today?"
    reasoning, content = extract_reasoning_and_content(raw, is_streaming=False)
    assert content == "Hello! How can I assist you with your project today?"
    assert reasoning == ""


def test_explicit_reasoning_and_content_combination() -> None:
    raw = "Here is the answer."
    explicit = "Explicit reasoning from provider delta"
    reasoning, content = extract_reasoning_and_content(raw, explicit_reasoning=explicit)
    assert reasoning == "Explicit reasoning from provider delta"
    assert content == "Here is the answer."


def test_legacy_blank_content_recovery() -> None:
    # Simulates loading a corrupted row where content was stored inside reasoning
    legacy_reasoning = (
        "Planning steps...\n"
        "---\n"
        "**Final Score: 100/100**\n"
        "Everything passed."
    )
    reasoning, content = extract_reasoning_and_content(raw_text="", explicit_reasoning=legacy_reasoning)
    assert "Planning steps..." in reasoning
    assert "**Final Score: 100/100**" in content
    assert "Everything passed." in content


def test_get_base_system_prompt() -> None:
    import datetime
    from modelmesh.core.formatting import get_base_system_prompt

    fixed_time = datetime.datetime(2026, 10, 6, 12, 0, 0, tzinfo=datetime.timezone.utc)
    prompt = get_base_system_prompt(now=fixed_time)

    assert "Current date: Tuesday, October 06, 2026" in prompt
    assert "You are ModelMesh, an intelligent AI assistant." in prompt
    assert "Markdown" in prompt
    assert "tools" in prompt.lower()

