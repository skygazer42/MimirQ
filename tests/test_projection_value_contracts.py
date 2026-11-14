import json
from dataclasses import asdict
from uuid import uuid4

import pytest

from app.api.v1 import audit, datasets, evidence
from app.models.document import Document
from app.models.evidence import EvidenceItem
from app.models.feedback import MessageFeedback
from app.services import chat_response_cache, rag_runtime_warmup, table_store_service


@pytest.mark.parametrize("field", ["dataset_id", "corpus_cache_token", "structured_preset"])
def test_chat_cache_keeps_empty_scope_values_distinct_from_absence(field: str) -> None:
    parameters = {
        "tenant_id": "tenant-1",
        "account_id": "account-1",
        "dataset_id": "dataset-1",
        "document_ids": ["document-1"],
        "question": "policy",
        "rag_config": {},
        "prompt_config": {},
        "structured_output": False,
        "structured_preset": None,
        "use_graph": False,
        "corpus_cache_token": "corpus-1",
    }

    empty = chat_response_cache.build_chat_cache_key(**{**parameters, field: ""})
    absent = chat_response_cache.build_chat_cache_key(**{**parameters, field: None})

    assert empty != absent


@pytest.mark.parametrize("stored", ["", None])
def test_sensitive_document_export_preserves_stored_optional_text(stored: str | None) -> None:
    document = Document(
        filename="sample.txt",
        file_path="sample.txt",
        owner_id=stored,
        access_mode=stored,
        lifecycle_owner=stored,
        error_message=stored,
    )

    row = json.loads(json.dumps(datasets._document_sensitive_export_fields(document, {})))

    for field in ("owner_id", "access_mode", "lifecycle_owner", "error_message"):
        assert row[field] == stored


def test_document_export_keeps_stored_pipeline_and_source_metadata() -> None:
    metadata = {
        "file_sha256": "ABCD",
        "pipeline_hash": "",
        "active_pipeline_hash": "",
        "source_last_modified_at": "",
        "source_last_modified_source": "",
        "source_fetched_at": "",
        "source_etag": "",
    }
    document = Document(id=uuid4())

    pipeline = datasets._document_pipeline_export_fields(document, metadata)
    source = datasets._document_source_export_fields(metadata, include_sensitive=False)

    assert pipeline == {
        "file_sha256": "ABCD",
        "pipeline_hash": "",
        "active_pipeline_hash": "",
        "doc_pipeline_key": None,
    }
    assert source == {
        "source_url_hash": None,
        "source_path_hash": None,
        "source_last_modified_at": "",
        "source_last_modified_source": "",
        "source_fetched_at": "",
        "source_etag": "",
    }


def test_document_export_keeps_the_source_etag_limit_without_mutating_metadata() -> None:
    metadata = {"source_etag": "a" * 600}

    exported = datasets._document_source_export_fields(metadata, include_sensitive=False)

    assert exported["source_etag"] == "a" * 500
    assert metadata["source_etag"] == "a" * 600


@pytest.mark.parametrize("status", ["", "draft"])
def test_training_export_preserves_persisted_status(status: str) -> None:
    dataset_id = uuid4()
    item = EvidenceItem(
        id=uuid4(),
        tenant_id=uuid4(),
        dataset_id=dataset_id,
        suite_id=uuid4(),
        status=status,
        query="policy",
        tags=[],
        source_metadata={},
        reference_sources=[],
        retrieval_snapshot={},
        rag_config_snapshot={},
    )

    row = json.loads(json.dumps(evidence._evidence_training_export_row(item), default=str))

    assert row["status"] == status
    assert row["dataset_id"] == str(dataset_id)


@pytest.mark.parametrize("reason", ["", None])
def test_feedback_training_export_preserves_stored_reason(reason: str | None) -> None:
    from app.models.chat import Conversation, Message

    feedback = MessageFeedback(id=uuid4(), extra={}, tags=[], rating=5, reason=reason)
    assistant = Message(id=uuid4())
    conversation = Conversation(id=uuid4(), dataset_id=None)

    row = evidence._feedback_training_export_row(
        feedback=feedback,
        assistant=assistant,
        conversation=conversation,
        trace_payload=None,
        question="policy",
        reference_sources=[],
    )

    assert row["source_metadata"]["reason"] == reason
    assert row["dataset_id"] is None


