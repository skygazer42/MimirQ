from __future__ import annotations

import json


def test_mine_hard_negatives_is_pii_safe_and_deduped_per_doc() -> None:
    from app.rag.core.hashing import stable_hash
    from app.rag.evaluation.hard_negative_mining import mine_hard_negatives_for_case_from_trace

    question = "How do I reset my password?"
    qh = stable_hash(question, length=16)

    case = {
        "question": question,
        "reference_sources": [
            {"chunk_id": "c_pos", "document_id": "d_pos"},
        ],
    }
    trace = {
        "event": "rag_trace",
        "question_hash": qh,
        "retrieval": {"retrieval_config_hash": "cfg123"},
        "citations": [
            {"chunk_id": "c_neg1", "document_id": "d1", "relevance_score": 0.99},
            {"chunk_id": "c_neg2", "document_id": "d1", "relevance_score": 0.98},
            {"chunk_id": "c_pos", "document_id": "d_pos", "relevance_score": 0.10},
            {"chunk_id": "c_neg3", "document_id": "d3", "relevance_score": 0.05},
        ],
    }

    rec = mine_hard_negatives_for_case_from_trace(
        case=case,
        trace_record=trace,
        query_hash=qh,
        max_hard_negatives=10,
        max_negatives_per_document=1,
    )

    assert rec.get("schema") == "mimirq.hard_negatives.v1"
    assert rec.get("query_hash") == qh
    assert rec.get("retrieval_config_hash") == "cfg123"

    hard = rec.get("hard_negatives") or []
    assert [h.get("chunk_id") for h in hard] == ["c_neg1"]

    # PII-safe: no raw question/query text in the output.
    dumped = json.dumps(rec, ensure_ascii=False, sort_keys=True)
    assert "reset my password" not in dumped


def test_hard_negative_loader_builds_lookup_by_query_hash(tmp_path) -> None:
    from app.rag.evaluation.hard_negative_mining import load_hard_negatives_jsonl

    p = tmp_path / "hn.jsonl"
    p.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "schema": "mimirq.hard_negatives.v1",
                        "query_hash": "q1",
                        "retrieval_config_hash": "cfg",
                        "hard_negatives": [{"chunk_id": "c1"}, {"chunk_id": "c2"}],
                    }
                ),
                json.dumps(
                    {
                        "schema": "mimirq.hard_negatives.v1",
                        "query_hash": "q2",
                        "retrieval_config_hash": "cfg",
                        "hard_negatives": [{"chunk_id": "c9"}],
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    lookup = load_hard_negatives_jsonl(p)
    assert lookup.get("q1") == ["c1", "c2"]
    assert lookup.get("q2") == ["c9"]

