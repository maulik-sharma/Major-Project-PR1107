"""Web search and URL fetching tools with bot-detection mitigation."""

from __future__ import annotations

import re
import urllib.parse
from typing import Any, Dict, List, Optional

import httpx

# Realistic browser headers to avoid bot detection
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
}


def _clean_html_text(raw_html: str) -> str:
    """Strip scripts, styles, and tags, returning clean readable text."""
    text = re.sub(r"<script.*?</script>", "", raw_html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<noscript.*?</noscript>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<svg.*?</svg>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    # Unescape common HTML entities
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


def _search_ddg_html(query: str, max_results: int) -> List[Dict[str, str]]:
    """Primary search backend: DuckDuckGo HTML endpoint with browser emulation."""
    results: List[Dict[str, str]] = []
    url = "https://html.duckduckgo.com/html/"
    data = {"q": query}
    headers = dict(BROWSER_HEADERS)
    headers["Origin"] = "https://html.duckduckgo.com"
    headers["Referer"] = "https://html.duckduckgo.com/"
    headers["Sec-Fetch-Site"] = "same-origin"

    response = httpx.post(url, data=data, headers=headers, timeout=8.0, follow_redirects=True)
    if response.status_code != 200:
        return results

    html = response.text
    blocks = re.findall(r'<div class="result results_links[^"]*">(.*?)</div>\s*</div>', html, re.DOTALL)
    if not blocks:
        blocks = re.findall(r'<div class="[^"]*result[^"]*">(.*?)</div>\s*</div>', html, re.DOTALL)

    for block in blocks:
        if len(results) >= max_results:
            break

        # Extract title and URL from result__a tag
        a_match = re.search(r'<a class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', block, re.DOTALL)
        if not a_match:
            a_match = re.search(r'<a class="result__url"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', block, re.DOTALL)
        if not a_match:
            a_match = re.search(r'<a [^>]*href="([^"]+)"[^>]*>(.*?)</a>', block, re.DOTALL)

        if not a_match:
            continue

        raw_href = a_match.group(1) or ""
        title_html = a_match.group(2) or ""
        title = _clean_html_text(title_html) if title_html else "Search Result"
        clean_url = _decode_ddg_url(raw_href)

        snippet_match = re.search(
            r'<a class="result__snippet[^"]*"[^>]*>(.*?)</a>|<div class="result__snippet[^"]*"[^>]*>(.*?)</div>',
            block,
            re.DOTALL,
        )
        snippet = ""
        if snippet_match:
            snippet_html = snippet_match.group(1) or snippet_match.group(2) or ""
            snippet = _clean_html_text(snippet_html)

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

    response = httpx.post(url, data={"q": query}, headers=headers, timeout=8.0, follow_redirects=True)
    if response.status_code != 200:
        return results

    html = response.text
    links = re.findall(r'<a class="result-link"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html, re.DOTALL)
    snippets = re.findall(r'<td class="result-snippet"[^>]*>(.*?)</td>', html, re.DOTALL)

    for i, (href, title_html) in enumerate(links):
        if len(results) >= max_results:
            break
        clean_url = _decode_ddg_url(href)
        title = _clean_html_text(title_html)
        snippet = _clean_html_text(snippets[i]) if i < len(snippets) else ""

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

    response = httpx.get(url, params=params, headers=headers, timeout=6.0, follow_redirects=True)
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
                "title": topic.get("Text", "")[:60] + "...",
                "url": topic.get("FirstURL", ""),
                "snippet": topic.get("Text", ""),
            })

    return results


def web_search(query: str, max_results: int = 5) -> Dict[str, Any]:
    """Search the web using multi-backend DuckDuckGo endpoints with bot-detection mitigation.

    Args:
        query: The search keywords or question.
        max_results: Maximum number of search results to return (default: 5).

    Returns:
        Dict with 'query', 'results_count', and 'results' list.
    """
    clean_query = query.strip()
    if not clean_query:
        return {"query": query, "results_count": 0, "results": [], "error": "Empty search query."}

    max_r = max(1, min(15, max_results))
    errors = []

    # Backend 1: DDG HTML
    try:
        results = _search_ddg_html(clean_query, max_r)
        if results:
            return {"query": clean_query, "results_count": len(results), "results": results}
    except Exception as exc:
        errors.append(f"HTML backend error: {exc}")

    # Backend 2: DDG Lite
    try:
        results = _search_ddg_lite(clean_query, max_r)
        if results:
            return {"query": clean_query, "results_count": len(results), "results": results}
    except Exception as exc:
        errors.append(f"Lite backend error: {exc}")

    # Backend 3: DDG API
    try:
        results = _search_ddg_api(clean_query, max_r)
        if results:
            return {"query": clean_query, "results_count": len(results), "results": results}
    except Exception as exc:
        errors.append(f"API backend error: {exc}")

    return {
        "query": clean_query,
        "results_count": 0,
        "results": [],
        "error": f"Search failed across all endpoints: {'; '.join(errors)}" if errors else "No results found.",
    }


def fetch_url(url: str, max_chars: int = 4000) -> Dict[str, Any]:
    """Fetch content from a URL via HTTP GET with browser emulation and extract text.

    Args:
        url: Target web URL to fetch.
        max_chars: Maximum character count to extract (default: 4000).

    Returns:
        Dict with URL, status code, readable extracted content, and length info.
    """
    clean_url = url.strip()
    if not clean_url.startswith(("http://", "https://")):
        clean_url = "https://" + clean_url

    try:
        response = httpx.get(
            clean_url,
            headers=BROWSER_HEADERS,
            timeout=8.0,
            follow_redirects=True,
        )
        response.raise_for_status()

        text_only = _clean_html_text(response.text)
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
