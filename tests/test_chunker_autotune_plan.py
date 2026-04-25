from __future__ import annotations


def test_build_chunker_autotune_plan_merges_high_priority_chunk_quality_patches() -> None:
    from app.services.chunk_quality_recommendation_service import build_chunker_autotune_plan

    out = build_chunker_autotune_plan(
        total_documents=20,
        chunk_quality_metrics={
            "gate_grade_docs": {"pass": 8, "warn": 4, "fail": 8, "unknown": 0},
            "coverage_low_documents": 6,
            "overlap_waste_high_documents": 5,
            "token_stats_missing_documents": 0,
        },
        recall_risk_hints=[
            {"key": "short_chunks_heavy", "severity": "error", "observed": {"short_chunk_pct": 42}},
        ],
        parse_risk_summary={},
        pipeline_defaults={
            "chunk_size": 800,
            "chunk_overlap": 240,
            "chunk_strategy": "semantic_sentence",
        },
    )

    assert out["schema"] == "mimirq.chunker_autotune_plan.v1"
    assert out["action"] == "retune_defaults"
    assert out["recommended_defaults"]["chunk_size"] == 1000
    assert out["recommended_defaults"]["chunk_overlap"] == 120
    assert out["recommended_defaults"]["chunk_strategy_candidates"][0] == "markdown_header"
    assert "increase_chunk_size_or_structure_aware" in out["source_recommendation_keys"]
    assert "reduce_chunk_overlap" in out["source_recommendation_keys"]


def test_build_chunker_autotune_plan_returns_noop_when_quality_is_healthy() -> None:
    from app.services.chunk_quality_recommendation_service import build_chunker_autotune_plan

    out = build_chunker_autotune_plan(
        total_documents=12,
        chunk_quality_metrics={
            "gate_grade_docs": {"pass": 12, "warn": 0, "fail": 0, "unknown": 0},
            "coverage_low_documents": 0,
            "overlap_waste_high_documents": 0,
            "token_stats_missing_documents": 0,
        },
        recall_risk_hints=[],
        parse_risk_summary={},
        pipeline_defaults={"chunk_size": 1000, "chunk_overlap": 200, "chunk_strategy": "semantic_sentence"},
    )

    assert out["schema"] == "mimirq.chunker_autotune_plan.v1"
    assert out["action"] == "no_change"
    assert out["recommended_defaults"] == {
        "chunk_size": 1000,
        "chunk_overlap": 200,
        "chunk_strategy": "semantic_sentence",
    }
