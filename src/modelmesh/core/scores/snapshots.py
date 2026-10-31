"""Snapshot storage and effective score resolution."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

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
    # LMArena ratings by category (e.g. {"overall": 1450.0, "coding": 1500.0}).
    arena: Dict[str, float] = field(default_factory=dict)
    arena_name: Optional[str] = None

    def metric(self, name: str) -> Optional[float]:
        """Value of a ranking metric: intelligence/coding/agentic (AA) or arena_<category>."""
        if name.startswith("arena_"):
            return self.arena.get(name[len("arena_"):])
        return {"intelligence": self.intelligence, "coding": self.coding, "agentic": self.agentic}.get(name)


def resolve_effective_scores(
    model: ModelConfig,
    snapshot: Optional[ScoreSnapshot] = None,
    arena_snapshot: Optional[ScoreSnapshot] = None,
) -> EffectiveScores:
    """Determine effective AA scores and LMArena ratings for a model.

    Priority:
    1. Manual overrides in model.scores.manual (arena_text_elo overrides arena "overall")
    2. Linked record in the AA snapshot via model.scores.aa_slug, and in the
       LMArena snapshot via model.scores.arena_name
    3. Unscored (None). A missing metric is never filled from another one:
       the selector decides which single metric to rank a whole pool on.
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

    aa_slug = model.scores.aa_slug
    if isinstance(aa_slug, dict):
        aa_slug = aa_slug.get("slug")
    if aa_slug is not None and not isinstance(aa_slug, str):
        aa_slug = str(aa_slug)

    aa_record: Optional[Dict[str, Any]] = None
    if aa_slug and snapshot and aa_slug in snapshot.models_by_slug:
        aa_record = snapshot.models_by_slug[aa_slug]
        evals = aa_record.get("evaluations", {})
        if intel is None and evals.get("artificial_analysis_intelligence_index") is not None:
            intel = float(evals["artificial_analysis_intelligence_index"])
        if code is None and evals.get("artificial_analysis_coding_index") is not None:
            code = float(evals["artificial_analysis_coding_index"])
        if agent is None and evals.get("artificial_analysis_agentic_index") is not None:
            agent = float(evals["artificial_analysis_agentic_index"])

    arena_name = model.scores.arena_name
    arena: Dict[str, float] = {}
    if arena_name and arena_snapshot and arena_name in arena_snapshot.models_by_slug:
        for cat, val in (arena_snapshot.models_by_slug[arena_name].get("ratings") or {}).items():
            if val is not None:
                arena[cat] = float(val)
    if elo is not None:
        arena["overall"] = elo
    has_any_manual = has_any_manual or elo is not None

    is_unscored = (intel is None and code is None and agent is None and not arena)
    if is_unscored:
        source = "unscored"
    elif has_any_manual:
        source = "manual"
    elif aa_record is not None or arena:
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
        aa_slug=aa_slug,
        arena=arena,
        arena_name=arena_name,
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

    def get_latest_snapshot_id(self, source: str = "artificial_analysis") -> Optional[str]:
        """Return a cheap marker that changes whenever a newer snapshot is stored."""
        return self.storage.get_newest_score_snapshot_id(source=source)

    def get_latest_snapshot(self, source: str = "artificial_analysis") -> Optional[ScoreSnapshot]:
        """Fetch the most recent snapshot from the database."""
        row = self.storage.get_latest_score_snapshot(source=source)
        if not row:
            return None
        return ScoreSnapshot.from_storage_dict(row)

    def get_active_snapshot(
        self,
        models: List[ModelConfig],
        source: str = "artificial_analysis",
    ) -> Tuple[Optional[ScoreSnapshot], Optional[str]]:
        """Snapshot to rank with: the index version that scores the most configured models.

        Returns (snapshot, note); the note explains when an older version was kept.
        """
        from modelmesh.core.scores.selection import choose_snapshot

        rows = self.storage.get_newest_score_snapshots_per_version(source=source)
        return choose_snapshot([ScoreSnapshot.from_storage_dict(r) for r in rows], models)
