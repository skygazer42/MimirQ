from __future__ import annotations

from app.services.queryset_health_service import (
    build_queryset_health_snapshot,
    update_queryset_health_history,
)


def test_build_queryset_health_snapshot_includes_profile_hash_and_trend() -> None:
    benchmark_report = {
        "schema": "mimirq.sample_retrieval_benchmark.v1",
        "fixture_hash": "fx123",
        "retrieval_mode": "keyword",
        "top_k": 5,
        "summary": {
            "cases_total": 20,
            "hit_at_k": 0.85,
            "mrr": 0.61,
            "ndcg_at_k": 0.70,
            "avg_latency_ms": 8.2,
            "p95_latency_ms": 15.0,
        },
    }
    previous = {
        "metrics": {
            "hit_at_k": 0.90,
            "mrr": 0.63,
            "ndcg_at_k": 0.72,
            "p95_latency_ms": 12.0,
        }
    }

    snap = build_queryset_health_snapshot(
        benchmark_report=benchmark_report,
        profile_hash="profile-v1",
        previous_snapshot=previous,
        generated_at="2026-03-11T00:00:00Z",
    )

    assert snap.get("schema") == "mimirq.queryset_health_snapshot.v1"
    assert snap.get("profile_hash") == "profile-v1"
    assert snap.get("fixture_hash") == "fx123"
    assert snap.get("retrieval_mode") == "keyword"
    assert int(snap.get("top_k") or 0) == 5
    assert snap.get("metrics", {}).get("hit_at_k") == 0.85

    trend = snap.get("trend") or {}
    assert trend.get("hit_at_k_delta") == -0.05
    assert trend.get("mrr_delta") == -0.02
    assert trend.get("ndcg_at_k_delta") == -0.02
    assert trend.get("p95_latency_ms_delta") == 3.0
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
