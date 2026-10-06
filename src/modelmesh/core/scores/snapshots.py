"""Snapshot storage and effective score resolution."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from modelmesh.core.storage import Storage
from modelmesh.core.types import ModelConfig


@dataclass
class ScoreSnapshot:
    """In-memory representation of an external score snapshot."""
    id: str
    source: str
    fetched_at: float
    index_version: Optional[str]
    models_by_slug: Dict[str, Dict[str, Any]]
    raw_payload: Dict[str, Any]
    rate_limit_remaining: Optional[int] = None

    @classmethod
    def from_raw(
        cls,
        models_list: List[Dict[str, Any]],
        index_version: Optional[str] = None,
        source: str = "artificial_analysis",
        rate_limit_remaining: Optional[int] = None,
        snapshot_id: Optional[str] = None,
        fetched_at: Optional[float] = None,
    ) -> ScoreSnapshot:
        by_slug: Dict[str, Dict[str, Any]] = {}
        for m in models_list:
            slug = m.get("slug")
            if slug:
                by_slug[slug] = m

        return cls(
            id=snapshot_id or str(uuid.uuid4()),
            source=source,
            fetched_at=fetched_at or time.time(),
            index_version=index_version,
            models_by_slug=by_slug,
            raw_payload={"models": models_list, "index_version": index_version},
            rate_limit_remaining=rate_limit_remaining,
        )

    @classmethod
    def from_storage_dict(cls, data: Dict[str, Any]) -> ScoreSnapshot:
        payload = data.get("payload", {})
        models_list = payload.get("models") or payload.get("data") or []
        by_slug: Dict[str, Dict[str, Any]] = {}
        for m in models_list:
            slug = m.get("slug")
            if slug:
                by_slug[slug] = m
        return cls(
            id=data["id"],
            source=data.get("source", "artificial_analysis"),
            fetched_at=float(data.get("fetched_at", time.time())),
            index_version=data.get("index_version"),
            models_by_slug=by_slug,
            raw_payload=payload,
            rate_limit_remaining=data.get("rate_limit_remaining"),
        )


@dataclass
class EffectiveScores:
    """Resolved quality scores for a logical model across manual overrides and snapshots."""
    intelligence: Optional[float] = None
    coding: Optional[float] = None
    agentic: Optional[float] = None
    arena_text_elo: Optional[float] = None
    source: str = "unscored"  # "manual", "snapshot", "unscored"
    is_manual: bool = False
    is_unscored: bool = True
    aa_slug: Optional[str] = None


def resolve_effective_scores(
    model: ModelConfig,
    snapshot: Optional[ScoreSnapshot] = None,
) -> EffectiveScores:
    """Determine effective intelligence, coding, and agentic scores for a model.

    Priority:
    1. Manual overrides in model.scores.manual
    2. Linked record in score snapshot via model.scores.aa_slug
    3. Unscored
    """
    manual = model.scores.manual
    has_any_manual = (
        manual.intelligence is not None
        or manual.coding is not None
        or manual.agentic is not None
    )

    intel = manual.intelligence
    code = manual.coding
    agent = manual.agentic
    elo = manual.arena_text_elo
    source = "manual" if has_any_manual else "unscored"

    aa_record: Optional[Dict[str, Any]] = None
    if model.scores.aa_slug and snapshot and model.scores.aa_slug in snapshot.models_by_slug:
        aa_record = snapshot.models_by_slug[model.scores.aa_slug]
        evals = aa_record.get("evaluations", {})
        if intel is None and evals.get("artificial_analysis_intelligence_index") is not None:
            intel = float(evals["artificial_analysis_intelligence_index"])
        if code is None and evals.get("artificial_analysis_coding_index") is not None:
            code = float(evals["artificial_analysis_coding_index"])
        if agent is None and evals.get("artificial_analysis_agentic_index") is not None:
            agent = float(evals["artificial_analysis_agentic_index"])

    is_unscored = (intel is None and code is None and agent is None)
    if is_unscored:
        source = "unscored"
    elif has_any_manual:
        source = "manual"
    elif aa_record is not None:
        source = "snapshot"
    else:
        source = "unscored"

    return EffectiveScores(
        intelligence=intel,
        coding=code,
        agentic=agent,
        arena_text_elo=elo,
        source=source,
        is_manual=has_any_manual,
        is_unscored=is_unscored,
        aa_slug=model.scores.aa_slug,
    )


class ScoreStore:
    """Persistence manager for score snapshots using the SQLite storage layer."""

    def __init__(self, storage: Storage) -> None:
        self.storage = storage

    def save_snapshot(self, snapshot: ScoreSnapshot) -> str:
        """Persist a snapshot to the database."""
        return self.storage.save_score_snapshot(
            source=snapshot.source,
            index_version=snapshot.index_version,
            payload=snapshot.raw_payload,
            rate_limit_remaining=snapshot.rate_limit_remaining,
            snapshot_id=snapshot.id,
            fetched_at=snapshot.fetched_at,
        )

    def get_latest_snapshot(self, source: str = "artificial_analysis") -> Optional[ScoreSnapshot]:
        """Fetch the most recent snapshot from the database."""
        row = self.storage.get_latest_score_snapshot(source=source)
        if not row:
            return None
        return ScoreSnapshot.from_storage_dict(row)
