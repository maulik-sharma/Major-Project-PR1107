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
            headers={"content-type": "text/html"},
        )
    )

    res = fetch_url("https://example.com/test")
    assert "content" in res
    assert "Hello World" in res["content"]
    assert "This is content." in res["content"]
    assert "evil()" not in res["content"]
    assert res.get("fetch_method") == "httpx"


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


def test_bot_challenge_detection() -> None:
    from modelmesh.core.tools.web import _is_bot_challenge

    normal_html = "<html><body><h1>Welcome to our site</h1><p>Documentation and guides.</p></body></html>"
    assert _is_bot_challenge(normal_html) is False

    cloudflare_challenge = (
        "<html><head><title>Just a moment...</title></head>"
        "<body><div>Checking your browser before accessing site. Ray ID: 8934789234</div>"
        "<div>cf-browser-verification please verify you are a human</div></body></html>"
    )
    assert _is_bot_challenge(cloudflare_challenge) is True


@respx.mock
def test_web_search_lite_backend() -> None:
    # Fail HTML endpoint
    respx.post("https://html.duckduckgo.com/html/").mock(return_value=httpx.Response(500))

    mock_lite_html = """
    <html>
      <body>
        <table>
          <tr><td><a class="result-link" href="https://duckduckgo.com/l/?uddg=https%3A%2F%2Fpython.org%2F">Python Home</a></td></tr>
          <tr><td class="result-snippet">The official home of Python.</td></tr>
        </table>
      </body>
    </html>
    """
    respx.post("https://lite.duckduckgo.com/lite/").mock(
        return_value=httpx.Response(200, text=mock_lite_html)
    )

    res = web_search("Python", max_results=3)
    assert res["results_count"] == 1
    assert res["results"][0]["title"] == "Python Home"
    assert res["results"][0]["url"] == "https://python.org/"
    assert "official home" in res["results"][0]["snippet"]


def test_web_search_query_limits_and_empty() -> None:
    empty_res = web_search("   ")
    assert empty_res["results_count"] == 0
    assert "Empty search query" in empty_res["error"]

    long_query = "a" * 1000
    # Should not crash, query should be capped at 400 chars
    res = web_search(long_query)
    assert len(res["query"]) <= 400


@respx.mock
def test_fetch_url_limits_and_options() -> None:
    # Empty url
    empty_res = fetch_url("")
    assert "error" in empty_res

    # Normal fetch with max_chars truncation
    long_content = "<p>" + ("A" * 500) + "</p>"
    respx.get("https://example.com/long").mock(
        return_value=httpx.Response(200, text=long_content, headers={"content-type": "text/html"})
    )
    res = fetch_url("https://example.com/long", max_chars=150)
    assert res["truncated"] is True
    assert len(res["content"]) <= 150
    assert res["total_chars"] >= 500


def test_filesystem_limits_and_edge_cases(tmp_path: Path) -> None:
    ws = tmp_path / "workspace"
    ws.mkdir()

    # 1. Overwrite=False
    f = ws / "existing.txt"
    f.write_text("orig", encoding="utf-8")
    write_res = write_text_file("existing.txt", "new", overwrite=False, workspace_folder=str(ws))
    assert "File already exists" in write_res.get("error", "")

    # 2. Max lines reading
    f_many = ws / "many_lines.txt"
    f_many.write_text("\n".join(f"line {i}" for i in range(50)), encoding="utf-8")
    read_res = read_text_file("many_lines.txt", max_lines=10, workspace_folder=str(ws))
    assert read_res["lines_shown"] == 10
    assert read_res["truncated"] is True
    assert read_res["line_count"] == 50

    # 3. Content too large for write (MAX_WRITE_BYTES)
    huge_content = "x" * 600_000
    huge_res = write_text_file("huge.txt", huge_content, workspace_folder=str(ws))
    assert "too large" in huge_res.get("error", "").lower()

    # 4. Search in files case sensitivity and pattern filter
    (ws / "doc.md").write_text("FIND_ME here\n", encoding="utf-8")
    (ws / "doc.txt").write_text("find_me here\n", encoding="utf-8")

    case_res = search_in_files("FIND_ME", case_sensitive=True, file_pattern="*.md", workspace_folder=str(ws))
    assert case_res["matches_count"] == 1
    assert "doc.md" in case_res["matches"][0]["file"]

    # Search with empty query
    empty_s = search_in_files("", workspace_folder=str(ws))
    assert empty_s["matches_count"] == 0
    assert "Empty search query" in empty_s.get("error", "")

