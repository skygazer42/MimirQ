from __future__ import annotations

import json


def test_replay_capture_record_redacts_query_and_chunk_text() -> None:
    from app.rag.core.hashing import stable_hash
    from app.rag.evaluation.replay_capture import build_retrieval_replay_capture_record

    query = "My SSN is 123-45-6789"
    payload = {
        "schema": "mimirq.evidence.v1",
        "citations": [
            {
                "chunk_id": "c1",
                "document_id": "d1",
                "chunk_content": "this should never be captured",
                "relevance_score": 0.9,
            }
        ],
        "metrics": {"retrieval_config_hash": "cfg123"},
    }

    rec = build_retrieval_replay_capture_record(
        query=query,
        dataset_id="ds",
        document_ids=[],
        rag_config={"retrieval_mode": "hybrid", "retrieval_profile": "recall50", "top_k": 50},
        evidence_payload=payload,
        seed=7,
        max_citations=5,
    )

    assert rec.get("schema") == "mimirq.retrieval_replay_capture.v1"
    assert rec.get("query_hash") == stable_hash(query, length=16)
    assert rec.get("retrieval_config_hash") == "cfg123"

    dumped = json.dumps(rec, ensure_ascii=False, sort_keys=True)
    assert "123-45-6789" not in dumped
    assert "chunk_content" not in dumped
    assert "this should never be captured" not in dumped


def test_replay_capture_fingerprint_is_deterministic_and_order_sensitive() -> None:
    from app.rag.evaluation.replay_capture import fingerprint_citations

    citations = [
        {"chunk_id": "c1", "document_id": "d1", "relevance_score": 0.9},
        {"chunk_id": "c2", "document_id": "d2", "relevance_score": 0.8},
    ]

    fp1 = fingerprint_citations(citations)
    fp2 = fingerprint_citations(citations)
    assert fp1 == fp2

    fp3 = fingerprint_citations(list(reversed(citations)))
    assert fp3 != fp1

