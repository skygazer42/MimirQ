from __future__ import annotations


def test_fit_platt_scaler_returns_monotonic_probabilities() -> None:
    from app.rag.evaluation.calibration import fit_platt_scaler, predict_platt_probability

    model = fit_platt_scaler(scores=[-2.0, -1.0, 1.0, 2.0], labels=[0, 0, 1, 1], learning_rate=0.1, steps=200)

    low = predict_platt_probability(model, -1.5)
    high = predict_platt_probability(model, 1.5)

    assert 0.0 <= low <= 1.0
    assert 0.0 <= high <= 1.0
    assert high > low


def test_fit_isotonic_calibrator_builds_non_decreasing_mapping() -> None:
    from app.rag.evaluation.calibration import fit_isotonic_calibrator, predict_isotonic_probability

    model = fit_isotonic_calibrator(scores=[0.1, 0.2, 0.8, 0.9], labels=[0, 0, 1, 1])

    low = predict_isotonic_probability(model, 0.15)
    high = predict_isotonic_probability(model, 0.85)

    assert 0.0 <= low <= 1.0
    assert 0.0 <= high <= 1.0
    assert high >= low
