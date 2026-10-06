"""Web search and URL fetching tools with multi-tier bot-detection mitigation.

Uses httpx for fast requests with realistic headers, falling back to a headless
Playwright browser for sites that reject plain HTTP clients.  HTML is cleaned
with BeautifulSoup + html2text for high-fidelity readable output.
"""

from __future__ import annotations

import logging
import re
import urllib.parse
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants & shared headers
# ---------------------------------------------------------------------------

MAX_QUERY_LENGTH = 400
MAX_RESULTS_CAP = 15
MAX_FETCH_CHARS_CAP = 50_000
DEFAULT_FETCH_CHARS = 8000
DEFAULT_SEARCH_RESULTS = 5
HTTP_TIMEOUT = 12.0

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Ch-Ua": '"Chromium";v="128", "Not;A=Brand";v="24", "Google Chrome";v="128"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "DNT": "1",
    "Connection": "keep-alive",
}

# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------


def _html_to_text(raw_html: str) -> str:
    """Convert HTML to readable text via html2text (preferred) or regex fallback."""
    try:
        import html2text

        h = html2text.HTML2Text()
        h.ignore_links = False
        h.ignore_images = True
        h.ignore_tables = False
        h.body_width = 0  # no line-wrapping
        h.skip_internal_links = True
        h.ignore_emphasis = False
        return h.handle(raw_html).strip()
    except ImportError:
        pass

    # Regex fallback
    text = re.sub(r"<script.*?</script>", "", raw_html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<noscript.*?</noscript>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<svg.*?</svg>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", text).strip()


def _clean_snippet(raw_html: str) -> str:
    """Strip HTML tags from a small snippet, preserving text only."""
    text = re.sub(r"<[^>]+>", "", raw_html)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", text).strip()


def _decode_ddg_url(raw_url: str) -> str:
    """Extract actual destination URL from DuckDuckGo redirect link."""
    if "duckduckgo.com/l/?" in raw_url or "uddg=" in raw_url:
        parsed = urllib.parse.urlparse(raw_url)
        params = urllib.parse.parse_qs(parsed.query)
        if "uddg" in params and params["uddg"]:
            return params["uddg"][0]
    return raw_url


# ---------------------------------------------------------------------------
# Search backends
# ---------------------------------------------------------------------------


def _search_ddg_html(query: str, max_results: int) -> List[Dict[str, str]]:
    """Primary search backend: DuckDuckGo HTML endpoint with browser emulation."""
    results: List[Dict[str, str]] = []
    url = "https://html.duckduckgo.com/html/"
    data = {"q": query}
    headers = dict(BROWSER_HEADERS)
    headers["Origin"] = "https://html.duckduckgo.com"
    headers["Referer"] = "https://html.duckduckgo.com/"
    headers["Sec-Fetch-Site"] = "same-origin"

    try:
        response = httpx.post(url, data=data, headers=headers, timeout=HTTP_TIMEOUT, follow_redirects=True)
    except Exception as exc:
        logger.debug("DDG HTML POST failed: %s", exc)
        return results
    if response.status_code != 200:
        return results

    html = response.text

    # Try with BeautifulSoup first for reliable extraction
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        for result_div in soup.select("div.result.results_links, div.result"):
            if len(results) >= max_results:
                break

            # Find result link
            a_tag = result_div.select_one("a.result__a")
            if not a_tag:
                a_tag = result_div.select_one("a.result__url")
            if not a_tag:
                a_tag = result_div.find("a", href=True)
            if not a_tag:
                continue

            raw_href = a_tag.get("href", "")
            title = " ".join(a_tag.get_text(separator=" ").split()) or "Search Result"
            clean_url = _decode_ddg_url(raw_href)

            # Find snippet
            snippet_tag = result_div.select_one("a.result__snippet")
            if not snippet_tag:
                snippet_tag = result_div.select_one("div.result__snippet")
            if not snippet_tag:
                snippet_tag = result_div.select_one(".result__snippet")
            snippet = " ".join(snippet_tag.get_text(separator=" ").split()) if snippet_tag else ""

            if clean_url and clean_url.startswith("http"):
                results.append({
                    "title": title or clean_url,
                    "url": clean_url,
                    "snippet": snippet or "No snippet available.",
                })
        if results:
            return results
    except ImportError:
        pass

    # Regex fallback
    blocks = re.findall(
        r'<div class="result results_links[^"]*">(.*?)</div>\s*</div>',
        html,
        re.DOTALL,
    )
    if not blocks:
        blocks = re.findall(r'<div class="[^"]*result[^"]*">(.*?)</div>\s*</div>', html, re.DOTALL)

    for block in blocks:
        if len(results) >= max_results:
            break

        a_match = re.search(r'<a class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', block, re.DOTALL)
        if not a_match:
            a_match = re.search(r'<a [^>]*href="([^"]+)"[^>]*>(.*?)</a>', block, re.DOTALL)
        if not a_match:
            continue

        raw_href = a_match.group(1)
        title = _clean_snippet(a_match.group(2)) or "Search Result"
        clean_url = _decode_ddg_url(raw_href)

        snippet_match = re.search(
            r'<a class="result__snippet[^"]*"[^>]*>(.*?)</a>'
            r'|<div class="result__snippet[^"]*"[^>]*>(.*?)</div>',
            block,
            re.DOTALL,
        )
        snippet = ""
        if snippet_match:
            snippet_html = snippet_match.group(1) or snippet_match.group(2) or ""
            snippet = _clean_snippet(snippet_html)

        if clean_url and clean_url.startswith("http"):
            results.append({
                "title": title or clean_url,
                "url": clean_url,
                "snippet": snippet or "No snippet available.",
            })

    return results


def _search_ddg_lite(query: str, max_results: int) -> List[Dict[str, str]]:
    """Secondary search backend: DuckDuckGo Lite endpoint."""
    results: List[Dict[str, str]] = []
    url = "https://lite.duckduckgo.com/lite/"
    headers = dict(BROWSER_HEADERS)
    headers["Referer"] = "https://lite.duckduckgo.com/"

    try:
        response = httpx.post(url, data={"q": query}, headers=headers, timeout=HTTP_TIMEOUT, follow_redirects=True)
    except Exception as exc:
        logger.debug("DDG Lite POST failed: %s", exc)
        return results
    if response.status_code != 200:
        return results

    html = response.text

    # Try with BeautifulSoup
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")

        # DDG Lite uses a table-based layout
        link_tags = soup.select("a.result-link")
        snippet_tags = soup.select("td.result-snippet")

        for i, a_tag in enumerate(link_tags):
            if len(results) >= max_results:
                break
            href = a_tag.get("href", "")
            title = a_tag.get_text(strip=True)
            clean_url = _decode_ddg_url(href)
            snippet = snippet_tags[i].get_text(strip=True) if i < len(snippet_tags) else ""

            if clean_url and clean_url.startswith("http"):
                results.append({
                    "title": title or clean_url,
                    "url": clean_url,
                    "snippet": snippet or "No snippet available.",
                })
        if results:
            return results
    except ImportError:
        pass

    # Regex fallback
    links = re.findall(r'<a class="result-link"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html, re.DOTALL)
    snippets = re.findall(r'<td class="result-snippet"[^>]*>(.*?)</td>', html, re.DOTALL)

    for i, (href, title_html) in enumerate(links):
        if len(results) >= max_results:
            break
        clean_url = _decode_ddg_url(href)
        title = _clean_snippet(title_html)
        snippet = _clean_snippet(snippets[i]) if i < len(snippets) else ""

        if clean_url and clean_url.startswith("http"):
            results.append({
                "title": title or clean_url,
                "url": clean_url,
                "snippet": snippet or "No snippet available.",
            })

    return results


def _search_ddg_api(query: str, max_results: int) -> List[Dict[str, str]]:
    """Tertiary fallback backend: DuckDuckGo Instant Answer JSON API."""
    results: List[Dict[str, str]] = []
    url = "https://api.duckduckgo.com/"
    params = {"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"}
    headers = {"User-Agent": BROWSER_HEADERS["User-Agent"]}

    try:
        response = httpx.get(url, params=params, headers=headers, timeout=HTTP_TIMEOUT, follow_redirects=True)
    except Exception as exc:
        logger.debug("DDG API failed: %s", exc)
        return results
    if response.status_code != 200:
        return results

    data = response.json()
    abstract = data.get("AbstractText")
    abstract_url = data.get("AbstractURL")
    heading = data.get("Heading")

    if abstract and abstract_url:
        results.append({
            "title": heading or query,
            "url": abstract_url,
            "snippet": abstract,
        })

    for topic in data.get("RelatedTopics", []):
        if len(results) >= max_results:
            break
        if "Text" in topic and "FirstURL" in topic:
            results.append({
                "title": topic.get("Text", "")[:80],
                "url": topic.get("FirstURL", ""),
                "snippet": topic.get("Text", ""),
            })

    return results


# ---------------------------------------------------------------------------
# Public: web_search
# ---------------------------------------------------------------------------


def web_search(query: str, max_results: int = DEFAULT_SEARCH_RESULTS) -> Dict[str, Any]:
    """Search the web using multi-backend DuckDuckGo endpoints with bot-detection mitigation.

    Args:
        query: The search keywords or question (max 400 characters).
        max_results: Maximum number of search results to return (1-15, default: 5).

    Returns:
        Dict with 'query', 'results_count', and 'results' list.
    """
    clean_query = query.strip()[:MAX_QUERY_LENGTH]
    if not clean_query:
        return {"query": query, "results_count": 0, "results": [], "error": "Empty search query."}

    max_r = max(1, min(MAX_RESULTS_CAP, max_results))
    errors: List[str] = []

    backends = [
        ("HTML", _search_ddg_html),
        ("Lite", _search_ddg_lite),
        ("API", _search_ddg_api),
    ]

    for name, backend_fn in backends:
        try:
            results = backend_fn(clean_query, max_r)
            if results:
                return {"query": clean_query, "results_count": len(results), "results": results}
        except Exception as exc:
            errors.append(f"{name} backend error: {exc}")
            logger.debug("Search backend %s failed: %s", name, exc)

    return {
        "query": clean_query,
        "results_count": 0,
        "results": [],
        "error": (
            f"Search failed across all endpoints: {'; '.join(errors)}"
            if errors
            else "No results found."
        ),
    }


# ---------------------------------------------------------------------------
# URL Fetching: multi-tier (httpx → Playwright)
# ---------------------------------------------------------------------------


def _fetch_httpx(url: str) -> Optional[str]:
    """Tier 1: Fast httpx GET with browser-like headers."""
    response = httpx.get(
        url,
        headers=BROWSER_HEADERS,
        timeout=HTTP_TIMEOUT,
        follow_redirects=True,
    )
    response.raise_for_status()

    content_type = response.headers.get("content-type", "")
    if "text" not in content_type and "html" not in content_type and "json" not in content_type:
        return None  # binary content, skip

    return response.text


def _fetch_playwright(url: str) -> Optional[str]:
    """Tier 2: Headless Chromium via Playwright for bot-protected pages."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.debug("Playwright not available for headless fetch.")
        return None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-gpu",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                ],
            )
            context = browser.new_context(
                user_agent=BROWSER_HEADERS["User-Agent"],
                viewport={"width": 1920, "height": 1080},
                locale="en-US",
                java_script_enabled=True,
            )
            page = context.new_page()

            # Block unnecessary resources to speed up loading
            def _route_handler(route: Any) -> None:
                resource = route.request.resource_type
                if resource in ("image", "media", "font", "stylesheet"):
                    route.abort()
                else:
                    route.fallback()

            page.route("**/*", _route_handler)

            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            # Give JS time to hydrate
            page.wait_for_timeout(2000)

            html = page.content()
            browser.close()
            return html
    except Exception as exc:
        logger.debug("Playwright fetch failed for %s: %s", url, exc)
        return None


def fetch_url(url: str, max_chars: int = DEFAULT_FETCH_CHARS) -> Dict[str, Any]:
    """Fetch content from a URL with multi-tier bot evasion and clean text extraction.

    Tries fast httpx first, falls back to headless Playwright for bot-protected sites.

    Args:
        url: Target web URL to fetch.
        max_chars: Maximum character count to extract (default: 8000, max: 50000).

    Returns:
        Dict with URL, status code, readable extracted content, and length info.
    """
    clean_url = url.strip()
    if not clean_url:
        return {"url": url, "error": "Empty URL provided."}

    if not clean_url.startswith(("http://", "https://")):
        clean_url = "https://" + clean_url

    max_chars = max(100, min(MAX_FETCH_CHARS_CAP, max_chars))
    errors: List[str] = []
    fetch_method = "httpx"

    # Tier 1: httpx
    raw_html: Optional[str] = None
    try:
        raw_html = _fetch_httpx(clean_url)
    except Exception as exc:
        errors.append(f"httpx: {exc}")
        logger.debug("Tier 1 httpx failed for %s: %s", clean_url, exc)

    # Verify the page isn't a bot challenge (common patterns)
    if raw_html and _is_bot_challenge(raw_html):
        logger.debug("Bot challenge detected for %s, escalating to Playwright", clean_url)
        raw_html = None
        errors.append("httpx: bot challenge detected")

    # Tier 2: Playwright headless
    if raw_html is None:
        try:
            raw_html = _fetch_playwright(clean_url)
            if raw_html:
                fetch_method = "playwright"
        except Exception as exc:
            errors.append(f"playwright: {exc}")
            logger.debug("Tier 2 Playwright failed for %s: %s", clean_url, exc)

    if raw_html is None:
        return {
            "url": clean_url,
            "error": f"Failed to fetch URL after all tiers: {'; '.join(errors)}",
        }

    text_only = _html_to_text(raw_html)
    truncated = len(text_only) > max_chars
    content = text_only[:max_chars]

    return {
        "url": clean_url,
        "content": content,
        "truncated": truncated,
        "total_chars": len(text_only),
        "fetch_method": fetch_method,
    }


def _is_bot_challenge(html: str) -> bool:
    """Detect common anti-bot challenge pages (Cloudflare, CAPTCHAs, etc.)."""
    indicators = [
        "cf-browser-verification",
        "challenge-platform",
        "just a moment",
        "checking your browser",
        "ray id",
        "cloudflare",
        "captcha",
        "access denied",
        "please verify you are a human",
        "enable javascript and cookies",
        "bot protection",
    ]
    lower = html[:5000].lower()
    matches = sum(1 for ind in indicators if ind in lower)
    # Need at least 2 indicators to avoid false positives
    return matches >= 2
