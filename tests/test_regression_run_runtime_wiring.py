from __future__ import annotations

from pathlib import Path


def test_create_ragas_regression_run_wires_extended_runtime_rag_params_in_both_payloads() -> None:
    text = Path("app/api/v1/evaluations.py").read_text(encoding="utf-8")

    expected_mappings = [
        '"retrieval_profile": request.retrieval_profile',
        '"enable_query_alias_expansion": request.enable_query_alias_expansion',
        '"query_alias_max_queries": request.query_alias_max_queries',
        '"enable_multi_query": request.enable_multi_query',
        '"multi_query_count": request.multi_query_count',
        '"multi_query_temperature": request.multi_query_temperature',
        '"multi_query_max_chars": request.multi_query_max_chars',
        '"enable_query_rewrite": request.enable_query_rewrite',
        '"query_rewrite_strategy": request.query_rewrite_strategy',
        '"query_rewrite_temperature": request.query_rewrite_temperature',
        '"query_rewrite_max_chars": request.query_rewrite_max_chars',
        '"sparse_retrieval_enabled": request.sparse_retrieval_enabled',
        '"sparse_retrieval_provider": request.sparse_retrieval_provider',
        '"fusion_strategy": request.fusion_strategy',
        '"fusion_budgets": request.fusion_budgets',
        '"fusion_min_scores": request.fusion_min_scores',
        '"fusion_weights": request.fusion_weights',
    ]

    for mapping in expected_mappings:
        assert text.count(mapping) >= 2, f"missing dual wiring for {mapping}"
