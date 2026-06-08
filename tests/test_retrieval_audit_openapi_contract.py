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


def test_retrieval_audit_put_request_body_uses_retrieval_audit_schema() -> None:
    from app.main import app  # noqa: WPS433

    spec = app.openapi()
    operation = spec["paths"]["/api/v1/datasets/{dataset_id}/retrieval-audit"]["put"]
    request_schema = operation["requestBody"]["content"]["application/json"]["schema"]

    assert request_schema == {"$ref": "#/components/schemas/DatasetRetrievalAuditOut"}

    generated_types = Path("web/types/openapi.ts").read_text(encoding="utf-8")
    operation_start = generated_types.index("put_dataset_retrieval_audit_api_v1_datasets__dataset_id__retrieval_audit_put:")
    operation_end = generated_types.index("clone_dataset_api_v1_datasets__dataset_id__clone_post:", operation_start)
    operation_type = generated_types[operation_start:operation_end]
    assert '"application/json": components["schemas"]["DatasetRetrievalAuditOut"];' in operation_type
