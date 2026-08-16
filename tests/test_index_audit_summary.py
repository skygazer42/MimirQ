

def test_compute_index_audit_summary_reports_missing_and_orphan_samples() -> None:
    from uuid import UUID

    from app.services.index_audit_service import compute_index_audit_summary

    tenant_id = UUID("00000000-0000-0000-0000-000000000000")
    dataset_id = UUID("11111111-1111-1111-1111-111111111111")

    out = compute_index_audit_summary(
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        active_documents=3,
        active_chunks=10,
        vector_id_missing=2,
        vector_ids_checked=["a", "b", "a"],
        vector_ids_existing={"a"},
        milvus_ids_sample=["a", "x"],
        active_chunk_ids_present={"a"},
        sample_limit=10,
    )

    assert out["active_documents"] == 3
    assert out["active_chunks"] == 10
    assert out["vector_id_missing"] == 2

    assert out["vector_ids_checked"] == 3
    assert out["vector_ids_missing_in_backend"] == 1
    assert out["vector_ids_missing_in_backend_sample"] == ["b"]

    assert out["milvus_ids_sampled"] == 2
    assert out["milvus_orphan_ids_sample"] == ["x"]
    assert out["index_channels"] == {}


def test_compute_index_channel_audit_summary_preserves_legacy_ready_behavior_without_rows(monkeypatch) -> None:  # noqa: ANN001
    from types import SimpleNamespace
    from uuid import UUID

    from app.services.index_audit_service import compute_index_channel_audit_summary

    tenant_id = UUID("00000000-0000-0000-0000-000000000000")
    dataset_id = UUID("11111111-1111-1111-1111-111111111111")
    document_id = UUID("22222222-2222-2222-2222-222222222222")

    monkeypatch.setattr(
        "app.services.index_audit_service.resolve_pipeline_effective",
        lambda **_kwargs: SimpleNamespace(
            chunk_vector_enabled=True,
            bm25_index_enabled=True,
            kg_enabled=False,
            event_vector_enabled=False,
            entity_vector_enabled=False,
        ),
    )

    document = SimpleNamespace(
        id=document_id,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        status="completed",
        error_message=None,
        doc_metadata={"active_pipeline_hash": "pipe-a", "active_pipeline_ready": True},
    )

    out = compute_index_channel_audit_summary(documents=[document], channel_rows=[])

    assert out["documents_with_channel_rows"] == 0
    assert out["documents_using_legacy_fallback"] == 1
    assert out["ready_documents"] == 1
    assert out["required_pending_documents"] == 0
    assert out["required_error_documents"] == 0
    assert out["optional_disabled_documents"] == 1
    assert out["optional_disabled_channels"] == 3
    assert out["required_pending_by_channel"] == {}
    assert out["required_error_by_channel"] == {}
    assert out["status_counts_by_channel"]["vector"] == {"ready": 1}
    assert out["status_counts_by_channel"]["kg"] == {"disabled": 1}
    assert out["legacy_by_channel"] == {
        "vector": 1,
        "bm25": 1,
        "kg": 1,
        "event_vector": 1,
        "entity_vector": 1,
    }
    assert out["optional_disabled_by_channel"] == {
        "kg": 1,
        "event_vector": 1,
        "entity_vector": 1,
    }


def test_compute_index_channel_audit_summary_distinguishes_required_and_optional_states(monkeypatch) -> None:  # noqa: ANN001
    from types import SimpleNamespace

    from app.services.index_audit_service import compute_index_channel_audit_summary

    monkeypatch.setattr(
        "app.services.index_audit_service.resolve_pipeline_effective",
        lambda **_kwargs: SimpleNamespace(
            chunk_vector_enabled=True,
            bm25_index_enabled=True,
            kg_enabled=False,
            event_vector_enabled=False,
            entity_vector_enabled=False,
        ),
    )

    document = SimpleNamespace(
        id="doc-1",
        tenant_id="tenant-1",
        dataset_id="dataset-1",
        status="processing",
        error_message=None,
        doc_metadata={"active_pipeline_hash": "pipe-a"},
    )
    rows = [
        SimpleNamespace(
            document_id="doc-1",
            pipeline_hash="pipe-a",
            channel="vector",
            required=True,
            enabled=True,
            status="pending",
            error=None,
        ),
        SimpleNamespace(
            document_id="doc-1",
            pipeline_hash="pipe-a",
            channel="bm25",
            required=True,
            enabled=True,
            status="error",
            error="bm25 failed",
        ),
        SimpleNamespace(
            document_id="doc-1",
            pipeline_hash="pipe-a",
            channel="kg",
            required=False,
            enabled=False,
            status="disabled",
            error=None,
        ),
        SimpleNamespace(
            document_id="doc-1",
            pipeline_hash="pipe-a",
            channel="event_vector",
            required=False,
            enabled=False,
            status="skipped",
            error=None,
        ),
    ]

    out = compute_index_channel_audit_summary(documents=[document], channel_rows=rows)

    assert out["documents_with_channel_rows"] == 1
    assert out["documents_using_legacy_fallback"] == 0
    assert out["ready_documents"] == 0
    assert out["required_pending_documents"] == 1
    assert out["required_error_documents"] == 1
    assert out["optional_disabled_documents"] == 1
    assert out["optional_skipped_documents"] == 1
    assert out["required_pending_channels"] == 1
    assert out["required_error_channels"] == 1
    assert out["optional_disabled_channels"] == 2
    assert out["optional_skipped_channels"] == 1
    assert out["required_pending_by_channel"] == {"vector": 1}
    assert out["required_error_by_channel"] == {"bm25": 1}
    assert out["optional_disabled_by_channel"] == {"entity_vector": 1, "kg": 1}
    assert out["optional_skipped_by_channel"] == {"event_vector": 1}
    assert out["status_counts_by_channel"]["vector"] == {"pending": 1}
    assert out["status_counts_by_channel"]["bm25"] == {"error": 1}
    assert out["legacy_by_channel"] == {"entity_vector": 1}


