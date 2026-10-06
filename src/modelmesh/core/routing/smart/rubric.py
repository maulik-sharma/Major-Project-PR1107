"""Rubric questions builder and version hashing."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict

from modelmesh.core.config.routing_config import RubricConfig


def build_rubric_questions(rubric: RubricConfig) -> Dict[str, Dict[str, Any]]:
    """Convert RubricConfig into the question dict expected by decision providers."""
    questions: Dict[str, Dict[str, Any]] = {}
    for qid, qcfg in rubric.questions.items():
        qdict: Dict[str, Any] = {
            "type": qcfg.type,
            "instructions": qcfg.instructions,
        }
        if qcfg.type == "choice" and qcfg.options:
            qdict["criteria"] = dict(qcfg.options)
        elif qcfg.type == "score" and qcfg.levels:
            qdict["criteria"] = list(qcfg.levels)
        questions[qid] = qdict
    return questions


def compute_rubric_hash(rubric: RubricConfig) -> str:
    """Compute a deterministic hash for cache keying."""
    questions_dict = build_rubric_questions(rubric)
    payload = {
        "version": rubric.version,
        "questions": questions_dict,
    }
    raw = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
