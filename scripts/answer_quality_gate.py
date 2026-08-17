#!/usr/bin/env python3

import argparse
import json
from pathlib import Path
from typing import Any

_THRESHOLDS_SCHEMA_V1 = "mimirq.answer_quality_thresholds.v1"


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


def _coerce_rule_bound(row: dict[str, Any], cfg_raw: dict[str, Any], key: str) -> None:
    if key not in cfg_raw:
        return
    try:
        row[key] = float(cfg_raw.get(key))
    except Exception:
        return


def _normalize_threshold_rule(cfg_raw: Any) -> dict[str, Any] | None:
    if isinstance(cfg_raw, (int, float)) and not isinstance(cfg_raw, bool):
        return {"min": float(cfg_raw), "required": True}
    if not isinstance(cfg_raw, dict):
        return None
    row: dict[str, Any] = {}
    _coerce_rule_bound(row, cfg_raw, "min")
    _coerce_rule_bound(row, cfg_raw, "max")
    row["required"] = bool(cfg_raw.get("required", True))
    return row if row else None


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
        row = _normalize_threshold_rule(cfg_raw)
        if row is None:
            continue
        out[key] = row
    return out


def evaluate_answer_quality(
    *,
    summary: dict[str, Any],
    thresholds: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    failures: list[str] = []

    for metric, rule in (thresholds or {}).items():
        required = bool(rule.get("required", True))
        raw_value = summary.get(metric)
        value = None
        if raw_value is not None:
            try:
                value = float(raw_value)
            except Exception:
                value = None

        row = {
            "metric": metric,
            "value": value,
            "required": required,
            "min": (float(rule.get("min")) if rule.get("min") is not None else None),
            "max": (float(rule.get("max")) if rule.get("max") is not None else None),
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
        if low is not None and float(value) < float(low):
            row["passed"] = False
            row["reason"] = "lt_min"
            failures.append(f"{metric}: {value:.6f} < min {float(low):.6f}")
        if high is not None and float(value) > float(high):
            row["passed"] = False
            row["reason"] = "gt_max"
            failures.append(f"{metric}: {value:.6f} > max {float(high):.6f}")
        checks.append(row)

    return {
        "schema": "mimirq.answer_quality_gate_report.v1",
        "passed": bool(len(failures) == 0),
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
    if not bool(report.get("passed")):
        print("[answer-quality-gate] FAIL")
        return 2
    print("[answer-quality-gate] PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
