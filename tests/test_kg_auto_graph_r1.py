from __future__ import annotations


def test_build_auto_graph_r1_plan_enables_relation_alias_and_skill_lanes() -> None:
    from app.rag.kg.extraction.auto_graph_r1 import build_auto_graph_r1_plan

    out = build_auto_graph_r1_plan(
        chunk_count=24,
        entity_type_counts={"person": 10, "organization": 8, "unknown": 3},
        predicate_counts={"works at": 4, "located-in": 2, "unknown": 3},
        alias_candidate_count=5,
        skill_candidate_count=2,
        extraction_backend="hybrid",
    )

    assert out["schema"] == "mimirq.kg.auto_graph_r1_plan.v1"
    assert out["backend"] == "hybrid"
    assert out["top_predicates"] == [
        {"predicate": "works_for", "count": 4},
        {"predicate": "unknown", "count": 3},
        {"predicate": "located_in", "count": 2},
    ]
    phase_ids = [row["phase_id"] for row in out["phases"]]
    assert phase_ids == [
        "bootstrap_extraction",
        "ontology_bootstrap",
        "predicate_induction",
        "alias_consolidation",
        "skill_harvest",
    ]
    assert "high_unknown_predicate_ratio" in out["risk_flags"]
    assert out["promotion_thresholds"]["manual_review_unknown_ratio_gt"] == 0.25


def test_build_auto_graph_r1_plan_falls_back_to_llm_and_skips_optional_lanes_without_signals() -> None:
    from app.rag.kg.extraction.auto_graph_r1 import build_auto_graph_r1_plan

    out = build_auto_graph_r1_plan(
        chunk_count=6,
        entity_type_counts={"unknown": 6},
        predicate_counts={"works with": 1},
        alias_candidate_count=0,
        skill_candidate_count=0,
        extraction_backend="unsupported",
    )

    assert out["backend"] == "llm"
    assert out["risk_flags"] == ["unknown_entity_type_heavy"]
    assert out["top_predicates"] == [{"predicate": "works_with", "count": 1}]
    phase_ids = [row["phase_id"] for row in out["phases"]]
    assert phase_ids == [
        "bootstrap_extraction",
        "ontology_bootstrap",
        "predicate_induction",
    ]
