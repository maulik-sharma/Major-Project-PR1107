"""Unit tests for Artificial Analysis client, snapshot store, and score resolver."""

import json
from pathlib import Path
import pytest
import respx
import httpx

from modelmesh.core.scores.aa_client import (
    ATTRIBUTION_TEXT,
    ArtificialAnalysisClient,
)
from modelmesh.core.scores.matcher import suggest_model_slugs
from modelmesh.core.scores.snapshots import (
    EffectiveScores,
    ScoreSnapshot,
    ScoreStore,
    resolve_effective_scores,
)
from modelmesh.core.storage import Storage
from modelmesh.core.types import ManualScoresConfig, ModelConfig, ModelScoresConfig


def test_scores_attribution_constant() -> None:
    """Verify required attribution text per Rule 16."""
    assert ATTRIBUTION_TEXT == "Model scores: Artificial Analysis"


def test_resolve_effective_scores_priority() -> None:
    """Verify manual overrides win over snapshot values, and unlinked models are unscored."""
    fixture_path = Path(__file__).resolve().parent / "fixtures" / "aa_response_synthetic.json"
    with open(fixture_path, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    snapshot = ScoreSnapshot.from_raw(
        models_list=raw_data["data"],
        index_version=raw_data["intelligence_index_version"],
    )

    # 1. Linked model without manual overrides
    m1 = ModelConfig(
        id="m1",
        display_name="Synthetic Flagship",
        scores=ModelScoresConfig(aa_slug="synthetic-flagship-1"),
    )
    eff1 = resolve_effective_scores(m1, snapshot)
    assert eff1.is_unscored is False
    assert eff1.is_manual is False
    assert eff1.intelligence == 72.0
    assert eff1.coding == 85.0
    assert eff1.agentic == 65.0
    assert eff1.source == "snapshot"

    # 2. Linked model WITH manual override on intelligence
    m2 = ModelConfig(
        id="m2",
        display_name="Synthetic Mid",
        scores=ModelScoresConfig(
            aa_slug="synthetic-mid-1",
            manual=ManualScoresConfig(intelligence=99.0),
        ),
    )
    eff2 = resolve_effective_scores(m2, snapshot)
    assert eff2.is_unscored is False
    assert eff2.is_manual is True
    assert eff2.intelligence == 99.0
    assert eff2.coding == 55.0  # From snapshot
    assert eff2.source == "manual"

    # 3. Unlinked model
    m3 = ModelConfig(
        id="m3",
        display_name="Custom Model",
        scores=ModelScoresConfig(aa_slug=None),
    )
    eff3 = resolve_effective_scores(m3, snapshot)
    assert eff3.is_unscored is True
    assert eff3.source == "unscored"


def test_score_store_sqlite_roundtrip(tmp_path: Path) -> None:
    """Verify persisting and retrieving snapshots from SQLite."""
    storage = Storage(tmp_path / "test_modelmesh.db")
    store = ScoreStore(storage)

    models_data = [
        {
            "slug": "test-slug-1",
            "name": "Test Model 1",
            "evaluations": {
                "artificial_analysis_intelligence_index": 50.0,
            }
        }
    ]
    snap = ScoreSnapshot.from_raw(
        models_list=models_data,
        index_version="4.3",
        rate_limit_remaining=95,
    )
    store.save_snapshot(snap)

    latest = store.get_latest_snapshot()
    assert latest is not None
    assert latest.index_version == "4.3"
    assert latest.rate_limit_remaining == 95
    assert "test-slug-1" in latest.models_by_slug
    assert latest.models_by_slug["test-slug-1"]["evaluations"]["artificial_analysis_intelligence_index"] == 50.0


def test_matcher_suggestions() -> None:
    """Verify fuzzy slug matching returns sensible candidates."""
    aa_models = [
        {"slug": "claude-sonnet-5-5-medium", "name": "Claude Sonnet 5.5 Medium", "evaluations": {"artificial_analysis_intelligence_index": 40.8}},
        {"slug": "claude-3-5-haiku", "name": "Claude 3.5 Haiku", "evaluations": {"artificial_analysis_intelligence_index": 8.9}},
        {"slug": "gpt-6-sol-high", "name": "GPT-6 Sol High", "evaluations": {"artificial_analysis_intelligence_index": 42.4}},
    ]
    suggestions = suggest_model_slugs("claude-sonnet-5-5", aa_models)
    assert len(suggestions) >= 1
    assert suggestions[0]["slug"] == "claude-sonnet-5-5-medium"


@respx.mock
def test_aa_client_pagination() -> None:
    """Verify AA client handles multi-page responses."""
    page1 = {
        "tier": "free",
        "intelligence_index_version": "4.3",
        "pagination": {"page": 1, "has_more": True},
        "data": [{"slug": "m1", "name": "Model 1"}]
    }
    page2 = {
        "tier": "free",
        "intelligence_index_version": "4.3",
        "pagination": {"page": 2, "has_more": False},
        "data": [{"slug": "m2", "name": "Model 2"}]
    }

    respx.get("https://artificialanalysis.ai/api/v2/language/models/free?page=1").respond(
        200, json=page1, headers={"x-ratelimit-remaining": "98"}
    )
    respx.get("https://artificialanalysis.ai/api/v2/language/models/free?page=2").respond(
        200, json=page2, headers={"x-ratelimit-remaining": "97"}
    )

    client = ArtificialAnalysisClient(api_key="test-key")
    models, ver, rl = client.fetch_all_models()
    assert len(models) == 2
    assert ver == "4.3"
    assert rl == 97
