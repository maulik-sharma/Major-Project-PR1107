"""Compare configured endpoints with a provider's live catalog, and apply chosen changes.

Pure: plain data in, plain data out (the fetch lives in core/providers/catalog_formats.py).
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from modelmesh.core.providers.catalog_formats import CatalogEntry
from modelmesh.core.types import (
    EndpointConfig,
    ModelConfig,
    ModelRoutingConfig,
    ProviderConfig,
)

# Change kinds, in the order the review dialog lists them.
KINDS = ("unavailable", "retired", "no_longer_free", "limits", "price", "deprecated", "new")


@dataclass
class CatalogChange:
    """One proposed edit to providers.yaml."""
    kind: str
    provider_id: str
    summary: str
    default_apply: bool
    model_id: Optional[str] = None
    endpoint_id: Optional[str] = None
    updates: Dict[str, Any] = field(default_factory=dict)  # endpoint fields to set
    entry: Optional[CatalogEntry] = None  # for "new"


def _matches(value: str, patterns: List[str]) -> bool:
    return any(fnmatch.fnmatch(value, p) for p in patterns)


def _fmt_price(p_in: float, p_out: float) -> str:
    return f"${p_in:g}/${p_out:g} per M"


def _is_free(entry: CatalogEntry) -> bool:
    return entry.price_in_per_mtok == 0 and entry.price_out_per_mtok == 0


def offerable(entry: CatalogEntry, provider: ProviderConfig) -> bool:
    """Whether a catalog model may be offered as a new model under the provider's catalog rules."""
    cfg = provider.catalog
    if cfg is None or not entry.chat or entry.retired or entry.retire_note:
        return False  # not chat, or already on its way out
    if not _matches(entry.api_model, cfg.include) or _matches(entry.api_model, cfg.exclude):
        return False
    return _is_free(entry) if cfg.free_only else True


def compute_changes(
    models: List[ModelConfig],
    provider: ProviderConfig,
    entries: List[CatalogEntry],
) -> List[CatalogChange]:
    """Proposed changes for one provider: unavailable/retired endpoints, wrong limits or
    prices, and models the catalog offers that are not configured yet."""
    cfg = provider.catalog
    if cfg is None:
        return []
    by_api = {e.api_model: e for e in entries}
    changes: List[CatalogChange] = []
    configured = set()
    for m in models:
        for ep in m.endpoints:
            if ep.provider != provider.id:
                continue
            configured.add(ep.api_model)
            if ep.enabled:
                changes.extend(_endpoint_changes(m, ep, by_api.get(ep.api_model), provider))

    for e in entries:
        if e.api_model not in configured and offerable(e, provider):
            if cfg.assume_free or _is_free(e):
                price = "free"
            elif e.price_in_per_mtok is not None:
                price = _fmt_price(e.price_in_per_mtok, e.price_out_per_mtok or 0.0)
            else:
                price = "price unknown: manual pick only until you set one"
            ctx = f", {e.context_window:,} ctx" if e.context_window else ""
            changes.append(CatalogChange(
                kind="new", provider_id=provider.id, entry=e,
                summary=f"Add {e.display_name} ({e.api_model}): {price}{ctx}",
                default_apply=cfg.free_only or cfg.assume_free,
            ))
    return changes


