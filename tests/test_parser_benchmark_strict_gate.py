from scripts.parser_benchmark import evaluate_baseline_compatibility, evaluate_strict_regressions


def test_strict_gate_rejects_an_empty_baseline_summary() -> None:
    result = evaluate_strict_regressions(
        current_summary={"basic": {"ok_rate": 1.0}},
        baseline_summary={},
        max_drop_by_metric={"ok_rate": 0.02},
    )

    assert result["passed"] is False
    assert result["failures"] == ["baseline summary is missing or empty"]


def test_strict_gate_rejects_a_missing_baseline_backend() -> None:
    result = evaluate_strict_regressions(
        current_summary={},
        baseline_summary={"basic": {"ok_rate": 1.0}},
        max_drop_by_metric={"ok_rate": 0.02},
    )

    assert result["passed"] is False
    assert result["failures"] == ["basic backend is missing from the current summary"]


def test_strict_gate_rejects_a_missing_current_metric() -> None:
    result = evaluate_strict_regressions(
        current_summary={"basic": {"ok_rate": 1.0}},
        baseline_summary={"basic": {"ok_rate": 1.0, "parse_score_mean": 0.8}},
        max_drop_by_metric={"ok_rate": 0.02, "parse_score_mean": 0.03},
    )

    assert result["passed"] is False
    assert result["failures"] == ["basic.parse_score_mean is missing from the current summary"]


def test_strict_gate_rejects_a_missing_baseline_metric() -> None:
    result = evaluate_strict_regressions(
        current_summary={"basic": {"ok_rate": 1.0}},
        baseline_summary={"basic": {}},
        max_drop_by_metric={"ok_rate": 0.02},
    )

    assert result["passed"] is False
    assert result["failures"] == ["basic.ok_rate is missing from the baseline summary"]


def test_strict_gate_rejects_malformed_metric_values() -> None:
    result = evaluate_strict_regressions(
        current_summary={"basic": {"ok_rate": "not-a-number"}},
        baseline_summary={"basic": {"ok_rate": 1.0}},
        max_drop_by_metric={"ok_rate": 0.02},
    )

    assert result["passed"] is False
    assert result["failures"] == ["basic.ok_rate has a non-numeric current value"]


def test_strict_gate_rejects_non_finite_metric_values() -> None:
    result = evaluate_strict_regressions(
        current_summary={"basic": {"ok_rate": "NaN"}},
        baseline_summary={"basic": {"ok_rate": 1.0}},
        max_drop_by_metric={"ok_rate": 0.02},
    )

    assert result["passed"] is False
    assert result["failures"] == ["basic.ok_rate has a non-numeric current value"]


def test_strict_gate_rejects_non_finite_thresholds() -> None:
    result = evaluate_strict_regressions(
        current_summary={"basic": {"ok_rate": 1.0}},
        baseline_summary={"basic": {"ok_rate": 1.0}},
        max_drop_by_metric={"ok_rate": float("nan")},
    )

    assert result["passed"] is False
    assert result["failures"] == ["ok_rate has a non-numeric maximum drop"]


def test_strict_gate_rejects_a_malformed_baseline_backend() -> None:
    result = evaluate_strict_regressions(
        current_summary={"basic": {"ok_rate": 1.0}},
        baseline_summary={"basic": "invalid"},
        max_drop_by_metric={"ok_rate": 0.02},
    )

    assert result["passed"] is False
    assert result["failures"] == ["basic backend has an invalid baseline summary"]


def test_strict_gate_rejects_missing_compatibility_hashes() -> None:
    result = evaluate_baseline_compatibility(
        current_report={"fixture_hash": "fixture", "profile_hash": "profile"},
        baseline_report={},
    )

    assert result == {
        "compatible": False,
        "mismatches": [
            "fixture_hash missing from baseline report",
            "profile_hash missing from baseline report",
        ],
    }
