from __future__ import annotations

from uuid import uuid4

import pytest


def test_regression_run_create_requires_dataset_id():
    from app.api.schemas.regression import RagasRegressionRunCreateRequest

    with pytest.raises(Exception):
        RagasRegressionRunCreateRequest(case_ids=[uuid4()], metrics=["faithfulness"], skip_empty_contexts=True, max_cases=1)


def test_regression_run_schema_exposes_dataset_id():
    from app.api.schemas.regression import RagasRegressionRunSchema

    assert "dataset_id" in getattr(RagasRegressionRunSchema, "model_fields", {})


def test_regression_run_model_has_dataset_id_column():
    from app.models.evaluation import RagasRegressionRun

    assert hasattr(RagasRegressionRun, "dataset_id")


def test_runtime_migrations_include_regression_run_dataset_id():
    from pathlib import Path

    text = Path("app/core/migrations.py").read_text(encoding="utf-8")
    assert "ALTER TABLE ragas_regression_runs ADD COLUMN IF NOT EXISTS dataset_id UUID" in text


def test_validate_case_ids_belong_to_dataset_rejects_mixed_or_missing():
    from app.services.regression_run_scope import validate_case_ids_belong_to_dataset

    ds = uuid4()
    other = uuid4()
    a = uuid4()
    b = uuid4()

    # Missing case id
    with pytest.raises(ValueError):
        validate_case_ids_belong_to_dataset(dataset_id=ds, case_ids=[a, b], rows=[(a, ds)])

    # Mixed dataset
    with pytest.raises(ValueError):
        validate_case_ids_belong_to_dataset(dataset_id=ds, case_ids=[a, b], rows=[(a, ds), (b, other)])


def test_validate_case_ids_belong_to_dataset_allows_all_match():
    from app.services.regression_run_scope import validate_case_ids_belong_to_dataset

    ds = uuid4()
    a = uuid4()
    b = uuid4()

    validate_case_ids_belong_to_dataset(dataset_id=ds, case_ids=[a, b], rows=[(a, ds), (b, ds)])

