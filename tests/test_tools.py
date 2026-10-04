"""Tests for built-in tools (safe AST calculator, datetime, file reader, fetch_url) and ToolRegistry."""

from pathlib import Path
import respx
import httpx

from modelmesh.core.tools.builtin import (
    calculator,
    create_builtin_registry,
    fetch_url,
    get_current_datetime,
    read_text_file,
)
from modelmesh.core.tools.registry import ToolRegistry


def test_safe_ast_calculator() -> None:
    # Basic math
    res1 = calculator("2 + 2")
    assert res1["result"] == 4

    # Precedence and power
    res2 = calculator("3 * (4 + 5) - 2 ** 3")
    assert res2["result"] == 19

    # Functions
    res3 = calculator("sqrt(144) + log10(100) + abs(-5)")
    assert res3["result"] == 12.0 + 2.0 + 5

    # Safe constants
    res4 = calculator("round(pi, 2)")
    assert res4["result"] == 3.14

    # Security: Reject unsafe arbitrary code execution
    bad1 = calculator("__import__('os').system('ls')")
    assert "error" in bad1

    bad2 = calculator("eval('1+1')")
    assert "error" in bad2


def test_get_current_datetime() -> None:
    dt = get_current_datetime()
    assert "iso" in dt
    assert "date" in dt
    assert "time" in dt
    assert "day_of_week" in dt
    assert "timezone" in dt
    assert len(dt["date"]) == 10  # YYYY-MM-DD


def test_read_text_file_security(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    secret_dir = tmp_path / "secret"
    secret_dir.mkdir()

    safe_file = workspace / "safe.txt"
    safe_file.write_text("Hello workspace\nLine 2", encoding="utf-8")

    secret_file = secret_dir / "passwords.txt"
    secret_file.write_text("secret_data", encoding="utf-8")

    # Safe read
    res1 = read_text_file(path="safe.txt", workspace_folder=str(workspace))
    assert res1.get("content") == "Hello workspace\nLine 2"
    assert res1.get("line_count") == 2

    # Path traversal attack prevention
    res2 = read_text_file(path="../secret/passwords.txt", workspace_folder=str(workspace))
    assert "Access denied" in res2.get("error", "")


@respx.mock
def test_fetch_url() -> None:
    respx.get("https://example.com/test").mock(
        return_value=httpx.Response(
            200,
            text="<html><head><title>Test</title></head><body><h1>Hello World</h1><script>evil()</script><p>This is content.</p></body></html>",
        )
    )

    res = fetch_url("https://example.com/test")
    assert res["status_code"] == 200
    assert "Hello World" in res["content"]
    assert "This is content." in res["content"]
    assert "evil()" not in res["content"]


def test_tool_registry_execution() -> None:
    reg = create_builtin_registry()
    specs = reg.get_tool_specs()
    names = [s.name for s in specs]
    assert "calculator" in names
    assert "get_current_datetime" in names
    assert "read_text_file" in names
    assert "fetch_url" in names

    # Execute calculator via registry
    res = reg.execute("calculator", {"expression": "50 * 2"})
    assert res.success is True
    assert res.output["result"] == 100
    assert res.duration_ms >= 0

    # Unregistered tool
    bad_res = reg.execute("nonexistent_tool", {})
    assert bad_res.success is False
    assert "not registered" in bad_res.error
