import pytest

from app.rag.retrieval.orchestration.query_variants import (
    QueryVariantStageInput,
    build_query_variant_stage,
)


def test_query_variant_stage_preserves_order_dedup_and_budget_trimming(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.rag.retrieval.orchestration import query_variants

    monkeypatch.setattr(query_variants, "num_tokens_from_string", lambda text: len(text.split()))
    output = build_query_variant_stage(
        QueryVariantStageInput(
            query_for_retrieval="q",
            alias_queries=["alias q"],
            dict_expansions=[],
            kg_query_expansion_queries=[],
            clause_fastlane_queries=["clause q"],
            lightweight_subqueries=["lite q"],
            multi_queries=[],
            step_back_used=False,
            step_back_query="",
            sub_questions=["sub q"],
            hyde_used=False,
            hyde_text="",
            query_expansion_max_queries_raw=2,
            query_expansion_max_candidates_raw=None,
            query_expansion_token_budget_raw=None,
            query_expansion_latency_budget_ms_raw=None,
            query_expansion_elapsed_ms=0.0,
        )
    )

    assert output.retrieval_queries == [
        ("main", "q"),
        ("alias", "alias q"),
        ("clause", "clause q"),
    ]
    assert output.query_expansion_budget_max_queries == 2
    assert output.query_expansion_budget_max_candidates == 0
    assert output.query_expansion_budget_token_budget == 0
    assert output.query_expansion_budget_latency_ms == 0.0
    assert output.query_expansion_budget_meta == {
        "enabled": True,
        "max_queries": 2,
        "max_candidates": 0,
        "token_budget": 0,
        "latency_budget_ms": 0.0,
        "generation_elapsed_ms": 0.0,
        "candidate_count": 4,
        "selected_count": 2,
        "selected_tokens": 4,
        "dropped_count": 2,
        "degraded": True,
        "reasons": ["query_budget_exceeded"],
    }


def test_query_variant_stage_deduplicates_normalized_queries_before_budgeting() -> None:
    output = build_query_variant_stage(
        QueryVariantStageInput(
            query_for_retrieval="Main Query",
            alias_queries=["  alias q  ", "alias q"],
            dict_expansions=[{"expanded_text": "alias q"}],
            kg_query_expansion_queries=[],
            clause_fastlane_queries=["ALIAS Q", "clause q"],
            lightweight_subqueries=[],
            multi_queries=[],
            step_back_used=True,
            step_back_query="Main Query",
            sub_questions=[],
            hyde_used=False,
            hyde_text="",
            query_expansion_max_queries_raw=None,
            query_expansion_max_candidates_raw=None,
            query_expansion_token_budget_raw=None,
            query_expansion_latency_budget_ms_raw=None,
            query_expansion_elapsed_ms=0.0,
        )
    )

    assert output.retrieval_queries == [
        ("main", "Main Query"),
        ("alias", "alias q"),
        ("clause", "clause q"),
    ]
    assert output.query_expansion_budget_meta == {
        "enabled": False,
        "max_queries": 0,
        "max_candidates": 0,
        "token_budget": 0,
        "latency_budget_ms": 0.0,
        "generation_elapsed_ms": 0.0,
        "candidate_count": 2,
        "selected_count": 0,
        "selected_tokens": 0,
        "dropped_count": 0,
        "degraded": False,
        "reasons": [],
    }
