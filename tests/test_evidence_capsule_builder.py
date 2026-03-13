from __future__ import annotations


def test_build_evidence_capsule_contains_hashes_and_contract_fields() -> None:
    from app.rag.core.evidence_capsule_builder import (
        EVIDENCE_CAPSULE_SCHEMA_V1,
        build_evidence_capsule,
        validate_evidence_capsule,
    )

    capsule = build_evidence_capsule(
        query_for_retrieval="按 region 统计订单金额前10",
        citations=[
            {
                "document_id": "doc-1",
                "chunk_id": "chunk-1",
                "retrieval_role": "tag",
                "table_id": "doc:1:sheet:0",
                "row_source_table": "demo.orders",
            }
        ],
        metrics={
            "retrieval_mode": "hybrid",
            "retrieval_config_hash": "cfg123",
            "must_recall_status": "passed",
            "must_recall_passed": True,
            "must_recall_enabled": True,
            "must_recall_fail_reasons": [],
        },
        retrieval_trace={"schema": "mimirq.retrieval_trace.v1", "passes": []},
        request_context={"tenant_id": "t1"},
    )

    assert str(capsule.get("schema") or "") == EVIDENCE_CAPSULE_SCHEMA_V1
    assert str(capsule.get("capsule_hash") or "")
    citations = list(capsule.get("citations") or [])
    assert len(citations) == 1
    assert str(citations[0].get("citation_hash") or "")
    assert str(capsule.get("must_recall", {}).get("status") or "") == "passed"
    ok, reason = validate_evidence_capsule(capsule)
    assert ok is True
    assert reason == "ok"
