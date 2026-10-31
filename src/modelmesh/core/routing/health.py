"""In-memory health tracking: per-endpoint cooldowns for transient failures, per-provider blacklist for auth."""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional

# Failures that say nothing about the endpoint's health (the request itself was the problem).
_REQUEST_CATEGORIES = frozenset({"bad_request", "context_length"})


class EndpointHealthTracker:
    """Tracks endpoint failures for the current session.

    Health is tracked per endpoint, never per model, so one provider's outage
    never hides the same model served by another provider.

    - ``auth`` failures (bad key, or an account out of credits) blacklist the
      endpoint, and its whole provider when known (every endpoint shares the
      key and account), until :meth:`clear_blacklist` (called when settings/keys change).
    - ``rate_limit`` puts the endpoint in cooldown immediately.
    - Other failures (``network``, ``server``, ``unknown``) put it in cooldown
      once ``failure_threshold`` consecutive failures are reached.
    - ``bad_request`` and ``context_length`` are not recorded.
    """

    def __init__(self, failure_threshold: int = 2, cooldown_seconds: float = 60.0) -> None:
        self.failure_threshold = max(1, failure_threshold)
        self.cooldown_seconds = cooldown_seconds
        self._consecutive_failures: Dict[str, int] = {}
        self._unhealthy_until: Dict[str, float] = {}
        self._blacklisted_endpoints: Dict[str, str] = {}  # endpoint_id -> reason
        self._blacklisted_providers: Dict[str, str] = {}  # provider_id -> reason
        self._lock = threading.Lock()

    def record_failure(
        self,
        endpoint_id: str,
        category: str = "unknown",
        reason: Optional[str] = None,
        provider_id: Optional[str] = None,
    ) -> None:
        """Record a failed request against an endpoint, classified by error category."""
        if category in _REQUEST_CATEGORIES:
            return
        with self._lock:
            if category == "auth":
                self._blacklisted_endpoints[endpoint_id] = reason or "Authentication failed"
                if provider_id:
                    self._blacklisted_providers[provider_id] = reason or "Authentication failed"
                return
            count = self._consecutive_failures.get(endpoint_id, 0) + 1
            self._consecutive_failures[endpoint_id] = count
            if category == "rate_limit" or count >= self.failure_threshold:
                self._unhealthy_until[endpoint_id] = time.time() + self.cooldown_seconds

    def record_success(self, endpoint_id: str) -> None:
        """Reset failure count and clear any cooldown or blacklist for an endpoint."""
        with self._lock:
            self._consecutive_failures.pop(endpoint_id, None)
            self._unhealthy_until.pop(endpoint_id, None)
            self._blacklisted_endpoints.pop(endpoint_id, None)

    def blacklist_endpoint(self, endpoint_id: str, reason: Optional[str] = None) -> None:
        """Explicitly blacklist an endpoint until the blacklist is cleared."""
        with self._lock:
            self._blacklisted_endpoints[endpoint_id] = reason or "Blacklisted for session"

    def is_blacklisted(self, endpoint_id: str, provider_id: Optional[str] = None) -> bool:
        """Return True if the endpoint, or its provider, is blacklisted for this session."""
        with self._lock:
            return endpoint_id in self._blacklisted_endpoints or (
                provider_id is not None and provider_id in self._blacklisted_providers
            )

    def get_blacklist_reason(self, endpoint_id: str, provider_id: Optional[str] = None) -> Optional[str]:
        """Return why an endpoint (or its provider) was blacklisted, or None."""
        with self._lock:
            if endpoint_id in self._blacklisted_endpoints:
                return self._blacklisted_endpoints[endpoint_id]
            return self._blacklisted_providers.get(provider_id) if provider_id else None

    def is_cooling_down(self, endpoint_id: str) -> bool:
        """Return True while an endpoint is inside its failure cooldown window."""
        with self._lock:
            return self._cooling_down_locked(endpoint_id)

    def is_healthy(self, endpoint_id: str) -> bool:
        """Return True if the endpoint is neither blacklisted nor cooling down."""
        with self._lock:
            if endpoint_id in self._blacklisted_endpoints:
                return False
            return not self._cooling_down_locked(endpoint_id)

    def get_blacklisted_endpoints(self) -> Dict[str, str]:
        """Return a snapshot of all blacklisted endpoints and their reasons."""
        with self._lock:
            return dict(self._blacklisted_endpoints)

    def clear_blacklist(self) -> None:
        """Reset all blacklists, failure counts, and cooldowns."""
        with self._lock:
            self._blacklisted_endpoints.clear()
            self._blacklisted_providers.clear()
            self._consecutive_failures.clear()
            self._unhealthy_until.clear()

    def get_status(self, endpoint_id: str) -> Dict[str, Any]:
        """Return a status dict for UI indicators."""
        with self._lock:
            blacklisted = endpoint_id in self._blacklisted_endpoints
            cooling = self._cooling_down_locked(endpoint_id)
            return {
                "healthy": not blacklisted and not cooling,
                "blacklisted": blacklisted,
                "cooling_down": cooling,
                "blacklist_reason": self._blacklisted_endpoints.get(endpoint_id),
                "consecutive_failures": self._consecutive_failures.get(endpoint_id, 0),
            }

    def _cooling_down_locked(self, endpoint_id: str) -> bool:
        """Cooldown check; caller must hold the lock. Expired cooldowns are cleared."""
        until = self._unhealthy_until.get(endpoint_id)
        if until is None:
            return False
        if time.time() >= until:
            self._unhealthy_until.pop(endpoint_id, None)
            self._consecutive_failures.pop(endpoint_id, None)
            return False
        return True
