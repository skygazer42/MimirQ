from __future__ import annotations

from app.services.queryset_health_diff_service import diff_queryset_health_snapshots


def test_queryset_health_diff_service_reports_metric_policy_and_hard_case_drift() -> None:
    baseline = {
        "schema": "mimirq.queryset_health_snapshot.v1",
        "policy_hash": "aaaaaaaaaaaaaaaaaaaaaaaa",
        "policy_source": "policy_json",
        "metrics": {
            "hit_at_k": 0.8,
            "mrr": 0.5,
            "ndcg_at_k": 0.6,
            "p95_latency_ms": 10.0,
        },
        "risk": {
            "miss_rate": 0.1,
            "weak_hit_rate": 0.2,
            "hard_cases": [{"id": "q-1"}, {"id": "q-2"}],
        },
        "degradation_flags": ["mrr_drop"],
    }
    current = {
        "schema": "mimirq.queryset_health_snapshot.v1",
        "policy_hash": "bbbbbbbbbbbbbbbbbbbbbbbb",
        "policy_source": "policy_json+cli_overrides",
        "metrics": {
            "hit_at_k": 0.75,
            "mrr": 0.45,
            "ndcg_at_k": 0.62,
            "p95_latency_ms": 13.5,
        },
        "risk": {
            "miss_rate": 0.2,
            "weak_hit_rate": 0.25,
            "hard_cases": [{"id": "q-2"}, {"id": "q-3"}],
        },
        "degradation_flags": ["mrr_drop", "miss_rate_regression"],
    }

    out = diff_queryset_health_snapshots(baseline, current, max_hard_case_ids=10)
    assert out.get("schema") == "mimirq.queryset_health_diff.v1"
    assert out.get("policy", {}).get("changed") is True
    assert out.get("policy", {}).get("baseline_hash") == "aaaaaaaaaaaaaaaaaaaaaaaa"
    assert out.get("policy", {}).get("current_hash") == "bbbbbbbbbbbbbbbbbbbbbbbb"

    deltas = out.get("metric_deltas") or {}
    assert deltas.get("hit_at_k_delta") == -0.05
    assert deltas.get("mrr_delta") == -0.05
    assert deltas.get("p95_latency_ms_delta") == 3.5
    assert deltas.get("miss_rate_delta") == 0.1
    assert deltas.get("weak_hit_rate_delta") == 0.05

    hard_cases = out.get("hard_case_drift") or {}
    assert hard_cases.get("added_ids") == ["q-3"]
    assert hard_cases.get("removed_ids") == ["q-1"]
    assert hard_cases.get("retained_ids") == ["q-2"]
