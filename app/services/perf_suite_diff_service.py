
import math
from typing import Any

PERF_SUITE_DIFF_SCHEMA_V1 = "mimirq.perf_suite_diff.v1"
PERF_REGRESSION_POLICY_SCHEMA_V1 = "mimirq.perf_regression_policy.v1"


def _as_float(value: Any) -> float | None:
    try:
        v = float(value)
    except Exception:
        return None
    if math.isnan(v):  # NaN
        return None
    return v


def _policy_block(policy: dict[str, Any] | None, *, case_name: str) -> dict[str, Any]:
    if not isinstance(policy, dict):
        return {}
    by_case = policy.get("cases") if isinstance(policy.get("cases"), dict) else {}
    case_cfg = by_case.get(case_name) if isinstance(by_case.get(case_name), dict) else {}
    default_cfg = policy.get("default") if isinstance(policy.get("default"), dict) else {}
    merged = dict(default_cfg)
    merged.update(case_cfg)
    return merged


def _threshold(cfg: dict[str, Any], key: str, default: float) -> float:
    v = _as_float(cfg.get(key))
    if v is None:
        return float(default)
    return float(v)


def _compare_metric(
    *,
    baseline_ms: float | None,
    current_ms: float | None,
    max_ratio_increase: float,
    max_abs_increase_ms: float,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "baseline_ms": baseline_ms,
        "current_ms": current_ms,
        "delta_ms": None,
        "delta_ratio": None,
        "regressed": False,
    }
    if baseline_ms is None or current_ms is None:
        return out

    delta_ms = float(current_ms - baseline_ms)
    out["delta_ms"] = delta_ms

    ratio = None
    if baseline_ms > 0:
        ratio = float((current_ms / baseline_ms) - 1.0)
        out["delta_ratio"] = ratio

    regressed = bool(delta_ms > float(max_abs_increase_ms) and (ratio is not None and ratio > float(max_ratio_increase)))
    out["regressed"] = regressed
    return out


def _cases_by_name(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = report.get("cases") if isinstance(report.get("cases"), list) else []
    out: dict[str, dict[str, Any]] = {}
    for row in raw:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        out[name] = row
    return out


def diff_perf_suite_reports(
    *,
    baseline: dict[str, Any],
    current: dict[str, Any],
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Diff two perf suite reports and flag p95/p99 latency regressions.

    This is intended for CI/nightly gating. It is PII-safe by construction: only numeric
    aggregates and case names are included in the diff.
    """
    base_cases = _cases_by_name(baseline or {})
    curr_cases = _cases_by_name(current or {})

    case_names = sorted(set(base_cases.keys()) | set(curr_cases.keys()))
    cases_out: dict[str, Any] = {}
    regressions = 0

    for name in case_names:
        cfg = _policy_block(policy, case_name=name)
        p95_ratio = _threshold(cfg, "max_p95_ratio_increase", 0.5)
        p95_abs = _threshold(cfg, "max_p95_abs_increase_ms", 50.0)
        p99_ratio = _threshold(cfg, "max_p99_ratio_increase", 0.5)
        p99_abs = _threshold(cfg, "max_p99_abs_increase_ms", 100.0)

        b_row = base_cases.get(name) or {}
        c_row = curr_cases.get(name) or {}

        b_lat = b_row.get("latency_ms") if isinstance(b_row.get("latency_ms"), dict) else {}
        c_lat = c_row.get("latency_ms") if isinstance(c_row.get("latency_ms"), dict) else {}

        b_p95 = _as_float(b_lat.get("p95"))
        c_p95 = _as_float(c_lat.get("p95"))
        b_p99 = _as_float(b_lat.get("p99"))
        c_p99 = _as_float(c_lat.get("p99"))

        p95 = _compare_metric(
            baseline_ms=b_p95,
            current_ms=c_p95,
            max_ratio_increase=p95_ratio,
            max_abs_increase_ms=p95_abs,
        )
        p99 = _compare_metric(
            baseline_ms=b_p99,
            current_ms=c_p99,
            max_ratio_increase=p99_ratio,
            max_abs_increase_ms=p99_abs,
        )

        regressed = bool(p95.get("regressed") or p99.get("regressed"))
        if regressed:
            regressions += 1

        cases_out[name] = {
            "name": name,
            "regressed": regressed,
            "p95": p95,
            "p99": p99,
        }

    strict_gate = {"passed": regressions == 0, "regressions": int(regressions)}

    return {
        "schema": PERF_SUITE_DIFF_SCHEMA_V1,
        "baseline_suite": str((baseline or {}).get("suite") or ""),
        "current_suite": str((current or {}).get("suite") or ""),
        "policy_schema": str((policy or {}).get("schema") or PERF_REGRESSION_POLICY_SCHEMA_V1),
        "strict_gate": strict_gate,
        "cases": cases_out,
    }


__all__ = [
    "PERF_REGRESSION_POLICY_SCHEMA_V1",
    "PERF_SUITE_DIFF_SCHEMA_V1",
    "diff_perf_suite_reports",
]

