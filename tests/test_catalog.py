"""Model catalog checks: parsing each list format, diffing against config, applying changes.

Fixtures are small and synthetic, in the shapes of the live responses.
"""

from __future__ import annotations

import datetime

import httpx
import pytest
import respx

from modelmesh.core.catalog import apply_changes, check_catalogs, compute_changes, model_id_for
from modelmesh.core.errors import ProviderError
from modelmesh.core.providers.catalog_formats import (
    CatalogEntry,
    fetch_catalog,
    parse_anthropic_models,
    parse_gemini_models,
    parse_openai_models,
)
from modelmesh.core.registry import ModelRegistry
from modelmesh.core.types import CatalogSettings, EndpointConfig, ModelConfig, ProviderConfig

TODAY = datetime.date(2026, 10, 31)

OPENROUTER_LIKE = {"data": [
    {"id": "acme/small:free", "name": "Acme Small (free)", "context_length": 65536,
     "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
     "pricing": {"prompt": "0", "completion": "0"}, "supported_parameters": ["tools", "reasoning"],
     "top_provider": {"context_length": 65536, "max_completion_tokens": 8192}},
    {"id": "acme/big", "name": "Acme Big", "context_length": 200000,
     "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["text"]},
     "pricing": {"prompt": "0.000002", "completion": "0.00001"}, "supported_parameters": ["tools"],
     "top_provider": {}},
    {"id": "acme/music:free", "name": "Music", "architecture": {"input_modalities": ["text"],
     "output_modalities": ["text", "audio"]}, "pricing": {"prompt": "0", "completion": "0"}},
    {"id": "acme/old:free", "name": "Old", "pricing": {"prompt": "0", "completion": "0"},
     "expiration_date": "2026-10-01"},
]}
GROQ_LIKE = {"object": "list", "data": [
    {"id": "vendor/chat-20b", "object": "model", "active": True, "context_window": 131072,
     "max_completion_tokens": 65536, "input_modalities": ["text"], "output_modalities": ["text"],
     "pricing": {"prompt": "0.000000075", "completion": "0.0000003"}, "supported_features": ["tools"]},
    {"id": "whisper-x", "object": "model", "active": True, "context_window": 448,
     "input_modalities": ["audio"], "output_modalities": ["transcription"]},
    {"id": "gone-model", "object": "model", "active": False, "context_window": 8192},
]}
OPENAI_LIKE = {"data": [
    {"id": "gpt-new", "object": "model", "created": 1, "owned_by": "system", "shutdown_date": None},
    {"id": "o-old", "object": "model", "created": 1, "owned_by": "system", "shutdown_date": "2026-10-23"},
]}
GEMINI_LIKE = {"models": [
    {"name": "models/gem-flash", "displayName": "Gem Flash", "inputTokenLimit": 1048576,
     "outputTokenLimit": 65536, "supportedGenerationMethods": ["generateContent", "countTokens"], "thinking": True},
    {"name": "models/gem-embed", "displayName": "Embed", "supportedGenerationMethods": ["embedContent"]},
]}
ANTHROPIC_LIKE = {"data": [
    {"type": "model", "id": "claude-x", "display_name": "Claude X", "lifecycle": "active",
     "max_input_tokens": 1000000, "max_tokens": 128000,
     "capabilities": {"image_input": {"supported": True}, "thinking": {"supported": True}}},
    {"type": "model", "id": "claude-w", "display_name": "Claude W", "lifecycle": "deprecated",
     "retires_at": "2027-01-05T00:00:00Z", "max_input_tokens": 200000, "max_tokens": 64000, "capabilities": None},
], "has_more": False, "last_id": "claude-w"}


def test_parse_openai_shape_reads_optional_fields() -> None:
    e = {x.api_model: x for x in parse_openai_models(OPENROUTER_LIKE, TODAY)}
    small = e["acme/small:free"]
    assert (small.context_window, small.max_output, small.price_in_per_mtok, small.tools) == (65536, 8192, 0.0, True)
    assert small.reasoning and small.chat
    assert e["acme/big"].price_out_per_mtok == 10.0 and e["acme/big"].vision
    assert e["acme/music:free"].chat is False
    assert e["acme/old:free"].retired and "2026-10-01" in e["acme/old:free"].retire_note

    g = {x.api_model: x for x in parse_openai_models(GROQ_LIKE, TODAY)}
    assert g["vendor/chat-20b"].price_in_per_mtok == pytest.approx(0.075)
    assert g["whisper-x"].chat is False and g["gone-model"].retired

    o = {x.api_model: x for x in parse_openai_models(OPENAI_LIKE, TODAY)}
    assert o["gpt-new"].context_window is None and o["gpt-new"].tools is None
    assert o["o-old"].retired


def test_parse_gemini_and_anthropic_shapes() -> None:
    g = {x.api_model: x for x in parse_gemini_models(GEMINI_LIKE, TODAY)}
    assert g["gem-flash"].context_window == 1048576 and g["gem-flash"].reasoning
    assert g["gem-embed"].chat is False
    a = {x.api_model: x for x in parse_anthropic_models(ANTHROPIC_LIKE, TODAY)}
    assert a["claude-x"].max_output == 128000 and a["claude-x"].vision
    assert not a["claude-w"].retired and "retires 2027-01-05" in a["claude-w"].retire_note


def test_unknown_shape_is_reported_not_guessed() -> None:
    with pytest.raises(ValueError):
        parse_openai_models({"models": []}, TODAY)


def _provider(pid: str, **catalog: object) -> ProviderConfig:
    return ProviderConfig(id=pid, protocol="openai_compat", base_url=f"https://{pid}.test/v1",
                          catalog=CatalogSettings(**catalog))  # type: ignore[arg-type]