def _endpoint_changes(
    m: ModelConfig,
    ep: EndpointConfig,
    e: Optional[CatalogEntry],
    provider: ProviderConfig,
) -> List[CatalogChange]:
    cfg = provider.catalog
    assert cfg is not None

    def change(kind: str, summary: str, default: bool, updates: Dict[str, Any]) -> CatalogChange:
        return CatalogChange(kind=kind, provider_id=provider.id, model_id=m.id, endpoint_id=ep.id,
                             summary=summary, default_apply=default, updates=updates)

    if e is None:
        return [change("unavailable", f"Disable {ep.id}: '{ep.api_model}' is no longer offered", True,
                       {"enabled": False})]
    if e.retired:
        return [change("retired", f"Disable {ep.id}: {e.retire_note or 'retired'}", True, {"enabled": False})]

    out: List[CatalogChange] = []
    if cfg.free_only and ep.price_in_per_mtok == 0 and ep.price_out_per_mtok == 0 and \
            e.price_in_per_mtok is not None and not _is_free(e):
        out.append(change("no_longer_free", f"Disable {ep.id}: no longer free "
                          f"({_fmt_price(e.price_in_per_mtok, e.price_out_per_mtok or 0.0)})", True,
                          {"enabled": False}))
        return out

    ctx_now = ep.context_window or m.context_window
    if e.context_window and e.context_window != ctx_now:
        out.append(change("limits", f"{ep.id}: context window {ctx_now:,} → {e.context_window:,}", True,
                          {"context_window": int(e.context_window)}))
    out_now = ep.max_output or m.max_output
    if e.max_output and out_now > e.max_output:  # asking for more than allowed fails the request
        out.append(change("limits", f"{ep.id}: max output {out_now:,} → {e.max_output:,}", True,
                          {"max_output": int(e.max_output)}))

    target: Optional[Tuple[float, float]] = None
    if cfg.assume_free:
        target = (0.0, 0.0)
    elif e.price_in_per_mtok is not None and e.price_out_per_mtok is not None:
        target = (e.price_in_per_mtok, e.price_out_per_mtok)
    if target and (abs(target[0] - ep.price_in_per_mtok) > 1e-9 or abs(target[1] - ep.price_out_per_mtok) > 1e-9):
        out.append(change("price", f"{ep.id}: price {_fmt_price(ep.price_in_per_mtok, ep.price_out_per_mtok)}"
                          f" → {_fmt_price(*target)}", True,
                          {"price_in_per_mtok": target[0], "price_out_per_mtok": target[1]}))

    if e.retire_note:
        out.append(change("deprecated", f"{ep.id}: {e.retire_note}; disable it now?", False, {"enabled": False}))
    return out


def model_id_for(api_model: str) -> str:
    """Logical model id for a catalog model: 'google/gemma-4-31b-it:free' -> 'gemma-4-31b-it'."""
    base = api_model.split("/")[-1].split(":")[0].lower()
    return re.sub(r"[^a-z0-9]+", "-", base).strip("-") or "model"


def apply_changes(
    models: Dict[str, ModelConfig],
    providers: Dict[str, ProviderConfig],
    changes: List[CatalogChange],
) -> List[ModelConfig]:
    """Apply chosen changes in place. Returns models created for "new" changes (caller adds them).

    A new catalog model joins an existing logical model with the same derived id
    only when that is plausibly the same model served by another provider: the
    model has no endpoint on this provider yet and the new endpoint's price is
    known (an unpriced endpoint would enter cost routing at $0). Otherwise it
    becomes a model of its own with a suffixed id.
    """
    created: Dict[str, ModelConfig] = {}
    for ch in changes:
        if ch.kind != "new":
            model = models.get(ch.model_id or "")
            ep = next((x for x in model.endpoints if x.id == ch.endpoint_id), None) if model else None
            if ep is not None:
                for key, value in ch.updates.items():
                    setattr(ep, key, value)
            continue
        e, provider = ch.entry, providers.get(ch.provider_id)
        if e is None or provider is None or provider.catalog is None:
            continue
        mid = model_id_for(e.api_model)
        model = models.get(mid) or created.get(mid)
        free = provider.catalog.assume_free or _is_free(e)
        price_known = free or e.price_in_per_mtok is not None
        if model is not None and (not price_known or any(x.provider == provider.id for x in model.endpoints)):
            base, n = mid, 2
            while mid in models or mid in created:
                mid, n = f"{base}-{n}", n + 1
            model = None
        if model is None:
            caps = ["streaming"]
            if e.tools is not False:
                caps.append("tools")
            if e.vision:
                caps.append("vision")
            if e.reasoning:
                caps.append("reasoning")
            model = ModelConfig(
                id=mid, display_name=e.display_name, tier="cheap" if free else "mid",
                context_window=int(e.context_window or 32768), max_output=int(min(e.max_output or 8192, 16384)),
                capabilities=caps,
                # Without a price, cost-based routing would treat it as free: manual pick only.
                routing=ModelRoutingConfig(routable=price_known),
            )
            created[mid] = model
        ep_id = f"{mid}@{provider.id}"
        taken = {x.id for x in model.endpoints}
        n = 2
        while ep_id in taken:
            ep_id, n = f"{mid}@{provider.id}-{n}", n + 1
        model.endpoints.append(EndpointConfig(
            id=ep_id, provider=provider.id, api_model=e.api_model,
            price_in_per_mtok=0.0 if free else float(e.price_in_per_mtok or 0.0),
            price_out_per_mtok=0.0 if free else float(e.price_out_per_mtok or 0.0),
            context_window=int(e.context_window) if e.context_window else None,
        ))
    return list(created.values())
