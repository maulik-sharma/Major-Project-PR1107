"""Model and Provider Registry for ModelMesh."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Set
import yaml

from modelmesh.core.errors import RegistryError
from modelmesh.core.types import (
    Candidate,
    EndpointConfig,
    ModelConfig,
    ProviderConfig,
)


class ModelRegistry:
    """Manages configured providers, logical models, and their endpoints."""

    def __init__(self) -> None:
        self._providers: Dict[str, ProviderConfig] = {}
        self._models: Dict[str, ModelConfig] = {}

    def clear(self) -> None:
        """Clear all loaded providers and models."""
        self._providers.clear()
        self._models.clear()

    def add_provider(self, provider: ProviderConfig) -> None:
        """Register or update a provider."""
        self._providers[provider.id] = provider

    def remove_provider(self, provider_id: str) -> None:
        """Remove a provider by ID."""
        self._providers.pop(provider_id, None)

    def get_provider(self, provider_id: str) -> Optional[ProviderConfig]:
        """Get a provider by ID."""
        return self._providers.get(provider_id)

    def providers(self) -> List[ProviderConfig]:
        """List all registered providers."""
        return list(self._providers.values())

    def add_model(self, model: ModelConfig) -> None:
        """Register or update a model."""
        self._models[model.id] = model

    def remove_model(self, model_id: str) -> None:
        """Remove a model by ID."""
        self._models.pop(model_id, None)

    def get_model(self, model_id: str) -> Optional[ModelConfig]:
        """Get a model by ID."""
        return self._models.get(model_id)

    def models(self) -> List[ModelConfig]:
        """List all registered models."""
        return list(self._models.values())

    def endpoints_for(self, model_id: str) -> List[EndpointConfig]:
        """List all endpoints defined for a model."""
        model = self.get_model(model_id)
        if not model:
            return []
        return list(model.endpoints)

    def add_endpoint(self, model_id: str, endpoint: EndpointConfig) -> None:
        """Add an endpoint to a model."""
        model = self.get_model(model_id)
        if not model:
            raise RegistryError(f"Cannot add endpoint: model '{model_id}' does not exist.")
        # Replace if endpoint id matches, else append
        existing_idx = next((i for i, ep in enumerate(model.endpoints) if ep.id == endpoint.id), None)
        if existing_idx is not None:
            model.endpoints[existing_idx] = endpoint
        else:
            model.endpoints.append(endpoint)

    def remove_endpoint(self, model_id: str, endpoint_id: str) -> None:
        """Remove an endpoint from a model."""
        model = self.get_model(model_id)
        if not model:
            return
        model.endpoints = [ep for ep in model.endpoints if ep.id != endpoint_id]

    def validate(self) -> None:
        """Validate the consistency and integrity of all providers and models.

        Raises:
            RegistryError: If any provider reference is missing or config is invalid.
        """
        provider_ids = set(self._providers.keys())
        seen_endpoint_ids: Set[str] = set()

        for model in self._models.values():
            if not model.id:
                raise RegistryError("Model has an empty or missing 'id'.")
            if not model.endpoints:
                raise RegistryError(f"Model '{model.id}' must have at least one endpoint.")

            for ep in model.endpoints:
                if not ep.id:
                    raise RegistryError(f"Endpoint in model '{model.id}' has empty 'id'.")
                if ep.id in seen_endpoint_ids:
                    raise RegistryError(
                        f"Duplicate endpoint ID '{ep.id}' detected in model '{model.id}'."
                    )
                seen_endpoint_ids.add(ep.id)

                if ep.provider not in provider_ids:
                    raise RegistryError(
                        f"Endpoint '{ep.id}' references unknown provider '{ep.provider}'. "
                        f"Available providers: {list(provider_ids)}"
                    )
                if not ep.api_model or not ep.api_model.strip():
                    raise RegistryError(
                        f"Endpoint '{ep.id}' has empty 'api_model' string."
                    )

    def candidates(self, enabled_only: bool = True) -> List[Candidate]:
        """Compute the resolved Candidate list for all (model, endpoint) pairs.

        Args:
            enabled_only: If True, only returns candidates where both model
                and endpoint are enabled.

        Returns:
            List of fully resolved Candidate objects.
        """
        self.validate()
        result: List[Candidate] = []
        for model in self._models.values():
            if enabled_only and not model.enabled:
                continue
            for endpoint in model.endpoints:
                if enabled_only and not endpoint.enabled:
                    continue
                provider = self.get_provider(endpoint.provider)
                if provider is None:
                    continue
                candidate = Candidate.resolve(
                    model=model,
                    endpoint=endpoint,
                    provider=provider,
                )
                result.append(candidate)
        return result

    def get_candidate(self, endpoint_id: str) -> Optional[Candidate]:
        """Get a resolved candidate by its endpoint ID."""
        for cand in self.candidates(enabled_only=False):
            if cand.endpoint_id == endpoint_id:
                return cand
        return None

    def load_from_yaml(self, yaml_content: str) -> None:
        """Parse and load registry configuration from a YAML string.

        Args:
            yaml_content: YAML text.

        Raises:
            RegistryError: If parsing or structure validation fails.
        """
        try:
            data = yaml.safe_load(yaml_content)
        except Exception as exc:
            raise RegistryError(f"Failed to parse YAML configuration: {exc}") from exc

        if not isinstance(data, dict):
            raise RegistryError("Configuration YAML root must be a dictionary/mapping.")

        self.clear()

        # Load providers
        raw_providers = data.get("providers", [])
        if not isinstance(raw_providers, list):
            raise RegistryError("'providers' section must be a list.")
        for raw_p in raw_providers:
            try:
                self.add_provider(ProviderConfig.from_dict(raw_p))
            except Exception as exc:
                raise RegistryError(f"Failed to load provider config: {exc}") from exc

        # Load models
        raw_models = data.get("models", [])
        if not isinstance(raw_models, list):
            raise RegistryError("'models' section must be a list.")
        for raw_m in raw_models:
            try:
                self.add_model(ModelConfig.from_dict(raw_m))
            except Exception as exc:
                raise RegistryError(f"Failed to load model config: {exc}") from exc

        self.validate()

    def load_from_file(self, path: Path | str) -> None:
        """Load registry from a YAML file path."""
        p = Path(path)
        if not p.exists():
            raise RegistryError(f"Configuration file not found: {p}")
        content = p.read_text(encoding="utf-8")
        self.load_from_yaml(content)

    def save_to_file(self, path: Path | str) -> None:
        """Serialize and save registry configuration to a YAML file."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "providers": [p.to_dict() for p in self.providers()],
            "models": [m.to_dict() for m in self.models()],
        }
        yaml_content = yaml.safe_dump(data, sort_keys=False, indent=2)
        p.write_text(yaml_content, encoding="utf-8")


def load_default_registry(config_dir: Optional[Path | str] = None) -> ModelRegistry:
    """Helper to load providers.yaml (or fallback to providers.example.yaml)."""
    base = Path(config_dir) if config_dir else Path.cwd() / "config"
    target = base / "providers.yaml"
    example = base / "providers.example.yaml"

    reg = ModelRegistry()
    if target.exists():
        reg.load_from_file(target)
    elif example.exists():
        reg.load_from_file(example)
    else:
        # Fallback minimal mock provider if no config file is found
        reg.add_provider(ProviderConfig(id="mock", protocol="mock"))
        reg.add_model(
            ModelConfig(
                id="mock-fast",
                display_name="Mock Fast Model",
                endpoints=[
                    EndpointConfig(
                        id="mock-fast@mock",
                        provider="mock",
                        api_model="mock-instant",
                    )
                ],
            )
        )
    return reg
