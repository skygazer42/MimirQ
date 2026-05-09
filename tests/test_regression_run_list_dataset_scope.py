from pathlib import Path


def test_regression_run_list_supports_dataset_scope():
    text = Path("app/api/v1/evaluations.py").read_text()

    assert 'dataset_id: Annotated[UUID | None, Query(description="Optional dataset scope")] = None' in text
    assert "DatasetService.get_dataset(db, tenant_id, dataset_id)" in text
    assert "RagasRegressionRun.dataset_id == dataset_id" in text
