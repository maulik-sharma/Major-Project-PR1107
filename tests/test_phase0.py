"""Unit tests for Phase 0 Smart Router fixtures, golden prompt dataset, and schema contracts."""

import json
from pathlib import Path
import pytest


def test_golden_prompts_dataset() -> None:
    """Verify golden prompt dataset integrity, counts, schema, and tier balance."""
    fixtures_dir = Path(__file__).resolve().parent / "fixtures"
    golden_path = fixtures_dir / "golden_prompts.json"
    assert golden_path.exists(), f"Missing golden prompts file at {golden_path}"

    with open(golden_path, "r", encoding="utf-8") as f:
        prompts = json.load(f)

    assert isinstance(prompts, list)
    assert len(prompts) == 30, f"Expected exactly 30 golden prompts, got {len(prompts)}"

    seen_ids = set()
    trivial_count = 0
    medium_count = 0
    hard_count = 0

    valid_tasks = {
        "coding",
        "math_reasoning",
        "writing_creative",
        "summarization_extraction",
        "translation_language",
        "analysis_research",
        "agentic_tool_use",
        "chat_general",
    }
    valid_tiers = {"cheap", "mid", "premium"}

    for p in prompts:
        pid = p.get("id")
        assert pid, "Prompt ID must be non-empty"
        assert pid not in seen_ids, f"Duplicate prompt ID: {pid}"
        seen_ids.add(pid)

        assert p.get("prompt"), f"Empty prompt text in {pid}"
        assert p.get("task") in valid_tasks, f"Invalid task in {pid}: {p.get('task')}"
        assert p.get("expected_tier") in valid_tiers, f"Invalid tier in {pid}: {p.get('expected_tier')}"

        diff = p.get("difficulty")
        assert isinstance(diff, int) and 0 <= diff <= 4, f"Invalid difficulty in {pid}: {diff}"

        prec = p.get("precision")
        assert isinstance(prec, int) and 0 <= prec <= 3, f"Invalid precision in {pid}: {prec}"

        ben = p.get("larger_model_benefit")
        assert isinstance(ben, int) and 0 <= ben <= 3, f"Invalid larger_model_benefit in {pid}: {ben}"

        if diff == 0:
            trivial_count += 1
            assert p.get("expected_tier") == "cheap"
        elif diff in (1, 2):
            medium_count += 1
            assert p.get("expected_tier") == "mid"
        else:
            hard_count += 1
            assert p.get("expected_tier") == "premium"

    assert trivial_count == 10, f"Expected 10 trivial prompts, got {trivial_count}"
    assert medium_count == 10, f"Expected 10 medium prompts, got {medium_count}"
    assert hard_count == 10, f"Expected 10 hard/expert prompts, got {hard_count}"


def test_clef_synthetic_fixture_schema() -> None:
    """Verify Clef-flash synthetic fixture adheres to the Cloudflare Workers AI schema."""
    fixtures_dir = Path(__file__).resolve().parent / "fixtures"
    fixture_path = fixtures_dir / "clef_response_synthetic.json"
    assert fixture_path.exists(), f"Missing fixture at {fixture_path}"

    with open(fixture_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data.get("success") is True
    assert "result" in data
    res = data["result"]
    assert res.get("model") == "clef-flash"
    assert "answers" in res

    answers = res["answers"]
    assert "task" in answers
    assert answers["task"]["type"] == "choice"
    assert "choice" in answers["task"]
    assert "probabilities" in answers["task"]
    assert "confidence" in answers["task"]

    assert "difficulty" in answers
    assert answers["difficulty"]["type"] == "score"
    assert isinstance(answers["difficulty"]["score"], (int, float))
    assert 0 <= answers["difficulty"]["score"] <= 4

    assert "precision" in answers
    assert answers["precision"]["type"] == "score"
    assert 0 <= answers["precision"]["score"] <= 3

    assert "needs_reasoning" in answers
    assert answers["needs_reasoning"]["type"] == "noul"
    assert isinstance(answers["needs_reasoning"]["noul"], (int, float))
    assert 0.0 <= answers["needs_reasoning"]["noul"] <= 1.0

    assert "usage" in res
    assert "input_tokens" in res["usage"]


def test_aa_synthetic_fixture_schema() -> None:
    """Verify Artificial Analysis synthetic fixture matches the v2 API free shape."""
    fixtures_dir = Path(__file__).resolve().parent / "fixtures"
    fixture_path = fixtures_dir / "aa_response_synthetic.json"
    assert fixture_path.exists(), f"Missing fixture at {fixture_path}"

    with open(fixture_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data.get("tier") == "free"
    assert "intelligence_index_version" in data
    assert "pagination" in data
    assert "data" in data
    models = data["data"]
    assert isinstance(models, list)
    assert len(models) >= 3

    for m in models:
        assert "slug" in m
        assert "name" in m
        assert "evaluations" in m
        evals = m["evaluations"]
        assert "artificial_analysis_intelligence_index" in evals
        assert "pricing" in m
        assert "price_1m_input_tokens" in m["pricing"]
        assert "price_1m_output_tokens" in m["pricing"]
        assert "performance" in m


def test_env_example_contains_phase0_vars() -> None:
    """Ensure .env.example contains Cloudflare and Artificial Analysis key names."""
    env_example = Path(__file__).resolve().parent.parent / ".env.example"
    assert env_example.exists()
    content = env_example.read_text(encoding="utf-8")
    assert "CLOUDFLARE_ACCOUNT_ID=" in content
    assert "CLOUDFLARE_AUTH_TOKEN=" in content
    assert "ARTIFICIAL_ANALYSIS_API_KEY=" in content
