"""Model-list APIs: fetch a provider's live catalog and normalise it to ``CatalogEntry``.

Three response shapes, named by ``catalog.format`` in providers.yaml:

- ``openai``: ``GET {base}/models`` -> ``{"data": [{"id", ...}]}``. Servers add
  optional fields that are read when present: ``context_length`` /
  ``context_window``, ``max_completion_tokens`` (or ``top_provider.*``),
  ``pricing.prompt`` / ``pricing.completion`` (USD per token, as strings),
  ``supported_parameters`` / ``supported_features``, input/output modalities
  (top level or under ``architecture``), ``active``, ``shutdown_date``,
  ``expiration_date``.
- ``gemini``: ``GET .../v1beta/models`` -> ``{"models": [...], "nextPageToken"}``
  with ``name`` ("models/x"), ``displayName``, ``inputTokenLimit``,
  ``outputTokenLimit``, ``supportedGenerationMethods``, ``thinking``.
- ``anthropic``: ``GET {base}/v1/models`` -> ``{"data": [...], "has_more", "last_id"}``
  with ``id``, ``display_name``, ``max_input_tokens``, ``max_tokens``,
  ``lifecycle``, ``retires_at``, ``capabilities``.

Field names were checked against live responses; unknown shapes raise instead
of being guessed (Rule 20).
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

import httpx

from modelmesh.core.errors import ProviderError
from modelmesh.core.keys import get_env_key
from modelmesh.core.types import ProviderConfig

MAX_PAGES = 20


@dataclass
class CatalogEntry:
    """One model as a provider's list API describes it (None = the API doesn't say)."""
    api_model: str
    display_name: str
    context_window: Optional[int] = None
    max_output: Optional[int] = None
    price_in_per_mtok: Optional[float] = None
    price_out_per_mtok: Optional[float] = None
    tools: Optional[bool] = None
    vision: Optional[bool] = None
    reasoning: Optional[bool] = None
    chat: bool = True  # text in, text-only out
    retired: bool = False
    retire_note: str = ""  # e.g. "shut down 2026-10-23" or "deprecated, retires 2027-01-05"


def _date(value: Any) -> Optional[datetime.date]:
    if not value:
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.datetime.fromtimestamp(value, tz=datetime.timezone.utc).date()
        return datetime.date.fromisoformat(str(value)[:10])
    except (ValueError, OSError):
        return None


def _per_mtok(value: Any) -> Optional[float]:
    try:
        return round(float(value) * 1_000_000, 6)
    except (TypeError, ValueError):
        return None


def parse_openai_models(payload: Dict[str, Any], today: datetime.date) -> List[CatalogEntry]:
    """Parse an OpenAI-shaped ``/models`` response (OpenAI, Groq, OpenRouter, ...)."""
    if not isinstance(payload.get("data"), list):
        raise ValueError("expected a 'data' list")
    entries: List[CatalogEntry] = []
    for m in payload["data"]:
        if not isinstance(m, dict) or not m.get("id"):
            continue
        arch = m.get("architecture") or {}
        top = m.get("top_provider") or {}
        features = m.get("supported_parameters") or m.get("supported_features")
        inputs = arch.get("input_modalities") or m.get("input_modalities")
        outputs = arch.get("output_modalities") or m.get("output_modalities")
        pricing = m.get("pricing") or {}
        entry = CatalogEntry(
            api_model=str(m["id"]),
            display_name=str(m.get("name") or m["id"]),
            context_window=m.get("context_length") or m.get("context_window") or top.get("context_length"),
            max_output=top.get("max_completion_tokens") or m.get("max_completion_tokens"),
            price_in_per_mtok=_per_mtok(pricing.get("prompt")) if pricing else None,
            price_out_per_mtok=_per_mtok(pricing.get("completion")) if pricing else None,
            tools=("tools" in features) if isinstance(features, list) else None,
            vision=("image" in inputs) if isinstance(inputs, list) else None,
            reasoning=("reasoning" in features) if isinstance(features, list) else None,
            # Text-only output: "text+audio" models are music/speech generators, not chat.
            chat=(not isinstance(outputs, list) or set(outputs) == {"text"})
            and (not isinstance(inputs, list) or "text" in inputs),
        )
        ends = _date(m.get("shutdown_date")) or _date(m.get("expiration_date"))
        if m.get("active") is False:
            entry.retired, entry.retire_note = True, "inactive"
        elif ends is not None:
            entry.retired = ends <= today
            entry.retire_note = f"{'shut down' if entry.retired else 'shuts down'} {ends.isoformat()}"
        entries.append(entry)
    return entries


def parse_gemini_models(payload: Dict[str, Any], today: datetime.date) -> List[CatalogEntry]:
    """Parse a Gemini ``v1beta/models`` page."""
    if not isinstance(payload.get("models"), list):
        raise ValueError("expected a 'models' list")
    entries = []
    for m in payload["models"]:
        name = str(m.get("name") or "")
        if not name:
            continue
        entries.append(CatalogEntry(
            api_model=name.removeprefix("models/"),
            display_name=str(m.get("displayName") or name),
            context_window=m.get("inputTokenLimit"),
            max_output=m.get("outputTokenLimit"),
            reasoning=m.get("thinking") if isinstance(m.get("thinking"), bool) else None,
            chat="generateContent" in (m.get("supportedGenerationMethods") or []),
        ))
    return entries


def parse_anthropic_models(payload: Dict[str, Any], today: datetime.date) -> List[CatalogEntry]:
    """Parse an Anthropic ``/v1/models`` page."""
    if not isinstance(payload.get("data"), list):
        raise ValueError("expected a 'data' list")
    entries = []
    for m in payload["data"]:
        if not m.get("id"):
            continue
        caps = m.get("capabilities") or {}
        lifecycle = m.get("lifecycle") or "active"
        retires = _date(m.get("retires_at"))
        note = ""
        if lifecycle == "retired":
            note = "retired"
        elif lifecycle == "deprecated":
            note = "deprecated" + (f", retires {retires.isoformat()}" if retires else "")
        entries.append(CatalogEntry(
            api_model=str(m["id"]),
            display_name=str(m.get("display_name") or m["id"]),
            context_window=m.get("max_input_tokens") or None,
            max_output=m.get("max_tokens") or None,
            vision=(caps.get("image_input") or {}).get("supported") if caps else None,
            reasoning=(caps.get("thinking") or {}).get("supported") if caps else None,
            retired=lifecycle == "retired",
            retire_note=note,
        ))
    return entries


def _api_key(provider: ProviderConfig) -> str:
    for var in provider.auth_env:
        val = get_env_key(var)
        if val:
            return val
    return ""


def _get_pages(
    client: httpx.Client,
    url: str,
    headers: Dict[str, str],
    first_params: Dict[str, Any],
    next_params: Callable[[Dict[str, Any]], Optional[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    pages, params = [], first_params
    for _ in range(MAX_PAGES):
        resp = client.get(url, headers=headers, params=params)
        resp.raise_for_status()
        page = resp.json()
        pages.append(page)
        follow = next_params(page)
        if not follow:
            break
        params = {**first_params, **follow}
    return pages


def fetch_catalog(
    provider: ProviderConfig,
    client: Optional[httpx.Client] = None,
    today: Optional[datetime.date] = None,
) -> List[CatalogEntry]:
    """Fetch and parse a provider's live model list. Raises ProviderError on failure."""
    cfg = provider.catalog
    if cfg is None:
        raise ProviderError(f"Provider '{provider.id}' has no catalog settings", "bad_request", provider_id=provider.id)
    base = (provider.base_url or "").rstrip("/")
    key = _api_key(provider)
    today = today or datetime.date.today()
    own = client is None
    http = client or httpx.Client(timeout=30.0, follow_redirects=True)
    try:
        if cfg.format == "openai":
            pages = _get_pages(http, cfg.url or f"{base}/models",
                               {"Authorization": f"Bearer {key}"} if key else {}, {}, lambda p: None)
            parse = parse_openai_models
        elif cfg.format == "gemini":
            pages = _get_pages(http, cfg.url or f"{base}/models", {"x-goog-api-key": key}, {"pageSize": 1000},
                               lambda p: {"pageToken": p["nextPageToken"]} if p.get("nextPageToken") else None)
            parse = parse_gemini_models
        elif cfg.format == "anthropic":
            pages = _get_pages(http, cfg.url or f"{base}/v1/models",
                               {"x-api-key": key, "anthropic-version": "2023-06-01"}, {"limit": 1000},
                               lambda p: {"after_id": p["last_id"]} if p.get("has_more") and p.get("last_id") else None)
            parse = parse_anthropic_models
        else:
            raise ProviderError(f"Unknown catalog format '{cfg.format}'", "bad_request", provider_id=provider.id)
        entries: List[CatalogEntry] = []
        for page in pages:
            entries.extend(parse(page, today))
        return entries
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        category = "auth" if status in (401, 403) else "rate_limit" if status == 429 else \
            "server" if status >= 500 else "bad_request"
        raise ProviderError(f"Model list request failed (HTTP {status})", category,  # type: ignore[arg-type]
                            provider_id=provider.id, status_code=status) from exc
    except httpx.RequestError as exc:
        raise ProviderError(f"Couldn't reach the model list: {exc}", "network", retryable=True,
                            provider_id=provider.id) from exc
    except (ValueError, KeyError, TypeError) as exc:
        raise ProviderError(f"Model list has an unexpected format ({exc}); not adapting automatically",
                            "bad_request", provider_id=provider.id) from exc
    finally:
        if own:
            http.close()
