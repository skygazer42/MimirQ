from __future__ import annotations

from app.rag.evaluation.poc_runner.telemetry import (
    POC_TELEMETRY_SCHEMA_V1,
    build_poc_interaction_row,
    build_poc_interaction_rows,
)


def test_build_poc_interaction_row_normalizes_trace_messages_and_feedback() -> None:
    row = build_poc_interaction_row(
        {
            "trace": {
                "request_id": "req-1",
                "conversation_id": "conv-1",
                "ts_ms": 1_710_000_000_000,
                "retrieval": {"elapsed_sec": 1.2},
                "citations": [
                    {"source": "manual-a.pdf"},
                    {"source": "manual-a.pdf"},
                    {"source": "manual-b.pdf"},
                ],
            },
            "conversation": {"id": "conv-1", "dataset_id": "ds-1"},
            "user_message": {
                "id": "u-1",
                "content": "485 怎么配置？",
                "created_at": "2026-04-21T10:00:00Z",
            },
            "assistant_message": {
                "id": "a-1",
                "content": "请按手册配置。",
                "message_metadata": {"request_id": "req-1"},
                "created_at": "2026-04-21T10:00:01Z",
            },
            "feedback": {
                "id": "fb-1",
                "rating": 1,
                "reason": "答非所问",
                "extra": {"retrieval_trace_request_id": "req-1"},
            },
        }
    )

    assert row["schema"] == POC_TELEMETRY_SCHEMA_V1
    assert row["interaction_id"] == "req-1"
    assert row["request_id"] == "req-1"
    assert row["conversation_id"] == "conv-1"
    assert row["dataset_id"] == "ds-1"
    assert row["original_query"] == "485 怎么配置？"
    assert row["llm_response"] == "请按手册配置。"
    assert row["final_context_filenames"] == ["manual-a.pdf", "manual-b.pdf"]
    assert row["feedback_id"] == "fb-1"
    assert row["feedback_score"] == 1
    assert row["feedback_comment"] == "答非所问"
    assert row["has_feedback"] is True
    assert row["feedback_polarity"] == "negative"
    assert row["attributable_feedback_eligible"] is True
    assert row["latency_total_ms"] == 1200


def test_build_poc_interaction_rows_preserves_order_and_handles_missing_feedback() -> None:
    rows = build_poc_interaction_rows(
        [
            {
                "trace": {"request_id": "req-1", "conversation_id": "conv-1", "ts_ms": 10},
                "conversation": {"id": "conv-1", "dataset_id": "ds-1"},
                "user_message": {"id": "u-1", "content": "Q1"},
                "assistant_message": {"id": "a-1", "content": "A1"},
            },
            {
                "trace": {"request_id": "req-2", "conversation_id": "conv-2", "ts_ms": 20},
                "conversation": {"id": "conv-2", "dataset_id": "ds-2"},
                "user_message": {"id": "u-2", "content": "Q2"},
                "assistant_message": {"id": "a-2", "content": "A2"},
            },
        ]
    )

    assert [row["interaction_id"] for row in rows] == ["req-1", "req-2"]
    assert rows[0]["has_feedback"] is False
    assert rows[0]["feedback_polarity"] == "none"
    assert rows[1]["dataset_id"] == "ds-2"
