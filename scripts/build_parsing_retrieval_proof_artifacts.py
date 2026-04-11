#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def build_parsing_proof_summary(batch_payload: Any) -> dict[str, Any]:
    payload = batch_payload if isinstance(batch_payload, dict) else {}
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    raw_cases = payload.get("cases") if isinstance(payload.get("cases"), list) else []
    cases = [item for item in raw_cases if isinstance(item, dict)]

    case_summaries: list[dict[str, Any]] = []
    failed_cases: list[str] = []
    for case in cases:
        case_summary = case.get("summary") if isinstance(case.get("summary"), dict) else {}
        hit = _coerce_float(case_summary.get("hit_at_k"))
        mrr = _coerce_float(case_summary.get("mrr"))
        case_id = str(case.get("id") or "").strip()
        row = {
            "id": case_id or None,
            "hit_at_k": hit,
            "mrr": mrr,
        }
        case_summaries.append(row)
        if hit < 1.0 or mrr < 1.0:
            failed_cases.append(case_id)

    return {
        "schema": "mimirq.parsing_retrieval_proof_summary.v1",
        "cases_total": int(payload.get("cases_total") or len(cases)),
        "hit_at_k_mean": _coerce_float(summary.get("hit_at_k_mean")),
        "mrr_mean": _coerce_float(summary.get("mrr_mean")),
        "failed_case_ids": [item for item in failed_cases if item],
        "cases": case_summaries,
    }


def build_parsing_proof_report(
    summary_payload: Any,
    *,
    summary_path: str,
    thresholds: dict[str, float],
) -> dict[str, Any]:
    payload = summary_payload if isinstance(summary_payload, dict) else {}
    values = {
        "hit_at_k_mean": _coerce_float(payload.get("hit_at_k_mean")),
        "mrr_mean": _coerce_float(payload.get("mrr_mean")),
    }
    checks = {
        name: {
            "value": values[name],
            "min": float(thresholds[name]),
            "passed": bool(values[name] >= float(thresholds[name])),
        }
        for name in values
    }
    return {
        "schema": "mimirq.parsing_retrieval_proof_report.v1",
        "summary_path": str(summary_path),
        "thresholds": {name: float(value) for name, value in thresholds.items()},
        "checks": checks,
        "failed_case_ids": list(payload.get("failed_case_ids") or []),
        "passed": bool(all(item["passed"] for item in checks.values())),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build deterministic parsing-proof summary/report artifacts from a batch proof report.")
    parser.add_argument("--batch-report", required=True, help="Input parsing proof batch report JSON path.")
    parser.add_argument("--summary-out", required=True, help="Output parsing proof summary JSON path.")
    parser.add_argument("--report-out", required=True, help="Output parsing proof report JSON path.")
    parser.add_argument("--min-hit-at-k-mean", type=float, default=1.0, help="Minimum acceptable hit_at_k_mean.")
    parser.add_argument("--min-mrr-mean", type=float, default=1.0, help="Minimum acceptable mrr_mean.")
    args = parser.parse_args(argv)

    batch_report_path = Path(str(args.batch_report)).expanduser().resolve()
    summary_out_arg = str(args.summary_out)
    report_out_arg = str(args.report_out)
    summary_out_path = Path(summary_out_arg).expanduser()
    report_out_path = Path(report_out_arg).expanduser()
    if not batch_report_path.exists():
        raise SystemExit(f"batch_report_not_found: {batch_report_path}")

    batch_payload = _load_json(batch_report_path)
    summary_payload = build_parsing_proof_summary(batch_payload)
    report_payload = build_parsing_proof_report(
        summary_payload,
        summary_path=summary_out_arg,
        thresholds={
            "hit_at_k_mean": float(args.min_hit_at_k_mean),
            "mrr_mean": float(args.min_mrr_mean),
        },
    )

    summary_out_path.parent.mkdir(parents=True, exist_ok=True)
    summary_out_path.write_text(json.dumps(summary_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report_out_path.parent.mkdir(parents=True, exist_ok=True)
    report_out_path.write_text(json.dumps(report_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[parsing-proof-artifacts] wrote {summary_out_path}")
    print(f"[parsing-proof-artifacts] wrote {report_out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
