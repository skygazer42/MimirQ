from __future__ import annotations

from uuid import uuid4


def test_regression_run_defaults_are_recall_friendly() -> None:
    """
    Regression gates are primarily used to detect retrieval regressions.

    Defaults should therefore bias towards recall (higher top_k, no similarity threshold),
    so CI callers don't need to pass explicit rag_params to get stable gates.
    """
    from app.api.schemas.regression import RagasRegressionRunCreateRequest

    req = RagasRegressionRunCreateRequest(dataset_id=uuid4())
    assert req.top_k == 20
    assert req.score_threshold == 0.0

