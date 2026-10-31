"""Artificial Analysis API client for model intelligence scores."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple
import httpx

from modelmesh.core.errors import ProviderError
from modelmesh.core.keys import get_env_key, load_env

ATTRIBUTION_TEXT: str = "Model scores: Artificial Analysis"


class ArtificialAnalysisClient:
    """Synchronous HTTP client for Artificial Analysis free models API.

    The URL and key variable come from ``scores`` in routing.yaml (Rule 6).
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 15.0,
    ) -> None:
        from modelmesh.core.config.routing_config import load_routing_config

        load_env()
        scores_cfg = load_routing_config().scores
        key_var = scores_cfg.auth_env[0] if scores_cfg.auth_env else ""
        self.api_key = api_key or (get_env_key(key_var) if key_var else None)
        self.key_var = key_var or "(scores.auth_env not set)"
        self.base_url = base_url or scores_cfg.base_url
        self.timeout = timeout

    def fetch_all_models(
        self,
        client: Optional[httpx.Client] = None,
    ) -> Tuple[List[Dict[str, Any]], str, Optional[int]]:
        """Fetch all model records across paginated endpoints.

        Returns:
            Tuple of (models_list, intelligence_index_version, rate_limit_remaining).

        Raises:
            ProviderError: If the API call fails or authentication is missing.
        """
        if not self.api_key:
            raise ProviderError(
                message=f"Missing {self.key_var} in environment or .env",
                category="auth",
                provider_id="artificial_analysis",
                retryable=False,
            )
        if not self.base_url:
            raise ProviderError(
                message="scores.base_url is not set in routing.yaml",
                category="bad_request",
                provider_id="artificial_analysis",
                retryable=False,
            )

        headers = {
            "x-api-key": self.api_key,
            "Accept": "application/json",
        }

        all_models: List[Dict[str, Any]] = []
        index_version = "unknown"
        rate_limit_remaining: Optional[int] = None

        owns_client = client is None
        http_client = client or httpx.Client(timeout=self.timeout)

        try:
            page = 1
            max_pages = 10  # safety cap
            while page <= max_pages:
                url = f"{self.base_url}?page={page}"
                try:
                    resp = http_client.get(url, headers=headers)
                except httpx.TimeoutException as exc:
                    raise ProviderError(
                        message=f"Timeout connecting to Artificial Analysis: {exc}",
                        category="network",
                        provider_id="artificial_analysis",
                        retryable=True,
                    ) from exc
                except httpx.RequestError as exc:
                    raise ProviderError(
                        message=f"Network error querying Artificial Analysis: {exc}",
                        category="network",
                        provider_id="artificial_analysis",
                        retryable=True,
                    ) from exc

                # Parse rate limit remaining if present
                rl_hdr = resp.headers.get("x-ratelimit-remaining")
                if rl_hdr is not None:
                    try:
                        rate_limit_remaining = int(rl_hdr)
                    except ValueError:
                        pass

                if resp.status_code == 401 or resp.status_code == 403:
                    raise ProviderError(
                        message=f"Artificial Analysis authentication failed (status {resp.status_code})",
                        category="auth",
                        provider_id="artificial_analysis",
                        retryable=False,
                    )
                if resp.status_code == 429:
                    raise ProviderError(
                        message="Artificial Analysis rate limit exceeded (100 req/24h)",
                        category="rate_limit",
                        provider_id="artificial_analysis",
                        retryable=True,
                    )
                if resp.status_code >= 500:
                    raise ProviderError(
                        message=f"Artificial Analysis server error (status {resp.status_code})",
                        category="server",
                        provider_id="artificial_analysis",
                        retryable=True,
                    )
                if resp.status_code != 200:
                    raise ProviderError(
                        message=f"Artificial Analysis request failed: {resp.text[:300]}",
                        category="bad_request",
                        provider_id="artificial_analysis",
                        retryable=False,
                    )

                try:
                    payload = resp.json()
                except Exception as exc:
                    raise ProviderError(
                        message=f"Failed to parse Artificial Analysis JSON response: {exc}",
                        category="server",
                        provider_id="artificial_analysis",
                        retryable=False,
                    ) from exc

                index_version = payload.get("intelligence_index_version", index_version)
                page_models = payload.get("data") or payload.get("models") or []
                if isinstance(page_models, list):
                    all_models.extend(page_models)

                pagination = payload.get("pagination", {})
                has_more = pagination.get("has_more", False)
                if not has_more:
                    break
                page += 1

            return all_models, index_version, rate_limit_remaining
        finally:
            if owns_client:
                http_client.close()

    def fetch_snapshot(
        self,
        client: Optional[httpx.Client] = None,
    ) -> Any:
        """Fetch all models and return a complete ScoreSnapshot instance.

        Returns:
            ScoreSnapshot populated with current models and index metadata.
        """
        from modelmesh.core.scores.snapshots import ScoreSnapshot

        models, index_version, remaining = self.fetch_all_models(client=client)
        return ScoreSnapshot.from_raw(
            models_list=models,
            index_version=index_version,
            rate_limit_remaining=remaining,
        )
