"""ModelMesh provider adapters."""

from modelmesh.core.providers.base import (
    ProviderAdapter,
    get_adapter,
    register_adapter,
)

# Import adapters to trigger registration
from modelmesh.core.providers import mock
from modelmesh.core.providers import openai_compat

__all__ = [
    "ProviderAdapter",
    "get_adapter",
    "register_adapter",
    "mock",
    "openai_compat",
]
