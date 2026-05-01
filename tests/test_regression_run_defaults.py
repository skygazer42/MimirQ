from __future__ import annotations

from uuid import uuid4

import pytest


def test_regression_run_defaults_are_recall_friendly() -> None:
    """
    Regression gates are primarily used to detect retrieval regressions.

    Defaults should therefore bias towards recall (higher top_k, no similarity threshold),
    so CI callers don't need to pass explicit rag_params to get stable gates.
    """
    from app.api.schemas.regression import RagasRegressionRunCreateRequest

    req = RagasRegressionRunCreateRequest(dataset_id=uuid4())
    assert req.top_k == 20
    assert req.score_threshold == pytest.approx(0.0)


def test_regression_run_defaults_follow_runtime_rerank_settings(monkeypatch) -> None:  # noqa: ANN001
    from app.api.schemas.regression import RagasRegressionRunCreateRequest
    from app.core.config import settings

    monkeypatch.setattr(settings, "ENABLE_RERANKER", True, raising=False)
    monkeypatch.setattr(settings, "RERANKER_PROVIDER", "llm", raising=False)
    monkeypatch.setattr(settings, "RERANKER_TOP_N", 12, raising=False)

    req = RagasRegressionRunCreateRequest(dataset_id=uuid4())

    assert req.enable_reranker is True
    assert req.reranker_provider == "llm"
    assert req.reranker_top_n == 12


def test_regression_run_request_accepts_extended_runtime_knobs() -> None:
    from app.api.schemas.regression import RagasRegressionRunCreateRequest

    req = RagasRegressionRunCreateRequest(
        dataset_id=uuid4(),
        retrieval_profile="recall50",
        enable_query_alias_expansion=True,
        enable_multi_query=True,
        multi_query_count=3,
        enable_hyde=False,
        enable_query_rewrite=True,
        query_rewrite_strategy="kb_followup.v2",
        query_rewrite_temperature=0.3,
        query_rewrite_max_chars=180,
        sparse_retrieval_enabled=True,
        sparse_retrieval_provider="splade",
        fusion_strategy="weighted",
        fusion_budgets={"vector": 20, "bm25": 10},
        fusion_min_scores={"vector": 0.2},
        fusion_weights={"vector": 0.7, "bm25": 0.3},
    )

    assert req.retrieval_profile == "recall50"
    assert req.enable_query_alias_expansion is True
    assert req.enable_multi_query is True
    assert req.multi_query_count == 3
    assert req.enable_hyde is False
    assert req.enable_query_rewrite is True
    assert req.query_rewrite_strategy == "kb_followup.v2"
    assert req.query_rewrite_temperature == pytest.approx(0.3)
    assert req.query_rewrite_max_chars == 180
    assert req.sparse_retrieval_enabled is True
    assert req.sparse_retrieval_provider == "splade"
    assert req.fusion_strategy == "weighted"
    assert req.fusion_budgets == {"vector": 20, "bm25": 10}
    assert req.fusion_min_scores == {"vector": 0.2}
    assert req.fusion_weights == {"vector": 0.7, "bm25": 0.3}