@pytest.mark.parametrize("include_sensitive", [True, False])
def test_access_graph_export_preserves_values_and_sensitive_redaction(include_sensitive: bool) -> None:
    document = Document(id=uuid4(), tenant_id=uuid4(), dataset_id=None, owner_id="", access_mode="")

    row = audit._export_access_graph_row(kind="document", row=document, include_sensitive=include_sensitive)

    assert row["owner_id"] == ("" if include_sensitive else None)
    assert row["owner_id_hash"] is None
    assert row["access_mode"] == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("capability", ["embedding", "reranker"])
async def test_failed_warmup_reports_the_actual_configured_model(
    monkeypatch: pytest.MonkeyPatch, capability: str
) -> None:
    monkeypatch.setattr(rag_runtime_warmup.settings, "EMBEDDING_MODEL", "")
    monkeypatch.setattr(rag_runtime_warmup.settings, "RERANKER_MODEL", "")

    def unavailable_provider(*_args):
        raise RuntimeError("provider probe failed")

    monkeypatch.setattr(rag_runtime_warmup, f"_probe_{capability}_runtime_sync", unavailable_provider)
    result = await getattr(rag_runtime_warmup, f"_probe_{capability}_runtime")(1.0)

    assert result["status"] == "failed"
    assert result["ready"] is False
    assert result["reason"] == "RuntimeError"
    assert result["model"] == ""


@pytest.mark.parametrize("lineage", ["", None])
def test_table_lineage_roundtrip_preserves_source_values(monkeypatch: pytest.MonkeyPatch, tmp_path, lineage) -> None:
    monkeypatch.setattr(table_store_service.settings, "TABLE_STORE_DIR", str(tmp_path / "tables"))
    assets = table_store_service.import_db_row_snapshots(
        tenant_id=uuid4(),
        dataset_id=uuid4(),
        document_id=uuid4(),
        snapshots=[
            {
                "sheet_name": "sample",
                "source_table": lineage,
                "source_sync_token": lineage,
                "columns": ["id"],
                "rows": [{"id": 1}],
            }
        ],
        max_tables=1,
        max_rows_per_table=10,
        max_cols=10,
        sample_rows=1,
    )

    assert len(assets) == 1
    assert assets[0].row_source_table == lineage
    assert assets[0].row_source_sync_token == lineage
    stored = json.loads(json.dumps({"table_store": {"tables": [asdict(assets[0])]}}, default=str))
    restored = table_store_service.list_tables_from_metadata(stored)
    assert len(restored) == 1
    assert restored[0].row_source_table == lineage
    assert restored[0].row_source_sync_token == lineage


def test_planner_diagnostics_keep_the_plan_expectation_when_override_is_blank() -> None:
    mismatch = table_store_service.evaluate_planner_execution_mismatch(
        planner_diagnostics={"sql_fingerprint": "planner-fingerprint"},
        expected_sql_fingerprint="",
        executed_sql="SELECT 1",
    )

    assert mismatch["expected_sql_fingerprint"] == "planner-fingerprint"
    assert mismatch["mismatch"] is True
    assert "sql_fingerprint_mismatch" in mismatch["reasons"]


@pytest.mark.parametrize("fingerprint", [0, False])
def test_planner_diagnostics_expose_invalid_fingerprint_types(fingerprint) -> None:
    with pytest.raises(AttributeError):
        table_store_service.evaluate_planner_execution_mismatch(
            planner_diagnostics={"sql_fingerprint": "planner-fingerprint"},
            expected_sql_fingerprint=fingerprint,
            executed_sql="SELECT 1",
        )


def test_planner_diagnostics_expose_an_empty_executed_statement() -> None:
    mismatch = table_store_service.evaluate_planner_execution_mismatch(
        planner_diagnostics=None, expected_sql_fingerprint=None, executed_sql=""
    )

    assert mismatch["expected_sql_fingerprint"] is None
    assert mismatch["actual_sql_fingerprint"] == ""


