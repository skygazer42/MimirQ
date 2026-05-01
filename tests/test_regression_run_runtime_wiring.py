from __future__ import annotations

from pathlib import Path


def test_create_ragas_regression_run_wires_extended_runtime_rag_params_in_both_payloads() -> None:
    text = Path("app/api/v1/evaluations.py").read_text(encoding="utf-8")
    schema_text = Path("app/api/schemas/regression.py").read_text(encoding="utf-8")

    assert "def _regression_rag_params_from_request" in text
    assert "def _jsonable_regression_rag_params" in text
    assert 'out["prompt_template_id"] = str(prompt_template_id)' in text
    assert "RagasRegressionRunCreateRequest.model_fields" in text
    assert "rag_params=_regression_rag_params_from_request" in text or "rag_params=rag_params" in text

    for field_name in [
        "retrieval_profile",
        "enable_query_alias_expansion",
        "query_alias_max_queries",
        "enable_multi_query",
        "multi_query_count",
        "multi_query_temperature",
        "multi_query_max_chars",
        "enable_query_rewrite",
        "query_rewrite_strategy",
        "query_rewrite_temperature",
        "query_rewrite_max_chars",
        "sparse_retrieval_enabled",
        "sparse_retrieval_provider",
        "fusion_strategy",
        "fusion_budgets",
        "fusion_min_scores",
        "fusion_weights",
    ]:
        assert field_name in schema_text, f"schema is missing runtime field {field_name}"
