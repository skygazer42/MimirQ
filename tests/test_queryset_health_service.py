from __future__ import annotations

from app.services.queryset_health_service import (
    build_queryset_health_snapshot,
    update_queryset_health_history,
    validate_and_normalize_queryset_health_policy,
)


def test_build_queryset_health_snapshot_includes_profile_hash_and_trend() -> None:
    benchmark_report = {
        "schema": "mimirq.sample_retrieval_benchmark.v1",
        "fixture_hash": "fx123",
        "retrieval_mode": "keyword",
        "top_k": 5,
        "summary": {
            "cases_total": 5,
            "hit_at_k": 0.85,
            "mrr": 0.61,
            "ndcg_at_k": 0.70,
            "avg_latency_ms": 8.2,
            "p95_latency_ms": 15.0,
        },
        "cases": [
            {
                "id": "q-1",
                "question": "where is project roadmap",
                "hit_at_k": 0.0,
                "reciprocal_rank": 0.0,
                "ndcg_at_k": 0.0,
                "latency_ms": 11.0,
            },
            {
                "id": "q-2",
                "question": "how to configure reranker",
                "hit_at_k": 1.0,
                "reciprocal_rank": 0.2,
                "ndcg_at_k": 0.42,
                "latency_ms": 8.2,
            },
            {
                "id": "q-3",
                "question": "enable lexical db",
                "hit_at_k": 1.0,
                "reciprocal_rank": 1.0,
                "ndcg_at_k": 1.0,
                "latency_ms": 4.4,
            },
            {
                "id": "q-4",
                "question": "ltr feature spec v3",
                "hit_at_k": 1.0,
                "reciprocal_rank": 0.111,
                "ndcg_at_k": 0.19,
                "latency_ms": 20.1,
            },
            {
                "id": "q-5",
                "question": "what is retrieval explain",
                "hit_at_k": 1.0,
                "reciprocal_rank": 0.5,
                "ndcg_at_k": 0.72,
                "latency_ms": 7.0,
            },
        ],
    }
    previous = {
        "metrics": {
            "hit_at_k": 0.90,
            "mrr": 0.63,
            "ndcg_at_k": 0.72,
            "p95_latency_ms": 12.0,
        },
        "risk": {
            "miss_rate": 0.0,
            "weak_hit_rate": 0.2,
        },
    }

    snap = build_queryset_health_snapshot(
        benchmark_report=benchmark_report,
        profile_hash="profile-v1",
        previous_snapshot=previous,
        generated_at="2026-03-11T00:00:00Z",
    )

    assert snap.get("schema") == "mimirq.queryset_health_snapshot.v1"
    assert snap.get("profile_hash") == "profile-v1"
    assert snap.get("policy_source") == "default"
    policy_hash = str(snap.get("policy_hash") or "")
    assert len(policy_hash) == 24
    assert snap.get("fixture_hash") == "fx123"
    assert snap.get("retrieval_mode") == "keyword"
    assert int(snap.get("top_k") or 0) == 5
    assert snap.get("metrics", {}).get("hit_at_k") == 0.85

    trend = snap.get("trend") or {}
    assert trend.get("hit_at_k_delta") == -0.05
    assert trend.get("mrr_delta") == -0.02
    assert trend.get("ndcg_at_k_delta") == -0.02
    assert trend.get("p95_latency_ms_delta") == 3.0
    assert trend.get("miss_rate_delta") == 0.2
    assert trend.get("weak_hit_rate_delta") == 0.2
    assert trend.get("policy_changed") is False

    risk = snap.get("risk") or {}
    assert risk.get("miss_count") == 1
    assert risk.get("miss_rate") == 0.2
    assert risk.get("weak_hit_count") == 2
    assert risk.get("weak_hit_rate") == 0.4
    hard_cases = risk.get("hard_cases")
    assert isinstance(hard_cases, list)
    assert [row.get("id") for row in hard_cases[:2]] == ["q-1", "q-4"]

    assert "miss_rate_regression" in (snap.get("degradation_flags") or [])
    assert snap.get("status") in {"degraded", "healthy"}


