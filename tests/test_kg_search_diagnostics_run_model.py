from __future__ import annotations


def test_kg_search_diagnostics_run_model_exists_and_is_dataset_scoped() -> None:
    from app.models import evaluation as evaluation_mod

    assert hasattr(evaluation_mod, "KGSearchDiagnosticsRun")

    from app.models.evaluation import KGSearchDiagnosticsRun  # noqa: PLC0415

    assert hasattr(KGSearchDiagnosticsRun, "dataset_id")

