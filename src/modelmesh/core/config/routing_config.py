"""Pydantic schema and loader for config/routing.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Literal, Optional
import yaml
from pydantic import BaseModel, Field, field_validator

from modelmesh.core.errors import RegistryError


class DecisionProviderConfig(BaseModel):
    """Configuration for an individual decision model provider."""
    id: str
    protocol: str = "heuristic"
    auth_env: List[str] = Field(default_factory=list)
    model: str = "clef-flash"


class DecisionConfig(BaseModel):
    """Decision layer settings and available decision providers."""
    active: str = "clef-flash"
    fallback: str = "heuristic"
    send_prompt_text: bool = True
    timeout_s: float = 1.5
    max_state_tokens: int = 2000
    providers: List[DecisionProviderConfig] = Field(default_factory=list)


class RubricQuestionConfig(BaseModel):
    """Configuration for a single rubric question."""
    type: Literal["choice", "score", "noul"]
    instructions: str
    options: Optional[Dict[str, str]] = None
    levels: Optional[List[str]] = None


class RubricConfig(BaseModel):
    """Rubric version and question dictionary."""
    version: int = 1
    questions: Dict[str, RubricQuestionConfig] = Field(default_factory=dict)


class NeedWeightsConfig(BaseModel):
    """Weights for the need calculation components."""
    difficulty: float = 0.5
    precision: float = 0.2
    larger_model_benefit: float = 0.3

    @field_validator("difficulty", "precision", "larger_model_benefit")
    @classmethod
    def check_non_negative(cls, v: float) -> float:
        if v < 0.0:
            raise ValueError("Weight cannot be negative.")
        return v


class NeedConfig(BaseModel):
    """Need scoring configuration."""
    weights: NeedWeightsConfig = Field(default_factory=NeedWeightsConfig)
    bias: float = 0.0
    uncertainty_k: float = 0.15
    slack: float = 0.10


class PoolConfig(BaseModel):
    """Include and exclude wildcard filters for routing candidates."""
    include: List[str] = Field(default_factory=lambda: ["*"])
    exclude: List[str] = Field(default_factory=lambda: ["mock-*"])


class StickinessConfig(BaseModel):
    """Session stickiness parameters."""
    enabled: bool = False
    task_changed_threshold: float = 0.6
    stay_unless_cost_ratio: float = 4.0


class ProfileConfig(BaseModel):
    """Quality / cost profile setting."""
    bias: float = 0.0


class ScoresSettingsConfig(BaseModel):
    """Scores source and update intervals."""
    source: str = "artificial_analysis"
    refresh_min_interval_days: int = 7


class SmartRoutingConfig(BaseModel):
    """Root model representing the entire routing.yaml file."""
    decision: DecisionConfig = Field(default_factory=DecisionConfig)
    rubric: RubricConfig = Field(default_factory=RubricConfig)
    need: NeedConfig = Field(default_factory=NeedConfig)
    metric_by_task: Dict[str, str] = Field(
        default_factory=lambda: {
            "coding": "coding",
            "agentic_tool_use": "agentic",
            "default": "intelligence",
        }
    )
    pool: PoolConfig = Field(default_factory=PoolConfig)
    unscored_policy: Literal["exclude", "tier_default"] = "exclude"
    stickiness: StickinessConfig = Field(default_factory=StickinessConfig)
    profiles: Dict[str, ProfileConfig] = Field(
        default_factory=lambda: {
            "frugal": ProfileConfig(bias=-0.15),
            "balanced": ProfileConfig(bias=0.0),
            "quality": ProfileConfig(bias=0.15),
        }
    )
    scores: ScoresSettingsConfig = Field(default_factory=ScoresSettingsConfig)


def find_routing_config_path() -> Path:
    """Locate config/routing.yaml in the project root or current working directory."""
    curr = Path.cwd().resolve()
    for p in [curr] + list(curr.parents):
        candidate = p / "config" / "routing.yaml"
        if candidate.exists():
            return candidate
    return Path.cwd() / "config" / "routing.yaml"


def load_routing_config(path: Optional[Path | str] = None) -> SmartRoutingConfig:
    """Load and validate routing.yaml using Pydantic.

    Args:
        path: Optional path to routing.yaml.

    Returns:
        Validated SmartRoutingConfig instance.

    Raises:
        RegistryError: If the YAML is malformed or invalid according to schema.
    """
    target = Path(path) if path else find_routing_config_path()
    if not target.exists():
        # Return default config if file is absent
        return SmartRoutingConfig()

    try:
        raw_text = target.read_text(encoding="utf-8")
        data = yaml.safe_load(raw_text) or {}
    except Exception as exc:
        raise RegistryError(f"Failed to read/parse {target}: {exc}") from exc

    try:
        return SmartRoutingConfig.model_validate(data)
    except Exception as exc:
        raise RegistryError(f"Invalid routing configuration in {target}: {exc}") from exc


def save_routing_config(config: SmartRoutingConfig, path: Optional[Path | str] = None) -> None:
    """Save SmartRoutingConfig back to config/routing.yaml."""
    target = Path(path) if path else find_routing_config_path()
    data = config.model_dump(mode="json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