def test_classify_index_audit_reconcile_status_marks_legacy_unknown_without_rows() -> None:
    from app.services.index_audit_service import _classify_index_audit_reconcile_status

    out = _classify_index_audit_reconcile_status(
        current_index_readiness={"ready": True, "pending_channels": [], "error_channels": []},
        channel_rows_present=0,
    )

    assert out == {
        "status": "legacy_unknown",
        "reason": "document_has_no_current_pipeline_channel_rows",
        "legacy": True,
        "channel_rows_present": 0,
        "ready": True,
    }


def test_classify_index_audit_reconcile_status_prefers_error_then_pending_then_ready() -> None:
    from app.services.index_audit_service import _classify_index_audit_reconcile_status

    error = _classify_index_audit_reconcile_status(
        current_index_readiness={"ready": False, "pending_channels": [], "error_channels": ["bm25"]},
        channel_rows_present=2,
    )
    pending = _classify_index_audit_reconcile_status(
        current_index_readiness={"ready": False, "pending_channels": ["vector"], "error_channels": []},
        channel_rows_present=2,
    )
    ready = _classify_index_audit_reconcile_status(
        current_index_readiness={"ready": True, "pending_channels": [], "error_channels": []},
        channel_rows_present=2,
    )

    assert error["status"] == "error"
    assert error["reason"] == "document_index_channels_error"
    assert pending["status"] == "pending"
    assert pending["reason"] == "document_index_channels_pending"
    assert ready["status"] == "ready"
    assert ready["reason"] is None


def test_plan_index_audit_reconcile_reports_only_pending_error_as_candidates(monkeypatch) -> None:  # noqa: ANN001
    from types import SimpleNamespace
    from uuid import UUID

    from app.services import index_audit_service as audit_service

    tenant_id = UUID("00000000-0000-0000-0000-000000000000")
    dataset_id = UUID("11111111-1111-1111-1111-111111111111")
    docs = [SimpleNamespace(id="doc-pending"), SimpleNamespace(id="doc-legacy"), SimpleNamespace(id="doc-ready")]

    class _Query:
        def limit(self, _cap):  # noqa: ANN001, ANN201
            return self

        def all(self):  # noqa: ANN201
            return list(docs)

    monkeypatch.setattr(audit_service.DatasetService, "get_dataset", lambda *_args, **_kwargs: object(), raising=True)
    monkeypatch.setattr(audit_service, "_active_index_audit_documents_query", lambda **_kwargs: _Query(), raising=True)

    payloads = {
        "doc-pending": {
            "status": "pending",
            "reason": "document_index_channels_pending",
            "legacy": False,
            "ready": False,
            "channel_rows_present": 2,
            "current_index_readiness": {"pending_channels": ["bm25"], "error_channels": []},
        },
        "doc-legacy": {
            "status": "legacy_unknown",
            "reason": "document_has_no_current_pipeline_channel_rows",
            "legacy": True,
            "ready": True,
            "channel_rows_present": 0,
            "current_index_readiness": {"pending_channels": [], "error_channels": []},
        },
        "doc-ready": {
            "status": "ready",
            "reason": None,
            "legacy": False,
            "ready": True,
            "channel_rows_present": 2,
            "current_index_readiness": {"pending_channels": [], "error_channels": []},
        },
    }
    monkeypatch.setattr(
        audit_service,
        "_build_index_audit_reconcile_document_status_payload",
        lambda **kwargs: {
            "schema": "mimirq.index_audit_reconcile_status.v1",
            "tenant_id": str(tenant_id),
            "dataset_id": str(dataset_id),
            "document_id": str(kwargs["document"].id),
            **payloads[str(kwargs["document"].id)],
        },
        raising=True,
    )

    plan = audit_service.plan_index_audit_reconcile(
        db=SimpleNamespace(),
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        limit=500,
        dry_run=True,
    )

    assert plan["scan_limit"] == 200
    assert plan["scanned_documents"] == 3
    assert plan["counts"]["candidate_documents"] == 1
    assert plan["counts"]["report_only_documents"] == 2
    assert [item["action"] for item in plan["items"]] == [
        "enqueue_rebuild",
        "report_only",
        "report_only",
    ]
