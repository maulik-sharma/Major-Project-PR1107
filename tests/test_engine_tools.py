"""Tests for ChatEngine tool execution loop, iteration limit, and skills prompt injection."""

from pathlib import Path
from modelmesh.core.engine import ChatEngine
from modelmesh.core.registry import ModelRegistry
from modelmesh.core.skills import SkillLoader
from modelmesh.core.tools.builtin import create_builtin_registry
from modelmesh.core.types import (
    ChatRequest,
    EndpointConfig,
    Message,
    ModelConfig,
    ProviderConfig,
    StreamEventType,
    ToolSpec,
)


def test_engine_tool_execution_loop() -> None:
    # 1. Setup registry with mock provider simulating a tool call
    reg = ModelRegistry()
    reg.add_provider(ProviderConfig(id="mock", protocol="mock"))
    model = ModelConfig(
        id="mock-tool-model",
        display_name="Mock Tool Model",
        capabilities=["streaming", "tools"],
        endpoints=[
            EndpointConfig(
                id="mock-tool@mock",
                provider="mock",
                api_model="mock-instant",
                quirks={
                    "simulate_tool_call": {
                        "name": "calculator",
                        "args": {"expression": "25 * 4"},
                    }
                },
            )
        ],
    )
    reg.add_model(model)

    tool_reg = create_builtin_registry()
    engine = ChatEngine(registry=reg, tool_registry=tool_reg)

    req = ChatRequest(
        messages=[Message.from_text(role="user", text="What is 25 * 4?")],
        tools=tool_reg.get_tool_specs(),
    )

    events = list(engine.run_turn(request=req))
    event_types = [e.type for e in events]

    assert StreamEventType.ROUTED in event_types
    assert StreamEventType.TOOL_CALL in event_types
    assert StreamEventType.TOOL_START in event_types
    assert StreamEventType.TOOL_RESULT in event_types
    assert StreamEventType.TEXT_DELTA in event_types
    assert StreamEventType.DONE in event_types

    # Verify tool result event contents
    tool_result_events = [e for e in events if e.type == StreamEventType.TOOL_RESULT]
    assert len(tool_result_events) == 1
    assert tool_result_events[0].data["success"] is True
    assert tool_result_events[0].data["result"]["result"] == 100


def test_engine_tool_loop_iteration_limit() -> None:
    # Setup mock with infinite tool calls
    reg = ModelRegistry()
    reg.add_provider(ProviderConfig(id="mock", protocol="mock"))
    model = ModelConfig(
        id="mock-infinite-model",
        display_name="Mock Infinite Model",
        capabilities=["streaming", "tools"],
        endpoints=[
            EndpointConfig(
                id="mock-inf@mock",
                provider="mock",
                api_model="mock-instant",
                quirks={
                    "simulate_tool_call": {
                        "name": "calculator",
                        "args": {"expression": "1 + 1"},
                    },
                    "simulate_infinite_tool_calls": True,
                },
            )
        ],
    )
    reg.add_model(model)

    tool_reg = create_builtin_registry()
    engine = ChatEngine(registry=reg, tool_registry=tool_reg)

    req = ChatRequest(
        messages=[Message.from_text(role="user", text="Loop forever")],
        tools=tool_reg.get_tool_specs(),
    )

    events = list(engine.run_turn(request=req))
    # Should terminate cleanly with DONE after hitting max 8 iterations
    tool_results = [e for e in events if e.type == StreamEventType.TOOL_RESULT]
    assert len(tool_results) == 8
    assert events[-1].type == StreamEventType.DONE


def test_engine_skills_progressive_disclosure(tmp_path: Path) -> None:
    # Setup skill loader with 1 skill
    skills_dir = tmp_path / "skills"
    code_dir = skills_dir / "code-reviewer"
    code_dir.mkdir(parents=True)
    (code_dir / "SKILL.md").write_text(
        """---
name: code-reviewer
description: Review code quality and style.
---
Check for variable naming conventions.
""",
        encoding="utf-8",
    )

    skill_loader = SkillLoader(skills_dir=skills_dir)
    tool_reg = create_builtin_registry()

    reg = ModelRegistry()
    reg.add_provider(ProviderConfig(id="mock", protocol="mock"))
    model = ModelConfig(
        id="mock-skill-model",
        display_name="Mock Skill Model",
        capabilities=["streaming", "tools"],
        endpoints=[
            EndpointConfig(
                id="mock-skill@mock",
                provider="mock",
                api_model="mock-instant",
            )
        ],
    )
    reg.add_model(model)

    engine = ChatEngine(registry=reg, tool_registry=tool_reg, skill_loader=skill_loader)

    req = ChatRequest(
        messages=[Message.from_text(role="user", text="Please review this function.")],
        tools=tool_reg.get_tool_specs(),
        system_prompt="You are a helpful assistant.",
    )

    events = list(engine.run_turn(request=req))
    assert events[-1].type == StreamEventType.DONE
    # Verify load_skill tool registered
    assert tool_reg.has_tool("load_skill")