def _model(mid: str, pid: str, api: str, ctx: int = 131072, price: float = 0.0, out: int = 4096) -> ModelConfig:
    return ModelConfig(id=mid, display_name=mid, context_window=ctx, max_output=out, endpoints=[
        EndpointConfig(id=f"{mid}@{pid}", provider=pid, api_model=api,
                       price_in_per_mtok=price, price_out_per_mtok=price)])


def test_changes_for_free_only_provider() -> None:
    prov = _provider("or", free_only=True)
    models = [_model("small", "or", "acme/small:free", ctx=32768, out=16384), _model("gone", "or", "acme/removed:free")]
    changes = compute_changes(models, prov, parse_openai_models(OPENROUTER_LIKE, TODAY))
    kinds = {(c.kind, c.endpoint_id or c.entry.api_model) for c in changes}
    assert ("unavailable", "gone@or") in kinds
    assert ("limits", "small@or") in kinds
    assert not any(c.kind == "new" and c.entry.api_model == "acme/big" for c in changes)  # not free
    assert not any(c.kind == "new" and c.entry.api_model in ("acme/music:free", "acme/old:free") for c in changes)
    limits = [c.updates for c in changes if c.kind == "limits"]
    assert {"context_window": 65536} in limits and {"max_output": 8192} in limits


def test_assume_free_prices_everything_at_zero_and_respects_excludes() -> None:
    prov = _provider("groq", assume_free=True, exclude=["whisper*"])
    models = [_model("chat", "groq", "vendor/chat-20b", price=0.1)]
    changes = compute_changes(models, prov, parse_openai_models(GROQ_LIKE, TODAY))
    price = [c for c in changes if c.kind == "price"]
    assert price and price[0].updates == {"price_in_per_mtok": 0.0, "price_out_per_mtok": 0.0}
    assert not [c for c in changes if c.kind == "new"]  # whisper excluded, inactive model skipped


def test_deprecated_is_offered_unchecked_and_not_as_new() -> None:
    prov = _provider("anthropic", format="anthropic")
    models = [_model("w", "anthropic", "claude-w", ctx=200000)]
    changes = compute_changes(models, prov, parse_anthropic_models(ANTHROPIC_LIKE, TODAY))
    dep = [c for c in changes if c.kind == "deprecated"]
    assert dep and dep[0].default_apply is False
    new = [c for c in changes if c.kind == "new"]
    assert [c.entry.api_model for c in new] == ["claude-x"] and new[0].default_apply is False


def test_apply_changes_updates_disables_and_adds() -> None:
    prov_or = _provider("or", free_only=True)
    prov_paid = _provider("paid")
    existing = _model("small", "or", "acme/small:free", ctx=32768)
    models = {"small": existing}
    changes = compute_changes([existing], prov_or, parse_openai_models(OPENROUTER_LIKE, TODAY))
    changes += compute_changes([], prov_paid, parse_openai_models(OPENAI_LIKE, TODAY))
    created = apply_changes(models, {"or": prov_or, "paid": prov_paid}, changes)
    assert existing.endpoints[0].context_window == 65536
    by_id = {m.id: m for m in created}
    assert by_id["gpt-new"].routing.routable is False  # unknown price -> manual pick only
    assert "o-old" not in by_id  # shut down: never offered


def test_new_model_joins_existing_logical_model() -> None:
    prov = _provider("or", free_only=True)
    existing = _model("small", "other", "acme-small")
    models = {"small": existing}
    entry = CatalogEntry(api_model="acme/small:free", display_name="Acme Small", price_in_per_mtok=0.0,
                         price_out_per_mtok=0.0, context_window=65536)
    changes = compute_changes([existing], prov, [entry])
    created = apply_changes(models, {"or": prov}, changes)
    assert created == [] and [e.id for e in existing.endpoints] == ["small@other", "small@or"]
    assert model_id_for("google/gemma-4-31b-it:free") == "gemma-4-31b-it"


@respx.mock
def test_fetch_follows_pagination_and_auth_headers(monkeypatch) -> None:
    monkeypatch.setenv("TEST_ANTHROPIC_KEY", "k-123")
    prov = ProviderConfig(id="anthropic", protocol="anthropic", base_url="https://api.anthropic.test",
                          auth_env=["TEST_ANTHROPIC_KEY"], catalog=CatalogSettings(format="anthropic"))
    page1 = {"data": ANTHROPIC_LIKE["data"][:1], "has_more": True, "last_id": "claude-x"}
    page2 = {"data": ANTHROPIC_LIKE["data"][1:], "has_more": False, "last_id": "claude-w"}
    route = respx.get("https://api.anthropic.test/v1/models")
    route.side_effect = [httpx.Response(200, json=page1), httpx.Response(200, json=page2)]
    entries = fetch_catalog(prov, today=TODAY)
    assert [e.api_model for e in entries] == ["claude-x", "claude-w"]
    assert route.calls[0].request.headers["x-api-key"] == "k-123"
    assert route.calls[1].request.url.params["after_id"] == "claude-x"


@respx.mock
def test_failed_fetch_proposes_nothing() -> None:
    reg = ModelRegistry()
    prov = _provider("or", free_only=True)
    reg.add_provider(prov)
    reg.add_model(_model("small", "or", "acme/small:free"))
    respx.get("https://or.test/v1/models").respond(401)
    report = check_catalogs(reg)
    assert report.changes == [] and "or" in report.errors


def test_fetch_requires_catalog_settings() -> None:
    with pytest.raises(ProviderError):
        fetch_catalog(ProviderConfig(id="x", protocol="openai_compat"))
