"""In-memory endpoint health tracking for consecutive failure cooldowns."""

from __future__ import annotations

import threading
import time
from typing import Any, Dict


class EndpointHealthTracker:
    """Tracks consecutive errors per endpoint and triggers a temporary cooldown."""

    def __init__(self, failure_threshold: int = 3, cooldown_seconds: float = 60.0) -> None:
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._consecutive_failures: Dict[str, int] = {}
        self._unhealthy_until: Dict[str, float] = {}
        self._lock = threading.Lock()

    def record_failure(self, endpoint_id: str) -> None:
        """Increment failure count; if threshold reached, mark unhealthy."""
        with self._lock:
            count = self._consecutive_failures.get(endpoint_id, 0) + 1
            self._consecutive_failures[endpoint_id] = count
            if count >= self.failure_threshold:
                self._unhealthy_until[endpoint_id] = time.time() + self.cooldown_seconds

    def record_success(self, endpoint_id: str) -> None:
        """Reset consecutive failures and clear any cooldown."""
        with self._lock:
            self._consecutive_failures.pop(endpoint_id, None)
            self._unhealthy_until.pop(endpoint_id, None)

    def is_healthy(self, endpoint_id: str) -> bool:
        """Check if an endpoint is currently considered healthy."""
        with self._lock:
            unhealthy_until = self._unhealthy_until.get(endpoint_id)
            if unhealthy_until is None:
                return True
            if time.time() >= unhealthy_until:
                # Cooldown expired
                self._unhealthy_until.pop(endpoint_id, None)
                self._consecutive_failures.pop(endpoint_id, None)
                return True
            return False

    def get_status(self, endpoint_id: str) -> Dict[str, Any]:
        """Return status dict for UI indicators."""
        with self._lock:
            is_ok = self.is_healthy(endpoint_id)
            failures = self._consecutive_failures.get(endpoint_id, 0)
            return {
                "healthy": is_ok,
                "consecutive_failures": failures,
            }
