from __future__ import annotations


def test_evaluate_online_rollback_trigger_triggers_on_consecutive_degradation() -> None:
    from app.services.ltr_model_registry import evaluate_online_rollback_trigger

    result = evaluate_online_rollback_trigger(
        windows=[
            {"delta.mrr": -0.05, "window": "5m"},
            {"delta.mrr": -0.04, "window": "5m"},
            {"delta.mrr": -0.03, "window": "5m"},
        ],
        metric_key="delta.mrr",
        max_allowed_delta=-0.02,
        min_consecutive_windows=3,
    )

    assert result["schema"] == "mimirq.ltr_online_rollback_trigger.v1"
    assert result["triggered"] is True
    assert result["degraded_consecutive"] == 3
    assert result["metric_key"] == "delta.mrr"


def test_evaluate_online_rollback_trigger_does_not_trigger_for_non_consecutive_degradation() -> None:
    from app.services.ltr_model_registry import evaluate_online_rollback_trigger

    result = evaluate_online_rollback_trigger(
        windows=[
            {"delta.mrr": -0.05, "window": "5m"},
            {"delta.mrr": 0.01, "window": "5m"},
            {"delta.mrr": -0.06, "window": "5m"},
            {"delta.mrr": -0.07, "window": "5m"},
        ],
        metric_key="delta.mrr",
        max_allowed_delta=-0.02,
        min_consecutive_windows=3,
    )

    assert result["triggered"] is False
    assert result["degraded_consecutive"] == 2
    assert any("consecutive" in str(reason) for reason in result["reasons"])


def test_evaluate_online_rollback_trigger_handles_insufficient_windows() -> None:
    from app.services.ltr_model_registry import evaluate_online_rollback_trigger

    result = evaluate_online_rollback_trigger(
        windows=[{"delta.mrr": -0.09, "window": "5m"}],
        metric_key="delta.mrr",
        max_allowed_delta=-0.02,
        min_consecutive_windows=2,
    )

    assert result["triggered"] is False
    assert any("insufficient windows" in str(reason) for reason in result["reasons"])
