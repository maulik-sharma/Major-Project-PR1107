"""Fuzzy matching helper to link model names with Artificial Analysis slugs."""

from __future__ import annotations

import difflib
import re
from typing import Any, Dict, List


def _clean_tokens(s: str) -> List[str]:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", " ", s.lower()).strip()
    stop_words = {"chat", "model", "instruct", "preview", "free", "api", "ai", "v", "the"}
    return [t for t in cleaned.split() if t not in stop_words and len(t) > 1]


def suggest_model_slugs(
    model_identifier: str,
    aa_models: List[Dict[str, Any]],
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """Rank candidate AA model records by name and slug similarity to a target model ID.

    Args:
        model_identifier: Model ID or display name (e.g. "gpt-oss-120b" or "Claude Sonnet 5.5").
        aa_models: List of raw AA model dictionary records.
        limit: Maximum number of candidate suggestions to return.

    Returns:
        List of candidate suggestions ordered by highest similarity.
    """
    if not model_identifier or not aa_models:
        return []

    target_tokens = _clean_tokens(model_identifier)
    target_str = model_identifier.lower().replace("/", "-")

    scored_candidates: List[tuple[float, Dict[str, Any]]] = []

    for item in aa_models:
        if isinstance(item, str):
            slug = item.lower()
            name = item.lower()
            creator = ""
            raw_slug = item
            raw_name = item
            evals = {}
        elif isinstance(item, dict):
            slug = str(item.get("slug", "")).lower()
            name = str(item.get("name", "")).lower()
            creator = str(item.get("model_creator", {}).get("name", ""))
            raw_slug = item.get("slug", "")
            raw_name = item.get("name", "")
            evals = item.get("evaluations", {})
        else:
            continue

        # Ratio similarity with target string
        slug_ratio = difflib.SequenceMatcher(None, target_str, slug).ratio()
        name_ratio = difflib.SequenceMatcher(None, target_str, name).ratio()
        base_score = max(slug_ratio, name_ratio)

        # Token intersection bonus
        item_tokens = set(_clean_tokens(slug) + _clean_tokens(name))
        matched_tokens = [t for t in target_tokens if t in item_tokens]
        token_overlap = len(matched_tokens) / max(len(target_tokens), 1)

        # Exact substring bonus
        if target_str in slug or target_str in name:
            base_score = max(base_score, 0.85)

        total_score = (base_score * 0.6) + (token_overlap * 0.4)

        if total_score > 0.35:
            suggestion = {
                "slug": raw_slug,
                "name": raw_name,
                "creator": creator,
                "intelligence": evals.get("artificial_analysis_intelligence_index"),
                "coding": evals.get("artificial_analysis_coding_index"),
                "agentic": evals.get("artificial_analysis_agentic_index"),
                "similarity": round(total_score, 3),
            }
            scored_candidates.append((total_score, suggestion))

    scored_candidates.sort(key=lambda x: x[0], reverse=True)
    return [c[1] for c in scored_candidates[:limit]]

