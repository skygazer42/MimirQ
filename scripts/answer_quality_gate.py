#!/usr/bin/env python3

import argparse
import json
import math
from pathlib import Path
from typing import Any, NotRequired, TypedDict

_THRESHOLDS_SCHEMA_V1 = "mimirq.answer_quality_thresholds.v1"


class _MetricCheck(TypedDict):
    metric: str
    value: float | None
    required: bool
    min: float | None
    max: float | None
    passed: bool
    reason: str | None


class _GateReport(TypedDict):
    schema: str
    passed: bool
    checks: list[_MetricCheck]
    failures: list[str]
    input: NotRequired[str]
    thresholds: NotRequired[str]


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def extract_summary(payload: Any) -> dict[str, Any]:
    """
    Extract summary payload from different artifact shapes.

    Supported:
    - {"summary": {...}}
    - {"run": {"summary": {...}}}
    - {...} (already a summary-like dict)
    """
    if not isinstance(payload, dict):
        return {}
    if isinstance(payload.get("summary"), dict):
        return dict(payload.get("summary") or {})
    run = payload.get("run")
    if isinstance(run, dict) and isinstance(run.get("summary"), dict):
        return dict(run.get("summary") or {})
    return dict(payload)


def _validate_threshold_schema(obj: dict[str, Any]) -> None:
    schema = str(obj.get("schema") or "").strip()
    if schema not in {"", _THRESHOLDS_SCHEMA_V1}:
        raise ValueError(f"invalid_threshold_schema: expected {_THRESHOLDS_SCHEMA_V1}, got {schema}")


def _finite_float(raw: Any) -> float | None:
    try:
        value = float(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if math.isfinite(value) else None


def _threshold_bound(metric: str, rule: dict[str, Any], bound: str) -> float | None:
    if bound not in rule:
        return None
    value = _finite_float(rule[bound])
    if value is None:
        raise ValueError(f"invalid_threshold_bound: {metric}.{bound} must be a finite number")
    return value


def _normalize_threshold_rule(metric: str, cfg_raw: Any) -> dict[str, Any] | None:
    if isinstance(cfg_raw, (int, float)) and not isinstance(cfg_raw, bool):
        cfg_raw = {"min": cfg_raw}
    if not isinstance(cfg_raw, dict):
        return None
    row: dict[str, Any] = {}
    for bound in ("min", "max"):
        value = _threshold_bound(metric, cfg_raw, bound)
        if value is not None:
            row[bound] = value
    row["required"] = bool(cfg_raw.get("required", True))
    return row


def normalize_thresholds(payload: Any) -> dict[str, dict[str, Any]]:
    obj = payload if isinstance(payload, dict) else {}
    _validate_threshold_schema(obj)
    raw = obj.get("metrics")
    raw = raw if isinstance(raw, dict) else obj
    out: dict[str, dict[str, Any]] = {}
    for metric, cfg_raw in (raw or {}).items():
        key = str(metric or "").strip()
        if not key:
            continue
        row = _normalize_threshold_rule(key, cfg_raw)
        if row is None:
            continue
        out[key] = row
    return out


def evaluate_answer_quality(
    *,
    summary: dict[str, Any],
    thresholds: dict[str, dict[str, Any]],
) -> _GateReport:
    checks: list[_MetricCheck] = []
    failures: list[str] = []

    for metric, rule in (thresholds or {}).items():
        required = bool(rule.get("required", True))
        value = _finite_float(summary.get(metric))

        row: _MetricCheck = {
            "metric": metric,
            "value": value,
            "required": required,
            "min": _threshold_bound(metric, rule, "min"),
            "max": _threshold_bound(metric, rule, "max"),
            "passed": True,
            "reason": None,
        }

        if value is None:
            if required:
                row["passed"] = False
                row["reason"] = "missing_metric"
                failures.append(f"{metric}: missing")
            checks.append(row)
            continue

        low = row["min"]
        high = row["max"]
        if low is not None and value < low:
            row["passed"] = False
            row["reason"] = "lt_min"
            failures.append(f"{metric}: {value:.6f} < min {low:.6f}")
        if high is not None and value > high:
            row["passed"] = False
            row["reason"] = "gt_max"
            failures.append(f"{metric}: {value:.6f} > max {high:.6f}")
        checks.append(row)

    return {
        "schema": "mimirq.answer_quality_gate_report.v1",
        "passed": len(failures) == 0,
        "checks": checks,
        "failures": failures,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Deterministic answer-quality gate.")
    parser.add_argument("--input", required=True, help="Input JSON containing summary metrics.")
    parser.add_argument("--thresholds", required=True, help="Thresholds JSON path.")
    parser.add_argument("--out", default="artifacts/answer_quality.gate.json", help="Output gate report JSON path.")
    args = parser.parse_args(argv)

    input_path = Path(str(args.input)).expanduser().resolve()
    thresholds_path = Path(str(args.thresholds)).expanduser().resolve()
    out_path = Path(str(args.out)).expanduser().resolve()

    if not input_path.exists():
        raise SystemExit(f"input_not_found: {input_path}")
    if not thresholds_path.exists():
        raise SystemExit(f"thresholds_not_found: {thresholds_path}")

    payload = _load_json(input_path)
    summary = extract_summary(payload)
    thresholds = normalize_thresholds(_load_json(thresholds_path))
    report = evaluate_answer_quality(summary=summary, thresholds=thresholds)
    report["input"] = str(input_path)
    report["thresholds"] = str(thresholds_path)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[answer-quality-gate] wrote {out_path}")
    if not report["passed"]:
        print("[answer-quality-gate] FAIL")
        return 2
    print("[answer-quality-gate] PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
