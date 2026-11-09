from types import SimpleNamespace

import pytest

from app.services import document_lifecycle_service, document_processing_operations, document_qa_service
from app.services.document_dedup_service import document_matches_dedup_identity


@pytest.mark.parametrize("module", [document_lifecycle_service, document_processing_operations])
@pytest.mark.parametrize("stage", [0, False])
def test_invalid_document_stage_is_not_considered_an_idle_document(module, stage):
    document = SimpleNamespace(
        status="pending", doc_metadata={}, current_stage=stage, processing_progress=0
    )
    with pytest.raises(AttributeError):
        module._is_idle_pending_document(document)


def test_missing_declared_dedup_attribute_is_not_repaired_from_metadata():
    document = SimpleNamespace(doc_metadata={"content_sha256": "abc", "pipeline_hash": "pipeline"})
    with pytest.raises(AttributeError, match="dedup_key"):
        document_matches_dedup_identity(document, content_sha256="abc", pipeline_hash="pipeline")


@pytest.mark.parametrize("pipeline_hash", [0, False])
def test_invalid_pipeline_identity_does_not_become_unversioned_qa(pipeline_hash):
    with pytest.raises(AttributeError):
        document_qa_service._active_pipeline_hash({"pipeline_hash": pipeline_hash})


def test_a_real_missing_pipeline_identity_remains_absent():
    assert document_qa_service._active_pipeline_hash({}) is None
