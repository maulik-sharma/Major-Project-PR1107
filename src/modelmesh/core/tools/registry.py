"""Tool registry and execution engine for model tool-calling."""

from __future__ import annotations

import inspect
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from modelmesh.core.types import ToolSpec


@dataclass
class ToolExecutionResult:
    """Result of a tool execution."""
    tool_name: str
    arguments: Dict[str, Any]
    output: Any
    success: bool
    error: Optional[str] = None
    duration_ms: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "output": self.output,
            "success": self.success,
            "error": self.error,
            "duration_ms": self.duration_ms,
        }


class ToolRegistry:
    """Central registry for declaring and executing LLM-callable tools."""

    def __init__(self, workspace_folder: Optional[str] = None) -> None:
        self._tools: Dict[str, ToolSpec] = {}
        self._handlers: Dict[str, Callable[..., Any]] = {}
        self._disabled_tools: set[str] = set()
        self.workspace_folder = workspace_folder or str(Path.cwd())

    def set_workspace_folder(self, folder: str) -> None:
        """Set active workspace directory for filesystem tools."""
        self.workspace_folder = folder

    def set_tool_enabled(self, name: str, enabled: bool) -> None:
        """Enable or disable a specific tool."""
        if enabled:
            self._disabled_tools.discard(name)
        else:
            self._disabled_tools.add(name)

    def is_tool_enabled(self, name: str) -> bool:
        """Check if a tool is enabled."""
        return name in self._tools and name not in self._disabled_tools

    def register(
        self,
        name: str,
        description: str,
        parameters: Dict[str, Any],
        func: Callable[..., Any],
    ) -> None:
        """Register a tool with explicit ToolSpec parameters and a callable."""
        spec = ToolSpec(name=name, description=description, parameters=parameters)
        self._tools[name] = spec
        self._handlers[name] = func

    def get_tool_specs(self) -> List[ToolSpec]:
        """Return all registered and enabled ToolSpecs."""
        return [
            spec for name, spec in self._tools.items()
            if name not in self._disabled_tools
        ]

    def list_all_specs(self) -> List[ToolSpec]:
        """Return all registered ToolSpecs regardless of enabled state."""
        return list(self._tools.values())

    def get_category(self, name: str) -> str:
        """Get the functional category for a tool."""
        if name in ("web_search", "fetch_url"):
            return "Web & Search"
        elif name in ("read_text_file", "write_text_file", "list_directory", "search_in_files"):
            return "Filesystem & Workspace"
        elif name in ("calculator", "get_current_datetime"):
            return "Math & Utilities"
        elif name.startswith("load_skill") or name == "load_skill":
            return "Skills"
        return "Custom"

    def get_spec(self, name: str) -> Optional[ToolSpec]:
        """Get ToolSpec for a given tool name."""
        return self._tools.get(name)

    def has_tool(self, name: str) -> bool:
        """Check if a tool is registered."""
        return name in self._tools

    def execute(self, name: str, arguments: Dict[str, Any]) -> ToolExecutionResult:
        """Execute a tool with given arguments and record timing and status."""
        start_time = time.time()
        if name not in self._handlers:
            return ToolExecutionResult(
                tool_name=name,
                arguments=arguments,
                output=None,
                success=False,
                error=f"Tool '{name}' is not registered in ToolRegistry.",
                duration_ms=0,
            )

        handler = self._handlers[name]
        try:
            # Execute handler with kwargs or positional
            if isinstance(arguments, dict):
                output = handler(**arguments)
            else:
                output = handler()
            duration_ms = int((time.time() - start_time) * 1000)
            return ToolExecutionResult(
                tool_name=name,
                arguments=arguments,
                output=output,
                success=True,
                error=None,
                duration_ms=duration_ms,
            )
        except Exception as exc:
            duration_ms = int((time.time() - start_time) * 1000)
            return ToolExecutionResult(
                tool_name=name,
                arguments=arguments,
                output=None,
                success=False,
                error=str(exc),
                duration_ms=duration_ms,
            )
