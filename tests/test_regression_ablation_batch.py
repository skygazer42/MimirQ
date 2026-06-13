from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest


def test_expand_ablation_grid_is_stable_and_bounded() -> None:
    from app.services.regression_run_ablation_batch import expand_ablation_grid

    variants = expand_ablation_grid(
        {
            "top_k": [10, 20],
            "retrieval_mode": ["vector", "hybrid"],
        },
        max_combinations=10,
    )

    assert variants == [
        {"top_k": 10, "retrieval_mode": "vector"},
        {"top_k": 10, "retrieval_mode": "hybrid"},
        {"top_k": 20, "retrieval_mode": "vector"},
        {"top_k": 20, "retrieval_mode": "hybrid"},
    ]

    with pytest.raises(ValueError, match="exceeds"):
        expand_ablation_grid({"top_k": [1, 2, 3], "alpha": [0.2, 0.4]}, max_combinations=5)


def test_ablation_batch_schema_and_endpoint_are_exposed() -> None:
    from app.api.schemas.regression import RagasRegressionAblationBatchRequest

    request = RagasRegressionAblationBatchRequest(
        dataset_id=uuid4(),
        grid={"top_k": [10, 20], "retrieval_mode": ["vector"]},
        max_combinations=10,
    )

    assert request.grid["top_k"] == [10, 20]
    assert request.max_combinations == 10

    text = Path("app/api/v1/evaluations.py").read_text(encoding="utf-8")
    assert '"/ragas/regression/ablation/batch"' in text
    assert "RagasRegressionAblationBatchResponse" in text
    assert "_assert_regression_cases_available" in text
    assert "No regression cases found for selected dataset" in text
