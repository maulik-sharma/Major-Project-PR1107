"""Scores tab: both sources shown, stale links flagged, strict auto-match (synthetic data)."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import QMessageBox

from modelmesh.core.registry import ModelRegistry
from modelmesh.core.scores.arena_client import ARENA_SOURCE
from modelmesh.core.scores.matcher import arena_votes, strict_match
from modelmesh.core.scores.snapshots import ScoreSnapshot, ScoreStore
from modelmesh.core.storage import Storage
from modelmesh.core.types import EndpointConfig, ModelConfig, ModelScoresConfig, ProviderConfig
from modelmesh.ui.settings.scores_tab import ScoresTab

AA = [
    {"slug": "acme-2", "name": "Acme 2 (High)", "evaluations": {"artificial_analysis_intelligence_index": 30.0}},
    {"slug": "acme-2-1", "name": "Acme 2.1 (High)", "evaluations": {"artificial_analysis_intelligence_index": 40.0}},
    {"slug": "acme-2-1-low", "name": "Acme 2.1 (Low)", "evaluations": {"artificial_analysis_intelligence_index": 20.0}},
    {"slug": "beta-7b", "name": "Beta 7B", "evaluations": {"artificial_analysis_intelligence_index": 9.0}},
]
ARENA = [
    {"slug": "Acme 2.1 (High)", "name": "Acme 2.1 (High)", "ratings": {"overall": 1400.0, "coding": 1450.0},
     "votes": {"overall": 900}},
    {"slug": "Acme 2.1 (Low)", "name": "Acme 2.1 (Low)", "ratings": {"overall": 1300.0}, "votes": {"overall": 50}},
]


def _model(mid: str, api: str, aa_slug: str | None = None) -> ModelConfig:
    return ModelConfig(
        id=mid, display_name=mid, scores=ModelScoresConfig(aa_slug=aa_slug),
        endpoints=[EndpointConfig(id=f"{mid}@p", provider="p", api_model=api)],
    )


def test_strict_match_never_crosses_versions() -> None:
    assert strict_match(["acme-2.1"], AA) == "acme-2-1"
    assert strict_match(["acme-3"], AA) is None
    assert strict_match(["gamma-7b"], AA) is None  # shares "7b" with beta-7b but not the name
    assert strict_match(["acme-2.1"], ARENA, arena_votes) == "Acme 2.1 (High)"


def test_tab_flags_stale_link_and_automatch_fixes_it(qapp, tmp_path: Path, monkeypatch) -> None:
    storage = Storage(tmp_path / "s.db")
    store = ScoreStore(storage)
    store.save_snapshot(ScoreSnapshot.from_raw(AA, index_version="1"))
    store.save_snapshot(ScoreSnapshot.from_raw(ARENA, index_version="2026-01-01", source=ARENA_SOURCE))
    reg = ModelRegistry()
    reg.add_provider(ProviderConfig(id="p", protocol="mock"))
    reg.add_model(_model("acme", "vendor/acme-2.1", aa_slug="acme-2"))  # endpoint calls 2.1, linked to 2
    reg.add_model(_model("beta", "beta-7b"))
    monkeypatch.setattr(reg, "save", lambda: True)

    tab = ScoresTab(registry=reg, storage=storage)
    assert tab.table.item(0, 8).text() == "Check link"
    assert tab._stale == {"acme": ("acme-2-1", None)}

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    tab._on_automatch_clicked()
    acme, beta = reg.get_model("acme"), reg.get_model("beta")
    assert acme.scores.aa_slug == "acme-2-1"
    assert acme.scores.arena_name == "Acme 2.1 (High)"
    assert beta.scores.aa_slug == "beta-7b" and beta.scores.arena_name is None
    assert tab.table.item(0, 7).text() == "1450"
    assert tab.table.item(0, 8).text() == "OK"
