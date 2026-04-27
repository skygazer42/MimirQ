from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4


def test_summarize_chunk_retrieval_usage_from_records_filters_to_chunk_and_tenant() -> None:
    from app.services.lineage_service import summarize_chunk_retrieval_usage_from_records

    tenant_id = uuid4()
    other_tenant_id = uuid4()
    document_id = uuid4()
    chunk_id = uuid4()
    other_chunk_id = uuid4()
    now = datetime(2026, 1, 1, 2, 0, tzinfo=UTC)

    records = [
        {
            "event": "rag_trace",
            "tenant_id": str(tenant_id),
            "request_id": "req-older",
            "conversation_id": "conv-1",
            "ts_ms": int(datetime(2025, 12, 31, 0, 0, tzinfo=UTC).timestamp() * 1000),
            "retrieval": {"mode": "hybrid", "retrieval_config_hash": "cfg-old"},
            "citations": [{"document_id": str(document_id), "chunk_id": str(chunk_id)}],
        },
        {
            "event": "rag_trace",
            "tenant_id": str(other_tenant_id),
            "request_id": "req-other-tenant",
            "conversation_id": "conv-1",
            "ts_ms": int(datetime(2026, 1, 1, 1, 40, tzinfo=UTC).timestamp() * 1000),
            "retrieval": {"mode": "hybrid", "retrieval_config_hash": "cfg-other"},
            "citations": [{"document_id": str(document_id), "chunk_id": str(chunk_id)}],
        },
        {
            "event": "rag_trace",
            "tenant_id": str(tenant_id),
            "request_id": "req-wrong-chunk",
            "conversation_id": "conv-2",
            "ts_ms": int(datetime(2026, 1, 1, 1, 45, tzinfo=UTC).timestamp() * 1000),
            "retrieval": {"mode": "keyword", "retrieval_config_hash": "cfg-wrong"},
            "citations": [{"document_id": str(document_id), "chunk_id": str(other_chunk_id)}],
        },
        {
            "event": "rag_trace",
            "tenant_id": str(tenant_id),
            "request_id": "req-1",
            "conversation_id": "conv-2",
            "ts_ms": int(datetime(2026, 1, 1, 1, 50, tzinfo=UTC).timestamp() * 1000),
            "retrieval": {"mode": "hybrid", "retrieval_config_hash": "cfg-1"},
            "citations": [
                {"document_id": str(document_id), "chunk_id": str(chunk_id), "page_number": 2},
                {"document_id": str(document_id), "chunk_id": str(other_chunk_id), "page_number": 3},
            ],
        },
        {
            "event": "rag_trace",
            "tenant_id": str(tenant_id),
            "request_id": "req-2",
            "conversation_id": "conv-3",
            "ts_ms": int(datetime(2026, 1, 1, 1, 55, tzinfo=UTC).timestamp() * 1000),
            "retrieval": {"mode": "expanded", "retrieval_config_hash": "cfg-2"},
            "citations": [
                {"document_id": str(document_id), "chunk_id": str(chunk_id), "page_number": 2},
                {"document_id": str(document_id), "chunk_id": str(chunk_id), "page_number": 2},
            ],
        },
    ]

    out = summarize_chunk_retrieval_usage_from_records(
        records,
        tenant_id=tenant_id,
        chunk_id=chunk_id,
        now=now,
        window_minutes=60,
        max_hits=4,
    )

    assert out["schema"] == "mimirq.chunk_retrieval_lineage.v1"
    assert out["chunk_id"] == str(chunk_id)
    assert out["traces_scanned"] == 3
    assert out["traces_with_hits"] == 2
    assert out["citations_matched"] == 3
    assert out["request_ids"] == ["req-2", "req-1"]
    assert out["retrieval_modes"] == {"expanded": 1, "hybrid": 1}
    assert [item["request_id"] for item in out["hits"]] == ["req-2", "req-2", "req-1"]
    assert out["hits"][0]["retrieval"]["mode"] == "expanded"
    assert out["hits"][0]["retrieval"]["retrieval_config_hash"] == "cfg-2"