def test_update_queryset_health_history_appends_and_prunes() -> None:
    history = [
        {"generated_at": "2026-03-09T00:00:00Z", "metrics": {"hit_at_k": 0.80}},
        {"generated_at": "2026-03-10T00:00:00Z", "metrics": {"hit_at_k": 0.82}},
    ]
    current = {"generated_at": "2026-03-11T00:00:00Z", "metrics": {"hit_at_k": 0.81}}

    out = update_queryset_health_history(history=history, current=current, max_items=2)

    assert len(out) == 2
    assert out[0]["generated_at"] == "2026-03-10T00:00:00Z"
    assert out[1]["generated_at"] == "2026-03-11T00:00:00Z"


def test_build_queryset_health_snapshot_applies_custom_risk_policy_thresholds() -> None:
    benchmark_report = {
        "summary": {
            "cases_total": 2,
            "hit_at_k": 0.5,
            "mrr": 0.1,
            "ndcg_at_k": 0.2,
            "avg_latency_ms": 8.0,
            "p95_latency_ms": 12.0,
        },
        "cases": [
            {
                "id": "q-1",
                "question": "miss case",
                "hit_at_k": 0.0,
                "reciprocal_rank": 0.0,
                "ndcg_at_k": 0.0,
                "latency_ms": 11.0,
            },
            {
                "id": "q-2",
                "question": "weak rank case",
                "hit_at_k": 1.0,
                "reciprocal_rank": 0.2,
                "ndcg_at_k": 0.3,
                "latency_ms": 7.0,
            },
        ],
    }
    previous = {
        "metrics": {
            "hit_at_k": 0.5,
            "mrr": 0.1,
            "ndcg_at_k": 0.2,
            "p95_latency_ms": 12.0,
        },
        "risk": {
            "miss_rate": 0.0,
            "weak_hit_rate": 0.0,
        },
    }

    snap = build_queryset_health_snapshot(
        benchmark_report=benchmark_report,
        profile_hash="profile-v2",
        previous_snapshot=previous,
        policy={
            "miss_rate_regression_threshold": 0.75,
            "weak_hit_rr_threshold": 0.15,
            "weak_hit_rate_regression_threshold": 0.6,
        },
    )

    assert snap.get("risk", {}).get("miss_count") == 1
    # rr=0.2 is no longer treated as weak when threshold is 0.15.
    assert snap.get("risk", {}).get("weak_hit_count") == 0
    assert "miss_rate_regression" not in (snap.get("degradation_flags") or [])


def test_validate_and_normalize_queryset_health_policy_rejects_invalid_values() -> None:
    import pytest

    with pytest.raises(ValueError):
        validate_and_normalize_queryset_health_policy({"unknown_key": 1})

    with pytest.raises(ValueError):
        validate_and_normalize_queryset_health_policy({"weak_hit_rr_threshold": 1.5})


def test_build_queryset_health_snapshot_includes_explicit_policy_source() -> None:
    snap = build_queryset_health_snapshot(
        benchmark_report={
            "summary": {
                "cases_total": 1,
                "hit_at_k": 1.0,
                "mrr": 1.0,
                "ndcg_at_k": 1.0,
                "avg_latency_ms": 1.0,
                "p95_latency_ms": 1.0,
            }
        },
        profile_hash="profile-v3",
        policy_source="policy_json+cli_overrides",
    )
    assert snap.get("policy_source") == "policy_json+cli_overrides"
    assert len(str(snap.get("policy_hash") or "")) == 24


def test_build_queryset_health_snapshot_marks_policy_changed_when_hash_differs() -> None:
    prev = {
        "policy_hash": "aaaaaaaaaaaaaaaaaaaaaaaa",
        "metrics": {"hit_at_k": 1.0, "mrr": 1.0, "ndcg_at_k": 1.0, "p95_latency_ms": 1.0},
        "risk": {"miss_rate": 0.0, "weak_hit_rate": 0.0},
    }
    snap = build_queryset_health_snapshot(
        benchmark_report={
            "summary": {
                "cases_total": 1,
                "hit_at_k": 1.0,
                "mrr": 1.0,
                "ndcg_at_k": 1.0,
                "avg_latency_ms": 1.0,
                "p95_latency_ms": 1.0,
            }
        },
        profile_hash="profile-v4",
        previous_snapshot=prev,
        policy={"miss_rate_regression_threshold": 0.2},
    )
    assert snap.get("trend", {}).get("policy_changed") is True
