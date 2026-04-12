#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    obj = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(obj, dict):
        raise ValueError(f"expected object: {path}")
    return obj


def build_review_markdown(
    *,
    summary: dict[str, Any],
    report: dict[str, Any],
    gate: dict[str, Any],
    diff: dict[str, Any],
) -> str:
    checks = report.get("checks") if isinstance(report.get("checks"), list) else []
    lines: list[str] = []
    lines.append("# Parsing Proof Review")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- `cases_total`: `{summary.get('cases_total')}`")
    lines.append(f"- `hit_at_k_mean`: `{summary.get('hit_at_k_mean')}`")
    lines.append(f"- `mrr_mean`: `{summary.get('mrr_mean')}`")
    lines.append(f"- `failed_case_ids`: `{', '.join(summary.get('failed_case_ids') or [])}`")
    lines.append("")
    lines.append("## Threshold Checks")
    lines.append("")
    if checks:
        for item in checks:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"- `{item.get('metric')}`: value=`{item.get('value')}` min=`{item.get('min')}` passed=`{item.get('passed')}`"
            )
    else:
        lines.append("- None")
    lines.append("")
    lines.append("## Baseline Drift")
    lines.append("")
    metric_deltas = diff.get("metric_deltas") if isinstance(diff.get("metric_deltas"), dict) else {}
    failed_drift = diff.get("failed_case_drift") if isinstance(diff.get("failed_case_drift"), dict) else {}
    lines.append(f"- `hit_at_k_mean_delta`: `{metric_deltas.get('hit_at_k_mean_delta')}`")
    lines.append(f"- `mrr_mean_delta`: `{metric_deltas.get('mrr_mean_delta')}`")
    lines.append(f"- Added failed cases: `{', '.join(failed_drift.get('added_ids') or [])}`")
    lines.append(f"- Removed failed cases: `{', '.join(failed_drift.get('removed_ids') or [])}`")
    lines.append("")
    lines.append("## Gate")
    lines.append("")
    lines.append(f"- `passed`: `{gate.get('passed')}`")
    lines.append(f"- `failures`: `{', '.join(gate.get('failures') or [])}`")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a human-readable parsing-proof review markdown from summary/report/gate/diff artifacts.")
    parser.add_argument("--summary", required=True, help="Parsing proof summary JSON path.")
    parser.add_argument("--report", required=True, help="Parsing proof report JSON path.")
    parser.add_argument("--gate", required=True, help="Parsing proof gate JSON path.")
    parser.add_argument("--diff", required=True, help="Parsing proof diff JSON path.")
    parser.add_argument("--out", required=True, help="Output Markdown path.")
    args = parser.parse_args(argv)

    summary = _load_json(Path(str(args.summary)).resolve())
    report = _load_json(Path(str(args.report)).resolve())
    gate = _load_json(Path(str(args.gate)).resolve())
    diff = _load_json(Path(str(args.diff)).resolve())
    out_path = Path(str(args.out)).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(build_review_markdown(summary=summary, report=report, gate=gate, diff=diff), encoding="utf-8")
    print(f"[parsing-proof-review] wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
