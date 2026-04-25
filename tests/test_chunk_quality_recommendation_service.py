from __future__ import annotations


def test_build_chunk_quality_recommendation_emits_actionable_actions() -> None:
    from app.services.chunk_quality_recommendation_service import build_chunk_quality_recommendation

    out = build_chunk_quality_recommendation(
        total_documents=20,
        chunk_quality_metrics={
            "gate_grade_docs": {"pass": 8, "warn": 4, "fail": 8, "unknown": 0},
            "coverage_low_documents": 6,
            "overlap_waste_high_documents": 5,
            "token_stats_missing_documents": 1,
        },
        recall_risk_hints=[
            {
                "key": "short_chunks_heavy",
                "severity": "error",
                "observed": {"short_chunk_pct": 42},
            },
            {
                "key": "low_lexical_diversity",
                "severity": "warning",
                "observed": {"duplicate_docs_pct": 18},
            },
        ],
        parse_risk_summary={
            "recommendation": "medium_parse_risk_prioritize_low_quality_docs",
            "high_risk_documents": 5,
            "considered_documents": 20,
        },
        pipeline_defaults={
            "chunk_size": 800,
            "chunk_overlap": 240,
            "chunk_strategy": "semantic_sentence",
        },
    )

    assert out["schema"] == "mimirq.chunk_quality_recommendation.v1"
    assert out["severity"] == "error"
    assert out["summary"]["fail_documents"] == 8
    assert out["summary"]["fail_ratio"] == 0.4

    by_key = {item["key"]: item for item in out["recommendations"]}
    assert "increase_chunk_size_or_structure_aware" in by_key
    assert "reduce_chunk_overlap" in by_key
    assert "enable_duplicate_governance" in by_key
    assert "reparse_low_quality_documents" in by_key
    assert "repair_coverage_before_reindex" in by_key

    size_rec = by_key["increase_chunk_size_or_structure_aware"]
    assert size_rec["priority"] == "high"
    assert size_rec["patch"]["chunk_size"] == 1000
    assert size_rec["patch"]["chunk_overlap"] == 300
    assert "markdown_header" in size_rec["patch"]["chunk_strategy_candidates"]

    overlap_rec = by_key["reduce_chunk_overlap"]
    assert overlap_rec["patch"]["chunk_overlap"] == 120

    dedup_rec = by_key["enable_duplicate_governance"]
    assert dedup_rec["patch"]["governance_drop_duplicate_paragraphs"] is True


def test_build_chunk_quality_recommendation_returns_healthy_when_no_signals() -> None:
    from app.services.chunk_quality_recommendation_service import build_chunk_quality_recommendation

    out = build_chunk_quality_recommendation(
        total_documents=12,
        chunk_quality_metrics={
            "gate_grade_docs": {"pass": 12, "warn": 0, "fail": 0, "unknown": 0},
            "coverage_low_documents": 0,
            "overlap_waste_high_documents": 0,
            "token_stats_missing_documents": 0,
        },
        recall_risk_hints=[],
        parse_risk_summary={"recommendation": "parse_quality_healthy", "high_risk_documents": 0},
        pipeline_defaults={"chunk_size": 1000, "chunk_overlap": 200},
    )

    assert out["schema"] == "mimirq.chunk_quality_recommendation.v1"
    assert out["severity"] == "healthy"
    assert out["recommendations"] == []
