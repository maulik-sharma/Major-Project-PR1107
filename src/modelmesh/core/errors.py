"""Error definitions and error normalization for ModelMesh providers and core."""

from __future__ import annotations

import re
from typing import Any, Literal, Optional

ErrorCategory = Literal[
    "auth",
    "rate_limit",
    "context_length",
    "bad_request",
    "network",
    "server",
    "unknown",
]

# Regex patterns for stripping potential API keys from error messages
_KEY_PATTERNS = [
    re.compile(r"sk-[a-zA-Z0-9_-]{20,}", re.IGNORECASE),
    re.compile(r"gsk_[a-zA-Z0-9_-]{20,}", re.IGNORECASE),
    re.compile(r"AIza[a-zA-Z0-9_-]{35}", re.IGNORECASE),
    re.compile(r"xkeys-[a-zA-Z0-9_-]{20,}", re.IGNORECASE),
    re.compile(r"Bearer\s+([a-zA-Z0-9_\-\.]{15,})", re.IGNORECASE),
]


def sanitize_error_message(text: str) -> str:
    """Scrub sensitive API key patterns from an error string.

    Args:
        text: Raw error text potentially containing keys.

    Returns:
        Sanitized error text with keys replaced by [REDACTED_KEY].
    """
    if not text:
        return ""
    sanitized = text
    for pat in _KEY_PATTERNS:
        sanitized = pat.sub("[REDACTED_KEY]", sanitized)
    return sanitized


class ModelMeshError(Exception):
    """Base exception for all ModelMesh errors."""

    def __init__(self, message: str) -> None:
        super().__init__(sanitize_error_message(message))
        self.raw_message = message


class ProviderError(ModelMeshError):
    """Normalized error representing any LLM provider failure.

    Attributes:
        category: Normalized category ('auth', 'rate_limit', 'context_length',
            'bad_request', 'network', 'server', 'unknown').
        retryable: Whether falling back or retrying makes sense.
        provider_id: ID of the provider that produced this error.
        status_code: HTTP status code if applicable.
        raw_error: The underlying original exception or payload.
        should_skip_model_siblings: If True, indicates that the issue is with
            the model or request itself (like context length) rather than a specific
            provider outage, so other endpoints for the same model should be skipped.
    """

    def __init__(
        self,
        message: str,
        category: ErrorCategory = "unknown",
        retryable: bool = False,
        provider_id: Optional[str] = None,
        status_code: Optional[int] = None,
        raw_error: Optional[Any] = None,
        should_skip_model_siblings: Optional[bool] = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.retryable = retryable
        self.provider_id = provider_id
        self.status_code = status_code
        self.raw_error = raw_error

        if should_skip_model_siblings is not None:
            self.should_skip_model_siblings = should_skip_model_siblings
        else:
            # Model-level issues skip siblings of the same model
            self.should_skip_model_siblings = category in ("context_length", "bad_request")

    def __str__(self) -> str:
        provider_str = f" [{self.provider_id}]" if self.provider_id else ""
        return f"{self.category.upper()}{provider_str}: {super().__str__()}"


class AuthError(ProviderError):
    """Authentication or authorization failure (e.g. invalid API key)."""

    def __init__(
        self,
        message: str,
        provider_id: Optional[str] = None,
        status_code: Optional[int] = 401,
        raw_error: Optional[Any] = None,
    ) -> None:
        super().__init__(
            message=message,
            category="auth",
            retryable=False,
            provider_id=provider_id,
            status_code=status_code,
            raw_error=raw_error,
            should_skip_model_siblings=False,
        )


class RateLimitError(ProviderError):
    """Rate limit or quota exceeded error."""

    def __init__(
        self,
        message: str,
        provider_id: Optional[str] = None,
        status_code: Optional[int] = 429,
        raw_error: Optional[Any] = None,
    ) -> None:
        super().__init__(
            message=message,
            category="rate_limit",
            retryable=True,
            provider_id=provider_id,
            status_code=status_code,
            raw_error=raw_error,
            should_skip_model_siblings=False,
        )


class ContextLengthError(ProviderError):
    """Prompt/context length exceeded model's maximum context window."""

    def __init__(
        self,
        message: str,
        provider_id: Optional[str] = None,
        status_code: Optional[int] = 400,
        raw_error: Optional[Any] = None,
    ) -> None:
        super().__init__(
            message=message,
            category="context_length",
            retryable=False,
            provider_id=provider_id,
            status_code=status_code,
            raw_error=raw_error,
            should_skip_model_siblings=True,
        )


class BadRequestError(ProviderError):
    """Malformed request or unsupported parameter."""

    def __init__(
        self,
        message: str,
        provider_id: Optional[str] = None,
        status_code: Optional[int] = 400,
        raw_error: Optional[Any] = None,
    ) -> None:
        super().__init__(
            message=message,
            category="bad_request",
            retryable=False,
            provider_id=provider_id,
            status_code=status_code,
            raw_error=raw_error,
            should_skip_model_siblings=True,
        )


class NetworkError(ProviderError):
    """Network connection error or timeout."""

    def __init__(
        self,
        message: str,
        provider_id: Optional[str] = None,
        status_code: Optional[int] = None,
        raw_error: Optional[Any] = None,
    ) -> None:
        super().__init__(
            message=message,
            category="network",
            retryable=True,
            provider_id=provider_id,
            status_code=status_code,
            raw_error=raw_error,
            should_skip_model_siblings=False,
        )


class ServerError(ProviderError):
    """Provider upstream 5xx server error."""

    def __init__(
        self,
        message: str,
        provider_id: Optional[str] = None,
        status_code: Optional[int] = 500,
        raw_error: Optional[Any] = None,
    ) -> None:
        super().__init__(
            message=message,
            category="server",
            retryable=True,
            provider_id=provider_id,
            status_code=status_code,
            raw_error=raw_error,
            should_skip_model_siblings=False,
        )


class RegistryError(ModelMeshError):
    """Error during model or provider registry loading / validation."""
    pass


class RoutingError(ModelMeshError):
    """Error when no eligible candidate satisfies the routing requirements."""
    pass
