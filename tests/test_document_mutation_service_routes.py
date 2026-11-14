from uuid import uuid4

import pytest

from app.api.schemas.document import DocumentPipelinePatchRequest, DocumentUserMetadataPatchRequest
from app.api.schemas.qa import DocumentQAGenerateRequest
from app.api.v1 import document_mutations
from app.services import document_metadata_operations, document_qa_service


def test_document_mutation_routes_delegate_to_business_services(monkeypatch: pytest.MonkeyPatch) -> None:
    document_id = uuid4()
    tenant_id = uuid4()
    account_id = "account-1"
    db = object()
    pipeline_payload = DocumentPipelinePatchRequest()
    metadata_payload = DocumentUserMetadataPatchRequest(patch={"label": "new"})
    qa_payload = DocumentQAGenerateRequest(num_pairs=3)
    results = {"pipeline": object(), "metadata": object(), "qa": object()}
    calls: dict[str, dict[str, object]] = {}

    def record(name: str):
        def operation(**kwargs):
            calls[name] = kwargs
            return results[name]

        return operation

    monkeypatch.setattr(
        document_mutations,
        "_documents_module",
        lambda: pytest.fail("mutation route reached the documents facade"),
        raising=False,
    )
    monkeypatch.setattr(document_metadata_operations, "patch_pipeline", record("pipeline"))
    monkeypatch.setattr(document_metadata_operations, "patch_user_metadata", record("metadata"))
    monkeypatch.setattr(document_qa_service, "generate_document_qa", record("qa"), raising=False)

    assert (
        document_mutations.patch_document_pipeline(
            document_id=document_id,
            payload=pipeline_payload,
            tenant_id=tenant_id,
            account_id=account_id,
            db=db,
        )
        is results["pipeline"]
    )
    assert (
        document_mutations.patch_document_user_metadata(
            document_id=document_id,
            payload=metadata_payload,
            tenant_id=tenant_id,
            account_id=account_id,
            db=db,
        )
        is results["metadata"]
    )
    assert (
        document_mutations.generate_document_qa(
            document_id=document_id,
            payload=qa_payload,
            tenant_id=tenant_id,
            account_id=account_id,
            db=db,
        )
        is results["qa"]
    )

    assert calls == {
        "pipeline": {
            "document_id": document_id,
            "payload": pipeline_payload,
            "db": db,
            "tenant_id": tenant_id,
            "account_id": account_id,
        },
        "metadata": {
            "document_id": document_id,
            "payload": metadata_payload,
            "db": db,
            "tenant_id": tenant_id,
            "account_id": account_id,
        },
        "qa": {
            "document_id": document_id,
            "payload": qa_payload,
            "db": db,
            "tenant_id": tenant_id,
            "account_id": account_id,
        },
    }
