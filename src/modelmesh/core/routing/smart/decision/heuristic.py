"""Rule-based heuristic decision provider (offline baseline and fail-open fallback)."""

from __future__ import annotations

import re
import time
from typing import Any, Dict

from modelmesh.core.routing.smart.decision.base import (
    DecisionProvider,
    DecisionRequest,
    DecisionResult,
    register_decision_provider,
)
from modelmesh.core.types import Usage


@register_decision_provider("heuristic")
class HeuristicDecisionProvider(DecisionProvider):
    """Rule-based analyzer producing the exact same answer shape as Clef."""

    def decide(self, request: DecisionRequest) -> DecisionResult:
        start_time = time.perf_counter()
        state = request.state or ""
        state_lower = state.lower()

        # 1. Task classification
        code_indicators = ["def ", "class ", "function", "import ", "const ", "```", "bug", "traceback", "exception", "asyncio", "sql", "rust", "python", "javascript", "c++"]
        math_indicators = ["derive", "proof", "prove", "theorem", "equation", "solve for", "calculus", "integral", "matrix", "multiplied by", "divided by"]
        creative_indicators = ["write a poem", "write a story", "draft a blog", "essay", "creative writing", "metaphor", "dialogue"]
        summary_indicators = ["summarize", "tldr", "extract", "bullet points", "synopsis", "key takeaways"]
        translation_indicators = ["translate", "spanish", "german", "french", "chinese", "japanese", "hindi"]
        analysis_indicators = ["compare", "contrast", "tradeoffs", "pros and cons", "analysis", "architectural", "evaluation", "benchmark"]
        tool_indicators = ["fetch", "search the web", "look up", "current weather", "scrape", "browse", "run command"]

        task_choice = "chat_general"
        if any(w in state_lower for w in code_indicators):
            task_choice = "coding"
        elif any(w in state_lower for w in math_indicators):
            task_choice = "math_reasoning"
        elif any(w in state_lower for w in tool_indicators):
            task_choice = "agentic_tool_use"
        elif any(w in state_lower for w in translation_indicators):
            task_choice = "translation_language"
        elif any(w in state_lower for w in summary_indicators):
            task_choice = "summarization_extraction"
        elif any(w in state_lower for w in analysis_indicators):
            task_choice = "analysis_research"
        elif any(w in state_lower for w in creative_indicators):
            task_choice = "writing_creative"

        # 2. Difficulty scoring (0 to 4)
        length = len(state)
        lines = len(state.splitlines())
        has_code_fences = "```" in state

        diff_score = 0.5
        if length < 60 and lines <= 2:
            diff_score = 0.1  # Trivial
        elif length < 250:
            diff_score = 1.2  # Easy
        elif length < 800:
            diff_score = 2.0  # Moderate
        else:
            diff_score = 3.2  # Hard

        if has_code_fences or "deadlock" in state_lower or "consensus" in state_lower or "lock-free" in state_lower or "dominance" in state_lower:
            diff_score = min(4.0, diff_score + 1.0)

        # 3. Precision scoring (0 to 3)
        precision_score = 1.0
        if task_choice in ("math_reasoning", "coding"):
            precision_score = 2.5
        elif task_choice in ("analysis_research", "translation_language"):
            precision_score = 2.0
        elif task_choice == "chat_general" and diff_score < 0.5:
            precision_score = 0.2

        # 4. Larger model benefit (0 to 3)
        benefit_score = 0.5
        if diff_score >= 3.0:
            benefit_score = 2.8
        elif diff_score >= 2.0:
            benefit_score = 1.6
        elif diff_score < 1.0:
            benefit_score = 0.2

        # 5. Needs reasoning (0 to 1)
        needs_reasoning = 0.1
        if task_choice in ("math_reasoning", "coding") or diff_score >= 2.5:
            needs_reasoning = 0.85

        # 6. Task changed (0 to 1)
        task_changed = 0.2

        answers: Dict[str, Any] = {
            "task": {
                "type": "choice",
                "choice": task_choice,
                "probabilities": {task_choice: 0.85},
                "confidence": 0.70,
            },
            "difficulty": {
                "type": "score",
                "score": round(diff_score, 2),
                "confidence": 0.60,
            },
            "precision": {
                "type": "score",
                "score": round(precision_score, 2),
                "confidence": 0.65,
            },
            "larger_model_benefit": {
                "type": "score",
                "score": round(benefit_score, 2),
                "confidence": 0.60,
            },
            "needs_reasoning": {
                "type": "noul",
                "noul": round(needs_reasoning, 2),
            },
            "task_changed": {
                "type": "noul",
                "noul": round(task_changed, 2),
            },
        }

        latency_ms = (time.perf_counter() - start_time) * 1000

        # Estimate input tokens
        input_tokens_est = max(10, len(state) // 4)

        return DecisionResult(
            answers=answers,
            usage=Usage(input_tokens=input_tokens_est, output_tokens=0),
            latency_ms=round(latency_ms, 2),
            provider_id=request.provider_id or "heuristic",
            model="heuristic",
            raw_response={"answers": answers},
            source="heuristic",
        )
