from __future__ import annotations

import pytest

from app.rag.evaluation.online_shadow import (
    build_online_shadow_plan,
    diff_online_shadow_runs,
)


def test_diff_online_shadow_runs_compares_candidate_against_baseline_by_sample_id() -> None:
    diff = diff_online_shadow_runs(
        baseline=[
            {
                "sample_id": "s1",
                "route_id": "retrieval",
                "answer": {"text": "old answer"},
                "evaluators": {"answer_det": {"answer_f1": 0.5}},
                "latency_ms": 1200,
                "token_cost": 0.01,
            }
        ],
        candidate=[
            {
                "sample_id": "s1",
                "route_id": "retrieval",
                "answer": {"text": "new answer"},
                "evaluators": {"answer_det": {"answer_f1": 0.8}},
                "latency_ms": 900,
                "token_cost": 0.015,
            }
        ],
    )

    assert diff["schema"] == "mimirq.online_shadow_diff.v1"
    assert diff["summary"]["compared"] == 1
    assert diff["summary"]["candidate_only"] == 0
    assert diff["summary"]["baseline_only"] == 0
    assert diff["summary"]["answer_f1_delta_avg"] == pytest.approx(0.3)
    assert diff["summary"]["latency_ms_delta_avg"] == pytest.approx(-300.0)
    assert diff["rows"][0]["sample_id"] == "s1"
    assert diff["rows"][0]["deltas"] == {
        "answer_f1": 0.3,
        "latency_ms": -300.0,
        "token_cost": 0.005,
    }


def test_diff_online_shadow_runs_tracks_unmatched_rows() -> None:
    diff = diff_online_shadow_runs(
        baseline=[{"sample_id": "baseline-only", "evaluators": {}, "latency_ms": 1000, "token_cost": 0.01}],
        candidate=[{"sample_id": "candidate-only", "evaluators": {}, "latency_ms": 800, "token_cost": 0.02}],
    )

    assert diff["summary"]["compared"] == 0
    assert diff["summary"]["candidate_only"] == 1
    assert diff["summary"]["baseline_only"] == 1
    assert diff["candidate_only"] == ["candidate-only"]
    assert diff["baseline_only"] == ["baseline-only"]


def test_build_online_shadow_plan_selects_deterministic_daily_sample() -> None:
    plan_a = build_online_shadow_plan(
        replay_records=[
            {"query_hash": "q1", "dataset_id_hash": "d1", "rag_config": {"top_k": 5}},
            {"query_hash": "q2", "dataset_id_hash": "d1", "rag_config": {"top_k": 5}},
            {"query_hash": "q3", "dataset_id_hash": "d2", "rag_config": {"top_k": 10}},
            {"query_hash": "q4", "dataset_id_hash": "d2", "rag_config": {"top_k": 10}},
        ],
        day_key="2026-04-24",
        sample_size=2,
        baseline_label="baseline@v1",
        candidate_label="candidate@v2",
    )
    plan_b = build_online_shadow_plan(
        replay_records=[
            {"query_hash": "q1", "dataset_id_hash": "d1", "rag_config": {"top_k": 5}},
            {"query_hash": "q2", "dataset_id_hash": "d1", "rag_config": {"top_k": 5}},
            {"query_hash": "q3", "dataset_id_hash": "d2", "rag_config": {"top_k": 10}},
            {"query_hash": "q4", "dataset_id_hash": "d2", "rag_config": {"top_k": 10}},
        ],
        day_key="2026-04-24",
        sample_size=2,
        baseline_label="baseline@v1",
        candidate_label="candidate@v2",
    )

    assert plan_a["schema"] == "mimirq.online_shadow_plan.v1"
    assert plan_a["summary"]["eligible"] == 4
    assert plan_a["summary"]["selected"] == 2
    assert plan_a["sample_ids"] == plan_b["sample_ids"]
    assert plan_a["baseline"]["label"] == "baseline@v1"
    assert plan_a["candidate"]["label"] == "candidate@v2"


def test_build_online_shadow_plan_skips_records_without_replay_keys() -> None:
    plan = build_online_shadow_plan(
        replay_records=[
            {"query_hash": "", "dataset_id_hash": "d1"},
            {"query_hash": "q2", "dataset_id_hash": "d1", "rag_config": {"top_k": 5}},
            {"dataset_id_hash": "d1", "rag_config": {"top_k": 5}},
        ],
        day_key="2026-04-24",
        sample_size=10,
        baseline_label="baseline",
        candidate_label="candidate",
    )

    assert plan["summary"]["eligible"] == 1
    assert plan["summary"]["selected"] == 1
    assert len(plan["samples"]) == 1
    assert plan["samples"][0]["query_hash"] == "q2"
