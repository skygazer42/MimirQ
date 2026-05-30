"""Case-paired statistics for RAGAS regression run diffs."""

from __future__ import annotations

import hashlib
import math
import statistics
from collections.abc import Iterable, Mapping
from typing import Any


def _get_value(item: Any, key: str) -> Any:
    if isinstance(item, Mapping):
        return item.get(key)
    return getattr(item, key, None)


def _scores(item: Any) -> dict[str, Any]:
    raw = _get_value(item, "scores")
    return dict(raw) if isinstance(raw, Mapping) else {}


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _deterministic_bootstrap_index(metric_key: str, iteration: int, offset: int, size: int) -> int:
    digest = hashlib.sha256(f"{metric_key}:{iteration}:{offset}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % size


def _case_id(item: Any) -> str:
    return str(_get_value(item, "case_id") or "").strip()


def _infer_metric_keys(base_items: Iterable[Any], target_items: Iterable[Any]) -> list[str]:
    keys: set[str] = set()
    for item in [*base_items, *target_items]:
        for key, value in _scores(item).items():
            if _as_float(value) is not None:
                keys.add(str(key))
    return sorted(keys)


def _mean(values: list[float]) -> float | None:
    return round(float(sum(values) / len(values)), 6) if values else None


def _sample_stdev(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    return float(statistics.stdev(values))


def _paired_t_p_value(deltas: list[float]) -> float | None:
    if len(deltas) < 2:
        return None
    mean_delta = float(sum(deltas) / len(deltas))
    stdev = _sample_stdev(deltas)
    if stdev is None or stdev <= 0:
        return 1.0 if abs(mean_delta) <= 1e-12 else 0.0
    z = abs(mean_delta / (stdev / math.sqrt(len(deltas))))
    return round(float(math.erfc(z / math.sqrt(2.0))), 6)


def _rank_abs_deltas(deltas: list[float]) -> list[tuple[float, float]]:
    non_zero = [(delta, abs(delta)) for delta in deltas if abs(delta) > 1e-12]
    non_zero.sort(key=lambda item: item[1])
    ranked: list[tuple[float, float]] = []
    index = 0
    while index < len(non_zero):
        end = index + 1
        while end < len(non_zero) and abs(non_zero[end][1] - non_zero[index][1]) <= 1e-12:
            end += 1
        rank = (index + 1 + end) / 2.0
        for pos in range(index, end):
            ranked.append((non_zero[pos][0], rank))
        index = end
    return ranked


def _wilcoxon_p_value(deltas: list[float]) -> float | None:
    ranked = _rank_abs_deltas(deltas)
    if not ranked:
        return 1.0
    total_rank = sum(rank for _delta, rank in ranked)
    positive_rank = sum(rank for delta, rank in ranked if delta > 0)
    observed = min(positive_rank, total_rank - positive_rank)

    if len(ranked) <= 15:
        count = 0
        extreme = 0
        ranks = [rank for _delta, rank in ranked]
        for mask in range(1 << len(ranks)):
            signed = sum(rank for idx, rank in enumerate(ranks) if mask & (1 << idx))
            if min(signed, total_rank - signed) <= observed + 1e-12:
                extreme += 1
            count += 1
        return round(float(extreme / count), 6)

    mean = total_rank / 2.0
    variance = sum(rank * rank for _delta, rank in ranked) / 4.0
    if variance <= 0:
        return None
    z = abs(positive_rank - mean) / math.sqrt(variance)
    return round(float(math.erfc(z / math.sqrt(2.0))), 6)


def _mcnemar_p_value(pairs: list[tuple[float, float]]) -> float | None:
    binary_pairs = [
        (int(base > 0), int(target > 0))
        for base, target in pairs
        if base in {0.0, 1.0} and target in {0.0, 1.0}
    ]
    if not binary_pairs:
        return None
    base_wrong_target_right = sum(1 for base, target in binary_pairs if base == 0 and target == 1)
    base_right_target_wrong = sum(1 for base, target in binary_pairs if base == 1 and target == 0)
    discordant = base_wrong_target_right + base_right_target_wrong
    if discordant == 0:
        return 1.0
    chi_square = (abs(base_wrong_target_right - base_right_target_wrong) - 1.0) ** 2 / discordant
    return round(float(math.erfc(math.sqrt(max(0.0, chi_square) / 2.0))), 6)


def _bootstrap_ci(metric_key: str, deltas: list[float], iterations: int) -> tuple[float | None, float | None]:
    if not deltas:
        return None, None
    if len(deltas) == 1:
        value = round(float(deltas[0]), 6)
        return value, value
    iterations = max(50, min(int(iterations or 0), 5000))
    means: list[float] = []
    for iteration in range(iterations):
        sample = [
            deltas[_deterministic_bootstrap_index(metric_key, iteration, offset, len(deltas))]
            for offset in range(len(deltas))
        ]
        means.append(sum(sample) / len(sample))
    means.sort()
    low_idx = max(0, min(len(means) - 1, int(math.floor(0.025 * (len(means) - 1)))))
    high_idx = max(0, min(len(means) - 1, int(math.ceil(0.975 * (len(means) - 1)))))
    return round(float(means[low_idx]), 6), round(float(means[high_idx]), 6)


def _bh_adjust(rows: list[dict[str, Any]]) -> None:
    indexed = [
        (idx, float(row["p_value"]))
        for idx, row in enumerate(rows)
        if row.get("p_value") is not None and math.isfinite(float(row["p_value"]))
    ]
    if not indexed:
        return
    indexed.sort(key=lambda item: item[1])
    total = len(indexed)
    adjusted_by_index: dict[int, float] = {}
    running = 1.0
    for rank, (idx, p_value) in reversed(list(enumerate(indexed, start=1))):
        running = min(running, p_value * total / rank)
        adjusted_by_index[idx] = round(float(min(1.0, running)), 6)
    for idx, value in adjusted_by_index.items():
        rows[idx]["p_value_bh"] = value
        rows[idx]["significant"] = value < 0.05


def compare_regression_items(
    *,
    base_items: Iterable[Any],
    target_items: Iterable[Any],
    metric_keys: list[str] | None = None,
    bootstrap_iterations: int = 1000,
    max_case_diffs: int = 500,
) -> dict[str, Any]:
    """Compare two run item collections by case_id and return per-metric/per-case diffs."""
    base_list = list(base_items or [])
    target_list = list(target_items or [])
    base_by_case = {_case_id(item): item for item in base_list if _case_id(item)}
    target_by_case = {_case_id(item): item for item in target_list if _case_id(item)}
    case_ids = sorted(set(base_by_case) & set(target_by_case))
    keys = list(metric_keys or []) or _infer_metric_keys(base_list, target_list)

    significance: list[dict[str, Any]] = []
    metric_pairs: dict[str, list[tuple[float, float]]] = {}
    for key in keys:
        pairs: list[tuple[float, float]] = []
        for case_id in case_ids:
            base_value = _as_float(_scores(base_by_case[case_id]).get(key))
            target_value = _as_float(_scores(target_by_case[case_id]).get(key))
            if base_value is None or target_value is None:
                continue
            pairs.append((base_value, target_value))
        if not pairs:
            continue

        metric_pairs[key] = pairs
        base_values = [base for base, _target in pairs]
        target_values = [target for _base, target in pairs]
        deltas = [target - base for base, target in pairs]
        delta_mean = float(sum(deltas) / len(deltas))
        stdev = _sample_stdev(deltas)
        ci_low, ci_high = _bootstrap_ci(key, deltas, bootstrap_iterations)
        significance.append(
            {
                "key": key,
                "compared": len(pairs),
                "base_mean": _mean(base_values),
                "target_mean": _mean(target_values),
                "delta_mean": round(delta_mean, 6),
                "bootstrap_ci_low": ci_low,
                "bootstrap_ci_high": ci_high,
                "p_value": _paired_t_p_value(deltas),
                "p_value_method": "paired_t_normal_approx",
                "p_value_bh": None,
                "wilcoxon_p_value": _wilcoxon_p_value(deltas),
                "mcnemar_p_value": _mcnemar_p_value(pairs),
                "cohen_d": None if stdev is None or stdev <= 0 else round(float(delta_mean / stdev), 6),
                "significant": False,
            }
        )
    _bh_adjust(significance)

    case_diffs: list[dict[str, Any]] = []
    for case_id in case_ids[: max(0, int(max_case_diffs or 0))]:
        base_item = base_by_case[case_id]
        target_item = target_by_case[case_id]
        metric_diffs: list[dict[str, Any]] = []
        deltas: list[float] = []
        for key in keys:
            base_value = _as_float(_scores(base_item).get(key))
            target_value = _as_float(_scores(target_item).get(key))
            if base_value is None or target_value is None:
                continue
            delta = round(float(target_value - base_value), 6)
            deltas.append(delta)
            metric_diffs.append({"key": key, "before": base_value, "after": target_value, "delta": delta})
        mean_delta = _mean(deltas)
        label = "无分数"
        if mean_delta is not None:
            label = "改善" if mean_delta > 0.05 else "退化" if mean_delta < -0.05 else "无明显变化"
        case_diffs.append(
            {
                "case_id": case_id,
                "question": str(_get_value(target_item, "question") or _get_value(base_item, "question") or ""),
                "metric_diffs": metric_diffs,
                "mean_delta": mean_delta,
                "label": label,
            }
        )

    return {
        "significance": significance,
        "case_diffs": case_diffs,
        "summary": {
            "paired_cases": len(case_ids),
            "metrics_compared": len(significance),
            "bh_corrected": True,
        },
    }


__all__ = ["compare_regression_items"]
