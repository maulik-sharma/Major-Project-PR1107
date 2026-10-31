"""Choose which stored Artificial Analysis snapshot to rank with.

AA occasionally ships a new index version (e.g. v4.3 -> v5) that has only
re-scored a fraction of models. Scores from different versions are not on the
same scale, so we never mix them: we pick the single snapshot that scores the
most configured models, preferring the newest on ties. Pure: no I/O (Rule 18).
"""

from __future__ import annotations

import datetime
from typing import Optional, Sequence, Tuple

from modelmesh.core.scores.snapshots import ScoreSnapshot
from modelmesh.core.types import ModelConfig

_INTELLIGENCE_KEY = "artificial_analysis_intelligence_index"


def _slug_of(model: ModelConfig) -> Optional[str]:
    slug = model.scores.aa_slug
    if isinstance(slug, dict):
        slug = slug.get("slug")
    return str(slug) if slug else None


def intelligence_coverage(snapshot: ScoreSnapshot, models: Sequence[ModelConfig]) -> int:
    """Number of models whose linked AA record has an intelligence score in this snapshot."""
    count = 0
    for m in models:
        slug = _slug_of(m)
        record = snapshot.models_by_slug.get(slug) if slug else None
        if record and (record.get("evaluations") or {}).get(_INTELLIGENCE_KEY) is not None:
            count += 1
    return count


def choose_snapshot(
    snapshots: Sequence[ScoreSnapshot],
    models: Sequence[ModelConfig],
) -> Tuple[Optional[ScoreSnapshot], Optional[str]]:
    """Return (snapshot to use, explanation when it is not the newest one).

    Args:
        snapshots: Candidate snapshots, typically the newest one per index version.
        models: Configured models whose coverage decides the choice.
    """
    if not snapshots:
        return None, None
    newest = max(snapshots, key=lambda s: s.fetched_at)
    linked = [m for m in models if _slug_of(m)]
    if not linked:
        return newest, None

    coverage = {s.id: intelligence_coverage(s, linked) for s in snapshots}
    best = max(snapshots, key=lambda s: (coverage[s.id], s.fetched_at))
    if best.id == newest.id:
        return newest, None

    def _label(s: ScoreSnapshot) -> str:
        day = datetime.datetime.fromtimestamp(s.fetched_at).strftime("%Y-%m-%d")
        return f"index v{s.index_version or '?'} ({day})"

    note = (
        f"Newest Artificial Analysis snapshot, {_label(newest)}, scores {coverage[newest.id]} of "
        f"{len(linked)} linked models; using {_label(best)}, which scores {coverage[best.id]}."
    )
    return best, note

