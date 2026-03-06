from __future__ import annotations

from app.services.hardcase_discovery_service import (
    build_rag_trace_index_from_records,
    plan_feedback_hardcase_candidates,
)


def test_build_rag_trace_index_prefers_latest_by_ts_ms() -> None:
    idx = build_rag_trace_index_from_records(
        records=[
            {
                "event": "rag_trace",
                "tenant_id": "t1",
                "request_id": "r1",
                "ts_ms": 10,
                "question_hash": "qh-old",
                "retrieval": {"retrieval_config_hash": "cfg-old", "errors": ["timeout:x"]},
                "citations_count": 0,
            },
            {
                "event": "rag_trace",
                "tenant_id": "t1",
                "request_id": "r1",
                "ts_ms": 20,
                "question_hash": "qh-new",
                "retrieval": {"retrieval_config_hash": "cfg-new", "errors": []},
                "citations_count": 3,
            },
        ],
        tenant_id="t1",
        cutoff_ms=0,
    )
    assert idx["r1"]["question_hash"] == "qh-new"
    assert idx["r1"]["retrieval_config_hash"] == "cfg-new"
    assert idx["r1"]["citations_count"] == 3


def test_plan_feedback_hardcases_dedupes_by_question_hash_and_marks_in_suite() -> None:
    trace_index = {
        "req-a": {
            "request_id": "req-a",
            "ts_ms": 100,
            "question_hash": "qh1",
            "retrieval_config_hash": "cfg1",
            "citations_count": 0,
            "retrieval_error_kinds": {"timeout": 1},
            "rag_config_template": {"template_key": "k", "version": 2, "patch_hash": "ph"},
        }
    }

    # Two feedback rows map to the same request_id -> same question_hash; should cluster to 1 candidate.
    candidates = plan_feedback_hardcase_candidates(
        feedback_rows=[
            {
                "feedback_id": "fb1",
                "conversation_id": "c1",
                "message_id": "m1",
                "request_id": "req-a",
                "rating": 1,
                "tags": ["neg"],
            },
            {
                "feedback_id": "fb2",
                "conversation_id": "c2",
                "message_id": "m2",
                "request_id": "req-a",
                "rating": 2,
                "tags": [],
            },
        ],
        trace_index=trace_index,
        existing_feedback_ids=set(),
        existing_question_hashes={"qh1"},
        max_candidates=10,
        include_existing=False,
    )

    assert len(candidates) == 0  # filtered because already in suite via question_hash

    candidates2 = plan_feedback_hardcase_candidates(
        feedback_rows=[
            {
                "feedback_id": "fb1",
                "conversation_id": "c1",
                "message_id": "m1",
                "request_id": "req-a",
                "rating": 1,
                "tags": ["neg"],
            },
            {
                "feedback_id": "fb2",
                "conversation_id": "c2",
                "message_id": "m2",
                "request_id": "req-a",
                "rating": 2,
                "tags": [],
            },
        ],
        trace_index=trace_index,
        existing_feedback_ids=set(),
        existing_question_hashes=set(),
        max_candidates=10,
        include_existing=True,
    )

    assert len(candidates2) == 1
    cand = candidates2[0]
    assert cand["cluster_size"] == 2
    assert cand["question_hash"] == "qh1"
    assert cand["retrieval_config_hash"] == "cfg1"
    assert cand["citations_count"] == 0
    assert cand["retrieval_error_kinds"].get("timeout") == 1
    assert cand["rag_config_template"]["patch_hash"] == "ph"

