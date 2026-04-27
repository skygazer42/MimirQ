from __future__ import annotations

from app.rag.evaluation.poc_runner.source_builder import build_dataset_analysis_sources


def test_build_dataset_analysis_sources_uses_request_id_as_primary_key() -> None:
    result = build_dataset_analysis_sources(
        traces=[
            {"request_id": "req-1", "conversation_id": "conv-1", "ts_ms": 10},
        ],
        feedback_rows=[
            {
                "id": "fb-1",
                "message_id": "a-1",
                "conversation_id": "conv-1",
                "rating": 1,
                "reason": "bad",
                "extra": {"retrieval_trace_request_id": "req-1"},
            }
        ],
        conversations=[{"id": "conv-1", "dataset_id": "ds-1"}],
        messages=[
            {
                "id": "u-1",
                "conversation_id": "conv-1",
                "role": "user",
                "content": "485 怎么配置？",
                "created_at": "2026-04-21T10:00:00Z",
            },
            {
                "id": "a-1",
                "conversation_id": "conv-1",
                "role": "assistant",
                "content": "请按手册配置。",
                "created_at": "2026-04-21T10:00:01Z",
                "message_metadata": {"request_id": "req-1"},
            },
        ],
    )

    assert result["counts"] == {
        "all_interactions": 1,
        "feedback_interactions": 1,
        "attributable_feedback_interactions": 1,
    }
    row = result["rows"][0]
    assert row["feedback"]["id"] == "fb-1"
    assert row["assistant_message"]["id"] == "a-1"
    assert row["user_message"]["id"] == "u-1"
    assert row["conversation"]["dataset_id"] == "ds-1"
    assert row["linkage"]["feedback_match"] == "request_id"
    assert row["linkage"]["assistant_match"] == "request_id"


def test_build_dataset_analysis_sources_falls_back_to_message_id_when_request_id_missing() -> None:
    result = build_dataset_analysis_sources(
        traces=[
            {"conversation_id": "conv-2", "ts_ms": 20},
        ],
        feedback_rows=[
            {
                "id": "fb-2",
                "message_id": "a-2",
                "conversation_id": "conv-2",
                "rating": 2,
                "reason": "still wrong",
                "extra": {},
            }
        ],
        conversations=[{"id": "conv-2", "dataset_id": "ds-2"}],
        messages=[
            {
                "id": "u-2",
                "conversation_id": "conv-2",
                "role": "user",
                "content": "Q2",
                "created_at": "2026-04-21T10:10:00Z",
            },
            {
                "id": "a-2",
                "conversation_id": "conv-2",
                "role": "assistant",
                "content": "A2",
                "created_at": "2026-04-21T10:10:01Z",
                "message_metadata": {},
            },
        ],
    )

    row = result["rows"][0]
    assert row["feedback"]["id"] == "fb-2"
    assert row["assistant_message"]["id"] == "a-2"
    assert row["user_message"]["id"] == "u-2"
    assert row["linkage"]["feedback_match"] == "message_id"
    assert result["counts"]["feedback_interactions"] == 1
    assert result["counts"]["attributable_feedback_interactions"] == 1
