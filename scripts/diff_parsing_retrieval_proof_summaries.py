#!/usr/bin/env python3

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError(f"summary root must be object: {path}")
    return obj


def run(*, baseline_path: Path, current_path: Path, out: Path | None, out_md: Path | None) -> dict[str, Any]:
    baseline = _load_json(baseline_path)
    current = _load_json(current_path)

    base_failed = [str(v) for v in (baseline.get("failed_case_ids") or []) if str(v).strip()]
    curr_failed = [str(v) for v in (current.get("failed_case_ids") or []) if str(v).strip()]
    diff = {
        "schema": "mimirq.parsing_retrieval_proof_diff.v1",
        "baseline_path": str(Path(baseline_path).resolve()),
        "current_path": str(Path(current_path).resolve()),
        "metric_deltas": {
            "hit_at_k_mean_delta": round(float(current.get("hit_at_k_mean") or 0.0) - float(baseline.get("hit_at_k_mean") or 0.0), 6),
            "mrr_mean_delta": round(float(current.get("mrr_mean") or 0.0) - float(baseline.get("mrr_mean") or 0.0), 6),
        },
        "failed_case_drift": {
            "added_ids": sorted(set(curr_failed) - set(base_failed)),
            "removed_ids": sorted(set(base_failed) - set(curr_failed)),
            "retained_ids": sorted(set(base_failed) & set(curr_failed)),
        },
    }
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(diff, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if out_md is not None:
        out_md.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "# Parsing Proof Summary Diff",
            "",
            f"- `hit_at_k_mean_delta`: `{diff['metric_deltas']['hit_at_k_mean_delta']}`",
            f"- `mrr_mean_delta`: `{diff['metric_deltas']['mrr_mean_delta']}`",
            f"- Added failed cases: `{', '.join(diff['failed_case_drift']['added_ids'])}`",
            f"- Removed failed cases: `{', '.join(diff['failed_case_drift']['removed_ids'])}`",
            f"- Retained failed cases: `{', '.join(diff['failed_case_drift']['retained_ids'])}`",
            "",
        ]
        out_md.write_text("\n".join(lines), encoding="utf-8")
    return diff


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Diff two broader parsing-proof summary JSON files.")
    parser.add_argument("--a", required=True, help="Baseline summary path")
    parser.add_argument("--b", required=True, help="Current summary path")
    parser.add_argument("--out", default="", help="Optional output JSON path")
    parser.add_argument("--out-md", default="", help="Optional output Markdown path")
    args = parser.parse_args(argv)

    try:
        diff = run(
            baseline_path=Path(args.a),
            current_path=Path(args.b),
            out=Path(args.out) if str(args.out or "").strip() else None,
            out_md=Path(args.out_md) if str(args.out_md or "").strip() else None,
        )
    except Exception as exc:
        print(f"[diff_parsing_retrieval_proof_summaries] ERROR: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(diff, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
