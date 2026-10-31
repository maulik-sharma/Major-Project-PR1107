"""LMArena score source: download, parse, and effective-score resolution (synthetic data)."""

from __future__ import annotations

import io
from typing import Any, Dict, List

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import respx

from modelmesh.core.errors import ProviderError
from modelmesh.core.scores.arena_client import ARENA_SOURCE, LMArenaClient, records_from_rows
from modelmesh.core.scores.snapshots import ScoreSnapshot, resolve_effective_scores
from modelmesh.core.types import ManualScoresConfig, ModelConfig, ModelScoresConfig

URL = "https://example.test/leaderboard.parquet"


def _row(name: str, cat: str, rating: float, date: str = "2026-01-02") -> Dict[str, Any]:
    """One row shaped like the published file (Bradley-Terry columns)."""
    return {
        "model_name": name, "organization": "org", "license": "Proprietary",
        "rating": rating, "rating_lower": rating - 5, "rating_upper": rating + 5,
        "variance": 1.0, "vote_count": 1000.0, "rank": 1, "category": cat,
        "leaderboard_publish_date": date,
    }


def _parquet(rows: List[Dict[str, Any]]) -> bytes:
    buf = io.BytesIO()
    pq.write_table(pa.Table.from_pylist(rows), buf)
    return buf.getvalue()


ROWS = [
    _row("Model A (High)", "overall", 1400.0),
    _row("Model A (High)", "coding", 1450.0),
    _row("Model A (High)", "korean", 1300.0),
    _row("Model B", "overall", 1350.0, date="2026-01-05"),
]


def test_records_group_categories_per_model() -> None:
    recs = {r["slug"]: r for r in records_from_rows(ROWS, ["overall", "coding"])}
    assert recs["Model A (High)"]["ratings"] == {"overall": 1400.0, "coding": 1450.0}
    assert recs["Model A (High)"]["votes"]["coding"] == 1000
    assert recs["Model B"]["ratings"] == {"overall": 1350.0}


@respx.mock
def test_fetch_snapshot_from_parquet() -> None:
    respx.get(URL).respond(200, content=_parquet(ROWS))
    snap = LMArenaClient(url=URL, categories=["overall", "coding"]).fetch_snapshot()
    assert snap.source == ARENA_SOURCE
    assert snap.index_version == "2026-01-05"
    assert set(snap.models_by_slug) == {"Model A (High)", "Model B"}


@respx.mock
def test_changed_columns_are_reported_not_guessed() -> None:
    renamed = [{"model": r["model_name"], "elo": r["rating"], "category": r["category"]} for r in ROWS]
    respx.get(URL).respond(200, content=_parquet(renamed))
    with pytest.raises(ProviderError) as exc:
        LMArenaClient(url=URL).fetch_snapshot()
    assert exc.value.category == "bad_request"
    assert "model_name" in str(exc.value)


@respx.mock
def test_http_errors_are_normalised() -> None:
    respx.get(URL).respond(503)
    with pytest.raises(ProviderError) as exc:
        LMArenaClient(url=URL).fetch_snapshot()
    assert exc.value.category == "server" and exc.value.retryable


def test_effective_scores_include_arena_ratings() -> None:
    arena = ScoreSnapshot.from_raw(records_from_rows(ROWS, ["overall", "coding"]), source=ARENA_SOURCE)
    linked = ModelConfig(id="a", display_name="A", scores=ModelScoresConfig(arena_name="Model A (High)"))
    eff = resolve_effective_scores(linked, None, arena)
    assert eff.metric("arena_coding") == 1450.0
    assert eff.metric("intelligence") is None
    assert not eff.is_unscored and eff.source == "snapshot"


def test_manual_arena_elo_overrides_overall() -> None:
    arena = ScoreSnapshot.from_raw(records_from_rows(ROWS, ["overall"]), source=ARENA_SOURCE)
    m = ModelConfig(id="a", display_name="A", scores=ModelScoresConfig(
        arena_name="Model A (High)", manual=ManualScoresConfig(arena_text_elo=1500.0)))
    eff = resolve_effective_scores(m, None, arena)
    assert eff.metric("arena_overall") == 1500.0 and eff.is_manual


def test_arena_name_round_trips_through_config() -> None:
    cfg = ModelScoresConfig.from_dict({"aa_slug": "x", "arena_name": "Model A (High)"})
    assert ModelScoresConfig.from_dict(cfg.to_dict()).arena_name == "Model A (High)"
