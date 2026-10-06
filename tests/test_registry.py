"""Tests for ModelRegistry and YAML configuration loading."""

from pathlib import Path
import pytest
from modelmesh.core.errors import RegistryError
from modelmesh.core.registry import ModelRegistry, load_default_registry


def test_load_example_config_file() -> None:
    example_path = Path("config/providers.example.yaml")
    assert example_path.exists()

    registry = ModelRegistry()
    registry.load_from_file(example_path)

    # Check providers
    providers = registry.providers()
    provider_ids = {p.id for p in providers}
    assert {"groq", "openrouter", "ollama", "anthropic", "mock"}.issubset(provider_ids)

    # Check models
    models = registry.models()
    model_ids = {m.id for m in models}
    assert "llama-fast" in model_ids
    assert "claude-mid" in model_ids
    assert "mock-fast" in model_ids

    # Check candidates resolution
    cands = registry.candidates()
    assert len(cands) >= 5

    # Check llama-fast candidates (3 endpoints)
    llama_cands = [c for c in cands if c.model_id == "llama-fast"]
    assert len(llama_cands) == 3
    llama_ep_ids = {c.endpoint_id for c in llama_cands}
    assert llama_ep_ids == {
        "llama-fast@groq",
        "llama-fast@openrouter",
        "llama-fast@ollama",
    }

    # Verify endpoint prices and providers
    groq_cand = next(c for c in llama_cands if c.endpoint_id == "llama-fast@groq")
    assert groq_cand.provider_id == "groq"
    assert groq_cand.price_in_per_mtok == 0.05
    assert groq_cand.price_out_per_mtok == 0.08
    assert groq_cand.priority == 1

    ollama_cand = next(c for c in llama_cands if c.endpoint_id == "llama-fast@ollama")
    assert ollama_cand.provider_id == "ollama"
    assert ollama_cand.price_in_per_mtok == 0.0
    assert ollama_cand.priority == 3


def test_invalid_yaml_missing_provider() -> None:
    invalid_yaml = """
providers:
  - id: groq
    protocol: openai_compat
models:
  - id: test-model
    display_name: Test
    endpoints:
      - id: test-model@unknown_provider
        provider: unknown_provider
        api_model: test
"""
    registry = ModelRegistry()
    with pytest.raises(RegistryError) as exc_info:
        registry.load_from_yaml(invalid_yaml)
    assert "unknown provider 'unknown_provider'" in str(exc_info.value)


def test_duplicate_endpoint_ids() -> None:
    invalid_yaml = """
providers:
  - id: p1
    protocol: mock
models:
  - id: m1
    endpoints:
      - id: dup-ep
        provider: p1
        api_model: a
  - id: m2
    endpoints:
      - id: dup-ep
        provider: p1
        api_model: b
"""
    registry = ModelRegistry()
    with pytest.raises(RegistryError) as exc_info:
        registry.load_from_yaml(invalid_yaml)
    assert "Duplicate endpoint ID 'dup-ep'" in str(exc_info.value)


def test_roundtrip_save_and_reload(tmp_path: Path) -> None:
    example_path = Path("config/providers.example.yaml")
    reg1 = ModelRegistry()
    reg1.load_from_file(example_path)

    saved_path = tmp_path / "test_providers.yaml"
    reg1.save_to_file(saved_path)
    assert saved_path.exists()

    reg2 = ModelRegistry()
    reg2.load_from_file(saved_path)
    assert len(reg2.models()) == len(reg1.models())
    assert len(reg2.providers()) == len(reg1.providers())
    assert len(reg2.candidates()) == len(reg1.candidates())


def test_active_providers_config() -> None:
    """Verify the active config/providers.yaml loads cleanly and has valid candidate endpoints."""
    active_path = Path("config/providers.yaml")
    if not active_path.exists():
        return

    reg = ModelRegistry()
    reg.load_from_file(active_path)

    cands = reg.candidates()
    assert len(cands) > 0
    for cand in cands:
        assert cand.api_model, f"Candidate {cand.candidate_id} has empty api_model"
        assert cand.provider_id in {p.id for p in reg.providers()}, f"Unknown provider {cand.provider_id}"
        assert cand.price_in_per_mtok >= 0.0
        assert cand.price_out_per_mtok >= 0.0

