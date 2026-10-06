"""Unit tests for config/routing.yaml loading and schema validation."""

import pytest
from pathlib import Path
from modelmesh.core.config.routing_config import (
    SmartRoutingConfig,
    load_routing_config,
)
from modelmesh.core.errors import RegistryError
from modelmesh.core.registry import ModelRegistry
from modelmesh.core.types import ModelConfig


def test_load_default_routing_config() -> None:
    """Verify loading default config/routing.yaml."""
    cfg = load_routing_config()
    assert isinstance(cfg, SmartRoutingConfig)
    assert cfg.decision.active == "clef-flash"
    assert cfg.decision.fallback == "heuristic"
    assert cfg.decision.timeout_s == 1.5
    assert cfg.rubric.version == 1
    assert "task" in cfg.rubric.questions
    assert "difficulty" in cfg.rubric.questions
    assert cfg.need.weights.difficulty == 0.5
    assert cfg.pool.include == ["*"]
    assert "mock-*" in cfg.pool.exclude
    assert "frugal" in cfg.profiles
    assert cfg.profiles["frugal"].bias == -0.15


def test_routing_config_invalid_yaml(tmp_path: Path) -> None:
    """Verify invalid YAML or schema errors raise RegistryError."""
    bad_file = tmp_path / "bad_routing.yaml"
    bad_file.write_text("need:\n  weights:\n    difficulty: -1.0\n", encoding="utf-8")

    with pytest.raises(RegistryError):
        load_routing_config(bad_file)


def test_model_config_scores_and_routing_defaults() -> None:
    """Verify ModelConfig scores and routing defaults work seamlessly."""
    raw = {
        "id": "test-model",
        "display_name": "Test Model",
        "endpoints": [
            {
                "id": "test-model@mock",
                "provider": "mock",
                "api_model": "test-mock",
            }
        ]
    }
    model = ModelConfig.from_dict(raw)
    assert model.scores.aa_slug is None
    assert model.scores.manual.intelligence is None
    assert model.routing.routable is True
    assert model.routing.admitted_tasks == ["all"]

    # Round-trip serialization
    d = model.to_dict()
    assert "scores" in d
    assert "routing" in d
    assert d["routing"]["routable"] is True
