"""Cloudflare Workers AI Clef / Clef-flash decision provider adapter."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional
import httpx

from modelmesh.core.errors import ProviderError
from modelmesh.core.keys import get_env_key, load_env
from modelmesh.core.routing.smart.decision.base import (
    DecisionProvider,
    DecisionRequest,
    DecisionResult,
    register_decision_provider,
)
from modelmesh.core.types import Usage


@register_decision_provider("cloudflare_decision")
class CloudflareDecisionAdapter(DecisionProvider):
    """Adapter for Cloudflare Workers AI Clef decision models.

    Configured from ``routing.yaml``: ``auth_env`` lists the account-id variable
    then the API-token variable; ``base_url`` may contain ``{account_id}``.
    """

    remote = True

    def __init__(
        self,
        account_id: Optional[str] = None,
        auth_token: Optional[str] = None,
        client: Optional[httpx.Client] = None,
        base_url: Optional[str] = None,
        auth_env: Optional[List[str]] = None,
    ) -> None:
        load_env()
        account_var, token_var = (list(auth_env or []) + ["", ""])[:2]
        self.account_id = account_id or (get_env_key(account_var) if account_var else None)
        self.auth_token = auth_token or (get_env_key(token_var) if token_var else None)
        self.base_url = (base_url or "").rstrip("/")
        self._auth_env = [v for v in (account_var, token_var) if v]
        self._client = client

    @classmethod
    def from_config(cls, config: Any) -> "CloudflareDecisionAdapter":
        """Build from a ``DecisionProviderConfig`` (auth_env + base_url)."""
        return cls(base_url=config.base_url, auth_env=config.auth_env)

    def _format_questions(self, questions: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """Ensure question schemas conform to Workers AI Clef requirements."""
        formatted: Dict[str, Any] = {}
        for qid, qspec in questions.items():
            qtype = qspec.get("type", "choice")
            instructions = qspec.get("instructions", "")
            if qtype == "choice":
                criteria = qspec.get("criteria") or qspec.get("options") or {}
                formatted[qid] = {
                    "type": "choice",
                    "instructions": instructions,
                    "criteria": criteria,
                }
            elif qtype == "score":
                criteria = qspec.get("criteria") or qspec.get("levels") or []
                formatted[qid] = {
                    "type": "score",
                    "instructions": instructions,
                    "criteria": criteria,
                }
            elif qtype == "noul":
                formatted[qid] = {
                    "type": "noul",
                    "instructions": instructions,
                }
            else:
                formatted[qid] = dict(qspec)
        return formatted

    def decide(self, request: DecisionRequest) -> DecisionResult:
        if not self.account_id or not self.auth_token:
            raise ProviderError(
                message=f"Missing decision provider credentials ({', '.join(self._auth_env) or 'auth_env not configured'})",
                category="auth",
                provider_id=request.provider_id,
                retryable=False,
            )
        if not self.base_url or not request.model:
            raise ProviderError(
                message="Decision provider base_url and model must be set in routing.yaml",
                category="bad_request",
                provider_id=request.provider_id,
                retryable=False,
            )

        model_name = request.model
        url = f"{self.base_url.format(account_id=self.account_id)}/{model_name}"
        headers = {
            "Authorization": f"Bearer {self.auth_token}",
            "Content-Type": "application/json",
        }

        formatted_questions = self._format_questions(request.questions)
        payload = {
            "model": model_name,
            "state": request.state,
            "questions": formatted_questions,
        }
        if request.images:
            payload["images"] = request.images

        owns_client = self._client is None
        http_client = self._client or httpx.Client(timeout=request.timeout_s)

        start_time = time.perf_counter()
        try:
            try:
                resp = http_client.post(url, headers=headers, json=payload)
            except httpx.TimeoutException as exc:
                raise ProviderError(
                    message=f"Clef decision request timed out after {request.timeout_s}s: {exc}",
                    category="network",
                    provider_id=request.provider_id,
                    retryable=True,
                ) from exc
            except httpx.RequestError as exc:
                raise ProviderError(
                    message=f"Network error querying Clef decision model: {exc}",
                    category="network",
                    provider_id=request.provider_id,
                    retryable=True,
                ) from exc

            latency_ms = (time.perf_counter() - start_time) * 1000

            if resp.status_code in (401, 403):
                raise ProviderError(
                    message=f"Cloudflare Workers AI authentication failed (status {resp.status_code})",
                    category="auth",
                    provider_id=request.provider_id,
                    retryable=False,
                )
            if resp.status_code == 429:
                raise ProviderError(
                    message="Cloudflare Workers AI rate limit exceeded",
                    category="rate_limit",
                    provider_id=request.provider_id,
                    retryable=True,
                )
            if resp.status_code >= 500:
                raise ProviderError(
                    message=f"Cloudflare Workers AI server error (status {resp.status_code})",
                    category="server",
                    provider_id=request.provider_id,
                    retryable=True,
                )
            if resp.status_code != 200:
                raise ProviderError(
                    message=f"Cloudflare Workers AI request failed (status {resp.status_code})",
                    category="bad_request",
                    provider_id=request.provider_id,
                    retryable=False,
                )

            try:
                raw_json = resp.json()
            except Exception as exc:
                raise ProviderError(
                    message=f"Failed to parse Clef JSON response: {exc}",
                    category="server",
                    provider_id=request.provider_id,
                    retryable=False,
                ) from exc

            # Unwrap Cloudflare envelope if present
            result_obj = raw_json.get("result", raw_json) if raw_json.get("success") is not None else raw_json
            raw_answers = result_obj.get("answers", {})
            if not raw_answers:
                raise ProviderError(
                    message="Clef response contained no answers",
                    category="bad_request",
                    provider_id=request.provider_id,
                    retryable=False,
                )

            # Extract usage
            raw_usage = result_obj.get("usage", {})
            usage = Usage(
                input_tokens=int(raw_usage.get("input_tokens", 0)),
                output_tokens=int(raw_usage.get("output_tokens", 0)),
            )

            return DecisionResult(
                answers=raw_answers,
                usage=usage,
                latency_ms=round(latency_ms, 2),
                provider_id=request.provider_id,
                model=model_name,
                raw_response=raw_json,
                source="clef",
            )
        finally:
            if owns_client:
                http_client.close()
