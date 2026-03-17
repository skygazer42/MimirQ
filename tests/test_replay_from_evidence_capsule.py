from __future__ import annotations

import json


def test_replay_from_evidence_capsule_builds_replay_payload(tmp_path) -> None:  # noqa: ANN001
    from app.rag.core.evidence_capsule_builder import build_evidence_capsule
    from app.rag.policy.recall_obligation import build_must_recall_proof
    from scripts.replay_from_evidence_capsule import run

    proof = build_must_recall_proof(
        enabled=True,
        status="passed",
        passed=True,
        required_source_keys=["sales"],
        required_anchor_fields=["chunk_id", "document_id"],
        source_eval={"missing_source_keys": [], "matched_by_required_source_key": {"sales": "sales"}},
        anchor_eval={"missing_any": 0, "missing_counts": {"chunk_id": 0, "document_id": 0}},
        fail_reasons=[],
        second_pass={"attempted": False, "used": False},
        contract_fail_reason_taxonomy="mimirq.contract_fail_reason.v1",
    )

    capsule = build_evidence_capsule(
        query_for_retrieval="Revenue by region",
        citations=[{"document_id": "doc-1", "chunk_id": "chunk-1"}],
        metrics={
            "retrieval_mode": "hybrid",
            "retrieval_contract_mode": "must_recall_strict",
            "must_recall_enabled": True,
        },
        retrieval_trace={
            "schema": "mimirq.retrieval_trace_pass.v1",
            "contract_diagnostics": {"must_recall": {"proof": proof}},
        },
    )
    path = tmp_path / "capsule.json"
    path.write_text(json.dumps(capsule, ensure_ascii=False), encoding="utf-8")

    out = run(capsule_path=path)
    assert str(out.get("schema") or "") == "mimirq.evidence_replay.v1"
    assert bool(out.get("capsule_hash_valid")) is True
    replay = out.get("replay_request") or {}
    assert str(replay.get("query") or "") == "Revenue by region"
    rag_config = replay.get("rag_config") or {}
    assert rag_config.get("must_recall_expected_source_keys") == ["sales"]
    assert rag_config.get("must_recall_required_anchor_fields") == ["chunk_id", "document_id"]
