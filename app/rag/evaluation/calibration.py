import math
from dataclasses import dataclass
from typing import TypedDict


@dataclass(frozen=True)
class PlattScaler:
    a: float
    b: float


@dataclass(frozen=True)
class IsotonicCalibrator:
    thresholds: list[float]
    values: list[float]


class _IsotonicBlock(TypedDict):
    start: float
    end: float
    sum: float
    count: int
    mean: float


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def fit_platt_scaler(
    *,
    scores: list[float],
    labels: list[int],
    learning_rate: float = 0.05,
    steps: int = 200,
) -> PlattScaler:
    xs = [float(x) for x in (scores or [])]
    ys = [1.0 if int(y) else 0.0 for y in (labels or [])]
    if len(xs) != len(ys) or not xs:
        return PlattScaler(a=1.0, b=0.0)

    a = 1.0
    b = 0.0
    lr = max(1e-5, float(learning_rate or 0.05))
    for _ in range(max(1, int(steps or 1))):
        grad_a = 0.0
        grad_b = 0.0
        for x, y in zip(xs, ys, strict=False):
            p = _sigmoid((a * x) + b)
            err = p - y
            grad_a += err * x
            grad_b += err
        grad_a /= len(xs)
        grad_b /= len(xs)
        a -= lr * grad_a
        b -= lr * grad_b
    return PlattScaler(a=a, b=b)


def predict_platt_probability(model: PlattScaler, score: float) -> float:
    return _sigmoid((float(model.a) * float(score)) + float(model.b))


def fit_isotonic_calibrator(*, scores: list[float], labels: list[int]) -> IsotonicCalibrator:
    pairs = sorted((float(s), 1.0 if int(y) else 0.0) for s, y in zip(scores or [], labels or [], strict=False))
    if not pairs:
        return IsotonicCalibrator(thresholds=[], values=[])

    blocks: list[_IsotonicBlock] = []
    for score, label in pairs:
        blocks.append({"start": score, "end": score, "sum": label, "count": 1, "mean": label})
        while len(blocks) >= 2 and blocks[-2]["mean"] > blocks[-1]["mean"]:
            right = blocks.pop()
            left = blocks.pop()
            total_sum = left["sum"] + right["sum"]
            total_count = left["count"] + right["count"]
            blocks.append(
                {
                    "start": left["start"],
                    "end": right["end"],
                    "sum": total_sum,
                    "count": total_count,
                    "mean": total_sum / float(total_count),
                }
            )

    thresholds = [block["end"] for block in blocks]
    values = [block["mean"] for block in blocks]
    return IsotonicCalibrator(thresholds=thresholds, values=values)


def predict_isotonic_probability(model: IsotonicCalibrator, score: float) -> float:
    s = float(score)
    if not model.thresholds:
        return 0.0
    for threshold, value in zip(model.thresholds, model.values, strict=False):
        if s <= float(threshold):
            return float(value)
    return float(model.values[-1])


__all__ = [
    "IsotonicCalibrator",
    "PlattScaler",
    "fit_isotonic_calibrator",
    "fit_platt_scaler",
    "predict_isotonic_probability",
    "predict_platt_probability",
]
