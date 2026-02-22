from __future__ import annotations


def test_evaluations_module_exposes_kg_diagnostics_run_routes() -> None:
    import app.api.v1.evaluations as eval_routes

    assert hasattr(eval_routes, "list_kg_search_diagnostics_runs")
    assert hasattr(eval_routes, "get_kg_search_diagnostics_run")

