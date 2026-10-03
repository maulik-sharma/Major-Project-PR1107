"""ProviderAdapter abstract base class and protocol adapter registry."""

from __future__ import annotations

from abc import ABC, abstractmethod
import threading
from typing import Callable, Dict, Iterator, List, Optional, Type

from modelmesh.core.errors import RegistryError
from modelmesh.core.types import (
    Candidate,
    ChatRequest,
    ProviderConfig,
    StreamEvent,
)


class ProviderAdapter(ABC):
    """Abstract base class for all LLM protocol adapters."""

    protocol_id: str

    @abstractmethod
    def stream_chat(
        self,
        request: ChatRequest,
        candidate: Candidate,
        cancel_event: Optional[threading.Event] = None,
    ) -> Iterator[StreamEvent]:
        """Stream normalized events for a chat request.

        Args:
            request: Canonical ChatRequest.
            candidate: Chosen Candidate containing provider/endpoint details.
            cancel_event: Optional event to signal cancellation during streaming.

        Yields:
            StreamEvent instances (TEXT_DELTA, REASONING_DELTA, TOOL_CALL, USAGE, DONE).

        Raises:
            ProviderError: If the provider call fails.
        """
        pass

    def list_models(self, provider: ProviderConfig) -> List[str]:
        """Fetch available model IDs from the provider.

        Args:
            provider: Provider configuration.

        Returns:
            List of model ID strings available at this provider.
        """
        return []

    def test_connection(self, provider: ProviderConfig) -> bool:
        """Perform a cheap authenticated health check call.

        Args:
            provider: Provider configuration.

        Returns:
            True if connection and authentication succeed.

        Raises:
            ProviderError: If the check fails.
        """
        return True


# Global registry mapping protocol ID to adapter instance / class
_ADAPTER_REGISTRY: Dict[str, ProviderAdapter] = {}


def register_adapter(protocol_id: str) -> Callable[[Type[ProviderAdapter]], Type[ProviderAdapter]]:
    """Decorator to register a ProviderAdapter subclass for a protocol ID."""
    def decorator(cls: Type[ProviderAdapter]) -> Type[ProviderAdapter]:
        cls.protocol_id = protocol_id
        _ADAPTER_REGISTRY[protocol_id] = cls()
        return cls
    return decorator


def get_adapter(protocol_id: str) -> ProviderAdapter:
    """Retrieve the registered adapter instance for a protocol ID."""
    adapter = _ADAPTER_REGISTRY.get(protocol_id)
    if not adapter:
        raise RegistryError(
            f"No provider adapter registered for protocol '{protocol_id}'. "
            f"Available protocols: {list(_ADAPTER_REGISTRY.keys())}"
        )
    return adapter
