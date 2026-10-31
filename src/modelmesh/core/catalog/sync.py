"""Check every provider that has catalog settings (network I/O; run off the UI thread)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from modelmesh.core.catalog.changes import KINDS, CatalogChange, compute_changes
from modelmesh.core.errors import friendly_error
from modelmesh.core.providers.catalog_formats import CatalogEntry, fetch_catalog
from modelmesh.core.registry import ModelRegistry
from modelmesh.core.types import ProviderConfig


@dataclass
class CatalogReport:
    """Result of a catalog check: proposed changes and per-provider failures."""
    changes: List[CatalogChange] = field(default_factory=list)
    errors: Dict[str, str] = field(default_factory=dict)  # provider_id -> friendly message
    checked: List[str] = field(default_factory=list)


def check_catalogs(
    registry: ModelRegistry,
    fetch: Callable[[ProviderConfig], List[CatalogEntry]] = fetch_catalog,
    provider_ids: Optional[List[str]] = None,
) -> CatalogReport:
    """Fetch each configured provider's catalog and diff it against the registry.

    A provider whose list can't be fetched is reported in ``errors`` and proposes
    no changes (a failed fetch must never look like "every model was removed").
    """
    report = CatalogReport()
    models = registry.models()
    for provider in registry.providers():
        if provider.catalog is None or (provider_ids and provider.id not in provider_ids):
            continue
        try:
            entries = fetch(provider)
        except Exception as exc:
            report.errors[provider.id] = friendly_error(exc)[0] + f" ({exc})"
            continue
        report.checked.append(provider.id)
        report.changes.extend(compute_changes(models, provider, entries))
    report.changes.sort(key=lambda c: (KINDS.index(c.kind), c.provider_id, c.summary))
    return report
