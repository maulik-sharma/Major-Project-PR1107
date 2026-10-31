"""Choosing an AA snapshot across index versions (synthetic data only, Rule 16)."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from modelmesh.core.registry import ModelRegistry
from modelmesh.core.routing.router import Router
from modelmesh.core.scores.selection import choose_snapshot
from modelmesh.core.scores.snapshots import ScoreSnapshot, ScoreStore
from modelmesh.core.storage import Storage
from modelmesh.core.types import ModelConfig, ModelScoresConfig


def _model(mid: str, slug: Optional[str]) -> ModelConfig:
    return ModelConfig(id=mid, display_name=mid, scores=ModelScoresConfig(aa_slug=slug))


def _snap(version: str, fetched_at: float, scored: Dict[str, Optional[float]], sid: str) -> ScoreSnapshot:
    records: List[dict] = [
        {"slug": slug, "evaluations": {"artificial_analysis_intelligence_index": val}}
        for slug, val in scored.items()
    ]
    return ScoreSnapshot.from_raw(records, index_version=version, snapshot_id=sid, fetched_at=fetched_at)


MODELS = [_model("a", "slug-a"), _model("b", "slug-b"), _model("c", "slug-c"), _model("x", None)]


def test_newer_version_with_poor_coverage_keeps_older_snapshot() -> None:
    old = _snap("4", 1000.0, {"slug-a": 50, "slug-b": 30, "slug-c": 10}, "old")
    new = _snap("5", 2000.0, {"slug-a": 55, "slug-b": None, "slug-c": None}, "new")
    chosen, note = choose_snapshot([new, old], MODELS)
    assert chosen.id == "old"
    assert note and "v5" in note and "1 of 3" in note and "v4" in note


def test_newest_wins_when_coverage_ties() -> None:
    old = _snap("4", 1000.0, {"slug-a": 50, "slug-b": 30}, "old")
    new = _snap("5", 2000.0, {"slug-a": 55, "slug-b": 40}, "new")
    chosen, note = choose_snapshot([old, new], MODELS)
    assert chosen.id == "new" and note is None


def test_no_linked_models_uses_newest() -> None:
    old = _snap("4", 1000.0, {"slug-a": 50}, "old")
    new = _snap("5", 2000.0, {}, "new")
    chosen, note = choose_snapshot([old, new], [_model("x", None)])
    assert chosen.id == "new" and note is None


def test_store_considers_newest_snapshot_of_each_version(tmp_path: Path) -> None:
    store = ScoreStore(Storage(tmp_path / "s.db"))
    store.save_snapshot(_snap("4", 1000.0, {"slug-a": 1, "slug-b": 1, "slug-c": 1}, "v4-old"))
    store.save_snapshot(_snap("4", 1500.0, {"slug-a": 2, "slug-b": 2, "slug-c": 2}, "v4-new"))
    store.save_snapshot(_snap("5", 2000.0, {"slug-a": 3}, "v5"))
    chosen, note = store.get_active_snapshot(MODELS)
    assert chosen.id == "v4-new"
    assert note is not None


def test_router_reselects_when_a_link_changes(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "r.db")
    store = ScoreStore(storage)
    store.save_snapshot(_snap("4", 1000.0, {"slug-a": 1, "slug-b": 1}, "v4"))
    store.save_snapshot(_snap("5", 2000.0, {"slug-a": 3, "slug-z": 3}, "v5"))
    reg = ModelRegistry()
    reg.add_model(_model("a", "slug-a"))
    reg.add_model(_model("b", "slug-b"))
    router = Router(registry=reg, storage=storage)
    assert router._active_snapshot()[0].id == "v4"
    reg.get_model("b").scores.aa_slug = "slug-z"  # now v5 covers both -> newest wins
    assert router._active_snapshot()[0].id == "v5"
