from __future__ import annotations


def test_build_contextual_855_evalset_plan_emits_expected_targets_and_tracks() -> None:
    from app.rag.evaluation.datasets.contextual_855_plan import build_contextual_855_evalset_plan

    out = build_contextual_855_evalset_plan()

    assert out["schema"] == "mimirq.contextual_855_evalset_plan.v1"
    assert out["target_documents"] == 50
    assert out["target_questions"] == 855
    assert out["avg_relevant_spans_per_question"] == 11.3
    assert out["modes"] == ["basic", "contextual", "expanded"]
    assert out["tracks"] == [
        "semantic_missing",
        "semantic_ambiguity",
        "structure_loss",
    ]


def test_build_contextual_855_evalset_plan_supports_overrides() -> None:
    from app.rag.evaluation.datasets.contextual_855_plan import build_contextual_855_evalset_plan

    out = build_contextual_855_evalset_plan(
        target_documents=60,
        target_questions=900,
        avg_relevant_spans_per_question=12.0,
    )

    assert out["target_documents"] == 60
    assert out["target_questions"] == 900
    assert out["avg_relevant_spans_per_question"] == 12.0
