from __future__ import annotations

import pytest

from app.services.hardcase_discovery_service import (
    build_parse_risk_hardcase_candidate,
    build_rag_trace_index_from_records,
    evaluate_parse_risk_auto_enqueue_policy,
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


def test_build_parse_risk_hardcase_candidate_emits_only_for_actionable_levels() -> None:
    c = build_parse_risk_hardcase_candidate(
        query_hash="qh-1",
        retrieval_mode="hybrid",
        retrieval_profile="grounded_strict",
        retrieval_config_hash="cfg-1",
        parse_risk={"level": "high", "score": 0.82, "reason": "high_parse_risk_reparse_documents"},
        ts_ms=123,
    )
    assert isinstance(c, dict)
    assert c.get("reason") == "parse_risk_tail"
    assert c.get("parse_risk_level") == "high"
    assert c.get("parse_risk_score") == pytest.approx(0.82)
    assert isinstance(c.get("dedupe_key"), str) and len(str(c.get("dedupe_key") or "")) >= 16

    c2 = build_parse_risk_hardcase_candidate(
        query_hash="qh-2",
        retrieval_mode="hybrid",
        retrieval_profile=None,
        retrieval_config_hash=None,
        parse_risk={"level": "low", "score": 0.2, "reason": "monitor_parse_quality_tail"},
        ts_ms=456,
    )
    assert c2 is None


def test_evaluate_parse_risk_auto_enqueue_policy_respects_level_and_score() -> None:
    out = evaluate_parse_risk_auto_enqueue_policy(
        parse_risk={"level": "high", "score": 0.82, "hardcase_eligible": True},
        enabled=True,
        allowed_levels={"high", "medium"},
        min_score=0.5,
    )
    assert out["enqueue"] is True
    assert out["reason"] == "eligible"

    out2 = evaluate_parse_risk_auto_enqueue_policy(
        parse_risk={"level": "medium", "score": 0.3, "hardcase_eligible": True},
        enabled=True,
        allowed_levels={"high", "medium"},
        min_score=0.5,
    )
    assert out2["enqueue"] is False
    assert out2["reason"] == "score_below_min"
