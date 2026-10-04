"""In-memory endpoint health tracking for consecutive failure cooldowns."""

from __future__ import annotations

import threading
import time
from typing import Any, Dict


class EndpointHealthTracker:
    """Tracks consecutive errors and manages session-level blacklisting for failed endpoints and models."""

    def __init__(self, failure_threshold: int = 1, cooldown_seconds: float = 60.0) -> None:
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._consecutive_failures: Dict[str, int] = {}
        self._unhealthy_until: Dict[str, float] = {}
        self._blacklisted_endpoints: Dict[str, str] = {}  # endpoint_id -> reason
        self._blacklisted_models: Dict[str, str] = {}      # model_id -> reason
        self._lock = threading.Lock()

    def record_failure(
        self,
        endpoint_id: str,
        model_id: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> None:
        """Record an endpoint query failure and automatically blacklist it and its model for this session."""
        with self._lock:
            count = self._consecutive_failures.get(endpoint_id, 0) + 1
            self._consecutive_failures[endpoint_id] = count

            if count >= self.failure_threshold:
                err_msg = reason or "Endpoint failed during request"
                self._blacklisted_endpoints[endpoint_id] = err_msg
                if model_id:
                    self._blacklisted_models[model_id] = err_msg
                self._unhealthy_until[endpoint_id] = time.time() + self.cooldown_seconds

    def record_success(
        self,
        endpoint_id: str,
        model_id: Optional[str] = None,
    ) -> None:
        """Reset consecutive failures and clear any cooldown or blacklist for an endpoint."""
        with self._lock:
            self._consecutive_failures.pop(endpoint_id, None)
            self._unhealthy_until.pop(endpoint_id, None)
            self._blacklisted_endpoints.pop(endpoint_id, None)
            if model_id:
                self._blacklisted_models.pop(model_id, None)

    def blacklist_model(self, model_id: str, reason: Optional[str] = None) -> None:
        """Explicitly blacklist a model for the remainder of this session."""
        with self._lock:
            self._blacklisted_models[model_id] = reason or "Blacklisted for session"

    def blacklist_endpoint(self, endpoint_id: str, reason: Optional[str] = None) -> None:
        """Explicitly blacklist an endpoint for the remainder of this session."""
        with self._lock:
            self._blacklisted_endpoints[endpoint_id] = reason or "Blacklisted for session"

    def is_blacklisted(
        self,
        endpoint_id: Optional[str] = None,
        model_id: Optional[str] = None,
    ) -> bool:
        """Check if an endpoint or model is currently blacklisted for this session."""
        with self._lock:
            if model_id and model_id in self._blacklisted_models:
                return True
            if endpoint_id and endpoint_id in self._blacklisted_endpoints:
                return True
            return False

    def get_blacklist_reason(
        self,
        endpoint_id: Optional[str] = None,
        model_id: Optional[str] = None,
    ) -> Optional[str]:
        """Get the reason why an endpoint or model was blacklisted in this session."""
        with self._lock:
            if model_id and model_id in self._blacklisted_models:
                return self._blacklisted_models[model_id]
            if endpoint_id and endpoint_id in self._blacklisted_endpoints:
                return self._blacklisted_endpoints[endpoint_id]
            return None

    def is_healthy(
        self,
        endpoint_id: str,
        model_id: Optional[str] = None,
    ) -> bool:
        """Check if an endpoint is currently considered healthy (not blacklisted or cooling down)."""
        with self._lock:
            if model_id and model_id in self._blacklisted_models:
                return False
            if endpoint_id in self._blacklisted_endpoints:
                return False

            unhealthy_until = self._unhealthy_until.get(endpoint_id)
            if unhealthy_until is None:
                return True
            if time.time() >= unhealthy_until:
                # Cooldown expired
                self._unhealthy_until.pop(endpoint_id, None)
                self._consecutive_failures.pop(endpoint_id, None)
                return True
            return False

    def get_blacklisted_models(self) -> Dict[str, str]:
        """Return a snapshot dictionary of all models blacklisted in this session."""
        with self._lock:
            return dict(self._blacklisted_models)

    def get_blacklisted_endpoints(self) -> Dict[str, str]:
        """Return a snapshot dictionary of all endpoints blacklisted in this session."""
        with self._lock:
            return dict(self._blacklisted_endpoints)

    def clear_blacklist(self) -> None:
        """Reset all session blacklists and health cooldowns."""
        with self._lock:
            self._blacklisted_models.clear()
            self._blacklisted_endpoints.clear()
            self._consecutive_failures.clear()
            self._unhealthy_until.clear()

    def get_status(self, endpoint_id: str, model_id: Optional[str] = None) -> Dict[str, Any]:
        """Return status dict for UI indicators."""
        with self._lock:
            blacklisted = self.is_blacklisted(endpoint_id=endpoint_id, model_id=model_id)
            is_ok = self.is_healthy(endpoint_id=endpoint_id, model_id=model_id)
            failures = self._consecutive_failures.get(endpoint_id, 0)
            reason = self.get_blacklist_reason(endpoint_id=endpoint_id, model_id=model_id)
            return {
                "healthy": is_ok,
                "blacklisted": blacklisted,
                "blacklist_reason": reason,
                "consecutive_failures": failures,
            }
