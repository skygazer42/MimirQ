from __future__ import annotations

import importlib
from uuid import uuid4

import pytest


def _import_bundle_module():
    try:
        return importlib.import_module("app.services.regression_case_bundle")
    except ModuleNotFoundError:
        pytest.fail("Missing module: app.services.regression_case_bundle", pytrace=False)

def _import_schema_import_request():
    try:
        from app.api.schemas.regression import RagasRegressionCaseImportRequest  # noqa: WPS433
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"Missing schema: RagasRegressionCaseImportRequest ({exc})", pytrace=False)
    return RagasRegressionCaseImportRequest


def test_import_endpoint_is_registered():
    # Keep this test lightweight: do not import FastAPI modules that pull heavy ML deps.
    from pathlib import Path

    text = Path("app/api/v1/evaluations.py").read_text(encoding="utf-8")
    assert '@router.post("/ragas/regression/cases/import"' in text


def test_import_schema_requires_dataset_id_and_items_and_evidence():
    RagasRegressionCaseImportRequest = _import_schema_import_request()

    with pytest.raises(Exception):
        RagasRegressionCaseImportRequest(items=[])

    with pytest.raises(Exception):
        RagasRegressionCaseImportRequest(dataset_id=uuid4(), items=[])

    with pytest.raises(Exception):
        RagasRegressionCaseImportRequest(
            dataset_id=uuid4(),
            items=[{"question": "q", "reference_sources": []}],
        )


def test_plan_case_import_counts_created_updated_skipped_and_errors():
    mod = _import_bundle_module()
    assert hasattr(mod, "plan_case_import"), "plan_case_import helper must exist"

    dataset_id = uuid4()
    existing_questions = {"exists"}

    items = [
        {"question": "  new  "},
        {"question": "exists"},
        {"question": "exists"},  # duplicate in same import batch
        {"question": "   "},  # invalid
    ]

    out = mod.plan_case_import(
        dataset_id=dataset_id,
        existing_questions=existing_questions,
        items=items,
        overwrite=False,
        max_items=100,
    )

    assert out["created"] == 1
    assert out["updated"] == 0
    assert out["skipped"] >= 1
    assert isinstance(out["errors"], list)
    assert out["errors"], "expected validation errors for duplicates/empty questions"

    out_overwrite = mod.plan_case_import(
        dataset_id=dataset_id,
        existing_questions=existing_questions,
        items=items,
        overwrite=True,
        max_items=100,
    )
    assert out_overwrite["created"] == 1
    assert out_overwrite["updated"] == 1
