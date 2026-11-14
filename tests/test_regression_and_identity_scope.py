from uuid import uuid4

import pytest
from fastapi import HTTPException
from langchain_core.documents import Document

from app.models.document import Document as StoredDocument
from app.models.evaluation import RagasRegressionCase
from app.parsing.processors.support.chunk_postprocess import _chunk_record_identity_key
from app.parsing.processors.support.stages import _dedup_record_identity_key
from app.rag.evaluation import ragas
from app.services import document_access
from app.services.document_index_channel_service import _pipeline_hash_from_document


def test_inaccessible_explicit_regression_documents_cannot_become_open_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(document_access.dataset_service, "ensure_member", lambda *_args: None)
    monkeypatch.setattr(document_access, "get_allowed_document_id_sets", lambda *_args, **_kwargs: (set(), set()))
    case = RagasRegressionCase(document_ids=[uuid4()], dataset_id=uuid4())

    with pytest.raises(HTTPException) as error:
        ragas._resolve_case_scope(db=object(), tenant_id=uuid4(), account_id="reader", case=case)

    assert error.value.status_code == 403


def test_invalid_explicit_regression_document_scope_is_rejected() -> None:
    case = RagasRegressionCase(document_ids=["invalid-uuid"], dataset_id=None)

    with pytest.raises(HTTPException) as error:
        ragas._resolve_case_scope(db=object(), tenant_id=uuid4(), account_id="reader", case=case)

    assert error.value.status_code == 400


def test_partially_allowed_regression_scope_keeps_only_authorized_documents(monkeypatch: pytest.MonkeyPatch) -> None:
    allowed, denied = uuid4(), uuid4()
    monkeypatch.setattr(ragas, "filter_allowed_document_ids", lambda *_args: [allowed])

    documents, dataset = ragas._resolve_case_scope(
        db=object(),
        tenant_id=uuid4(),
        account_id="reader",
        case=RagasRegressionCase(document_ids=[allowed, denied], dataset_id=uuid4()),
    )

    assert documents == [allowed]
    assert dataset is None


def test_no_explicit_regression_scope_keeps_the_existing_open_scope_contract() -> None:
    assert ragas._resolve_case_scope(
        db=object(),
        tenant_id=uuid4(),
        account_id="reader",
        case=RagasRegressionCase(document_ids=[], dataset_id=None),
    ) == (None, None)


def test_regression_graph_state_preserves_the_actual_empty_document_scope() -> None:
    state = ragas._build_regression_graph_state(
        db=object(),
        tenant_id=uuid4(),
        account_id="reader",
        case=RagasRegressionCase(question="policy"),
        scope_doc_ids=[],
        scope_dataset_id=None,
        rag_params={},
        routing_state=ragas.RegressionCaseRoutingState(
            modality="text", multimodal_router_meta={}, tag_meta={}, image_meta={}, injected_docs=[]
        ),
    )

    assert state["document_ids"] == []


@pytest.mark.parametrize("requested", [None, "", "   ", "explicit"])
def test_channel_version_selection_uses_the_existing_pipeline_owner(requested: str | None) -> None:
    document = StoredDocument(doc_metadata={"active_pipeline_hash": "active"})

    assert _pipeline_hash_from_document(document, pipeline_hash=requested) == (
        "explicit" if requested == "explicit" else "active"
    )


@pytest.mark.parametrize("requested", [0, False])
def test_channel_version_selection_exposes_invalid_parameter_types(requested) -> None:
    with pytest.raises(AttributeError):
        _pipeline_hash_from_document(
            StoredDocument(doc_metadata={"active_pipeline_hash": "active"}), pipeline_hash=requested
        )


@pytest.mark.parametrize("key,error", [(None, AttributeError), ("", ValueError), (False, AttributeError)])
def test_present_but_invalid_record_identity_is_not_treated_as_absent(key, error) -> None:
    metadata = {"_record_identity": {"key": key}}

    with pytest.raises(error):
        _chunk_record_identity_key(Document(page_content="text", metadata=metadata))
    with pytest.raises(error):
        _dedup_record_identity_key(metadata)


def test_missing_key_in_an_existing_record_identity_exposes_the_broken_contract() -> None:
    metadata = {"_record_identity": {}}

    with pytest.raises(KeyError):
        _chunk_record_identity_key(Document(page_content="text", metadata=metadata))
    with pytest.raises(KeyError):
        _dedup_record_identity_key(metadata)


def test_genuinely_absent_record_identity_remains_optional() -> None:
    assert _chunk_record_identity_key(Document(page_content="text", metadata={})) is None
    assert _dedup_record_identity_key({}) is None
