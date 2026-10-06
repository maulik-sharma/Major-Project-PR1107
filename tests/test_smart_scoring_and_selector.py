"""Unit tests verifying SmartRouter scoring math and selector worked examples."""

import pytest
from modelmesh.core.config.routing_config import NeedConfig
from modelmesh.core.routing.smart.scoring import (
    compute_bar,
    compute_need,
    normalize_scores_to_quality,
)
from modelmesh.core.routing.smart.selector import select_smart_candidate
from modelmesh.core.scores.snapshots import EffectiveScores
from modelmesh.core.types import (
    Candidate,
    EndpointConfig,
    ModelConfig,
    ProviderConfig,
)


def _build_candidate(model_id: str, price_out: float) -> Candidate:
    m = ModelConfig(id=model_id, display_name=model_id)
    ep = EndpointConfig(
        id=f"{model_id}@prov",
        provider="prov",
        api_model=f"api-{model_id}",
        price_in_per_mtok=0.0,
        price_out_per_mtok=price_out,
    )
    p = ProviderConfig(id="prov", protocol="mock")
    return Candidate.resolve(model=m, endpoint=ep, provider=p)


def test_worked_examples_table_4_8() -> None:
    """Validate all 4 worked-example rows from Part 4.8 of the SmartRouter plan."""
    cand_a = _build_candidate("model_a", price_out=0.0)
    cand_b = _build_candidate("model_b", price_out=0.08)
    cand_c = _build_candidate("model_c", price_out=6.0)
    cand_d = _build_candidate("model_d", price_out=15.0)
    cand_e = _build_candidate("model_e", price_out=25.0)

    candidates = [cand_a, cand_b, cand_c, cand_d, cand_e]
    raw_scores = {"model_a": 18.0, "model_b": 28.0, "model_c": 45.0, "model_d": 62.0, "model_e": 72.0}

    effective_scores = {
        mid: EffectiveScores(intelligence=score, is_unscored=False, is_manual=True, source="manual")
        for mid, score in raw_scores.items()
    }

    q_map = normalize_scores_to_quality(raw_scores)
    assert q_map["model_a"] == 0.0
    assert pytest.approx(q_map["model_b"], abs=0.01) == 0.19
    assert pytest.approx(q_map["model_c"], abs=0.01) == 0.50
    assert pytest.approx(q_map["model_d"], abs=0.01) == 0.81
    assert q_map["model_e"] == 1.0

    need_cfg = NeedConfig()

    # --- Row 1: "hi, thanks!" ---
    answers_row1 = {
        "difficulty": {"score": 0.05, "confidence": 0.95},
        "precision": {"score": 0.2},
        "larger_model_benefit": {"score": 0.05},
    }
    need1 = compute_need(answers_row1, need_cfg, bias_override=0.0)
    assert pytest.approx(need1, abs=0.01) == 0.03
    bar1 = compute_bar(need1, slack=0.10)
    assert bar1 == 0.0

    chosen1, fallbacks1, _ = select_smart_candidate(
        candidates=candidates,
        effective_scores=effective_scores,
        metric="intelligence",
        need=need1,
        bar=bar1,
    )
    assert chosen1.model_id == "model_a"

    # --- Row 2: "Explain mutex vs semaphore" ---
    answers_row2 = {
        "difficulty": {"score": 1.3, "confidence": 0.80},
        "precision": {"score": 2.0},
        "larger_model_benefit": {"score": 0.8},
    }
    need2 = compute_need(answers_row2, need_cfg, bias_override=0.0)
    assert pytest.approx(need2, abs=0.02) == 0.41
    bar2 = compute_bar(need2, slack=0.10)
    assert pytest.approx(bar2, abs=0.02) == 0.31

    chosen2, fallbacks2, _ = select_smart_candidate(
        candidates=candidates,
        effective_scores=effective_scores,
        metric="intelligence",
        need=need2,
        bar=bar2,
    )
    assert chosen2.model_id == "model_c"

    # --- Row 3: "Debug this 400-line async deadlock..." ---
    answers_row3 = {
        "difficulty": {"score": 3.2, "confidence": 0.70},
        "precision": {"score": 2.8},
        "larger_model_benefit": {"score": 2.4},
    }
    need3 = compute_need(answers_row3, need_cfg, bias_override=0.0)
    assert pytest.approx(need3, abs=0.02) == 0.87
    bar3 = compute_bar(need3, slack=0.10)
    assert pytest.approx(bar3, abs=0.02) == 0.77

    chosen3, fallbacks3, _ = select_smart_candidate(
        candidates=candidates,
        effective_scores=effective_scores,
        metric="intelligence",
        need=need3,
        bar=bar3,
    )
    assert chosen3.model_id == "model_d"

    # --- Row 4: Same prompt with quality bias +0.10 ---
    need4 = compute_need(answers_row3, need_cfg, bias_override=0.10)
    assert pytest.approx(need4, abs=0.02) == 0.97
    bar4 = compute_bar(need4, slack=0.10)
    assert pytest.approx(bar4, abs=0.02) == 0.87

    chosen4, fallbacks4, _ = select_smart_candidate(
        candidates=candidates,
        effective_scores=effective_scores,
        metric="intelligence",
        need=need4,
        bar=bar4,
    )
    assert chosen4.model_id == "model_e"


def test_edge_cases_pool_and_unscored() -> None:
    """Verify edge cases from Part 4.7 (unscored policy, pool exclusion)."""
    cand_mock = _build_candidate("mock-test", price_out=0.01)
    cand_real = _build_candidate("real-model", price_out=1.0)

    effective_scores = {
        "real-model": EffectiveScores(intelligence=50.0, is_unscored=False, is_manual=True, source="manual")
    }

    # Pool exclude "mock-*"
    chosen, _, _ = select_smart_candidate(
        candidates=[cand_mock, cand_real],
        effective_scores=effective_scores,
        metric="intelligence",
        need=0.5,
        bar=0.4,
        pool_exclude=["mock-*"],
    )
    assert chosen.model_id == "real-model"
