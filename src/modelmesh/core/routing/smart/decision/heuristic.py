"""Rule-based heuristic decision provider (offline baseline and fail-open fallback).

Runs on-device, so it reads the real latest user message even in privacy mode
(Rule 19 only restricts what is sent to remote providers).
"""

from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Pattern, Tuple

from modelmesh.core.routing.smart.decision.base import (
    DecisionProvider,
    DecisionRequest,
    DecisionResult,
    register_decision_provider,
)
from modelmesh.core.types import Usage


def _words(*terms: str) -> Pattern[str]:
    """Compile terms into one case-insensitive, word-boundary regex."""
    return re.compile(r"(?<!\w)(?:" + "|".join(terms) + r")(?!\w)", re.IGNORECASE)


# Checked in order; the first match wins.
_TASK_PATTERNS: List[Tuple[str, Pattern[str]]] = [
    ("coding", re.compile(
        r"```|\bdef \w+\(|\bclass [A-Z]\w*|\bimport \w+|=>|\w+\(\)|"
        r"(?<!\w)(?:python|javascript|typescript|java|c\+\+|c#|rust|golang|sql|regex|bash|"
        r"bug|debug|traceback|stack trace|exception|compiler?|refactor|unit tests?|"
        r"segfault|null pointer|api endpoint|asyncio|deadlock|code)(?!\w)",
        re.IGNORECASE,
    )),
    ("math_reasoning", _words(
        "prove", "proof", "theorem", "derive", "derivation", "integral", "integrate",
        "equation", "calculus", "matrix", "eigenvalues?", "solve for", "probability",
        "lemma", "differential",
    )),
    ("agentic_tool_use", _words(
        "search the web", "look up", "browse", "scrape", "fetch", "current weather",
        "run (?:the )?command", "latest news",
    )),
    ("translation_language", _words("translate", "translation", "in (?:spanish|french|german|hindi|chinese|japanese)")),
    ("summarization_extraction", _words("summari[sz]e", "summary", "tl;?dr", "extract", "key takeaways", "bullet points")),
    ("analysis_research", _words(
        "compare", "contrast", "trade-?offs?", "pros and cons", "analy[sz]e", "analysis",
        "evaluate", "architecture", "architectural", "research",
    )),
    ("writing_creative", _words("poem", "story", "essay", "blog post", "lyrics", "creative writing", "dialogue")),
]

_HARD_SIGNALS = _words(
    "deadlock", "race condition", "lock-free", "consensus", "distributed", "optimi[sz]e",
    "prove", "proof", "formal", "rigorous", "step by step", "complexity", "concurren(?:t|cy)",
)
_TRIVIAL = re.compile(
    r"^\s*(?:hi|hello|hey|yo|thanks|thank you|thx|ok(?:ay)?|cool|good (?:morning|night|evening))"
    r"[\s!.,?]*$",
    re.IGNORECASE,
)


def classify_task(text: str) -> str:
    """Return the rubric task label for a user message."""
    for task, pattern in _TASK_PATTERNS:
        if pattern.search(text):
            return task
    return "chat_general"


def score_difficulty(text: str, task: str) -> Tuple[float, float]:
    """Return (difficulty 0..4, confidence) for a user message."""
    if _TRIVIAL.match(text):
        return 0.05, 0.95
    length = len(text)
    if task == "chat_general":
        diff, conf = (0.6, 0.85) if length < 250 else (1.5, 0.7)
    elif length < 250:
        diff, conf = 1.5, 0.75
    elif length < 800:
        diff, conf = 2.2, 0.7
    else:
        diff, conf = 3.0, 0.65
    if task in ("coding", "math_reasoning"):
        diff = max(diff, 2.0)
    if "```" in text or _HARD_SIGNALS.search(text):
        diff = min(4.0, diff + 1.0)
    return diff, conf


@register_decision_provider("heuristic")
class HeuristicDecisionProvider(DecisionProvider):
    """Rule-based analyzer producing the exact same answer shape as Clef."""

    def decide(self, request: DecisionRequest) -> DecisionResult:
        start_time = time.perf_counter()
        text = request.latest_text if request.latest_text is not None else (request.state or "")
        context = request.context or {}

        task = classify_task(text)
        diff, conf_diff = score_difficulty(text, task)
        if context.get("has_images") and diff < 1.5:
            diff = 1.5  # Vision questions need a capable model even when short.

        if task in ("math_reasoning", "coding"):
            precision = 2.5
        elif task in ("analysis_research", "translation_language"):
            precision = 2.0
        elif task == "chat_general":
            precision = 0.1 if diff <= 0.1 else 0.6
        else:
            precision = 1.2

        if diff >= 3.0:
            benefit = 2.8
        elif diff >= 2.0:
            benefit = 1.6
        elif diff <= 0.1:
            benefit = 0.05
        elif diff < 1.0:
            benefit = 0.3
        else:
            benefit = 0.9

        needs_reasoning = 0.85 if task in ("math_reasoning", "coding") or diff >= 2.5 else (0.0 if diff <= 0.1 else 0.2)
        trivial = diff <= 0.1

        answers: Dict[str, Any] = {
            "task": {"type": "choice", "choice": task, "probabilities": {task: 0.85}, "confidence": 0.70},
            "difficulty": {"type": "score", "score": round(diff, 2), "confidence": round(conf_diff, 2)},
            "precision": {"type": "score", "score": round(precision, 2), "confidence": 0.75 if trivial else 0.65},
            "larger_model_benefit": {"type": "score", "score": round(benefit, 2), "confidence": 0.75 if trivial else 0.60},
            "needs_reasoning": {"type": "noul", "noul": round(needs_reasoning, 2)},
            "task_changed": {"type": "noul", "noul": 0.2},
        }

        return DecisionResult(
            answers=answers,
            source="heuristic",
            usage=Usage(input_tokens=max(10, len(text) // 4), output_tokens=0),
            latency_ms=round((time.perf_counter() - start_time) * 1000, 2),
            provider_id=request.provider_id or "heuristic",
            model="heuristic",
            raw_response={"answers": answers},
        )
