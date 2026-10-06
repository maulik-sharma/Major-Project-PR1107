"""Built-in tool registry and definitions for ModelMesh."""

from __future__ import annotations

import ast
import datetime
import math
import operator
from pathlib import Path
from typing import Any, Dict, Optional

from modelmesh.core.tools.filesystem import (
    list_directory,
    read_text_file,
    search_in_files,
    write_text_file,
)
from modelmesh.core.tools.registry import ToolRegistry
from modelmesh.core.tools.web import fetch_url, web_search


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

def get_current_datetime(timezone: Optional[str] = None) -> Dict[str, str]:
    """Return current system date, time, day of week, and timezone offset."""
    now = datetime.datetime.now().astimezone()
    return {
        "iso": now.isoformat(),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "day_of_week": now.strftime("%A"),
        "timezone": str(now.tzinfo),
    }


def create_builtin_registry(workspace_folder: Optional[str] = None) -> ToolRegistry:
    """Create and initialize a ToolRegistry with all standard built-in tools."""
    registry = ToolRegistry(workspace_folder=workspace_folder)

    # 1. Web Search Tool
    registry.register(
        name="web_search",
        description="Search the web for up-to-date information, documentation, news, or answers.",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search keywords or query.",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of search results to return (default: 5, max: 15).",
                },
            },
            "required": ["query"],
        },
        func=web_search,
    )

    # 2. Fetch URL Tool
    registry.register(
        name="fetch_url",
        description="Fetch a web page via HTTP GET and extract its readable textual content.",
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

    # 3. Read Text File
    def _read_file_wrapper(path: str, max_lines: int = 200) -> Dict[str, Any]:
        return read_text_file(path=path, max_lines=max_lines, workspace_folder=registry.workspace_folder)

    registry.register(
        name="read_text_file",
        description="Read the text content of a local file within the project workspace folder.",
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

    # 4. Write Text File
    def _write_file_wrapper(path: str, content: str, overwrite: bool = True) -> Dict[str, Any]:
        return write_text_file(
            path=path,
            content=content,
            overwrite=overwrite,
            workspace_folder=registry.workspace_folder,
        )

    registry.register(
        name="write_text_file",
        description="Write or create a text file within the project workspace folder.",
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative file path within the workspace directory.",
                },
                "content": {
                    "type": "string",
                    "description": "The text content to write into the file.",
                },
                "overwrite": {
                    "type": "boolean",
                    "description": "Whether to overwrite if file already exists (default: true).",
                },
            },
            "required": ["path", "content"],
        },
        func=_write_file_wrapper,
    )

    # 5. List Directory
    def _list_dir_wrapper(
        path: str = ".",
        recursive: bool = False,
        max_items: int = 100,
    ) -> Dict[str, Any]:
        return list_directory(
            path=path,
            recursive=recursive,
            max_items=max_items,
            workspace_folder=registry.workspace_folder,
        )

    registry.register(
        name="list_directory",
        description="List files and subdirectories inside the workspace directory.",
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative directory path within workspace (default: '.').",
                },
                "recursive": {
                    "type": "boolean",
                    "description": "Whether to traverse subdirectories recursively (default: false).",
                },
                "max_items": {
                    "type": "integer",
                    "description": "Maximum number of items to return (default: 100).",
                },
            },
        },
        func=_list_dir_wrapper,
    )

    # 6. Search in Files (Grep)
    def _search_files_wrapper(
        query: str,
        file_pattern: str = "*",
        case_sensitive: bool = False,
        max_matches: int = 50,
    ) -> Dict[str, Any]:
        return search_in_files(
            query=query,
            file_pattern=file_pattern,
            case_sensitive=case_sensitive,
            max_matches=max_matches,
            workspace_folder=registry.workspace_folder,
        )

    registry.register(
        name="search_in_files",
        description="Search for text or regex pattern across files within the workspace directory.",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Text substring or regex pattern to search for.",
                },
                "file_pattern": {
                    "type": "string",
                    "description": "Glob pattern for filtering file names (e.g. '*.py', '*.md', default: '*').",
                },
                "case_sensitive": {
                    "type": "boolean",
                    "description": "Whether the search is case-sensitive (default: false).",
                },
                "max_matches": {
                    "type": "integer",
                    "description": "Maximum number of matching lines to return (default: 50).",
                },
            },
            "required": ["query"],
        },
        func=_search_files_wrapper,
    )

    # 7. Calculator
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

    # 8. DateTime
    registry.register(
        name="get_current_datetime",
        description="Get the current date, time, day of the week, and timezone.",
        parameters={
            "type": "object",
            "properties": {
                "timezone": {
                    "type": "string",
                    "description": "Optional timezone name.",
                }
            },
        },
        func=get_current_datetime,
    )

    return registry
