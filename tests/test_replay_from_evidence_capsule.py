from __future__ import annotations

import json


def test_replay_from_evidence_capsule_builds_replay_payload(tmp_path) -> None:  # noqa: ANN001
    from app.rag.core.evidence_capsule_builder import build_evidence_capsule
    from scripts.replay_from_evidence_capsule import run

    capsule = build_evidence_capsule(
        query_for_retrieval="Revenue by region",
        citations=[{"document_id": "doc-1", "chunk_id": "chunk-1"}],
        metrics={
            "retrieval_mode": "hybrid",
            "retrieval_contract_mode": "must_recall_strict",
            "must_recall_enabled": True,
        },
        retrieval_trace={"schema": "mimirq.retrieval_trace.v1", "passes": []},
    )
    path = tmp_path / "capsule.json"
    path.write_text(json.dumps(capsule, ensure_ascii=False), encoding="utf-8")

    out = run(capsule_path=path)
    assert str(out.get("schema") or "") == "mimirq.evidence_replay.v1"
    assert bool(out.get("capsule_hash_valid")) is True
    replay = out.get("replay_request") or {}
    assert str(replay.get("query") or "") == "Revenue by region"
