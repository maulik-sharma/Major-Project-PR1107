"""Built-in tool definitions: datetime, safe AST calculator, workspace file reader, and URL fetcher."""

from __future__ import annotations

import ast
import datetime
import math
import operator
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from modelmesh.core.tools.registry import ToolRegistry


# --- 1. Safe AST Calculator ---

SAFE_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

SAFE_FUNCTIONS = {
    "sqrt": math.sqrt,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "log": math.log,
    "log10": math.log10,
    "exp": math.exp,
    "abs": abs,
    "round": round,
    "floor": math.floor,
    "ceil": math.ceil,
    "min": min,
    "max": max,
    "pi": math.pi,
    "e": math.e,
}


def _eval_ast_node(node: ast.AST) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    elif isinstance(node, ast.BinOp):
        left = _eval_ast_node(node.left)
        right = _eval_ast_node(node.right)
        op_type = type(node.op)
        if op_type in SAFE_OPERATORS:
            return SAFE_OPERATORS[op_type](left, right)
        raise ValueError(f"Unsupported binary operator: {op_type.__name__}")
    elif isinstance(node, ast.UnaryOp):
        operand = _eval_ast_node(node.operand)
        op_type = type(node.op)
        if op_type in SAFE_OPERATORS:
            return SAFE_OPERATORS[op_type](operand)
        raise ValueError(f"Unsupported unary operator: {op_type.__name__}")
    elif isinstance(node, ast.Name):
        if node.id in SAFE_FUNCTIONS:
            return SAFE_FUNCTIONS[node.id]
        raise ValueError(f"Unsupported identifier or variable: {node.id}")
    elif isinstance(node, ast.Call):
        func = _eval_ast_node(node.func)
        if not callable(func):
            raise ValueError(f"Not a callable function: {node.func}")
        args = [_eval_ast_node(arg) for arg in node.args]
        return func(*args)
    else:
        raise ValueError(f"Unsupported expression element: {type(node).__name__}")


def calculator(expression: str) -> Dict[str, Any]:
    """Safely parse and evaluate a mathematical expression using an AST parser."""
    clean_expr = expression.strip()
    if not clean_expr:
        return {"error": "Empty expression provided."}

    try:
        parsed = ast.parse(clean_expr, mode="eval")
        result = _eval_ast_node(parsed.body)
        return {
            "expression": clean_expr,
            "result": result,
            "result_str": str(result),
        }
    except Exception as exc:
        return {
            "expression": clean_expr,
            "error": f"Calculation error: {exc}",
        }


# --- 2. Current DateTime Tool ---

def get_current_datetime() -> Dict[str, str]:
    """Return current system date, time, day of week, and timezone offset."""
    now = datetime.datetime.now().astimezone()
    return {
        "iso": now.isoformat(),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "day_of_week": now.strftime("%A"),
        "timezone": str(now.tzinfo),
    }


# --- 3. Local Workspace File Reader ---

def read_text_file(
    path: str,
    max_lines: int = 200,
    workspace_folder: Optional[str] = None,
) -> Dict[str, Any]:
    """Read a local text file safely within a specified workspace folder."""
    root = Path(workspace_folder).resolve() if workspace_folder else Path.cwd().resolve()
    raw_p = Path(path)
    target = raw_p.resolve() if raw_p.is_absolute() else (root / raw_p).resolve()

    # Security check: ensure path is within workspace root
    try:
        target.relative_to(root)
    except ValueError:
        return {
            "error": f"Access denied: Target path '{path}' is outside the configured workspace directory '{root}'."
        }

    if not target.exists():
        return {"error": f"File not found: '{path}'."}
    if not target.is_file():
        return {"error": f"Path is not a regular file: '{path}'."}

    try:
        content = target.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines()
        truncated = len(lines) > max_lines
        selected_lines = lines[:max_lines]

        return {
            "path": path,
            "absolute_path": str(target),
            "line_count": len(lines),
            "lines_shown": len(selected_lines),
            "truncated": truncated,
            "content": "\n".join(selected_lines),
        }
    except Exception as exc:
        return {"error": f"Failed to read file: {exc}"}


# --- 4. URL Fetcher & Web Reader ---

def fetch_url(url: str, max_chars: int = 4000) -> Dict[str, Any]:
    """Fetch content from a URL via HTTP GET and return plain text content."""
    clean_url = url.strip()
    if not clean_url.startswith(("http://", "https://")):
        clean_url = "https://" + clean_url

    try:
        headers = {"User-Agent": "ModelMesh/0.1.0"}
        response = httpx.get(clean_url, headers=headers, timeout=6.0, follow_redirects=True)
        response.raise_for_status()

        text = response.text
        # Simple HTML tag stripping for text extraction
        import re
        text_only = re.sub(r"<script.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text_only = re.sub(r"<style.*?</style>", "", text_only, flags=re.DOTALL | re.IGNORECASE)
        text_only = re.sub(r"<[^>]+>", " ", text_only)
        text_only = re.sub(r"\s+", " ", text_only).strip()

        truncated = len(text_only) > max_chars
        content = text_only[:max_chars]

        return {
            "url": clean_url,
            "status_code": response.status_code,
            "content": content,
            "truncated": truncated,
            "total_chars": len(text_only),
        }
    except Exception as exc:
        return {
            "url": clean_url,
            "error": f"Failed to fetch URL: {exc}",
        }


def create_builtin_registry(workspace_folder: Optional[str] = None) -> ToolRegistry:
    """Create and initialize a ToolRegistry with all standard built-in tools."""
    registry = ToolRegistry(workspace_folder=workspace_folder)

    # Calculator
    registry.register(
        name="calculator",
        description="Safely evaluate a mathematical expression (e.g. '2 + 2', 'sqrt(144) * 3', 'log(100)').",
        parameters={
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "The math expression to evaluate.",
                }
            },
            "required": ["expression"],
        },
        func=calculator,
    )

    # DateTime
    registry.register(
        name="get_current_datetime",
        description="Get the current date, time, day of the week, and timezone.",
        parameters={
            "type": "object",
            "properties": {},
        },
        func=get_current_datetime,
    )

    # Read File
    def _read_file_wrapper(path: str, max_lines: int = 200) -> Dict[str, Any]:
        return read_text_file(path=path, max_lines=max_lines, workspace_folder=registry.workspace_folder)

    registry.register(
        name="read_text_file",
        description="Read the text content of a local file in the project workspace folder.",
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative file path within the workspace directory.",
                },
                "max_lines": {
                    "type": "integer",
                    "description": "Maximum number of lines to return (default: 200).",
                },
            },
            "required": ["path"],
        },
        func=_read_file_wrapper,
    )

    # Fetch URL
    registry.register(
        name="fetch_url",
        description="Fetch a web page via HTTP GET and extract its textual content.",
        parameters={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The web URL to fetch.",
                },
                "max_chars": {
                    "type": "integer",
                    "description": "Maximum character length to return (default: 4000).",
                },
            },
            "required": ["url"],
        },
        func=fetch_url,
    )

    return registry
