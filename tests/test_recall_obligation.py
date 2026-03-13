from __future__ import annotations

from app.rag.policy.recall_obligation import (
    MUST_RECALL_PROOF_SCHEMA_V1,
    RECALL_OBLIGATION_LEDGER_SCHEMA_V1,
    build_must_recall_proof,
    build_recall_obligation_ledger,
)


def test_build_recall_obligation_ledger_tracks_source_and_anchor_coverage() -> None:
    ledger = build_recall_obligation_ledger(
        required_source_keys=["sales", "inventory"],
        source_eval={
            "matched_by_required_source_key": {"sales": "sales"},
            "missing_source_keys": ["inventory"],
        },
        required_anchor_fields=["chunk_id", "document_id"],
        anchor_eval={
            "missing_any": 2,
            "missing_counts": {"chunk_id": 0, "document_id": 2},
        },
    )

    assert ledger["schema"] == RECALL_OBLIGATION_LEDGER_SCHEMA_V1
    assert int(ledger["required_total"]) == 4
    assert int(ledger["missing_total"]) == 2
    assert int((ledger["source_keys"] or {}).get("missing") or 0) == 1
    assert int((ledger["anchors"] or {}).get("missing_fields") or 0) == 1


def test_build_must_recall_proof_is_versioned_and_self_contained() -> None:
    proof = build_must_recall_proof(
        enabled=True,
        status="passed",
        passed=True,
        required_source_keys=["sales"],
        required_anchor_fields=["chunk_id", "document_id"],
        source_eval={
            "missing_source_keys": [],
            "matched_by_required_source_key": {"sales": "sales"},
        },
        anchor_eval={"missing_any": 0, "missing_counts": {"chunk_id": 0, "document_id": 0}},
        fail_reasons=[],
        second_pass={"attempted": False, "used": False},
        contract_fail_reason_taxonomy="mimirq.contract_fail_reason.v1",
    )

    assert proof["schema"] == MUST_RECALL_PROOF_SCHEMA_V1
    assert proof["enabled"] is True
    assert proof["status"] == "passed"
    assert proof["passed"] is True
    ledger = proof.get("obligation_ledger") or {}
    assert ledger.get("schema") == RECALL_OBLIGATION_LEDGER_SCHEMA_V1
    assert int(ledger.get("missing_total") or 0) == 0
