from __future__ import annotations

from pathlib import Path


def test_retrieval_audit_openapi_contract_includes_kg_recommendation() -> None:
    from app.main import app  # noqa: WPS433

    spec = app.openapi()
    schema = spec["components"]["schemas"]["DatasetRetrievalAuditOut"]

    assert "kg_recommendation" in schema["properties"]

    generated_types = Path("web/types/openapi.ts").read_text(encoding="utf-8")
    assert "DatasetRetrievalAuditOut:" in generated_types
    assert "kg_recommendation?: string | null;" in generated_types
