"""ModelMesh routing strategies and candidate evaluation."""

from modelmesh.core.routing.base import (
    Strategy,
    get_strategy,
    list_strategies,
    register_strategy,
)
from modelmesh.core.routing.features import (
    extract_request_features,
    filter_eligible_candidates,
)
from modelmesh.core.routing.health import EndpointHealthTracker
from modelmesh.core.routing.router import Router

# Import strategies to trigger registration
from modelmesh.core.routing import cheapest
from modelmesh.core.routing import expensive
from modelmesh.core.routing import manual
from modelmesh.core.routing import random_
from modelmesh.core.routing import smart

__all__ = [
    "Strategy",
    "get_strategy",
    "list_strategies",
    "register_strategy",
    "extract_request_features",
    "filter_eligible_candidates",
    "EndpointHealthTracker",
    "Router",
    "cheapest",
    "expensive",
    "manual",
    "random_",
    "smart",
]