def test_trace_keeps_false_scope_presence_without_exposing_identifiers() -> None:
    from app.services.rag_trace_service import normalize_rag_trace_record

    trace = normalize_rag_trace_record(
        {
            "ts_ms": 1,
            "retrieval": {
                "per_query": [
                    {
                        "kind": "main",
                        "retriever_debug": {
                            "scope": {
                                "tenant_id": "",
                                "dataset_id": "",
                                "account_id_present": False,
                                "document_ids_count": 0,
                                "kind": "tenant",
                            }
                        },
                    }
                ]
            },
        }
    )

    payload = trace.model_dump(mode="json", exclude_none=True)

    assert payload["retrieval"]["per_query"][0]["retriever_debug"]["scope"] == {
        "tenant_id_present": False,
        "dataset_id_present": False,
        "account_id_present": False,
        "document_ids_count": 0,
        "kind": "tenant",
    }


def test_trace_does_not_invent_negative_presence_for_unknown_scope_fields() -> None:
    from app.services.rag_trace_service import normalize_rag_trace_record

    trace = normalize_rag_trace_record(
        {
            "ts_ms": 1,
            "retrieval": {"per_query": [{"retriever_debug": {"scope": {"kind": "tenant"}}}]},
        }
    )

    assert trace.retrieval.per_query[0].retriever_debug["scope"] == {"kind": "tenant"}


def test_trace_preserves_already_redacted_presence_flags() -> None:
    from app.services.rag_trace_service import normalize_rag_trace_record

    trace = normalize_rag_trace_record(
        {
            "ts_ms": 1,
            "retrieval": {
                "per_query": [
                    {
                        "retriever_debug": {
                            "scope": {"tenant_id_present": True, "dataset_id_present": False, "document_ids_count": 0}
                        }
                    }
                ]
            },
        }
    )

    assert trace.retrieval.per_query[0].retriever_debug["scope"] == {
        "tenant_id_present": True,
        "dataset_id_present": False,
        "document_ids_count": 0,
    }


@pytest.mark.parametrize("stored", ["", None])
def test_index_drift_response_preserves_optional_text(stored: str | None) -> None:
    from app.api.v1.observability import IndexDriftItemResponse, _serialize_index_drift_item
    from app.models.index_drift_item import IndexDriftItem

    dataset_id = uuid4()
    item = IndexDriftItem(
        id=uuid4(),
        tenant_id=uuid4(),
        dataset_id=dataset_id,
        document_id=None,
        chunk_id=None,
        operation="upsert",
        channel="vector",
        strictness="off",
        status="open",
        reason="stale",
        details={},
        replay_count=0,
        reconcile_task_id=stored,
        resolved_by=stored,
        resolution_note=stored,
    )

    response = IndexDriftItemResponse.model_validate(_serialize_index_drift_item(item))

    assert response.dataset_id == str(dataset_id)
    assert response.document_id is None
    assert response.reconcile_task_id == stored
    assert response.resolved_by == stored
    assert response.resolution_note == stored
    assert response.replay_count == 0


def test_index_drift_serializer_exposes_missing_required_details() -> None:
    from app.api.v1.observability import _serialize_index_drift_item
    from app.models.index_drift_item import IndexDriftItem

    item = IndexDriftItem(
        id=uuid4(),
        tenant_id=uuid4(),
        operation="upsert",
        channel="vector",
        strictness="off",
        status="open",
        reason="stale",
        details=None,
        marker={},
        replay_count=0,
    )

    with pytest.raises(TypeError):
        _serialize_index_drift_item(item)


@pytest.mark.parametrize("field", ["top_k", "score_threshold", "retrieval_mode"])
def test_profile_projection_exposes_missing_internal_baseline_fields(field: str) -> None:
    from app.api.v1.retrieval_profiles import _effective_profile, _runtime_baseline

    baseline = _runtime_baseline()
    del baseline[field]

    with pytest.raises(KeyError, match=field):
        _effective_profile(None, baseline=baseline)


def test_profile_baseline_reports_the_actual_sparse_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.v1.retrieval_profiles import _runtime_baseline, settings

    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_PROVIDER", "")

    assert _runtime_baseline()["sparse_retrieval_provider"] == ""


@pytest.mark.parametrize("stored", ["", None])
def test_feedback_case_metadata_preserves_category_source(stored: str | None) -> None:
    from app.api.v1.feedback import _build_regression_case_extra

    feedback = MessageFeedback(
        id=uuid4(), message_id=uuid4(), rating=5, category="other", category_source=stored, extra={}
    )

    extra = _build_regression_case_extra(fb=feedback, body_extra=None, dataset_id=None)

    assert extra["feedback_category_source"] == stored
