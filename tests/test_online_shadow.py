from __future__ import annotations

import pytest

from app.rag.evaluation.online_shadow import diff_online_shadow_runs


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
