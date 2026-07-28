#!/usr/bin/env python3

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _load_json(path: Path) -> dict[str, Any]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError("run_payload_not_object")
    return obj


def _run_summary(run: dict[str, Any]) -> dict[str, Any]:
    if isinstance(run.get("summary"), dict):
        return dict(run.get("summary") or {})
    wrapped = run.get("run")
    if isinstance(wrapped, dict) and isinstance(wrapped.get("summary"), dict):
        return dict(wrapped.get("summary") or {})
    return {}


def _run_rows(run: dict[str, Any]) -> list[dict[str, Any]] | None:
    rows = run.get("items")
    if not isinstance(rows, list):
        rows = run.get("results")
    if not isinstance(rows, list) and isinstance(run.get("run"), dict):
        wrapped = run.get("run") or {}
        rows = wrapped.get("items")
        if not isinstance(rows, list):
            rows = wrapped.get("results")
    if not isinstance(rows, list):
        return None
    return [row for row in rows if isinstance(row, dict)]


def _row_metrics(row: dict[str, Any]) -> dict[str, Any]:
    metrics = row.get("metrics")
    return metrics if isinstance(metrics, dict) else {}


def _row_meta(row: dict[str, Any]) -> dict[str, Any]:
    meta = row.get("meta")
    return meta if isinstance(meta, dict) else {}


