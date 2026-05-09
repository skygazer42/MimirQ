from __future__ import annotations

import json

from app.rag.feedback_loop.dispatcher import (
    FEEDBACK_LOOP_BATCH_SCHEMA_V1,
    dispatch_feedback_loop_batch,
    dispatch_scheduled_feedback_loop_batch,
)


def test_manual_dispatcher_exports_hardneg_jsonl_without_realtime_listener(tmp_path) -> None:
    output_path = tmp_path / "feedback-hard-negatives.jsonl"
    rows = [
        {
            "feedback_id": "fb-neg-1",
            "conversation_id": "conv-1",
            "message_id": "msg-1",
            "dataset_id": "dataset-1",
            "rating": 2,
            "original_query": "PLC 状态为什么错了",
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

    result = dispatch_feedback_loop_batch(
        rows=rows,
        output_path=output_path,
        dry_run=False,
        trigger="manual",
        max_rating=2,
    )

    assert result["schema"] == FEEDBACK_LOOP_BATCH_SCHEMA_V1
    assert result["trigger"] == "manual"
    assert result["realtime_listener_enabled"] is False
    assert result["candidates"]["negative_feedback_total"] == 1
    assert result["hard_negative_export"]["written_records"] == 1
    assert output_path.exists()

    record = json.loads(output_path.read_text(encoding="utf-8").splitlines()[0])
    assert record["source_feedback_ids"] == ["fb-neg-1"]
    assert record["source_conversation_ids"] == ["conv-1"]
    assert record["source_message_ids"] == ["msg-1"]


def test_scheduled_dispatcher_wrapper_uses_scheduled_trigger_without_listener(tmp_path) -> None:
    result = dispatch_scheduled_feedback_loop_batch(
        rows=[],
        output_path=tmp_path / "scheduled.jsonl",
        dry_run=True,
    )

    assert result["schema"] == FEEDBACK_LOOP_BATCH_SCHEMA_V1
    assert result["trigger"] == "scheduled"
    assert result["realtime_listener_enabled"] is False
