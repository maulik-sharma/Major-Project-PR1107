"""Fuzzy matching helper to link model names with Artificial Analysis slugs."""

from __future__ import annotations

import difflib
import functools
import re
from typing import Any, Callable, Dict, FrozenSet, List, Optional, Tuple


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



_STRICT_STOP_WORDS = {"chat", "model", "instruct", "it", "preview", "free", "api", "the", "v"}


@functools.lru_cache(maxsize=16384)
def _strict_tokens(s: str) -> Tuple[FrozenSet[str], Tuple[str, ...]]:
    """(word tokens, version numbers) of a name, ignoring bracketed variants and dates.

    "Claude Haiku 4.5 (20251001)" -> ({"claude", "haiku"}, ("4", "5")).
    """
    s = re.sub(r"\([^)]*\)", " ", s.lower())
    parts = re.findall(r"[a-z]+|\d+", s)
    words = frozenset(p for p in parts if p.isalpha() and p not in _STRICT_STOP_WORDS)
    numbers = tuple(p for p in parts if p.isdigit() and len(p) < 6)
    return words, numbers


def strict_match(
    identifiers: List[str],
    records: List[Dict[str, Any]],
    prefer: Optional[Callable[[Dict[str, Any]], float]] = None,
) -> Optional[str]:
    """Return the slug of the record that is unambiguously the same model, else None.

    Safe for automatic linking: version numbers must be identical (so "Opus 5.5"
    never links to "Opus 4.6") and every word of the identifier must appear in
    the record's name or slug. A record with exactly the identifier's words (slug
    before display name) beats one with extra words (e.g. a "-low" variant). If
    several equally good records remain, ``prefer`` (e.g. vote count) picks one;
    without it the match is ambiguous. Identifiers (e.g. api model, model id, display name) are tried in turn.
    """
    for ident in identifiers:
        words, numbers = _strict_tokens(ident)
        if not words:
            continue
        exact_slug: Dict[str, Dict[str, Any]] = {}
        exact_name: Dict[str, Dict[str, Any]] = {}
        subset: Dict[str, Dict[str, Any]] = {}
        for rec in records:
            slug = str(rec.get("slug") or "")
            for is_slug, text in ((True, slug), (False, str(rec.get("name") or ""))):
                r_words, r_numbers = _strict_tokens(text)
                if r_numbers != numbers or not words <= r_words:
                    continue
                if r_words != words:
                    subset[slug] = rec
                else:
                    (exact_slug if is_slug else exact_name)[slug] = rec
        for hits in (exact_slug, exact_name, subset):
            if len(hits) == 1:
                return next(iter(hits))
            if len(hits) > 1:
                if prefer is not None:
                    return max(hits, key=lambda k: prefer(hits[k]))
                break
    return None


def arena_votes(record: Dict[str, Any]) -> float:
    """Preference for ``strict_match`` on LMArena records: the most-voted variant."""
    return float((record.get("votes") or {}).get("overall", 0))


def match_identifiers(model: Any) -> List[str]:
    """Names to try when linking a model: each endpoint's api model, then id, then display name."""
    names = []
    for ep in getattr(model, "endpoints", []) or []:
        api = str(ep.api_model or "").split("/")[-1].split(":")[0]
        if api and api not in names:
            names.append(api)
    return names + [model.id, model.display_name]