def _first_non_none(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _coerce_bool_flag(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no"}:
            return False
    return None


def _summary_case_total(summary: dict[str, Any], *keys: str) -> int:
    for key in keys:
        raw = summary.get(key)
        try:
            if raw is not None:
                return int(raw)
        except Exception:
            continue
    progress = summary.get("progress")
    if isinstance(progress, dict):
        try:
            raw_total = progress.get("total_cases")
            if raw_total is not None:
                return int(raw_total)
        except Exception:
            pass
    return 0


def _summary_rate(
    summary: dict[str, Any],
    *,
    rate_key: str,
    passed_keys: tuple[str, ...],
    total_keys: tuple[str, ...],
) -> tuple[float | None, int, int]:
    total = _summary_case_total(summary, *total_keys)
    try:
        rate = float(summary.get(rate_key))
        passed_raw = _first_non_none(*(summary.get(key) for key in passed_keys))
        passed = int(passed_raw if passed_raw is not None else 0)
    except (TypeError, ValueError):
        return None, 0, total
    if total <= 0 or not 0.0 <= rate <= 1.0 or not 0 <= passed <= total:
        return None, 0, total
    return rate, passed, total


def _compute_must_recall_pass_rate(run: dict[str, Any]) -> tuple[float | None, int, int]:
    rows = _run_rows(run)
    if not rows:
        return _summary_rate(
            _run_summary(run),
            rate_key="must_recall_pass_rate",
            passed_keys=("must_recall_passed_cases", "must_recall_cases_passed"),
            total_keys=("total_cases", "must_recall_cases_total"),
        )

    total = len(rows)
    passed = 0
    for row in rows:
        metrics = _row_metrics(row)
        meta = _row_meta(row)
        status = str(
            _first_non_none(
                row.get("must_recall_status"),
                metrics.get("must_recall_status"),
                meta.get("must_recall_status"),
                "",
            )
        ).strip().lower()
        passed_flag = _coerce_bool_flag(
            _first_non_none(
                row.get("must_recall_passed"),
                metrics.get("must_recall_passed"),
                meta.get("must_recall_passed"),
            )
        )
        if passed_flag is None:
            passed_flag = status in {"passed", "partial_miss_recovered"}
        if passed_flag:
            passed += 1
    return float(passed) / float(total), int(passed), int(total)


def _capsule_is_valid(
    capsule: dict[str, Any],
    *,
    strict_integrity: bool,
    require_signature: bool,
) -> bool:
    from app.rag.core.evidence_capsule_builder import validate_evidence_capsule

    ok, _reason = validate_evidence_capsule(
        capsule,
        strict=bool(strict_integrity),
        verify_signature=bool(require_signature),
    )
    if not ok:
        return False
    if not str(capsule.get("capsule_hash") or "").strip():
        return False
    citations = capsule.get("citations")
    if not isinstance(citations, list):
        return False
    for row in citations:
        if not isinstance(row, dict):
            continue
        if not str(row.get("citation_hash") or "").strip():
            return False
    return True


def _compute_provenance_integrity_rate(
    run: dict[str, Any],
    *,
    strict_integrity: bool,
    require_signature: bool,
) -> tuple[float | None, int, int]:
    rows = _run_rows(run)
    if not rows:
        if strict_integrity or require_signature:
            return None, 0, 0
        return _summary_rate(
            _run_summary(run),
            rate_key="provenance_integrity_rate",
            passed_keys=("provenance_passed_cases", "provenance_cases_passed"),
            total_keys=("total_cases", "provenance_cases_total"),
        )

    total = len(rows)
    passed = 0
    for row in rows:
        metrics = _row_metrics(row)
        meta = _row_meta(row)
        capsule = row.get("evidence_capsule")
        if not isinstance(capsule, dict):
            capsule = metrics.get("evidence_capsule")
        if not isinstance(capsule, dict):
            capsule = meta.get("evidence_capsule")
        if isinstance(capsule, dict):
            if _capsule_is_valid(
                capsule,
                strict_integrity=bool(strict_integrity),
                require_signature=bool(require_signature),
            ):
                passed += 1
            continue
        if strict_integrity or require_signature:
            continue
        passed_flag = _coerce_bool_flag(
            _first_non_none(
                row.get("provenance_integrity_passed"),
                metrics.get("provenance_integrity_passed"),
                meta.get("provenance_integrity_passed"),
            )
        )
        if passed_flag:
            passed += 1
    return float(passed) / float(total), int(passed), int(total)


def run_gate(
    *,
    run_json: Path,
    must_recall_min: float,
    provenance_min: float,
    strict_integrity: bool = False,
    require_signature: bool = False,
) -> dict[str, Any]:
    run = _load_json(run_json)
    must_recall_rate, must_recall_passed, total_cases = _compute_must_recall_pass_rate(run)
    provenance_rate, provenance_passed, provenance_total = _compute_provenance_integrity_rate(
        run,
        strict_integrity=bool(strict_integrity),
        require_signature=bool(require_signature),
    )

    failures: list[str] = []
    if must_recall_rate is None:
        failures.append("missing_must_recall_pass_rate")
    elif must_recall_rate < float(must_recall_min):
        failures.append("must_recall_pass_rate_below_threshold")
    if provenance_rate is None:
        failures.append("missing_provenance_integrity_rate")
    elif provenance_rate < float(provenance_min):
        failures.append("provenance_integrity_rate_below_threshold")

    return {
        "schema": "mimirq.must_recall_provenance_gate.v1",
        "run_json": str(run_json),
        "thresholds": {
            "must_recall_pass_rate_min": float(must_recall_min),
            "provenance_integrity_rate_min": float(provenance_min),
            "strict_integrity": bool(strict_integrity),
            "require_signature": bool(require_signature),
        },
        "summary": {
            "total_cases": max(int(total_cases), int(provenance_total)),
            "must_recall_passed_cases": int(must_recall_passed),
            "must_recall_pass_rate": must_recall_rate,
            "provenance_passed_cases": int(provenance_passed),
            "provenance_integrity_rate": provenance_rate,
        },
        "passed": bool(len(failures) == 0),
        "failures": failures,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="One-shot gate for must-recall and provenance integrity.")
    ap.add_argument("--run-json", required=True, help="Regression run detail JSON path")
    ap.add_argument("--must-recall-min", type=float, default=1.0, help="Minimum acceptable must_recall_pass_rate")
    ap.add_argument("--provenance-min", type=float, default=1.0, help="Minimum acceptable provenance_integrity_rate")
    ap.add_argument("--strict-integrity", action="store_true", help="Require strict capsule hash/citation integrity")
    ap.add_argument("--require-signature", action="store_true", help="Require signed evidence capsule")
    ap.add_argument("--out", default="", help="Optional output JSON path")
    ap.add_argument("--compact", action="store_true", help="Print compact JSON")
    args = ap.parse_args(argv)

    try:
        result = run_gate(
            run_json=Path(str(args.run_json)).resolve(),
            must_recall_min=float(args.must_recall_min),
            provenance_min=float(args.provenance_min),
            strict_integrity=bool(args.strict_integrity),
            require_signature=bool(args.require_signature),
        )
    except Exception as exc:
        print(f"[must_recall_provenance_gate] ERROR: {exc}", file=sys.stderr)
        return 1

    if str(args.out or "").strip():
        out_path = Path(str(args.out)).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.compact:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))

    return 0 if bool(result.get("passed")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
