from __future__ import annotations


def test_kg_search_diagnostics_request_exposes_persist_run_flag() -> None:
    from app.api.schemas.kg_diagnostics import KGSearchDiagnosticsRequest

    assert "persist_run" in getattr(KGSearchDiagnosticsRequest, "model_fields", {})


def test_kg_search_diagnostics_response_exposes_run_id() -> None:
    from app.api.schemas.kg_diagnostics import KGSearchDiagnosticsResponse

    assert "run_id" in getattr(KGSearchDiagnosticsResponse, "model_fields", {})

