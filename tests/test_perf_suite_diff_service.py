from __future__ import annotations

import importlib.util


def test_perf_suite_diff_service_flags_p95_p99_regressions() -> None:
    assert (
        importlib.util.find_spec("app.services.perf_suite_diff_service") is not None
    ), "perf suite diff service not implemented yet"

    from app.services.perf_suite_diff_service import diff_perf_suite_reports

    baseline = {
        "suite": "perf-v1",
        "cases": [
            {"name": "health", "latency_ms": {"p95": 10.0, "p99": 15.0}},
            {"name": "meta", "latency_ms": {"p95": 12.0, "p99": 18.0}},
        ],
    }
    current = {
        "suite": "perf-v1",
        "cases": [
            {"name": "health", "latency_ms": {"p95": 30.0, "p99": 40.0}},
            {"name": "meta", "latency_ms": {"p95": 12.5, "p99": 18.5}},
        ],
    }
    policy = {
        "schema": "mimirq.perf_regression_policy.v1",
        "default": {
            "max_p95_ratio_increase": 0.5,
            "max_p95_abs_increase_ms": 5.0,
            "max_p99_ratio_increase": 0.5,
            "max_p99_abs_increase_ms": 5.0,
        },
    }

    diff = diff_perf_suite_reports(baseline=baseline, current=current, policy=policy)
    assert diff["schema"] == "mimirq.perf_suite_diff.v1"
    assert diff["strict_gate"]["passed"] is False

    health = diff["cases"]["health"]
    assert health["regressed"] is True
    assert health["p95"]["baseline_ms"] == 10.0
    assert health["p95"]["current_ms"] == 30.0
    assert health["p99"]["baseline_ms"] == 15.0
    assert health["p99"]["current_ms"] == 40.0

    meta = diff["cases"]["meta"]
    assert meta["regressed"] is False