def test_build_chunk_lineage_payload_includes_connector_acl_pipeline_and_usage() -> None:
    from app.rag.core.hashing import stable_hash
    from app.services.lineage_service import build_chunk_lineage_payload

    tenant_id = uuid4()
    dataset_id = uuid4()
    document_id = uuid4()
    chunk_id = uuid4()

    chunk = SimpleNamespace(
        id=chunk_id,
        tenant_id=tenant_id,
        document_id=document_id,
        chunk_index=7,
        page_number=3,
        start_char=120,
        end_char=280,
        vector_id="vec-1",
        doc_metadata={
            "chunk_role": "child",
            "pipeline_hash": "pipe-v2",
            "chunk_quality": {"grade": "good", "score": 0.91},
        },
    )
    document = SimpleNamespace(
        id=document_id,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        filename="ops/runbook.pdf",
        file_type="pdf",
        status="completed",
        owner_id="owner-42",
        access_mode="partial_members",
        chunk_count=12,
        total_characters=2400,
        doc_metadata={
            "pipeline_hash": "pipe-v2",
            "connector": {
                "connector_id": "sharepoint",
                "config_id": "cfg-1",
                "source_ref": "sp://sites/ops/runbook",
            },
            "acl_provenance": {
                "effective_access": {
                    "mode": "partial_members",
                    "partial_member_count": 2,
                    "partial_group_ids": ["group-1"],
                },
                "source_acl": {
                    "fallback_used": True,
                    "mapped_group_ids": ["group-1"],
                    "principal_hashes": ["p1", "p2"],
                },
            },
            "pipeline_provenance_versions": {
                "pipe-v2": {
                    "pipeline_hash": "pipe-v2",
                    "created_at": "2026-01-01T00:00:00Z",
                    "transforms": {"chunk": {"hash": "chunk-hash"}},
                }
            },
        },
    )
    permissions = [
        SimpleNamespace(account_id="alice@example.com"),
        SimpleNamespace(account_id="bob@example.com"),
    ]
    retrieval_usage = {
        "schema": "mimirq.chunk_retrieval_lineage.v1",
        "chunk_id": str(chunk_id),
        "traces_scanned": 5,
        "traces_with_hits": 2,
        "citations_matched": 3,
        "request_ids": ["req-2", "req-1"],
        "hits": [
            {"request_id": "req-2", "retrieval": {"mode": "expanded", "retrieval_config_hash": "cfg-2"}},
            {"request_id": "req-1", "retrieval": {"mode": "hybrid", "retrieval_config_hash": "cfg-1"}},
        ],
    }

    out = build_chunk_lineage_payload(
        chunk=chunk,
        document=document,
        permissions=permissions,
        retrieval_usage=retrieval_usage,
    )

    assert out["schema"] == "mimirq.lineage.chunk.v1"
    assert out["chunk"]["chunk_id"] == str(chunk_id)
    assert out["chunk"]["chunk_index"] == 7
    assert out["chunk"]["chunk_role"] == "child"
    assert out["document"]["document_id"] == str(document_id)
    assert out["document"]["dataset_id"] == str(dataset_id)
    assert out["connector"]["connector_id"] == "sharepoint"
    assert out["connector"]["source_ref"] == "sp://sites/ops/runbook"
    assert out["acl"]["mode"] == "partial_members"
    assert out["acl"]["permission_count"] == 2
    assert out["acl"]["permission_hashes"] == [
        stable_hash("alice@example.com", length=32),
        stable_hash("bob@example.com", length=32),
    ]
    assert out["pipeline"]["active_pipeline_hash"] == "pipe-v2"
    assert out["pipeline"]["version"]["transforms"]["chunk"]["hash"] == "chunk-hash"
    assert out["retrieval_usage"]["traces_with_hits"] == 2
    assert out["retrieval_usage"]["request_ids"] == ["req-2", "req-1"]
