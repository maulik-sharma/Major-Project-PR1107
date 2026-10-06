"""Tests for built-in tools (web search, fetch_url, filesystem tools, safe AST calculator, datetime) and ToolRegistry."""

from pathlib import Path
import respx
import httpx

from modelmesh.core.tools.builtin import (
    calculator,
    create_builtin_registry,
    fetch_url,
    get_current_datetime,
    list_directory,
    read_text_file,
    search_in_files,
    web_search,
    write_text_file,
)
from modelmesh.core.tools.registry import ToolRegistry


def test_safe_ast_calculator() -> None:
    res1 = calculator("2 + 2")
    assert res1["result"] == 4

    res2 = calculator("3 * (4 + 5) - 2 ** 3")
    assert res2["result"] == 19

    res3 = calculator("sqrt(144) + log10(100) + abs(-5)")
    assert res3["result"] == 12.0 + 2.0 + 5

    res4 = calculator("round(pi, 2)")
    assert res4["result"] == 3.14

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
    assert len(dt["date"]) == 10


def test_read_and_write_text_file(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    secret_dir = tmp_path / "secret"
    secret_dir.mkdir()

    # 1. Write file in workspace
    write_res = write_text_file(
        path="src/main.py",
        content="print('Hello from workspace!')\n",
        workspace_folder=str(workspace),
    )
    assert write_res["success"] is True
    assert write_res["lines_written"] == 1

    # 2. Read back
    read_res = read_text_file(path="src/main.py", workspace_folder=str(workspace))
    assert "Hello from workspace!" in read_res.get("content", "")

    # 3. Path traversal attack prevention
    secret_file = secret_dir / "passwords.txt"
    secret_file.write_text("secret_data", encoding="utf-8")

    traversal_read = read_text_file(path="../secret/passwords.txt", workspace_folder=str(workspace))
    assert "Access denied" in traversal_read.get("error", "")

    traversal_write = write_text_file(path="../secret/hacked.txt", content="hacked", workspace_folder=str(workspace))
    assert "Access denied" in traversal_write.get("error", "")


def test_list_directory_and_search_in_files(tmp_path: Path) -> None:
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "app.py").write_text("def run():\n    return 'modelmesh'\n", encoding="utf-8")
    sub = ws / "pkg"
    sub.mkdir()
    (sub / "mod.py").write_text("KEYWORD = 'target_value'\n", encoding="utf-8")

    # List directory flat
    listing = list_directory(path=".", recursive=False, workspace_folder=str(ws))
    assert listing["total_items"] >= 2
    names = [it["name"] for it in listing["items"]]
    assert "app.py" in names
    assert "pkg" in names

    # List directory recursive
    rec_listing = list_directory(path=".", recursive=True, workspace_folder=str(ws))
    assert rec_listing["total_items"] >= 3

    # Search in files
    search_res = search_in_files(query="target_value", workspace_folder=str(ws))
    assert search_res["matches_count"] == 1
    assert "pkg/mod.py" in search_res["matches"][0]["file"]
    assert "target_value" in search_res["matches"][0]["line_content"]


@respx.mock
def test_web_search_html_backend() -> None:
    mock_html = """
    <html>
      <body>
        <div class="result results_links">
          <div class="result__body">
            <a class="result__url" href="https://duckduckgo.com/l/?uddg=https%3A%2F%2Ffastapi.tiangolo.com%2F">https://fastapi.tiangolo.com/</a>
            <a class="result__a" href="https://fastapi.tiangolo.com/"><b>FastAPI</b> Official Documentation</a>
            <a class="result__snippet">FastAPI framework, high performance, easy to learn.</a>
          </div>
        </div>
      </div>
    </html>
    """
    respx.post("https://html.duckduckgo.com/html/").mock(
        return_value=httpx.Response(200, text=mock_html)
    )

    res = web_search("FastAPI framework", max_results=5)
    assert res["results_count"] == 1
    item = res["results"][0]
    assert item["title"] == "FastAPI Official Documentation"
    assert item["url"] == "https://fastapi.tiangolo.com/"
    assert "easy to learn" in item["snippet"]


@respx.mock
def test_web_search_fallback_to_api() -> None:
    # Fail HTML & Lite endpoints
    respx.post("https://html.duckduckgo.com/html/").mock(return_value=httpx.Response(500))
    respx.post("https://lite.duckduckgo.com/lite/").mock(return_value=httpx.Response(500))

    # Mock Instant Answer API
    api_json = {
        "Heading": "Python (programming language)",
        "AbstractText": "Python is a high-level general-purpose programming language.",
        "AbstractURL": "https://en.wikipedia.org/wiki/Python_(programming_language)",
        "RelatedTopics": [],
    }
    respx.get("https://api.duckduckgo.com/").mock(
        return_value=httpx.Response(200, json=api_json)
    )

    res = web_search("Python language")
    assert res["results_count"] == 1
    assert res["results"][0]["title"] == "Python (programming language)"
    assert "high-level general-purpose" in res["results"][0]["snippet"]


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


def test_tool_registry_full_suite() -> None:
    reg = create_builtin_registry()
    all_specs = reg.list_all_specs()
    names = [s.name for s in all_specs]

    assert "web_search" in names
    assert "fetch_url" in names
    assert "read_text_file" in names
    assert "write_text_file" in names
    assert "list_directory" in names
    assert "search_in_files" in names
    assert "calculator" in names
    assert "get_current_datetime" in names

    assert reg.get_category("web_search") == "Web & Search"
    assert reg.get_category("read_text_file") == "Filesystem & Workspace"
    assert reg.get_category("calculator") == "Math & Utilities"

    # Execute calculator via registry
    res = reg.execute("calculator", {"expression": "50 * 2"})
    assert res.success is True
    assert res.output["result"] == 100

    # Toggle tool
    reg.set_tool_enabled("web_search", False)
    assert reg.is_tool_enabled("web_search") is False
    assert "web_search" not in [s.name for s in reg.get_tool_specs()]
    assert "web_search" in [s.name for s in reg.list_all_specs()]
