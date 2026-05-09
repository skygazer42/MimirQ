from __future__ import annotations

import json

from app.rag.evaluation.hard_negative_mining import HARD_NEGATIVES_SCHEMA_V1, load_hard_negatives_jsonl
from app.rag.feedback_loop.candidates import build_feedback_loop_candidates
from app.rag.feedback_loop.hard_negative_promoter import (
    FEEDBACK_HARD_NEGATIVE_EXPORT_SCHEMA_V1,
    promote_hard_negatives_to_jsonl,
)


def test_promoter_writes_pii_safe_jsonl_with_feedback_lineage(tmp_path) -> None:
    rows = [
        {
            "feedback_id": "fb-neg-1",
            "conversation_id": "conv-1",
            "message_id": "msg-1",
            "dataset_id": "dataset-1",
            "rating": 1,
            "original_query": "MCU 私密报警原因是什么",
            "reference_sources": [{"chunk_id": "chunk-positive", "document_id": "doc-good"}],
            "retrieval_trace": {
                "retrieval": {"retrieval_config_hash": "cfg-1"},
                "citations": [
                    {"chunk_id": "chunk-hard", "document_id": "doc-bad"},
                    {"chunk_id": "chunk-positive", "document_id": "doc-good"},
                ],
            },
        }
    ]
    candidates = build_feedback_loop_candidates(rows, max_rating=2)
    output_path = tmp_path / "hard_negatives.jsonl"

    summary = promote_hard_negatives_to_jsonl(
        candidates,
        output_path=output_path,
        append=False,
        dry_run=False,
    )

    assert summary["schema"] == FEEDBACK_HARD_NEGATIVE_EXPORT_SCHEMA_V1
    assert summary["written_records"] == 1
    assert summary["hard_negatives"] == 1
    assert summary["output_path"] == str(output_path)
    assert output_path.exists()

    [line] = output_path.read_text(encoding="utf-8").splitlines()
    record = json.loads(line)
    assert record["schema"] == HARD_NEGATIVES_SCHEMA_V1
    assert record["hard_negatives"] == [{"chunk_id": "chunk-hard", "document_id": "doc-bad", "rank": 1}]
    assert record["source"] == "feedback_loop"
    assert record["source_feedback_ids"] == ["fb-neg-1"]
    assert record["source_conversation_ids"] == ["conv-1"]
    assert record["source_message_ids"] == ["msg-1"]
    assert record["dataset_id"] == "dataset-1"
    assert "MCU 私密报警原因是什么" not in line

    loaded = load_hard_negatives_jsonl(output_path)
    assert loaded == {record["query_hash"]: ["chunk-hard"]}
